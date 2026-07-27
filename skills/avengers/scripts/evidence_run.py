#!/usr/bin/env python3
"""avengers — evidence_run.py (WP-4). The execution-grounded evidence primitive.

D5 (design §6). A sandboxed, READ-ONLY, TIME-BOXED runner any seat may REQUEST to
execute an EXISTING test suite / benchmark / read-only probe. The results enter the
docket as DATA — fenced, UNTRUSTED-class in seat prompts (rendered by
seat_prompt.render_evidence_runs, exactly like peer records / member memory). This
is the mechanism that lets the skeptic say "run the suite against the proposal"
instead of speculating (the critic-with-execution edge — MapCoder HumanEval −14pts
without it).

THE HARD-RULE (verbatim, non-negotiable): avengers stays NON-MUTATING. evidence_run
NEVER writes to the project tree, NEVER commits, NEVER spawns bob, NEVER signs a
contract map. It runs a read-only probe, captures its output, and RETURNS it as an
in-memory DATA record. It persists NOTHING to the repo tree itself.

Defense-in-depth (stated HONESTLY — no "structurally secure" overclaim, mirroring
references/trust-boundary.md):

  1. NO SHELL. argv is always a list; ``shell=False``. A SEAT-originated request may
     reference a probe ONLY by ``probe_id`` from a TRUSTED registry — never a raw
     argv (an injected seat supplying ``rm -rf`` / ``python3 -c '...'`` is the exact
     threat this closes). ``run_probe(argv, ...)`` — the low-level primitive that
     accepts an explicit argv — is for TRUSTED callers (the chair/kernel resolving a
     registered probe), and is defense-in-depth'd by every layer below.
  2. ARGV VALIDATION. argv[0]'s basename must be in ``ALLOWED_EXECUTABLES`` (a small
     set of read-only test/benchmark runners); every token is scanned for shell
     metacharacters and obvious mutation signals (``bob``, ``git commit/push/add``,
     redirects, ``rm``/``mv``) — a match is REFUSED before anything runs.
  3. OS SANDBOX (best-effort, tiered): ``bubblewrap`` / ``firejail`` read-only bind
     when present + functional -> a write is PREVENTED (EROFS). Absent -> the
     snapshot tier below is the guarantee.
  4. WRITE-DETECTION (ALWAYS-ON containment): the project's ``git status --porcelain``
     (+ ``HEAD``) is snapshotted BEFORE and AFTER; ANY new delta -> the run is marked
     ``tainted_write_detected`` and its output is VOIDED (``admissible: false``), so a
     probe that writes cannot smuggle poisoned output into the docket. Because the
     snapshot is a BEFORE/AFTER DIFF, it is correct even when the working tree is
     already dirty — the guarantee is "no NEW git-visible change attributable to the
     run", which is precisely success-criterion #5 ("no writes; git status --short
     clean after").
  5. TIME-BOX. a hard timeout kills the WHOLE process group (start_new_session +
     killpg) — a probe cannot outlive its budget or orphan children.
  6. OUTPUT BUDGET. stdout/stderr are tail-truncated to a byte budget (results are
     DATA, not a transcript) and handed to the seat JSON-escaped behind the untrusted
     warning; instruction-looking text in probe output is DATA, reported-not-obeyed.

Hardened after the WP-4 adversarial security pass (agy, 2026-07-13):
  * FAIL-CLOSED containment — a run is admissible ONLY if it had PREVENTION (an OS
    sandbox read-only bind) OR DETECTION (git write-detection available AND clean). A
    run with NEITHER (snapshot tier on a NON-git root) is NOT admitted (closes the
    non-git fail-open). A post-run git snapshot that FAILS when the pre-run one
    succeeded is treated as TAINTED (possible ``.git`` tampering to blind the detector)
    — never silently "no change". The result carries a `containment` field.
  * argv[0] must be a BARE name resolved from PATH (a basename-only check is
    bypassable via ``/tmp/python``).
  * ``npx``/``deno`` removed from the allowlist (they fetch-and-execute arbitrary
    remote packages).
  * the runner's OWN git calls run under a scrubbed env (no ``GIT_EXTERNAL_DIFF`` /
    ``GIT_PAGER`` command execution).
  * the probe's process group is swept after BOTH the normal and timeout paths (a
    daemonized grandchild reap; bwrap's PID namespace already handles this).

Residual (NOT denied — honest, mirroring references/trust-boundary.md):
  * On a host with NO functional bwrap/firejail (snapshot tier), a probe CAN write
    during its run; the detector CONTAINS a NET git-visible change (detects + VOIDS)
    but a WRITE-THEN-RESTORE that leaves the tree byte-identical, or a write to a
    GITIGNORED path (``.pytest_cache/``, ``node_modules/``), is not a net git-visible
    mutation. bwrap (the tier on this host) PREVENTS all of these; ``no:cacheprovider``
    + ``PYTHONDONTWRITEBYTECODE`` reduce gitignored churn.
  * The mutation-signal regex is a defense-in-depth SIGNAL, not the containment — an
    interpreter (``python -c``) can obfuscate a mutation past it, but the actual write
    is still caught by porcelain-detection (or a commit by the HEAD-change detector) or
    PREVENTED by the sandbox.
  * ``firejail`` (best-effort tier) read-only-binds the repo + ``--net=none`` +
    private-tmp, but does not read-only the whole host FS the way bwrap does; git
    write-detection still catches in-repo mutations. bwrap is the strong tier.
  * A probe is arbitrary code within its allowlisted runner — the registry-only seat
    boundary + the argv allowlist keep an INJECTED seat from CHOOSING that code; a
    genuinely trusted-but-buggy registered probe is out of scope (the caller vouches).
  * Fence-break / prompt-injection in probe OUTPUT is neutralized at the RENDER layer
    (seat_prompt.render_evidence_runs JSON-escapes the whole record, exactly like peer
    records / reference materials) — evidence_run.py captures raw bytes by design.

Dependencies: Python stdlib ONLY (subprocess/os/signal/shutil — machine state only;
no PyYAML, no network). Executes ONLY the allowlisted argv it is handed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# The HARD-RULE, verbatim (design §6 / global avengers non-mutating charter). It is
# a module constant so callers/tests can assert it survives byte-for-byte.
# --------------------------------------------------------------------------- #
HARD_RULE = (
    "avengers is NON-MUTATING: evidence_run runs a read-only, sandboxed, time-boxed "
    "probe and returns its output as UNTRUSTED DATA. It NEVER writes to the project "
    "tree, NEVER commits, NEVER spawns bob, NEVER signs a contract map."
)

DEFAULT_TIMEOUT_S = 300
DEFAULT_OUTPUT_BYTE_BUDGET = 4000  # per stream, tail-kept

# Read-only test/benchmark runners a probe may invoke. argv[0] must be a BARE name
# (no path separator — the basename-only check is bypassable via `/tmp/python`, so we
# require a bare name resolved from PATH) IN this set. This is a TRUSTED allowlist
# (not seat-supplied). Shell interpreters (sh/bash/zsh) and recipe runners (make) are
# DELIBERATELY excluded — they re-open the arbitrary-command surface the no-shell
# control just closed. `npx`/`deno` are excluded too: they FETCH-AND-EXECUTE arbitrary
# remote packages (an out-of-band arbitrary-code path even past the no-shell control).
ALLOWED_EXECUTABLES = frozenset({
    "python", "python3", "pytest", "py.test",
    "node",
    "go", "cargo",
})

# Tokens that signal a mutation / bob-spawn attempt. Scanned across the joined argv as
# a defense-in-depth INJECTION SIGNAL (the sandbox + write-detection are the real
# containment; this makes an obvious attempt a hard, logged refusal).
_MUTATION_SIGNAL_RE = re.compile(
    r"(?:^|[\s/])(?:bob)(?:$|[\s])"
    r"|git\s+(?:commit|push|add|reset|checkout|stash|rm|clean|merge|rebase)"
    r"|\brm\b|\bmv\b|\btee\b|\btruncate\b|\bdd\b|>>|(?<![0-9])>(?!=)",
    re.IGNORECASE,
)
# Shell metacharacters — even with shell=False these have no legitimate place in a
# read-only-probe argv token; their presence is treated as an injection attempt.
_SHELL_METACHAR_RE = re.compile(r"[;&|`\n\r]|\$\(|\$\{|<\(|>\(")


class ProbeRefused(Exception):
    """A probe request was refused BEFORE execution (validation / gate failure).
    Nothing ran, nothing was written — the HARD-RULE holds trivially."""


# --------------------------------------------------------------------------- #
# argv validation
# --------------------------------------------------------------------------- #
def validate_argv(argv: Sequence[str], *, allow_executables: frozenset = ALLOWED_EXECUTABLES) -> List[str]:
    """Validate an explicit probe argv. Returns the normalized list or raises
    ProbeRefused. Enforces: non-empty list of strings; argv[0] basename in the
    allowlist; no shell metacharacters; no mutation/bob-spawn signal."""
    if not isinstance(argv, (list, tuple)) or not argv:
        raise ProbeRefused("probe argv must be a non-empty list")
    if not all(isinstance(tok, str) and tok != "" for tok in argv):
        raise ProbeRefused("probe argv must be a list of non-empty strings")
    raw0 = str(argv[0])
    # Require a BARE executable name resolved from PATH — a basename-only check is
    # bypassable ('/tmp/python' has basename 'python' but runs an attacker binary).
    if os.sep in raw0 or (os.altsep and os.altsep in raw0):
        raise ProbeRefused(
            f"probe executable must be a bare name resolved from PATH, not a path: {raw0!r}"
        )
    if raw0 not in allow_executables:
        raise ProbeRefused(
            f"executable {raw0!r} not in the read-only-probe allowlist {sorted(allow_executables)}"
        )
    joined = " ".join(argv)
    if _SHELL_METACHAR_RE.search(joined):
        raise ProbeRefused(f"shell metacharacter in probe argv (no-shell control): {joined!r}")
    if _MUTATION_SIGNAL_RE.search(joined):
        raise ProbeRefused(
            f"mutation / bob-spawn signal in probe argv (avengers is non-mutating): {joined!r}"
        )
    return [str(tok) for tok in argv]


# --------------------------------------------------------------------------- #
# Sandbox tiering (best-effort OS-level prevention)
# --------------------------------------------------------------------------- #
_BWRAP_WORKS_CACHE: Optional[bool] = None
_FIREJAIL_WORKS_CACHE: Optional[bool] = None


def _bwrap_works() -> bool:
    """True iff bubblewrap is present AND functional (user namespaces enabled). A
    binary can exist while userns is disabled, so we actually launch /bin/true under
    a minimal read-only bind and check rc==0. Cached (deterministic per process)."""
    global _BWRAP_WORKS_CACHE
    if _BWRAP_WORKS_CACHE is not None:
        return _BWRAP_WORKS_CACHE
    ok = False
    if shutil.which("bwrap"):
        try:
            r = subprocess.run(
                ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                 "--tmpfs", "/tmp", "--unshare-all", "--die-with-parent", "--", "/bin/true"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
            )
            ok = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
    _BWRAP_WORKS_CACHE = ok
    return ok


def _firejail_works() -> bool:
    global _FIREJAIL_WORKS_CACHE
    if _FIREJAIL_WORKS_CACHE is not None:
        return _FIREJAIL_WORKS_CACHE
    ok = False
    if shutil.which("firejail"):
        try:
            r = subprocess.run(
                ["firejail", "--quiet", "--net=none", "--private-tmp", "--", "/bin/true"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
            )
            ok = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
    _FIREJAIL_WORKS_CACHE = ok
    return ok


def select_sandbox_tier(prefer: str = "auto") -> str:
    """Return the active sandbox tier: 'bwrap' | 'firejail' | 'snapshot'.

    'snapshot' means NO OS prevention layer — write-detection (git diff) is the
    containment guarantee. `prefer='none'` forces 'snapshot' (used to test the
    portable containment path deterministically); `prefer='bwrap'`/`'firejail'`
    require that tier to be functional (else raise ProbeRefused)."""
    if prefer in ("none", "snapshot"):
        return "snapshot"
    if prefer == "bwrap":
        if _bwrap_works():
            return "bwrap"
        raise ProbeRefused("bwrap sandbox requested but not functional on this host")
    if prefer == "firejail":
        if _firejail_works():
            return "firejail"
        raise ProbeRefused("firejail sandbox requested but not functional on this host")
    # auto: strongest available prevention layer, else snapshot containment.
    if _bwrap_works():
        return "bwrap"
    if _firejail_works():
        return "firejail"
    return "snapshot"


def _wrap_for_sandbox(argv: List[str], tier: str, project_root: Path) -> List[str]:
    """Wrap argv in the OS sandbox for `tier`. 'snapshot' returns argv unchanged (no
    OS layer; write-detection is the guarantee). The read-only bind covers the whole
    filesystem; only a private tmpfs /tmp is writable and the network is unshared."""
    if tier == "bwrap":
        pr = str(project_root)
        return [
            "bwrap",
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            # Re-expose project_root READ-ONLY on top of the tmpfs so a project tree
            # that lives under /tmp is still visible (else --chdir lands nowhere);
            # a re-bind of a non-/tmp root is a harmless ro-on-ro. Writes to it still
            # EROFS (prevention preserved); /tmp stays writable scratch.
            "--ro-bind", pr, pr,
            "--unshare-all",
            "--die-with-parent",
            "--chdir", pr,
            "--", *argv,
        ]
    if tier == "firejail":
        return [
            "firejail", "--quiet",
            f"--read-only={project_root}",
            "--net=none",
            "--private-tmp",
            "--", *argv,
        ]
    return argv


# --------------------------------------------------------------------------- #
# Write-detection (always-on containment) — git porcelain BEFORE/AFTER diff
# --------------------------------------------------------------------------- #
def _git_env() -> Dict[str, str]:
    """A scrubbed environment for the runner's OWN git calls: neutralize the git
    hooks that would let an attacker-controlled env execute a command during a plain
    `status`/`rev-parse` (GIT_EXTERNAL_DIFF, GIT_PAGER, GIT_SSH, system config/attrs)."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "GIT_PAGER": "cat",
        "GIT_EXTERNAL_DIFF": "",
        "GIT_SSH_COMMAND": "",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
    }


def _git(project_root: Path, *args: str, timeout: int = 30) -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", "-C", str(project_root), *args],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=timeout,
            env=_git_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def git_snapshot(project_root: Path) -> Optional[Dict[str, Any]]:
    """Snapshot the git-visible state of the working tree: the full `git status
    --porcelain` set plus HEAD. None when project_root is not a git repo (the
    caller then has no write-detection guarantee and must rely on an OS sandbox)."""
    porcelain = _git(project_root, "status", "--porcelain")
    head = _git(project_root, "rev-parse", "HEAD")
    if porcelain is None:
        return None
    return {
        "porcelain_lines": sorted(l for l in porcelain.splitlines() if l.strip()),
        "head": (head or "").strip(),
    }


def mutation_delta(before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Compare two git snapshots. Returns None when there is NO new git-visible change
    attributable to the run, else a summary of what changed (new porcelain lines +
    any HEAD move — a HEAD move means a commit happened, e.g. a bob-spawn attempt)."""
    if before is None or after is None:
        return None
    new_lines = [l for l in after["porcelain_lines"] if l not in set(before["porcelain_lines"])]
    head_changed = before["head"] != after["head"]
    if not new_lines and not head_changed:
        return None
    return {
        "new_porcelain_lines": new_lines,
        "head_before": before["head"],
        "head_after": after["head"],
        "head_changed": head_changed,
    }


# --------------------------------------------------------------------------- #
# Output budgeting
# --------------------------------------------------------------------------- #
def _tail_bytes(text: str, byte_budget: int) -> Tuple[str, bool]:
    """Keep the TAIL of `text` within `byte_budget` UTF-8 bytes (the tail usually
    carries the summary / failing assertions). Returns (kept_text, truncated)."""
    if text is None:
        return "", False
    raw = text.encode("utf-8")
    if len(raw) <= byte_budget:
        return text, False
    kept = raw[-byte_budget:].decode("utf-8", errors="replace")
    return kept, True


def _hardened_env(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """A minimal, hardened environment for the probe subprocess: keep just enough to
    resolve + run a test/benchmark, discourage in-repo cache writes, and disable any
    interactive git prompting."""
    src = base if base is not None else os.environ
    return {
        "PATH": src.get("PATH", "/usr/bin:/bin"),
        "HOME": src.get("HOME", "/tmp"),
        "LANG": src.get("LANG", "C.UTF-8"),
        "LC_ALL": src.get("LC_ALL", src.get("LANG", "C.UTF-8")),
        "TERM": "dumb",
        "TMPDIR": "/tmp",  # writable scratch inside the sandbox (tmpfs under bwrap)
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTEST_ADDOPTS": "-p no:cacheprovider",
        "GIT_TERMINAL_PROMPT": "0",
    }


# --------------------------------------------------------------------------- #
# The core primitive
# --------------------------------------------------------------------------- #
def run_probe(
    argv: Sequence[str],
    *,
    project_root: Any,
    probe_id: Optional[str] = None,
    requested_by: Optional[str] = None,
    rationale: Optional[str] = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    output_byte_budget: int = DEFAULT_OUTPUT_BYTE_BUDGET,
    sandbox: str = "auto",
    allow_executables: frozenset = ALLOWED_EXECUTABLES,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run ONE read-only, sandboxed, time-boxed probe and return a DATA record.

    `argv` is an EXPLICIT command (TRUSTED caller path). For a seat-originated
    request use `run_requested_evidence` (probe_id-only; never a raw argv).

    The returned dict is the evidence record injected — via
    seat_prompt.render_evidence_runs — as fenced UNTRUSTED DATA. Key fields:
      status                 : refused | completed | timeout | error
      exit_code              : int | None
      timed_out              : bool
      sandbox_tier           : bwrap | firejail | snapshot
      write_detection        : porcelain-diff | unavailable
      containment            : prevention | detection | none | compromised
      tainted_write_detected : bool  (a NEW git-visible change happened)
      mutation_summary       : dict | None
      admissible             : bool  (False iff tainted OR no containment — voided)
      hard_rule_held         : bool  (False iff a mutation was detected)
      stdout_tail/stderr_tail: str   (tail-truncated, UNTRUSTED DATA)

    FAIL-CLOSED containment (hardened after the WP-4 adversarial pass): a run is
    admissible ONLY if it had PREVENTION (an OS sandbox read-only bind) OR DETECTION
    (git write-detection available AND clean). A run with NEITHER (snapshot tier on a
    non-git root) is NOT admitted. A post-run git snapshot that FAILS when the pre-run
    one succeeded (possible .git tampering) is treated as TAINTED under the snapshot
    tier — never silently 'no change'.

    Never raises for an execution failure (a failing suite IS the evidence); only a
    pre-exec validation/gate problem is reported as status 'refused' (or 'error' for
    an environment problem like a missing executable). NEVER writes to project_root."""
    project_root = Path(project_root)
    base: Dict[str, Any] = {
        "kind": "evidence_run",
        "probe_id": probe_id,
        "argv": list(argv) if isinstance(argv, (list, tuple)) else [str(argv)],
        "requested_by": requested_by,
        "rationale": rationale,
        "sandbox_tier": None,
        "write_detection": None,
        "containment": None,
        "exit_code": None,
        "timed_out": False,
        "duration_s": 0.0,
        "stdout_tail": "",
        "stderr_tail": "",
        "output_truncated": False,
        "tainted_write_detected": False,
        "mutation_summary": None,
        "admissible": False,
        "hard_rule_held": True,
        "status": "refused",
        "error": None,
        "hard_rule": HARD_RULE,
    }

    # 1. Validate argv + resolve the sandbox tier (both fail-closed, pre-exec).
    try:
        norm_argv = validate_argv(argv, allow_executables=allow_executables)
        tier = select_sandbox_tier(sandbox)
    except ProbeRefused as e:
        base["error"] = str(e)
        base["status"] = "refused"
        # nothing ran -> the HARD-RULE held, but there is no admissible evidence.
        base["hard_rule_held"] = True
        base["admissible"] = False
        return base
    base["argv"] = norm_argv
    base["sandbox_tier"] = tier

    # 2. Snapshot git BEFORE (write-detection containment). Unavailable => no
    #    porcelain guarantee; we then rely on the OS sandbox tier alone.
    before = git_snapshot(project_root)
    base["write_detection"] = "porcelain-diff" if before is not None else "unavailable"

    wrapped = _wrap_for_sandbox(norm_argv, tier, project_root)
    run_env = env if env is not None else _hardened_env()

    # 3. Execute time-boxed, in its own process group so a timeout kills children.
    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            wrapped, cwd=str(project_root), env=run_env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
    except FileNotFoundError as e:
        base["status"] = "error"
        base["error"] = f"probe executable not found: {e}"
        base["admissible"] = False
        return base
    except OSError as e:  # pragma: no cover - environment dependent
        base["status"] = "error"
        base["error"] = f"probe failed to start: {e}"
        base["admissible"] = False
        return base

    try:
        out, err = proc.communicate(timeout=timeout_s)
        base["exit_code"] = proc.returncode
        base["status"] = "completed"
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        out, err = proc.communicate()
        base["timed_out"] = True
        base["exit_code"] = None
        base["status"] = "timeout"
    finally:
        # Sweep any stragglers (daemonized grandchildren) after BOTH paths — the
        # session leader's pgid == its pid (start_new_session). Under bwrap the PID
        # namespace + --die-with-parent already reaps the whole tree; this is the
        # snapshot-tier belt-and-braces. Best-effort.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    base["duration_s"] = round(time.monotonic() - start, 3)

    st, st_trunc = _tail_bytes(out or "", output_byte_budget)
    se, se_trunc = _tail_bytes(err or "", output_byte_budget)
    base["stdout_tail"] = st
    base["stderr_tail"] = se
    base["output_truncated"] = st_trunc or se_trunc

    # 4. Snapshot git AFTER + decide CONTAINMENT (fail-closed). A run is admissible
    #    ONLY with PREVENTION (an OS sandbox read-only bind) or DETECTION (git
    #    write-detection available AND clean). Neither => not admitted.
    prevention = tier in ("bwrap", "firejail")
    after = git_snapshot(project_root)
    delta = mutation_delta(before, after)
    post_run_git_lost = before is not None and after is None

    if delta is not None:
        # A NEW git-visible change happened during the run -> contained by detection.
        base["tainted_write_detected"] = True
        base["mutation_summary"] = delta
        base["hard_rule_held"] = False
        base["admissible"] = False  # poisoned output is VOIDED at render time
        base["containment"] = "detection"
    elif post_run_git_lost and not prevention:
        # git was readable BEFORE but not AFTER, with no OS prevention: the probe may
        # have tampered with .git to blind the detector. Cannot verify cleanliness ->
        # FAIL CLOSED (never silently 'no change').
        base["tainted_write_detected"] = True
        base["mutation_summary"] = {"post_run_git_snapshot_failed": True,
                                    "note": "git state unreadable after run (possible .git tampering)"}
        base["hard_rule_held"] = False
        base["admissible"] = False
        base["containment"] = "compromised"
        base["error"] = base.get("error") or "git state unreadable after run — fail-closed"
    else:
        base["tainted_write_detected"] = False
        base["hard_rule_held"] = True
        if prevention:
            base["containment"] = "prevention"
        elif before is not None and after is not None:
            base["containment"] = "detection"
        else:
            base["containment"] = "none"
        if base["containment"] == "none":
            # NEITHER OS prevention NOR git write-detection (e.g. snapshot tier on a
            # non-git root) -> no containment at all -> do NOT admit unguarded evidence.
            base["admissible"] = False
            base["error"] = base.get("error") or (
                "no containment: OS sandbox unavailable AND git write-detection "
                "unavailable (non-git project root?) — evidence not admitted (fail-closed)"
            )
        else:
            # Admissible iff the run actually produced evidence (completed / timeout);
            # a hard error produced no usable evidence.
            base["admissible"] = base["status"] in ("completed", "timeout")
    return base


def _kill_group(proc: "subprocess.Popen") -> None:
    """Kill the probe's whole process group (SIGTERM then SIGKILL). Best-effort."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            return
        try:
            proc.wait(timeout=2)
            return
        except subprocess.TimeoutExpired:
            continue


# --------------------------------------------------------------------------- #
# Seat-facing gate — probe_id ONLY, resolved from a TRUSTED registry
# --------------------------------------------------------------------------- #
# A shipped default probe registry. TRUSTED config: a seat may name one of these by
# id; it can NEVER supply a raw argv. Projects extend it via the profile's
# `evidence.probes` map (merged by convene into the plan's evidence_policy).
DEFAULT_PROBE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "avengers-selftest": {
        "description": "the avengers pytest suite (read-only self-test)",
        "argv": ["python3", "-m", "pytest", "-q", "skills/avengers/tests"],
    },
}


def registry_argv(registry: Dict[str, Any], probe_id: str) -> List[str]:
    """Resolve a probe_id to a validated argv from the TRUSTED registry. Fail-closed:
    unknown id or a malformed/mutating registry entry raises ProbeRefused."""
    if not isinstance(registry, dict) or probe_id not in registry:
        raise ProbeRefused(
            f"probe_id {probe_id!r} not in the trusted registry {sorted(registry) if isinstance(registry, dict) else registry!r}"
        )
    entry = registry[probe_id]
    argv = entry.get("argv") if isinstance(entry, dict) else None
    if not argv:
        raise ProbeRefused(f"registry entry {probe_id!r} has no argv")
    # A registry entry is trusted config but still passes the same argv guard — a
    # mis-authored (mutating) registry entry must not slip a mutation through.
    return validate_argv(argv)


def run_requested_evidence(
    request: Dict[str, Any],
    *,
    registry: Dict[str, Any],
    project_root: Any,
    phase: Optional[str] = None,
    allowed_phases: Optional[Sequence[str]] = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    output_byte_budget: int = DEFAULT_OUTPUT_BYTE_BUDGET,
    sandbox: str = "auto",
) -> Dict[str, Any]:
    """The SEAT-facing entry point. `request` is UNTRUSTED (it originates inside the
    deliberation): it may carry ONLY {probe_id, requested_by, rationale}. A raw
    `argv`/`cmd` in the request is IGNORED and REFUSED — a seat cannot choose the
    command; it can only name a probe the trusted registry already blesses. The
    probe_id is resolved to a validated argv and run under `run_probe`.

    `allowed_phases` gates WHICH phases may request evidence (the phase machine
    wiring — DOCKET / CROSS_EXAM by default; a blind-diverge request is refused)."""
    probe_id = (request or {}).get("probe_id")
    requested_by = (request or {}).get("requested_by")
    rationale = (request or {}).get("rationale")

    def _refusal(msg: str) -> Dict[str, Any]:
        return {
            "kind": "evidence_run", "probe_id": probe_id, "argv": [],
            "requested_by": requested_by, "rationale": rationale,
            "status": "refused", "error": msg, "admissible": False,
            "hard_rule_held": True, "tainted_write_detected": False,
            "hard_rule": HARD_RULE,
        }

    # A seat MUST NOT be able to supply a command. Reject any raw-argv smuggling.
    if any(k in (request or {}) for k in ("argv", "cmd", "command", "shell")):
        return _refusal("seat requests may reference a probe_id ONLY, never a raw command")
    if not probe_id:
        return _refusal("evidence request missing probe_id")
    if allowed_phases is not None and phase is not None and phase not in set(allowed_phases):
        return _refusal(
            f"evidence_run not permitted in phase {phase!r} (allowed: {sorted(set(allowed_phases))})"
        )
    try:
        argv = registry_argv(registry, probe_id)
    except ProbeRefused as e:
        return _refusal(str(e))
    return run_probe(
        argv, project_root=project_root, probe_id=probe_id,
        requested_by=requested_by, rationale=rationale,
        timeout_s=timeout_s, output_byte_budget=output_byte_budget, sandbox=sandbox,
    )


# --------------------------------------------------------------------------- #
# CLI (the chair / a test harness runs a probe and prints the JSON record)
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="avengers evidence_run (WP-4): sandboxed, read-only, time-boxed probe -> UNTRUSTED DATA record"
    )
    ap.add_argument("--project-root", type=Path, default=Path.cwd(),
                    help="the git repo the probe runs against (write-detection anchor)")
    ap.add_argument("--probe-id", help="resolve argv from the trusted registry (seat-facing path)")
    ap.add_argument("--registry", type=Path, default=None,
                    help="optional JSON file: {probe_id: {argv:[...]}} (defaults to the shipped registry)")
    ap.add_argument("--requested-by", default=None, help="the seat that requested this probe")
    ap.add_argument("--rationale", default=None, help="why this probe was requested (docket note)")
    ap.add_argument("--phase", default=None, help="current phase (gated by --allowed-phase)")
    ap.add_argument("--allowed-phase", action="append", default=None,
                    help="repeatable; restrict evidence requests to these phases")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="hard time-box in seconds")
    ap.add_argument("--output-budget", type=int, default=DEFAULT_OUTPUT_BYTE_BUDGET,
                    help="per-stream tail byte budget for captured output")
    ap.add_argument("--sandbox", default="auto", choices=["auto", "bwrap", "firejail", "none"],
                    help="OS sandbox tier ('none' forces the snapshot containment path)")
    ap.add_argument("cmd", nargs="*", help="explicit probe argv (TRUSTED path; mutually exclusive with --probe-id)")
    args = ap.parse_args(argv)

    registry = DEFAULT_PROBE_REGISTRY
    if args.registry is not None:
        try:
            registry = json.loads(args.registry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            sys.stderr.write(f"evidence_run: bad registry file: {e}\n")
            return 2

    if args.probe_id:
        result = run_requested_evidence(
            {"probe_id": args.probe_id, "requested_by": args.requested_by, "rationale": args.rationale},
            registry=registry, project_root=args.project_root,
            phase=args.phase, allowed_phases=args.allowed_phase,
            timeout_s=args.timeout, output_byte_budget=args.output_budget, sandbox=args.sandbox,
        )
    elif args.cmd:
        result = run_probe(
            args.cmd, project_root=args.project_root,
            requested_by=args.requested_by, rationale=args.rationale,
            timeout_s=args.timeout, output_byte_budget=args.output_budget, sandbox=args.sandbox,
        )
    else:
        sys.stderr.write("evidence_run: pass --probe-id <id> or an explicit -- <argv>\n")
        return 2

    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    # Exit 0 when the run itself is well-formed evidence (even a failing suite);
    # non-zero only when the probe was REFUSED / errored / a mutation was detected.
    if result.get("status") in ("refused", "error") or result.get("tainted_write_detected"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
