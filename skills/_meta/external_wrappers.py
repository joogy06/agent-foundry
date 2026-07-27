#!/usr/bin/env python3
"""external_wrappers.py — shared helper for wrapping external-tool subprocess calls.

Public API (Contract 4 in `.forge/contracts.md`):

    run_with_observation(
        cmd: list[str], *, timeout: int = 600,
        subject_id: str, fingerprint_on_error: str = "returncode",
        **kwargs,
    ) -> subprocess.CompletedProcess
        Runs `subprocess.run(cmd, timeout=timeout, capture_output=True, text=True, **kwargs)`.
        Emits `external_tool_fail` observation BEFORE returning on non-zero exit.
        Emits `external_tool_slow` observation BEFORE re-raising subprocess.TimeoutExpired.
        Returns CompletedProcess on success (no observation on returncode == 0).

    emit_malformed(subject_id: str, excerpt: str) -> None
        Helper for callers who do their own parsing: emits
        `external_tool_fail` with fingerprint=`malformed_output` when tool output
        is unparseable JSON/YAML/etc. Fail-open (never raises).

Fail-open policy:
    - The `from process_observation.scripts.write import claude_observe`
      import is wrapped in try/except ImportError at module load time.
      If the process-observation skill is missing, `claude_observe` is
      replaced with a no-op stub so the PRIMARY subprocess call still runs.
    - Observation emission is defensively wrapped in try/except at every
      call site (defense-in-depth on top of claude_observe's own
      BEST-EFFORT semantics) so observation-write failure NEVER blocks
      the primary subprocess call nor the re-raise of TimeoutExpired.

Consumers (future cycles): codex-orchestration, antigravity-cli, gh-copilot-cli
scripts migrate from raw `subprocess.run` to `run_with_observation` so that
external-tool failures/slowness feed the process-observation ledger.

Design refs:
    docs/plans/2026-04-23-ecosystem-keystone-design.md §5.9
    progress/contract-map.yaml `external-wrappers` component
    .forge/contracts.md Contract 4
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Fail-open import of claude_observe
# ---------------------------------------------------------------------------
#
# Path layout:
#   ~/.claude/skills/_meta/external_wrappers.py          (this file)
#   ~/.claude/skills/process-observation/scripts/write.py (claude_observe)
#
# The process-observation scripts directory is added to sys.path so
# `from write import claude_observe` resolves without requiring callers to
# configure PYTHONPATH. If process-observation is missing altogether,
# `claude_observe` is replaced with a no-op stub so the primary subprocess
# call still runs.

_PROCESS_OBSERVATION_SCRIPTS = (
    Path(__file__).resolve().parent.parent / "process-observation" / "scripts"
)
if _PROCESS_OBSERVATION_SCRIPTS.is_dir():
    _po_path_str = str(_PROCESS_OBSERVATION_SCRIPTS)
    if _po_path_str not in sys.path:
        sys.path.insert(0, _po_path_str)

try:
    from write import claude_observe  # type: ignore[import-not-found]
except ImportError:
    # Fail-open: no observation system available. Replace with a no-op stub
    # so the primary subprocess call still runs.
    def claude_observe(*args, **kwargs) -> None:  # type: ignore[misc]
        return None


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _safe_observe(*args, **kwargs) -> None:
    """Call `claude_observe` defensively so observation failure never raises.

    Defense-in-depth on top of claude_observe's own BEST-EFFORT semantics —
    the module-level stub is already a no-op, but if the real implementation
    were partially broken we still must not propagate exceptions to the
    caller of run_with_observation/emit_malformed.
    """
    try:
        claude_observe(*args, **kwargs)
    except BaseException as e:  # noqa: BLE001 — swallow absolutely everything
        sys.stderr.write(
            f"EXTERNAL_WRAPPERS_OBSERVE_FAIL: {type(e).__name__}: {e}\n"
        )
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_with_observation(
    cmd: list,
    *,
    timeout: int = 600,
    subject_id: str,
    fingerprint_on_error: str = "returncode",
    **kwargs,
) -> subprocess.CompletedProcess:
    """Run an external tool subprocess and emit observations on failure/timeout.

    Policy:
      - On returncode == 0: return CompletedProcess (no observation).
      - On returncode != 0: emit `external_tool_fail` BEFORE returning,
        with fingerprint `f"{fingerprint_on_error}-{returncode}"` and
        what_happened describing cmd + returncode + tail of stderr.
      - On subprocess.TimeoutExpired: emit `external_tool_slow` BEFORE
        re-raising, with fingerprint `f"timeout-{timeout}s"`.

    Security / hygiene:
      - Never passes `shell=True` by default. Does NOT mutate `cmd`.

    Fail-open:
      - Observation emission is defensively wrapped so it cannot block
        the primary control flow (return of CompletedProcess or
        re-raise of TimeoutExpired).

    Args:
        cmd: subprocess argv list (list[str]); NOT mutated.
        timeout: seconds before subprocess.TimeoutExpired is raised.
        subject_id: observation subject (e.g. "codex", "gemini", "gh-copilot").
        fingerprint_on_error: template prefix for observation fingerprint on
            non-zero exit; concatenated with `-{returncode}`. Defaults to
            "returncode".
        **kwargs: forwarded to subprocess.run (e.g. env, cwd).

    Returns:
        subprocess.CompletedProcess. Caller decides policy based on
        returncode/stderr — we only observe, never re-interpret.

    Raises:
        subprocess.TimeoutExpired: re-raised AFTER observation emission.
    """
    # Default subprocess.run options; caller may override via **kwargs.
    run_kwargs = {"capture_output": True, "text": True}
    run_kwargs.update(kwargs)
    try:
        result = subprocess.run(cmd, timeout=timeout, **run_kwargs)
    except subprocess.TimeoutExpired:
        # Emit observation BEFORE re-raising so callers that only log the
        # exception still get the observation written.
        _safe_observe(
            "external_tool_slow",
            subject_id=subject_id,
            what_happened=f"{subject_id} exceeded {timeout}s running {cmd!r}",
            fingerprint=f"timeout-{timeout}s",
            subject_type="external_tool",
        )
        raise

    if result.returncode != 0:
        # stderr may be None when capture_output is disabled via kwargs.
        stderr_tail = ""
        if result.stderr:
            # Tail to at most 200 chars so the aggregate `what_happened`
            # field stays bounded; fingerprint carries the dedup signal.
            stderr_tail = str(result.stderr)[-200:]
        _safe_observe(
            "external_tool_fail",
            subject_id=subject_id,
            what_happened=(
                f"{subject_id} exit {result.returncode} running {cmd!r}: "
                f"{stderr_tail}"
            ),
            fingerprint=f"{fingerprint_on_error}-{result.returncode}",
            subject_type="external_tool",
        )
    return result


def emit_malformed(subject_id: str, excerpt: str) -> None:
    """Emit a `malformed_output` observation (helper for callers who parse).

    Use when a wrapped tool exited 0 but its stdout was unparseable
    (invalid JSON/YAML/etc.). The excerpt is truncated to the first
    200 chars so an enormous blob does not drown the aggregate field.

    Fail-open: observation emission failure is swallowed. Never raises.

    Args:
        subject_id: observation subject (e.g. "codex").
        excerpt: substring of the unparseable output; truncated to 200 chars.
    """
    truncated = (excerpt or "")[:200]
    _safe_observe(
        "external_tool_fail",
        subject_id=subject_id,
        what_happened=f"unparseable output: {truncated}",
        fingerprint="malformed_output",
        subject_type="external_tool",
    )


__all__ = ["run_with_observation", "emit_malformed", "claude_observe"]
