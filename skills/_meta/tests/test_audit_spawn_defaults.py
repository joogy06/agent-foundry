"""audit_spawn defaults, race-safe helper, and the S080 codex-arm pin.

S030-quickwins #53 + #54 (original scope):
    #53: DEFAULT_TIMEOUT_S guard — the value has moved 180 -> 300 -> 600; the
        assertion is CARRIED FORWARD to each new expected value, never deleted.
        A deleted assertion records nothing.
    #54: ensure_verdicts_dir() MUST exist and synchronously create the directory
        before any caller spawns parallel subprocesses that write into it.

S080 stream 4 (WP-402) adds guards for the codex arm's wiring: both axes pinned
from the single emitter, stdin closed on BOTH arms, and the two arms' budgets
split without truncating the longer one at the shorter one's ceiling.

Observed live at write time (2026-09-09, codex 0.153.4, roster corroborated):
    CODEX_PIN = CodexPin(model='gpt-5.6-sol', effort='xhigh', timeout=600,
                         provenance_source='data')
    argv fragment = ['-m', 'gpt-5.6-sol', '-c', 'model_reasoning_effort=xhigh']
The concrete SLUG is deliberately NOT asserted here: it is codex_model.py's
value, guarded by test_codex_model.py, and S080 stream 1 re-pins it while
touching audit_spawn.py but NOT this file. What IS asserted below is what this
module owns — that the arm resolves the `audit_codex_arm` ROLE, emits BOTH axes,
and can never fall back to inheriting from ~/.codex/config.toml.

S081 stream 1 (WP-P01, design §4.1) adds the P0 containment guards, each paired
with a control that proves the guard is not vacuous:
    L1  a repo-carried .claude/model-policy.yaml cannot downgrade the Claude
        reviewer (POSITIVE CONTROL: the same file really does poison
        smart-config's resolver in the same cwd).
    L2  a reviewer model env override is honoured only when it equals the pin;
        anything else is refused AND recorded (CONTROL: the equal value is
        accepted with source "env"). Same pair for the codex arm.
    BIN AUDIT_CLAUDE_BIN / AUDIT_CODEX_BIN are recorded with their realpath
        (CONTROL: unset -> no field and no warning).
Child processes run with HOME=<tmp> holding a FIXTURE codex roster — never the
live ~/.codex/models_cache.json — and with cwd outside any project.

S081 stream 1 (WP-P02, plan I19) adds a documentation-drift guard: no fenced
audit_spawn.py invocation in agents/bob.md may pass `--timeout` below
DEFAULT_TIMEOUT_S (NEGATIVE CONTROL: the same parser flags `--timeout 180`).

S081 stream 3 (WP-R06) wires both arms to seat_model and the codex arm to
codex_quota. Stream 1's assertions are CARRIED FORWARD onto the new resolver, and
new guards cover: the non-ephemeral codex call (I6; #302: every seat), the before/after meter,
exhaustion signals (with a prompt-echo negative control), token usage from the
call's own rollout (I9), and STUB-LAUNCH ADOPTION tests that run the real CLI
against stub binaries under a fixture HOME whose freeze holds codex on sol
(NEGATIVE CONTROL: without the freeze the fixture roster's TOP, gpt-6-astra, is
what the arm would run).

ISOLATION. audit_spawn resolves both pins at IMPORT, and seat_model reads the
home tier (codex roster, freeze pins, quota meter) and records the TOP it resolved
in ~/.claude/state/seat-model-tops.json. This module therefore imports audit_spawn
under an EMPTY throwaway HOME (nothing to read, nothing written: the harness-literal
path records nothing), and an autouse fixture points HOME at a per-test tmp dir, so
no test reads the live ~/.codex or writes the live ~/.claude. HOME-dependent facts
are asserted through `_resolve_*_pin()` under a fixture HOME or through child
processes, never through the import-time constants.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import os
import re
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

import pytest

_HERE = Path(__file__).resolve()
_META = _HERE.parent.parent
sys.path.insert(0, str(_META))

import codex_model  # noqa: E402
import codex_quota  # noqa: E402
import seat_model  # noqa: E402
import model_roster  # noqa: E402

#: #291: the Claude reviewer's model (the code_reviewer row) is ROSTER DATA. Where a test below
#: means "the reviewer's / the substitute's model" it asserts MAIN, read from model_roster (the
#: data), never from the resolver under test. Synthetic inputs (a fake served id fed to a pure
#: function, a stub invoked by hand, a hand-built substitution dict) stay literal.
MAIN = model_roster.CLAUDE_MAIN
SUPPORT = model_roster.CLAUDE_SUPPORT
#: Synthetic full served ids, one explicit LITERAL per vendor alias: the id a stub envelope reports
#: when it served that alias. Tests pick the entry for the alias they mean (the requested model for a
#: no-mismatch case, another tier's alias for a mismatch case), so the id strings stay literal while
#: which one a test needs follows the roster.
SERVED_ID = {"fable": "claude-fable-5-1", "opus": "claude-opus-5", "sonnet": "claude-sonnet-5",
             "haiku": "claude-haiku-4-5"}

_HOME_VARS = ("HOME", "USERPROFILE")


def _import_under_empty_home(name: str):
    """Import `name` with HOME pointed at an empty throwaway dir, then restore HOME.

    A no-op when another module in this pytest session already imported it (that
    module's own isolation applies; see known issues in the WP-R06 record).
    """
    if name in sys.modules:
        return sys.modules[name]
    saved = {var: os.environ.get(var) for var in _HOME_VARS}
    home = tempfile.mkdtemp(prefix="audit-spawn-import-home-")
    try:
        for var in _HOME_VARS:
            os.environ[var] = home
        return importlib.import_module(name)
    finally:
        for var, value in saved.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value
        shutil.rmtree(home, ignore_errors=True)


audit_spawn = _import_under_empty_home("audit_spawn")
codex_watch = audit_spawn.codex_watch


# ---------------------------------------------------------------------------
# D24: the codex arm's spawn seam moved (S081 revision 4, WP-A03)
# ---------------------------------------------------------------------------
#
# Before D24 both arms went through `subprocess.run`, so a test simulated a codex
# call by patching that one function. The codex arm now runs under codex_watch
# (Popen + activity polling), which streams to FILES and returns a WatchResult, so
# a `subprocess.run` patch alone no longer reaches it — the arm would spawn the real
# binary.
#
# `_codex_spawn_patched` keeps every existing test expressing itself the way it
# always did — one `fake_run(cmd, **kwargs)` returning a completed-process shape —
# and routes that fake to BOTH seams: `subprocess.run` (still the Claude arm's) and
# `codex_watch.watch` (now the codex arm's). The fakes are unchanged; only the
# plumbing under them is. Tests that assert on the WATCHDOG's own behaviour use real
# stub binaries instead (see the D24 stub-launch block), because a fake that
# answers instantly can never prove an activity timeout.
def _run_to_watch(fake_run: Any) -> Any:
    """Adapt a legacy `fake_run` into a `codex_watch.watch` side effect.

    The fake's stdout/stderr are written to the paths the watchdog was given (the
    arm reads the transcript back from those files), and its exceptions keep their
    old meaning under the new vocabulary:
      * FileNotFoundError      -> raised through, exactly as Popen would raise it.
      * subprocess.TimeoutExpired -> the RETRYABLE stop, i.e. `idle_timeout`. A
        legacy fake that raised TimeoutExpired was saying "this call was stopped for
        running too long, and that is retryable"; after D24 the stop with that
        meaning is the idle timeout, not the hard cap (which is a gap).
    """
    def _watch(cmd, **kwargs):
        stdout_path = Path(kwargs["stdout_path"])
        stderr_path = Path(kwargs["stderr_path"])
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        hard_cap = float(kwargs.get("hard_cap_s") or 0.0)
        idle = kwargs.get("idle_timeout_s")

        def _result(stop_reason, child_exit_code):
            return codex_watch.WatchResult(
                stop_reason=stop_reason, exit_code=child_exit_code or 0,
                child_exit_code=child_exit_code, elapsed_s=0.0, max_silence_s=0.0,
                mode=codex_watch.MODE_CODEX, argv=tuple(str(c) for c in cmd),
                stdout_path=stdout_path, stderr_path=stderr_path,
                idle_timeout_s=None if idle is None else float(idle), hard_cap_s=hard_cap,
            )

        # #291 fix round 2 N2: the codex prompt travels on stdin from a file; a legacy fake
        # sees it as `input=`, the way subprocess.run would have been handed it.
        fake_kwargs: Dict[str, Any] = {}
        if kwargs.get("stdin_path") is not None:
            fake_kwargs["input"] = Path(kwargs["stdin_path"]).read_bytes().decode("utf-8")
        try:
            proc = fake_run(cmd, **fake_kwargs)
        except subprocess.TimeoutExpired as exc:
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text(_as_text(getattr(exc, "stderr", None)), encoding="utf-8")
            return _result(codex_watch.STOP_IDLE_TIMEOUT, None)
        stdout_path.write_text(_as_text(getattr(proc, "stdout", "")), encoding="utf-8")
        stderr_path.write_text(_as_text(getattr(proc, "stderr", "")), encoding="utf-8")
        return _result(codex_watch.STOP_OK, getattr(proc, "returncode", 0))

    return _watch


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class _codex_spawn_patched:
    """Patch BOTH spawn seams from one legacy `fake_run`. See the note above.

    `side_effect` may be a callable, an exception instance or an exception class,
    matching what `mock.patch.object(..., side_effect=...)` already accepted, so a
    call site converts by swapping the `with` header and nothing else.
    """

    def __init__(self, side_effect: Any) -> None:
        self._side_effect = side_effect
        self._patches: List[Any] = []

    def _as_callable(self) -> Any:
        effect = self._side_effect
        if isinstance(effect, BaseException) or (
                isinstance(effect, type) and issubclass(effect, BaseException)):
            def _raise(cmd, **kwargs):
                raise effect
            return _raise
        return effect

    def __enter__(self):
        fake = self._as_callable()
        self._patches = [
            mock.patch.object(audit_spawn.subprocess, "run", side_effect=fake),
            mock.patch.object(audit_spawn.codex_watch, "watch", side_effect=_run_to_watch(fake)),
        ]
        entered = [p.__enter__() for p in self._patches]
        return entered[0]

    def __exit__(self, *exc_info) -> None:
        for patch in reversed(self._patches):
            patch.__exit__(*exc_info)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test resolves, meters and records against a tmp HOME, never the live one.

    #282 R3: every Claude reviewer launch resolves its fixed cwd from XDG_RUNTIME_DIR, so
    that too points at a per-test tmp dir (inherited by every child via _child_env) —
    no test creates or runs a stub in the host's real /run/user/<uid>/foundry-reviewer-cwd.

    #282 fix round 2 G3 (plan K55) makes CLAUDE_CONFIG_DIR load-bearing for the auto-memory
    directory, so it is UNSET here for the same reason HOME is redirected: a developer who has
    it exported would otherwise have every quarantine test reach into their real config dir.
    A test that wants the relocated root sets it itself.
    """
    home = tmp_path / "autouse-home"
    home.mkdir()
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    for var in _HOME_VARS:
        monkeypatch.setenv(var, str(home))
    assert Path.home() == home
    runtime = tmp_path / "xdg-runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    return home


# ---------------------------------------------------------------------------
# Timeouts — NUMBERS, not inequalities
# ---------------------------------------------------------------------------

def test_default_timeout_s_is_600() -> None:
    """Regression guard: DEFAULT_TIMEOUT_S = 600 (S080 stream 4; was 300).

    This is S030-quickwins #53's assertion preserved at its new expected value.
    The raise belongs to the CLAUDE arm alone and is separately justified
    (design §13.5: that arm moved opus -> fable on the harness's most-run gate).
    Design §11.4 M2 forbids raising it as a side effect of the codex split, so
    the codex arm is asserted independently below.
    """
    assert audit_spawn.DEFAULT_TIMEOUT_S == 600
    # S081 WP-R06: the value is OWNED by the role table, not by this module.
    assert audit_spawn.DEFAULT_TIMEOUT_S == seat_model.ROLE_TABLE["code_reviewer"]["claude"].timeout
    assert audit_spawn.DEFAULT_TIMEOUT_S == audit_spawn.CLAUDE_PIN.timeout


def test_codex_arm_timeout_comes_from_the_emitter_pin() -> None:
    """The value that actually protects the audit.

    The codex arm does NOT read DEFAULT_TIMEOUT_S; it takes its wall time from
    the pin. Asserted as an exact value AND as a floor: the rev0 form of this
    criterion was `> 293`, which the then-current 300 already satisfied while
    changing nothing at all.

    RE-POINTED (S081 revision 4, WP-A03; expected_red_set). xhigh 600 -> 2400:
    WP-A02 raised codex_model._TIMEOUT_FLOOR_S per D24, because a fixed 600s wall
    clock was killing healthy calls. The assertion is carried to its new value, not
    deleted, and the `>= 600` floor is carried too — it still fails on any regression
    BELOW the old number, which is the direction that reintroduces the D24 kill.
    """
    assert audit_spawn.CODEX_TIMEOUT_S == 2400
    assert audit_spawn.CODEX_TIMEOUT_S >= 600
    assert audit_spawn.CODEX_TIMEOUT_S == audit_spawn.CODEX_PIN.timeout
    # S081 WP-R06: the single codex timeout owner (design §4.2).
    assert audit_spawn.CODEX_TIMEOUT_S == codex_model.timeout_for(
        audit_spawn.CODEX_MODEL, audit_spawn.CODEX_EFFORT)


def test_pool_join_is_computed_from_the_longer_arm() -> None:
    """The join is computed from the LONGEST path an arm can take, never `timeout_s + 30`
    off one value.

    With two per-arm budgets, joining on the shared scalar cuts the longer arm
    at the shorter arm's ceiling and reports it as an outer-timeout failure —
    the exact truncation the split exists to fix.

    History (the assertion is CARRIED FORWARD to each new expected value, never deleted):
    max(claude, codex) + 30 = 630 (S080 stream 4) -> max(claude, 2 x codex + substitute) + 30
    = 1830 (S081 WP-F03, plan J13): the codex arm's worst case is now a timeout, the one
    same-model retry timing out too, then the fresh Fable substitute running to its own
    budget, all inside the codex worker.
    -> 5430 (S081 revision 4, WP-A03): the FORMULA is unchanged; its input moved when
    WP-A02 raised the codex arm's ceiling to 2400 (D24). Widening it is load-bearing —
    a join left at 1830 while each attempt may run to 2400 makes the POOL the new
    premature killer, moving the truncation from the arm to the join rather than
    removing it. _join_timeout_s's docstring carries the J13 freshness-window limit
    at its new value (worst case now exceeds ARBITER_FRESHNESS_WINDOW_S by 3630s, not
    30s; it fails CLOSED, so a stale request yields no VERIFIED, only an escalation).
    """
    join = audit_spawn._join_timeout_s(
        audit_spawn.DEFAULT_TIMEOUT_S, audit_spawn.CODEX_TIMEOUT_S, audit_spawn.SUBSTITUTE_TIMEOUT_S)
    assert join == 5430
    assert join == max(audit_spawn.DEFAULT_TIMEOUT_S,
                       2 * audit_spawn.CODEX_TIMEOUT_S + audit_spawn.SUBSTITUTE_TIMEOUT_S) + 30
    assert join >= audit_spawn.CODEX_TIMEOUT_S + 30
    assert join >= audit_spawn.DEFAULT_TIMEOUT_S + 30
    assert join >= 2 * audit_spawn.CODEX_TIMEOUT_S + audit_spawn.SUBSTITUTE_TIMEOUT_S + 30
    # A --timeout longer than the whole codex path still wins (the Claude arm is never cut).
    assert audit_spawn._join_timeout_s(4000, 600, 600) == 4030


# ---------------------------------------------------------------------------
# bob.md must not cut the reviewer short (S081 stream 1, WP-P02, plan I19)
# ---------------------------------------------------------------------------
#
# Raising DEFAULT_TIMEOUT_S protects nothing if the documented caller overrides
# it: bob.md carried `--timeout 180` on its fenced audit_spawn.py invocation
# through both raises (180 -> 300 -> 600). An explicit argv value wins over the
# module default, so every VERIFIED-gate audit bob ran was still cut at 180s.
# WP-R06 re-pointed the threshold to seat_model's code_reviewer Claude timeout
# (I19): the floor is the ROLE's budget, whichever module happens to read it.

_BOB_MD = _HERE.parents[3] / "agents" / "bob.md"


def _reviewer_timeout_floor() -> int:
    """seat_model's code_reviewer Claude timeout. The Claude adapter reads nothing."""
    return seat_model.resolve("code_reviewer", "claude").timeout

_FENCE_PREFIXES = ("```", "~~~")


def _fenced_logical_lines(markdown: str) -> List[str]:
    """Logical lines inside fenced code blocks; `\\`-newline continuations joined.

    Prose outside a fence is ignored: a sentence that merely names the helper is
    not an invocation. Indented fences (inside list items) count.
    """
    out: List[str] = []
    in_fence = False
    pending = ""
    for raw in markdown.splitlines():
        stripped = raw.strip()
        if stripped.startswith(_FENCE_PREFIXES):
            if pending:
                out.append(pending)
                pending = ""
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1] + " "
            continue
        out.append(pending + stripped)
        pending = ""
    if pending:
        out.append(pending)
    return out


def _audit_invocations(markdown: str) -> List[str]:
    return [line for line in _fenced_logical_lines(markdown) if "audit_spawn.py" in line]


def _short_timeouts(markdown: str, floor: int) -> List[Tuple[str, str]]:
    """(invocation, value) for every `--timeout` below `floor` on an audit call.

    A value that is not a literal integer is reported too: a placeholder cannot
    be shown to respect the floor, so it fails closed.
    """
    found: List[Tuple[str, str]] = []
    for line in _audit_invocations(markdown):
        for match in re.finditer(r"--timeout(?:=|\s+)(\S+)", line):
            value = match.group(1).strip("\"'")
            if not value.isdigit() or int(value) < floor:
                found.append((line, value))
    return found


def test_bob_md_audit_invocations_do_not_undercut_the_default() -> None:
    """Every fenced audit_spawn.py call in bob.md leaves the reviewer its 600s."""
    assert _BOB_MD.is_file(), f"agents/bob.md not found beside this tree: {_BOB_MD}"
    text = _BOB_MD.read_text(encoding="utf-8")
    # Non-vacuity: the parser must actually see the invocation it is guarding.
    assert _audit_invocations(text), "no fenced audit_spawn.py invocation found in bob.md"
    assert _short_timeouts(text, _reviewer_timeout_floor()) == []
    # The role floor and the module default are the same number from the same owner.
    assert _reviewer_timeout_floor() == audit_spawn.DEFAULT_TIMEOUT_S


def test_timeout_parser_reports_a_short_timeout() -> None:
    """NEGATIVE CONTROL: the same parser flags `--timeout 180` on a fenced call.

    Also pins the edges the real check relies on: an equal-to-floor value and a
    prose mention are not reported; `=` form, continuation lines and a
    placeholder are.
    """
    fixture = "\n".join([
        "Prose naming audit_spawn.py --timeout 5 is not an invocation.",
        "   ```bash",
        '   python3 ~/.claude/skills/_meta/audit_spawn.py c b.json --project-root "<r>" --timeout 180',
        "   python3 audit_spawn.py c b.json --timeout 600",
        "   ```",
        "```",
        "python3 audit_spawn.py c b.json \\",
        "  --timeout=120",
        "python3 audit_spawn.py c b.json --timeout <t>",
        "python3 verification_arbiter_spawn.py --timeout 10",
        "```",
    ])
    assert len(_audit_invocations(fixture)) == 4
    floor = _reviewer_timeout_floor()
    assert floor == 600
    reported = [value for _, value in _short_timeouts(fixture, floor)]
    assert reported == ["180", "120", "<t>"]


# ---------------------------------------------------------------------------
# The codex pin — both axes, right role, no inherit path
# ---------------------------------------------------------------------------

def test_codex_pin_resolves_the_audit_role_not_a_default(_isolated_home: Path) -> None:
    """The arm is wired to the `code_reviewer` codex ROLE, fail-open, with a GATED env override.

    Pins the whole triple (role, env var, fail_open) rather than just the
    resulting slug: resolving `default_model()` or another role would produce a
    plausible-looking model while silently detaching this arm from its own pin.

    S081 stream 1 (I3) gated the env layer; S081 WP-R06 moved the arm from
    codex_model's `audit_codex_arm` key onto seat_model's `code_reviewer` row
    (LEGACY_ROLE_MAP documents the mapping). The original assertions are carried
    forward on both branches — the no-override pin, and the pin the arm resolves
    when an equal override is accepted — against a FIXTURE HOME, never the live one.
    """
    assert seat_model.LEGACY_ROLE_MAP[codex_model.AUDIT_CODEX_ARM] == ("code_reviewer", "codex")
    _seat_home(_isolated_home, freeze="gpt-5.6-sol")

    expected = seat_model.resolve("code_reviewer", "codex", env_var="AUDIT_CODEX_MODEL", fail_open=True)
    clean_env = {k: v for k, v in os.environ.items() if k != "AUDIT_CODEX_MODEL"}
    with mock.patch.dict(os.environ, clean_env, clear=True):
        pin = audit_spawn._resolve_codex_pin()
    assert pin == expected
    assert pin.provenance.get("env_override_refused") is None
    assert (pin.model, pin.effort, pin.provenance["source"]) == ("gpt-5.6-sol", "xhigh", "freeze")
    assert pin.provenance["requested_selector"] == "TOP@xhigh"
    # Not a default and not a neighbouring role: those resolve differently here.
    assert pin != seat_model.resolve("consultant_support", "codex", fail_open=True)
    # RE-POINTED by the astra reserve (roster rev 4): the arbiter is Sol @ xhigh now, so the neighbouring
    # role that still differs in effort is escalation (TOP @ max).
    assert pin.effort != seat_model.resolve("escalation", "codex", fail_open=True).effort
    assert audit_spawn.CODEX_MODEL == audit_spawn.CODEX_PIN.model
    assert audit_spawn.CODEX_EFFORT == audit_spawn.CODEX_PIN.effort
    assert audit_spawn.CODEX_MODEL_SOURCE in seat_model.SOURCES
    assert audit_spawn.CODEX_PIN.provenance["requested_selector"] == "TOP@xhigh"

    # The accepted-override branch: the same model and effort, source env.
    with mock.patch.dict(os.environ, {"AUDIT_CODEX_MODEL": expected.model}):
        accepted = audit_spawn._resolve_codex_pin()
        with_env = seat_model.resolve("code_reviewer", "codex", env_var="AUDIT_CODEX_MODEL",
                                      fail_open=True)
    assert accepted == with_env
    assert accepted.model == expected.model
    assert accepted.effort == expected.effort
    assert accepted.provenance["source"] == "env"
    assert accepted.provenance.get("env_override_refused") is None


def test_codex_effort_is_part_of_the_pin() -> None:
    """EFFORT IS PART OF THE PIN (design §11.4 M1).

    `xhigh` is what this arm inherits from config.toml today, so the pin makes
    today's behaviour explicit rather than changing it. An unpinned effort is
    how a TUI selection silently reprices every headless audit.
    """
    assert audit_spawn.CODEX_EFFORT == "xhigh"


def test_codex_argv_pins_both_axes_before_the_prompt() -> None:
    """`-m <model> -c model_reasoning_effort=<effort>`, then the prompt.

    Both are `codex exec` options and MUST precede the PROMPT positional. The
    defect being fixed is that the arm pinned NEITHER axis.
    """
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout="", returncode=1, stderr="")

    with _codex_spawn_patched(fake_run):
        audit_spawn.run_codex_auditor("PROMPT-SENTINEL", 60)

    cmd = captured["cmd"]
    assert "-m" in cmd, "the arm must never omit -m and inherit from config.toml"
    model = cmd[cmd.index("-m") + 1]
    assert model == audit_spawn.CODEX_MODEL and model
    effort_cfg = f"model_reasoning_effort={audit_spawn.CODEX_EFFORT}"
    assert effort_cfg in cmd
    assert cmd[cmd.index(effort_cfg) - 1] == "-c"
    # Both axes come from the emitter verbatim, and both land before the prompt.
    frag = codex_model.argv_fragment(audit_spawn.CODEX_MODEL, audit_spawn.CODEX_EFFORT)
    assert list(frag) == list(audit_spawn.CODEX_PIN.argv_fragment)
    # #291 fix round 2 N2: the PROMPT positional is `-` (read stdin); the prompt is on stdin.
    assert cmd[-1] == "-"
    assert captured["kwargs"]["input"] == "PROMPT-SENTINEL"
    assert "PROMPT-SENTINEL" not in cmd
    assert cmd.index("-m") < len(cmd) - 1
    assert cmd.index(effort_cfg) < len(cmd) - 1


def _captured_codex_cmd() -> List[str]:
    captured: Dict[str, Any] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout="", returncode=1, stderr="")

    with _codex_spawn_patched(fake_run):
        audit_spawn.run_codex_auditor("PROMPT-SENTINEL", 60)
    return captured["cmd"]


def test_no_codex_seat_is_ephemeral() -> None:
    """#302 design s3.4b / JC-3 (supersedes the S081 I6 selector rule): EVERY codex call is
    metered, whatever role's seat it serves - an ephemeral session writes no rollout, so the
    quota a support-tier call spent (terra) could never be read. The selector no longer decides
    --ephemeral: the switch is gone and no argv this module builds carries the flag.

    Each codex role's pin is resolved (fail-open, the autouse tmp HOME) and planted as the arm's
    pin, the non-TOP consultant_support row included - the row that used to run ephemeral."""
    assert not hasattr(audit_spawn, "CODEX_EPHEMERAL")
    source = Path(audit_spawn.__file__).read_text(encoding="utf-8")
    assert '"--ephemeral"' not in source and "'--ephemeral'" not in source
    roles = [role for role in sorted(seat_model.ROLES) if seat_model.CODEX in seat_model.ROLE_TABLE[role]]
    assert "consultant_support" in roles and seat_model.is_top("consultant_support", "codex") is False
    for role in roles:
        pin = seat_model.resolve(role, seat_model.CODEX, fail_open=True)
        with mock.patch.object(audit_spawn, "CODEX_PIN", pin):
            cmd = _captured_codex_cmd()
        assert "--ephemeral" not in cmd, (role, cmd)
        assert cmd[:2] == [audit_spawn.CODEX_BIN, "exec"], role
        assert cmd[-1] == "-"  # the prompt is on stdin (#291 fix round 2 N2)


# ---------------------------------------------------------------------------
# STDIN RULE (#155 / design D6) — BOTH arms
# ---------------------------------------------------------------------------

def test_codex_arm_closes_stdin() -> None:
    """#291 fix round 2 N2: the rule now reads "stdin EOFs", not "stdin is DEVNULL" -- the
    prompt is fed from a regular file (which EOFs at its end) instead of argv (E2BIG).

    Verified live on codex 0.153.4: `codex exec` prints "Reading additional
    input from stdin..." and waits. An inherited never-EOFing stdin hangs the
    arm at 0 bytes before any API call, and the CLI's print-timeout does not
    fire because it guards only the print phase.

    RE-POINTED (S081 revision 4, WP-A03): the RULE is unchanged and so is this
    test's question — does the codex arm's real spawn close stdin? Only the seam
    moved. Before D24 the arm called `subprocess.run(stdin=DEVNULL)` itself; it now
    delegates the spawn to codex_watch, so the guarantee is asserted at the Popen
    the watchdog actually makes. Asserting it on the old seam would have quietly
    become vacuous — the arm no longer passes through it.
    """
    captured: Dict[str, Any] = {}

    class _DoneProc:
        pid = 4321
        returncode = 0

        def poll(self):      # finished on the first sample: no polling loop
            return 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(argv, **kwargs):
        captured.update(kwargs)
        captured["argv"] = list(argv)
        handle = kwargs.get("stdin")
        captured["stdin_mode"] = os.fstat(handle.fileno()).st_mode if hasattr(handle, "fileno") else None
        captured["stdin_bytes"] = handle.read() if hasattr(handle, "read") else None
        return _DoneProc()

    with mock.patch.object(codex_watch.subprocess, "Popen", side_effect=fake_popen):
        audit_spawn.run_codex_auditor("prompt", 60)

    # #291 fix round 2 N2: stdin is no longer DEVNULL but the prompt, from a REGULAR FILE,
    # which reaches EOF at its end -- never a pipe, never inherited (both could hang).
    assert captured.get("stdin") not in (None, subprocess.PIPE, subprocess.DEVNULL)
    assert stat.S_ISREG(captured["stdin_mode"])
    assert captured["stdin_bytes"] == b"prompt"
    assert captured["argv"][-1] == "-"
    assert "input" not in captured, "never a pipe the parent must feed (Popen input=)"
    assert "prompt" not in captured["argv"], "never argv, where a >128 KiB prompt is E2BIG"


def test_claude_arm_closes_stdin() -> None:
    """Same rule, other transport (#291 fix round 1 B, the sibling of #290): the Claude arm's
    prompt travels on a piped stdin (`input=`), which EOFs as soon as it is written, never in
    argv, where a >128 KiB prompt is E2BIG. Encoded UTF-8, never the locale codec (C)."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        captured["cmd"] = list(cmd)
        return SimpleNamespace(stdout="", returncode=1, stderr="")

    with _codex_spawn_patched(fake_run):
        audit_spawn.run_claude_auditor("prompt", 60)

    assert captured.get("input") == "prompt"
    assert "stdin" not in captured  # subprocess.run refuses stdin= together with input=
    assert "prompt" not in captured["cmd"]
    assert (captured.get("encoding"), captured.get("errors")) == ("utf-8", "replace")


# ---------------------------------------------------------------------------
# Provenance — REQUESTED and REPORTED recorded separately (design §4.6 / D7)
# ---------------------------------------------------------------------------

#: A verbatim slice of real `codex exec` stderr, captured 2026-09-09 against
#: codex 0.153.4. The banner precedes the API call and is the ONLY sanctioned
#: source for what codex actually ran.
REAL_CODEX_STDERR = (
    "Reading additional input from stdin...\n"
    "OpenAI Codex v0.153.4\n"
    "--------\n"
    "workdir: /tmp/scratch\n"
    "model: gpt-5.6-sol\n"
    "provider: openai\n"
    "approval: never\n"
    "sandbox: read-only\n"
    "reasoning effort: low\n"
    "--------\n"
    "user\n"
    "Reply with exactly: OK\n"
)


def test_banner_parser_reads_the_real_stderr_shape() -> None:
    model, effort = audit_spawn._extract_codex_banner(REAL_CODEX_STDERR)
    assert model == "gpt-5.6-sol"
    assert effort == "low"


def test_banner_is_unknown_when_absent_never_backfilled() -> None:
    """Unavailable evidence stays `unknown`; it is NEVER the request echoed back.

    Backfilling the requested slug into the reported field is what turns a
    provenance record into a tautology that can never disagree with the config.
    """
    for stderr in ("", None, "some unrelated noise\n"):
        model, effort = audit_spawn._extract_codex_banner(stderr)
        assert model == audit_spawn.MODEL_UNKNOWN
        assert effort == audit_spawn.MODEL_UNKNOWN
        assert model != audit_spawn.CODEX_MODEL


def test_banner_first_match_wins_over_a_prompt_echo() -> None:
    """codex echoes the prompt onto the SAME stream after the banner, so a
    prompt containing its own `model:` line must not displace the real one."""
    stderr = REAL_CODEX_STDERR + "model: attacker-supplied\n"
    model, _ = audit_spawn._extract_codex_banner(stderr)
    assert model == "gpt-5.6-sol"


def test_codex_arm_records_requested_and_reported_separately() -> None:
    sink: dict = {}

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="", returncode=1, stderr=REAL_CODEX_STDERR)

    with _codex_spawn_patched(fake_run):
        audit_spawn.run_codex_auditor("prompt", 60, sink)

    assert sink["requested_model"] == audit_spawn.CODEX_MODEL
    assert sink["requested_effort"] == audit_spawn.CODEX_EFFORT
    assert sink["requested_source"] in seat_model.SOURCES  # S081 WP-R06: seat_model's source set
    assert sink["reported_model"] == "gpt-5.6-sol"
    assert sink["reported_effort"] == "low"
    assert sink["reported_source"] == "codex_stderr_banner"


def test_provenance_is_captured_even_on_a_failing_run() -> None:
    """A non-zero exit is exactly when knowing the model matters. The banner
    prints before the API call, so it is read before the returncode check."""
    sink: dict = {}

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="", returncode=7, stderr=REAL_CODEX_STDERR)

    with _codex_spawn_patched(fake_run):
        verdict, err = audit_spawn.run_codex_auditor("prompt", 60, sink)

    assert verdict is None and err and "exited 7" in err
    assert sink["reported_model"] == "gpt-5.6-sol"


def test_spawn_failure_leaves_reported_unknown() -> None:
    """No process, no banner. The requested side is still recorded."""
    sink: dict = {}
    with _codex_spawn_patched(FileNotFoundError()):
        verdict, err = audit_spawn.run_codex_auditor("prompt", 60, sink)

    assert verdict is None and err
    assert sink["reported_model"] == audit_spawn.MODEL_UNKNOWN
    assert sink["requested_model"] == audit_spawn.CODEX_MODEL


# ---------------------------------------------------------------------------
# S081 stream 1 — P0 containment (design §4.1, WP-P01)
# ---------------------------------------------------------------------------

#: Every variable that can steer a reviewer arm. Scrubbed from child envs so a
#: developer shell that happens to set one cannot make a test pass or fail.
_REVIEWER_ENV = (
    "AUDIT_CLAUDE_MODEL", "ARBITER_CLAUDE_MODEL", "AUDIT_CODEX_MODEL",
    "AUDIT_CLAUDE_BIN", "AUDIT_CODEX_BIN",
)
#: The resolver the PRE-S081 wiring invoked, from this test's own tree.
_RESOLVER = _META.parent / "smart-config" / "scripts" / "model_policy.py"
_POSIX_ONLY = pytest.mark.skipif(
    os.name == "nt", reason="stub reviewer binaries use a POSIX shebang"
)
_POISON = "version: 1\ntiers:\n  complex:\n    claude-code: haiku\n"


def _iso_now(offset_s: float = 0.0) -> str:
    return datetime.fromtimestamp(time.time() + offset_s, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: (slug, priority, visibility, efforts) — the SHAPE of the 2026-09-14 live roster:
#: astra is the priority-1 listed TOP, gpt-reserve is hidden, sol is listed at p4.
_LIVE_LIKE_ROSTER = (
    ("gpt-6-astra", 1, "list", ["low", "medium", "high", "xhigh", "max", "ultra"]),
    ("gpt-reserve", 3, "hide", ["low", "medium", "high", "xhigh", "max"]),
    ("gpt-5.6-sol", 4, "list", ["low", "medium", "high", "xhigh", "max", "ultra"]),
    ("gpt-5.5", 12, "list", ["low", "medium", "high", "xhigh"]),
)


def _write_fixture_roster(path: Path, models: Any, fetched_at: Optional[str] = None) -> str:
    """A codex roster in the LIVE object shape (levels are objects keyed `effort`).

    `models` is either {slug: efforts} (all listed, priority = position, so the first
    entry is TOP) or a sequence of (slug, priority, visibility, efforts). `fetched_at`
    defaults to NOW so seat_model never sees the fixture as a stale roster. Returns it.
    """
    if isinstance(models, dict):
        rows = [(slug, i + 1, "list", efforts) for i, (slug, efforts) in enumerate(models.items())]
    else:
        rows = list(models)
    fetched_at = fetched_at or _iso_now()
    doc = {
        "fetched_at": fetched_at,
        "client_version": "fixture",
        "models": [
            {
                "slug": slug,
                "priority": priority,
                "supported_reasoning_levels": [{"effort": e} for e in efforts],
                "visibility": visibility,
                "supported_in_api": True,
                "upgrade": None,
            }
            for slug, priority, visibility, efforts in rows
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return fetched_at


def _write_freeze(home: Path, codex_top: str) -> Path:
    pins = home / ".claude" / "state" / "seat-model-pins.json"
    pins.parent.mkdir(parents=True, exist_ok=True)
    pins.write_text(json.dumps({
        "schema": "seat-model-pins.v1",
        "pins": {"codex": {"top": codex_top, "set_at": _iso_now(), "reason": "fixture freeze"}},
    }), encoding="utf-8")
    return pins


def _seat_home(home: Path, *, freeze: Optional[str] = None, roster: Any = _LIVE_LIKE_ROSTER) -> str:
    """Populate `home` with a fixture codex roster (and a codex freeze when given)."""
    fetched_at = _write_fixture_roster(home / ".codex" / "models_cache.json", roster)
    if freeze is not None:
        _write_freeze(home, freeze)
    return fetched_at


def _fixture_home(tmp_path: Path) -> Path:
    """HOME for child processes: a fixture roster, and a COPY of smart-config's
    resolver at the exact `~/.claude/...` path the pre-S081 wiring called. The
    copy makes the poisoned-cwd test a real regression guard: re-adding that
    call would read the poisoned project layer again, not a missing file.

    The roster lists sol first, so the code_reviewer TOP @ xhigh is sol with no
    freeze (source roster)."""
    home = tmp_path / "home"
    _write_fixture_roster(
        home / ".codex" / "models_cache.json",
        {
            codex_model.DEFAULT_MODEL: ["low", "medium", "high", "xhigh", "max"],
            # Listed on purpose: the pre-S081 roster-membership check ACCEPTED it.
            "gpt-5.5": ["low", "medium", "high", "xhigh"],
        },
    )
    dst = home / ".claude" / "skills" / "smart-config" / "scripts"
    dst.mkdir(parents=True)
    shutil.copy2(_RESOLVER, dst / "model_policy.py")
    return home


def _poisoned_cwd(tmp_path: Path) -> Path:
    """A repo that tries to steer its own reviewer three ways: a smart-config policy,
    a repo-local freeze pin and a repo-local codex roster (WP-R06 adds the last two;
    seat_model must read none of them)."""
    cwd = tmp_path / "poisoned-repo"
    (cwd / ".claude").mkdir(parents=True)
    (cwd / ".claude" / "model-policy.yaml").write_text(_POISON, encoding="utf-8")
    _write_freeze(cwd, "gpt-5.5")
    _write_fixture_roster(cwd / ".codex" / "models_cache.json", {"gpt-5.5": ["xhigh"]})
    return cwd


def _child_env(home: Path, **overrides: str) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _REVIEWER_ENV}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.update(overrides)
    return env


_PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import audit_spawn as m
build = getattr(m, "_build_model_provenance", None)
print(json.dumps({
    "claude_model": m.CLAUDE_MODEL,
    "claude_source": getattr(m, "CLAUDE_MODEL_SOURCE", None),
    "codex_model": m.CODEX_MODEL,
    "codex_effort": m.CODEX_EFFORT,
    "codex_timeout": m.CODEX_TIMEOUT_S,
    "codex_source": m.CODEX_MODEL_SOURCE,
    "cache_path": str(m.seat_model._paths().codex_roster),
    "provenance": build(600, m.CODEX_TIMEOUT_S, {}) if build else None,
}))
"""


def _probe(cwd: Path, env: Dict[str, str]) -> Tuple[dict, str]:
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(_META)],
        cwd=str(cwd), env=env, capture_output=True, text=True,
        encoding="utf-8", timeout=60, stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1]), proc.stderr


def test_poisoned_cwd_cannot_downgrade_the_claude_reviewer(tmp_path: Path) -> None:
    """L1 TRUST. A repo file must not pick the model that reviews that repo."""
    home = _fixture_home(tmp_path)
    cwd = _poisoned_cwd(tmp_path)
    env = _child_env(home)

    # POSITIVE CONTROL — the fixture really poisons smart-config in THIS cwd.
    resolver = home / ".claude" / "skills" / "smart-config" / "scripts" / "model_policy.py"
    ctl = subprocess.run(
        [sys.executable, str(resolver), "resolve", "--tier", "complex",
         "--surface", "headless", "--no-log"],
        cwd=str(cwd), env=env, capture_output=True, text=True,
        encoding="utf-8", timeout=60, stdin=subprocess.DEVNULL,
    )
    assert ctl.returncode == 0, ctl.stderr
    poisoned = json.loads(ctl.stdout.strip().splitlines()[-1])
    assert poisoned["model"] == "haiku" and poisoned["source"] == "project"
    # POSITIVE CONTROL — the SAME freeze file in HOME would move the codex reviewer.
    moved = tmp_path / "moved-home"
    shutil.copytree(home, moved)
    _write_freeze(moved, "gpt-5.5")
    moved_state, _ = _probe(tmp_path, _child_env(moved))
    assert (moved_state["codex_model"], moved_state["codex_source"]) == ("gpt-5.5", "freeze")

    state, _ = _probe(cwd, env)
    # Isolation guard: the child read the FIXTURE roster, not the live one.
    assert Path(state["cache_path"]).resolve() == (home / ".codex" / "models_cache.json").resolve()
    assert state["claude_model"] == MAIN
    assert state["claude_source"] == "harness_literal"
    # The repo-local freeze (gpt-5.5) and roster were ignored: HOME's roster TOP serves.
    assert (state["codex_model"], state["codex_source"]) == (codex_model.DEFAULT_MODEL, "roster")


def _calls_mentioning(tree: ast.AST, needle: str) -> List[ast.Call]:
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and needle in sub.value:
                    hits.append(node)
                    break
    return hits


def _uses_subprocess(func: ast.FunctionDef) -> bool:
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and node.id == "subprocess":
            return True
    return False


def _calls_seat_model_resolve(func: ast.FunctionDef) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "resolve" and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "seat_model"
        for node in ast.walk(func)
    )


#: The pre-S081 shape, verbatim in structure — the detectors must flag it.
_PRE_S081_SHAPE = '''
def _resolve_claude_pin(env_var, hardcoded):
    resolver = os.path.expanduser("~/.claude/skills/smart-config/scripts/model_policy.py")
    proc = subprocess.run(["python3", resolver, "resolve", "--tier", "complex"])
    return hardcoded
'''


def test_resolution_never_invokes_smart_config() -> None:
    """L1: no call site builds a model_policy.py path, and neither resolution
    function has a subprocess (NEGATIVE CONTROL: the pre-S081 shape is flagged by
    both detectors). WP-R06: both functions resolve through seat_model, and stream 1's
    ad-hoc gating function is gone rather than duplicated."""
    control = ast.parse(_PRE_S081_SHAPE)
    assert _calls_mentioning(control, "model_policy")
    assert _uses_subprocess(control.body[0])
    assert not _calls_seat_model_resolve(control.body[0])

    tree = ast.parse(Path(audit_spawn.__file__).read_text(encoding="utf-8"))
    assert _calls_mentioning(tree, "model_policy") == []
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name in ("_resolve_claude_pin", "_resolve_codex_pin"):
        assert not _uses_subprocess(funcs[name]), name
        assert _calls_seat_model_resolve(funcs[name]), name
    assert "_resolve_spawn_model" not in funcs
    assert not hasattr(audit_spawn, "_AUDIT_HARDCODED_MODEL")


def test_claude_env_override_is_gated_to_the_pin() -> None:
    """L2: a downgrade is refused and recorded; the equal value is accepted.
    Carried forward from stream 1 onto seat_model's provenance."""
    with mock.patch.dict(os.environ, {"AUDIT_CLAUDE_MODEL": "haiku"}):
        pin = audit_spawn._resolve_claude_pin()
    assert (pin.model, pin.provenance["source"]) == (MAIN, "harness_literal")
    refused = pin.provenance["env_override_refused"]
    assert {k: refused[k] for k in ("var", "value")} == {"var": "AUDIT_CLAUDE_MODEL", "value": "haiku"}
    assert "protected" in refused["reason"]

    # CONTROL: equal to the pin -> honoured, and the source says so.
    with mock.patch.dict(os.environ, {"AUDIT_CLAUDE_MODEL": MAIN}):
        pin = audit_spawn._resolve_claude_pin()
    assert (pin.model, pin.provenance["source"], pin.provenance.get("env_override_refused")) == (
        MAIN, "env", None)

    clean = {k: v for k, v in os.environ.items() if k != "AUDIT_CLAUDE_MODEL"}
    with mock.patch.dict(os.environ, clean, clear=True):
        pin = audit_spawn._resolve_claude_pin()
    assert (pin.model, pin.provenance["source"], pin.provenance.get("env_override_refused")) == (
        MAIN, "harness_literal", None)
    # L4: the declared fallback is the role row's alias, the Claude main tier (MAIN, from model_roster).
    assert pin.provenance["resolved_model"] == MAIN
    assert seat_model.ROLE_TABLE["code_reviewer"]["claude"].value == MAIN


def test_codex_env_override_is_gated_to_the_resolved_model(_isolated_home: Path, tmp_path: Path) -> None:
    """L2 / I3: roster membership is no longer enough — gpt-5.5 IS listed."""
    roster = _isolated_home / ".codex" / "models_cache.json"
    _write_fixture_roster(
        roster,
        {codex_model.DEFAULT_MODEL: ["xhigh"], "gpt-5.5": ["low", "xhigh"]},
    )
    with mock.patch.dict(os.environ, {"AUDIT_CODEX_MODEL": "gpt-5.5"}):
        # Premise: the pre-S081 wiring (env layer straight into resolve) accepted it.
        legacy = codex_model.resolve(
            codex_model.AUDIT_CODEX_ARM, env_var="AUDIT_CODEX_MODEL",
            fail_open=True, cache_path=roster,
        )
        pin = audit_spawn._resolve_codex_pin()
    assert (legacy.model, legacy.provenance_source) == ("gpt-5.5", "env")
    assert pin.model == codex_model.DEFAULT_MODEL
    assert pin.provenance["source"] == "roster"  # seat_model's name for codex_model's "data"
    refused = pin.provenance["env_override_refused"]
    assert {k: refused[k] for k in ("var", "value")} == {"var": "AUDIT_CODEX_MODEL", "value": "gpt-5.5"}

    # CONTROL: the arm's own resolved slug is accepted with source env.
    with mock.patch.dict(os.environ, {"AUDIT_CODEX_MODEL": codex_model.DEFAULT_MODEL}):
        pin = audit_spawn._resolve_codex_pin()
    assert (pin.model, pin.provenance["source"], pin.provenance.get("env_override_refused")) == (
        codex_model.DEFAULT_MODEL, "env", None,
    )


_STUB = """#!{python}
import json, os, sys
with open(os.environ["STUB_ARGV_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({{"bin": os.path.basename(sys.argv[0]), "argv": sys.argv[1:]}}) + "\\n")
sys.stdout.write(os.environ["STUB_VERDICT_JSON"])
"""


def _write_stub(path: Path, template: str = _STUB) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.format(python=sys.executable), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _audit_verdict() -> dict:
    return {
        "verdict": "pass",
        "structured_disagreements": [
            {"point": "p1", "severity": "minor", "location": "comp-x"},
            {"point": "p2", "severity": "minor", "location": "comp-x"},
            {"point": "p3", "severity": "moderate", "location": "comp-x"},
        ],
        "evidence_verified": True,
        "reason": "fixture",
    }


def _audit_verdict_json() -> str:
    return json.dumps(_audit_verdict())


def _audit_project(tmp_path: Path, note: Optional[str] = None) -> Tuple[Path, Path]:
    """A minimal project + trusted bundle. `note` (WP-F03) puts arbitrary evidence text
    into the bundle, and so into the prompt codex echoes onto stderr."""
    root = tmp_path / "proj"
    (root / "progress").mkdir(parents=True)
    (root / "progress" / "contract-map.yaml").write_text(
        "revision: 1\ncomponents:\n  - id: comp-x\n    success_criteria: []\n",
        encoding="utf-8",
    )
    bundle = root / "bundle.json"
    body: Dict[str, Any] = {"produced_by": "bob-trusted-runner", "component_id": "comp-x",
                            "bundle_hash": "e" * 64}
    if note is not None:
        body["note"] = note
    bundle.write_text(json.dumps(body), encoding="utf-8")
    return root, bundle


def _run_audit_cli(tmp_path: Path, env: Dict[str, str]) -> Tuple[dict, str, List[dict]]:
    root, bundle = _audit_project(tmp_path)
    argv_log = tmp_path / "argv.jsonl"
    env = dict(env, STUB_ARGV_LOG=str(argv_log), STUB_VERDICT_JSON=_audit_verdict_json())
    proc = subprocess.run(
        [sys.executable, str(_META / "audit_spawn.py"), "comp-x", str(bundle),
         "--project-root", str(root)],
        cwd=str(_poisoned_cwd(tmp_path)), env=env, capture_output=True, text=True,
        encoding="utf-8", timeout=120, stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    calls = [json.loads(l) for l in argv_log.read_text(encoding="utf-8").splitlines() if l]
    return json.loads(proc.stdout), proc.stderr, calls


def _spawn_rows(tmp_path: Path) -> Dict[str, dict]:
    """The spawn-runs rows `_run_audit_cli` left in its project root, keyed by tool."""
    path = tmp_path / "proj" / ".process-observations" / "spawn-runs.jsonl"
    return {row["tool"]: row for row in (
        json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())}


def _argv_of(calls: List[dict], name: str) -> List[str]:
    return next(c["argv"] for c in calls if name in c["bin"])


def _refusal(block: dict) -> dict:
    """The {var, value} of a seat_model refusal record, after checking its shape."""
    record = block["env_override_refused"]
    assert set(record) == {"var", "value", "reason"}
    return {"var": record["var"], "value": record["value"]}


@_POSIX_ONLY
def test_refusals_and_bin_overrides_reach_the_verdict_provenance(tmp_path: Path) -> None:
    """L2 + BIN, end to end through the real CLI with stub reviewer binaries."""
    home = _fixture_home(tmp_path)
    claude_stub = _write_stub(tmp_path / "bin" / "claude-stub")
    codex_stub = _write_stub(tmp_path / "bin" / "codex-stub")
    link = tmp_path / "bin" / "claude-link"
    try:
        link.symlink_to(claude_stub)
        claude_bin = link  # realpath must see THROUGH the link
    except (OSError, NotImplementedError):
        claude_bin = claude_stub
    env = _child_env(
        home,
        AUDIT_CLAUDE_MODEL="haiku", AUDIT_CODEX_MODEL="gpt-5.5",
        AUDIT_CLAUDE_BIN=str(claude_bin), AUDIT_CODEX_BIN=str(codex_stub),
    )
    out, stderr, calls = _run_audit_cli(tmp_path, env)

    assert out["result"] == "VERIFIED"
    claude = out["model_provenance"]["claude"]
    codex = out["model_provenance"]["codex"]
    assert claude["requested"] == MAIN
    assert claude["requested_source"] == "harness_literal"
    assert _refusal(claude) == {"var": "AUDIT_CLAUDE_MODEL", "value": "haiku"}
    assert claude["bin_override"] == {
        "var": "AUDIT_CLAUDE_BIN", "value": str(claude_bin),
        "realpath": os.path.realpath(str(claude_stub)),
    }
    assert codex["requested"] == codex_model.DEFAULT_MODEL
    assert _refusal(codex) == {"var": "AUDIT_CODEX_MODEL", "value": "gpt-5.5"}
    assert codex["bin_override"]["realpath"] == os.path.realpath(str(codex_stub))
    # What actually ran: the pins, not the refused values.
    claude_argv = _argv_of(calls, "claude")
    assert claude_argv[claude_argv.index("--model") + 1] == MAIN
    codex_argv = _argv_of(calls, "codex")
    assert codex_argv[codex_argv.index("-m") + 1] == codex_model.DEFAULT_MODEL
    for var in ("AUDIT_CLAUDE_MODEL", "AUDIT_CODEX_MODEL", "AUDIT_CLAUDE_BIN", "AUDIT_CODEX_BIN"):
        assert any(var in line and "WARNING" in line for line in stderr.splitlines()), var
    # Written at import: non-ASCII here could raise on a cp1252 console (W003).
    assert stderr.isascii()
    # S081 WP-R06 (plan I2): the same refusal records ride each arm's telemetry row.
    rows = _spawn_rows(tmp_path)
    assert rows["audit_claude"]["env_override_refused"] == claude["env_override_refused"]
    assert rows["audit_codex"]["env_override_refused"] == codex["env_override_refused"]


@_POSIX_ONLY
def test_equal_overrides_accepted_and_unset_bins_leave_no_field(tmp_path: Path) -> None:
    """CONTROL for the test above: the SAME stubs, reached via PATH with the BIN
    variables unset, and env overrides equal to the pins."""
    home = _fixture_home(tmp_path)
    bindir = tmp_path / "pathbin"
    _write_stub(bindir / "claude")
    _write_stub(bindir / "codex")
    env = _child_env(
        home,
        AUDIT_CLAUDE_MODEL=MAIN, AUDIT_CODEX_MODEL=codex_model.DEFAULT_MODEL,
    )
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    out, stderr, calls = _run_audit_cli(tmp_path, env)

    claude = out["model_provenance"]["claude"]
    codex = out["model_provenance"]["codex"]
    assert (claude["requested"], claude["requested_source"]) == (MAIN, "env")
    assert (codex["requested"], codex["requested_source"]) == (codex_model.DEFAULT_MODEL, "env")
    for block in (claude, codex):
        assert "env_override_refused" not in block
        assert "bin_override" not in block
    assert "WARNING" not in stderr
    assert {c["bin"] for c in calls} == {"claude", "codex"}
    rows = _spawn_rows(tmp_path)
    assert sorted(rows) == ["audit_claude", "audit_codex"]
    for row in rows.values():
        assert "env_override_refused" not in row


def test_live_import_keeps_both_pins() -> None:
    """In-process import with a clean env: fable, no refusal, no binary override.

    HOME-independent facts only (the Claude adapter reads nothing): this module's
    import ran under an empty HOME, so the codex slug here is not evidence of the live
    pin — the LIVE check lives in the WP-R06 stage record."""
    if any(os.environ.get(v) for v in _REVIEWER_ENV):
        pytest.skip("a reviewer override is set in this shell")
    assert audit_spawn.CLAUDE_MODEL == MAIN
    assert audit_spawn.CLAUDE_MODEL_SOURCE == "harness_literal"
    assert audit_spawn.CLAUDE_ENV_OVERRIDE_REFUSED is None
    assert audit_spawn.CLAUDE_BIN_OVERRIDE is None
    assert audit_spawn.CODEX_BIN_OVERRIDE is None
    assert audit_spawn.CODEX_EFFORT == "xhigh"
    prov = audit_spawn._build_model_provenance(600, audit_spawn.CODEX_TIMEOUT_S, {})
    assert "bin_override" not in prov["claude"] and "bin_override" not in prov["codex"]


# ---------------------------------------------------------------------------
# S081 WP-R06 — seat_model provenance in the verdict
# ---------------------------------------------------------------------------

_OPTIONAL_SEAT_KEYS = ("roster_stale", "fallback_reason", "upgrade_followed", "upgrade_ignored_reason",
                       "roster_invalid")  # #282 R4 (K14): the invalid-roster event key rides the same rule


def test_model_provenance_carries_the_seat_provenance() -> None:
    """source / requested_selector / roster_fetched_at always; the event keys exactly
    when seat_model recorded the event (absent means "did not happen")."""
    prov = audit_spawn._build_model_provenance(600, audit_spawn.CODEX_TIMEOUT_S, {})
    for arm, pin in (("claude", audit_spawn.CLAUDE_PIN), ("codex", audit_spawn.CODEX_PIN)):
        block = prov[arm]
        assert block["source"] == pin.provenance["source"] == block["requested_source"]
        assert block["requested_selector"] == pin.provenance["requested_selector"]
        assert block["roster_fetched_at"] == pin.provenance["roster_fetched_at"]
        for key in _OPTIONAL_SEAT_KEYS:
            assert (key in block) == (key in pin.provenance), (arm, key)
    assert prov["claude"]["requested_selector"] == MAIN
    assert prov["codex"]["requested_selector"] == "TOP@xhigh"


def test_provenance_records_a_fail_open_fallback(_isolated_home: Path) -> None:
    """A roster that lists no eligible model is a failure; the fail-open arm serves the
    harness literal and SAYS SO (fallback_reason). CONTROL: a usable roster records none."""
    _seat_home(_isolated_home, roster=[("gpt-5.5", 1, "list", ["low"])])  # nothing supports xhigh
    pin = audit_spawn._resolve_codex_pin()
    assert (pin.model, pin.provenance["source"]) == (seat_model.CODEX_TOP_HARNESS_LITERAL, "harness_literal")
    with mock.patch.object(audit_spawn, "CODEX_PIN", pin):
        block = audit_spawn._build_model_provenance(600, 600, {})["codex"]
    assert "no eligible" in block["fallback_reason"] or "xhigh" in block["fallback_reason"]

    _seat_home(_isolated_home)
    pin = audit_spawn._resolve_codex_pin()
    assert pin.provenance["source"] == "roster" and "fallback_reason" not in pin.provenance
    with mock.patch.object(audit_spawn, "CODEX_PIN", pin):
        block = audit_spawn._build_model_provenance(600, 600, {})["codex"]
    assert "fallback_reason" not in block


# ---------------------------------------------------------------------------
# #282 R4 (plan K14) — an invalid codex roster is a RECORDED harness literal, never an
# import-time exception. Before R4 a roster entry with `supported_reasoning_levels: true`
# raised TypeError out of codex_model, through seat_model, and out of `import audit_spawn`.
# ---------------------------------------------------------------------------

def _write_invalid_roster(home: Path) -> None:
    """The live-like roster with astra's `supported_reasoning_levels` set to `true`."""
    _seat_home(home)
    path = home / ".codex" / "models_cache.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["models"][0]["supported_reasoning_levels"] = True
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_r4_an_invalid_roster_at_import_is_a_recorded_harness_literal(tmp_path: Path) -> None:
    home = tmp_path / "invalid-home"
    _write_invalid_roster(home)
    state, stderr = _probe(tmp_path, _child_env(home))            # asserts the child exits 0
    assert "Traceback" not in stderr
    assert Path(state["cache_path"]).resolve() == (home / ".codex" / "models_cache.json").resolve()
    # RE-POINTED (S081 revision 4, WP-A03; expected_red_set): the harness-literal fallback
    # reports the RAISED xhigh timeout (600 -> 2400, WP-A02/D24). The literal MODEL and the
    # "harness_literal" source — what this test is actually about — are unchanged.
    assert (state["codex_model"], state["codex_effort"], state["codex_timeout"], state["codex_source"]) == (
        seat_model.CODEX_TOP_HARNESS_LITERAL, "xhigh", 2400, "harness_literal")
    codex = state["provenance"]["codex"]
    assert codex["roster_invalid"] is True and codex["fallback_reason"]
    assert "unavailable_reason" not in codex
    assert "roster_invalid" not in state["provenance"]["claude"]
    # CONTROL: the same HOME with a valid roster -> source roster, no event key
    control = tmp_path / "valid-home"
    _seat_home(control)
    ok, _ = _probe(tmp_path, _child_env(control))
    assert (ok["codex_model"], ok["codex_source"]) == ("gpt-6-astra", "roster")
    assert "roster_invalid" not in ok["provenance"]["codex"] and "fallback_reason" not in ok["provenance"]["codex"]


def test_r4_an_invalid_roster_is_never_a_plan_time_substitution(_isolated_home: Path) -> None:
    """The D6 no_eligible_model substitution is unchanged, and an invalid roster is not it: the arm
    runs the recorded literal. CONTROL: an all-hidden (valid) roster is no_eligible_model."""
    _write_invalid_roster(_isolated_home)
    pin = audit_spawn._resolve_codex_pin()
    assert (pin.model, pin.provenance["source"], pin.provenance["roster_invalid"]) == (
        "gpt-6-astra", "harness_literal", True)
    with mock.patch.object(audit_spawn, "CODEX_PIN", pin), \
            mock.patch.object(audit_spawn, "_codex_cli_missing", return_value=False):
        assert audit_spawn._plan_time_unavailable() is None
        assert audit_spawn._build_model_provenance(600, 600, {})["codex"]["roster_invalid"] is True
    _seat_home(_isolated_home, roster=_ALL_HIDDEN_ROSTER)
    hidden = audit_spawn._resolve_codex_pin()
    assert "roster_invalid" not in hidden.provenance
    with mock.patch.object(audit_spawn, "CODEX_PIN", hidden), \
            mock.patch.object(audit_spawn, "_codex_cli_missing", return_value=False):
        assert audit_spawn._plan_time_unavailable() == seat_model.UNAVAILABLE_NO_ELIGIBLE
        assert "roster_invalid" not in audit_spawn._build_model_provenance(600, 600, {})["codex"]


@_POSIX_ONLY
def test_r4_an_invalid_roster_audit_runs_codex_on_the_literal_and_records_it(tmp_path: Path) -> None:
    """End to end through the real CLI: the codex arm is spawned with the harness literal (no
    substitution, no substitution row) and the verdict's codex block records roster_invalid."""
    home = _substitution_home(tmp_path, freeze=None)
    doc_path = home / ".codex" / "models_cache.json"
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    doc["models"][0]["supported_reasoning_levels"] = True
    doc_path.write_text(json.dumps(doc), encoding="utf-8")
    run = _run_substitution_cli(tmp_path, home, codex_plan=["ok"], claude_plan=[_PASS])
    assert "Traceback" not in run["stderr"]
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", run["out"]
    assert len(run["codex"]) == 1 and _model_arg(run["codex"][0], "-m") == "gpt-6-astra"
    block = run["out"]["model_provenance"]["codex"]
    assert (block["source"], block["roster_invalid"]) == ("harness_literal", True)
    _assert_no_substitution(run)


# ---------------------------------------------------------------------------
# S081 WP-R06 — the meter, exhaustion signals and token usage (design §4.7, §4.11)
# ---------------------------------------------------------------------------

_SESSION_ID = "01a0a02a-bdf9-7281-b75e-d9ce6c8f591b"

#: The banner shape observed from codex 0.154.0 (session id line included).
REAL_CODEX_0154_STDERR = (
    "Reading additional input from stdin...\n"
    "OpenAI Codex v0.154.0\n"
    "--------\n"
    "workdir: /tmp/scratch\n"
    "model: gpt-5.6-sol\n"
    "provider: openai\n"
    "approval: never\n"
    "sandbox: read-only\n"
    "reasoning effort: xhigh\n"
    "reasoning summaries: none\n"
    f"session id: {_SESSION_ID}\n"
    "--------\n"
    "user\n"
)
_USAGE_LIMIT_LINE = (
    "ERROR: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
    "visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 6:12 PM.\n"
)


def _rollout_event(observed: float, primary: float, weekly: float,
                   tokens: Optional[Dict[str, int]] = None, reached_type: Optional[str] = None) -> dict:
    return {
        "timestamp": datetime.fromtimestamp(observed, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": None if tokens is None else {"total_token_usage": tokens, "last_token_usage": tokens},
            "rate_limits": {
                "limit_id": "codex", "limit_name": None,
                "primary": {"used_percent": primary, "window_minutes": 300,
                            "resets_at": int(observed + 7200)},
                "secondary": {"used_percent": weekly, "window_minutes": 10080,
                              "resets_at": int(observed + 72 * 3600)},
                "credits": None, "plan_type": "plus", "rate_limit_reached_type": reached_type,
            },
        },
    }


def _write_rollout(home: Path, session_id: str, events: List[dict], *, at: Optional[float] = None) -> Path:
    at = time.time() if at is None else at
    stamp = datetime.fromtimestamp(at, timezone.utc)
    day = home / ".codex" / "sessions" / stamp.strftime("%Y") / stamp.strftime("%m") / stamp.strftime("%d")
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-{stamp.strftime('%Y-%m-%dT%H-%M-%S')}-{session_id}.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


def test_meter_brackets_the_codex_call(_isolated_home: Path) -> None:
    """quota_before is read BEFORE the call and quota_after AFTER it: the fake call writes
    a newer rollout, and only the after-reading sees it. The row-safe reading drops the
    rollout PATH (rows land in a tracked file)."""
    now = time.time()
    _write_rollout(_isolated_home, "00000000-0000-0000-0000-00000000aaaa",
                   [_rollout_event(now - 60, 10.0, 5.0)], at=now - 60)

    def fake_run(cmd, **kwargs):
        _write_rollout(_isolated_home, _SESSION_ID,
                       [_rollout_event(time.time(), 12.0, 5.5, {"input_tokens": 900, "output_tokens": 40})])
        return SimpleNamespace(stdout=_audit_verdict_json(), returncode=0, stderr=REAL_CODEX_0154_STDERR)

    sink: dict = {}
    with _codex_spawn_patched(fake_run):
        verdict, err = audit_spawn.run_codex_auditor("prompt", 60, sink)
    assert err is None and verdict["verdict"] == "pass"
    assert (sink["quota_before"]["state"], sink["quota_before"]["primary_used_percent"]) == ("fresh", 10.0)
    assert (sink["quota_after"]["state"], sink["quota_after"]["primary_used_percent"]) == ("fresh", 12.0)
    assert sink["quota_source"] == audit_spawn.QUOTA_SOURCE_METER
    for reading in (sink["quota_before"], sink["quota_after"]):
        assert set(reading) == set(audit_spawn._QUOTA_ROW_KEYS) and "source" not in reading
    # I9: tokens from THIS call's rollout, found through the banner's session id.
    assert sink["tokens"] == {"input_tokens": 900, "output_tokens": 40}


def test_meter_is_read_only_when_something_records_it() -> None:
    """The legacy 2-arg call records nothing, so it reads nothing (CONTROL: with a sink,
    exactly one reading before and one after, even when the spawn itself fails)."""
    with mock.patch.object(audit_spawn.codex_quota, "snapshot", wraps=codex_quota.snapshot) as snap, \
            _codex_spawn_patched(lambda c, **k: SimpleNamespace(stdout="", returncode=1, stderr="")):
        audit_spawn.run_codex_auditor("prompt", 60)
    assert snap.call_count == 0

    sink: dict = {}
    with mock.patch.object(audit_spawn.codex_quota, "snapshot", wraps=codex_quota.snapshot) as snap, \
            _codex_spawn_patched(FileNotFoundError()):
        audit_spawn.run_codex_auditor("prompt", 60, sink)
    assert snap.call_count == 2
    assert sink["quota_before"]["state"] == "unknown" and sink["quota_after"]["state"] == "unknown"


def test_a_broken_meter_never_changes_the_audit() -> None:
    sink: dict = {}
    with mock.patch.object(audit_spawn.codex_quota, "snapshot", side_effect=RuntimeError("boom")), \
            _codex_spawn_patched(lambda c, **k: SimpleNamespace(
                                  stdout=_audit_verdict_json(), returncode=0, stderr="")):
        verdict, err = audit_spawn.run_codex_auditor("prompt", 60, sink)
    assert err is None and verdict["verdict"] == "pass"
    assert sink["quota_before"] is None and sink["quota_after"] is None


def _meter_rollout(home: Path, token: Optional[str]) -> None:
    """A fresh rollout under `home` whose unavailable() token is `token` (None: a healthy reading)."""
    now = time.time()
    primary, reached = {None: (10.0, None), "quota_exhausted": (99.5, None),
                        "rate_limit_reached": (40.0, "primary")}[token]
    _write_rollout(home, "00000000-0000-0000-0000-0000000000e1",
                   [_rollout_event(now - 60, primary, 5.0, reached_type=reached)], at=now - 60)
    assert codex_quota.unavailable() == token  # premise: the meter really says so


@pytest.mark.parametrize("line,signal,meter", [
    (_USAGE_LIMIT_LINE, "usage_limit", None),
    ("ERROR: You\u2019ve hit your usage limit.\n", "usage_limit", None),
    ("ERROR: exceeded retry limit, last status: 429 Too Many Requests\n", "http_429", None),
    # CARRIED FORWARD CORROBORATED by #282 R2: a bare line counts only while the meter agrees (its bare,
    # uncorroborated form is the negative in test_r2_a_bare_exhaustion_line_without_the_meter_is_not_a_stop).
    ("stream error: unexpected status 429 Too Many Requests: slow down\n", "http_429", "quota_exhausted"),
    ("ERROR: rate limit exceeded: try again later\n", "rate_limit_exceeded", None),
    ('{"rate_limits":{"rate_limit_reached_type":"primary"}}\n', "rate_limit_reached_type", "rate_limit_reached"),
    ("ERROR: Quota exceeded. Check your plan and billing details.\n", "quota_exceeded", None),  # #282 vocabulary
])
def test_exhaustion_signal_stops_the_arm_as_audit_unavailable(line: str, signal: str, meter: Optional[str],
                                                              _isolated_home: Path) -> None:
    """A real exhaustion signal on a call that returned no verdict is a named quota stop,
    recorded as quota_source exhaustion; the original error text is kept.

    RE-POINTED by #282 R2 (the error text and quota_source are derived from the ONE classification):
    the text names the classifier's reason, "(quota_exhausted)", not the pattern that matched; the
    pattern name is still asserted through codex_quota's line-agnostic helper."""
    if meter is not None:
        _meter_rollout(_isolated_home, meter)
    sink: dict = {}
    stderr = REAL_CODEX_0154_STDERR + "the prompt\n" + line
    with _codex_spawn_patched(lambda c, **k: SimpleNamespace(stdout="", returncode=1, stderr=stderr)):
        verdict, err = audit_spawn.run_codex_auditor("the prompt", 60, sink)
    assert verdict is None
    assert err.startswith("codex quota exhausted (quota_exhausted): codex exited 1")
    assert sink["quota_source"] == audit_spawn.QUOTA_SOURCE_EXHAUSTION
    assert codex_quota.exhaustion_signal(stderr, "the prompt") == signal


@pytest.mark.parametrize("line", [
    "stream error: unexpected status 429 Too Many Requests: slow down\n",
    '{"rate_limits":{"rate_limit_reached_type":"primary"}}\n',
    "You've hit your usage limit. Upgrade to Pro to continue.\n",
    "    ERROR: You've hit your usage limit.\n",
])
def test_r2_a_bare_exhaustion_line_without_the_meter_is_not_a_stop(line: str, _isolated_home: Path) -> None:
    """#282 R2 NEGATIVE: the same words on a line codex does not own, with a healthy meter, leave the error
    as it was and quota_source meter. CONTROL: the meter agreeing makes the bare line a stop."""
    _meter_rollout(_isolated_home, None)
    stderr = REAL_CODEX_0154_STDERR + "the prompt\n" + line
    fake = _codex_spawn_patched(lambda c, **k: SimpleNamespace(stdout="", returncode=1, stderr=stderr))
    sink: dict = {}
    with fake:
        verdict, err = audit_spawn.run_codex_auditor("the prompt", 60, sink)
    assert verdict is None and err.startswith("codex exited 1")
    assert sink["quota_source"] == audit_spawn.QUOTA_SOURCE_METER

    _meter_rollout(_isolated_home, "quota_exhausted")
    sink = {}
    with fake:
        verdict, err = audit_spawn.run_codex_auditor("the prompt", 60, sink)
    assert err.startswith("codex quota exhausted (quota_exhausted): codex exited 1")
    assert sink["quota_source"] == audit_spawn.QUOTA_SOURCE_EXHAUSTION


def test_exhaustion_signal_inside_the_echoed_prompt_is_not_a_stop() -> None:
    """NEGATIVE CONTROL. codex echoes the prompt onto stderr, and an audit prompt carries
    arbitrary evidence. Evidence that merely MENTIONS a usage limit or a 429 must not
    relabel a failure as a quota stop."""
    prompt = ("bundle: {\"note\": \"You've hit your usage limit\", \"status\": 429, "
              "\"err\": \"429 Too Many Requests\", \"rate_limit_reached_type\": \"primary\"}")
    stderr = REAL_CODEX_0154_STDERR + prompt + "\n"
    # Premise: without removing the echo, the patterns WOULD fire on this stderr.
    # S081 WP-F03 (plan J9): the matcher now has ONE owner, codex_quota; audit_spawn's
    # duplicate is deleted, so the premise and the guard are asserted on the owner.
    assert codex_quota.exhaustion_signal(stderr, "") is not None
    assert codex_quota.exhaustion_signal(stderr, prompt) is None

    sink: dict = {}
    with _codex_spawn_patched(lambda c, **k: SimpleNamespace(stdout="", returncode=1, stderr=stderr)):
        verdict, err = audit_spawn.run_codex_auditor(prompt, 60, sink)
    assert verdict is None and err.startswith("codex exited 1")
    assert sink["quota_source"] == audit_spawn.QUOTA_SOURCE_METER


def test_a_signal_on_a_call_that_returned_a_verdict_is_not_a_stop() -> None:
    """A retried 429 that still produced a valid verdict did not stop the call."""
    sink: dict = {}
    stderr = REAL_CODEX_0154_STDERR + "stream error: unexpected status 429 Too Many Requests; retrying 1/5\n"
    with _codex_spawn_patched(lambda c, **k: SimpleNamespace(
                               stdout=_audit_verdict_json(), returncode=0, stderr=stderr)):
        verdict, err = audit_spawn.run_codex_auditor("prompt", 60, sink)
    assert err is None and verdict["verdict"] == "pass"
    assert sink["quota_source"] == audit_spawn.QUOTA_SOURCE_METER
    # CONTROL: null reached-type and ordinary failures are not signals either (codex_quota
    # owns the matcher since S081 WP-F03).
    assert codex_quota.exhaustion_signal('"rate_limit_reached_type": null', "") is None
    assert codex_quota.exhaustion_signal("codex exited 1: model not found\n", "") is None


def test_rollout_tokens_are_read_only_from_this_sessions_rollout(_isolated_home: Path) -> None:
    other = "11111111-2222-3333-4444-555555555555"
    now = time.time()
    _write_rollout(_isolated_home, other, [_rollout_event(now, 1, 1, {"input_tokens": 7})], at=now)
    _write_rollout(_isolated_home, _SESSION_ID, [
        _rollout_event(now - 5, 1, 1, {"input_tokens": 10, "output_tokens": 1}),
        {"type": "response_item", "payload": {"type": "message"}},
        _rollout_event(now - 1, 1, 1, {"input_tokens": 30, "output_tokens": 4,
                                       "reasoning_output_tokens": 2, "cached_input_tokens": 0}),
        _rollout_event(now, 1, 1, None),  # a later event with no info keeps the last usage
    ], at=now - 5)
    assert audit_spawn._codex_session_id(REAL_CODEX_0154_STDERR) == _SESSION_ID
    assert audit_spawn._codex_rollout_tokens(_SESSION_ID) == {
        "input_tokens": 30, "output_tokens": 4, "reasoning_output_tokens": 2, "cached_input_tokens": 0,
    }
    # Unobservable -> None, never an estimate or another session's numbers.
    assert audit_spawn._codex_rollout_tokens("99999999-0000-0000-0000-000000000000") is None
    assert audit_spawn._codex_rollout_tokens(None) is None
    assert audit_spawn._codex_rollout_tokens("*") is None
    assert audit_spawn._codex_rollout_tokens("0000000*-0000") is None
    assert audit_spawn._codex_session_id(REAL_CODEX_STDERR) is None  # 0.153.4 fixture: no id line


def test_claude_tokens_come_from_the_json_envelope() -> None:
    envelope = [{"type": "system"}, {"type": "result", "result": "{}",
                 "usage": {"input_tokens": 5, "output_tokens": 6, "service_tier": "standard",
                           "cache_read_input_tokens": 0, "flag_tokens": True}}]
    assert audit_spawn._claude_tokens(envelope) == {
        "input_tokens": 5, "output_tokens": 6, "cache_read_input_tokens": 0}
    for unobservable in (None, "text", [], [{"type": "result"}], {"usage": []}):
        assert audit_spawn._claude_tokens(unobservable) is None


def test_admit_audit_records_and_is_never_refused(_isolated_home: Path, tmp_path: Path,
                                                  capsys: pytest.CaptureFixture) -> None:
    """design §4.7: the VERIFIED-gate audit is never refused, even at 95% of the 5-hour
    window, and every admission is a budget row. A broken admit never breaks the audit."""
    project = tmp_path / "proj-admit"
    project.mkdir()
    now = time.time()
    _write_rollout(_isolated_home, _SESSION_ID, [_rollout_event(now - 30, 95.0, 96.0)], at=now - 30)
    decision = audit_spawn._admit_audit(project)
    assert (decision["admitted"], decision["reason"], decision["use"]) == (True, "audit_exempt", "audit")
    assert decision["snapshot_state"] == "fresh" and decision["primary"] == 95.0
    budget = _isolated_home / ".claude" / "projects" / codex_quota.project_slug(project) / "astra-budget.jsonl"
    rows = [json.loads(l) for l in budget.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert [(r["use"], r["admitted"], r["cycle_id"]) for r in rows] == [
        ("audit", True, codex_quota.cycle_id_for(project))]

    with mock.patch.object(audit_spawn.codex_quota, "admit", side_effect=ValueError("caller bug")):
        assert audit_spawn._admit_audit(project) is None
    assert "not recorded" in capsys.readouterr().err


@pytest.mark.parametrize("kind, expected", [("std", "std"), ("top", "top")])
def test_admit_audit_bills_the_resolved_codex_pin(_isolated_home: Path, tmp_path: Path, kind: str,
                                                  expected: str) -> None:
    """D21 fix round 1 (m3): the audit row names the class, model and role CODEX_PIN actually
    resolved to. A code_reviewer seat sized onto the std tier was filed `top` before. The audit
    stays never-refused in either class."""
    project = tmp_path / f"proj-{kind}"
    project.mkdir()
    std = audit_spawn.seat_model.CODEX_STD_MODEL
    pin = (audit_spawn.seat_model.SeatPin(model=std, effort="xhigh", timeout=1, argv_fragment=(), provenance={},
                                          row_kind=audit_spawn.seat_model.KIND_LITERAL)
           if kind == "std" else
           audit_spawn.seat_model.SeatPin(model="gpt-6-astra", effort="xhigh", timeout=1, argv_fragment=(),
                                          provenance={}, row_kind=audit_spawn.seat_model.KIND_TOP))
    with mock.patch.object(audit_spawn, "CODEX_PIN", pin):
        decision = audit_spawn._admit_audit(project)
    assert (decision["admitted"], decision["reason"]) == (True, "audit_exempt")
    budget = _isolated_home / ".claude" / "projects" / codex_quota.project_slug(project) / "astra-budget.jsonl"
    rows = [json.loads(l) for l in budget.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert [(r["use"], r["model_class"], r["requested_model"], r.get("role")) for r in rows] == [
        ("audit", expected, pin.model, audit_spawn.REVIEWER_ROLE)]


# ---------------------------------------------------------------------------
# S081 WP-R06 — STUB-LAUNCH ADOPTION (design §11 "Adoption")
# ---------------------------------------------------------------------------
#
# The real audit_spawn.py CLI, run with its OWN stdin an open pipe that never EOFs,
# against stub reviewer binaries that record their argv and whether THEIR stdin is at
# EOF. HOME is a fixture tree: a live-shaped codex roster whose TOP is gpt-6-astra, a
# freeze pin holding codex on gpt-5.6-sol, and a fresh rollout. The codex stub prints
# codex's banner and writes its own non-ephemeral rollout, as the real CLI does.

_ADOPTION_STUB = """#!{python}
import json, os, select, sys, time
from datetime import datetime, timezone

def drain_stdin():
    # Read stdin until EOF or 1 s of silence: (text read, reached EOF). #291 fix round 1 B:
    # the Claude launches now pipe the prompt in, so "at EOF" means "EOF after the prompt".
    data = b""
    try:
        while True:
            ready, _, _ = select.select([0], [], [], 1.0)
            if not ready:
                return data.decode("utf-8", "replace"), False
            chunk = os.read(0, 65536)
            if chunk == b"":
                return data.decode("utf-8", "replace"), True
            data += chunk
    except OSError:
        return data.decode("utf-8", "replace"), False

argv = sys.argv[1:]
name = os.path.basename(sys.argv[0])
with open(os.environ["STUB_ARGV_LOG"], "a", encoding="utf-8") as fh:
    _stdin_text, _stdin_eof = drain_stdin()
    fh.write(json.dumps({{"bin": name, "argv": argv, "stdin_eof": _stdin_eof,
                         "stdin_text": _stdin_text}}) + "\\n")

if "codex" in name:
    model = argv[argv.index("-m") + 1] if "-m" in argv else "unset"
    effort = "unset"
    for token in argv:
        if token.startswith("model_reasoning_effort="):
            effort = token.split("=", 1)[1]
    session = os.environ["STUB_SESSION_ID"]
    sys.stderr.write("OpenAI Codex v0.154.0\\n--------\\nmodel: %s\\nreasoning effort: %s\\n"
                     "session id: %s\\n--------\\nuser\\n%s\\n" % (model, effort, session,
                     _stdin_text if argv[-1] == "-" else argv[-1]))
    now = time.time()
    stamp = datetime.fromtimestamp(now, timezone.utc)
    day = os.path.join(os.path.expanduser("~"), ".codex", "sessions",
                       stamp.strftime("%Y"), stamp.strftime("%m"), stamp.strftime("%d"))
    os.makedirs(day, exist_ok=True)
    event = {{"timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "type": "event_msg",
             "payload": {{"type": "token_count",
                         "info": {{"total_token_usage": json.loads(os.environ["STUB_TOKENS"])}},
                         "rate_limits": {{"limit_id": "codex",
                                         "primary": {{"used_percent": float(os.environ["STUB_PRIMARY_AFTER"]),
                                                     "window_minutes": 300, "resets_at": int(now + 7200)}},
                                         "secondary": {{"used_percent": 6.0, "window_minutes": 10080,
                                                       "resets_at": int(now + 259200)}},
                                         "rate_limit_reached_type": None}}}}}}
    path = os.path.join(day, "rollout-%s-%s.jsonl" % (stamp.strftime("%Y-%m-%dT%H-%M-%S"), session))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\\n")
    sys.stdout.write(os.environ["STUB_CODEX_STDOUT"])
else:
    sys.stdout.write(os.environ["STUB_CLAUDE_STDOUT"])
"""

_ADOPTION_TOKENS = {"input_tokens": 4321, "cached_input_tokens": 1000, "output_tokens": 210}
_CLAUDE_USAGE = {"input_tokens": 3000, "output_tokens": 150}


def _adoption_home(tmp_path: Path, *, freeze: bool) -> Tuple[Path, str]:
    home = tmp_path / "adoption-home"
    fetched_at = _seat_home(home, freeze="gpt-5.6-sol" if freeze else None)
    now = time.time()
    _write_rollout(home, "00000000-0000-0000-0000-0000000000b0",
                   [_rollout_event(now - 90, 10.0, 5.0)], at=now - 90)
    return home, fetched_at


def _run_adoption(tmp_path: Path, home: Path) -> Dict[str, Any]:
    root, bundle = _audit_project(tmp_path)
    (root / ".process-observations").mkdir()
    bindir = tmp_path / "adoption-bin"
    claude_stub = _write_stub(bindir / "claude-stub", _ADOPTION_STUB)
    codex_stub = _write_stub(bindir / "codex-stub", _ADOPTION_STUB)
    argv_log = tmp_path / "adoption-argv.jsonl"
    claude_stdout = json.dumps([
        {"type": "system", "subtype": "init"},
        {"type": "result", "subtype": "success", "result": _audit_verdict_json(),
         "total_cost_usd": 0.02, "duration_ms": 1500, "num_turns": 1, "usage": _CLAUDE_USAGE},
    ])
    env = _child_env(
        home, AUDIT_CLAUDE_BIN=str(claude_stub), AUDIT_CODEX_BIN=str(codex_stub),
        STUB_ARGV_LOG=str(argv_log), STUB_SESSION_ID=_SESSION_ID,
        STUB_TOKENS=json.dumps(_ADOPTION_TOKENS), STUB_PRIMARY_AFTER="12.5",
        STUB_CODEX_STDOUT=_audit_verdict_json(), STUB_CLAUDE_STDOUT=claude_stdout,
    )
    for var in ("FORGE_SESSION_ID", "CLAUDE_SESSION_ID"):
        env.pop(var, None)
    cwd = _poisoned_cwd(tmp_path)
    read_end, write_end = os.pipe()  # the CLI's own stdin: open, and never at EOF
    try:
        proc = subprocess.Popen(
            [sys.executable, str(_META / "audit_spawn.py"), "comp-x", str(bundle),
             "--project-root", str(root)],
            cwd=str(cwd), env=env, stdin=read_end,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        try:
            out, err = proc.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            raise
    finally:
        os.close(read_end)
        os.close(write_end)
    assert proc.returncode == 0, (out, err)
    calls = [json.loads(l) for l in argv_log.read_text(encoding="utf-8").splitlines() if l]
    rows = [json.loads(l) for l in (root / ".process-observations" / "spawn-runs.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]
    budget = home / ".claude" / "projects" / codex_quota.project_slug(root) / "astra-budget.jsonl"
    return {
        "out": json.loads(out), "stderr": err, "calls": calls, "root": root,
        "rows": {r["tool"]: r for r in rows}, "row_count": len(rows),
        "budget": [json.loads(l) for l in budget.read_text(encoding="utf-8").splitlines() if l.strip()],
        "claude_stub": claude_stub, "codex_stub": codex_stub,
    }


def _call(calls: List[dict], name: str) -> dict:
    matches = [c for c in calls if name in c["bin"]]
    assert len(matches) == 1, calls
    return matches[0]


@_POSIX_ONLY
def test_adoption_stub_launch_runs_the_frozen_pins(tmp_path: Path) -> None:
    home, fetched_at = _adoption_home(tmp_path, freeze=True)
    run = _run_adoption(tmp_path, home)
    out = run["out"]
    assert out["result"] == "VERIFIED"
    prompt_head = "You are a cold-context metacognitive auditor"

    # --- codex: pinned, non-ephemeral, options before the prompt, stdin at EOF -------
    codex = _call(run["calls"], "codex")
    argv = codex["argv"]
    assert argv[0] == "exec"
    assert "--ephemeral" not in argv
    i = argv.index("-m")
    assert argv[i:i + 4] == ["-m", "gpt-5.6-sol", "-c", "model_reasoning_effort=xhigh"]
    assert argv[-1] == "-"                               # prompt on stdin (#291 fix round 2 N2)
    assert codex["stdin_text"].startswith(prompt_head)
    assert max(argv.index("-s"), i + 3) < len(argv) - 1
    assert codex["stdin_eof"] is True

    # --- claude: the main tier, prompt on stdin (never argv, #291 B), stdin at EOF ---
    claude = _call(run["calls"], "claude")
    assert claude["argv"][claude["argv"].index("--model") + 1] == MAIN
    assert claude["stdin_text"].startswith(prompt_head)
    assert not any(a.startswith(prompt_head) for a in claude["argv"])
    assert claude["stdin_eof"] is True

    # --- verdict provenance -----------------------------------------------------------
    prov = out["model_provenance"]
    assert (prov["codex"]["requested"], prov["codex"]["source"], prov["codex"]["requested_selector"]) == (
        "gpt-5.6-sol", "freeze", "TOP@xhigh")
    assert prov["codex"]["roster_fetched_at"] == fetched_at
    assert (prov["codex"]["reported"], prov["codex"]["reported_source"]) == ("gpt-5.6-sol", "codex_stderr_banner")
    assert prov["codex"]["bin_override"]["realpath"] == os.path.realpath(str(run["codex_stub"]))
    assert (prov["claude"]["requested"], prov["claude"]["source"]) == (MAIN, "harness_literal")
    assert prov["claude"]["bin_override"]["realpath"] == os.path.realpath(str(run["claude_stub"]))

    # --- telemetry rows (design §4.11) --------------------------------------------------
    assert run["row_count"] == 2
    codex_row, claude_row = run["rows"]["audit_codex"], run["rows"]["audit_claude"]
    assert (codex_row["requested_model"], codex_row["served_model"], codex_row["role"]) == (
        "gpt-5.6-sol", "gpt-5.6-sol", "code_reviewer")
    assert codex_row["tokens"] == _ADOPTION_TOKENS
    assert (codex_row["quota_before"]["state"], codex_row["quota_before"]["primary_used_percent"]) == ("fresh", 10.0)
    assert (codex_row["quota_after"]["state"], codex_row["quota_after"]["primary_used_percent"]) == ("fresh", 12.5)
    assert codex_row["quota_source"] == "codex_rollout_meter"
    assert (claude_row["requested_model"], claude_row["served_model"], claude_row["role"]) == (
        MAIN, "unknown", "code_reviewer")
    assert claude_row["tokens"] == _CLAUDE_USAGE
    for absent in ("quota_before", "quota_after", "quota_source"):
        assert absent not in claude_row
    for row in (codex_row, claude_row):
        assert "env_override_refused" not in row

    # --- the budget row: audit, admitted, never refused ------------------------------
    assert [(r["use"], r["admitted"], r["reason"], r["cycle_id"]) for r in run["budget"]] == [
        ("audit", True, "audit_exempt", codex_quota.cycle_id_for(run["root"]))]


@_POSIX_ONLY
def test_adoption_negative_control_without_the_freeze_the_roster_top_would_run(tmp_path: Path) -> None:
    """NEGATIVE CONTROL: the SAME fixture minus the codex freeze. The arm follows the
    fixture roster's TOP — gpt-6-astra — so it is the freeze that holds sol above."""
    home, _ = _adoption_home(tmp_path, freeze=False)
    run = _run_adoption(tmp_path, home)
    argv = _call(run["calls"], "codex")["argv"]
    assert argv[argv.index("-m") + 1] == "gpt-6-astra"
    assert run["out"]["model_provenance"]["codex"]["source"] == "roster"
    assert run["rows"]["audit_codex"]["served_model"] == "gpt-6-astra"


@_POSIX_ONLY
def test_adoption_stub_really_detects_an_open_stdin(tmp_path: Path) -> None:
    """CONTROL for `stdin_eof is True` above: the same stub launched with an OPEN pipe as
    stdin reports False, and with /dev/null reports True."""
    stub = _write_stub(tmp_path / "bin" / "claude-probe", _ADOPTION_STUB)
    log = tmp_path / "probe.jsonl"
    env = dict(os.environ, STUB_ARGV_LOG=str(log), STUB_CLAUDE_STDOUT="")
    read_end, write_end = os.pipe()
    try:
        subprocess.run([str(stub)], stdin=read_end, env=env, timeout=30, check=True,
                       capture_output=True)
    finally:
        os.close(read_end)
        os.close(write_end)
    subprocess.run([str(stub)], stdin=subprocess.DEVNULL, env=env, timeout=30, check=True,
                   capture_output=True)
    states = [json.loads(l)["stdin_eof"] for l in log.read_text(encoding="utf-8").splitlines()]
    assert states == [False, True]


# ---------------------------------------------------------------------------
# S081 WP-F03 — astra unavailable -> a second cold-context Fable auditor (amendment 1 D6)
# ---------------------------------------------------------------------------
#
# Plan J9, J13, J14, J15. When the codex arm cannot run, a fresh Claude subprocess on the
# code_reviewer Claude row runs THE SAME prompt and its verdict fills the codex slot. The
# flat conjunction still needs two valid verdicts (aggregate_verdicts is unchanged), the
# substitution is recorded (budget store row, verdict provenance, telemetry row), and it
# never launders an unclassified codex failure (codex_error stays AUDIT_UNAVAILABLE).
#
# The stub below stands in for BOTH binaries (AUDIT_CLAUDE_BIN / AUDIT_CODEX_BIN, or the
# module constants they set). It logs argv, whether its stdin is at EOF and a per-binary
# call index, and picks its behaviour from a JSON plan indexed by that call. Arm vs
# substitute ordering: the codex stub can wait until the Claude ARM has logged its call
# (STUB_CODEX_WAIT_FOR_CLAUDE), which makes the Claude arm call 0 and the substitute
# call 1 deterministically; a pre-call substitution has no codex call to wait on, so
# those tests use a uniform Claude plan and order-independent assertions.

_SUBSTITUTION_STUB = """#!{python}
import json, os, select, sys, time

def drain_stdin():
    # Read stdin until EOF or 1 s of silence: (text read, reached EOF). #291 fix round 1 B:
    # the Claude launches now pipe the prompt in, so "at EOF" means "EOF after the prompt".
    data = b""
    try:
        while True:
            ready, _, _ = select.select([0], [], [], 1.0)
            if not ready:
                return data.decode("utf-8", "replace"), False
            chunk = os.read(0, 65536)
            if chunk == b"":
                return data.decode("utf-8", "replace"), True
            data += chunk
    except OSError:
        return data.decode("utf-8", "replace"), False

argv = sys.argv[1:]
name = os.path.basename(sys.argv[0])
kind = "codex" if "codex" in name else "claude"
log = os.environ["STUB_ARGV_LOG"]
stdin_text, eof = drain_stdin()

def entries():
    try:
        with open(log, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except FileNotFoundError:
        return []

index = sum(1 for e in entries() if e["kind"] == kind)
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({{"bin": name, "kind": kind, "argv": argv, "stdin_eof": eof, "stdin_text": stdin_text,
                         "index": index, "cwd": os.getcwd(),
                         "settings_visible": os.path.exists(os.path.join(".claude", "settings.json")),
                         "dot_claude": os.path.lexists(".claude")}}) + "\\n")

def pick(plan_var):
    plan = json.loads(os.environ[plan_var])
    return plan[min(index, len(plan) - 1)]

def verdict_json(word):
    return json.dumps({{"verdict": word, "structured_disagreements": [
        {{"point": "%s-p1" % word, "severity": "minor", "location": "comp-x"}},
        {{"point": "%s-p2" % word, "severity": "minor", "location": "comp-x"}},
        {{"point": "%s-p3" % word, "severity": "moderate", "location": "comp-x"}}],
        "evidence_verified": word != "fail", "reason": "stub " + word}})

if kind == "codex":
    if os.environ.get("STUB_CODEX_WAIT_FOR_CLAUDE"):
        deadline = time.time() + 30
        while time.time() < deadline and not any(e["kind"] == "claude" for e in entries()):
            time.sleep(0.02)
    model = argv[argv.index("-m") + 1] if "-m" in argv else "unset"
    sys.stderr.write("OpenAI Codex v0.154.0\\n--------\\nmodel: %s\\nreasoning effort: xhigh\\n"
                     "--------\\nuser\\n%s\\n" % (model, stdin_text if argv[-1] == "-" else argv[-1]))
    sys.stderr.flush()
    action = pick("STUB_CODEX_PLAN")
    if action == "ok":
        sys.stdout.write(verdict_json("pass"))
    elif action == "ok_fail":
        sys.stdout.write(verdict_json("fail"))
    elif action == "429":
        sys.stderr.write("ERROR: exceeded retry limit, last status: 429 Too Many Requests\\n")
        sys.exit(1)
    elif action == "auth":
        sys.stderr.write("ERROR: Your access token could not be refreshed because your refresh "
                         "token has expired. Please log out and sign in again.\\n")
        sys.exit(1)
    elif action == "malformed":
        sys.stdout.write("this is not a verdict")
    elif action == "rc1":
        sys.stderr.write("ERROR: something went wrong\\n")
        sys.exit(1)
    elif action == "bare_usage_limit":  # #282 R2: tool output that merely quotes a usage limit
        sys.stderr.write("exec\\n/bin/bash -lc 'cat notes.md' in /repo\\n succeeded in 4ms:\\n"
                         "You've hit your usage limit. Upgrade to Pro to continue.\\n")
        sys.exit(1)
    elif action == "error_usage_limit":  # #282 R2 CONTROL: the same words on a codex error line
        sys.stderr.write("ERROR: You've hit your usage limit.\\n")
        sys.exit(1)
    elif action == "capacity":  # #282 classifier vocabulary
        sys.stderr.write("ERROR: Selected model is at capacity. Please try a different model.\\n")
        sys.exit(1)
    elif action == "rc2":
        sys.stderr.write("error: unexpected argument '--bogus' found\\n")
        sys.exit(2)
    elif action == "sleep":
        time.sleep(float(os.environ.get("STUB_CODEX_SLEEP", "30")))
        sys.stdout.write(verdict_json("pass"))
else:
    item = pick("STUB_CLAUDE_PLAN")
    if item == "garbage":
        sys.stdout.write("no json here")
    else:
        result = {{"type": "result", "subtype": "success", "result": verdict_json(item["verdict"]),
                  "total_cost_usd": item.get("cost", 0.01), "duration_ms": item.get("duration_ms", 1000),
                  "num_turns": 1, "usage": {{"input_tokens": item.get("input_tokens", 100),
                                            "output_tokens": 10}}}}
        if "model_usage" in item:  # #282 R3: {{id: outputTokens}} -> the envelope's modelUsage map
            result["modelUsage"] = {{k: {{"inputTokens": 1, "outputTokens": v}}
                                    for k, v in item["model_usage"].items()}}
        sys.stdout.write(json.dumps([{{"type": "system", "subtype": "init"}}, result]))
"""

_PASS = {"verdict": "pass", "cost": 0.02, "input_tokens": 200}
_FAIL = {"verdict": "fail", "cost": 0.05, "input_tokens": 500}
_SUB_PASS = {"verdict": "pass", "cost": 0.05, "input_tokens": 500}

#: The top-level stdout key sets (#124: unchanged in EVERY outcome, substituted or not).
_RESULT_KEYS = frozenset({"result", "component_id", "claude_verdict", "codex_verdict", "disagreements",
                          "bundle_hash", "elapsed_s", "model_provenance"})
_UNAVAILABLE_KEYS = frozenset({"result", "claude_verdict", "codex_verdict", "claude_error", "codex_error",
                               "disagreements", "reason", "component_id", "bundle_hash", "elapsed_s",
                               "model_provenance"})
#: The J14 substitution keys inside model_provenance.codex.
_SUBSTITUTION_PROVENANCE = ("codex_arm_substituted_by", "substitution_reason", "substitute_timeout_s",
                            "provider_gap", "codex_attempts")


def _stub_env(log: Path, codex_plan: List[str], claude_plan: List[Any], wait: bool) -> Dict[str, str]:
    env = {"STUB_ARGV_LOG": str(log), "STUB_CODEX_PLAN": json.dumps(codex_plan),
           "STUB_CLAUDE_PLAN": json.dumps(claude_plan), "STUB_CODEX_SLEEP": "30"}
    if wait:
        env["STUB_CODEX_WAIT_FOR_CLAUDE"] = "1"
    return env


def _read_jsonl(path: Path) -> List[dict]:
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _budget_rows(home: Path, root: Path) -> List[dict]:
    return _read_jsonl(home / ".claude" / "projects" / codex_quota.project_slug(root) / "astra-budget.jsonl")


def _fresh_rollout(home: Path, *, primary: float = 10.0, reached_type: Optional[str] = None) -> None:
    now = time.time()
    _write_rollout(home, "00000000-0000-0000-0000-0000000000c0",
                   [_rollout_event(now - 60, primary, 5.0, reached_type=reached_type)], at=now - 60)


def _substitution_home(tmp_path: Path, *, freeze: Optional[str] = "gpt-5.6-sol", roster: Any = _LIVE_LIKE_ROSTER,
                       reached_type: Optional[str] = None, rollout: bool = True) -> Path:
    home = tmp_path / "sub-home"
    home.mkdir(parents=True, exist_ok=True)
    if roster is not None:
        _seat_home(home, freeze=freeze, roster=roster)
    elif freeze is not None:
        _write_freeze(home, freeze)
    if rollout:
        _fresh_rollout(home, reached_type=reached_type)
    return home


def _run_substitution_cli(tmp_path: Path, home: Path, *, codex_plan: List[str], claude_plan: List[Any],
                          wait: bool = False, codex_bin: Optional[Path] = None,
                          note: Optional[str] = None, codex_bin_env: bool = True,
                          claude_bin_env: bool = True, path_dir: Optional[Path] = None,
                          caller_cwd: Optional[Path] = None,
                          codex_on_path: bool = False) -> Dict[str, Any]:
    """The REAL audit_spawn.py CLI against the substitution stub under a fixture HOME.

    #282 R1 knobs: `codex_bin_env=False` leaves AUDIT_CODEX_BIN UNSET (the arm looks `codex` up
    on PATH), `claude_bin_env=False` leaves AUDIT_CLAUDE_BIN unset (a `claude` stub is placed
    in `path_dir` instead), and `path_dir` becomes the child's whole PATH — a directory with no
    `codex` in it makes the un-overridden binary missing.

    #282 fix round 1 F1 knob: `codex_on_path=True` reaches the SAME stub behaviours as the
    UN-OVERRIDDEN `codex` — AUDIT_CODEX_BIN unset, a `codex` stub written into the child's PATH.
    Every CALL-TIME SUBSTITUTION assertion needs it now: F1 makes every classifier substitution
    a gap while AUDIT_CODEX_BIN is set, so a substitution can only be exercised on the
    un-overridden binary (exactly the case F1 leaves alone). Same idiom as R1's re-point of
    test_missing_codex_binary_substitutes_before_any_codex_spawn.

    #282 R3 knob: `caller_cwd` is the directory the CLI itself is launched from (default a clean
    scratch dir); the stub logs its own cwd and whether `.claude/settings.json` is visible there.
    """
    root, bundle = _audit_project(tmp_path, note=note)
    bindir = tmp_path / "sub-bin"
    claude_stub = _write_stub(bindir / "claude-stub", _SUBSTITUTION_STUB)
    codex_stub = _write_stub(bindir / "codex-stub", _SUBSTITUTION_STUB)
    log = tmp_path / "sub-argv.jsonl"
    overrides: Dict[str, str] = {}
    if codex_on_path:
        codex_bin_env = False
        path_dir = path_dir if path_dir is not None else tmp_path / "path-with-codex"
        path_dir.mkdir(parents=True, exist_ok=True)
        _write_stub(path_dir / "codex", _SUBSTITUTION_STUB)
    if claude_bin_env:
        overrides["AUDIT_CLAUDE_BIN"] = str(claude_stub)
    if codex_bin_env:
        overrides["AUDIT_CODEX_BIN"] = str(codex_bin if codex_bin is not None else codex_stub)
    if path_dir is not None:
        path_dir.mkdir(parents=True, exist_ok=True)
        if not claude_bin_env:
            _write_stub(path_dir / "claude", _SUBSTITUTION_STUB)
        overrides["PATH"] = str(path_dir)
    env = _child_env(home, **overrides, **_stub_env(log, codex_plan, claude_plan, wait))
    for var in ("FORGE_SESSION_ID", "CLAUDE_SESSION_ID"):
        env.pop(var, None)
    cwd = caller_cwd if caller_cwd is not None else tmp_path / "scratch-cwd"
    cwd.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(_META / "audit_spawn.py"), "comp-x", str(bundle), "--project-root", str(root)],
        cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8", timeout=180,
        stdin=subprocess.DEVNULL,
    )
    calls = _read_jsonl(log)
    return {
        "code": proc.returncode, "out": json.loads(proc.stdout), "stderr": proc.stderr, "root": root,
        "calls": calls, "codex": [c for c in calls if c["kind"] == "codex"],
        "claude": [c for c in calls if c["kind"] == "claude"],
        "rows": {r["tool"]: r for r in _read_jsonl(root / ".process-observations" / "spawn-runs.jsonl")},
        "row_count": len(_read_jsonl(root / ".process-observations" / "spawn-runs.jsonl")),
        "budget": _budget_rows(home, root),
    }


def _model_arg(call: dict, flag: str) -> str:
    argv = call["argv"]
    return argv[argv.index(flag) + 1]


def _substitution_rows(run: Dict[str, Any]) -> List[dict]:
    return [r for r in run["budget"] if r.get("kind") == "substitution"]


def _admit_rows(run: Dict[str, Any]) -> List[dict]:
    return [r for r in run["budget"] if "admitted" in r]


def _assert_top_level_keys(run: Dict[str, Any]) -> None:
    keys = set(run["out"])
    if run["out"]["result"] == "AUDIT_UNAVAILABLE":
        assert keys == _UNAVAILABLE_KEYS, keys
    else:
        assert keys == _RESULT_KEYS, keys


def _assert_no_substitution(run: Dict[str, Any]) -> None:
    codex_block = run["out"]["model_provenance"]["codex"]
    for key in _SUBSTITUTION_PROVENANCE + ("substitution_error", "substitution_row_error"):
        assert key not in codex_block, key
    assert _substitution_rows(run) == []
    for row in run["rows"].values():
        for key in ("substitute_for", "substitution_reason", "use"):
            assert key not in row, key


@_POSIX_ONLY
def test_codex_429_is_served_by_a_fresh_fable_auditor(tmp_path: Path) -> None:
    """(1) codex stub 429 -> the Claude stub runs TWICE on the code_reviewer alias with the
    same prompt, the result is the aggregate of both verdicts, and the substitution is on
    record in the provenance, the budget store and the codex arm's telemetry row."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["429"], claude_plan=[_PASS, _SUB_PASS], wait=True,
        codex_on_path=True)
    assert run["code"] == 0, (run["out"], run["stderr"])
    _assert_top_level_keys(run)
    out = run["out"]
    assert out["result"] == "VERIFIED"
    assert out["claude_verdict"]["reason"] == "stub pass" and out["codex_verdict"]["reason"] == "stub pass"

    # codex ran ONCE (a quota stop is not retried on the same model), then the substitute.
    assert len(run["codex"]) == 1
    assert _model_arg(run["codex"][0], "-m") == "gpt-5.6-sol"
    assert [c["index"] for c in run["claude"]] == [0, 1]
    for call in run["claude"]:
        assert _model_arg(call, "--model") == MAIN
        assert call["stdin_eof"] is True
    # SAME prompt for the arm, the codex call and the substitute (J13). Every launch takes it
    # on stdin (#291 fix round 1 B for Claude, fix round 2 N2 for codex).
    prompts = {c["stdin_text"] for c in run["calls"]}
    assert len(prompts) == 1 and next(iter(prompts)).startswith("You are a cold-context metacognitive auditor")

    codex_block = out["model_provenance"]["codex"]
    assert codex_block["codex_arm_substituted_by"] == MAIN
    assert codex_block["substitution_reason"] == "quota_exhausted"
    assert codex_block["provider_gap"] == "openai"
    assert codex_block["substitute_timeout_s"] == seat_model.resolve("code_reviewer", "claude").timeout == 600
    assert codex_block["codex_attempts"] == 1
    # REQUESTED and REPORTED codex facts are kept as they were: sol asked for, sol banner.
    assert (codex_block["requested"], codex_block["reported"]) == ("gpt-5.6-sol", "gpt-5.6-sol")
    assert "substitution_row_error" not in codex_block
    assert "codex_arm_substituted_by" not in out["model_provenance"]["claude"]

    # ONE substitution row, use audit, Fable for sol; plus the audit admission it followed.
    subs = _substitution_rows(run)
    assert len(subs) == 1
    sub = subs[0]
    assert (sub["use"], sub["reason"], sub["substitute_for"], sub["served_model"], sub["requested_model"],
            sub["role"]) == ("audit", "quota_exhausted", "codex", MAIN, "gpt-5.6-sol", "code_reviewer")
    assert sub["cycle_id"] == codex_quota.cycle_id_for(run["root"])
    assert [(r["use"], r["admitted"], r["reason"]) for r in _admit_rows(run)] == [("audit", True, "audit_exempt")]

    # Telemetry (J15): the arm keeps tool audit_codex; model = the alias; the requested slug
    # is the codex one; cost and tokens come from the substitute's envelope.
    # RE-POINTED by #282 R3 (spec H1 R3 item 5, plan K5): served_model is what the substitute's
    # envelope modelUsage names, and this stub envelope has none -> "unknown" (it was the alias,
    # i.e. the request echoed back). The modelUsage case is asserted in
    # test_r3_served_model_reaches_the_rows_and_the_provenance_through_the_cli.
    assert run["row_count"] == 2
    codex_row, claude_row = run["rows"]["audit_codex"], run["rows"]["audit_claude"]
    assert (codex_row["model"], codex_row["served_model"], codex_row["requested_model"]) == (
        MAIN, audit_spawn.MODEL_UNKNOWN, "gpt-5.6-sol")
    assert (codex_row["substitute_for"], codex_row["substitution_reason"], codex_row["use"]) == (
        "codex", "quota_exhausted", "audit")
    assert codex_row["cost_usd"] == 0.05 and codex_row["tokens"]["input_tokens"] == 500
    assert codex_row["status"] == "pass"
    assert codex_row["quota_source"] == audit_spawn.QUOTA_SOURCE_EXHAUSTION
    assert claude_row["cost_usd"] == 0.02
    for key in ("substitute_for", "substitution_reason", "use"):
        assert key not in claude_row


@_POSIX_ONLY
def test_control_a_valid_codex_verdict_substitutes_nothing(tmp_path: Path) -> None:
    """CONTROL for (1): the same fixture with codex answering. No provenance keys, zero
    substitution rows, the Claude stub runs once, and the codex row names sol."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["ok"], claude_plan=[_PASS], wait=True)
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED"
    _assert_top_level_keys(run)
    _assert_no_substitution(run)
    assert len(run["codex"]) == 1 and len(run["claude"]) == 1
    assert run["rows"]["audit_codex"]["served_model"] == "gpt-5.6-sol"
    assert run["rows"]["audit_codex"]["model"] == "gpt-5.6-sol"
    assert [(r["use"], r["admitted"]) for r in run["budget"]] == [("audit", True)]


@_POSIX_ONLY
@pytest.mark.parametrize("plan,attempts,reason", [
    (["auth"], 1, "auth_failure"),
    (["malformed", "malformed"], 2, "malformed_twice"),
])
def test_call_time_failures_that_substitute(tmp_path: Path, plan: List[str], attempts: int, reason: str) -> None:
    """(3) malformed twice -> malformed_twice after exactly two codex calls; an auth failure
    substitutes at once (a same-model retry would be doomed)."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=plan, claude_plan=[_PASS, _SUB_PASS], wait=True,
        codex_on_path=True)
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", run["out"]
    _assert_top_level_keys(run)
    assert len(run["codex"]) == attempts
    assert len(run["claude"]) == 2
    block = run["out"]["model_provenance"]["codex"]
    assert (block["codex_arm_substituted_by"], block["substitution_reason"], block["codex_attempts"]) == (
        MAIN, reason, attempts)
    assert [r["reason"] for r in _substitution_rows(run)] == [reason]
    assert run["rows"]["audit_codex"]["substitution_reason"] == reason


@_POSIX_ONLY
def test_control_malformed_once_then_valid_is_a_retry_not_a_substitution(tmp_path: Path) -> None:
    """CONTROL for (3): one malformed answer is retried on the SAME model (same argv) and the
    second answer stands. The retry is visible (codex_attempts 2) but nothing is substituted."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["malformed", "ok"], claude_plan=[_PASS], wait=True)
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED"
    assert len(run["codex"]) == 2 and len(run["claude"]) == 1
    assert run["codex"][0]["argv"] == run["codex"][1]["argv"]
    block = run["out"]["model_provenance"]["codex"]
    assert block["codex_attempts"] == 2
    for key in ("codex_arm_substituted_by", "substitution_reason", "provider_gap", "substitute_timeout_s"):
        assert key not in block
    assert _substitution_rows(run) == []
    assert "substitute_for" not in run["rows"]["audit_codex"]


@_POSIX_ONLY
def test_missing_codex_binary_substitutes_before_any_codex_spawn(tmp_path: Path) -> None:
    """(4) `codex` absent from PATH with AUDIT_CODEX_BIN UNSET -> cli_missing pre-call: codex is
    never spawned, no audit admission is recorded (no TOP call happens; the seat_model CLI's J10
    order), and the substitution row is. CONTROL: the stub present -> codex spawned + admitted.

    RE-POINTED by #282 R1 (spec H1 R1, plan K6): this run used AUDIT_CODEX_BIN=<missing path>,
    which is now a GAP (test_r1_an_overridden_missing_codex_binary_is_audit_unavailable). Every
    substitution assertion below is kept unchanged on the un-overridden missing binary, which is
    exactly the case R1 says keeps the cli_missing substitution."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["ok"], claude_plan=[_PASS], codex_bin_env=False,
                                path_dir=tmp_path / "path-without-codex")
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", run["out"]
    _assert_top_level_keys(run)
    assert run["codex"] == []
    assert len(run["claude"]) == 2 and all(_model_arg(c, "--model") == MAIN for c in run["claude"])
    block = run["out"]["model_provenance"]["codex"]
    assert (block["codex_arm_substituted_by"], block["substitution_reason"], block["codex_attempts"]) == (
        MAIN, "cli_missing", 0)
    assert block["reported"] == audit_spawn.MODEL_UNKNOWN  # codex never printed a banner
    assert _admit_rows(run) == []
    assert [(r["use"], r["reason"], r["requested_model"]) for r in _substitution_rows(run)] == [
        ("audit", "cli_missing", "gpt-5.6-sol")]
    codex_row = run["rows"]["audit_codex"]
    # RE-POINTED by #282 R3 (plan K5): served_model "fable" -> "unknown" (no modelUsage in the stub
    # envelope); the substitute's alias is still asserted, on `model`.
    assert (codex_row["model"], codex_row["served_model"], codex_row["substitution_reason"]) == (
        MAIN, audit_spawn.MODEL_UNKNOWN, "cli_missing")
    for key in ("quota_before", "quota_after", "quota_source"):
        assert key not in codex_row  # no codex call, so nothing to bracket

    control = _run_substitution_cli(tmp_path / "control", _substitution_home(tmp_path / "control"),
                                    codex_plan=["ok"], claude_plan=[_PASS])
    assert len(control["codex"]) == 1
    _assert_no_substitution(control)
    assert [(r["use"], r["admitted"]) for r in _admit_rows(control)] == [("audit", True)]


@_POSIX_ONLY
def test_fresh_rate_limit_reached_substitutes_before_the_codex_call(tmp_path: Path) -> None:
    """(5) a fresh rollout whose rate_limits carries rate_limit_reached_type -> the audit
    admission (never refused) carries `unavailable`, and the codex arm is substituted
    pre-call: codex is never spawned. CONTROL: the same rollout with a null type -> codex runs."""
    home = _substitution_home(tmp_path, reached_type="primary")
    run = _run_substitution_cli(tmp_path, home, codex_plan=["ok"], claude_plan=[_PASS])
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", run["out"]
    assert run["codex"] == [] and len(run["claude"]) == 2
    block = run["out"]["model_provenance"]["codex"]
    assert (block["substitution_reason"], block["codex_attempts"]) == ("rate_limit_reached", 0)
    admits = _admit_rows(run)
    assert [(r["use"], r["admitted"], r.get("unavailable")) for r in admits] == [
        ("audit", True, "rate_limit_reached")]
    assert [r["reason"] for r in _substitution_rows(run)] == ["rate_limit_reached"]

    ctl_root = tmp_path / "control"
    control = _run_substitution_cli(ctl_root, _substitution_home(ctl_root, reached_type=None),
                                    codex_plan=["ok"], claude_plan=[_PASS])
    assert len(control["codex"]) == 1
    _assert_no_substitution(control)
    assert "unavailable" not in _admit_rows(control)[0]


_ALL_HIDDEN_ROSTER = (
    ("gpt-6-astra", 1, "hide", ["low", "medium", "high", "xhigh", "max"]),
    ("gpt-5.6-sol", 4, "hide", ["low", "medium", "high", "xhigh", "max"]),
)


@_POSIX_ONLY
def test_no_eligible_top_substitutes_before_the_codex_call(tmp_path: Path) -> None:
    """(6) an all-hidden roster -> CODEX_PIN's fail-open provenance names no_eligible_model and
    the arm is substituted pre-call (requested_model null: nothing eligible was requested).
    CONTROL: NO roster at all -> the sanctioned harness literal gpt-6-astra, codex spawned."""
    home = _substitution_home(tmp_path, freeze=None, roster=_ALL_HIDDEN_ROSTER)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["ok"], claude_plan=[_PASS])
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", run["out"]
    assert run["codex"] == [] and len(run["claude"]) == 2
    block = run["out"]["model_provenance"]["codex"]
    assert (block["substitution_reason"], block["codex_arm_substituted_by"]) == ("no_eligible_model", MAIN)
    assert _admit_rows(run) == []
    assert [(r["reason"], r["requested_model"]) for r in _substitution_rows(run)] == [("no_eligible_model", None)]
    codex_row = run["rows"]["audit_codex"]
    # RE-POINTED by #282 R3 (plan K5): the alias moved from served_model to `model`; served_model is
    # "unknown" because the stub envelope carries no modelUsage.
    assert codex_row["model"] == MAIN and "requested_model" not in codex_row  # same fact as the row
    assert codex_row["served_model"] == audit_spawn.MODEL_UNKNOWN

    ctl_root = tmp_path / "control"
    control = _run_substitution_cli(ctl_root, _substitution_home(ctl_root, freeze=None, roster=None),
                                    codex_plan=["ok"], claude_plan=[_PASS])
    assert len(control["codex"]) == 1
    assert _model_arg(control["codex"][0], "-m") == seat_model.CODEX_TOP_HARNESS_LITERAL == "gpt-6-astra"
    assert control["out"]["model_provenance"]["codex"]["source"] == "harness_literal"
    _assert_no_substitution(control)


@_POSIX_ONLY
def test_conjunction_substitute_fail_is_rejected_never_a_pass(tmp_path: Path) -> None:
    """(7a) the substitute returns fail -> the aggregate of pass + fail: REJECTED."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["429"], claude_plan=[_PASS, _FAIL], wait=True,
        codex_on_path=True)
    assert run["code"] == 0
    _assert_top_level_keys(run)
    assert run["out"]["result"] == "REJECTED"
    assert (run["out"]["claude_verdict"]["verdict"], run["out"]["codex_verdict"]["verdict"]) == ("pass", "fail")
    assert run["out"]["model_provenance"]["codex"]["codex_arm_substituted_by"] == MAIN


@_POSIX_ONLY
def test_conjunction_substitute_error_is_audit_unavailable(tmp_path: Path) -> None:
    """(7b) the substitute's output is unusable -> AUDIT_UNAVAILABLE exit 4, the codex error
    naming BOTH failures; the substitution itself is still on record."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["429"], claude_plan=[_PASS, "garbage"], wait=True,
        codex_on_path=True)
    assert run["code"] == 4
    _assert_top_level_keys(run)
    out = run["out"]
    assert out["result"] == "AUDIT_UNAVAILABLE"
    assert out["codex_verdict"] is None and out["claude_verdict"]["verdict"] == "pass"
    # RE-POINTED by #282 R2 (the quota wording is derived from the ONE classification): the codex error
    # names the classifier's reason, not the matched "429" pattern (the stderr excerpt is cut at 200 chars).
    assert "codex quota exhausted (quota_exhausted)" in out["codex_error"] and "substitute" in out["codex_error"]
    assert "not parseable" in out["codex_error"]
    assert out["claude_error"] is None
    assert len(_substitution_rows(run)) == 1
    assert run["rows"]["audit_codex"]["status"].startswith("ERROR")


@_POSIX_ONLY
def test_conjunction_claude_arm_error_while_codex_is_substituted(tmp_path: Path) -> None:
    """(7c) the Claude ARM fails while the codex slot holds a valid substitute verdict ->
    AUDIT_UNAVAILABLE exit 4. The Claude arm is never substituted."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["429"], claude_plan=["garbage", _SUB_PASS], wait=True,
        codex_on_path=True)
    assert run["code"] == 4
    _assert_top_level_keys(run)
    out = run["out"]
    assert out["result"] == "AUDIT_UNAVAILABLE"
    assert out["claude_verdict"] is None and "not parseable" in out["claude_error"]
    assert out["codex_verdict"]["verdict"] == "pass" and out["codex_error"] is None
    assert len(run["claude"]) == 2  # arm + substitute; never a third (no Claude-arm substitute)
    assert "codex_arm_substituted_by" not in out["model_provenance"]["claude"]


@_POSIX_ONLY
def test_unclassified_codex_failure_is_audit_unavailable_not_substituted(tmp_path: Path) -> None:
    """(8) codex rc 2 (a usage fault) -> gap codex_error: AUDIT_UNAVAILABLE, codex ran once (no
    retry), the Claude stub ran once, and there is no substitution row. Substitution does not
    launder every failure."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["rc2"], claude_plan=[_PASS], wait=True)
    assert run["code"] == 4
    _assert_top_level_keys(run)
    assert run["out"]["result"] == "AUDIT_UNAVAILABLE"
    assert run["out"]["codex_error"].startswith("codex exited 2")
    assert len(run["codex"]) == 1 and len(run["claude"]) == 1
    _assert_no_substitution(run)


@_POSIX_ONLY
def test_prompt_echo_cannot_impersonate_a_quota_stop(tmp_path: Path) -> None:
    """The prompt-echo guard, end to end. The bundle (and so the prompt codex echoes onto its
    stderr) quotes a 429 and a usage limit; codex then fails with no real signal -> gap, no
    substitution. CONTROL: the same bundle with a REAL 429 after the echo -> substituted."""
    note = "evidence quotes: exceeded retry limit, last status: 429 Too Many Requests; You've hit your usage limit."
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["rc1"], claude_plan=[_PASS], wait=True, note=note)
    assert note in run["codex"][0]["stdin_text"]  # premise: the note really is in the echoed prompt
    assert run["code"] == 4 and run["out"]["result"] == "AUDIT_UNAVAILABLE"
    assert run["out"]["codex_error"].startswith("codex exited 1")
    _assert_no_substitution(run)

    ctl_root = tmp_path / "control"
    control = _run_substitution_cli(ctl_root, _substitution_home(ctl_root), codex_plan=["429"],
                                    claude_plan=[_PASS, _SUB_PASS], wait=True, note=note,
        codex_on_path=True)
    assert control["code"] == 0
    assert control["out"]["model_provenance"]["codex"]["substitution_reason"] == "quota_exhausted"


@_POSIX_ONLY
def test_r2_tool_output_quoting_a_usage_limit_is_a_gap_not_a_substitution(tmp_path: Path) -> None:
    """#282 R2 (j), end to end through the real CLI: codex's stderr carries TOOL OUTPUT (a `cat` of a file)
    that says "You've hit your usage limit", the meter is healthy, codex exits 1 -> the codex slot is a gap:
    AUDIT_UNAVAILABLE exit 4, no substitution row, quota_source stays the meter. CONTROL: the same words on
    `ERROR: ` -> the fresh Fable substitute serves the slot, reason quota_exhausted, quota_source exhaustion."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["bare_usage_limit"], claude_plan=[_PASS, _SUB_PASS],
                                wait=True)
    assert run["code"] == 4 and run["out"]["result"] == "AUDIT_UNAVAILABLE", run["stderr"]
    assert run["out"]["codex_error"].startswith("codex exited 1")
    _assert_no_substitution(run)
    assert len(run["codex"]) == 1 and len(run["claude"]) == 1
    assert [(r["use"], r["admitted"]) for r in run["budget"]] == [("audit", True)]
    assert run["rows"]["audit_codex"]["quota_source"] == audit_spawn.QUOTA_SOURCE_METER

    ctl_root = tmp_path / "control"
    control = _run_substitution_cli(ctl_root, _substitution_home(ctl_root), codex_plan=["error_usage_limit"],
                                    claude_plan=[_PASS, _SUB_PASS], wait=True,
        codex_on_path=True)
    assert control["code"] == 0 and control["out"]["result"] == "VERIFIED", control["stderr"]
    assert control["out"]["model_provenance"]["codex"]["substitution_reason"] == "quota_exhausted"
    assert [r["reason"] for r in _substitution_rows(control)] == ["quota_exhausted"]
    assert control["rows"]["audit_codex"]["quota_source"] == audit_spawn.QUOTA_SOURCE_EXHAUSTION


@_POSIX_ONLY
def test_r2_a_model_at_capacity_is_retried_once_then_substituted_capacity_twice(tmp_path: Path) -> None:
    """#282 classifier vocabulary, end to end: capacity twice -> codex called twice on the SAME argv, then
    the Fable substitute serves the slot with reason capacity_twice (one substitution row). CONTROL: capacity
    then a valid answer -> VERIFIED, nothing substituted. CONJUNCTION: capacity twice with an unusable
    substitute -> AUDIT_UNAVAILABLE (a substitution never passes without its own valid verdict)."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["capacity", "capacity"],
                                claude_plan=[_PASS, _SUB_PASS], wait=True,
        codex_on_path=True)
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", run["stderr"]
    assert len(run["codex"]) == 2 and run["codex"][0]["argv"] == run["codex"][1]["argv"]
    codex_block = run["out"]["model_provenance"]["codex"]
    assert (codex_block["substitution_reason"], codex_block["codex_attempts"]) == ("capacity_twice", 2)
    assert [(r["reason"], r["use"]) for r in _substitution_rows(run)] == [("capacity_twice", "audit")]
    assert "one retry on the same model" in run["stderr"]

    ctl_root = tmp_path / "control"
    control = _run_substitution_cli(ctl_root, _substitution_home(ctl_root), codex_plan=["capacity", "ok"],
                                    claude_plan=[_PASS], wait=True)
    assert control["code"] == 0 and control["out"]["result"] == "VERIFIED"
    assert len(control["codex"]) == 2 and len(control["claude"]) == 1
    block = control["out"]["model_provenance"]["codex"]
    assert block["codex_attempts"] == 2  # a retry is recorded, as for malformed-then-ok
    for key in ("codex_arm_substituted_by", "substitution_reason", "provider_gap", "substitute_timeout_s"):
        assert key not in block
    assert _substitution_rows(control) == [] and "substitute_for" not in control["rows"]["audit_codex"]

    bad_root = tmp_path / "unusable-substitute"
    bad = _run_substitution_cli(bad_root, _substitution_home(bad_root), codex_plan=["capacity", "capacity"],
                                claude_plan=[_PASS, "garbage"], wait=True,
        codex_on_path=True)
    assert bad["code"] == 4 and bad["out"]["result"] == "AUDIT_UNAVAILABLE"
    assert bad["out"]["codex_verdict"] is None and "capacity_twice" in bad["out"]["codex_error"]


@_POSIX_ONLY
def test_r2_one_corroboration_and_one_classification_per_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                 capsys: pytest.CaptureFixture) -> None:
    """#282 R2 (k), in process with spies: a malformed first answer then a 429 -> classify exactly twice (once
    per attempt), each FAILED attempt with its own corroboration object built by corroboration_for; the
    line-agnostic exhaustion_signal / auth_signal are never called from audit_spawn. CONTROL: a valid first
    answer -> classify once with no corroboration and no corroboration_for read (nothing extra)."""
    def spies():
        return (mock.patch.object(audit_spawn.codex_quota, "classify_codex_failure",
                                  wraps=codex_quota.classify_codex_failure),
                mock.patch.object(audit_spawn.codex_quota, "corroboration_for", wraps=codex_quota.corroboration_for),
                mock.patch.object(audit_spawn.codex_quota, "exhaustion_signal", wraps=codex_quota.exhaustion_signal),
                mock.patch.object(audit_spawn.codex_quota, "auth_signal", wraps=codex_quota.auth_signal))

    p_classify, p_corr, p_exh, p_auth = spies()
    with p_classify as classify, p_corr as corr, p_exh as exh, p_auth as auth:
        run = _in_process_audit(tmp_path, monkeypatch, capsys, codex_plan=["malformed", "429"],
                                claude_plan=[_PASS, _SUB_PASS], wait=True)
    assert run["code"] == 0 and run["out"]["model_provenance"]["codex"]["substitution_reason"] == "quota_exhausted"
    assert classify.call_count == 2 and corr.call_count == 2
    assert [c.kwargs["attempt"] for c in classify.call_args_list] == [1, 2]
    for call in classify.call_args_list:
        corroboration = call.kwargs["corroboration"]
        assert isinstance(corroboration, dict) and set(corroboration) == {"codex_error_lines", "unavailable_token"}
    assert classify.call_args_list[0].kwargs["corroboration"]["codex_error_lines"] == []
    assert classify.call_args_list[1].kwargs["corroboration"]["codex_error_lines"] == [
        "ERROR: exceeded retry limit, last status: 429 Too Many Requests"]
    assert exh.call_count == 0 and auth.call_count == 0

    ok_root = tmp_path / "ok"
    ok_root.mkdir()
    p_classify, p_corr, p_exh, p_auth = spies()
    with p_classify as classify, p_corr as corr, p_exh as exh, p_auth as auth:
        ok = _in_process_audit(ok_root, monkeypatch, capsys, codex_plan=["ok"], claude_plan=[_PASS])
    assert ok["code"] == 0 and ok["out"]["result"] == "VERIFIED"
    assert classify.call_count == 1 and classify.call_args.kwargs["corroboration"] is None
    assert corr.call_count == 0 and exh.call_count == 0 and auth.call_count == 0


def test_r2_a_successful_codex_call_reads_nothing_extra() -> None:
    """#282 R2: run_codex_auditor builds a corroboration only for a FAILED call and only when something
    records (usage_out). CONTROLS: a failed call with a sink -> exactly one; the legacy 2-arg failed call ->
    none (it classifies on the error lines alone)."""
    ok = lambda c, **k: SimpleNamespace(stdout=_audit_verdict_json(), returncode=0, stderr="")  # noqa: E731
    failed = lambda c, **k: SimpleNamespace(stdout="", returncode=1, stderr="ERROR: 429 Too Many Requests\n")  # noqa: E731
    for side_effect, sink, expected in ((ok, {}, 0), (failed, {}, 1), (failed, None, 0)):
        with mock.patch.object(audit_spawn.codex_quota, "corroboration_for",
                               wraps=codex_quota.corroboration_for) as corr, \
                _codex_spawn_patched(side_effect):
            verdict, err = audit_spawn.run_codex_auditor("prompt", 60, sink)
        assert corr.call_count == expected, (side_effect, sink)
        if side_effect is failed:
            assert verdict is None and err.startswith("codex quota exhausted (quota_exhausted)")


@_POSIX_ONLY
@pytest.mark.parametrize("freeze,first_model", [(None, "gpt-6-astra"), ("gpt-5.6-sol", "gpt-5.6-sol")])
def test_sol_is_never_the_substitute(tmp_path: Path, freeze: Optional[str], first_model: str) -> None:
    """(9) SOL NEVER. With no freeze codex's pin is astra; with the sol freeze it is sol. Either
    way a failed call is followed by NO further codex call (not on sol, not on anything), and
    the substitute is the Claude alias — never a gpt- model. A pre-call refusal under the
    no-freeze fixture spawns no codex call at all."""
    home = _substitution_home(tmp_path, freeze=freeze)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["429"], claude_plan=[_PASS, _SUB_PASS], wait=True,
        codex_on_path=True)
    assert run["code"] == 0
    assert [_model_arg(c, "-m") for c in run["codex"]] == [first_model]
    for call in run["claude"]:
        model = _model_arg(call, "--model")
        assert model == MAIN and not model.lower().startswith("gpt-")
    assert run["out"]["model_provenance"]["codex"]["codex_arm_substituted_by"] == MAIN
    for row in _substitution_rows(run):
        assert row["served_model"] == MAIN and row["requested_model"] == first_model
    # RE-POINTED by #282 R3 (plan K5): the telemetry row's alias is on `model`; its served_model is
    # the envelope's modelUsage id, "unknown" for this stub (the budget row above is unchanged).
    assert run["rows"]["audit_codex"]["model"] == MAIN
    assert run["rows"]["audit_codex"]["served_model"] == audit_spawn.MODEL_UNKNOWN

    if freeze is None:
        ctl_root = tmp_path / "precall"
        precall = _run_substitution_cli(ctl_root, _substitution_home(ctl_root, freeze=None,
                                                                     reached_type="primary"),
                                        codex_plan=["ok"], claude_plan=[_PASS])
        assert precall["codex"] == []
        assert all(_model_arg(c, "--model") == MAIN for c in precall["claude"])
        assert [r["requested_model"] for r in _substitution_rows(precall)] == ["gpt-6-astra"]


# --- in-process runs: timeouts need a short codex budget, so the module constants are patched ---

def _in_process_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, *,
                      codex_plan: List[str], claude_plan: List[Any], codex_timeout_s: int = 3,
                      wait: bool = False, codex_bin_override: bool = False,
                      idle_timeout_s: Optional[float] = None) -> Dict[str, Any]:
    """#282 fix round 1: `codex_bin_override=True` also sets CODEX_BIN_OVERRIDE to the record
    _bin_override() would make for the codex stub — the in-process way to run a stub that
    HANGS under an override on a bounded timeout. Default False keeps every earlier caller's
    behaviour (the stub is CODEX_BIN with no override recorded).

    S081 revision 4 (WP-A03, D24): `codex_timeout_s` is now the watchdog's HARD CAP, and
    `idle_timeout_s` sets the SILENCE timeout — the two stops that used to be one number.
    A `sleep` stub is SILENT, so which one a test drives decides what it proves:
      * idle_timeout_s below the cap -> the stub is stopped for going quiet, the RETRYABLE
        stop (retry once, then substitute `timeout_twice`);
      * no idle_timeout_s, cap reached -> the runaway stop, a GAP.
    A test that wants the old "hangs past its budget -> retry" meaning must now set
    `idle_timeout_s`; left unset it would get a gap instead, which is a different assertion.
    """
    root, bundle = _audit_project(tmp_path)
    bindir = tmp_path / "inproc-bin"
    claude_stub = _write_stub(bindir / "claude-stub", _SUBSTITUTION_STUB)
    codex_stub = _write_stub(bindir / "codex-stub", _SUBSTITUTION_STUB)
    log = tmp_path / "inproc-argv.jsonl"
    for key, value in _stub_env(log, codex_plan, claude_plan, wait).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(audit_spawn, "CLAUDE_BIN", str(claude_stub))
    monkeypatch.setattr(audit_spawn, "CODEX_BIN", str(codex_stub))
    monkeypatch.setattr(audit_spawn, "CODEX_TIMEOUT_S", codex_timeout_s)
    if idle_timeout_s is not None:
        monkeypatch.setattr(audit_spawn.codex_watch, "IDLE_TIMEOUT_S", idle_timeout_s)
    if codex_bin_override:
        monkeypatch.setattr(audit_spawn, "CODEX_BIN_OVERRIDE",
                            {"var": "AUDIT_CODEX_BIN", "value": str(codex_stub),
                             "realpath": os.path.realpath(str(codex_stub))})
    with pytest.raises(SystemExit) as exc:
        audit_spawn.main(["audit_spawn.py", "comp-x", str(bundle), "--project-root", str(root)])
    calls = _read_jsonl(log)
    return {
        "code": exc.value.code, "out": json.loads(capsys.readouterr().out), "root": root,
        "codex": [c for c in calls if c["kind"] == "codex"], "claude": [c for c in calls if c["kind"] == "claude"],
        "budget": _budget_rows(Path.home(), root),
        "rows": {r["tool"]: r for r in _read_jsonl(root / ".process-observations" / "spawn-runs.jsonl")},
    }


@_POSIX_ONLY
def test_codex_timeout_once_then_valid_is_retried_not_substituted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                  capsys: pytest.CaptureFixture) -> None:
    """(2a) the first codex call GOES SILENT and is stopped; the same-model retry answers.
    Codex is called twice, nothing is substituted.

    RE-POINTED (S081 revision 4, WP-A03, D24): the stub is unchanged and so is every
    assertion — only WHICH STOP the test drives is now stated explicitly. "Runs past its
    budget" used to be the single available stop; D24 splits it, and the RETRYABLE one is
    the idle timeout. Driving the cap instead would be a GAP, which is a different test (see
    test_d24_a_stub_active_to_the_hard_cap_is_a_gap_with_no_substitution).
    """
    run = _in_process_audit(tmp_path, monkeypatch, capsys, codex_plan=["sleep", "ok"], claude_plan=[_PASS],
                            codex_timeout_s=30, idle_timeout_s=1)
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", run["out"]
    assert len(run["codex"]) == 2 and len(run["claude"]) == 1
    assert run["codex"][0]["argv"] == run["codex"][1]["argv"]
    assert run["out"]["model_provenance"]["codex"]["codex_attempts"] == 2
    assert _substitution_rows(run) == []


@_POSIX_ONLY
def test_codex_timeout_twice_substitutes_timeout_twice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                       capsys: pytest.CaptureFixture) -> None:
    """(2b) both codex calls go silent -> codex was called EXACTLY twice, then the substitute
    (reason timeout_twice) serves the slot.

    RE-POINTED (S081 revision 4, WP-A03, D24): drives the idle timeout, for the reason given
    on test_codex_timeout_once_then_valid_is_retried_not_substituted. The reason token
    `timeout_twice` is UNCHANGED — D24 invented no new substitution reason.
    """
    run = _in_process_audit(tmp_path, monkeypatch, capsys, codex_plan=["sleep"], claude_plan=[_PASS],
                            codex_timeout_s=30, idle_timeout_s=1)
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", run["out"]
    assert len(run["codex"]) == 2
    assert len(run["claude"]) == 2
    block = run["out"]["model_provenance"]["codex"]
    assert (block["substitution_reason"], block["codex_attempts"], block["codex_arm_substituted_by"]) == (
        "timeout_twice", 2, MAIN)
    assert [r["reason"] for r in _substitution_rows(run)] == ["timeout_twice"]
    assert run["rows"]["audit_codex"]["substitution_reason"] == "timeout_twice"


def test_join_timeout_is_passed_to_both_futures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                capsys: pytest.CaptureFixture) -> None:
    """(10) main() joins both futures on _join_timeout_s(claude, codex, substitute) — the pinned
    values give 5430. Subprocesses are mocked; only the join arithmetic is under test.

    RE-POINTED (S081 revision 4, WP-A03): 1830 -> 5430, following the codex arm's raised
    ceiling. What this test guards is that BOTH futures join on the SAME computed value and
    that the value comes from _join_timeout_s rather than a literal — unchanged.
    """
    root, bundle = _audit_project(tmp_path)
    monkeypatch.setattr(audit_spawn, "_codex_cli_missing", lambda: False)
    seen: List[Any] = []

    def fake_run(cmd, **kwargs):
        if "codex" in str(cmd[0]).lower():
            return SimpleNamespace(stdout=_audit_verdict_json(), returncode=0, stderr="")
        return SimpleNamespace(stdout=json.dumps([{"type": "result", "result": _audit_verdict_json()}]),
                               returncode=0, stderr="")

    class SpyFuture:
        def __init__(self, future):
            self._future = future

        def result(self, timeout=None):
            seen.append(timeout)
            return self._future.result(timeout=timeout)

    class SpyPool(audit_spawn.ThreadPoolExecutor):
        def submit(self, *args, **kwargs):
            return SpyFuture(super().submit(*args, **kwargs))

    with _codex_spawn_patched(fake_run), \
            mock.patch.object(audit_spawn, "ThreadPoolExecutor", SpyPool), \
            mock.patch.object(audit_spawn, "_join_timeout_s", wraps=audit_spawn._join_timeout_s) as join:
        with pytest.raises(SystemExit) as exc:
            audit_spawn.main(["audit_spawn.py", "comp-x", str(bundle), "--project-root", str(root)])
    assert exc.value.code == 0, capsys.readouterr()
    join.assert_called_once_with(audit_spawn.DEFAULT_TIMEOUT_S, audit_spawn.CODEX_TIMEOUT_S,
                                 audit_spawn.SUBSTITUTE_TIMEOUT_S)
    assert seen == [5430, 5430]


def test_join_timeout_comment_records_the_freshness_limit() -> None:
    """J13 RECORDED LIMIT, written where the number is computed: the worst case against the
    1800s ARBITER_FRESHNESS_WINDOW_S, needs two codex failures, fails closed.

    RE-POINTED (S081 revision 4, WP-A03): the worst case moved 1830 -> 5430 when D24 raised
    the codex arm's ceiling. The GUARD is unchanged and is the point of this test — the limit
    must still be WRITTEN DOWN where the number is computed, and the window must still be
    1800 (the criterion is "J13 IS RECORDED, NOT SILENTLY WIDENED"; widening the window to
    make the exceedance go away is exactly what this test exists to catch).
    """
    source = Path(audit_spawn.__file__).read_text(encoding="utf-8")
    head = source[source.index("def _join_timeout_s"):]
    head = head[:head.index("\ndef ", 1)]
    for needle in ("5430", "ARBITER_FRESHNESS_WINDOW_S", "1800", "twice", "fail-closed"):
        assert needle in head, needle
    # The premise the limit states: claims' freshness window default is 1800.
    claims_source = (_META / "claims.py").read_text(encoding="utf-8")
    assert '"ARBITER_FRESHNESS_WINDOW_S", "1800"' in claims_source


def test_substitute_timeout_is_the_code_reviewer_claude_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                           capsys: pytest.CaptureFixture) -> None:
    """J13: the substitute's budget is the code_reviewer Claude ROW (600), not `--timeout`, which
    bounds the Claude arm only. With `--timeout 900` the two claude subprocesses get 900 (arm)
    and 600 (substitute); CONTROL without the flag both get the row's 600."""
    assert audit_spawn.SUBSTITUTE_TIMEOUT_S == seat_model.ROLE_TABLE["code_reviewer"]["claude"].timeout == 600
    monkeypatch.setattr(audit_spawn, "_codex_cli_missing", lambda: True)

    def run(extra: List[str], root_dir: Path) -> List[Any]:
        timeouts: List[Any] = []

        def fake_run(cmd, **kwargs):
            timeouts.append(kwargs.get("timeout"))
            return SimpleNamespace(stdout=json.dumps([{"type": "result", "result": _audit_verdict_json()}]),
                                   returncode=0, stderr="")

        root, bundle = _audit_project(root_dir)
        with _codex_spawn_patched(fake_run):
            with pytest.raises(SystemExit) as exc:
                audit_spawn.main(["audit_spawn.py", "comp-x", str(bundle), "--project-root", str(root), *extra])
        out = json.loads(capsys.readouterr().out)
        assert exc.value.code == 0 and out["model_provenance"]["codex"]["substitute_timeout_s"] == 600
        return sorted(timeouts)

    assert run(["--timeout", "900"], tmp_path / "flag") == [600, 900]
    assert run([], tmp_path / "noflag") == [600, 600]


def test_the_exhaustion_matcher_has_one_owner() -> None:
    """J9: audit_spawn's duplicate patterns are gone and the codex arm relabels a quota stop
    through codex_quota's matcher (a patched owner changes what the arm reports).

    RE-POINTED by #282 R2 ("_codex_attempt no longer calls exhaustion_signal"; the error text and
    quota_source come from the ONE classification): the owner is codex_quota.classify_codex_failure. A
    patched classifier saying (substitute, quota_exhausted) relabels the error; a patched
    exhaustion_signal is never consulted and changes nothing (CONTROL)."""
    assert not hasattr(audit_spawn, "_CODEX_EXHAUSTION_PATTERNS")
    assert not hasattr(audit_spawn, "_codex_exhaustion_signal")
    source = Path(audit_spawn.__file__).read_text(encoding="utf-8")
    assert "you(?:'|\\u2019)ve hit your usage limit" not in source
    assert "codex_quota.exhaustion_signal(" not in source and "codex_quota.auth_signal(" not in source
    run = _codex_spawn_patched(lambda c, **k: SimpleNamespace(stdout="", returncode=1, stderr="x"))
    sink: dict = {}
    with mock.patch.object(audit_spawn.codex_quota, "classify_codex_failure",
                           return_value=("substitute", "quota_exhausted")) as owner, run:
        verdict, err = audit_spawn.run_codex_auditor("the prompt", 60, sink)
    assert verdict is None and err.startswith("codex quota exhausted (quota_exhausted): codex exited 1")
    assert sink["quota_source"] == audit_spawn.QUOTA_SOURCE_EXHAUSTION
    owner.assert_called_once()
    assert owner.call_args.args == (1, "x") and owner.call_args.kwargs["prompt"] == "the prompt"

    sink = {}
    with mock.patch.object(audit_spawn.codex_quota, "exhaustion_signal", return_value="owner_sentinel") as helper, \
            mock.patch.object(audit_spawn.codex_quota, "auth_signal", return_value="owner_sentinel") as auth, run:
        verdict, err = audit_spawn.run_codex_auditor("the prompt", 60, sink)
    assert verdict is None and err.startswith("codex exited 1")
    assert helper.call_count == 0 and auth.call_count == 0
    assert sink["quota_source"] == audit_spawn.QUOTA_SOURCE_METER


def test_call_time_classification_goes_through_codex_quota(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                          capsys: pytest.CaptureFixture) -> None:
    """J9: the arm asks codex_quota.classify_codex_failure — with the prompt, so the echo is
    removed — and obeys it. A classifier forced to say `gap` turns a real 429 into
    AUDIT_UNAVAILABLE with no substitution (so the decision really is the owner's)."""
    root, bundle = _audit_project(tmp_path)
    monkeypatch.setattr(audit_spawn, "_codex_cli_missing", lambda: False)
    stderr_429 = "ERROR: exceeded retry limit, last status: 429 Too Many Requests\n"

    def fake_run(cmd, **kwargs):
        if "codex" in str(cmd[0]).lower():
            return SimpleNamespace(stdout="", returncode=1, stderr=stderr_429)
        return SimpleNamespace(stdout=json.dumps([{"type": "result", "result": _audit_verdict_json()}]),
                               returncode=0, stderr="")

    with _codex_spawn_patched(fake_run), \
            mock.patch.object(audit_spawn.codex_quota, "classify_codex_failure",
                              wraps=codex_quota.classify_codex_failure) as classify:
        with pytest.raises(SystemExit) as exc:
            audit_spawn.main(["audit_spawn.py", "comp-x", str(bundle), "--project-root", str(root)])
    out = json.loads(capsys.readouterr().out)
    assert exc.value.code == 0 and out["model_provenance"]["codex"]["substitution_reason"] == "quota_exhausted"
    assert classify.call_count == 1
    args, kwargs = classify.call_args
    assert args == (1, stderr_429)
    assert kwargs["attempt"] == 1 and kwargs["timed_out"] is False and kwargs["output_ok"] is False
    assert kwargs["prompt"].startswith("You are a cold-context metacognitive auditor")
    # #282 R2: the failed call's ONE corroboration travels with the ONE classify call.
    assert kwargs["corroboration"] == {"codex_error_lines": [stderr_429.rstrip("\n")], "unavailable_token": None}

    root2 = tmp_path / "forced"
    root2.mkdir()
    _root2, bundle2 = _audit_project(root2)
    with _codex_spawn_patched(fake_run), \
            mock.patch.object(audit_spawn.codex_quota, "classify_codex_failure", return_value=("gap", "codex_error")):
        with pytest.raises(SystemExit) as exc:
            audit_spawn.main(["audit_spawn.py", "comp-x", str(bundle2), "--project-root", str(_root2)])
    forced = json.loads(capsys.readouterr().out)
    assert exc.value.code == 4 and forced["result"] == "AUDIT_UNAVAILABLE"
    assert "codex_arm_substituted_by" not in forced["model_provenance"]["codex"]


def test_a_substitution_that_cannot_be_made_is_audit_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                 capsys: pytest.CaptureFixture) -> None:
    """seat_model.substitute raising (a harness bug) never lets the codex slot pass unfilled
    and never falls back to an unrecorded Claude call: AUDIT_UNAVAILABLE naming both."""
    root, bundle = _audit_project(tmp_path)
    monkeypatch.setattr(audit_spawn, "_codex_cli_missing", lambda: True)
    calls: List[Any] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd[0])
        return SimpleNamespace(stdout=json.dumps([{"type": "result", "result": _audit_verdict_json()}]),
                               returncode=0, stderr="")

    with _codex_spawn_patched(fake_run), \
            mock.patch.object(audit_spawn.seat_model, "substitute",
                              side_effect=seat_model.SeatModelError("broken table")):
        with pytest.raises(SystemExit) as exc:
            audit_spawn.main(["audit_spawn.py", "comp-x", str(bundle), "--project-root", str(root)])
    out = json.loads(capsys.readouterr().out)
    assert exc.value.code == 4 and out["result"] == "AUDIT_UNAVAILABLE"
    assert set(out) == _UNAVAILABLE_KEYS
    assert "cli_missing" in out["codex_error"] and "broken table" in out["codex_error"]
    assert len(calls) == 1  # the Claude arm only: no unrecorded substitute ran
    block = out["model_provenance"]["codex"]
    assert "codex_arm_substituted_by" not in block
    assert block["substitution_reason"] == "cli_missing" and "broken table" in block["substitution_error"]


def test_an_unwritten_substitution_row_is_visible_in_the_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                    capsys: pytest.CaptureFixture) -> None:
    """A budget store that cannot take the row still serves the seat (seat_model's contract),
    and the verdict says the row is missing. CONTROL: a writable store -> no such key."""
    root, bundle = _audit_project(tmp_path)
    monkeypatch.setattr(audit_spawn, "_codex_cli_missing", lambda: True)

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout=json.dumps([{"type": "result", "result": _audit_verdict_json()}]),
                               returncode=0, stderr="")

    broken = {"row_written": False, "error": "OSError: read-only store"}
    with _codex_spawn_patched(fake_run), \
            mock.patch.object(seat_model.codex_quota, "record_substitution", return_value=broken):
        with pytest.raises(SystemExit) as exc:
            audit_spawn.main(["audit_spawn.py", "comp-x", str(bundle), "--project-root", str(root)])
    out = json.loads(capsys.readouterr().out)
    assert exc.value.code == 0 and out["result"] == "VERIFIED"
    assert "read-only store" in out["model_provenance"]["codex"]["substitution_row_error"]

    ctl, ctl_bundle = _audit_project(tmp_path / "ctl")
    with _codex_spawn_patched(fake_run):
        with pytest.raises(SystemExit):
            audit_spawn.main(["audit_spawn.py", "comp-x", str(ctl_bundle), "--project-root", str(ctl)])
    control = json.loads(capsys.readouterr().out)
    assert "substitution_row_error" not in control["model_provenance"]["codex"]
    assert control["model_provenance"]["codex"]["substitution_reason"] == "cli_missing"


def test_a_binary_that_vanishes_after_the_check_substitutes_cli_missing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """The presence check passed but the spawn raised FileNotFoundError (the binary went away
    in between): the classifier sees exit 127 -> substitute cli_missing after ONE attempt.
    CONTROL: an OSError that is not a missing binary is a gap (AUDIT_UNAVAILABLE)."""
    monkeypatch.setattr(audit_spawn, "_codex_cli_missing", lambda: False)

    def runner(codex_exc):
        def fake_run(cmd, **kwargs):
            if "codex" in str(cmd[0]).lower():
                raise codex_exc
            return SimpleNamespace(stdout=json.dumps([{"type": "result", "result": _audit_verdict_json()}]),
                                   returncode=0, stderr="")
        return fake_run

    root, bundle = _audit_project(tmp_path)
    with _codex_spawn_patched(runner(FileNotFoundError())):
        with pytest.raises(SystemExit) as exc:
            audit_spawn.main(["audit_spawn.py", "comp-x", str(bundle), "--project-root", str(root)])
    out = json.loads(capsys.readouterr().out)
    assert exc.value.code == 0 and out["result"] == "VERIFIED"
    block = out["model_provenance"]["codex"]
    assert (block["substitution_reason"], block["codex_attempts"]) == ("cli_missing", 1)
    # The admission was recorded (the spawn was attempted), and so is the substitution.
    kinds = [(r.get("kind", "admit"), r["use"], r["reason"]) for r in _budget_rows(Path.home(), root)]
    assert kinds == [("admit", "audit", "audit_exempt"), ("substitution", "audit", "cli_missing")]

    ctl, ctl_bundle = _audit_project(tmp_path / "ctl")
    with _codex_spawn_patched(runner(PermissionError("denied"))):
        with pytest.raises(SystemExit) as exc:
            audit_spawn.main(["audit_spawn.py", "comp-x", str(ctl_bundle), "--project-root", str(ctl)])
    control = json.loads(capsys.readouterr().out)
    assert exc.value.code == 4 and control["result"] == "AUDIT_UNAVAILABLE"
    assert control["codex_error"].startswith("codex subprocess OS error")
    assert "substitution_reason" not in control["model_provenance"]["codex"]


def test_a_retried_codex_call_keeps_the_first_quota_reading(_isolated_home: Path, tmp_path: Path) -> None:
    """The meter brackets the WHOLE slot: quota_before is read before the FIRST call and
    quota_after after the LAST, so a retry cannot hide the quota the first call spent.
    Each fake call writes a newer rollout; only the first reading sees the original 10%."""
    now = time.time()
    _write_rollout(_isolated_home, "00000000-0000-0000-0000-00000000dddd",
                   [_rollout_event(now - 120, 10.0, 5.0)], at=now - 120)
    calls: List[int] = []

    def fake_run(cmd, **kwargs):
        calls.append(1)
        _write_rollout(_isolated_home, f"00000000-0000-0000-0000-00000000{len(calls):04d}",
                       [_rollout_event(time.time() - 10 + len(calls), 10.0 + 5 * len(calls), 5.0)])
        stdout = "not a verdict" if len(calls) == 1 else _audit_verdict_json()
        return SimpleNamespace(stdout=stdout, returncode=0, stderr="")

    sink: Dict[str, Any] = {}
    with _codex_spawn_patched(fake_run):
        verdict, err = audit_spawn._run_codex_arm("prompt", 60, sink, project_root=tmp_path, precall_reason=None)
    assert err is None and verdict["verdict"] == "pass"
    assert len(calls) == 2 and sink["codex_attempts"] == 2
    assert sink["quota_before"]["primary_used_percent"] == 10.0
    assert sink["quota_after"]["primary_used_percent"] == 20.0
    assert "substitution" not in sink


def test_codex_cli_missing_follows_the_binary_constant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """J12: presence is shutil.which(CODEX_BIN), an in-process PATH lookup — so an
    AUDIT_CODEX_BIN stub counts as present and a missing path as missing."""
    stub = _write_stub(tmp_path / "bin" / "codex-stub")
    monkeypatch.setattr(audit_spawn, "CODEX_BIN", str(stub))
    assert audit_spawn._codex_cli_missing() is False
    monkeypatch.setattr(audit_spawn, "CODEX_BIN", str(tmp_path / "missing" / "codex"))
    assert audit_spawn._codex_cli_missing() is True
    with _codex_spawn_patched(AssertionError("no subprocess")):
        audit_spawn._codex_cli_missing()


# ---------------------------------------------------------------------------
# #282 R1 — a binary override never becomes a substitution (plan K6)
# ---------------------------------------------------------------------------
#
# `cli_missing` substitutes only for the un-overridden `codex` looked up on PATH. When
# AUDIT_CODEX_BIN is set and names no binary, the codex slot is a GAP: AUDIT_UNAVAILABLE with
# no admission row, no substitution row and no codex spawn (pre-call), or no substitution
# (call time, exit 127). Every guard has a CONTROL on the un-overridden binary, which still
# substitutes — so the gap cannot pass because the substitution path is simply broken.


def _claude_envelope_run(calls: List[Any]):
    """A subprocess.run fake: logs cmd[0]; the Claude arm and the substitute answer a pass."""
    def fake_run(cmd, **kwargs):
        calls.append(str(cmd[0]))
        if "codex" in os.path.basename(str(cmd[0])).lower():
            raise AssertionError(f"codex must not be spawned: {cmd[0]}")
        return SimpleNamespace(stdout=json.dumps([{"type": "result", "result": _audit_verdict_json()}]),
                               returncode=0, stderr="")
    return fake_run


def _override_record(path: Path) -> Dict[str, str]:
    """The record _bin_override() makes for AUDIT_CODEX_BIN naming a missing path."""
    return {"var": "AUDIT_CODEX_BIN", "value": str(path), "realpath": "unresolvable"}


def test_r1_plan_time_an_overridden_missing_codex_binary_is_a_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                  capsys: pytest.CaptureFixture) -> None:
    """(a) PLAN-TIME. CODEX_BIN_OVERRIDE set + CODEX_BIN missing -> exit 4 AUDIT_UNAVAILABLE decided
    before any admission: _admit_audit never called, the fixture budget store has NO row of any
    kind, codex never spawned, and codex_error names the override. CONTROL: CODEX_BIN_OVERRIDE
    None and `codex` absent from PATH -> the cli_missing substitution (row written)."""
    missing = tmp_path / "missing" / "codex"
    root, bundle = _audit_project(tmp_path)
    monkeypatch.setattr(audit_spawn, "CODEX_BIN", str(missing))
    monkeypatch.setattr(audit_spawn, "CODEX_BIN_OVERRIDE", _override_record(missing))
    assert audit_spawn._plan_time_unavailable() == audit_spawn.PRECALL_GAP_BIN_OVERRIDE
    assert audit_spawn.PRECALL_GAP_BIN_OVERRIDE not in codex_quota.SUBSTITUTION_REASONS
    calls: List[Any] = []
    with _codex_spawn_patched(_claude_envelope_run(calls)), \
            mock.patch.object(audit_spawn, "_admit_audit", wraps=audit_spawn._admit_audit) as admit, \
            mock.patch.object(audit_spawn.seat_model, "substitute", wraps=audit_spawn.seat_model.substitute) as sub:
        with pytest.raises(SystemExit) as exc:
            audit_spawn.main(["audit_spawn.py", "comp-x", str(bundle), "--project-root", str(root)])
    out = json.loads(capsys.readouterr().out)
    assert exc.value.code == 4 and out["result"] == "AUDIT_UNAVAILABLE", out
    assert set(out) == _UNAVAILABLE_KEYS
    assert out["claude_verdict"] is not None and out["codex_verdict"] is None
    assert "AUDIT_CODEX_BIN" in out["codex_error"] and str(missing) in out["codex_error"]
    assert "unresolvable" in out["codex_error"] and "gap" in out["codex_error"]
    admit.assert_not_called()
    sub.assert_not_called()
    assert _budget_rows(Path.home(), root) == []          # no admission row, no substitution row
    assert len(calls) == 1                                  # the Claude arm only
    block = out["model_provenance"]["codex"]
    for key in _SUBSTITUTION_PROVENANCE + ("substitution_error", "substitution_row_error",
                                           "substitute_bin_override"):
        assert key not in block, key
    assert block["bin_override"] == _override_record(missing)

    # CONTROL — the un-overridden binary missing from PATH still substitutes.
    ctl_root, ctl_bundle = _audit_project(tmp_path / "control")
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    monkeypatch.setattr(audit_spawn, "CODEX_BIN", "codex")
    monkeypatch.setattr(audit_spawn, "CODEX_BIN_OVERRIDE", None)
    monkeypatch.setenv("PATH", str(empty_path))
    assert audit_spawn._plan_time_unavailable() == "cli_missing"
    ctl_calls: List[Any] = []
    with _codex_spawn_patched(_claude_envelope_run(ctl_calls)):
        with pytest.raises(SystemExit) as exc:
            audit_spawn.main(["audit_spawn.py", "comp-x", str(ctl_bundle), "--project-root", str(ctl_root)])
    control = json.loads(capsys.readouterr().out)
    assert exc.value.code == 0 and control["result"] == "VERIFIED", control
    ctl_block = control["model_provenance"]["codex"]
    assert (ctl_block["codex_arm_substituted_by"], ctl_block["substitution_reason"]) == (MAIN, "cli_missing")
    assert "bin_override" not in ctl_block
    assert len(ctl_calls) == 2                              # the arm + the substitute
    assert [(r["kind"], r["reason"]) for r in _budget_rows(Path.home(), ctl_root)] == [("substitution", "cli_missing")]


@_POSIX_ONLY
def test_r1_an_overridden_missing_codex_binary_is_audit_unavailable(tmp_path: Path) -> None:
    """(b) VERDICT-LEVEL, the real CLI. AUDIT_CODEX_BIN points at a missing path (AUDIT_CLAUDE_BIN
    is a stub returning a valid verdict) -> exit 4 AUDIT_UNAVAILABLE; codex_error names the
    override and its realpath; the codex block has bin_override and NO codex_arm_substituted_by /
    substitution_reason; the budget store has no row at all; the Claude stub ran ONCE (no
    substitute). CONTROL without AUDIT_CODEX_BIN and a PATH lacking codex -> the substitute served
    the slot (codex_arm_substituted_by present)."""
    home = _substitution_home(tmp_path)
    missing = tmp_path / "no-such-dir" / "codex"
    run = _run_substitution_cli(tmp_path, home, codex_plan=["ok"], claude_plan=[_PASS], codex_bin=missing)
    assert run["code"] == 4, (run["out"], run["stderr"])
    _assert_top_level_keys(run)
    out = run["out"]
    assert out["result"] == "AUDIT_UNAVAILABLE"
    assert out["claude_verdict"]["reason"] == "stub pass" and out["codex_verdict"] is None
    assert "AUDIT_CODEX_BIN" in out["codex_error"] and str(missing) in out["codex_error"]
    assert "unresolvable" in out["codex_error"]
    block = out["model_provenance"]["codex"]
    assert block["bin_override"] == {"var": "AUDIT_CODEX_BIN", "value": str(missing), "realpath": "unresolvable"}
    assert "codex_arm_substituted_by" not in block and "substitution_reason" not in block
    _assert_no_substitution(run)
    assert run["budget"] == []                              # no admission row either
    assert run["codex"] == [] and len(run["claude"]) == 1

    ctl_root = tmp_path / "control"
    control = _run_substitution_cli(ctl_root, _substitution_home(ctl_root), codex_plan=["ok"], claude_plan=[_PASS],
                                    codex_bin_env=False, path_dir=ctl_root / "path-without-codex")
    assert control["code"] == 0 and control["out"]["result"] == "VERIFIED", (control["out"], control["stderr"])
    ctl_block = control["out"]["model_provenance"]["codex"]
    assert (ctl_block["codex_arm_substituted_by"], ctl_block["substitution_reason"]) == (MAIN, "cli_missing")
    assert "bin_override" not in ctl_block
    assert [r["reason"] for r in _substitution_rows(control)] == ["cli_missing"]
    assert control["codex"] == [] and len(control["claude"]) == 2


def test_r1_call_time_exit_127_with_the_override_set_is_a_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """(c) CALL-TIME. The presence check passed but the spawn raised FileNotFoundError (the
    classifier sees 127 -> substitute cli_missing): with CODEX_BIN_OVERRIDE set the slot is a gap
    — (None, error naming the override), no substitution record, no substitution row, ONE codex
    attempt. CONTROL without the override -> the same outcome substitutes cli_missing."""
    override_path = tmp_path / "vanished" / "codex"
    codex_spawns: List[Any] = []

    def fake_run(cmd, **kwargs):
        if "codex" in os.path.basename(str(cmd[0])).lower():
            codex_spawns.append(cmd[0])
            raise FileNotFoundError(str(cmd[0]))
        return SimpleNamespace(stdout=json.dumps([{"type": "result", "result": _audit_verdict_json()}]),
                               returncode=0, stderr="")

    monkeypatch.setattr(audit_spawn, "CODEX_BIN", str(override_path))
    monkeypatch.setattr(audit_spawn, "CODEX_BIN_OVERRIDE", {"var": "AUDIT_CODEX_BIN", "value": str(override_path),
                                                            "realpath": str(override_path)})
    sink: Dict[str, Any] = {}
    root = tmp_path / "proj-gap"
    root.mkdir()
    with _codex_spawn_patched(fake_run), \
            mock.patch.object(audit_spawn.codex_quota, "classify_codex_failure",
                              wraps=codex_quota.classify_codex_failure) as classify:
        verdict, err = audit_spawn._run_codex_arm("prompt", 60, sink, project_root=root, precall_reason=None)
    # The classifier stays override-blind: it still says substitute cli_missing; the arm maps it.
    assert classify.call_count == 1
    assert codex_quota.classify_codex_failure(*classify.call_args.args, **classify.call_args.kwargs) == (
        codex_quota.ACTION_SUBSTITUTE, "cli_missing")
    assert verdict is None
    assert "AUDIT_CODEX_BIN" in err and str(override_path) in err and "gap" in err
    assert "codex binary not found" in err                  # the call-time spawn error is kept
    assert "substitution" not in sink and sink["codex_attempts"] == 1 and len(codex_spawns) == 1
    assert _budget_rows(Path.home(), root) == []

    # CONTROL — the same 127 outcome without the override substitutes.
    monkeypatch.setattr(audit_spawn, "CODEX_BIN_OVERRIDE", None)
    ctl_sink: Dict[str, Any] = {}
    ctl_root = tmp_path / "proj-control"
    ctl_root.mkdir()
    with _codex_spawn_patched(fake_run):
        verdict, err = audit_spawn._run_codex_arm("prompt", 60, ctl_sink, project_root=ctl_root, precall_reason=None)
    assert err is None and verdict["verdict"] == "pass"
    assert ctl_sink["substitution"]["reason"] == "cli_missing" and ctl_sink["substitution"]["served_model"] == MAIN
    assert [(r["kind"], r["reason"]) for r in _budget_rows(Path.home(), ctl_root)] == [("substitution", "cli_missing")]


@_POSIX_ONLY
def test_r1_substitute_bin_override_records_the_claude_binary_the_substitute_ran(tmp_path: Path) -> None:
    """(d) AUDIT_CLAUDE_BIN stub + a pre-call substitution (AUDIT_CODEX_BIN unset, no codex on PATH)
    -> the codex block's substitute_bin_override is the AUDIT_CLAUDE_BIN record (realpath == the
    stub's), the codex block has NO bin_override (that key means AUDIT_CODEX_BIN only) and the
    Claude block keeps its own bin_override. CONTROL without AUDIT_CLAUDE_BIN (a `claude` stub
    found on PATH) -> no substitute_bin_override key, and no bin_override anywhere."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["ok"], claude_plan=[_PASS], codex_bin_env=False,
                                path_dir=tmp_path / "path-without-codex")
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", (run["out"], run["stderr"])
    stub_realpath = os.path.realpath(str(tmp_path / "sub-bin" / "claude-stub"))
    codex_block = run["out"]["model_provenance"]["codex"]
    claude_block = run["out"]["model_provenance"]["claude"]
    assert codex_block["codex_arm_substituted_by"] == MAIN
    assert codex_block["substitute_bin_override"] == {
        "var": "AUDIT_CLAUDE_BIN", "value": str(tmp_path / "sub-bin" / "claude-stub"), "realpath": stub_realpath}
    assert "bin_override" not in codex_block
    assert claude_block["bin_override"]["realpath"] == stub_realpath
    assert "substitute_bin_override" not in claude_block

    ctl_root = tmp_path / "control"
    control = _run_substitution_cli(ctl_root, _substitution_home(ctl_root), codex_plan=["ok"], claude_plan=[_PASS],
                                    codex_bin_env=False, claude_bin_env=False,
                                    path_dir=ctl_root / "path-with-claude-only")
    assert control["code"] == 0 and control["out"]["result"] == "VERIFIED", (control["out"], control["stderr"])
    ctl_codex = control["out"]["model_provenance"]["codex"]
    assert ctl_codex["codex_arm_substituted_by"] == MAIN and len(control["claude"]) == 2
    assert "substitute_bin_override" not in ctl_codex and "bin_override" not in ctl_codex
    assert "bin_override" not in control["out"]["model_provenance"]["claude"]


# ---------------------------------------------------------------------------
# #282 fix round 1 F1 — EVERY classifier substitution under an override is a gap
# ---------------------------------------------------------------------------
#
# R1 closed only `cli_missing`. An AUDIT_CODEX_BIN that EXITS 0 with unusable output reaches
# `malformed_twice`, a hanging one `timeout_twice`, a 429 `quota_exhausted`, an expired token
# `auth_failure` — and each of those still bought a Fable substitute, i.e. two Claude verdicts
# for a conjunction that must have two providers. Fix (plan K35/K36): at the call site, EVERY
# `action == ACTION_SUBSTITUTE` decision returns the override gap when CODEX_BIN_OVERRIDE is
# set. The classifier stays override-blind and pure. Every guard has the NEGATIVE CONTROL the
# spec names: the SAME stub reached through PATH with AUDIT_CODEX_BIN UNSET still substitutes,
# so a gap cannot pass merely because the substitution path is broken.


def _assert_override_gap(out: Dict[str, Any], *, reason: str) -> None:
    """The K36 gap message: the variable, its recorded value and realpath, `produced <reason>`.

    The value/realpath are read back from the codex provenance block's own `bin_override`
    record, so the message is checked against what the run actually recorded — never
    against a path the test guessed.
    """
    err = out["codex_error"]
    record = out["model_provenance"]["codex"]["bin_override"]
    assert err is not None
    assert record["var"] == "AUDIT_CODEX_BIN"
    assert f"AUDIT_CODEX_BIN={record['value']!r}" in err
    assert f"(realpath {record['realpath']!r})" in err
    assert f"produced {reason}" in err
    assert "never substituted" in err and "gap" in err


@_POSIX_ONLY
@pytest.mark.parametrize("plan,reason,attempts", [
    (["malformed", "malformed"], "malformed_twice", 2),   # (1) exits 0, unparseable stdout
    (["auth"], "auth_failure", 1),                        # (3) substitutes at once, no retry
    (["429", "429"], "quota_exhausted", 1),               # (3) a metered stop
    (["capacity", "capacity"], "capacity_twice", 2),      # (3) at capacity on both calls
])
def test_fr1_f1_every_classifier_substitution_under_an_override_is_a_gap(
        tmp_path: Path, plan: List[str], reason: str, attempts: int) -> None:
    """(1)+(3) A STUB THAT RUNS. AUDIT_CODEX_BIN names a stub that exits 0 with unparseable
    stdout / fails auth / is rate-limited / is at capacity -> the classifier says substitute,
    and the arm maps EVERY one of those to the override gap: exit 4 AUDIT_UNAVAILABLE, the
    codex_error names the override AND the classifier reason, NO substitution row in the
    temp-HOME budget store, no substitute spawn (the Claude stub ran exactly ONCE), and the
    codex block keeps `bin_override` and gains none of the substitution keys."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=plan, claude_plan=[_PASS], wait=True)
    assert run["code"] == 4, (run["out"], run["stderr"])
    _assert_top_level_keys(run)
    out = run["out"]
    assert out["result"] == "AUDIT_UNAVAILABLE"
    assert out["claude_verdict"]["reason"] == "stub pass" and out["codex_verdict"] is None
    _assert_override_gap(out, reason=reason)
    block = out["model_provenance"]["codex"]
    for key in ("codex_arm_substituted_by", "substitution_reason", "substitute_timeout_s",
                "provider_gap", "substitution_error", "substitution_row_error",
                "substitute_bin_override"):
        assert key not in block, key
    # codex_attempts follows the unchanged _build_model_provenance contract: recorded only
    # when the one same-model retry ran (attempts > 1), absent for a single attempt.
    assert block.get("codex_attempts") == (attempts if attempts > 1 else None)
    assert _substitution_rows(run) == []
    assert len(run["codex"]) == attempts
    assert len(run["claude"]) == 1                    # the arm only — nothing was substituted


@_POSIX_ONLY
@pytest.mark.parametrize("plan,reason", [
    (["malformed", "malformed"], "malformed_twice"),
    (["auth"], "auth_failure"),
    (["429", "429"], "quota_exhausted"),
    (["capacity", "capacity"], "capacity_twice"),
])
def test_fr1_f1_control_the_same_stub_through_path_without_the_override_substitutes(
        tmp_path: Path, plan: List[str], reason: str) -> None:
    """(4) NEGATIVE CONTROL for (1)+(3): the SAME stub behaviours reached as plain `codex` on
    PATH with AUDIT_CODEX_BIN UNSET keep the pre-S081 substitution — a Fable substitute serves
    the slot, the substitution row IS written, and the audit is VERIFIED. The gap above is
    therefore the override's doing, not a broken substitution path."""
    home = _substitution_home(tmp_path)
    path_dir = tmp_path / "path-with-codex"
    path_dir.mkdir(parents=True, exist_ok=True)
    _write_stub(path_dir / "codex", _SUBSTITUTION_STUB)
    run = _run_substitution_cli(tmp_path, home, codex_plan=plan, claude_plan=[_PASS, _SUB_PASS],
                                codex_bin_env=False, path_dir=path_dir)
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", (run["out"], run["stderr"])
    block = run["out"]["model_provenance"]["codex"]
    assert (block["codex_arm_substituted_by"], block["substitution_reason"]) == (MAIN, reason)
    assert "bin_override" not in block
    assert [r["reason"] for r in _substitution_rows(run)] == [reason]
    assert len(run["claude"]) == 2                    # the arm + the substitute


@_POSIX_ONLY
def test_fr1_f1_a_hanging_override_binary_is_a_gap_not_a_timeout_substitution(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """(2) A STUB THAT HANGS. Both codex calls run past a BOUNDED budget (codex_timeout_s=3, so
    the test is fast) -> `timeout_twice`; with the override set the slot is a GAP, not the
    substitution test_codex_timeout_twice_substitutes_timeout_twice asserts for the
    un-overridden binary. Exactly two codex attempts, one Claude call, no substitution row."""
    # RE-POINTED (S081 revision 4, WP-A03, D24): drives the IDLE timeout, so the classifier
    # still reaches `timeout_twice` and this test keeps asking its own question — does the
    # override turn that substitution into a gap? The cap would reach a gap by another route
    # and make the override irrelevant, i.e. would quietly make the test vacuous.
    run = _in_process_audit(tmp_path, monkeypatch, capsys, codex_plan=["sleep"], claude_plan=[_PASS],
                            codex_bin_override=True, codex_timeout_s=30, idle_timeout_s=1)
    assert run["code"] == 4 and run["out"]["result"] == "AUDIT_UNAVAILABLE", run["out"]
    _assert_override_gap(run["out"], reason="timeout_twice")
    block = run["out"]["model_provenance"]["codex"]
    assert block["codex_attempts"] == 2
    for key in ("codex_arm_substituted_by", "substitution_reason", "provider_gap",
                "substitute_timeout_s"):
        assert key not in block, key
    assert _substitution_rows(run) == []
    assert len(run["codex"]) == 2 and len(run["claude"]) == 1
    assert "substitute_for" not in run["rows"].get("audit_codex", {})


def test_fr1_f1_the_classifier_stays_override_blind(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """The mapping lives at the CALL SITE, not in codex_quota: with the override set the
    classifier still returns (substitute, malformed_twice) for the same inputs, and
    PRECALL_GAP_BIN_OVERRIDE is not a substitution reason. _substitute_codex_arm and
    seat_model.substitute are never reached."""
    override_path = tmp_path / "stub" / "codex"
    monkeypatch.setattr(audit_spawn, "CODEX_BIN", str(override_path))
    monkeypatch.setattr(audit_spawn, "CODEX_BIN_OVERRIDE",
                        {"var": "AUDIT_CODEX_BIN", "value": str(override_path),
                         "realpath": str(override_path)})

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(stdout="this is not a verdict", returncode=0, stderr="")

    sink: Dict[str, Any] = {}
    root = tmp_path / "proj-blind"
    root.mkdir()
    with _codex_spawn_patched(fake_run), \
            mock.patch.object(audit_spawn.codex_quota, "classify_codex_failure",
                              wraps=codex_quota.classify_codex_failure) as classify, \
            mock.patch.object(audit_spawn, "_substitute_codex_arm") as sub_arm, \
            mock.patch.object(audit_spawn.seat_model, "substitute") as sub:
        verdict, err = audit_spawn._run_codex_arm("prompt", 60, sink, project_root=root,
                                                  precall_reason=None)
    assert classify.call_count == 2                    # attempt 1 retried, attempt 2 substitutes
    assert codex_quota.classify_codex_failure(*classify.call_args.args,
                                              **classify.call_args.kwargs) == (
        codex_quota.ACTION_SUBSTITUTE, "malformed_twice")
    assert audit_spawn.PRECALL_GAP_BIN_OVERRIDE not in codex_quota.SUBSTITUTION_REASONS
    assert verdict is None
    assert f"AUDIT_CODEX_BIN={str(override_path)!r}" in err
    assert f"(realpath {str(override_path)!r})" in err
    assert "produced malformed_twice" in err and "never substituted" in err and "gap" in err
    sub_arm.assert_not_called()
    sub.assert_not_called()
    assert "substitution" not in sink and sink["codex_attempts"] == 2
    assert _budget_rows(Path.home(), root) == []


def test_fr1_f9_the_override_record_is_made_whenever_the_variable_is_present(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F9. CODEX_BIN_OVERRIDE is a RECORD of the variable's PRESENCE, not of a failure: it is
    made even when the value is literally `codex` and even when the binary RESOLVES (realpath
    is then a real path, not "unresolvable"). That is why a misbehaving binary under ANY
    override is a gap. Control: the variable unset -> None."""
    bindir = tmp_path / "bin"
    stub = _write_stub(bindir / "codex", _SUBSTITUTION_STUB)
    monkeypatch.setenv("PATH", str(bindir))

    monkeypatch.setenv("AUDIT_CODEX_BIN", "codex")     # the ordinary name, and it resolves
    record = audit_spawn._bin_override("AUDIT_CODEX_BIN")
    assert record == {"var": "AUDIT_CODEX_BIN", "value": "codex",
                      "realpath": os.path.realpath(str(stub))}
    assert record["realpath"] != "unresolvable"

    monkeypatch.setenv("AUDIT_CODEX_BIN", str(stub))   # an explicit path that resolves
    assert audit_spawn._bin_override("AUDIT_CODEX_BIN")["realpath"] == os.path.realpath(str(stub))

    monkeypatch.setenv("AUDIT_CODEX_BIN", "")          # present but empty: still a record
    assert audit_spawn._bin_override("AUDIT_CODEX_BIN") == {
        "var": "AUDIT_CODEX_BIN", "value": "", "realpath": "unresolvable"}

    monkeypatch.delenv("AUDIT_CODEX_BIN")              # CONTROL: absent -> no record
    assert audit_spawn._bin_override("AUDIT_CODEX_BIN") is None


def test_fr1_f9_docstrings_state_the_override_is_a_presence_record() -> None:
    """F9 is a DOCUMENTATION finding: _bin_override, _plan_time_unavailable and the module
    header must each say that the record is made whenever AUDIT_CODEX_BIN is PRESENT (even
    `codex`, even when it resolves), so a missing or misbehaving binary under ANY override is a
    gap, never `cli_missing` and never a substitution."""
    for owner in (audit_spawn._bin_override, audit_spawn._plan_time_unavailable):
        doc = (owner.__doc__ or "").lower()
        assert "present" in doc, owner.__name__
        assert "codex" in doc and "override" in doc, owner.__name__
    bin_doc = (audit_spawn._bin_override.__doc__ or "").lower()
    assert "resolves" in bin_doc or "resolve" in bin_doc
    plan_doc = (audit_spawn._plan_time_unavailable.__doc__ or "").lower()
    assert "never a substitution" in plan_doc or "never substituted" in plan_doc
    header = (audit_spawn.__doc__ or "").lower()
    assert "every substitution the classifier produces" in header
    gap_doc = (audit_spawn._bin_override_gap.__doc__ or "").lower()
    assert "reason" in gap_doc and "substitution" in gap_doc


# ---------------------------------------------------------------------------
# #282 R3 — reviewer Claude subprocesses never load the reviewed project's configuration
# ---------------------------------------------------------------------------
#
# Plan K2-K5. Every Claude reviewer launch (the Claude arm and the codex slot's Fable substitute)
# runs from ONE fixed empty directory with `--setting-sources user`, never `--bare`, stdin closed,
# and records the served model from the envelope's modelUsage. The autouse fixture points
# XDG_RUNTIME_DIR at a per-test tmp dir, so resolve_reviewer_cwd() resolves inside tmp_path.
# Every guard has a CONTROL: the pre-R3 argv/cwd really does see a poisoned settings file; a
# clean directory is accepted; alias-vs-full-id is not a mismatch while opus-for-fable is.

import verification_arbiter_spawn as _vas  # noqa: E402  (the Claude adapter reads nothing at import)

#: The R3 acceptance envelope (tests/fixtures/reviewer/claude-envelope-model-usage.json), captured
#: 2026-09-15T15:42:37Z on Claude Code 2.1.272 by the #282 WP-H1B stage, from the reviewer dir:
#:     cd /run/user/1000/foundry-reviewer-cwd && timeout 300 \
#:       claude -p --model sonnet --setting-sources user --output-format json "reply OK" < /dev/null
#: exit 0, result "OK", modelUsage {"claude-sonnet-5": {..., "outputTokens": 4, ...}}, the directory
#: still empty afterwards. Only session_id and uuid were replaced by fixed placeholders; every key,
#: the nesting and the modelUsage shape are verbatim. Note the shape: ONE result dict, not a stream
#: array.
_R3_FIXTURE = _HERE.parent / "fixtures" / "reviewer" / "claude-envelope-model-usage.json"

_R3_SETTINGS_POISON = {"model": "haiku", "env": {"X": "1"}}


def _r3_reviewer_dir(variant: Optional[str] = None) -> str:
    """The directory the autouse XDG_RUNTIME_DIR makes resolve_reviewer_cwd() return.

    `variant` (#282 fix round 2 G4 / plan K56) restates the naming rule independently of the
    implementation: a non-None variant appends `-<variant>` to REVIEWER_CWD_NAME, so the
    codex slot's Fable substitute resolves `foundry-reviewer-cwd-substitute`.
    """
    name = audit_spawn.REVIEWER_CWD_NAME if variant is None else f"{audit_spawn.REVIEWER_CWD_NAME}-{variant}"
    return os.path.realpath(os.path.join(os.environ["XDG_RUNTIME_DIR"], name))


def _mkdir_chain(path: Path, mode: int = 0o700) -> Path:
    """Create `path` and every missing parent AT `mode`, and return it.

    #282 fix round 1 F4 (plan K38): an ancestor that is group- or world-writable without
    the sticky bit is refused, and a plain mkdir under the common umask 002 yields 0o775.
    Path.mkdir(parents=True, mode=...) cannot be used — it creates the parents with the
    default permissions and applies `mode` only to the leaf. So every fixture chain that
    must be ACCEPTED is created explicitly; the fixtures that must be REFUSED are left
    exactly as they were, since they refuse on the rule under test before F4 is reached.
    """
    missing: List[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=mode)
    return path


def _r3_settings_poisoned_project(root: Path) -> Path:
    """A caller cwd whose project settings try to steer any claude started in it."""
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "settings.json").write_text(json.dumps(_R3_SETTINGS_POISON), encoding="utf-8")
    return root


def _r3_envelope(model_usage: Optional[Dict[str, Any]], verdict: Optional[dict] = None) -> str:
    result: Dict[str, Any] = {"type": "result", "subtype": "success",
                              "result": json.dumps(verdict or _audit_verdict()), "num_turns": 1}
    if model_usage is not None:
        result["modelUsage"] = {k: {"inputTokens": 1, "outputTokens": v} for k, v in model_usage.items()}
    return json.dumps(result)


def _r3_code_reviewer_effort() -> str:
    """The code_reviewer Claude seat's pinned effort, read from the one authority (seat_model)."""
    return audit_spawn.seat_model.ROLE_TABLE["code_reviewer"]["claude"].effort


def _r3_assert_reviewer_argv(cmd: List[str], model: str, effort: Optional[str] = None) -> None:
    """argv is exactly [bin, -p, --model M, --effort E, --setting-sources user, --output-format json];
    the prompt is NOT in argv (#291 fix round 1 B: it travels on stdin). #311 fix round 1 F1: the
    protected seat's pinned effort is passed explicitly, so the user's global effortLevel cannot
    lower the reviewer."""
    effort = effort or _r3_code_reviewer_effort()
    assert cmd[1:] == ["-p", "--model", model, "--effort", effort, "--setting-sources", "user",
                       "--output-format", "json"], cmd
    for forbidden in ("--bare", "--fallback-model"):
        assert not any(str(token).startswith(forbidden) for token in cmd), (forbidden, cmd)


def test_r3_claude_arm_and_substitute_argv_cwd_and_stdin(tmp_path: Path) -> None:
    """(a) + (b) in process: the Claude arm AND the substitute call (through _substitute_codex_arm)
    carry `--setting-sources user` and the pinned `--effort`, lack --bare / --fallback-model, run with cwd = the
    resolved reviewer dir (created 0700, holding no `.claude/`) and the prompt on a piped stdin
    (`input=`, #291 fix round 1 B) rather than stdin DEVNULL plus argv.

    RE-POINTED by #282 fix round 2 G4 (plan K56), which IS the finding: the two calls no longer
    share ONE directory — the substitute runs from its own `-substitute` variant. Nothing is
    deleted: every assertion below is kept and now runs against the directory each call
    actually used, and both are still asserted 0700 and free of a `.claude/`."""
    captured: List[Tuple[List[str], Dict[str, Any]]] = []

    def fake_run(cmd, **kwargs):
        captured.append((list(cmd), kwargs))
        return SimpleNamespace(stdout=_r3_envelope(None), returncode=0, stderr="")

    root = tmp_path / "proj"
    root.mkdir()
    sink: Dict[str, Any] = {}
    with _codex_spawn_patched(fake_run):
        verdict, err = audit_spawn.run_claude_auditor("the prompt", 60, project_root=root)
        assert err is None and verdict["verdict"] == "pass"
        verdict, err = audit_spawn._substitute_codex_arm("the prompt", "cli_missing", None, sink,
                                                         project_root=root, attempts=0)
        assert err is None and verdict["verdict"] == "pass", err
    assert len(captured) == 2
    expected_dirs = (_r3_reviewer_dir(), _r3_reviewer_dir("substitute"))
    assert expected_dirs[0] != expected_dirs[1]          # G4: the arm and the substitute differ
    for (cmd, kwargs), model, expected_dir in zip(
            captured, (audit_spawn.CLAUDE_MODEL, sink["substitution"]["served_model"]), expected_dirs):
        _r3_assert_reviewer_argv(cmd, model)
        assert "the prompt" not in cmd
        assert kwargs["cwd"] == expected_dir
        assert kwargs["input"] == "the prompt" and "stdin" not in kwargs
    for expected_dir in expected_dirs:
        assert stat.S_IMODE(os.lstat(expected_dir).st_mode) == 0o700
        assert not os.path.lexists(os.path.join(expected_dir, ".claude"))
        assert os.getcwd() != expected_dir


@_POSIX_ONLY
def test_r3_a_poisoned_caller_cwd_is_invisible_to_both_claude_reviewers(tmp_path: Path) -> None:
    """(b) + (c) through the REAL CLI: launched from a project whose `.claude/settings.json` sets a
    model and an env, codex 429s and the Fable substitute serves the slot. BOTH claude calls (arm and
    substitute) ran in the reviewer dir, saw no settings file and no `.claude/` there, and carried
    `--setting-sources user`. CONTROL: the same stub launched with the PRE-R3 argv from that project
    sees the settings file — so the invisibility is the fix, not a blind stub.

    RE-POINTED by #282 fix round 2 G4 (plan K56), which IS the finding: call 0 (the arm) and
    call 1 (the substitute) now run in DIFFERENT reviewer directories. Nothing is deleted —
    every call is still asserted to have run in a reviewer directory with no settings file and
    no `.claude/`, now named per call."""
    project = _r3_settings_poisoned_project(tmp_path / "settings-poisoned")
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["429"], claude_plan=[_PASS, _SUB_PASS], wait=True,
                                caller_cwd=project,
        codex_on_path=True)
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", (run["out"], run["stderr"])
    assert run["out"]["model_provenance"]["codex"]["codex_arm_substituted_by"] == MAIN
    assert [c["index"] for c in run["claude"]] == [0, 1]
    # G4 (plan K56): index 0 is the arm, index 1 the substitute, each in its OWN directory.
    for call, expected_dir in zip(run["claude"], (_r3_reviewer_dir(), _r3_reviewer_dir("substitute"))):
        assert call["cwd"] == expected_dir, call
        assert call["settings_visible"] is False and call["dot_claude"] is False
        _r3_assert_reviewer_argv([call["bin"]] + call["argv"], MAIN)
        assert call["stdin_eof"] is True

    log = tmp_path / "pre-r3-control.jsonl"
    stub = _write_stub(tmp_path / "control-bin" / "claude-stub", _SUBSTITUTION_STUB)
    env = dict(os.environ, **_stub_env(log, ["ok"], [_PASS], wait=False))
    subprocess.run([str(stub), "-p", "--model", "fable", "--output-format", "json", "the prompt"],
                   cwd=str(project), env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=True)
    (control,) = _read_jsonl(log)
    assert os.path.realpath(control["cwd"]) == os.path.realpath(str(project))
    assert control["settings_visible"] is True and control["dot_claude"] is True


@_POSIX_ONLY
def test_r3_a_relative_claude_bin_is_resolved_against_the_callers_cwd(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """A relative AUDIT_CLAUDE_BIN names a file relative to the CALLER's cwd (where _bin_override
    recorded its realpath); launching from the reviewer dir must still run that file. CONTROL: a bare
    name is left for the PATH lookup."""
    caller = tmp_path / "caller"
    _write_stub(caller / "bin" / "claude-stub", _SUBSTITUTION_STUB)
    log = tmp_path / "relative.jsonl"
    for key, value in _stub_env(log, ["ok"], [_PASS], wait=False).items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(caller)
    monkeypatch.setattr(audit_spawn, "CLAUDE_BIN", os.path.join("bin", "claude-stub"))
    assert audit_spawn._claude_launch_bin() == str(caller / "bin" / "claude-stub")
    verdict, err = audit_spawn.run_claude_auditor("the prompt", 60)
    assert err is None and verdict["verdict"] == "pass"
    (call,) = _read_jsonl(log)
    assert call["cwd"] == _r3_reviewer_dir()
    monkeypatch.setattr(audit_spawn, "CLAUDE_BIN", "claude")
    assert audit_spawn._claude_launch_bin() == "claude"


def test_r3_reviewer_cwd_is_created_0700_and_a_clean_dir_is_accepted(tmp_path: Path) -> None:
    """(e) CONTROL: a clean runtime dir -> the directory is created 0700, returned as its realpath,
    and accepted again on the next launch (re-checked, not cached). Other entries are tolerated."""
    expected = _r3_reviewer_dir()
    assert not os.path.lexists(expected)
    assert audit_spawn.resolve_reviewer_cwd(tmp_path / "proj") == expected
    assert os.path.isdir(expected) and not os.path.islink(expected)
    if hasattr(os, "getuid"):
        assert stat.S_IMODE(os.lstat(expected).st_mode) == 0o700
    Path(expected, "stray.txt").write_text("tolerated", encoding="utf-8")
    assert audit_spawn.resolve_reviewer_cwd(tmp_path / "proj") == expected


@pytest.mark.parametrize("marker", ["CLAUDE.md", "CLAUDE.local.md", ".mcp.json",
                                    os.path.join(".claude", "settings.json"),
                                    os.path.join(".claude", "settings.local.json")])
def test_r3_an_ancestor_holding_claude_configuration_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                marker: str) -> None:
    """(e) XDG_RUNTIME_DIR planted under a tree whose ancestor carries claude configuration -> refused,
    naming the marker. CONTROL: the sibling clean tree is accepted."""
    poisoned = tmp_path / "poisoned-tree"
    (poisoned / os.path.dirname(marker)).mkdir(parents=True, exist_ok=True)
    (poisoned / marker).write_text("{}", encoding="utf-8")
    runtime = poisoned / "deep" / "runtime"
    runtime.mkdir(parents=True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd()
    assert os.path.basename(marker) in str(exc.value) and "ancestor" in str(exc.value)

    clean = _mkdir_chain(tmp_path / "clean-tree" / "deep" / "runtime")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(clean))
    assert audit_spawn.resolve_reviewer_cwd() == os.path.realpath(str(clean / audit_spawn.REVIEWER_CWD_NAME))


@pytest.mark.parametrize("entry", [".claude", "CLAUDE.md", "CLAUDE.local.md", ".mcp.json"])
def test_r3_a_reviewer_dir_holding_claude_configuration_is_refused(tmp_path: Path, entry: str) -> None:
    """(e) the directory itself must hold none of the configuration entries."""
    target = Path(_r3_reviewer_dir())
    target.mkdir(mode=0o700)
    if entry == ".claude":
        (target / entry).mkdir()
    else:
        (target / entry).write_text("{}", encoding="utf-8")
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd()
    assert entry in str(exc.value)


def test_r3_a_symlinked_or_non_directory_reviewer_dir_is_refused(tmp_path: Path) -> None:
    """(e) lstat, not stat: a symlink to a perfectly clean directory is refused; so is a file."""
    target = Path(_r3_reviewer_dir())
    elsewhere = tmp_path / "clean-elsewhere"
    elsewhere.mkdir(mode=0o700)
    try:
        target.symlink_to(elsewhere, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd()
    assert "symlink" in str(exc.value)
    target.unlink()
    target.write_text("not a dir", encoding="utf-8")
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd()
    assert "not a directory" in str(exc.value)


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX permission bits: no group/world-writable on Windows")
@pytest.mark.parametrize("mode", [0o770, 0o707, 0o777])
def test_r3_a_group_or_world_writable_reviewer_dir_is_refused(tmp_path: Path, mode: int) -> None:
    """(e) POSIX: any group- or world-write bit is refused. CONTROL: 0o700 and 0o755 are accepted."""
    target = Path(_r3_reviewer_dir())
    target.mkdir()
    os.chmod(target, mode)
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd()
    assert "writable" in str(exc.value)
    for ok in (0o700, 0o755):
        os.chmod(target, ok)
        assert audit_spawn.resolve_reviewer_cwd() == str(target)


def test_r3_a_reviewer_dir_inside_the_callers_cwd_project_root_or_claude_home_is_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolated_home: Path) -> None:
    """(e) never the caller's cwd, the --project-root or ~/.claude, nor inside one. CONTROL: the same
    directory is accepted from an unrelated cwd with an unrelated project root."""
    runtime = Path(os.environ["XDG_RUNTIME_DIR"])
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(runtime)
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd()
    assert "caller's cwd" in str(exc.value)
    monkeypatch.chdir(unrelated)
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd(project_root=runtime)
    assert "project root" in str(exc.value)
    claude_home_runtime = _isolated_home / ".claude" / "runtime"
    claude_home_runtime.mkdir(parents=True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(claude_home_runtime))
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd(project_root=unrelated)
    assert "~/.claude" in str(exc.value)

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    assert audit_spawn.resolve_reviewer_cwd(project_root=unrelated) == _r3_reviewer_dir()


def test_r3_candidate_falls_back_to_the_temp_dir_by_uid_or_user_name(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """K3 resolution order without a usable XDG_RUNTIME_DIR: a relative or missing value is ignored;
    with no /run/user/<uid> runtime dir the temp dir holds foundry-reviewer-cwd-<uid>; where os.getuid
    is absent (Windows) the sanitized user name is the suffix. CONTROL: an absolute existing
    XDG_RUNTIME_DIR wins."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    no_runtime_uid = 4000000123  # no /run/user/<this uid> on any host
    assert not os.path.exists(os.path.join(os.sep, "run", "user", str(no_runtime_uid)))
    for xdg in ("relative/runtime", str(tmp_path / "missing")):
        monkeypatch.setenv("XDG_RUNTIME_DIR", xdg)
        monkeypatch.setattr(audit_spawn.os, "getuid", lambda: no_runtime_uid, raising=False)
        assert audit_spawn._reviewer_cwd_candidate() == os.path.join(
            str(tmp_path), f"foundry-reviewer-cwd-{no_runtime_uid}")
    monkeypatch.delattr(audit_spawn.os, "getuid", raising=False)
    monkeypatch.setattr(audit_spawn.getpass, "getuser", lambda: "Dom\\ain user")
    assert audit_spawn._reviewer_cwd_candidate() == os.path.join(str(tmp_path), "foundry-reviewer-cwd-Dom_ain_user")

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    assert audit_spawn._reviewer_cwd_candidate() == os.path.join(str(runtime), "foundry-reviewer-cwd")


@_POSIX_ONLY
def test_r3_a_refused_reviewer_dir_fails_the_claude_arm_closed_through_the_cli(tmp_path: Path,
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """(e) end to end: XDG_RUNTIME_DIR planted under a tree whose ancestor holds `.claude/settings.json`
    -> exit 4 AUDIT_UNAVAILABLE, claude_error names the refusal, the claude stub was NEVER invoked (the
    caller's cwd is not a fallback). CONTROL: the same run with a clean runtime dir -> VERIFIED."""
    poisoned_runtime = _r3_settings_poisoned_project(tmp_path / "planted") / "run"
    poisoned_runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(poisoned_runtime))
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["ok"], claude_plan=[_PASS])
    assert run["code"] == 4, (run["out"], run["stderr"])
    _assert_top_level_keys(run)
    out = run["out"]
    assert out["result"] == "AUDIT_UNAVAILABLE" and out["claude_verdict"] is None
    assert out["claude_error"].startswith("reviewer cwd unavailable:") and "settings.json" in out["claude_error"]
    assert run["claude"] == []
    assert out["codex_verdict"] is not None and len(run["codex"]) == 1
    assert run["rows"]["audit_claude"]["status"].startswith("ERROR: reviewer cwd unavailable")

    clean = _mkdir_chain(tmp_path / "clean-runtime")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(clean))
    ctl_root = tmp_path / "control"
    control = _run_substitution_cli(ctl_root, _substitution_home(ctl_root), codex_plan=["ok"], claude_plan=[_PASS])
    assert control["code"] == 0 and control["out"]["result"] == "VERIFIED", (control["out"], control["stderr"])
    assert len(control["claude"]) == 1


def test_r3_both_launchers_resolve_the_same_reviewer_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PARITY (plan K2): for the same environment the duplicated resolvers return the same directory or
    the same refusal, and the two modules share the name and the check lists."""
    assert audit_spawn.REVIEWER_CWD_NAME == _vas.REVIEWER_CWD_NAME == "foundry-reviewer-cwd"
    assert audit_spawn._REVIEWER_CWD_FORBIDDEN_ENTRIES == _vas._REVIEWER_CWD_FORBIDDEN_ENTRIES
    assert audit_spawn._REVIEWER_CWD_ANCESTOR_MARKERS == _vas._REVIEWER_CWD_ANCESTOR_MARKERS

    def outcome(module):
        try:
            return ("ok", module.resolve_reviewer_cwd())
        except module.ReviewerCwdError as exc:
            return ("refused", str(exc))

    first = outcome(audit_spawn)
    assert first == ("ok", _r3_reviewer_dir()) and outcome(_vas) == first
    planted = _r3_settings_poisoned_project(tmp_path / "planted") / "run"
    planted.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(planted))
    refused = outcome(audit_spawn)
    assert refused[0] == "refused" and outcome(_vas) == refused
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", "relative")
    assert audit_spawn._reviewer_cwd_candidate() == _vas._reviewer_cwd_candidate()


# ---------------------------------------------------------------------------
# #282 fix round 1 F2 / F4 / F8 — the reviewer cwd resolver's remaining holes
# ---------------------------------------------------------------------------
#
# Plan K37 (HOME is exempt from the two `.claude/settings*.json` markers, and an ancestor
# strictly BELOW home holding a `.claude` entry is refused), K38 (every ancestor of the
# path AND of its realpath is owner/mode/symlink-checked, POSIX only) and K39 (a
# filesystem root is never a containment root). Each has the control the spec names.

_F4_FOREIGN_UID = 4000000321  # no host runs the test suite as this uid


def _fake_lstat_for(monkeypatch: pytest.MonkeyPatch, target: Path, uid: Optional[int] = None,
                    gid: Optional[int] = None) -> None:
    """Report `uid` / `gid` as the owner of exactly `target` (real mode and type kept).

    An ancestor owned by root, or a ROOT-owned symlink, cannot be created by a test that
    must not require root, so the one field the rule reads is faked and everything else
    stays the real lstat. #282 fix round 2 G2 (plan K54) added `gid`: a FOREIGN-group
    ancestor is equally uncreatable without root, and the private-group carve-out must be
    proven to refuse one.
    """
    real_lstat = os.lstat
    wanted = os.path.normcase(str(target))

    def fake_lstat(path, *args, **kwargs):
        st = real_lstat(path, *args, **kwargs)
        try:
            hit = os.path.normcase(os.fspath(path)) == wanted
        except TypeError:  # a file descriptor: never the path we are faking
            hit = False
        if not hit:
            return st
        return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink,
                               st.st_uid if uid is None else uid,
                               st.st_gid if gid is None else gid,
                               st.st_size, int(st.st_atime), int(st.st_mtime), int(st.st_ctime)))

    monkeypatch.setattr(os, "lstat", fake_lstat)


def test_f2_a_runtime_dir_under_home_is_accepted_despite_the_users_own_settings(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolated_home: Path) -> None:
    """F2 (H1H2 Fable M2, plan K37): the runtime/temp dir lands UNDER HOME on every Windows
    host and wherever XDG_RUNTIME_DIR=$HOME/run, so refusing on the user's OWN
    ~/.claude/settings.json failed every Claude reviewer arm closed. HOME itself is exempt
    from exactly the two settings markers — the user tier loads into the reviewer anyway
    (`--setting-sources user`) and is trusted. CONTROL: CLAUDE.md at HOME still refuses."""
    os.chmod(_isolated_home, 0o700)  # F4/K38: the fixture home must not trip the mode rule
    (_isolated_home / ".claude").mkdir()
    (_isolated_home / ".claude" / "settings.json").write_text(
        json.dumps(_R3_SETTINGS_POISON), encoding="utf-8")
    (_isolated_home / ".claude" / "settings.local.json").write_text("{}", encoding="utf-8")
    runtime = _mkdir_chain(_isolated_home / "run")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    expected = os.path.realpath(str(runtime / audit_spawn.REVIEWER_CWD_NAME))

    assert audit_spawn.resolve_reviewer_cwd(tmp_path / "proj") == expected

    for marker in ("CLAUDE.md", "CLAUDE.local.md", ".mcp.json"):
        (_isolated_home / marker).write_text("steer the reviewer", encoding="utf-8")
        with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
            audit_spawn.resolve_reviewer_cwd(tmp_path / "proj")
        assert marker in str(exc.value) and "ancestor" in str(exc.value)
        (_isolated_home / marker).unlink()
    assert audit_spawn.resolve_reviewer_cwd(tmp_path / "proj") == expected


def test_f2_an_ancestor_below_home_holding_a_dot_claude_entry_is_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolated_home: Path) -> None:
    """F2's forward-compatible half (H1H2 Fable m4, plan K37): a `.claude` entry at an
    ancestor STRICTLY below home is a project's configuration root. It is refused by the
    ENTRY rather than by enumerating claude's discovery files, which would go stale.
    `lexists`, so a plain file named `.claude` counts too. CONTROLS: the same ancestor
    without the entry is accepted; a settings marker at a non-home ancestor still refuses
    by the marker; the entry AT home is the exemption above, not a refusal."""
    os.chmod(_isolated_home, 0o700)  # F4/K38: the fixture home must not trip the mode rule
    workspace = _isolated_home / "workspace"
    runtime = _mkdir_chain(workspace / "deep" / "run")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    expected = os.path.realpath(str(runtime / audit_spawn.REVIEWER_CWD_NAME))
    assert audit_spawn.resolve_reviewer_cwd(tmp_path / "proj") == expected  # CONTROL

    (workspace / ".claude").mkdir()
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd(tmp_path / "proj")
    assert ".claude" in str(exc.value) and str(workspace) in str(exc.value)
    (workspace / ".claude").rmdir()
    assert audit_spawn.resolve_reviewer_cwd(tmp_path / "proj") == expected

    (workspace / ".claude").write_text("a file, not a directory", encoding="utf-8")
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd(tmp_path / "proj")
    assert ".claude" in str(exc.value)
    (workspace / ".claude").unlink()

    (workspace / ".claude").mkdir()
    (workspace / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd(tmp_path / "proj")
    assert "settings.json" in str(exc.value)


@pytest.mark.skipif(not hasattr(os, "getuid"),
                    reason="POSIX ancestor owner/mode rules: Windows reports uid 0 and 0o777 everywhere")
def test_f4_a_group_or_world_writable_ancestor_without_the_sticky_bit_is_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F4 (H1H2 astra A1, plan K38 (b)): only the reviewer dir itself was validated, so a
    0777 parent could be swapped under it between the check and the launch. CONTROL: 1777
    — the /tmp shape every host's temp dir has — is accepted, and so is 0700.

    RE-POINTED by #282 fix round 2 G2 (plan K54), and the re-pointing is the finding: the
    GROUP-writable modes 0o770 / 0o775 are no longer refused unconditionally — they are
    refused only when the group is not the current user's provably private one, which is
    what `_multi_member_group` forces here. World-write (0o777 / 0o707) stays an
    unconditional refusal, and no assertion is dropped: every mode that was asserted
    refused is still asserted refused, under the shared-group condition the rule exists
    for. The private-group ACCEPT half is proven in
    test_g2_a_private_group_group_writable_ancestor_is_accepted."""
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    expected = os.path.realpath(str(runtime / audit_spawn.REVIEWER_CWD_NAME))
    assert audit_spawn.resolve_reviewer_cwd() == expected

    _multi_member_group(monkeypatch)
    for mode in (0o777, 0o770, 0o707):
        os.chmod(runtime, mode)
        with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
            audit_spawn.resolve_reviewer_cwd()
        assert "sticky" in str(exc.value) and str(runtime) in str(exc.value)
    for ok in (0o1777, 0o755, 0o700):
        os.chmod(runtime, ok)
        assert audit_spawn.resolve_reviewer_cwd() == expected
    os.chmod(runtime, 0o700)


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX ancestor ownership rule")
def test_f4_an_ancestor_owned_by_another_user_is_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F4 (plan K38 (a)): OWNER in {root, this user}. A foreign-owned ancestor cannot be
    created without root, so the one field the rule reads is faked. CONTROL: uid 0 — the
    shape of /, /run and /usr on every host — is accepted."""
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    expected = os.path.realpath(str(runtime / audit_spawn.REVIEWER_CWD_NAME))

    _fake_lstat_for(monkeypatch, runtime, _F4_FOREIGN_UID)
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd()
    assert str(_F4_FOREIGN_UID) in str(exc.value) and str(runtime) in str(exc.value)

    _fake_lstat_for(monkeypatch, runtime, 0)
    assert audit_spawn.resolve_reviewer_cwd() == expected


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX ancestor symlink rule")
def test_f4_a_symlinked_ancestor_is_refused_unless_it_is_root_owned(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F4 (plan K38 (c)): a user-owned symlinked ancestor is refused — the realpath chain
    alone would never see it, so BOTH chains are walked. CONTROL (the narrowing K38
    records): a ROOT-owned symlink whose parent passes is ACCEPTED, because macOS's
    /var -> private/var and /tmp -> private/tmp would otherwise take every macOS reviewer
    arm down the way the settings marker took Windows down."""
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    link = tmp_path / "link-runtime"
    try:
        link.symlink_to(runtime, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(link))
    expected = os.path.realpath(str(link / audit_spawn.REVIEWER_CWD_NAME))

    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd()
    assert "symlink" in str(exc.value) and str(link) in str(exc.value)

    _fake_lstat_for(monkeypatch, link, 0)
    assert audit_spawn.resolve_reviewer_cwd() == expected


# ---------------------------------------------------------------------------
# #282 fix round 2 G1 / G2 — the two chains that still failed a reviewer closed
# ---------------------------------------------------------------------------
#
# Plan K53 / K54, both launchers (plan K2).
#
# G1 (MAJOR, found independently by BOTH re-review seats): `resolve_reviewer_cwd` compared
# each ancestor AS A STRING against `_home_dir_forms()`, but `tempfile.gettempdir()` keeps
# the Windows 8.3 SHORT form — `C:\Users\RUNNER~1\AppData\Local\Temp`, the standard
# GitHub-Actions shape and common for any user name over 8 characters. The short ancestor
# equals NEITHER form of HOME, so the F2 exemption missed while the marker `lexists`
# resolved straight through the alias and every reviewer arm failed closed on the user's
# OWN ~/.claude/settings.json — the exact defect F2 exists to close.
#
# NO WINDOWS HOST IS AVAILABLE HERE. The 8.3 chain is SIMULATED: two real directories play
# the two names of one directory, and `os.path.realpath` is monkeypatched to resolve the
# short one onto the long one, which is precisely what an 8.3 alias does. The LOGIC is
# verified; the TRIGGER (that Windows really returns the short form from `gettempdir`)
# stays INFERRED from the finding, not observed. The NEGATIVE CONTROL — the identical
# fixture with `realpath` left alone, which must still be REFUSED — is what makes the
# simulation load-bearing rather than a tautology.
#
# G2 (minor, and THIS host is one): F4 rule (b) refused ANY group-writable ancestor without
# the sticky bit, so a user-created `XDG_RUNTIME_DIR=$HOME/run` or `TMPDIR=$HOME/tmp` on a
# umask-002 host — 0775 with the user's own PRIVATE single-member group — was refused too.
# World-write stays an unconditional refusal; group-write is accepted ONLY for a provably
# private group, and every failure to prove it FAILS CLOSED.

try:  # POSIX only (P001): every G2 test below skips where os.getgid is absent.
    import grp as _grp
    import pwd as _pwd
except ImportError:  # pragma: no cover - Windows has neither module
    _grp = None  # type: ignore[assignment]
    _pwd = None  # type: ignore[assignment]


def _alias_realpath(monkeypatch: pytest.MonkeyPatch, short: Path, long: Path) -> None:
    """Resolve `short` (and everything under it) onto the matching path under `long`.

    That IS an 8.3 short name on Windows: a second NAME for one directory, which
    `os.path.realpath` resolves and a plain string comparison does not. Everything else
    keeps the real `os.path.realpath`.
    """
    real_realpath = os.path.realpath
    short_s, long_s = str(short), str(long)

    def fake_realpath(path, *args, **kwargs):
        try:
            text = os.fspath(path)
        except TypeError:  # a file descriptor: never the path we are aliasing
            return real_realpath(path, *args, **kwargs)
        if isinstance(text, str) and (text == short_s or text.startswith(short_s + os.sep)):
            return real_realpath(long_s + text[len(short_s):], *args, **kwargs)
        return real_realpath(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)


def _short_path_home_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tuple[Path, Path]:
    """A HOME reachable by two names: `runnerlong` and its 8.3 alias `RUNNER~1`.

    Both are real directories here (a POSIX host has no 8.3 aliases) and BOTH carry the
    user's own `.claude/settings.json`, because on Windows they are one directory and the
    marker `lexists` sees the file through either name. `_alias_realpath` supplies the only
    thing a mkdir cannot: the resolution of one name onto the other. Returns
    (long_home, short_home); XDG_RUNTIME_DIR is pointed at `<short_home>/run`, so the
    candidate derives from the SHORT chain exactly as it does from `gettempdir()`.
    """
    users = _mkdir_chain(tmp_path / "Users")
    long_home = _mkdir_chain(users / "runnerlong")
    short_home = _mkdir_chain(users / "RUNNER~1")
    for home in (long_home, short_home):
        _mkdir_chain(home / ".claude")
        (home / ".claude" / "settings.json").write_text(
            json.dumps(_R3_SETTINGS_POISON), encoding="utf-8")
        _mkdir_chain(home / "run")
    for var in _HOME_VARS:
        monkeypatch.setenv(var, str(long_home))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(short_home / "run"))
    return long_home, short_home


def _fake_group(monkeypatch: pytest.MonkeyPatch, members) -> None:
    """Report `members` as the member list of EVERY group (or raise when it is an exception).

    Both launchers `import grp`, so patching the one module object reaches both.
    """
    if _grp is None:  # pragma: no cover - the callers skip on Windows first
        pytest.skip("grp is POSIX-only")

    def fake_getgrgid(gid):
        # Only gr_mem is read by the code under test; the name and the shadow placeholder
        # are literals, matching the duplicated helper in test_verification_arbiter_spawn.py.
        if isinstance(members, BaseException):
            raise members
        return _grp.struct_group(("fake", "x", gid, list(members)))

    monkeypatch.setattr(_grp, "getgrgid", fake_getgrgid)


def _multi_member_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SHARED-group shape G2 must keep refusing: a second member in the group."""
    if _grp is None or not hasattr(os, "getgid"):  # pragma: no cover - Windows
        return
    _fake_group(monkeypatch, ["someone-else"])


_G2_FOREIGN_GID = 65533


@pytest.mark.skipif(not hasattr(os, "getuid"),
                    reason="POSIX ancestor owner/mode rules: the chain walk is gated on os.getuid")
def test_g1_a_short_path_alias_of_home_is_exempt_from_the_settings_markers(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolated_home: Path) -> None:
    """G1 (plan K53): `at_home` is an IDENTITY question, so it must see through the 8.3
    alias — evaluate it over the raw ancestor AND its realpath. CONTROL: with `realpath`
    left alone the short directory is simply a DIFFERENT directory that happens to hold a
    settings file, and both launchers must still refuse it."""
    long_home, short_home = _short_path_home_chain(tmp_path, monkeypatch)
    expected = str(long_home / "run" / audit_spawn.REVIEWER_CWD_NAME)

    for module in (audit_spawn, _vas):  # CONTROL: no alias, still refused
        with pytest.raises(module.ReviewerCwdError) as exc:
            module.resolve_reviewer_cwd()
        assert "settings.json" in str(exc.value) and str(short_home) in str(exc.value)

    _alias_realpath(monkeypatch, short_home, long_home)
    for module in (audit_spawn, _vas):
        assert module.resolve_reviewer_cwd() == expected

    # CONTROL: the exemption is scoped to the two settings markers, exactly as at HOME.
    (short_home / "CLAUDE.md").write_text("steer", encoding="utf-8")
    for module in (audit_spawn, _vas):
        with pytest.raises(module.ReviewerCwdError) as exc:
            module.resolve_reviewer_cwd()
        assert "CLAUDE.md" in str(exc.value)


@pytest.mark.skipif(not hasattr(os, "getuid"),
                    reason="POSIX ancestor owner/mode rules: the chain walk is gated on os.getuid")
def test_g1_a_below_home_claude_entry_is_refused_through_both_ancestor_forms(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolated_home: Path) -> None:
    """G1 (plan K53): resolving the alias must NOT blind the below-home `.claude` rule.
    A `.claude` at an ancestor strictly below home refuses whether the RAW ancestor is the
    one below home (i) or only its resolved form is (ii). CONTROL: with neither entry
    present the same chain resolves."""
    long_home, short_home = _short_path_home_chain(tmp_path, monkeypatch)
    _alias_realpath(monkeypatch, short_home, long_home)
    expected = str(long_home / "run" / audit_spawn.REVIEWER_CWD_NAME)
    for module in (audit_spawn, _vas):  # CONTROL
        assert module.resolve_reviewer_cwd() == expected

    (long_home / "run" / ".claude").mkdir()          # (i) raw ancestor below home
    for module in (audit_spawn, _vas):
        with pytest.raises(module.ReviewerCwdError) as exc:
            module.resolve_reviewer_cwd()
        assert ".claude" in str(exc.value) and "below home" in str(exc.value)
    (long_home / "run" / ".claude").rmdir()
    for module in (audit_spawn, _vas):
        assert module.resolve_reviewer_cwd() == expected

    (short_home / "run" / ".claude").mkdir()         # (ii) only the resolved form is
    for module in (audit_spawn, _vas):
        with pytest.raises(module.ReviewerCwdError) as exc:
            module.resolve_reviewer_cwd()
        assert ".claude" in str(exc.value) and "below home" in str(exc.value)


@pytest.mark.skipif(not (hasattr(os, "getuid") and hasattr(os, "getgid")),
                    reason="POSIX ownership: Windows has no uid/gid or permission bits")
def test_g2_a_private_group_group_writable_ancestor_is_accepted(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """G2 (plan K54): on a umask-002 host a user-created `$HOME/run` is 0775 with the
    user's own PRIVATE single-member group, and F4 rule (b) refused it — failing every
    reviewer arm closed for a directory only that user can write. Both the empty-member
    and the lists-only-the-owner shapes count as private (some distributions write the
    owner into its own group). CONTROL: 0777 world-write is still refused even when the
    group is private."""
    runtime = _mkdir_chain(tmp_path / "runtime")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    expected = os.path.realpath(str(runtime / audit_spawn.REVIEWER_CWD_NAME))
    me = _pwd.getpwuid(os.getuid()).pw_name if _pwd is not None else None

    for members in ([], [me] if me else []):
        _fake_group(monkeypatch, members)
        for mode in (0o775, 0o770):
            os.chmod(runtime, mode)
            for module in (audit_spawn, _vas):
                assert module.resolve_reviewer_cwd() == expected, (members, oct(mode))

    _fake_group(monkeypatch, [])
    os.chmod(runtime, 0o777)  # CONTROL: world-write is unconditional
    for module in (audit_spawn, _vas):
        with pytest.raises(module.ReviewerCwdError) as exc:
            module.resolve_reviewer_cwd()
        assert "sticky" in str(exc.value) and str(runtime) in str(exc.value)
    os.chmod(runtime, 0o700)


@pytest.mark.skipif(not (hasattr(os, "getuid") and hasattr(os, "getgid")),
                    reason="POSIX ownership: Windows has no uid/gid or permission bits")
@pytest.mark.parametrize("label", ["multi_member", "foreign_gid", "lookup_keyerror",
                                   "lookup_oserror", "grp_unavailable"])
def test_g2_a_group_writable_ancestor_is_refused_unless_the_group_is_provably_private(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label: str) -> None:
    """G2 (plan K54): the carve-out FAILS CLOSED. A shared group, a foreign gid, an
    unresolvable group and an absent `grp` module are each refused exactly as before the
    fix — an unverifiable group is not a proven private one. CONTROL: the accepted shape
    is proven in test_g2_a_private_group_group_writable_ancestor_is_accepted."""
    runtime = _mkdir_chain(tmp_path / "runtime")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    os.chmod(runtime, 0o775)

    if label == "multi_member":
        _fake_group(monkeypatch, ["someone-else"])
    elif label == "foreign_gid":
        _fake_group(monkeypatch, [])
        _fake_lstat_for(monkeypatch, runtime, gid=_G2_FOREIGN_GID)
    elif label == "lookup_keyerror":
        _fake_group(monkeypatch, KeyError("no such group"))
    elif label == "lookup_oserror":
        _fake_group(monkeypatch, OSError("nss is down"))
    else:
        for module in (audit_spawn, _vas):
            monkeypatch.setattr(module, "grp", None, raising=False)

    for module in (audit_spawn, _vas):
        with pytest.raises(module.ReviewerCwdError) as exc:
            module.resolve_reviewer_cwd()
        assert "sticky" in str(exc.value) and str(runtime) in str(exc.value)
    os.chmod(runtime, 0o700)


@pytest.mark.skipif(not (hasattr(os, "getuid") and hasattr(os, "getgid")),
                    reason="POSIX ownership: Windows has no uid/gid or permission bits")
def test_g2_the_sticky_bit_and_the_reviewer_dirs_own_mode_rule_are_unchanged(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """G2 (plan K54) scope guard: the split touches ANCESTOR rule (b) only. The sticky-bit
    escape (/tmp's 1777) still accepts a shared-group ancestor, and the reviewer directory
    ITSELF is still refused on any group- or world-write bit, private group or not."""
    runtime = _mkdir_chain(tmp_path / "runtime")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    expected = os.path.realpath(str(runtime / audit_spawn.REVIEWER_CWD_NAME))

    _multi_member_group(monkeypatch)
    os.chmod(runtime, 0o1775)  # sticky wins over the shared group, as /tmp does
    for module in (audit_spawn, _vas):
        assert module.resolve_reviewer_cwd() == expected
    os.chmod(runtime, 0o700)

    _fake_group(monkeypatch, [])  # the most permissive private-group answer possible
    target = Path(expected)
    for mode in (0o770, 0o775, 0o707):
        os.chmod(target, mode)
        for module in (audit_spawn, _vas):
            with pytest.raises(module.ReviewerCwdError) as exc:
                module.resolve_reviewer_cwd()
            assert "group/world-writable" in str(exc.value)
    os.chmod(target, 0o700)


def test_f8_a_filesystem_root_is_never_a_containment_root(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F8 (H1H2 Fable m2, plan K39): commonpath(["/x", "/"]) == "/", so a caller whose cwd
    (or --project-root) is "/" marked EVERY candidate "inside the caller's cwd" and failed
    every launch closed. All three containment checks ignore a filesystem root. CONTROL:
    the candidate's real parent still refuses, in both launchers."""
    runtime = Path(os.environ["XDG_RUNTIME_DIR"])
    expected = _r3_reviewer_dir()
    for module in (audit_spawn, _vas):
        assert module._same_or_under(expected, os.sep) is False
        assert module._same_or_under(expected, str(runtime)) is True

    monkeypatch.chdir(os.sep)
    assert audit_spawn.resolve_reviewer_cwd() == expected
    assert audit_spawn.resolve_reviewer_cwd(project_root=Path(os.sep)) == expected
    assert _vas.resolve_reviewer_cwd() == expected

    monkeypatch.chdir(runtime)
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd()
    assert "caller's cwd" in str(exc.value)


def test_r3_both_launchers_agree_on_every_f2_f4_f8_fixture(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolated_home: Path) -> None:
    """PARITY (plan K2) extended for this round: on each F2 / F4 / F8 fixture the two
    duplicated resolvers return the SAME directory or the SAME refusal message, and they
    share the new marker-exemption and below-home entry lists."""
    assert audit_spawn._REVIEWER_CWD_HOME_EXEMPT_MARKERS == _vas._REVIEWER_CWD_HOME_EXEMPT_MARKERS
    assert audit_spawn._REVIEWER_CWD_BELOW_HOME_ENTRY == _vas._REVIEWER_CWD_BELOW_HOME_ENTRY
    assert set(audit_spawn._REVIEWER_CWD_HOME_EXEMPT_MARKERS) <= set(
        audit_spawn._REVIEWER_CWD_ANCESTOR_MARKERS)

    def outcome(module):
        try:
            return ("ok", module.resolve_reviewer_cwd())
        except module.ReviewerCwdError as exc:
            return ("refused", str(exc).replace(module.__name__, ""))

    def agree(label: str, expect: str) -> None:
        first = outcome(audit_spawn)
        assert first[0] == expect, (label, first)
        assert outcome(_vas) == first, label

    # F2: a runtime dir under a HOME that holds the user's own settings.
    os.chmod(_isolated_home, 0o700)
    (_isolated_home / ".claude").mkdir()
    (_isolated_home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    runtime = _mkdir_chain(_isolated_home / "run")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    agree("F2 home exemption", "ok")

    # F2 (m4): a `.claude` entry at an ancestor strictly below home.
    (runtime / ".claude").mkdir()
    deeper = _mkdir_chain(runtime / "deep")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(deeper))
    agree("F2 below-home .claude", "refused")

    # F4: a 0777 non-sticky ancestor.
    if hasattr(os, "getuid"):
        plain = _mkdir_chain(tmp_path / "plain")
        inner = _mkdir_chain(plain / "runtime")
        os.chmod(plain, 0o777)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(inner))
        agree("F4 0777 ancestor", "refused")
        os.chmod(plain, 0o1777)
        agree("F4 1777 ancestor", "ok")
        os.chmod(plain, 0o700)

    # G1 (plan K53): the simulated Windows 8.3 alias of HOME. The two launchers must agree
    # on the EXEMPTION, on the negative control (no alias -> refused) and on the below-home
    # `.claude` rule reached only through the resolved form.
    long_home, short_home = _short_path_home_chain(tmp_path, monkeypatch)
    agree("G1 alias, no realpath mapping", "refused")
    _alias_realpath(monkeypatch, short_home, long_home)
    agree("G1 alias of home exempt", "ok")
    (short_home / "run" / ".claude").mkdir()
    agree("G1 below-home .claude via the resolved form", "refused")
    (short_home / "run" / ".claude").rmdir()

    # G2 (plan K54): the private-group carve-out and its shared-group control.
    if hasattr(os, "getuid") and hasattr(os, "getgid") and _grp is not None:
        g2 = _mkdir_chain(tmp_path / "g2-runtime")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(g2))
        _fake_group(monkeypatch, [])
        os.chmod(g2, 0o775)
        agree("G2 private-group 0775 ancestor", "ok")
        _fake_group(monkeypatch, ["someone-else"])
        agree("G2 shared-group 0775 ancestor", "refused")
        _fake_group(monkeypatch, [])
        os.chmod(g2, 0o777)
        agree("G2 world-writable ancestor", "refused")
        os.chmod(g2, 0o700)

    # F8: the filesystem root as the caller's cwd, from a runtime dir of its own (the G1
    # fixture left XDG_RUNTIME_DIR inside the aliased HOME chain).
    runtime_f8 = _mkdir_chain(tmp_path / "f8-runtime")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_f8))
    monkeypatch.chdir(os.sep)
    agree("F8 root cwd", "ok")

    # F3 (plan K40): the duplicated auto-memory helpers name the SAME directory.
    assert (audit_spawn._reviewer_memory_dir(_r3_reviewer_dir())
            == _vas._reviewer_memory_dir(_r3_reviewer_dir()))

    # G3 (plan K55): and they agree under a RELOCATED CLAUDE_CONFIG_DIR too — the case the
    # pre-fix helpers could not see at all.
    config = _mkdir_chain(tmp_path / "parity-config")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    assert (audit_spawn._reviewer_memory_dir(_r3_reviewer_dir())
            == _vas._reviewer_memory_dir(_r3_reviewer_dir())
            == str(_memory_under(config, _r3_reviewer_dir())))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")

    # G4 (plan K56): identical variant signature, identical answer, and the arbiter — which
    # has no substitute — still resolves the un-varied directory.
    for variant in (None, "substitute"):
        assert (audit_spawn.resolve_reviewer_cwd(variant=variant)
                == _vas.resolve_reviewer_cwd(variant=variant)), variant
    assert _vas.resolve_reviewer_cwd() == audit_spawn.resolve_reviewer_cwd()


# ---------------------------------------------------------------------------
# #282 fix round 1 F3 — the shared reviewer auto-memory directory
# ---------------------------------------------------------------------------
#
# Plan K40. Every reviewer / arbiter / substitute call shares ONE reviewer cwd, so they
# share ONE `~/.claude/projects/<slug>/memory/`: one reviewer's memories reach the next
# reviewer's context. `--bare` would disable it but breaks the Max OAuth path, so the
# directory is EMPTIED before every launch — moved, never deleted, and recorded.
#
# FIXTURE HOMES ONLY. Every test here resolves its reviewer cwd from the autouse
# XDG_RUNTIME_DIR (a tmp dir) and its home from the autouse HOME (a tmp dir), so the slug
# is a tmp-path slug and the host's real
# ~/.claude/projects/-run-user-1000-foundry-reviewer-cwd/ is never named, read or written.


def _f3_memory_dir(variant: Optional[str] = None) -> Path:
    """K40's rule restated independently of the implementation, for the fixture HOME.

    `~/.claude/projects/<every non-alphanumeric of the abspath -> '-'>/memory`.

    `variant` (#282 fix round 2 G4 / plan K56) names the reviewer directory the way
    _reviewer_cwd_candidate does — `foundry-reviewer-cwd-substitute` — so a test can name the
    SUBSTITUTE's own memory directory without reaching into the implementation.
    """
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(_r3_reviewer_dir(variant)))
    return Path.home() / ".claude" / "projects" / slug / "memory"


def _f3_launch(sink: Optional[Dict[str, Any]] = None,
               observe: Optional[Any] = None) -> Tuple[Any, Any, List[Dict[str, Any]]]:
    """Run one Claude arm against a stubbed subprocess; return (verdict, err, calls).

    `observe(kwargs)` runs INSIDE the fake subprocess call, so a test can prove what the
    launch saw at the moment it happened rather than after the fact.
    """
    calls: List[Dict[str, Any]] = []

    def fake_run(cmd, **kwargs):
        seen: Dict[str, Any] = {"cwd": kwargs["cwd"]}
        if observe is not None:
            seen["observed"] = observe(kwargs)
        calls.append(seen)
        return SimpleNamespace(stdout=_r3_envelope(None), returncode=0, stderr="")

    with _codex_spawn_patched(fake_run):
        verdict, err = audit_spawn.run_claude_auditor("the prompt", 60, sink)
    return verdict, err, calls


def test_f3_a_seeded_reviewer_memory_dir_is_quarantined_before_the_launch(
        capsys: pytest.CaptureFixture[str], _isolated_home: Path) -> None:
    """F3 (H1H2 Fable M3, plan K40): a file AND a subdirectory left by an earlier reviewer
    are MOVED into memory.quarantine/<UTC stamp>/ before the next launch; the count rides
    the provenance side-channel and one ASCII stderr line; the launch then PROCEEDS and
    sees an empty memory dir; nothing is deleted and `memory/` itself is kept."""
    memory = _f3_memory_dir()
    _mkdir_chain(memory)
    (memory / "MEMORY.md").write_text("a previous reviewer's notes", encoding="utf-8")
    (memory / "sub").mkdir(mode=0o700)
    (memory / "sub" / "note.md").write_text("nested", encoding="utf-8")

    sink: Dict[str, Any] = {}
    verdict, err, calls = _f3_launch(sink, observe=lambda _kw: sorted(os.listdir(memory)))
    assert err is None and verdict["verdict"] == "pass"
    # The quarantine happened BEFORE the launch, and the launch still ran.
    assert calls == [{"cwd": _r3_reviewer_dir(), "observed": []}]
    assert sink["reviewer_memory_quarantined"] == 2

    quarantine = memory.parent / "memory.quarantine"
    stamps = sorted(quarantine.iterdir())
    assert len(stamps) == 1, stamps
    assert re.fullmatch(r"\d{8}T\d{6}\d{6}Z", stamps[0].name), stamps[0].name
    assert sorted(p.name for p in stamps[0].iterdir()) == ["MEMORY.md", "sub"]
    # NOTHING is deleted: both entries are readable under the quarantine path.
    assert (stamps[0] / "MEMORY.md").read_text(encoding="utf-8") == "a previous reviewer's notes"
    assert (stamps[0] / "sub" / "note.md").read_text(encoding="utf-8") == "nested"
    # The memory directory itself is KEPT, left empty.
    assert memory.is_dir() and not sorted(memory.iterdir())

    err_text = capsys.readouterr().err
    assert "2" in err_text and "quarantin" in err_text.lower(), err_text
    assert err_text.isascii(), err_text


def test_f3_an_empty_or_absent_memory_dir_moves_nothing_and_records_no_key(
        capsys: pytest.CaptureFixture[str], _isolated_home: Path) -> None:
    """CONTROL (the spec names it): with nothing to quarantine there is no move, no event
    key and no quarantine directory — so an absent key always means "nothing was moved",
    never "not checked". Both shapes: the directory absent, and present but empty."""
    memory = _f3_memory_dir()
    quarantine = memory.parent / "memory.quarantine"

    assert not memory.exists()
    sink: Dict[str, Any] = {}
    _verdict, err, calls = _f3_launch(sink)
    assert err is None and calls == [{"cwd": _r3_reviewer_dir()}]
    assert "reviewer_memory_quarantined" not in sink
    assert not quarantine.exists()
    assert "quarantin" not in capsys.readouterr().err.lower()

    _mkdir_chain(memory)
    sink = {}
    _verdict, err, calls = _f3_launch(sink)
    assert err is None and calls == [{"cwd": _r3_reviewer_dir()}]
    assert "reviewer_memory_quarantined" not in sink
    assert not quarantine.exists()
    assert memory.is_dir() and not sorted(memory.iterdir())
    assert "quarantin" not in capsys.readouterr().err.lower()


def test_f3_a_move_failure_fails_the_arm_closed_and_never_launches(
        _isolated_home: Path) -> None:
    """FAIL CLOSED (plan K40): an OSError while quarantining takes the existing
    `reviewer cwd unavailable: <reason>` path — AUDIT_UNAVAILABLE for this arm — because a
    reviewer that loads unquarantined memory is exactly what F3 forbids. No launch, no
    event key, and the entry that could not be moved is still there (nothing is deleted)."""
    memory = _f3_memory_dir()
    _mkdir_chain(memory)
    (memory / "MEMORY.md").write_text("notes", encoding="utf-8")

    def boom(_src, _dst):
        raise OSError(13, "Permission denied")

    sink: Dict[str, Any] = {}
    with mock.patch.object(os, "replace", side_effect=boom):
        verdict, err, calls = _f3_launch(sink)
    assert verdict is None
    assert err.startswith("reviewer cwd unavailable: "), err
    assert "MEMORY.md" in err and "PermissionError" in err, err
    assert calls == []  # the stub NEVER ran
    assert "reviewer_memory_quarantined" not in sink
    assert (memory / "MEMORY.md").read_text(encoding="utf-8") == "notes"


def test_f3_a_memory_path_that_is_not_a_real_directory_fails_closed(
        _isolated_home: Path) -> None:
    """FAIL CLOSED (plan K40): a `memory` that exists and is not a real directory cannot be
    emptied, so the arm refuses rather than launching over it. A SYMLINK counts even when
    it points at a real directory (listdir would follow it and the moves would escape the
    project). CONTROL: a plain file named `memory` is refused the same way."""
    memory = _f3_memory_dir()
    _mkdir_chain(memory.parent)
    target = memory.parent / "elsewhere"
    target.mkdir(mode=0o700)
    (target / "MEMORY.md").write_text("not ours to move", encoding="utf-8")
    try:
        memory.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    verdict, err, calls = _f3_launch()
    assert verdict is None and calls == []
    assert err.startswith("reviewer cwd unavailable: "), err
    assert "not a real directory" in err, err
    assert (target / "MEMORY.md").exists()  # untouched

    memory.unlink()
    memory.write_text("not a directory", encoding="utf-8")
    verdict, err, calls = _f3_launch()
    assert verdict is None and calls == []
    assert "not a real directory" in err, err


def test_f3_an_ancestor_that_is_not_a_directory_means_nothing_to_quarantine(
        _isolated_home: Path) -> None:
    """CONTROL for the fail-closed rule, and the shape `~/.claude/projects` itself takes in
    test_r10_*: when a PARENT component is not a directory the memory dir CANNOT exist, so
    there is definitively nothing to quarantine and the launch proceeds. That is the same
    answer as "absent", not an unknown — only `memory` ITSELF not being a real directory
    (where lstat succeeds) fails the arm closed."""
    projects = Path.home() / ".claude" / "projects"
    projects.parent.mkdir(parents=True, exist_ok=True)
    projects.write_text("not a directory", encoding="utf-8")

    sink: Dict[str, Any] = {}
    verdict, err, calls = _f3_launch(sink)
    assert err is None and verdict["verdict"] == "pass"
    assert calls == [{"cwd": _r3_reviewer_dir()}]
    assert "reviewer_memory_quarantined" not in sink
    assert projects.read_text(encoding="utf-8") == "not a directory"  # untouched


def test_f3_two_launches_under_one_stamp_get_distinct_quarantine_directories(
        monkeypatch: pytest.MonkeyPatch, _isolated_home: Path) -> None:
    """A second launch inside the same timestamp gets its OWN directory via the collision
    suffix, so one launch's memories can never land on another's. The real stamp carries
    microseconds; it is pinned here so the suffix path is the one under test."""
    memory = _f3_memory_dir()
    _mkdir_chain(memory)
    monkeypatch.setattr(audit_spawn, "_quarantine_stamp", lambda: "20260915T235959000000Z")

    for note in ("first", "second"):
        (memory / "MEMORY.md").write_text(note, encoding="utf-8")
        sink: Dict[str, Any] = {}
        _verdict, err, calls = _f3_launch(sink)
        assert err is None and len(calls) == 1
        assert sink["reviewer_memory_quarantined"] == 1

    stamps = sorted(p.name for p in (memory.parent / "memory.quarantine").iterdir())
    assert stamps == ["20260915T235959000000Z", "20260915T235959000000Z-1"], stamps
    kept = {p.name: (p / "MEMORY.md").read_text(encoding="utf-8")
            for p in (memory.parent / "memory.quarantine").iterdir()}
    assert sorted(kept.values()) == ["first", "second"], kept


def test_f3_the_count_reaches_the_provenance_block_of_the_arm_that_launched() -> None:
    """RECORD (plan K40): `reviewer_memory_quarantined` is an EVENT KEY in the block of the
    arm that launched — `claude` for the Claude arm, `codex` for the slot's Fable
    substitute (its own launch, its own quarantine). CONTROL: nothing moved -> no key in
    either block, so the key never has to be read as a zero."""
    prov = audit_spawn._build_model_provenance(600, 600, {}, {"reviewer_memory_quarantined": 3})
    assert prov["claude"]["reviewer_memory_quarantined"] == 3
    assert "reviewer_memory_quarantined" not in prov["codex"]

    substituted = {"substitution": {"reason": "malformed_twice", "codex_attempts": 2,
                                    "served_model": "fable", "timeout_s": 600,
                                    "usage": {"reviewer_memory_quarantined": 1}}}
    prov = audit_spawn._build_model_provenance(600, 600, substituted, {})
    assert prov["codex"]["reviewer_memory_quarantined"] == 1
    assert prov["codex"]["codex_arm_substituted_by"] == "fable"
    assert "reviewer_memory_quarantined" not in prov["claude"]

    prov = audit_spawn._build_model_provenance(600, 600, {}, {})
    assert "reviewer_memory_quarantined" not in prov["claude"]
    assert "reviewer_memory_quarantined" not in prov["codex"]


def test_f3_the_fable_substitute_quarantines_before_its_own_launch(
        tmp_path: Path, _isolated_home: Path) -> None:
    """K40 names THREE launchers: the Claude arm, the arbiter and the codex slot's Fable
    substitute. The substitute is its own `claude -p` subprocess (it shares no context with
    the arm), so it performs its OWN quarantine — and the count lands in the codex block,
    because the codex slot is the arm that launched it.

    RE-POINTED by #282 fix round 2 G4 (plan K56), which IS the finding: the substitute no
    longer shares the arm's reviewer cwd, so the directory it quarantines is its own
    `_f3_memory_dir("substitute")`. Nothing is deleted — every assertion below is kept, on the
    directory the substitute actually uses, and that the arm's directory stays untouched is
    asserted in test_g4_a_seeded_entry_in_one_memory_dir_is_untouched_by_the_other_arm."""
    memory = _f3_memory_dir("substitute")
    _mkdir_chain(memory)
    (memory / "MEMORY.md").write_text("an earlier reviewer's notes", encoding="utf-8")

    seen: List[List[str]] = []

    def fake_run(_cmd, **_kwargs):
        seen.append(sorted(os.listdir(memory)))
        return SimpleNamespace(stdout=_r3_envelope(None), returncode=0, stderr="")

    root = _mkdir_chain(tmp_path / "proj")
    codex_usage: Dict[str, Any] = {}
    with _codex_spawn_patched(fake_run):
        verdict, err = audit_spawn._substitute_codex_arm(
            "the prompt", "cli_missing", None, codex_usage, project_root=root, attempts=0)
    assert err is None and verdict["verdict"] == "pass", err
    assert seen == [[]]  # the substitute's own launch saw an emptied memory dir
    assert codex_usage["substitution"]["usage"]["reviewer_memory_quarantined"] == 1

    prov = audit_spawn._build_model_provenance(600, 600, codex_usage, {})
    assert prov["codex"]["reviewer_memory_quarantined"] == 1
    assert "reviewer_memory_quarantined" not in prov["claude"]

    stamps = sorted((memory.parent / "memory.quarantine").iterdir())
    assert len(stamps) == 1, stamps
    assert (stamps[0] / "MEMORY.md").read_text(encoding="utf-8") == "an earlier reviewer's notes"


def test_f3_both_launchers_quarantine_the_same_directory_the_same_way(
        tmp_path: Path, _isolated_home: Path) -> None:
    """PARITY (plan K2 / K40) for the F3 helpers: the two duplicated copies name the same
    auto-memory directory for any reviewer cwd, agree with K40's slug rule, and quarantine
    an identical fixture identically (count, destination shape, nothing deleted)."""
    for cwd in (_r3_reviewer_dir(), str(tmp_path / "some other dir"), os.path.join(os.sep, "x")):
        expected = os.path.join(
            str(Path.home()), ".claude", "projects",
            re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(cwd)), "memory")
        assert audit_spawn._reviewer_memory_dir(cwd) == expected
        assert _vas._reviewer_memory_dir(cwd) == expected

    results = []
    for module in (audit_spawn, _vas):
        memory = _mkdir_chain(tmp_path / module.__name__ / "memory")
        (memory / "MEMORY.md").write_text("shared", encoding="utf-8")
        moved = module._quarantine_reviewer_memory(str(memory))
        stamps = sorted((memory.parent / "memory.quarantine").iterdir())
        results.append((moved, len(stamps), sorted(p.name for p in stamps[0].iterdir()),
                        memory.is_dir(), sorted(memory.iterdir())))
    assert results[0] == results[1] == (1, 1, ["MEMORY.md"], True, [])


# ---------------------------------------------------------------------------
# #282 fix round 2 G3 / G4 — the quarantine follows CLAUDE_CONFIG_DIR, and the
# substitute gets a reviewer cwd of its own
# ---------------------------------------------------------------------------
#
# G3 (plan K55). `_reviewer_memory_dir` built its path from `Path.home()` ALONE, so under a
# relocated CLAUDE_CONFIG_DIR the directory it named did not exist: _quarantine_reviewer_memory
# returned 0 and the launch PROCEEDED over the memory claude would really read. A count of 0 is
# supposed to mean "nothing was moved", never "not checked" — this was the second reading.
#
# G4 (plan K56). The Claude arm and the codex slot's Fable substitute run in ONE
# ThreadPoolExecutor and shared `foundry-reviewer-cwd`, so they shared ONE memory directory:
# the arm could re-create `memory/` after the substitute had emptied it, and the two arms of a
# conjunction stopped being independent. The substitute now runs from its own variant
# directory, which gives it its own slug and therefore its own memory dir with no second code
# path — and every safety check applies to it unchanged.
#
# FIXTURE HOMES ONLY, exactly as the F3 block above. Every CLAUDE_CONFIG_DIR here points into
# tmp_path and every reviewer directory is resolved from the autouse XDG_RUNTIME_DIR, so the
# host's real ~/.claude/projects/-run-user-1000-foundry-reviewer-cwd/ AND the new
# substitute-slug directory are never named, read, moved or written.


def _memory_under(root: Path, reviewer_cwd: str) -> Path:
    """K55's rule restated independently of the implementation.

    CLAUDE_CONFIG_DIR names the `.claude` directory ITSELF, so the path is
    `<root>/projects/<slug>/memory` — never `<root>/.claude/projects/...`.
    """
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(reviewer_cwd))
    return root / "projects" / slug / "memory"


def test_g3_a_relocated_claude_config_dir_is_the_quarantine_root(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolated_home: Path) -> None:
    """G3 (plan K55): with CLAUDE_CONFIG_DIR set, THAT root's `projects/<slug>/memory` is the
    directory quarantined before the launch — the one claude will really read. The pre-fix
    code looked under ~/.claude, found nothing, returned 0 and launched over unquarantined
    memory. Both duplicated helpers name the relocated directory, and the ~/.claude path is
    left ALONE: the fix moves WHERE the check looks, it does not widen it to two places."""
    config = _mkdir_chain(tmp_path / "relocated-claude")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    reviewer = _r3_reviewer_dir()
    relocated = _memory_under(config, reviewer)
    for module in (audit_spawn, _vas):
        assert module._reviewer_memory_dir(reviewer) == str(relocated), module.__name__

    _mkdir_chain(relocated)
    (relocated / "MEMORY.md").write_text("a previous reviewer's notes", encoding="utf-8")
    home_path = _f3_memory_dir()
    _mkdir_chain(home_path)
    (home_path / "MEMORY.md").write_text("not the reviewer's memory", encoding="utf-8")

    sink: Dict[str, Any] = {}
    verdict, err, calls = _f3_launch(sink, observe=lambda _kw: sorted(os.listdir(relocated)))
    assert err is None and verdict["verdict"] == "pass"
    assert calls == [{"cwd": reviewer, "observed": []}]   # quarantined BEFORE the launch
    assert sink["reviewer_memory_quarantined"] == 1

    stamps = sorted((relocated.parent / "memory.quarantine").iterdir())
    assert len(stamps) == 1, stamps
    assert sorted(p.name for p in stamps[0].iterdir()) == ["MEMORY.md"]
    assert (stamps[0] / "MEMORY.md").read_text(encoding="utf-8") == "a previous reviewer's notes"
    assert (home_path / "MEMORY.md").read_text(encoding="utf-8") == "not the reviewer's memory"
    assert not (home_path.parent / "memory.quarantine").exists()


def test_g3_control_an_unset_or_empty_claude_config_dir_still_uses_the_home_path(
        monkeypatch: pytest.MonkeyPatch, _isolated_home: Path) -> None:
    """CONTROL for G3 (plan K55): UNSET keeps today's `~/.claude/projects/<slug>/memory`, and
    an EMPTY value is treated as unset rather than as the filesystem root. Without this the
    G3 test above could pass on a helper that had simply stopped consulting the home."""
    reviewer = _r3_reviewer_dir()
    expected = str(_f3_memory_dir())
    for value in (None, ""):
        if value is None:
            monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        else:
            monkeypatch.setenv("CLAUDE_CONFIG_DIR", value)
        for module in (audit_spawn, _vas):
            assert module._reviewer_memory_dir(reviewer) == expected, (module.__name__, value)

    memory = _mkdir_chain(Path(expected))
    (memory / "MEMORY.md").write_text("notes", encoding="utf-8")
    sink: Dict[str, Any] = {}
    _verdict, err, _calls = _f3_launch(sink)
    assert err is None and sink["reviewer_memory_quarantined"] == 1


def test_g3_an_undeterminable_home_without_the_variable_is_still_a_quarantine_failure(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolated_home: Path) -> None:
    """K55 widens WHERE the directory is, never WHETHER the check happens. With
    CLAUDE_CONFIG_DIR unset and no home resolvable the helper still raises ReviewerCwdError —
    a silent skip is exactly what F3 forbids. CONTROL: the SAME broken home WITH the variable
    set resolves, because the variable alone is enough to name the directory."""
    reviewer = _r3_reviewer_dir()
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    for module in (audit_spawn, _vas):
        with mock.patch.object(module.Path, "home", side_effect=RuntimeError("no home")):
            with pytest.raises(module.ReviewerCwdError) as exc:
                module._reviewer_memory_dir(reviewer)
        assert "home directory" in str(exc.value), module.__name__

    config = _mkdir_chain(tmp_path / "config-only")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    for module in (audit_spawn, _vas):
        with mock.patch.object(module.Path, "home", side_effect=RuntimeError("no home")):
            assert module._reviewer_memory_dir(reviewer) == str(_memory_under(config, reviewer))


def test_g4_the_substitute_resolves_its_own_reviewer_cwd_and_memory_dir(
        _isolated_home: Path) -> None:
    """G4 (plan K56): `variant="substitute"` resolves a SECOND reviewer directory — the same
    parent, `-substitute` appended before the uid suffix — which gives it a different slug and
    therefore a different memory directory, with no second code path. CONTROL: the arbiter and
    the Claude arm pass no variant and still resolve the SAME directory, so the parity the
    launchers are duplicated for is untouched."""
    arm = audit_spawn.resolve_reviewer_cwd()
    substitute = audit_spawn.resolve_reviewer_cwd(variant="substitute")
    assert substitute != arm
    assert arm == _r3_reviewer_dir() and substitute == _r3_reviewer_dir("substitute")
    assert os.path.basename(substitute) == audit_spawn.REVIEWER_CWD_NAME + "-substitute"
    assert os.path.dirname(substitute) == os.path.dirname(arm)

    arm_memory = audit_spawn._reviewer_memory_dir(arm)
    sub_memory = audit_spawn._reviewer_memory_dir(substitute)
    assert arm_memory != sub_memory
    assert (Path(arm_memory), Path(sub_memory)) == (_f3_memory_dir(), _f3_memory_dir("substitute"))

    # CONTROL: no variant -> one directory, and the arbiter agrees with the arm (K2 parity).
    assert _vas.resolve_reviewer_cwd() == arm
    assert audit_spawn.resolve_reviewer_cwd(variant=None) == arm


def test_g4_a_seeded_entry_in_one_memory_dir_is_untouched_by_the_other_arm(
        tmp_path: Path, _isolated_home: Path) -> None:
    """G4 (plan K56), the defect itself: the arm and the substitute quarantine INDEPENDENTLY.
    A seeded entry in the arm's memory dir survives the substitute's launch and vice versa —
    before the fix both launches emptied ONE directory, so the arm could re-create `memory/`
    after the substitute had cleared it and the two arms stopped being independent."""
    arm_memory = _mkdir_chain(_f3_memory_dir())
    (arm_memory / "MEMORY.md").write_text("the arm's notes", encoding="utf-8")
    sub_memory = _mkdir_chain(_f3_memory_dir("substitute"))
    (sub_memory / "MEMORY.md").write_text("the substitute's notes", encoding="utf-8")

    seen: List[Dict[str, Any]] = []

    def fake_run(_cmd, **kwargs):
        seen.append({"cwd": kwargs["cwd"], "arm": sorted(os.listdir(arm_memory)),
                     "sub": sorted(os.listdir(sub_memory))})
        return SimpleNamespace(stdout=_r3_envelope(None), returncode=0, stderr="")

    root = _mkdir_chain(tmp_path / "proj")
    codex_usage: Dict[str, Any] = {}
    with _codex_spawn_patched(fake_run):
        verdict, err = audit_spawn._substitute_codex_arm(
            "the prompt", "cli_missing", None, codex_usage, project_root=root, attempts=0)
    assert err is None and verdict["verdict"] == "pass", err
    # The substitute launched from ITS directory, emptied ITS memory, and left the arm's alone.
    assert seen == [{"cwd": _r3_reviewer_dir("substitute"), "arm": ["MEMORY.md"], "sub": []}]
    assert codex_usage["substitution"]["usage"]["reviewer_memory_quarantined"] == 1

    sink: Dict[str, Any] = {}
    _verdict, err, calls = _f3_launch(
        sink, observe=lambda _kw: {"arm": sorted(os.listdir(arm_memory)),
                                   "sub": sorted(os.listdir(sub_memory))})
    assert err is None
    assert calls == [{"cwd": _r3_reviewer_dir(), "observed": {"arm": [], "sub": []}}]
    assert sink["reviewer_memory_quarantined"] == 1
    # Nothing was deleted: each quarantine holds exactly its own arm's entry.
    for memory, text in ((arm_memory, "the arm's notes"), (sub_memory, "the substitute's notes")):
        stamps = sorted((memory.parent / "memory.quarantine").iterdir())
        assert len(stamps) == 1, (memory, stamps)
        assert (stamps[0] / "MEMORY.md").read_text(encoding="utf-8") == text


def test_g4_the_substitute_directory_is_subject_to_the_same_refusals(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolated_home: Path) -> None:
    """G4 (plan K56): the variant directory is not a bypass. It goes through the identical
    resolve_reviewer_cwd body, so the same safety rules refuse it — proven here on the
    forbidden-entry rule and on the reviewer directory's own mode rule. CONTROL: the arm's
    directory, left clean, still resolves in the same call."""
    substitute = audit_spawn.resolve_reviewer_cwd(variant="substitute")
    (Path(substitute) / "CLAUDE.md").write_text("project instructions", encoding="utf-8")
    with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
        audit_spawn.resolve_reviewer_cwd(variant="substitute")
    assert "CLAUDE.md" in str(exc.value) and "-substitute" in str(exc.value)
    assert audit_spawn.resolve_reviewer_cwd() == _r3_reviewer_dir()   # CONTROL
    (Path(substitute) / "CLAUDE.md").unlink()

    if hasattr(os, "getuid"):
        os.chmod(substitute, 0o777)
        with pytest.raises(audit_spawn.ReviewerCwdError) as exc:
            audit_spawn.resolve_reviewer_cwd(variant="substitute")
        assert "group/world-writable" in str(exc.value)
        os.chmod(substitute, 0o700)
    assert audit_spawn.resolve_reviewer_cwd(variant="substitute") == substitute


def test_g4_both_launchers_carry_the_identical_variant_signature(
        _isolated_home: Path) -> None:
    """PARITY (plan K2 / K56): the two duplicated resolvers take the SAME keyword-only
    `variant` and name the same directory for the same value, and only `_substitute_codex_arm`
    passes one — the substitute is NEVER identified by `model is not None`, which would
    mislabel any model-pinned Claude-arm call as a substitute."""
    for name in ("resolve_reviewer_cwd", "_reviewer_cwd_candidate"):
        first = inspect.signature(getattr(audit_spawn, name))
        assert first == inspect.signature(getattr(_vas, name)), name
        assert first.parameters["variant"].kind is inspect.Parameter.KEYWORD_ONLY, name
        assert first.parameters["variant"].default is None, name
    assert (inspect.signature(audit_spawn.run_claude_auditor).parameters["variant"].kind
            is inspect.Parameter.KEYWORD_ONLY)

    for variant in (None, "substitute"):
        assert (audit_spawn.resolve_reviewer_cwd(variant=variant)
                == _vas.resolve_reviewer_cwd(variant=variant)), variant
        assert (audit_spawn._reviewer_cwd_candidate(variant=variant)
                == _vas._reviewer_cwd_candidate(variant=variant)), variant

    # Exactly ONE call site passes a variant, read off the AST so a docstring mentioning the
    # keyword cannot satisfy (or break) the count.
    tree = ast.parse(Path(audit_spawn.__file__).read_text(encoding="utf-8"))
    passers = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
               and any(kw.arg == "variant" and not isinstance(kw.value, ast.Name)
                       for kw in node.keywords)]
    assert len(passers) == 1, [ast.dump(n) for n in passers]
    (kw,) = [k for k in passers[0].keywords if k.arg == "variant"]
    assert isinstance(kw.value, ast.Constant) and kw.value.value == "substitute"
    # The variant is an EXPLICIT parameter, never inferred from the substitute's model pin.
    sink: Dict[str, Any] = {}
    calls: List[str] = []

    def fake_run(_cmd, **kwargs):
        calls.append(kwargs["cwd"])
        return SimpleNamespace(stdout=_r3_envelope(None), returncode=0, stderr="")

    with _codex_spawn_patched(fake_run):
        _verdict, err = audit_spawn.run_claude_auditor("p", 60, sink, model="fable")
    assert err is None and calls == [_r3_reviewer_dir()]


# ---------------------------------------------------------------------------
# #282 fix round 2 G7d — the override-gap provenance GOLDEN (plan K59d)
# ---------------------------------------------------------------------------


@_POSIX_ONLY
def test_g7d_golden_the_override_gap_provenance_of_malformed_and_timeout_twice(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """GOLDEN / CHARACTERIZATION (plan K59d), NOT a fix: it must pass GREEN against the code
    as it stands. It pins the shape fix round 1's F1 (K35/K36) produces for the two override
    gaps the spec names — `malformed_twice` (a stub that exits 0 with unparseable stdout) and
    `timeout_twice` (a stub that hangs past a bounded budget) — reached through the two
    DIFFERENT harnesses those two cases need, and asserts ONE pinned shape for both:

      * exit 4 / AUDIT_UNAVAILABLE, the Claude arm's own verdict still present;
      * `bin_override` present in the codex block and naming AUDIT_CODEX_BIN;
      * NONE of `codex_arm_substituted_by`, `substitution_reason`, `substitute_timeout_s`,
        `substitute_bin_override`;
      * no `kind: substitution` row in the temp-HOME budget store, and ONE Claude call (the
        arm) — a substitute would have made a second.

    A RED result here means F1 regressed: that is a STOP for the round, never something to
    "fix" in this stage.
    """
    def golden(out: Dict[str, Any], budget: List[dict], claude_calls: int, label: str) -> None:
        assert out["result"] == "AUDIT_UNAVAILABLE", label
        assert out["claude_verdict"] is not None and out["codex_verdict"] is None, label
        block = out["model_provenance"]["codex"]
        record = block["bin_override"]
        assert record["var"] == "AUDIT_CODEX_BIN", label
        assert set(record) == {"var", "value", "realpath"}, label
        for key in ("codex_arm_substituted_by", "substitution_reason", "substitute_timeout_s",
                    "substitute_bin_override"):
            assert key not in block, (label, key)
        assert [r for r in budget if r.get("kind") == "substitution"] == [], label
        assert claude_calls == 1, label

    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["malformed", "malformed"],
                                claude_plan=[_PASS], wait=True)
    assert run["code"] == 4, (run["out"], run["stderr"])
    _assert_override_gap(run["out"], reason="malformed_twice")
    golden(run["out"], run["budget"], len(run["claude"]), "malformed_twice")
    assert len(run["codex"]) == 2

    # RE-POINTED (S081 revision 4, WP-A03, D24): the `timeout_twice` half now drives the IDLE
    # timeout — the stop that still classifies as a retryable timeout. The golden SHAPE this
    # test pins is unchanged; only the way the stub is stopped is stated explicitly.
    hang = _in_process_audit(tmp_path / "hang", monkeypatch, capsys, codex_plan=["sleep"],
                             claude_plan=[_PASS], codex_bin_override=True,
                             codex_timeout_s=30, idle_timeout_s=1)
    assert hang["code"] == 4, hang["out"]
    _assert_override_gap(hang["out"], reason="timeout_twice")
    golden(hang["out"], hang["budget"], len(hang["claude"]), "timeout_twice")
    assert len(hang["codex"]) == 2


def test_r3_served_model_from_the_acceptance_fixture() -> None:
    """(f) the REAL envelope: served == its sonnet id, every modelUsage key kept, no mismatch for the
    requested "sonnet" — in both launchers."""
    envelope = json.loads(_R3_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(envelope, dict) and envelope["type"] == "result" and "modelUsage" in envelope
    for module in (audit_spawn, _vas):
        fields = module._served_model_fields(envelope, "sonnet")
        assert fields == {"served_model": "claude-sonnet-5", "served_model_usage": {"claude-sonnet-5": 4},
                          "served_model_mismatch": None}, module.__name__
        # The existing token/usage readers still read this real shape.
        assert module._claude_tokens(envelope)["output_tokens"] == 4


def test_r3_multi_key_model_usage_and_the_mismatch_rule() -> None:
    """(f) {claude-haiku-x: 50, claude-fable-5-1: 900} requested "fable" -> served claude-fable-5-1, both
    keys kept, no mismatch (alias vs full id is NOT a mismatch). CONTROL: claude-opus-5 served for
    "fable" IS a mismatch. No modelUsage -> "unknown" and no mismatch. Ties -> the smallest id. Both
    launchers give identical answers (parity), for the stream-array shape too."""
    def env(usage):
        return {"type": "result", "result": "x", "modelUsage": {k: {"outputTokens": v} for k, v in usage.items()}}

    cases = [
        (env({"claude-haiku-x": 50, "claude-fable-5-1": 900}), "fable",
         ("claude-fable-5-1", {"claude-haiku-x": 50, "claude-fable-5-1": 900}, None)),
        (env({"claude-opus-5": 700}), "fable", ("claude-opus-5", {"claude-opus-5": 700}, True)),
        ({"type": "result", "result": "x"}, "fable", ("unknown", None, None)),
        (env({"claude-b-1": 10, "claude-a-1": 10}), "a", ("claude-a-1", {"claude-b-1": 10, "claude-a-1": 10}, None)),
        (env({"CLAUDE-Fable-5-1": 3}), "FABLE", ("CLAUDE-Fable-5-1", {"CLAUDE-Fable-5-1": 3}, None)),
        (env({"claude-fable-5-1": 3}), "claude-fable-5-1", ("claude-fable-5-1", {"claude-fable-5-1": 3}, None)),
        (env({"claude-opus-5": 3}), "opus[1m]", ("claude-opus-5", {"claude-opus-5": 3}, None)),
        (env({"claude-fabled-5": 3}), "fable", ("claude-fabled-5", {"claude-fabled-5": 3}, True)),
        ({"type": "result", "modelUsage": {"claude-x-1": {"outputTokens": "lots"}}}, "x",
         ("claude-x-1", {"claude-x-1": None}, None)),
        ([{"type": "system"}, env({"claude-fable-5-1": 9})], "fable",
         ("claude-fable-5-1", {"claude-fable-5-1": 9}, None)),
        (None, "fable", ("unknown", None, None)),
        ("not json", "fable", ("unknown", None, None)),
        ({"type": "result", "modelUsage": "garbage"}, "fable", ("unknown", None, None)),
    ]
    for envelope, requested, (served, usage, mismatch) in cases:
        for module in (audit_spawn, _vas):
            got = module._served_model_fields(envelope, requested)
            assert got == {"served_model": served, "served_model_usage": usage,
                           "served_model_mismatch": mismatch}, (module.__name__, envelope, requested, got)


def test_r3_a_served_model_mismatch_is_warned_and_recorded_never_a_verdict_change(
        capsys: pytest.CaptureFixture) -> None:
    """K4: opus served for "fable" -> the verdict is still returned, usage_out carries the mismatch, and
    ONE ASCII stderr WARNING names both. CONTROL: a matching served id and an envelope without
    modelUsage -> no warning, and no mismatch recorded."""
    def call(model_usage):
        sink: Dict[str, Any] = {}
        with _codex_spawn_patched(lambda c, **k: SimpleNamespace(stdout=_r3_envelope(model_usage),
                                                                          returncode=0, stderr="")):
            verdict, err = audit_spawn.run_claude_auditor("p", 60, sink, model="fable")
        return verdict, err, sink, capsys.readouterr().err

    verdict, err, sink, stderr = call({"claude-opus-5": 700})
    assert err is None and verdict["verdict"] == "pass"
    assert (sink["served_model"], sink["served_model_mismatch"]) == ("claude-opus-5", True)
    warnings = [line for line in stderr.splitlines() if "WARNING" in line]
    assert len(warnings) == 1 and "claude-opus-5" in warnings[0] and "fable" in warnings[0]
    assert "served_model_mismatch" in warnings[0] and warnings[0].isascii()

    for usage, served in (({"claude-fable-5-1": 700}, "claude-fable-5-1"), (None, "unknown")):
        verdict, err, sink, stderr = call(usage)
        assert err is None and verdict["verdict"] == "pass"
        assert (sink["served_model"], sink["served_model_mismatch"]) == (served, None)
        assert "WARNING" not in stderr


@_POSIX_ONLY
def test_r3_served_model_reaches_the_rows_and_the_provenance_through_the_cli(tmp_path: Path) -> None:
    """(f) + (g) end to end: codex 429s, the Claude arm's envelope names the full id of the requested
    Claude main-tier alias (plus a haiku key) and the substitute's names another tier's id. The
    audit_claude row records the main-tier id with both keys and no mismatch; provenance claude.reported
    is that id, source claude_model_usage; the substituted audit_codex row records the other id with
    served_model_mismatch true and a stderr
    WARNING — and the result is still VERIFIED, exit 0 (K4); codex_arm_substituted_by keeps the alias.
    CONTROL (the default stub, no modelUsage) lives in test_codex_429_is_served_by_a_fresh_fable_auditor:
    reported / served_model "unknown" and neither new key."""
    home = _substitution_home(tmp_path)
    # #291: the arm's served id is the full id OF the requested alias (MAIN) -> no mismatch; the
    # substitute's is the full id of ANOTHER tier's alias (SUPPORT, never MAIN by the roster invariant)
    # -> a mismatch. Before the roster swap these were claude-fable-5-1 and claude-opus-5.
    same, other = SERVED_ID[MAIN], SERVED_ID[SUPPORT]
    arm = dict(_PASS, model_usage={"claude-haiku-x": 50, same: 900})
    sub = dict(_SUB_PASS, model_usage={other: 300})
    run = _run_substitution_cli(tmp_path, home, codex_plan=["429"], claude_plan=[arm, sub], wait=True,
        codex_on_path=True)
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", (run["out"], run["stderr"])
    _assert_top_level_keys(run)
    prov = run["out"]["model_provenance"]
    assert (prov["claude"]["reported"], prov["claude"]["reported_source"]) == (same, "claude_model_usage")
    assert prov["claude"]["requested"] == MAIN
    assert prov["codex"]["codex_arm_substituted_by"] == MAIN
    claude_row, codex_row = run["rows"]["audit_claude"], run["rows"]["audit_codex"]
    assert (claude_row["served_model"], claude_row["served_model_usage"]) == (
        same, {"claude-haiku-x": 50, same: 900})
    assert "served_model_mismatch" not in claude_row
    assert (codex_row["model"], codex_row["served_model"], codex_row["served_model_usage"],
            codex_row["served_model_mismatch"]) == (MAIN, other, {other: 300}, True)
    warnings = [line for line in run["stderr"].splitlines() if "served_model_mismatch" in line]
    assert len(warnings) == 1 and other in warnings[0]


def test_r3_no_model_usage_keeps_reported_unknown_and_adds_no_row_keys(tmp_path: Path,
                                                                        capsys: pytest.CaptureFixture) -> None:
    """(g) CONTROL, in process: envelopes without modelUsage -> provenance claude reported / reported_source
    stay "unknown", the audit_claude row's served_model is "unknown", and neither served_model_usage nor
    served_model_mismatch appears on any row."""
    root, bundle = _audit_project(tmp_path)

    def fake_run(cmd, **kwargs):
        if "codex" in str(cmd[0]).lower():
            return SimpleNamespace(stdout=_audit_verdict_json(), returncode=0, stderr="")
        return SimpleNamespace(stdout=_r3_envelope(None), returncode=0, stderr="")

    with mock.patch.object(audit_spawn, "_codex_cli_missing", return_value=False), \
            _codex_spawn_patched(fake_run):
        with pytest.raises(SystemExit) as exc:
            audit_spawn.main(["audit_spawn.py", "comp-x", str(bundle), "--project-root", str(root)])
    out = json.loads(capsys.readouterr().out)
    assert exc.value.code == 0 and out["result"] == "VERIFIED"
    claude = out["model_provenance"]["claude"]
    assert (claude["reported"], claude["reported_source"]) == ("unknown", "unknown")
    rows = {r["tool"]: r for r in _read_jsonl(root / ".process-observations" / "spawn-runs.jsonl")}
    assert rows["audit_claude"]["served_model"] == "unknown"
    for row in rows.values():
        assert "served_model_usage" not in row and "served_model_mismatch" not in row


# ---------------------------------------------------------------------------
# #282 r10 — a substituted audit is not an admitted TOP call (plan K12)
# ---------------------------------------------------------------------------
#
# main() keeps the audit admission's admission_id and threads it through _run_codex_arm ->
# _substitute_codex_arm -> seat_model.substitute, for a pre-call `unavailable` substitution AND a
# call-time one, so the substitution row names the admission it replaces and the budget counts net
# that audit out. A plan-time substitution (no admission) and an admission the store never recorded
# name none. The conjunction is untouched: every run below still needs two valid verdicts.

_ADMISSION_ID = re.compile(r"[0-9a-f]{32}")


def _netted_count(home: Path, root: Path, cycle_id: str) -> int:
    path = home / ".claude" / "projects" / codex_quota.project_slug(root) / "astra-budget.jsonl"
    return codex_quota._count_admitted(path, cycle_id, None, None)


@_POSIX_ONLY
def test_r10_a_precall_token_substitution_names_the_audit_admission_and_is_netted(tmp_path: Path) -> None:
    home = _substitution_home(tmp_path, reached_type="primary")
    run = _run_substitution_cli(tmp_path, home, codex_plan=["ok"], claude_plan=[_PASS])
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", run["out"]
    assert run["codex"] == [] and len(run["claude"]) == 2
    (admit,), (sub,) = _admit_rows(run), _substitution_rows(run)
    assert (admit["use"], admit["admitted"], admit["unavailable"]) == ("audit", True, "rate_limit_reached")
    assert _ADMISSION_ID.fullmatch(admit["admission_id"])
    assert (sub["reason"], sub["admission_id"], sub["prior_admitted_in_cycle"]) == (
        "rate_limit_reached", admit["admission_id"], 0)
    assert _netted_count(home, run["root"], admit["cycle_id"]) == 0


@_POSIX_ONLY
def test_r10_a_call_time_substitution_names_the_audit_admission_and_is_netted(tmp_path: Path) -> None:
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["error_usage_limit"], claude_plan=[_PASS, _SUB_PASS],
                                wait=True,
        codex_on_path=True)
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", run["stderr"]
    assert len(run["codex"]) == 1 and len(run["claude"]) == 2
    (admit,), (sub,) = _admit_rows(run), _substitution_rows(run)
    assert "unavailable" not in admit and _ADMISSION_ID.fullmatch(admit["admission_id"])
    assert (sub["reason"], sub["admission_id"], sub["prior_admitted_in_cycle"]) == (
        "quota_exhausted", admit["admission_id"], 0)
    assert _netted_count(home, run["root"], admit["cycle_id"]) == 0


@_POSIX_ONLY
def test_r10_control_a_plan_time_substitution_names_no_admission_and_a_real_call_still_counts(tmp_path: Path) -> None:
    """CONTROL: cli_missing is decided before any admission -> no admit row, the substitution names none.
    CONTROL: codex answering -> the admission stands un-netted (the netting never swallows a real TOP call)."""
    home = _substitution_home(tmp_path)
    run = _run_substitution_cli(tmp_path, home, codex_plan=["ok"], claude_plan=[_PASS], codex_bin_env=False,
                                path_dir=tmp_path / "path-without-codex")
    assert run["code"] == 0 and run["out"]["result"] == "VERIFIED", run["out"]
    assert run["codex"] == [] and _admit_rows(run) == []
    assert [(r["reason"], r["admission_id"]) for r in _substitution_rows(run)] == [("cli_missing", None)]

    ran_root = tmp_path / "ran"
    ran_home = _substitution_home(ran_root)
    ran = _run_substitution_cli(ran_root, ran_home, codex_plan=["ok"], claude_plan=[_PASS], wait=True)
    assert ran["code"] == 0 and ran["out"]["result"] == "VERIFIED" and len(ran["codex"]) == 1
    (admit,) = _admit_rows(ran)
    assert _substitution_rows(ran) == [] and _ADMISSION_ID.fullmatch(admit["admission_id"])
    assert _netted_count(ran_home, ran["root"], admit["cycle_id"]) == 1


def test_r10_an_unrecorded_admission_is_never_named_and_the_audit_completes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """In process, a call-time 429 substitutes. (a) an unwritable budget store: the admission row is not
    written, so the substitution names no admission (admission_id None) and the audit still completes;
    (b) a missing decision (admit raising): the same. CONTROL: a writable store -> the id the admit row
    carries reaches seat_model.substitute and the substitution row."""
    monkeypatch.setattr(audit_spawn, "_codex_cli_missing", lambda: False)
    stderr_429 = "ERROR: exceeded retry limit, last status: 429 Too Many Requests\n"

    def fake_run(cmd, **kwargs):
        if "codex" in str(cmd[0]).lower():
            return SimpleNamespace(stdout="", returncode=1, stderr=stderr_429)
        return SimpleNamespace(stdout=json.dumps([{"type": "result", "result": _audit_verdict_json()}]),
                               returncode=0, stderr="")

    def audit(root_dir: Path, admit_error: Optional[Exception] = None) -> Tuple[int, dict, Any, Path]:
        root, bundle = _audit_project(root_dir)
        admit_patch = (mock.patch.object(audit_spawn.codex_quota, "admit", side_effect=admit_error)
                       if admit_error is not None else mock.patch.object(audit_spawn.codex_quota, "admit",
                                                                         wraps=codex_quota.admit))
        with _codex_spawn_patched(fake_run), admit_patch, \
                mock.patch.object(audit_spawn.seat_model, "substitute", wraps=seat_model.substitute) as sub:
            with pytest.raises(SystemExit) as exc:
                audit_spawn.main(["audit_spawn.py", "comp-x", str(bundle), "--project-root", str(root)])
        out = json.loads(capsys.readouterr().out)
        return exc.value.code, out, sub, root

    projects = Path.home() / ".claude" / "projects"
    projects.parent.mkdir(parents=True, exist_ok=True)
    projects.write_text("not a directory", encoding="utf-8")
    code, out, sub, _root = audit(tmp_path / "unwritable")
    assert code == 0 and out["result"] == "VERIFIED", out
    block = out["model_provenance"]["codex"]
    assert (block["substitution_reason"], block["codex_arm_substituted_by"]) == ("quota_exhausted", MAIN)
    assert "substitution_row_error" in block
    assert sub.call_count == 1 and sub.call_args.kwargs["admission_id"] is None
    projects.unlink()

    code, out, sub, root = audit(tmp_path / "no-decision", admit_error=RuntimeError("store exploded"))
    assert code == 0 and out["result"] == "VERIFIED", out
    assert sub.call_count == 1 and sub.call_args.kwargs["admission_id"] is None
    rows = _budget_rows(Path.home(), root)
    assert [(r.get("kind"), r["admission_id"]) for r in rows] == [("substitution", None)]

    code, out, sub, root = audit(tmp_path / "control")
    assert code == 0 and out["result"] == "VERIFIED", out
    rows = _budget_rows(Path.home(), root)
    assert [r.get("kind", "admit") for r in rows] == ["admit", "substitution"]
    assert _ADMISSION_ID.fullmatch(rows[0]["admission_id"])
    assert sub.call_args.kwargs["admission_id"] == rows[0]["admission_id"] == rows[1]["admission_id"]


@pytest.mark.parametrize("precall_reason,expected", [
    ("rate_limit_reached", "0123456789abcdef0123456789abcdef"),
    ("quota_exhausted", "0123456789abcdef0123456789abcdef"),
    ("cli_missing", None),
    ("no_eligible_model", None),
])
def test_r10_the_codex_slot_never_names_an_admission_for_a_plan_time_reason(
        tmp_path: Path, precall_reason: str, expected: Optional[str]) -> None:
    """_run_codex_arm's own guard: a plan-time reason (no admission happened) never carries an id, even
    if a caller passed one; a pre-call `unavailable` token does."""
    sink: Dict[str, Any] = {}
    with mock.patch.object(audit_spawn.seat_model, "substitute",
                           side_effect=seat_model.SeatModelError("stop here")) as sub, \
            _codex_spawn_patched(AssertionError("no codex call")):
        verdict, err = audit_spawn._run_codex_arm("prompt", 60, sink, project_root=tmp_path,
                                                  precall_reason=precall_reason,
                                                  admission_id="0123456789abcdef0123456789abcdef")
    assert verdict is None and "stop here" in err
    assert sub.call_count == 1 and sub.call_args.kwargs["admission_id"] == expected


# ---------------------------------------------------------------------------
# #54 — race-safe verdicts dir
# ---------------------------------------------------------------------------

def test_ensure_verdicts_dir_creates_directory(tmp_path: Path) -> None:
    """ensure_verdicts_dir() creates the dir and returns the resolved path."""
    target = tmp_path / "ledger" / "verdicts"
    assert not target.exists()
    out = audit_spawn.ensure_verdicts_dir(target)
    assert out.exists() and out.is_dir()
    assert out == target.resolve()


def test_ensure_verdicts_dir_idempotent(tmp_path: Path) -> None:
    """Calling ensure_verdicts_dir() twice on the same path is safe."""
    target = tmp_path / "ledger" / "verdicts"
    audit_spawn.ensure_verdicts_dir(target)
    # No exception on the second call.
    audit_spawn.ensure_verdicts_dir(target)
    assert target.is_dir()


def test_audit_spawn_race_note_documents_motivation() -> None:
    """The race-note string mentions the helper name + the .ledger path."""
    note = audit_spawn.audit_spawn_race_note
    assert "ensure_verdicts_dir" in note
    assert ".ledger/verdicts" in note


# ---------------------------------------------------------------------------
# D24 — the activity watchdog at the codex call site (S081 revision 4, WP-A03)
# ---------------------------------------------------------------------------
#
# STUB BINARIES ONLY. This cycle makes no model call of any kind, so every test
# below drives a fixture script that prints on a schedule and exits with a chosen
# code. The thresholds are SCALED DOWN (an idle timeout of ~1s standing in for 300s,
# a cap of a few seconds standing in for 2400s) and the RATIO is what is preserved:
# a stub that keeps emitting past a fixed budget, a stub that goes silent past the
# idle timeout, a stub that stays busy to the cap. Real seconds would make the suite
# unrunnable and would prove nothing the ratio does not.

#: Emits to stderr every `tick` seconds for `total` seconds, then writes a verdict
#: and exits 0. stderr is where codex prints its transcript, and its growth is one of
#: the three heartbeats the watchdog reads.
_CHATTY_STUB = """#!{python}
import os, sys, time
tick = float(os.environ.get("CHATTY_TICK", "0.1"))
total = float(os.environ.get("CHATTY_TOTAL", "2.0"))
end = time.time() + total
while time.time() < end:
    sys.stderr.write("thinking...\\n")
    sys.stderr.flush()
    time.sleep(tick)
sys.stdout.write(os.environ["CHATTY_VERDICT"])
sys.stdout.flush()
sys.exit(0)
"""

#: Writes one line, then stays BUSY (never silent) for far longer than any cap it
#: will be given -- the runaway a hard cap exists for.
_RUNAWAY_STUB = """#!{python}
import sys, time
while True:
    sys.stderr.write("still going\\n")
    sys.stderr.flush()
    time.sleep(0.05)
"""


def _watch_stub(tmp_path: Path, template: str, *, hard_cap_s: float,
                idle_timeout_s: Optional[float], env: Optional[Dict[str, str]] = None) -> Any:
    """Run one stub under the REAL watchdog and return its WatchResult."""
    stub = _write_stub(tmp_path / "bin" / "stub", template)
    saved = {k: os.environ.get(k) for k in (env or {})}
    os.environ.update(env or {})
    try:
        return codex_watch.watch(
            [str(stub)], mode=codex_watch.MODE_CODEX,
            stdout_path=tmp_path / "out.txt", stderr_path=tmp_path / "err.txt",
            hard_cap_s=hard_cap_s, idle_timeout_s=idle_timeout_s,
            poll_interval_s=0.02, record_telemetry=False,
        )
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_d24_an_active_stub_past_the_old_fixed_budget_now_completes(tmp_path: Path) -> None:
    """THE FIX, WITH THE CONTROL THAT MAKES IT LOAD-BEARING.

    A stub that keeps EMITTING for longer than a fixed budget:
      * under the watchdog (idle timeout above its tick, cap above its runtime) it RUNS TO
        COMPLETION and returns its verdict — the D24 behaviour;
      * under the PRE-CHANGE mechanism (`subprocess.run(timeout=<that budget>)`) the same
        stub is KILLED.

    The control is the whole point: without it "the call completed" would be equally true of
    a stub that finished quickly, and the test would prove nothing. This is the scaled model
    of the evidence D24 was raised on — two sol sessions (896s and 538s) killed by a 600s
    wall clock while still emitting reasoning events to the last second.
    """
    verdict = _audit_verdict_json()
    env = {"CHATTY_TICK": "0.1", "CHATTY_TOTAL": "2.0", "CHATTY_VERDICT": verdict}
    result = _watch_stub(tmp_path / "watched", _CHATTY_STUB,
                         hard_cap_s=30.0, idle_timeout_s=1.0, env=env)
    assert (result.stop_reason, result.child_exit_code) == (codex_watch.STOP_OK, 0)
    assert result.timed_out is False
    assert json.loads(result.stdout_path.read_text(encoding="utf-8"))["verdict"] == "pass"
    # It really did outlive the budget the control kills it with, and it was never silent.
    assert result.elapsed_s > 1.0
    assert result.max_silence_s < 1.0

    # NEGATIVE CONTROL: the pre-change mechanism on the same stub, same budget.
    stub = _write_stub(tmp_path / "control" / "bin" / "stub", _CHATTY_STUB)
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            subprocess.run([str(stub)], capture_output=True, text=True, timeout=1.0,
                           stdin=subprocess.DEVNULL)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_d24_a_silent_stub_is_stopped_and_classified_as_the_retry_once_path(tmp_path: Path) -> None:
    """A stub that goes SILENT past the idle timeout is stopped, and the classifier's
    idle rule (unchanged by D21 F10, which moved only the 112 hard-cap rule) maps it to
    the retry-once rule — retry on attempt 1, substitute `timeout_twice` on attempt 2. No
    new substitution reason exists."""
    result = _watch_stub(tmp_path, _CHATTY_STUB, hard_cap_s=30.0, idle_timeout_s=0.5,
                         env={"CHATTY_TICK": "5.0", "CHATTY_TOTAL": "20.0",
                              "CHATTY_VERDICT": "{}"})
    assert result.stop_reason == codex_watch.STOP_IDLE_TIMEOUT
    assert result.exit_code == codex_watch.EXIT_IDLE_TIMEOUT
    assert result.elapsed_s < 20.0, "stopped on silence, not by running to the stub's end"

    outcome = audit_spawn._outcome_from_watch(result, "")
    assert outcome["timed_out"] is True
    assert codex_quota.classify_codex_failure(
        outcome["returncode"], outcome["stderr"], timed_out=outcome["timed_out"],
        output_ok=False, attempt=1) == (codex_quota.ACTION_RETRY, "timeout")
    assert codex_quota.classify_codex_failure(
        outcome["returncode"], outcome["stderr"], timed_out=outcome["timed_out"],
        output_ok=False, attempt=2) == (codex_quota.ACTION_SUBSTITUTE, "timeout_twice")
    assert "timeout_twice" in codex_quota.SUBSTITUTION_REASONS


def test_d24_a_stub_active_to_the_hard_cap_is_a_gap_with_no_substitution(tmp_path: Path) -> None:
    """A stub that stays BUSY to its cap is a runaway, and a runaway is a GAP on the FIRST
    hit — never a substitution, at any attempt. This is the asymmetry the design asks for:
    silence is retryable, a runaway is not."""
    result = _watch_stub(tmp_path, _RUNAWAY_STUB, hard_cap_s=1.0, idle_timeout_s=30.0)
    assert result.stop_reason == codex_watch.STOP_HARD_CAP
    assert result.exit_code == codex_watch.EXIT_HARD_CAP

    outcome = audit_spawn._outcome_from_watch(result, "")
    assert (outcome["returncode"], outcome["timed_out"]) == (codex_watch.EXIT_HARD_CAP, False)
    for attempt in (1, 2):
        assert codex_quota.classify_codex_failure(
            outcome["returncode"], outcome["stderr"], timed_out=outcome["timed_out"],
            output_ok=False, attempt=attempt) == (codex_quota.ACTION_GAP, "codex_error"), attempt


def test_d24_a_hard_cap_run_writes_no_substitution_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                       capsys: pytest.CaptureFixture) -> None:
    """The gap reaches the END of the arm: a full in-process audit whose codex stub stays busy
    to the cap records NO `kind: substitution` row in the temp-HOME budget store, and the run
    is AUDIT_UNAVAILABLE rather than a silently substituted pass."""
    monkeypatch.setenv("CHATTY_TICK", "0.05")
    monkeypatch.setenv("CHATTY_TOTAL", "60.0")
    monkeypatch.setenv("CHATTY_VERDICT", "{}")
    run = _in_process_audit(tmp_path, monkeypatch, capsys, codex_plan=["sleep"],
                            claude_plan=[_PASS], codex_timeout_s=1, idle_timeout_s=30)
    assert run["out"]["result"] == "AUDIT_UNAVAILABLE", run["out"]
    assert _substitution_rows(run) == []
    block = run["out"]["model_provenance"]["codex"]
    assert "codex_arm_substituted_by" not in block and "substitution_reason" not in block


def test_d24_the_pool_join_cannot_fire_before_the_arms_own_cap(tmp_path: Path) -> None:
    """The join is always LOOSER than the worst path the codex arm can take, so the pool can
    never become the new premature killer — the truncation moving from the arm to the join is
    the one way this fix could reintroduce what it removes.

    Proven across the tier table rather than on today's numbers alone: for every codex
    ceiling codex_model can resolve, the join strictly exceeds two attempts plus a substitute.
    """
    for effort, ceiling in sorted(codex_model._TIMEOUT_FLOOR_S.items()):
        join = audit_spawn._join_timeout_s(
            audit_spawn.DEFAULT_TIMEOUT_S, ceiling, audit_spawn.SUBSTITUTE_TIMEOUT_S)
        worst = audit_spawn.CODEX_MAX_ATTEMPTS * ceiling + audit_spawn.SUBSTITUTE_TIMEOUT_S
        assert join > worst, (effort, ceiling, join, worst)
        assert join > ceiling, (effort, ceiling)
    # And on the pins actually in force.
    assert audit_spawn._join_timeout_s(
        audit_spawn.DEFAULT_TIMEOUT_S, audit_spawn.CODEX_TIMEOUT_S,
        audit_spawn.SUBSTITUTE_TIMEOUT_S) == 5430


# ---------------------------------------------------------------------------
# S081 revision 4, D21 fix round 1 -- WP-X5: F8's one banner regex, and the
# AUDIT-LEVEL proof of F10 (the classifier fix itself landed in WP-X4, in
# codex_quota.classify_codex_failure). Review: docs/reviews/2026-09-22-S081-rev4-review.md.
# ---------------------------------------------------------------------------

#: The first 12 stderr lines of the D21 review's astra call (codex-cli 0.155.1), VERBATIM.
#: The golden is progress/.golden-rev4/fix-round-1/codex-banner-0.155.1.stderr, which the
#: ~/.claude tree does not carry, so the bytes are embedded and their sha256 asserted.
_X5_BANNER_0155_1 = (
    "Reading additional input from stdin...\n"
    "OpenAI Codex v0.155.1\n"
    "--------\n"
    "workdir: /tmp/claude-1000/-path-to-projects-foundry-lab/"
    "148bbc98-4e5f-4060-8444-37a973666792/scratchpad/d21clone\n"
    "model: gpt-6-astra\n"
    "provider: openai\n"
    "approval: never\n"
    "sandbox: read-only\n"
    "reasoning effort: xhigh\n"
    "reasoning summaries: none\n"
    "session id: 01a0cb17-355b-7f32-92f6-010c8f42b7d6\n"
    "--------\n"
)
_X5_BANNER_0155_1_SHA256 = "6165fabebe14c98eb19fbf6efb63094a71ffffc724851930f58b739b27d4505c"
_X5_BANNER_0155_1_ID = "01a0cb17-355b-7f32-92f6-010c8f42b7d6"


def _x5_session_regex_literals(source: str) -> List[int]:
    """Lines of every `<x>.compile(<literal>, ...)` whose pattern literal mentions `session id`."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "compile" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                and "session id" in node.args[0].value):
            lines.append(node.lineno)
    return lines


def test_x5_F8_audit_spawn_binds_codex_watchs_one_banner_regex() -> None:
    """ONE banner regex (plan L40). codex_watch defines it -- the watchdog needs it to find the
    rollout heartbeat of a plain `codex exec` -- and audit_spawn binds THE SAME OBJECT for its
    token lookup; no second `session id:` pattern is compiled anywhere in audit_spawn.py."""
    assert audit_spawn._CODEX_BANNER_SESSION_RE is codex_watch.CODEX_BANNER_SESSION_RE
    source = Path(audit_spawn.__file__).read_text(encoding="utf-8")
    assert _x5_session_regex_literals(source) == []
    # NEGATIVE CONTROL: the scan does find a private copy.
    assert _x5_session_regex_literals(
        'import re\n_R = re.compile(r"^session id:[ \\t]*(x)$", re.MULTILINE)\n') == [2]


def test_x5_F8_control_the_token_lookup_reads_the_real_0155_banner() -> None:
    """CONTROL (green at the round base): the post-hoc token lookup already read the banner
    form; binding the watchdog's object changes nothing it returns."""
    assert hashlib.sha256(_X5_BANNER_0155_1.encode("utf-8")).hexdigest() == _X5_BANNER_0155_1_SHA256
    assert audit_spawn._codex_session_id(_X5_BANNER_0155_1 + "user\n") == _X5_BANNER_0155_1_ID
    assert audit_spawn._codex_session_id(REAL_CODEX_0154_STDERR) == _SESSION_ID


#: A codex-owned error line of each family that used to buy a retry or a substitution out of a
#: hard-capped transcript: capacity (retry), and two exhaustion shapes (substitute quota_exhausted).
_X5_F10_LINES = {
    "capacity": "ERROR: Selected model is at capacity. Please try a different model.\n",
    "exhaustion_429": "ERROR: exceeded retry limit, last status: 429 Too Many Requests\n",
    "usage_limit": _USAGE_LIMIT_LINE,
}


def _x5_codex_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, stop_reason: str,
                   child_exit: int, line: str) -> Tuple[int, Optional[str], int, List[str], int, str]:
    """Run THE CODEX SLOT (_run_codex_arm) in process against a STUBBED codex_watch.watch -- no
    codex and no claude run. Every call "ends" with `stop_reason`, the 0.154.0 banner and `line` on
    its stderr. Returns (watch calls, substitution reason, substitute-auditor calls, substitution
    rows' reasons, codex_attempts, error)."""
    calls: List[List[str]] = []

    def watched(cmd, **kwargs):
        calls.append([str(c) for c in cmd])
        out_path, err_path = Path(kwargs["stdout_path"]), Path(kwargs["stderr_path"])
        out_path.write_text("", encoding="utf-8")
        err_path.write_text(REAL_CODEX_0154_STDERR + line, encoding="utf-8")
        capped = stop_reason == codex_watch.STOP_HARD_CAP
        return codex_watch.WatchResult(
            stop_reason=stop_reason,
            exit_code=codex_watch.EXIT_HARD_CAP if capped else child_exit,
            child_exit_code=child_exit, elapsed_s=2400.0 if capped else 5.0, max_silence_s=12.0,
            mode=codex_watch.MODE_CODEX, argv=tuple(calls[-1]), stdout_path=out_path,
            stderr_path=err_path, idle_timeout_s=float(codex_watch.IDLE_TIMEOUT_S),
            hard_cap_s=float(kwargs.get("hard_cap_s") or 2400.0),
        )

    substitutes: List[Any] = []

    def substitute_auditor(*_args, **kwargs):
        substitutes.append(kwargs.get("model"))
        return None, "stub substitute: no verdict"

    monkeypatch.setattr(audit_spawn.codex_watch, "watch", watched)
    monkeypatch.setattr(audit_spawn, "run_claude_auditor", substitute_auditor)
    monkeypatch.setattr(audit_spawn, "CODEX_BIN_OVERRIDE", None)
    root = tmp_path / "x5-proj"
    root.mkdir()
    usage: Dict[str, Any] = {}
    verdict, err = audit_spawn._run_codex_arm("prompt", 2400, usage, project_root=root,
                                              precall_reason=None, admission_id=None)
    assert verdict is None and isinstance(err, str)
    rows = [r.get("reason") for r in _budget_rows(Path.home(), root) if r.get("kind") == "substitution"]
    reason = (usage.get("substitution") or {}).get("reason")
    return len(calls), reason, len(substitutes), rows, usage["codex_attempts"], err


@pytest.mark.parametrize("line", sorted(_X5_F10_LINES))
def test_x5_F10_major_a_hard_capped_call_with_a_codex_error_line_is_a_gap_on_attempt_1(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line: str) -> None:
    """F10 at the AUDIT level, through the codex slot. A call the watchdog stopped at its RUNAWAY
    cap (112) is the non-retryable stop, and a codex error line in its transcript does not make it
    one: ONE call, no second attempt, no substitution, no substitution row, the substitute auditor
    never run. At the round base the classifier read the line first -- capacity bought a retry and
    then `capacity_twice`, an exhaustion line `quota_exhausted` on the first call."""
    calls, reason, substitutes, rows, attempts, err = _x5_codex_slot(
        tmp_path, monkeypatch, stop_reason=codex_watch.STOP_HARD_CAP, child_exit=-15,
        line=_X5_F10_LINES[line])
    assert (calls, reason, substitutes, rows, attempts) == (1, None, 0, [], 1)
    assert "hard cap" in err, err


def test_x5_F10_control_the_same_capacity_line_on_an_ordinary_failure_retries_then_substitutes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CONTROL (green at the base AND after): the harness above is not gap-blind. The same line on
    an ORDINARY failed exit (rc 1) still retries once and substitutes `capacity_twice`."""
    calls, reason, substitutes, rows, attempts, _err = _x5_codex_slot(
        tmp_path, monkeypatch, stop_reason=codex_watch.STOP_OK, child_exit=1,
        line=_X5_F10_LINES["capacity"])
    assert (calls, reason, substitutes, rows, attempts) == (2, "capacity_twice", 1, ["capacity_twice"], 2)


def test_x5_F10_control_a_plain_hard_cap_was_already_a_gap(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CONTROL (green at the base AND after): a hard cap with no codex error line was a gap
    before WP-X4 too -- 112 fell through to the final branch then."""
    calls, reason, substitutes, rows, attempts, err = _x5_codex_slot(
        tmp_path, monkeypatch, stop_reason=codex_watch.STOP_HARD_CAP, child_exit=-15, line="")
    assert (calls, reason, substitutes, rows, attempts) == (1, None, 0, [], 1)
    assert "hard cap" in err, err


#: The two passages of `_outcome_from_watch`'s docstring that WP-X4's classifier made false, as
#: they stood at the round base (13a3e04), VERBATIM (the idle bullet between them omitted; the em
#: dash spelled as an escape) -- NEGATIVE CONTROL only (~/.claude is not a git repository, so the
#: base text is embedded, never read through git).
_X5_BASE_OUTCOME_DOC = """\
    THE CLASSIFIER IS NOT TOUCHED. codex_quota.classify_codex_failure keeps deciding
    retry / substitute / gap, and no new SUBSTITUTION_REASONS token is invented; the
    watchdog's two stop reasons are simply expressed in the outcome fields the
    classifier already reads:
      * `hard_cap`     -> timed_out=False, returncode=codex_watch.EXIT_HARD_CAP (112).
        A runaway that stayed ACTIVE to its cap is NOT the retryable kind: 112 is
        neither 0 nor EXIT_COMMAND_NOT_FOUND (127), so it falls to the classifier's
        final branch, (gap, "codex_error") \u2014 a GAP on the FIRST hit, never a
        substitution, exactly as the design requires.
"""


def _x5_outcome_doc_problems(doc: str) -> List[str]:
    problems = []
    if "THE CLASSIFIER IS NOT TOUCHED" in doc:
        problems.append("says the classifier is not touched (WP-X4 touched it, for F10)")
    if "falls to the classifier's" in doc:
        problems.append("says 112 falls to the classifier's final branch")
    if "decides 112 FIRST" not in doc:
        problems.append("does not say the classifier decides 112 FIRST")
    if "whatever stderr says" not in doc:
        problems.append("does not say a codex error line cannot change the gap")
    return problems


def test_x5_F10_the_outcome_docstring_states_the_first_branch_rule() -> None:
    """GUARD: `_outcome_from_watch` describes the classifier WP-X4 shipped -- the hard cap is its
    FIRST decision, not a fall-through -- and no longer claims the classifier was left alone."""
    assert _x5_outcome_doc_problems(audit_spawn._outcome_from_watch.__doc__ or "") == []
    # NEGATIVE CONTROL: the base passage trips all four.
    assert len(_x5_outcome_doc_problems(_X5_BASE_OUTCOME_DOC)) == 4
    # A TRUE sentence passes.
    assert _x5_outcome_doc_problems(
        "the classifier decides 112 FIRST, whatever stderr says") == []



# --------------------------------------------------------------------------- #
# #311 fix round 1 F1: the protected Claude arm is launched at its PINNED effort
# --------------------------------------------------------------------------- #
def test_311_f1_the_claude_arm_pin_is_the_seat_effort_and_is_on_the_command(tmp_path: Path) -> None:
    pinned = _r3_code_reviewer_effort()
    assert audit_spawn.CLAUDE_EFFORT == pinned
    captured: List[List[str]] = []

    def fake_run(cmd, **kwargs):
        captured.append(list(cmd))
        return SimpleNamespace(stdout=_r3_envelope(None), returncode=0, stderr="")

    root = tmp_path / "proj"
    root.mkdir()
    with _codex_spawn_patched(fake_run):
        verdict, err = audit_spawn.run_claude_auditor("p", 60, project_root=root)
    assert err is None
    (cmd,) = captured
    assert cmd[cmd.index("--effort") + 1] == pinned


@pytest.mark.parametrize("bad", [None, "", "ludicrous"])
def test_311_f1_a_missing_effort_refuses_to_spawn(tmp_path: Path, monkeypatch, bad) -> None:
    monkeypatch.setattr(audit_spawn, "CLAUDE_EFFORT", bad)
    captured: List[List[str]] = []

    def fake_run(cmd, **kwargs):
        captured.append(list(cmd))
        return SimpleNamespace(stdout=_r3_envelope(None), returncode=0, stderr="")

    root = tmp_path / "proj"
    root.mkdir()
    with _codex_spawn_patched(fake_run):
        verdict, err = audit_spawn.run_claude_auditor("p", 60, project_root=root)
    assert verdict is None and "effort" in err
    assert captured == [], "nothing is spawned without the pinned effort"


def test_311_r2_item6_an_explicit_none_effort_refuses_and_the_default_is_the_pin(tmp_path: Path) -> None:
    captured: List[List[str]] = []

    def fake_run(cmd, **kwargs):
        captured.append(list(cmd))
        return SimpleNamespace(stdout=_r3_envelope(None), returncode=0, stderr="")

    root = tmp_path / "proj"
    root.mkdir()
    with _codex_spawn_patched(fake_run):
        verdict, err = audit_spawn.run_claude_auditor("p", 60, project_root=root, effort=None)
        assert verdict is None and "effort" in err and captured == []
        verdict, err = audit_spawn.run_claude_auditor("p", 60, project_root=root)
        assert err is None and captured[-1][captured[-1].index("--effort") + 1] == audit_spawn.CLAUDE_EFFORT


def test_311_r2_item6_a_substitute_pin_without_an_effort_is_not_spawned(tmp_path: Path, monkeypatch) -> None:
    real = audit_spawn.seat_model.substitute

    def no_effort(*a, **kw):
        pin = real(*a, **kw)
        return audit_spawn.seat_model.SeatPin(model=pin.model, effort=None, timeout=pin.timeout,
                                              argv_fragment=("--model", pin.model), provenance=pin.provenance)

    monkeypatch.setattr(audit_spawn.seat_model, "substitute", no_effort)
    captured: List[List[str]] = []

    def fake_run(cmd, **kwargs):
        captured.append(list(cmd))
        return SimpleNamespace(stdout=_r3_envelope(None), returncode=0, stderr="")

    root = tmp_path / "proj"
    root.mkdir()
    sink: Dict[str, Any] = {}
    with _codex_spawn_patched(fake_run):
        verdict, err = audit_spawn._substitute_codex_arm("p", "cli_missing", None, sink, project_root=root,
                                                         attempts=0)
    assert verdict is None and "effort" in err
    assert captured == []


# ---------------------------------------------------------------------------
# #292 — a SIGTERM / SIGHUP to audit_spawn reaps the codex arm's child
# ---------------------------------------------------------------------------

#: A codex that records its pid and then hangs silently, as a long call would.
_HANGING_CODEX_STUB = """#!{python}
import os, time
with open(os.environ["STUB_CODEX_PID"], "w", encoding="utf-8") as fh:
    fh.write(str(os.getpid()))
time.sleep(120)
"""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@_POSIX_ONLY
@pytest.mark.parametrize("signame", ["SIGTERM", "SIGHUP"])
def test_292_a_stop_signal_reaps_the_codex_child_and_exits_128_plus_signum(
    tmp_path: Path, signame: str
) -> None:
    """Before #292 the codex arm ran watch() on a worker thread with no stop latch, so a
    SIGTERM killed audit_spawn and left the codex child (its own session) running."""
    import signal

    signum = getattr(signal, signame)
    home = _fixture_home(tmp_path)
    claude_stub = _write_stub(tmp_path / "bin" / "claude-stub")
    codex_stub = _write_stub(tmp_path / "bin" / "codex-stub", _HANGING_CODEX_STUB)
    pid_file = tmp_path / "codex.pid"
    root, bundle = _audit_project(tmp_path)
    env = _child_env(
        home, AUDIT_CLAUDE_BIN=str(claude_stub), AUDIT_CODEX_BIN=str(codex_stub),
        STUB_CODEX_PID=str(pid_file), STUB_ARGV_LOG=str(tmp_path / "argv.jsonl"),
        STUB_VERDICT_JSON=_audit_verdict_json(),
    )
    proc = subprocess.Popen(
        [sys.executable, str(_META / "audit_spawn.py"), "comp-x", str(bundle),
         "--project-root", str(root)],
        cwd=str(tmp_path), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    codex_pid = None
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and proc.poll() is None:
            if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip():
                codex_pid = int(pid_file.read_text(encoding="utf-8"))
                break
            time.sleep(0.05)
        assert codex_pid is not None, ("the codex stub never started", proc.poll())
        proc.send_signal(signum)
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 128 + signum, err.decode("utf-8", "replace")
        assert out == b"", "a stopped audit must never print a result"
        assert not _pid_alive(codex_pid), "the codex child outlived audit_spawn (orphaned)"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if codex_pid is not None and _pid_alive(codex_pid):
            os.kill(codex_pid, signal.SIGKILL)


class TestStopStartsNoNewCodexWork292:
    """#292 fix round 1 (D21 review F1): once a stop is latched, the codex slot starts no
    retry and no Claude stand-in (the stand-in would also write a substitution row)."""

    @pytest.fixture
    def latched(self, monkeypatch):
        import audit_spawn

        latch = audit_spawn.codex_watch._StopLatch(record_only=True)
        monkeypatch.setattr(audit_spawn, "_STOP_LATCH", latch)
        subs: List[Any] = []
        monkeypatch.setattr(audit_spawn, "_substitute_codex_arm",
                            lambda *a, **k: subs.append((a, k)) or ({"verdict": "pass"}, None))
        return audit_spawn, latch, subs

    def test_a_latched_stop_skips_the_precall_stand_in(self, latched, tmp_path):
        audit_spawn, latch, subs = latched
        latch.handler(15, None)
        with pytest.raises(audit_spawn.codex_watch._StopSignal):
            audit_spawn._run_codex_arm("p", 10, {}, project_root=tmp_path,
                                       precall_reason="quota_exhausted")
        assert subs == []

    @pytest.mark.parametrize("action", ["retry", "substitute"])
    def test_a_stop_during_an_attempt_starts_neither_a_retry_nor_a_stand_in(
        self, latched, tmp_path, monkeypatch, action
    ):
        audit_spawn, latch, subs = latched
        attempts: List[int] = []

        def attempt(*_a, **_k):
            attempts.append(1)
            latch.handler(15, None)  # the stop lands while this attempt runs
            return None, "failed", {"returncode": 1, "stderr": "", "timed_out": False}

        verdicts = {"retry": audit_spawn.codex_quota.ACTION_RETRY,
                    "substitute": audit_spawn.codex_quota.ACTION_SUBSTITUTE}
        monkeypatch.setattr(audit_spawn, "_codex_attempt", attempt)
        monkeypatch.setattr(audit_spawn, "_classify_codex_attempt",
                            lambda *a, **k: (verdicts[action], "timeout_twice", "failed"))
        with pytest.raises(audit_spawn.codex_watch._StopSignal):
            audit_spawn._run_codex_arm("p", 10, {}, project_root=tmp_path, precall_reason=None)
        assert attempts == [1], "a retry started after the stop"
        assert subs == [], "a Claude stand-in started after the stop"

    def test_control_without_a_stop_the_stand_in_still_serves(self, latched, tmp_path, monkeypatch):
        audit_spawn, _latch, subs = latched
        monkeypatch.setattr(audit_spawn, "_codex_attempt",
                            lambda *a, **k: (None, "failed", {"returncode": 1, "stderr": "",
                                                              "timed_out": False}))
        monkeypatch.setattr(audit_spawn, "_classify_codex_attempt",
                            lambda *a, **k: (audit_spawn.codex_quota.ACTION_SUBSTITUTE,
                                             "timeout_twice", "failed"))
        monkeypatch.setattr(audit_spawn, "CODEX_BIN_OVERRIDE", None)
        verdict, _err = audit_spawn._run_codex_arm("p", 10, {}, project_root=tmp_path,
                                                   precall_reason=None)
        assert verdict == {"verdict": "pass"} and len(subs) == 1


@pytest.mark.usefixtures("_restore_stop_signals")
class TestStopOutranksAWorkerException292:
    """#292 fix round 1 (D21 review codex F2): a latched stop exits 128+N even when a
    worker future raised; with no stop, that exception propagates as before."""

    @pytest.fixture
    def _restore_stop_signals(self):
        import signal

        saved = {n: signal.getsignal(getattr(signal, n)) for n in ("SIGTERM", "SIGHUP")
                 if hasattr(signal, n)}
        yield
        for n, h in saved.items():
            signal.signal(getattr(signal, n), h)

    def _main(self, tmp_path, monkeypatch, stop: bool):
        import audit_spawn

        root, bundle = _audit_project(tmp_path)
        monkeypatch.setattr(audit_spawn, "load_component_entry", lambda *a, **k: {"id": "comp-x"})
        monkeypatch.setattr(audit_spawn, "load_ledger_row", lambda *a, **k: {})
        monkeypatch.setattr(audit_spawn, "_plan_time_unavailable", lambda: None)
        monkeypatch.setattr(audit_spawn, "_admit_audit", lambda *a, **k: {})

        def claude(*_a, **_k):
            if stop:
                audit_spawn._STOP_LATCH.handler(15, None)
            raise RuntimeError("the claude arm broke")

        monkeypatch.setattr(audit_spawn, "run_claude_auditor", claude)
        monkeypatch.setattr(audit_spawn, "_run_codex_arm", lambda *a, **k: ({"verdict": "pass"}, None))
        audit_spawn.main(["audit_spawn.py", "comp-x", str(bundle), "--project-root", str(root)])

    def test_a_latched_stop_wins_over_the_worker_exception(self, tmp_path, monkeypatch):
        with pytest.raises(SystemExit) as exc:
            self._main(tmp_path, monkeypatch, stop=True)
        assert exc.value.code == 128 + 15

    def test_control_without_a_stop_the_exception_propagates(self, tmp_path, monkeypatch):
        with pytest.raises(RuntimeError, match="the claude arm broke"):
            self._main(tmp_path, monkeypatch, stop=False)


def test_292_a_stop_while_the_stand_in_row_is_written_starts_no_stand_in(monkeypatch, tmp_path):
    """#292 re-review N1: the stop is re-checked inside _substitute_codex_arm, after the
    budget row and before the Claude stand-in spawns."""
    import audit_spawn

    latch = audit_spawn.codex_watch._StopLatch(record_only=True)
    monkeypatch.setattr(audit_spawn, "_STOP_LATCH", latch)
    spawned: List[Any] = []

    def substitute(*_a, **_k):
        latch.handler(15, None)  # the stop lands while the row is being written
        return SimpleNamespace(model="opus", provenance={"row_written": True})

    monkeypatch.setattr(audit_spawn.seat_model, "substitute", substitute)
    monkeypatch.setattr(audit_spawn, "run_claude_auditor",
                        lambda *a, **k: spawned.append(1) or ({"verdict": "pass"}, None))
    with pytest.raises(audit_spawn.codex_watch._StopSignal):
        audit_spawn._substitute_codex_arm("p", "timeout_twice", "err", {},
                                          project_root=tmp_path, attempts=2, admission_id=None)
    assert spawned == [], "the Claude stand-in started after the stop"
