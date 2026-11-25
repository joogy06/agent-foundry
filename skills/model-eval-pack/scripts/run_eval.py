#!/usr/bin/env python3
"""model-eval-pack runner: run the case files against one or more models and score them.

Stdlib only. Every case runs in a fresh scratch workspace; scoring is deterministic
(no model grades another). Results: <out>/results.jsonl, <out>/scorecard.md, <out>/raw/.

  python3 run_eval.py --model gemini-4-argon-high --model claude:consultant_main \\
      --category deliberation --repeat 3

A `--model` value may carry a provider prefix: `agy:<slug>`, `codex:<role>`, `claude:<role>`.
A bare value uses `--provider` (default agy). codex and claude models are seat ROLES resolved
through skills/_meta/seat_model.py; a literal slug is refused for them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import unicodedata
import urllib.error
import urllib.request
import secrets
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
CASES_DIR = PACK / "cases"
FIXTURE_SKILLS = PACK / "fixtures" / "skills"
# The installed pack sits beside _meta (~/.claude/skills/_meta); in the repo it is skills/_meta.
META = PACK.parent / "_meta"
MODES = ("sandbox", "skip_perms", "no_slash")
STATUSES = ("ok", "timeout", "error", "skipped_quota", "skipped_cap", "cancelled")
# Statuses that are a gap in the run, never a model failure: excluded from every denominator.
UNSCORED = {"skipped_quota": "quota", "skipped_cap": "cap", "cancelled": "cancelled"}
RC_CANCELLED = -4
_TURN_REF = re.compile(r"\{turn(\d+)\}")
_ROLE_RE = re.compile(r"^[a-z][a-z_]{0,40}$")
#: A literal claude model id, accepted only with --measure-literal (measurement, never a seat).
_CLAUDE_LITERAL_RE = re.compile(r"^claude-[a-z]+-\d+(-\d+)*$")
#: The usage fields a claude row sums across turns.
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
              "output_tokens", "thinking_tokens", "cost_usd")


def parse_claude_json(stdout: str) -> tuple[str, dict | None, bool]:
    """`claude --output-format json` -> (answer text, usage, is_error). Unparseable output is
    returned as-is with no usage, so a scorer sees what the CLI printed."""
    try:
        doc = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return stdout, None, False
    if not isinstance(doc, dict):
        return stdout, None, False
    u = doc.get("usage") or {}
    usage = {k: int(u.get(k) or 0) for k in USAGE_KEYS[:4]}
    usage["thinking_tokens"] = int((u.get("output_tokens_details") or {}).get("thinking_tokens") or 0)
    usage["cost_usd"] = float(doc.get("total_cost_usd") or 0.0)
    return str(doc.get("result") or ""), usage, bool(doc.get("is_error"))


def add_usage(total: dict | None, more: dict | None) -> dict | None:
    if more is None:
        return total
    total = dict(total or {k: 0 for k in USAGE_KEYS})
    for k in USAGE_KEYS:
        total[k] = total.get(k, 0) + more.get(k, 0)
    total["cost_usd"] = round(total["cost_usd"], 6)
    return total


class EvalUsageError(Exception):
    """A command line the runner refuses (exit 2)."""


@dataclass
class CallResult:
    stdout: str
    stderr: str
    rc: int
    status: str  # one of STATUSES
    usage: dict | None = None  # claude: tokens and list cost from --output-format json


@dataclass
class Model:
    """One requested model, resolved before any call."""

    label: str  # what the user asked for, e.g. "claude:consultant_main"; keys rows and raw/ dirs
    provider: str
    slug: str  # the model the CLI is given
    effort: str | None = None
    pin: list[str] = field(default_factory=list)  # argv fragment placed before the prompt
    cap: int | None = None  # codex: the watchdog hard cap (seat_model timeout)

    def describe(self) -> str:
        return self.slug + (f" @ {self.effort}" if self.effort else "")


def _seat_model(args: list[str]) -> str:
    """Run skills/_meta/seat_model.py; stdout on success, EvalUsageError otherwise."""
    proc = subprocess.run([sys.executable, str(META / "seat_model.py"), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise EvalUsageError(f"seat_model.py {' '.join(args)} failed (exit {proc.returncode}): "
                             + (proc.stderr.strip().splitlines() or ["no output"])[-1])
    return proc.stdout.strip()


def _check_role(provider: str, role: str) -> None:
    if not _ROLE_RE.fullmatch(role):
        raise EvalUsageError(f"{provider}:{role}: a {provider} model is a seat ROLE (e.g. "
                             f"{provider}:consultant_main); literal slugs are refused - seats "
                             "resolve only through seat_model")


# --- cancellation and process cleanup ---------------------------------------------

#: How long a reap after a kill may wait for the pipes to close. A grandchild that left the
#: process group can hold them open forever; the runner must not hang on it.
REAP_WAIT_S = 10.0
#: How often a waiting call wakes to see whether the run was stopped.
WAIT_SLICE_S = 0.2


def _killpg(pgid: int, sig) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _child_pids(pid: int) -> list[int]:
    """Direct children of `pid`, read from /proc (POSIX/Linux; [] where /proc is absent)."""
    kids = []
    proc_dir = Path("/proc")
    if not proc_dir.is_dir():
        return kids
    for d in proc_dir.iterdir():
        if not d.name.isdigit():
            continue
        try:
            stat = (d / "stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fields = stat[stat.rfind(")") + 2:].split()  # after "pid (comm) ": state ppid pgrp ...
        if len(fields) > 1 and fields[1] == str(pid):
            kids.append(int(d.name))
    return kids


def kill_tree(proc: subprocess.Popen) -> None:
    """SIGKILL `proc`'s process group AND the process group of each direct child.

    A child that called setsid (codex under codex_watch.py runs with start_new_session=True)
    is outside its parent's group, so killpg on the parent alone orphans it. The children are
    found BEFORE the parent dies: once it is gone they are reparented and cannot be told apart.

    A process already reaped (`returncode` set) is skipped: its pid, and so its group id, may
    already belong to an unrelated process.
    """
    if proc.returncode is not None:
        return
    if os.name != "posix":
        proc.kill()
        return
    for kid in _child_pids(proc.pid):
        try:
            _killpg(os.getpgid(kid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    _killpg(proc.pid, signal.SIGKILL)


def reap(proc: subprocess.Popen, wait_s: float | None = None) -> tuple[str, str]:
    """Collect a killed process's output, never waiting more than `wait_s` (REAP_WAIT_S) for it."""
    wait_s = REAP_WAIT_S if wait_s is None else wait_s
    try:
        out, err = proc.communicate(timeout=wait_s)
        return out or "", err or ""
    except subprocess.TimeoutExpired:
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        return "", "\nREAP TIMEOUT: output pipes still held after the kill"


class RunControl:
    """The run's stop flag and its active processes.

    The MAIN thread owns the signal handling and the cleanup (signal handlers only run
    there); executor workers check `stopped` before each launch and register every process
    they start. A process registered after the stop is stopped at once, so no launch slips
    through the gap between the flag and the cleanup.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._active: dict[int, tuple[subprocess.Popen, object]] = {}
        self._cancelled: set[int] = set()
        self.signum: int | None = None
        self.signals = 0  # stop signals received; the second one force-quits

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def request_stop(self, signum: int | None = None) -> None:
        if self.signum is None:
            self.signum = signum
        if signum is not None:
            self.signals += 1
        self._stop.set()

    def kill_all_now(self) -> None:
        """Force-quit path: SIGKILL every active process tree at once, waiting for nothing."""
        with self._lock:
            procs = list(self._active.values())
            self._cancelled.update(id(p) for p, _ in procs)
        for proc, _ in procs:
            kill_tree(proc)

    def register(self, proc: subprocess.Popen, stopper) -> None:
        """`stopper(proc, phase)`: phase "term" asks politely, "kill" forces."""
        with self._lock:
            self._active[id(proc)] = (proc, stopper)
            late = self._stop.is_set()
            if late:
                self._cancelled.add(id(proc))
        if late:
            stopper(proc, "term")
            stopper(proc, "kill")

    def unregister(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._active.pop(id(proc), None)

    def was_cancelled(self, proc: subprocess.Popen) -> bool:
        with self._lock:
            return id(proc) in self._cancelled

    def cancel_active(self, grace_s: float) -> None:
        """MAIN THREAD: stop every active process. "term" first (a codex watchdog reaps
        its child on SIGTERM), wait up to `grace_s` for them to exit, then "kill" the rest."""
        with self._lock:
            procs = list(self._active.values())
            self._cancelled.update(id(p) for p, _ in procs)
        for proc, stopper in procs:
            stopper(proc, "term")
        deadline = time.monotonic() + grace_s
        while time.monotonic() < deadline and any(p.poll() is None for p, _ in procs):
            time.sleep(0.05)
        for proc, stopper in procs:
            if proc.poll() is None:
                stopper(proc, "kill")


RUN = RunControl()


def _stop_group(proc: subprocess.Popen, phase: str) -> None:
    """agy / claude: nothing to wait for, so both phases kill the group at once."""
    kill_tree(proc)


# --- providers ---------------------------------------------------------------

def call(argv: list[str], cwd: Path, timeout: int, stdin_file: Path | None = None) -> tuple[str, str, int]:
    # Own process group, so a timeout kills the CLI's children too, not just the CLI.
    stdin = open(stdin_file, "rb") if stdin_file else subprocess.DEVNULL
    try:
        return _call(argv, cwd, timeout, stdin)
    finally:
        if stdin_file:
            stdin.close()


def _call(argv: list[str], cwd: Path, timeout: int, stdin) -> tuple[str, str, int]:
    proc = subprocess.Popen(argv, cwd=cwd, stdin=stdin, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                            **({"start_new_session": True} if os.name == "posix" else {}))
    RUN.register(proc, _stop_group)
    deadline = time.monotonic() + timeout
    try:
        while True:
            # Short slices, so a stop is noticed even while an escaped grandchild holds the pipes.
            try:
                out, err = proc.communicate(timeout=max(0.0, min(WAIT_SLICE_S, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                if RUN.was_cancelled(proc):
                    kill_tree(proc)
                    out, err = reap(proc)
                    return out, err + "\nCANCELLED", RC_CANCELLED
                if time.monotonic() >= deadline:
                    kill_tree(proc)
                    out, err = reap(proc)
                    return out, err + "\nTIMEOUT", -1
        rc = proc.returncode
        # A call that finished cleanly before the stop keeps its result; anything else the
        # stop touched is cancelled.
        if RUN.was_cancelled(proc) and rc != 0:
            return out or "", (err or "") + "\nCANCELLED", RC_CANCELLED
        return out, err, rc
    finally:
        RUN.unregister(proc)


def _status_for(rc: int) -> str:
    if rc == RC_CANCELLED:
        return "cancelled"
    return "ok" if rc == 0 else ("timeout" if rc == -1 else "error")


class AgyProvider:
    """Antigravity CLI. Flags before -p, prompt last, stdin closed (host agy rules).

    The eval pack is the one sanctioned place that passes `--model` literally: choosing the
    model under test is its purpose. Every mode but `skip_perms` carries `--mode plan`, so the
    pack measures the call the seats make (Pattern 1, #366).
    """

    name = "agy"
    isolation: list[str] = []

    def resolve(self, spec: str) -> Model:
        return Model(label=spec, provider=self.name, slug=spec)

    def argv(self, model: str, mode: str, prompt: str) -> list[str]:
        cmd = ["agy", "--sandbox"]
        if mode == "skip_perms":
            cmd.append("--dangerously-skip-permissions")
        else:
            cmd += ["--mode", "plan"]
        if mode == "no_slash":
            cmd.append("--disable-slash-commands")
        cmd += ["--model", model, "--print-timeout", "9m", "-p", prompt]
        return cmd

    def run(self, model: Model, mode: str, prompt: str, cwd: Path, timeout: int,
            stdin_file: Path | None = None) -> CallResult:
        out, err, rc = call(self.argv(model.slug, mode, prompt), cwd, timeout, stdin_file)
        return CallResult(out, err, rc, _status_for(rc))


class ClaudeProvider:
    """Headless `claude -p`, model resolved through seat_model, no tools, isolated config.

    `measure_literal` (the `--measure-literal` flag) also accepts a literal `claude-<family>-<n>`
    id, benched or not: choosing the model under test is the pack's purpose, as with agy. That
    path is measurement only; no seat ever resolves through it.
    """

    name = "claude"

    def __init__(self, measure_literal: bool = False) -> None:
        self.measure_literal = measure_literal
    # What each flag isolates (claude 2.1.x, checked against `claude --help`):
    #   --safe-mode           CLAUDE.md, skills, plugins, hooks, MCP, custom agents/commands off
    #   --setting-sources ""  no user / project / local settings files
    #   --strict-mcp-config   no MCP server unless --mcp-config names one (none does)
    #   --tools ""            no built-in tools
    #   --disable-slash-commands, --no-session-persistence
    # --bare is NOT used: it reads only ANTHROPIC_API_KEY and never OAuth, so it fails on a
    # subscription login.
    isolation = ["--safe-mode", "--setting-sources", "", "--strict-mcp-config", "--tools", "",
                 "--disable-slash-commands", "--no-session-persistence", "--output-format", "json"]

    def resolve(self, spec: str) -> Model:
        if _CLAUDE_LITERAL_RE.fullmatch(spec):
            if not self.measure_literal:
                raise EvalUsageError(f"claude:{spec}: a literal claude model is measured only with "
                                     "--measure-literal; seats resolve only through seat_model")
            return Model(label=f"claude:{spec}", provider=self.name, slug=spec)
        _check_role(self.name, spec)
        slug = _seat_model(["model", "--role", spec, "--provider", "claude"])
        return Model(label=f"claude:{spec}", provider=self.name, slug=slug)

    def argv(self, model: Model, prompt: str) -> list[str]:
        return ["claude", "--model", model.slug, *self.isolation, "-p", prompt]

    def run(self, model: Model, mode: str, prompt: str, cwd: Path, timeout: int) -> CallResult:
        out, err, rc = call(self.argv(model, prompt), cwd, timeout)
        text, usage, is_error = parse_claude_json(out)
        status = _status_for(rc)
        if is_error and status == "ok":
            status, err = "error", (err or "") + "\nclaude reported is_error"
        return CallResult(text, err, rc, status, usage)


class VertexProvider:
    """Vertex AI `generateContent`, no tools, one stateless call per turn (measurement only).

    `vertex:<model>[-low|-medium|-high]`: a trailing level sets `thinkingConfig.thinkingLevel`.
    Auth is the `VERTEX_API_KEY` express key; the project is `VERTEX_PROJECT` or
    `GOOGLE_CLOUD_PROJECT`, the location `VERTEX_EVAL_LOCATION` (default `global`: the key's own
    default region may not serve a new model). Never a seat: agy serves Google seats.
    """

    name = "vertex"
    isolation = ["generateContent", "no tools"]
    _SLUG_RE = re.compile(r"^(gemini-[a-z0-9.-]+?)(?:-(low|medium|high))?$")

    def resolve(self, spec: str) -> Model:
        m = self._SLUG_RE.fullmatch(spec)
        if not m:
            raise EvalUsageError(f"vertex:{spec}: expected gemini-<name>[-low|-medium|-high]")
        return Model(label=f"vertex:{spec}", provider=self.name, slug=m.group(1), effort=m.group(2))

    @staticmethod
    def endpoint(model: Model) -> str:
        loc = os.environ.get("VERTEX_EVAL_LOCATION", "global")
        proj = os.environ.get("VERTEX_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not proj or not os.environ.get("VERTEX_API_KEY"):
            raise RuntimeError("vertex needs VERTEX_API_KEY and VERTEX_PROJECT / GOOGLE_CLOUD_PROJECT")
        host = "aiplatform.googleapis.com" if loc == "global" else f"aiplatform.{loc}.rep.googleapis.com"
        return (f"https://{host}/v1/projects/{proj}/locations/{loc}/publishers/google/models/"
                f"{model.slug}:generateContent")

    @staticmethod
    def body(model: Model, prompt: str) -> dict:
        body: dict = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if model.effort:
            body["generationConfig"] = {"thinkingConfig": {"thinkingLevel": model.effort}}
        return body

    @staticmethod
    def parse(doc: dict) -> tuple[str, dict, str | None]:
        """-> (answer text, usage, problem). Thought parts are dropped from the answer."""
        u = doc.get("usageMetadata") or {}
        usage = {"input_tokens": int(u.get("promptTokenCount") or 0) - int(u.get("cachedContentTokenCount") or 0),
                 "cache_creation_input_tokens": 0,
                 "cache_read_input_tokens": int(u.get("cachedContentTokenCount") or 0),
                 "output_tokens": int(u.get("candidatesTokenCount") or 0) + int(u.get("thoughtsTokenCount") or 0),
                 "thinking_tokens": int(u.get("thoughtsTokenCount") or 0), "cost_usd": 0.0}
        cands = doc.get("candidates") or []
        if not cands:
            return "", usage, f"no candidates: {json.dumps(doc.get('promptFeedback'))}"
        c = cands[0]
        text = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", []) if not p.get("thought"))
        reason = c.get("finishReason")
        return text, usage, (None if reason in (None, "STOP") else f"finishReason={reason}")

    def run(self, model: Model, mode: str, prompt: str, cwd: Path, timeout: int) -> CallResult:
        if RUN.stopped:
            return CallResult("", "run cancelled; call not launched", RC_CANCELLED, "cancelled")
        try:
            req = urllib.request.Request(self.endpoint(model) + "?key=" + os.environ["VERTEX_API_KEY"],
                                         data=json.dumps(self.body(model, prompt)).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                doc = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            # 429 RESOURCE_EXHAUSTED is the project's rate limit, a gap in the run, not a model failure.
            return CallResult("", f"HTTP {exc.code}: {detail}", exc.code,
                              "skipped_quota" if exc.code == 429 else "error")
        except TimeoutError:
            return CallResult("", "TIMEOUT", -1, "timeout")
        except Exception as exc:  # network, bad JSON, missing env
            return CallResult("", f"vertex call failed: {exc!r}", -2, "error")
        text, usage, problem = self.parse(doc)
        if problem:
            return CallResult(text, problem, 1, "error", usage)
        return CallResult(text, "", 0, "ok", usage)


class LocalProvider:
    """A local OpenAI-compatible server (llama.cpp, Strata, vLLM ...): `/chat/completions`, no
    tools, one stateless call per turn (measurement only; a local model holds no seat).

    `local:<model>`: the model name the server lists. The server is `LOCAL_EVAL_BASE_URL`
    (default `http://127.0.0.1:8080/v1`, so reach a LAN host over an SSH tunnel), with an optional
    bearer key `LOCAL_EVAL_API_KEY` and output cap `LOCAL_EVAL_MAX_TOKENS`. Reasoning text
    (`reasoning_content`, or a `<think>` block left in `content`) is never part of the answer.
    """

    name = "local"
    isolation = ["chat/completions", "no tools"]
    _SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
    _THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

    def resolve(self, spec: str) -> Model:
        if not self._SLUG_RE.fullmatch(spec):
            raise EvalUsageError(f"local:{spec}: expected the model name the local server lists")
        return Model(label=f"local:{spec}", provider=self.name, slug=spec, effort=None)

    @staticmethod
    def endpoint() -> str:
        return os.environ.get("LOCAL_EVAL_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/") + "/chat/completions"

    @staticmethod
    def body(model: Model, prompt: str) -> dict:
        body: dict = {"model": model.slug, "messages": [{"role": "user", "content": prompt}], "stream": False}
        cap = os.environ.get("LOCAL_EVAL_MAX_TOKENS")
        if cap:
            body["max_tokens"] = int(cap)
        return body

    @classmethod
    def parse(cls, doc: dict) -> tuple[str, dict, str | None]:
        """-> (answer text, usage, problem)."""
        u = doc.get("usage") or {}
        thinking = int(((u.get("completion_tokens_details") or {}).get("reasoning_tokens")) or 0)
        usage = {"input_tokens": int(u.get("prompt_tokens") or 0), "cache_creation_input_tokens": 0,
                 "cache_read_input_tokens": 0, "output_tokens": int(u.get("completion_tokens") or 0),
                 "thinking_tokens": thinking, "cost_usd": 0.0}
        choices = doc.get("choices") or []
        if not choices:
            return "", usage, f"no choices: {json.dumps(doc)[:300]}"
        c = choices[0]
        text = cls._THINK_RE.sub("", (c.get("message") or {}).get("content") or "").strip()
        reason = c.get("finish_reason")
        return text, usage, (None if reason in (None, "stop") else f"finish_reason={reason}")

    def run(self, model: Model, mode: str, prompt: str, cwd: Path, timeout: int) -> CallResult:
        if RUN.stopped:
            return CallResult("", "run cancelled; call not launched", RC_CANCELLED, "cancelled")
        headers = {"Content-Type": "application/json"}
        if os.environ.get("LOCAL_EVAL_API_KEY"):
            headers["Authorization"] = "Bearer " + os.environ["LOCAL_EVAL_API_KEY"]
        try:
            req = urllib.request.Request(self.endpoint(), data=json.dumps(self.body(model, prompt)).encode("utf-8"),
                                         headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                doc = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return CallResult("", f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:500]}", exc.code, "error")
        except TimeoutError:
            return CallResult("", "TIMEOUT", -1, "timeout")
        except Exception as exc:  # refused connection, bad JSON
            return CallResult("", f"local call failed: {exc!r}", -2, "error")
        text, usage, problem = self.parse(doc)
        if problem:
            return CallResult(text, problem, 1, "error", usage)
        return CallResult(text, "", 0, "ok", usage)


class CodexProvider:
    """`codex exec` under skills/_meta/codex_watch.py, pinned by seat_model, quota-checked.

    Eval calls are measurement, not seats: they take no cycle budget slot. Each call runs
    the account-wide trip-wire first (check-only); `--max-codex-calls` is the run's budget.
    """

    name = "codex"
    isolation: list[str] = []

    def __init__(self, max_calls: int | None = None, deadline_margin_s: float = 120.0,
                 term_wait_s: float = 30.0, telemetry: bool = False) -> None:
        self.max_calls = max_calls
        self.launched = 0
        self._lock = threading.Lock()
        self.deadline_margin_s = deadline_margin_s  # runner deadline = watchdog cap + this
        self.term_wait_s = term_wait_s  # after SIGTERM, how long the watchdog gets to reap codex
        self.telemetry = telemetry

    def resolve(self, spec: str) -> Model:
        _check_role(self.name, spec)
        pin = _seat_model(["argv", "--role", spec, "--provider", "codex"]).split()
        cap = int(float(_seat_model(["timeout", "--role", spec, "--provider", "codex"])))
        slug = pin[pin.index("-m") + 1] if "-m" in pin else "?"
        effort = next((p.split("=", 1)[1] for p in pin if p.startswith("model_reasoning_effort=")), None)
        return Model(label=f"codex:{spec}", provider=self.name, slug=slug, effort=effort, pin=pin, cap=cap)

    # Seams the offline tests replace.
    def _tripwire(self) -> dict:
        if str(META) not in sys.path:
            sys.path.insert(0, str(META))
        import codex_quota  # noqa: E402
        return codex_quota.tripwire("supporting")

    def _classify(self, rc: int, err_file: Path, out_file: Path, prompt_file: Path) -> str:
        """`codex_quota.py classify` on a FAILED call -> its verdict line, e.g. 'gap codex_error'."""
        proc = subprocess.run([sys.executable, str(META / "codex_quota.py"), "classify", "--exit-code",
                               str(rc), "--attempt", "1", "--stderr-file", str(err_file), "--output-file",
                               str(out_file), "--prompt-file", str(prompt_file)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL)
        return proc.stdout.strip()

    def argv(self, model: Model, prompt: str, ws: Path, out_file: Path, err_file: Path) -> list[str]:
        cmd = [sys.executable, str(META / "codex_watch.py"), "--mode", "codex", "--hard-cap", str(model.cap),
               "--model", model.slug, "--stdout-file", str(out_file), "--stderr-file", str(err_file)]
        if not self.telemetry:
            cmd.append("--no-telemetry")
        # No --ephemeral (policy: every codex call meters real quota).
        return cmd + ["--", "codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", "-C", str(ws),
                      *model.pin, prompt]

    @staticmethod
    def _stop_watchdog(proc: subprocess.Popen, phase: str) -> None:
        """"term": SIGTERM the watchdog, which reaps codex itself. "kill": the watchdog ignored
        that, so SIGKILL codex's OWN process group (codex runs in its own session under
        codex_watch.py) together with the watchdog's."""
        if phase == "term":
            try:
                proc.send_signal(signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
        else:
            kill_tree(proc)

    def _claim_launch(self) -> bool:
        with self._lock:
            if self.max_calls is not None and self.launched >= self.max_calls:
                return False
            self.launched += 1
            return True

    def run(self, model: Model, mode: str, prompt: str, cwd: Path, timeout: int) -> CallResult:
        # A stopped run neither consults the trip-wire nor spends a slot of the call budget.
        if RUN.stopped:
            return CallResult("", "run cancelled; call not launched", RC_CANCELLED, "cancelled")
        trip = self._tripwire()
        if not trip.get("proceed", False):
            return CallResult("", f"codex trip-wire: {trip.get('action')} {trip.get('reason')}", -3,
                              "skipped_quota")
        if not self._claim_launch():
            # A refusal by the run's own budget is a gap in the run, not a model failure.
            return CallResult("", f"--max-codex-calls {self.max_calls} reached; call not launched", -2,
                              "skipped_cap")
        # The watchdog's files live in the run's work dir, OUTSIDE the case workspace.
        io_dir = Path(tempfile.mkdtemp(prefix="codex-io-", dir=cwd.parent))
        out_file, err_file = io_dir / "stdout.txt", io_dir / "stderr.txt"
        try:
            proc = subprocess.Popen(self.argv(model, prompt, cwd, out_file, err_file), cwd=io_dir,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace",
                                    **({"start_new_session": True} if os.name == "posix" else {}))
            RUN.register(proc, self._stop_watchdog)
            timed_out = False
            try:
                try:
                    _, werr = proc.communicate(timeout=model.cap + self.deadline_margin_s)
                except subprocess.TimeoutExpired:
                    # Timing belongs to the watchdog: SIGTERM it (it reaps codex), and only then escalate.
                    timed_out = True
                    self._stop_watchdog(proc, "term")
                    try:
                        _, werr = proc.communicate(timeout=self.term_wait_s)
                    except subprocess.TimeoutExpired:
                        self._stop_watchdog(proc, "kill")
                        _, werr = reap(proc)
            finally:
                RUN.unregister(proc)
            rc = proc.returncode
            out = out_file.read_text(encoding="utf-8", errors="replace") if out_file.exists() else ""
            err = (err_file.read_text(encoding="utf-8", errors="replace") if err_file.exists() else "")
            err += ("\n--- watchdog ---\n" + werr) if werr else ""
            if RUN.was_cancelled(proc) and not (rc == 0 and not timed_out):
                # A call that finished cleanly before the stop keeps its result.
                return CallResult(out, err + "\nCANCELLED", RC_CANCELLED, "cancelled")
            if timed_out:
                return CallResult(out, err + "\nTIMEOUT", -1, "timeout")
            if rc == 0:
                return CallResult(out, err, rc, "ok")
            if rc in (111, 112):  # watchdog idle timeout / runaway cap
                return CallResult(out, err, rc, "error")
            prompt_file = io_dir / "prompt.txt"
            prompt_file.write_text(prompt, encoding="utf-8")
            verdict = self._classify(rc, err_file, out_file, prompt_file)
            quota = any(w in verdict for w in ("quota_exhausted", "rate_limit_reached"))
            return CallResult(out, err + f"\nclassify: {verdict}", rc, "skipped_quota" if quota else "error")
        finally:
            shutil.rmtree(io_dir, ignore_errors=True)


PROVIDERS = {p.name: p for p in (AgyProvider(), CodexProvider(), ClaudeProvider(), VertexProvider(), LocalProvider())}


def split_model(value: str, default_provider: str) -> tuple[str, str]:
    for name in PROVIDERS:
        if value.startswith(name + ":"):
            return name, value[len(name) + 1:]
    return default_provider, value


# --- case loading and prompt expansion -------------------------------------------

def _expand_scorers(raw: list, shared: dict) -> list[dict]:
    scorers = []
    for s in raw:
        scorers.extend(shared[s[1:]] if isinstance(s, str) and s.startswith("@") else [s])
    return scorers


def load_cases(categories: set[str] | None, case_ids: set[str] | None) -> list[dict]:
    cases = []
    for path in sorted(CASES_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        cat = doc["category"]
        if categories and cat not in categories:
            continue
        shared = doc.get("shared_scorers", {})
        for case in doc["cases"]:
            if case_ids and case["id"] not in case_ids:
                continue
            if ("prompt" in case) == ("turns" in case):
                raise ValueError(f"{case['id']}: give exactly one of prompt / turns")
            if "turns" in case:
                turns = [{"prompt": t["prompt"], "scorers": _expand_scorers(t["scorers"], shared)}
                         for t in case["turns"]]
            else:
                turns = [{"prompt": case["prompt"], "scorers": _expand_scorers(case["scorers"], shared)}]
            for n, t in enumerate(turns, 1):
                bad = [int(k) for k in _TURN_REF.findall(t["prompt"]) if not 1 <= int(k) < n]
                if bad:
                    raise ValueError(f"{case['id']}: turn {n} refers to a turn that has not run: {bad}")
            # Prompts are NOT expanded here: a {file:} resource is read only for a case that will
            # run (check_resources), so --list and a run on another provider never touch it.
            mode = case.get("mode", "sandbox")
            if mode not in MODES:
                raise ValueError(f"{case['id']}: unknown mode {mode!r}")
            providers = case.get("providers")
            if providers is not None and (not providers or any(p not in PROVIDERS for p in providers)):
                raise ValueError(f"{case['id']}: unknown providers {providers!r}")
            cases.append({**case, "category": cat, "turns": turns, "scorers": turns[0]["scorers"],
                          "mode": mode, "kind": case.get("kind", "behaviour"), "providers": providers})
    return cases


def applies(case: dict, provider: str) -> bool:
    return case.get("providers") is None or provider in case["providers"]


def check_resources(cases: list[dict], providers: set[str]) -> None:
    """Expand every prompt and file of the cases some requested provider will run, so a
    missing {file:} or {skill:} fails before any model call (EvalUsageError -> exit 2).
    Cases no requested provider runs are never expanded."""
    for case in cases:
        if not any(applies(case, p) for p in providers):
            continue
        for text in [t["prompt"] for t in case["turns"]] + list(case.get("files", {}).values()):
            try:
                expand(text, "check")
            except (OSError, UnicodeDecodeError) as exc:
                raise EvalUsageError(f"{case['id']}: a resource the case needs is missing or "
                                     f"unreadable: {exc}") from exc


def haystack(lines: int = 1500, needle_at: int = 1103) -> str:
    # About 108 KB: stays under Linux's 128 KB single-argument limit (MAX_ARG_STRLEN).
    rng = random.Random(7)
    words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike".split()
    out = [" ".join(rng.choice(words) for _ in range(12)) for _ in range(lines)]
    out[needle_at] = "The vault combination is 48-15-93 and it belongs to Marguerite."
    return "\n".join(out)


def expand(text: str, token: str) -> str:
    def skill(m: re.Match) -> str:
        return (FIXTURE_SKILLS / m.group(1) / "SKILL.md").read_text(encoding="utf-8")

    def file_(m: re.Match) -> str:
        return Path(m.group(1)).expanduser().read_text(encoding="utf-8")

    text = re.sub(r"\{skill:([\w.-]+)\}", skill, text)
    text = re.sub(r"\{file:([^}]+)\}", file_, text)
    if "{haystack}" in text:
        text = text.replace("{haystack}", haystack())
    return text.replace("{token}", token)


def fill_turns(prompt: str, outputs: list[str]) -> str:
    """Put earlier turns' outputs into `{turnN}` in ONE pass: literal replacement, never
    str.format, and an output is never rescanned, so braces in it cannot break the prompt."""
    return _TURN_REF.sub(lambda m: outputs[int(m.group(1)) - 1], prompt)


# --- workspace -----------------------------------------------------------------

def safe_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", model).lstrip(".") or "model"


def snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def make_workspace(base: Path, case: dict, token: str) -> Path:
    ws = Path(tempfile.mkdtemp(prefix=case["id"] + "-", dir=base))
    for rel, content in case.get("files", {}).items():
        target = (ws / rel).resolve()
        if not target.is_relative_to(ws.resolve()):
            raise ValueError(f"{case['id']}: file {rel!r} escapes the workspace")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(expand(content, token), encoding="utf-8")
    if case.get("workspace_skill"):
        name = case["workspace_skill"]
        shutil.copytree(FIXTURE_SKILLS / name, ws / ".agents" / "skills" / name)
    return ws


def make_home_dir(case: dict, token: str) -> Path | None:
    """A throwaway directory under the user's home for a case that names `home_files`, or None.

    The workspace is under the system temp dir, which an advisory agy call can read; only a path
    under home shows whether agy's non-workspace read is denied (#366). The caller deletes it."""
    if not case.get("home_files"):
        return None
    root = Path.home() / ".cache"
    root.mkdir(parents=True, exist_ok=True)
    hd = Path(tempfile.mkdtemp(prefix="model-eval-home-", dir=root))
    for name, content in case["home_files"].items():
        if Path(name).name != name:
            raise ValueError(f"{case['id']}: home file {name!r} must be a bare name")
        (hd / name).write_text(expand(content, token), encoding="utf-8")
    return hd


# --- scoring -------------------------------------------------------------------

def _lines(out: str) -> list[str]:
    return [ln.rstrip() for ln in out.strip().splitlines() if ln.strip()]


def key_values(out: str, key: str) -> list[str]:
    """The value of every `KEY: value` line, markdown `*` and backticks stripped."""
    vals = []
    for ln in out.splitlines():
        clean = ln.replace("*", "").replace("`", "").strip()
        m = re.match(re.escape(key) + r":\s*(.*?)\s*$", clean)
        if m:
            vals.append(m.group(1))
    return vals


_MD_LEAD = re.compile(r"^(?:\s*(?:#{1,6}|>|[-+*]|\d{1,3}[.)])\s+)+")
#: Every occurrence of the WORD final, any case, colon or not (`Final answer: 20` counts, `semifinal`
#: and `finally` do not). Matched after NFKC normalisation and with format characters removed.
_FINAL_WORD = re.compile(r"\bfinal\b", re.I)
#: A markdown horizontal rule (`---`, `***`, `___`, spaced or not): ignored, never a line of the answer.
_HR_LINE = re.compile(r"\s*([-*_])(?:\s*\1){2,}\s*")


def _normalise(text: str) -> str:
    """NFKC (full-width and compatibility letters fold to ASCII), then every format character
    (Unicode category Cf: zero-width space / joiners, BOM, soft hyphen, bidi marks) removed, so
    `F\u200bINAL` or a full-width `ＦＩＮＡＬ` cannot hide a second FINAL from the count."""
    return "".join(c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c) != "Cf")


def _md_clean(line: str) -> str:
    """One output line without markdown: leading heading / blockquote / list markers, then
    every `*`, `_` and backtick."""
    line = _MD_LEAD.sub("", line.strip() + " ").strip()
    return re.sub(r"[*_`]", "", line).strip()


def _strict_final(out: str) -> str | None:
    """The value of a strict FINAL answer, or None.

    The output is NFKC-normalised with format characters removed, horizontal-rule lines are
    dropped, and markdown is stripped. Then the WORD `final` occurs exactly ONCE in the whole
    output (any case, with or without a colon: `Final answer: 20` counts, `semifinal` does not),
    it is on the LAST non-empty line, and that line is nothing but `FINAL: <value>` (an optional
    trailing full stop allowed). So a FINAL followed by a retraction, a quoted or conceded earlier
    FINAL, a `Final answer:` beside the real one, and an explanation after the value all fail; a
    closing `---` does not.
    """
    lines = [x for x in _normalise(out).splitlines() if not _HR_LINE.fullmatch(x)]
    lines = [_md_clean(x) for x in lines]
    lines = [x for x in lines if x]
    if not lines or len(_FINAL_WORD.findall("\n".join(lines))) != 1:
        return None
    m = re.fullmatch(r"FINAL:\s*(\S+?)\.?", lines[-1])
    return m.group(1) if m else None


def score_one(s: dict, out: str, ctx: dict) -> bool:
    t = s["type"]
    lines = _lines(out)
    if t == "exact":
        return out.strip() == s["value"]
    if t == "final":
        if s.get("strict"):
            return _strict_final(out) in s["accept"]
        found = re.findall(r"FINAL:\s*[*`]*\s*([^\s*`]+)", out)
        return bool(found) and found[-1].strip(".") in s["accept"]
    if t == "verdict":
        # Exactly one KEY line; its whole value is one allowed token and equals `expect`.
        vals = key_values(out, s["key"])
        return len(vals) == 1 and vals[0] in s["allowed"] and vals[0] == s["expect"]
    if t == "set_equals":
        vals = key_values(out, s["key"])
        if len(vals) != 1:
            return False
        items = [x for x in re.split(r"[\s,]+", vals[0]) if x]
        return (len(items) == len(set(items)) and all(x in s["allowed"] for x in items)
                and set(items) == set(s["expect"]))
    if t == "regex":
        return re.search(s["pattern"], out) is not None
    if t == "contains_all":
        return all(re.search(p, out, re.I) for p in s["patterns"])
    if t == "contains_none":
        return not any(re.search(p, out, re.I) for p in s["patterns"])
    if t == "first_line":
        return bool(lines) and re.search(s["pattern"], lines[0]) is not None
    if t == "last_line":
        return bool(lines) and re.search(s["pattern"], lines[-1]) is not None
    if t == "json_equals":
        try:
            return json.loads(out.strip()) == s["value"]
        except ValueError:
            return False
    if t == "token_present":
        return ctx["token"] in out
    if t == "token_absent":
        return ctx["token"] not in out
    if t == "no_file_changes":
        return ctx["before"] == ctx["after"]
    if t == "file_created":
        return s["path"] in set(ctx["after"]) - set(ctx["before"])
    raise ValueError(f"unknown scorer {t!r}")


def scorer_label(s: dict) -> str:
    if s["type"] in ("verdict", "set_equals"):
        exp = s["expect"] if isinstance(s["expect"], str) else ",".join(s["expect"])
        return f"{s['type']}:{s['key']}={exp}"
    if s["type"] == "final" and s.get("strict"):
        return "final:strict"
    return s["type"] + (":" + s.get("pattern", "")[:40] if "pattern" in s else "")


# --- running -------------------------------------------------------------------

def _as_model(model) -> Model:
    return model if isinstance(model, Model) else Model(label=str(model), provider="agy", slug=str(model))


def run_case(provider, model, case: dict, rep: int, work: Path, raw: Path, timeout: int) -> dict:
    model = _as_model(model)
    token = secrets.token_hex(6)
    multi = len(case["turns"]) > 1
    stem = raw / safe_name(model.label) / f"{case['id']}.{rep}"
    stem.parent.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    turn_rows: list[dict] = []
    checks: list[dict] = []
    captured = None
    changed: set[str] = set()
    status = "ok"
    rc = 0
    t_case = time.monotonic()
    usage = None
    ws = hd = None
    try:
        ws = make_workspace(work, case, token)
        hd = make_home_dir(case, token)
        for n, turn in enumerate(case["turns"], 1):
            if RUN.stopped:
                status, rc = "cancelled", RC_CANCELLED
                break
            t0 = time.monotonic()
            try:
                before = snapshot(ws)
                prompt = fill_turns(expand(turn["prompt"], token), outputs)
                if hd is not None:
                    prompt = prompt.replace("{home_dir}", str(hd))
                piped = {}
                if case.get("stdin"):        # outside the workspace, so the snapshot does not see it
                    feed = Path(tempfile.mkdtemp(prefix="stdin-", dir=work)) / "stdin.txt"
                    feed.write_text(expand(case["stdin"], token), encoding="utf-8")
                    piped = {"stdin_file": feed}
                res = provider.run(model, case["mode"], prompt, ws, timeout, **piped)
                after = snapshot(ws)
            except Exception as exc:  # one broken case must not kill the model's run or the scorecard
                res, before, after = CallResult("", f"RUNNER ERROR: {exc!r}", -2, "error"), {}, {}
            secs = round(time.monotonic() - t0, 2)
            usage = add_usage(usage, res.usage)
            outputs.append(res.stdout)
            ctx = {"token": token, "before": before, "after": after}
            prefix = f"t{n}: " if multi else ""
            tchecks = [{"scorer": prefix + scorer_label(s),
                        "pass": res.status == "ok" and score_one(s, res.stdout, ctx)} for s in turn["scorers"]]
            if res.status != "ok":
                tchecks.insert(0, {"scorer": f"{prefix}status={res.status}", "pass": False})
            checks += tchecks
            changed |= set(after) ^ set(before) | {k for k in after if before.get(k) not in (None, after[k])}
            tstem = Path(f"{stem}.t{n}") if multi else stem
            Path(str(tstem) + ".out").write_text(res.stdout, encoding="utf-8")
            if res.stderr:
                Path(str(tstem) + ".err").write_text(res.stderr, encoding="utf-8")
            turn_rows.append({"turn": n, "status": res.status, "rc": res.rc, "seconds": secs,
                              "pass": all(c["pass"] for c in tchecks), "empty_output": not res.stdout.strip(),
                              "usage": res.usage})
            if case.get("capture") and captured is None:
                m = re.search(case["capture"], res.stdout)
                captured = m.group(1).strip() if m else None
            rc = res.rc
            if res.status != "ok":
                status = res.status
            if not turn_rows[-1]["pass"]:
                break  # a wrong turn makes the later ones meaningless (and wastes calls)
    except Exception as exc:
        status, rc = "error", -2
        checks.append({"scorer": "status=error", "pass": False})
        Path(str(stem) + ".err").write_text(f"RUNNER ERROR: {exc!r}", encoding="utf-8")
    finally:
        for tmp in (ws, hd):
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
    if status == "cancelled" and not any(c["scorer"].endswith("status=cancelled") for c in checks):
        checks.append({"scorer": "status=cancelled", "pass": False})
    for n in range(len(turn_rows) + 1, len(case["turns"]) + 1):
        checks.append({"scorer": f"t{n}: not run", "pass": False})
    passed = bool(turn_rows) and len(turn_rows) == len(case["turns"]) and all(c["pass"] for c in checks)
    return {"model": model.label, "provider": provider.name, "resolved": model.describe(), "case": case["id"],
            "category": case["category"], "kind": case["kind"], "mode": case["mode"], "rep": rep,
            "status": status, "rc": rc, "seconds": round(time.monotonic() - t_case, 2),
            "pass": passed and status == "ok", "checks": checks, "turns": turn_rows, "captured": captured,
            "files_changed": sorted(changed), "empty_output": any(t["empty_output"] for t in turn_rows),
            "usage": usage}


def _scored(rows: list[dict]) -> list[dict]:
    """Rows that count: a quota skip, a call-cap refusal or a cancellation is a gap, never a
    model failure."""
    return [r for r in rows if r.get("status") not in UNSCORED]


def _unscored_note(rows: list[dict]) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        if r.get("status") in UNSCORED:
            counts[UNSCORED[r["status"]]] = counts.get(UNSCORED[r["status"]], 0) + 1
    return ", ".join(f"{n} skipped ({why})" for why, n in sorted(counts.items()))


def planned_rows(model: Model, cases: list[dict], repeat: int) -> int:
    """How many case runs (rows) a finished run would have for `model`."""
    return sum(1 for c in cases if applies(c, model.provider)) * repeat


def _signal_name(signum: int | None) -> str:
    try:
        return signal.Signals(signum).name
    except (TypeError, ValueError):
        return f"signal {signum}" if signum is not None else "a stop request"


def scorecard(rows: list[dict], models: list[str], cases: list[dict], resolved: dict | None = None,
              isolation: dict | None = None, interrupted: dict | None = None) -> str:
    """`interrupted`, for a stopped run: {"signum": int | None, "planned": {label: rows}}. The
    card then opens with a banner and a planned / finished table, and a case a model never
    reached reads `not run` rather than `-`."""
    resolved = resolved or {}
    isolation = isolation or {}
    out = ["# Model eval scorecard", ""]
    if interrupted is not None:
        planned = interrupted.get("planned", {})
        out += [f"**INTERRUPTED by {_signal_name(interrupted.get('signum'))}** - the run was stopped "
                "before it finished; every figure below is partial.", "",
                "| model | planned | finished | cancelled | not run |", "|---|---|---|---|---|"]
        for m in models:
            mine = [r for r in rows if r["model"] == m]
            cancelled = sum(1 for r in mine if r.get("status") == "cancelled")
            plan = planned.get(m, len(mine))
            out.append(f"| {m} | {plan} | {len(mine) - cancelled} | {cancelled} | {max(0, plan - len(mine))} |")
        out.append("")
    if resolved:
        out += ["## Models", "", "| model | provider | resolved | isolation flags |", "|---|---|---|---|"]
        for m in models:
            prov, desc = resolved.get(m, ("?", m))
            flags = " ".join(repr(f) if f == "" else f for f in isolation.get(m, [])) or "-"
            out.append(f"| {m} | {prov} | {desc} | {flags} |")
        out.append("")
    by = {}
    for r in rows:
        by.setdefault((r["model"], r["case"]), []).append(r)
    cats = sorted({c["category"] for c in cases})
    out += ["## Summary (behaviour cases only; quota skips, call-cap refusals and cancellations excluded)", "",
            "| model | " + " | ".join(cats) + " | overall | median s | unscored |",
            "|---" * (len(cats) + 4) + "|"]
    for m in models:
        cells, tot_p, tot_n = [], 0, 0
        for cat in cats:
            rs = _scored([r for r in rows if r["model"] == m and r["category"] == cat and r["kind"] == "behaviour"])
            p = sum(r["pass"] for r in rs)
            tot_p, tot_n = tot_p + p, tot_n + len(rs)
            cells.append(f"{p}/{len(rs)}" if rs else "-")
        secs = [r["seconds"] for r in _scored(rows) if r["model"] == m]
        med = f"{statistics.median(secs):.1f}" if secs else "-"
        skipped = sum(1 for r in rows if r["model"] == m and r.get("status") in UNSCORED)
        out.append(f"| {m} | " + " | ".join(cells) + f" | {tot_p}/{tot_n} | {med} | {skipped} |")
    out += ["", "## Per case (passes / runs, median seconds)", "",
            "| case | kind | " + " | ".join(models) + " |", "|---|---" + "|---" * len(models) + "|"]
    for c in cases:
        cells = []
        for m in models:
            all_rs = by.get((m, c["id"]), [])
            rs = _scored(all_rs)
            if not all_rs:
                prov = resolved[m][0] if m in resolved else split_model(m, "agy")[0]
                cells.append("not run" if interrupted is not None and applies(c, prov) else "-")
                continue
            if not rs:
                cells.append(_unscored_note(all_rs))
                continue
            p = sum(r["pass"] for r in rs)
            med = statistics.median(r["seconds"] for r in rs)
            extra = " (empty)" if any(r["empty_output"] for r in rs) else ""
            cap = {r["captured"] for r in rs if r["captured"]}
            extra += f" [{', '.join(sorted(cap))}]" if cap else ""
            extra += f" +{_unscored_note(all_rs)}" if len(all_rs) > len(rs) else ""
            cells.append(f"{p}/{len(rs)} · {med:.0f}s{extra}")
        out.append(f"| {c['id']} | {c['kind']} | " + " | ".join(cells) + " |")
    out += token_table(rows, models)
    fails = [r for r in _scored(rows) if not r["pass"]]
    if fails:
        out += ["", "## Failed checks", ""]
        for r in fails:
            bad = ", ".join(c["scorer"] for c in r["checks"] if not c["pass"])
            out.append(f"- {r['model']} · {r['case']} #{r['rep']}: {bad}"
                       + (" · files changed: " + ", ".join(r["files_changed"]) if r["files_changed"] else ""))
    return "\n".join(out) + "\n"


def token_table(rows: list[dict], models: list[str]) -> list[str]:
    """Per-model token use for the rows that carry it (claude). Input counts the CLI's own
    system prompt (cache creation / read), so compare OUTPUT tokens between models."""
    have = [m for m in models if any(r.get("usage") for r in rows if r["model"] == m)]
    if not have:
        return []
    out = ["", "## Tokens (claude, vertex and local rows; per case run, all turns summed; output includes thinking; "
           "cost is the claude CLI's list price, 0 for vertex and local, which report no price)", "",
           "| model | runs | median out | p90 out | total out | of which thinking | median in (uncached + cache) "
           "| total cost USD | USD per pass |", "|---|---|---|---|---|---|---|---|---|"]
    for m in have:
        rs = [r for r in _scored(rows) if r["model"] == m and r.get("usage")]
        outs = sorted(r["usage"]["output_tokens"] for r in rs)
        ins = [r["usage"]["input_tokens"] + r["usage"]["cache_creation_input_tokens"]
               + r["usage"]["cache_read_input_tokens"] for r in rs]
        cost = sum(r["usage"]["cost_usd"] for r in rs)
        passes = sum(r["pass"] for r in rs)
        p90 = outs[min(len(outs) - 1, int(0.9 * len(outs)))] if outs else 0
        out.append(f"| {m} | {len(rs)} | {statistics.median(outs) if outs else 0:.0f} | {p90} | {sum(outs)} "
                   f"| {sum(r['usage']['thinking_tokens'] for r in rs)} | {statistics.median(ins) if ins else 0:.0f} "
                   f"| {cost:.2f} | {cost / passes if passes else 0:.3f} |")
    cats = sorted({r["category"] for r in rows})
    out += ["", "Median output tokens per case run, by category:", "",
            "| model | " + " | ".join(cats) + " |", "|---" * (len(cats) + 1) + "|"]
    for m in have:
        cells = []
        for c in cats:
            o = [r["usage"]["output_tokens"] for r in _scored(rows)
                 if r["model"] == m and r["category"] == c and r.get("usage")]
            cells.append(f"{statistics.median(o):.0f}" if o else "-")
        out.append(f"| {m} | " + " | ".join(cells) + " |")
    return out


def planned_codex_calls(models: list[tuple[str, str]], cases: list[dict], repeat: int) -> int:
    """Σ over DISTINCT codex roles of Σ applicable cases' turns x repeats."""
    roles = {spec for prov, spec in models if prov == "codex"}
    per_model = sum(len(c["turns"]) for c in cases if applies(c, "codex")) * repeat
    return len(roles) * per_model


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", action="append", help="model (repeatable): <slug>, agy:<slug>, "
                    "codex:<role> or claude:<role>")
    ap.add_argument("--provider", default="agy", choices=sorted(PROVIDERS),
                    help="provider for a --model value without a prefix (default agy)")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--category", action="append", help="limit to a category (repeatable)")
    ap.add_argument("--case", action="append", help="limit to a case id (repeatable)")
    ap.add_argument("--out", type=Path, default=None, help="results dir (default: a new temp dir)")
    ap.add_argument("--measure-literal", action="store_true",
                    help="accept a literal claude model id (claude:claude-<family>-<n>), benched or not; "
                         "measurement only, never a seat")
    ap.add_argument("--timeout", type=int, default=600, help="per-call timeout in seconds (agy, claude; "
                    "codex timing belongs to its watchdog)")
    ap.add_argument("--max-codex-calls", type=int, default=None,
                    help="REQUIRED with a codex model: the run's codex call budget")
    ap.add_argument("--list", action="store_true", help="list cases and exit")
    a = ap.parse_args(argv)

    cases = load_cases(set(a.category or []) or None, set(a.case or []) or None)
    if a.list:
        for c in cases:
            turns = f"{len(c['turns'])} turns" if len(c["turns"]) > 1 else ""
            print(f"{c['category']:16} {c['id']:28} {c['kind']:12} {c['mode']:10} "
                  f"{','.join(c['providers']) if c['providers'] else 'any':8} {turns}".rstrip())
        return 0
    if not a.model:
        ap.error("--model is required (unless --list)")
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2
    requested = list(dict.fromkeys(split_model(m, a.provider) for m in a.model))
    # Keep only the cases some requested provider runs, BEFORE any prompt is expanded.
    cases = [c for c in cases if any(applies(c, p) for p, _ in requested)]
    if not cases:
        print("no selected case applies to the requested providers", file=sys.stderr)
        return 2
    try:
        check_resources(cases, {p for p, _ in requested})
        if any(p == "codex" for p, _ in requested):
            if a.max_codex_calls is None:
                raise EvalUsageError("--max-codex-calls N is required when a codex model is requested")
            planned = planned_codex_calls(requested, cases, a.repeat)
            if planned > a.max_codex_calls:
                raise EvalUsageError(f"planned codex calls {planned} exceed --max-codex-calls "
                                     f"{a.max_codex_calls}; narrow the run or raise the cap")
        providers = dict(PROVIDERS)
        providers["codex"] = CodexProvider(max_calls=a.max_codex_calls)
        providers["claude"] = ClaudeProvider(measure_literal=a.measure_literal)
        models = [providers[p].resolve(spec) for p, spec in requested]
    except EvalUsageError as exc:
        print(f"run_eval: error: {exc}", file=sys.stderr)
        return 2
    labels = list(dict.fromkeys(m.label for m in models))
    out = a.out or Path(tempfile.mkdtemp(prefix="model-eval-"))
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    # Workspaces always live in the system temp dir, never under --out, so a model with
    # tools unlocked never sits inside a repo. Writes outside the workspace are not detected.
    work = Path(tempfile.mkdtemp(prefix="model-eval-work-"))
    rows: list[dict] = []
    lock = threading.Lock()
    results = out / "results.jsonl"

    def per_model(model: Model) -> None:
        # Cases run in sequence per model; models run side by side. A worker checks the stop
        # flag before every launch; the main thread does the signal handling and cleanup.
        provider = providers[model.provider]
        for rep in range(1, a.repeat + 1):
            for case in cases:
                if RUN.stopped:
                    return
                if not applies(case, model.provider):
                    continue
                row = run_case(provider, model, case, rep, work, raw, a.timeout)
                with lock:
                    rows.append(row)
                    with results.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(row) + "\n")
                    verdict = ("PASS" if row["pass"] else
                               f"SKIP({UNSCORED[row['status']]})" if row["status"] in UNSCORED else "FAIL")
                    print(f"{model.label} {case['id']} #{rep}: {verdict} ({row['seconds']}s)", flush=True)

    RUN.reset()
    # How long the main thread lets codex watchdogs reap their child after SIGTERM.
    grace = providers["codex"].term_wait_s if any(m.provider == "codex" for m in models) else 1.0
    previous = _install_stop_handlers()
    try:
        with ThreadPoolExecutor(max_workers=len(models)) as pool:
            futures = [pool.submit(per_model, m) for m in models]
            cancelled = False
            while not all(f.done() for f in futures):
                wait(futures, timeout=0.2)
                if RUN.stopped and not cancelled:
                    cancelled = True
                    print("run_eval: stop requested; no new launches, stopping active calls", file=sys.stderr,
                          flush=True)
                    RUN.cancel_active(grace)
            for f in futures:
                f.result()
    finally:
        _restore_stop_handlers(previous)
    resolved = {m.label: (m.provider, m.describe()) for m in models}
    isolation = {m.label: providers[m.provider].isolation for m in models}
    interrupted = None
    if RUN.stopped:
        planned: dict[str, int] = {}
        for m in models:
            planned.setdefault(m.label, planned_rows(m, cases, a.repeat))
        interrupted = {"signum": RUN.signum, "planned": planned}
    (out / "scorecard.md").write_text(scorecard(rows, labels, cases, resolved, isolation, interrupted),
                                      encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    print(f"scorecard: {out / 'scorecard.md'}")
    if RUN.stopped:
        return 128 + (RUN.signum or signal.SIGTERM)
    return 0


def _stop_signals() -> list[int]:
    return [getattr(signal, n) for n in ("SIGINT", "SIGTERM") if hasattr(signal, n)]


def _on_stop_signal(signum: int, _frame) -> None:
    """First SIGINT / SIGTERM: a graceful stop. A second one is a force-quit: every active
    process tree is SIGKILLed without waiting, default handling is restored and the signal is
    delivered again, so the runner dies at once even if the graceful stop is stuck."""
    if RUN.signals == 0:
        RUN.request_stop(signum)
        return
    RUN.kill_all_now()
    for n in _stop_signals():
        if signal.getsignal(n) is _on_stop_signal:
            signal.signal(n, signal.SIG_DFL)
    print("run_eval: second stop signal; force-quitting", file=sys.stderr, flush=True)
    if os.name != "posix":
        os._exit(128 + signum)
    os.kill(os.getpid(), signum)


def _install_stop_handlers() -> list:
    """SIGINT / SIGTERM set the stop flag (MAIN THREAD only; elsewhere they are left alone);
    a second one force-quits (`_on_stop_signal`). An ignored signal stays ignored."""
    if threading.current_thread() is not threading.main_thread():
        return []
    previous = []
    for signum in _stop_signals():
        if signal.getsignal(signum) == signal.SIG_IGN:
            continue
        previous.append((signum, signal.getsignal(signum)))
        signal.signal(signum, _on_stop_signal)
    return previous


def _restore_stop_handlers(previous: list) -> None:
    for signum, handler in previous:
        signal.signal(signum, signal.SIG_DFL if handler is None else handler)


if __name__ == "__main__":
    sys.path.insert(0, str(META))
    from portable_cli import run_cli  # noqa: E402  (#251 stream hardening)
    sys.exit(run_cli(main))
