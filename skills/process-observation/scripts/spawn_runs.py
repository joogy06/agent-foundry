#!/usr/bin/env python3
"""spawn_runs.py — observe-only cost/latency telemetry sidecar writer.

S046 / S039-review #124 (observe-only cost telemetry, v1).

Sibling of gate_runs.py. Where gate_runs.py records a denominator tick per gate
invocation, this records ONE line per cold-context verifier spawn (an
audit_spawn.py arm or a verification_arbiter_spawn.py run) capturing the
cost/latency the `claude -p --output-format json` envelope reported, plus the
correlation fields needed to later join a spawn to its cycle / component /
bundle / verification request.

Public API (importable; loaded by the spawners via a fail-open loader):

    record_spawn_run(*, tool, status, cost_usd, duration_ms, num_turns,
                     wall_clock_s, model=None, cycle_id=None, component_id=None,
                     bundle_hash=None, request_id=None, invocation_id=None,
                     project_root_override=None) -> None
        BEST-EFFORT; never raises. Appends one canonical-JSON line to
        spawn-runs.jsonl. A broken backend (ImportError, unwritable dir, full
        disk) cannot perturb the caller's return value or exit code — the
        ENTIRE body is wrapped in try/except BaseException (#124 null-safety
        contract; mirrors gate_runs.bump_gate_run / claude_observe).

Persistence layout (sibling of the EXISTING friction ledger + gate-runs
denominator — never touches active.yaml / events.jsonl / gate-runs.jsonl, so
neither the 13-category friction taxonomy nor the efficacy denominator alf
consumes is perturbed):

    <project_root>/.process-observations/
        spawn-runs.jsonl     # NEW append-only cost/latency log

spawn-runs.jsonl record shape (canonical-JSON line, lock-free O_APPEND like
events.jsonl / gate-runs.jsonl):

    {"ts":"2026-06-07T10:00:00Z","invocation_id":"<uuid4hex>","cycle_id":null,
     "component_id":"wiring-extract-static","bundle_hash":"<64hex|null>",
     "request_id":"<32hex|null>","tool":"verification_arbiter","model":"...",
     "status":"VERIFIED","cost_usd":0.0123,"duration_ms":4210,"num_turns":1,
     "wall_clock_s":4.4}

Field semantics:
  * ts            ISO-Z write time.
  * invocation_id per-spawn uuid4 (minted here if the caller doesn't supply one).
  * cycle_id      forge/bob cycle correlation (None until a cycle id is threaded;
                  the per-cycle rollup display tolerates None — see rollup.py).
  * component_id  contract-map component under verification (None for the audit
                  arm's combined call where it is still known; spawners pass it).
  * bundle_hash   the frozen evidence bundle hash (correlates to the dual-verdict
                  archive + ledger). NEVER the bundle bytes — just its hash.
  * request_id    the open verification request id (arbiter arm only; None for
                  the audit arm which is not request-bound).
  * tool          "audit_claude" | "audit_codex" | "verification_arbiter".
  * model         the model id the spawn used (best-effort; may be None).
  * status        the spawn's own outcome string (verdict or error sentinel) —
                  observe-only context, NOT a gate signal.
  * cost_usd / duration_ms / num_turns  from spawn_usage.extract_usage (any may
                  be None on a non-JSON / Codex / truncated path).
  * wall_clock_s  the spawner's own measured wall time for the arm (float).

Classification / aggregation (total_cost_usd, p50/p95 latency, summed
wall-clock) happens at READ time in the rollup (query.py rollup op), NOT here.
This writer is dumb on purpose.

Design refs:
    docs/plans/2026-06-07-s039-batch1-telemetry-rollback-lease-design.md §A, §G
    Mirrors gate_runs.py + write.py O_APPEND best-effort never-raise patterns.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Reuse write.py's project-root discovery + ISO clock + append helper so all
# three sidecar writers (events / gate-runs / spawn-runs) agree on layout.
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


SPAWN_RUNS_FILENAME = "spawn-runs.jsonl"

# Closed set of tool tags so the rollup can group cleanly. Not enforced (a new
# spawner can pass a new tag), but documented so callers stay consistent.
KNOWN_TOOLS = frozenset({"audit_claude", "audit_codex", "verification_arbiter"})


def _obs_dir(project_root: Path) -> Path:
    return project_root / ".process-observations"


def _resolve_root(project_root_override: Optional[Path]) -> Optional[Path]:
    if project_root_override is not None:
        return Path(project_root_override)
    return _discover_project_root()


def _coerce_num(value: Any) -> Optional[float]:
    """Pass numbers through, reject bool, coerce clean numeric strings, else
    None. Keeps the JSONL numeric-clean even if a caller hands us a stray type.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s) if ("." in s or "e" in s or "E" in s) else int(s)
        except ValueError:
            return None
    return None


def record_spawn_run(
    *,
    tool: str,
    status: Any,
    cost_usd: Any,
    duration_ms: Any,
    num_turns: Any,
    wall_clock_s: Any,
    model: Optional[str] = None,
    cycle_id: Optional[str] = None,
    component_id: Optional[str] = None,
    bundle_hash: Optional[str] = None,
    request_id: Optional[str] = None,
    invocation_id: Optional[str] = None,
    project_root_override: Optional[Path] = None,
) -> None:
    """Append one spawn-run record. BEST-EFFORT; never raises.

    All numeric fields are coerced null-safe (None stays None). The ENTIRE body
    is wrapped in try/except BaseException so a broken backend cannot perturb
    the caller's exit code (#124 / design §A — observe-only, never-raise).
    """
    try:
        root = _resolve_root(project_root_override)
        if root is None:
            # No project root -> nothing to write (telemetry is per-project).
            return
        obs_dir = _obs_dir(root)
        obs_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": _now_iso(),
            "invocation_id": invocation_id or uuid.uuid4().hex,
            "cycle_id": cycle_id,
            "component_id": component_id,
            "bundle_hash": bundle_hash,
            "request_id": request_id,
            "tool": str(tool),
            "model": model,
            "status": None if status is None else str(status),
            "cost_usd": _coerce_num(cost_usd),
            "duration_ms": _coerce_num(duration_ms),
            "num_turns": _coerce_num(num_turns),
            "wall_clock_s": _coerce_num(wall_clock_s),
        }
        _append_event_line(obs_dir / SPAWN_RUNS_FILENAME, record)
    except BaseException as e:  # noqa: BLE001
        try:
            sys.stderr.write(f"SPAWN_RUN_RECORD_FAIL: {type(e).__name__}: {e}\n")
        except BaseException:
            pass
        return None
