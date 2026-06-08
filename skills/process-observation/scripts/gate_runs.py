#!/usr/bin/env python3
"""
gate_runs.py - efficacy-telemetry gate-run denominator writer (S039 WP1).

Public API (importable; loaded by gates.py via a fail-open loader):

    bump_gate_run(gate) -> None
        BEST-EFFORT; never raises. Called PRE-dispatch in gates.py main(),
        before any sys.exit, to record one denominator tick per gate
        invocation. Establishes the denominator-window sentinel on first call.

    record_gate_outcome(gate, code) -> None
        BEST-EFFORT; never raises. Called from the try/except SystemExit in
        gates.py main(); records the RAW normalized exit code (int or None)
        the gate's SystemExit carried. Does NOT derive a label — the rollup
        classifies at read time (design §5/§6.1).

Why two helpers (design §7):
    The bump fires before dispatch so the denominator is correct even if the
    process is killed before the SystemExit is caught (that run lands in the
    denominator with code:null). The outcome fires after dispatch and carries
    the terminal exit code. ONE denominator record per invocation: the outcome
    write UPDATES the in-flight record's `code` field by appending the final
    record keyed on the same run_id is NOT used — instead the bump writes the
    record with code:null and the outcome appends a SECOND record with the
    same run_id carrying the real code; the rollup folds same-run_id records
    (last code wins, null if no outcome). This append-only design keeps the
    write path lock-free O_APPEND (crash-safe) and never mutates a prior line.

Persistence layout (sibling of the EXISTING friction ledger — never touches
active.yaml / events.jsonl, so the 13-category friction taxonomy alf consumes
is provably uncorrupted, design §4 constraint #5):

    <project_root>/.process-observations/
        gate-runs.jsonl     # NEW append-only denominator log
        .telemetry_window   # NEW sentinel: first-bump ISO timestamp

gate-runs.jsonl record shape (canonical-JSON line, lock-free O_APPEND like
events.jsonl):

    {"ts":"2026-06-03T10:00:00Z","gate":"G1","run_id":"<uuid4>","code":0}

`code` is the RAW normalized exit code (int) the SystemExit carried, or null
(a run whose process was killed before the try/except SystemExit caught a
terminal exit). The bump record carries code:null; the outcome record carries
the real code. Classification (fail = exit 2 only; 3 = advisory/env-error; 4 =
skip) happens at read time in the rollup (query.py rollup op), NOT here.

Design refs:
    docs/plans/2026-06-03-efficacy-telemetry-v1-design.md §5, §7
    Mirrors write.py O_APPEND + best-effort never-raise patterns.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Reuse write.py's project-root discovery + ISO clock so the two writers agree
# on layout. Import is package-local; gate_runs.py lives next to write.py.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    from write import discover_project_root as _discover_project_root  # noqa: E402
    from write import now_iso as _now_iso  # noqa: E402
    from write import append_event_line as _append_event_line  # noqa: E402
except Exception:  # pragma: no cover - last-resort standalone fallback
    def _now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _discover_project_root(start: Optional[Path] = None) -> Optional[Path]:
        p = (start or Path.cwd()).resolve()
        while True:
            if (p / ".process-observations").is_dir():
                return p
            if (p / "PROJECT.md").is_file():
                return p
            if (p / ".git").is_dir():
                return p
            if p.parent == p:
                return None
            p = p.parent

    def _append_event_line(path: Path, record: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = (
            json.dumps(record, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False) + "\n"
        ).encode("utf-8")
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)


GATE_RUNS_FILENAME = "gate-runs.jsonl"
WINDOW_SENTINEL_FILENAME = ".telemetry_window"

# Per-invocation run_id so the bump record and its later outcome record can be
# folded together by the rollup. Module-global because gates.py main() runs
# exactly one gate per process; both helpers fire within that one process.
_RUN_ID: Optional[str] = None


def _obs_dir(project_root: Path) -> Path:
    return project_root / ".process-observations"


def _resolve_root(project_root_override: Optional[Path]) -> Optional[Path]:
    if project_root_override is not None:
        return Path(project_root_override)
    return _discover_project_root()


def _ensure_window_sentinel(obs_dir: Path, ts: str) -> None:
    """Write `.telemetry_window` with the first-bump timestamp if absent.

    The sentinel records `denominator_window_start` (design §6/§9): every rate
    over a window predating this is understated, and the rollup surfaces the
    start so a too-young baseline is self-evident. Idempotent — never
    overwritten once present.
    """
    sentinel = obs_dir / WINDOW_SENTINEL_FILENAME
    if sentinel.is_file():
        return
    # O_CREAT|O_EXCL so a concurrent bump from another process cannot clobber
    # an already-established start. EEXIST is a no-op success.
    try:
        fd = os.open(str(sentinel), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return
    try:
        os.write(fd, (ts + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def read_window_start(project_root: Path) -> Optional[str]:
    """Return the denominator_window_start ISO string, or None if no bump yet.

    Read-only helper for the rollup. Never raises.
    """
    try:
        sentinel = _obs_dir(Path(project_root)) / WINDOW_SENTINEL_FILENAME
        if not sentinel.is_file():
            return None
        val = sentinel.read_text(encoding="utf-8").strip()
        return val or None
    except Exception:
        return None


def bump_gate_run(
    gate: str,
    *,
    project_root_override: Optional[Path] = None,
) -> None:
    """Record one denominator tick for `gate`. BEST-EFFORT; never raises.

    PRE-dispatch hook: writes a gate-run record with code:null and mints the
    per-invocation run_id. Establishes the window sentinel on first call. The
    ENTIRE body (including arg normalization) is wrapped in try/except
    BaseException so a broken backend cannot perturb the caller's exit code
    (design §7: claude_observe's never-raise guarantee protects only its own
    body, not the caller's arg-construction).
    """
    global _RUN_ID
    try:
        _RUN_ID = uuid.uuid4().hex
        root = _resolve_root(project_root_override)
        if root is None:
            # No project root -> nothing to write (denominator is per-project).
            return
        obs_dir = _obs_dir(root)
        obs_dir.mkdir(parents=True, exist_ok=True)
        ts = _now_iso()
        _ensure_window_sentinel(obs_dir, ts)
        record = {
            "ts": ts,
            "gate": str(gate),
            "run_id": _RUN_ID,
            "code": None,
        }
        _append_event_line(obs_dir / GATE_RUNS_FILENAME, record)
    except BaseException as e:  # noqa: BLE001
        try:
            sys.stderr.write(f"GATE_RUN_BUMP_FAIL: {type(e).__name__}: {e}\n")
        except BaseException:
            pass
        return None


def _normalize_exit_code(code: Any) -> Optional[int]:
    """Normalize a SystemExit.code (None | str | int) to int-or-None.

    SystemExit.code semantics (CPython):
      - None        -> process exit 0   -> 0
      - int         -> that exit code    -> int
      - str / other -> process exit 1    -> 1  (Python prints the str to
                       stderr and exits 1)
    """
    if code is None:
        return 0
    if isinstance(code, bool):
        # bool is an int subclass; True->1, False->0. Treat explicitly.
        return 1 if code else 0
    if isinstance(code, int):
        return code
    # Any non-int (str, object) -> Python exits 1.
    return 1


def record_gate_outcome(
    gate: str,
    code: Any,
    *,
    project_root_override: Optional[Path] = None,
) -> None:
    """Record the terminal exit code for the in-flight gate run.

    BEST-EFFORT; never raises. Called from the try/except SystemExit in
    gates.py main(); `code` is the SystemExit.code (None/str/int), normalized
    internally. Appends a SECOND record with the same run_id carrying the real
    code (rollup folds same-run_id: last non-null code wins). The ENTIRE body
    is wrapped in try/except BaseException (design §7).

    If no prior bump minted a run_id (defensive — shouldn't happen), a fresh
    run_id is minted so the outcome is still attributable.
    """
    global _RUN_ID
    try:
        normalized = _normalize_exit_code(code)
        root = _resolve_root(project_root_override)
        if root is None:
            return
        obs_dir = _obs_dir(root)
        obs_dir.mkdir(parents=True, exist_ok=True)
        run_id = _RUN_ID or uuid.uuid4().hex
        record = {
            "ts": _now_iso(),
            "gate": str(gate),
            "run_id": run_id,
            "code": normalized,
        }
        _append_event_line(obs_dir / GATE_RUNS_FILENAME, record)
    except BaseException as e:  # noqa: BLE001
        try:
            sys.stderr.write(f"GATE_RUN_OUTCOME_FAIL: {type(e).__name__}: {e}\n")
        except BaseException:
            pass
        return None
