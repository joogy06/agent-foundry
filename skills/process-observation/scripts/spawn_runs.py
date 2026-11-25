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
                     requested_model=None, served_model=None, tokens=None,
                     quota_before=None, quota_after=None, quota_source=None,
                     role=None, env_override_refused=None,
                     substitute_for=None, substitution_reason=None, use=None,
                     served_model_usage=None, served_model_mismatch=None,
                     max_silence_s=None, stop_reason=None, exit_code=None,
                     idle_timeout_s=None, hard_cap_s=None,
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

OPTIONAL provenance / quota fields (S081 design §4.11, additive). Each key is
written ONLY when the caller passes a non-None value, so a row from a caller
that passes none of them has exactly the keys shown above (byte-shape
unchanged). Readers must treat every one of them as possibly absent.
  * requested_model       the model the spawner asked for (the pin).
  * served_model          the model the provider reported serving, when
                          observable (e.g. the codex banner, or — #282 R3 — the
                          `modelUsage` key of a `claude -p --output-format json`
                          envelope with the most output tokens); may differ.
  * served_model_usage    #282 R3: EVERY `modelUsage` key of a claude envelope
                          mapped to its outputTokens ({model id: N}), so a call
                          that used more than one model keeps all of them.
  * served_model_mismatch #282 R3: true when the requested alias is not a
                          dash-delimited token of served_model ("fable" matches
                          "claude-fable-5-1"). Present ONLY on a mismatch; a
                          mismatch is recorded, it never changes a verdict.
  * tokens                token usage when observable (shape is the caller's).
  * quota_before / quota_after
                          rate-limit snapshots around the call (shape is the
                          caller's; codex_quota.snapshot() in practice).
  * quota_source          where the quota snapshots came from.
  * role                  the seat_model role the spawn resolved (e.g.
                          "code_reviewer").
  * env_override_refused  {var, value} when an env model override was refused.
  * substitute_for        S081 amendment 1 (D6): the provider whose seat a
                          substitute served — "codex" when astra could not run
                          the seat and a fresh Claude agent took it. Absent on
                          every row that is not a substitution.
  * substitution_reason   why the seat was substituted (a codex_quota
                          SUBSTITUTION_REASONS token, e.g. "quota_exhausted").
  * use                   the codex_quota use the seat was admitted under
                          (e.g. "audit").

OPTIONAL WATCHDOG fields (S081 rev 4 WP-A01b, team-lead ruling 1; written by
skills/_meta/codex_watch.py). Same rule again: emitted only for a non-None
value, so every row from a caller that is not the watchdog keeps its exact key
set. These are what the D24 timeout table is tuned FROM.
  * max_silence_s         the longest gap between two heartbeats during the
                          call, in seconds. THE FIELD THAT EARNS THIS BLOCK:
                          it is the only one that says how close a HEALTHY call
                          came to tripping the idle timeout. `wall_clock_s` and
                          `status` describe calls that stopped; neither can
                          report the margin on the calls that did not, which is
                          exactly the number a threshold must be set against.
  * stop_reason           "ok" | "idle_timeout" | "hard_cap" — the watchdog's
                          own verdict. Duplicates `status` on a watchdog row on
                          purpose: `status` is the generic spawn-outcome column
                          shared with every other tool, and a reader filtering
                          watchdog rows should not have to know that.
  * exit_code             the code the watchdog returned: the child's own on a
                          normal finish, 111 on idle timeout, 112 on hard cap.
  * idle_timeout_s        the idle threshold in force for that call. ABSENT on
                          an agy row, because agy has no idle timeout at all
                          (it is silent while reasoning, so stdout growth
                          cannot distinguish thinking from hung) — the absence
                          is the record, not a lost value.
  * hard_cap_s            the runaway cap in force for that call.
These are recorded as given. A value json cannot encode never costs the row:
its unencodable parts are coerced to str (see _jsonable). A substituted arm
keeps its own `tool` tag (e.g. "audit_codex") so rollups stay comparable; its
`model` / `served_model` name the substitute and `requested_model` the model
the seat asked for.

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


def _jsonable(value: Any) -> Any:
    """Return `value` in a form json.dumps accepts, never raising.

    Unencodable leaves become their str() (structure is kept); a value that
    cannot be encoded even then (circular reference, non-scalar dict keys)
    becomes str(value) as a whole; a value whose str() and repr() both raise
    becomes a type-named placeholder. The optional fields must never cost the
    row, because the row is the only record the spawn happened.
    """
    try:
        return json.loads(json.dumps(value, default=str, ensure_ascii=False))
    except BaseException:  # noqa: BLE001 - never-raise contract
        pass
    for render in (str, repr):
        try:
            return render(value)
        except BaseException:  # noqa: BLE001
            continue
    return f"<unserialisable {type(value).__name__}>"


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
    requested_model: Any = None,
    served_model: Any = None,
    tokens: Any = None,
    quota_before: Any = None,
    quota_after: Any = None,
    quota_source: Any = None,
    role: Any = None,
    env_override_refused: Any = None,
    substitute_for: Any = None,
    substitution_reason: Any = None,
    use: Any = None,
    served_model_usage: Any = None,
    served_model_mismatch: Any = None,
    max_silence_s: Any = None,
    stop_reason: Any = None,
    exit_code: Any = None,
    idle_timeout_s: Any = None,
    hard_cap_s: Any = None,
    project_root_override: Optional[Path] = None,
) -> None:
    """Append one spawn-run record. BEST-EFFORT; never raises.

    All numeric fields are coerced null-safe (None stays None). The ENTIRE body
    is wrapped in try/except BaseException so a broken backend cannot perturb
    the caller's exit code (#124 / design §A — observe-only, never-raise).

    The S081 optional fields — including the amendment-1 substitution fields
    `substitute_for`, `substitution_reason` and `use`, the #282 R3 fields
    `served_model_usage` and `served_model_mismatch`, and the rev-4 WP-A01b
    watchdog fields `max_silence_s`, `stop_reason`, `exit_code`,
    `idle_timeout_s` and `hard_cap_s` — are emitted only when not None (see the
    module docstring), so existing callers' rows keep their exact key set.
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
        optional = {
            "requested_model": requested_model,
            "served_model": served_model,
            "tokens": tokens,
            "quota_before": quota_before,
            "quota_after": quota_after,
            "quota_source": quota_source,
            "role": role,
            "env_override_refused": env_override_refused,
            "substitute_for": substitute_for,
            "substitution_reason": substitution_reason,
            "use": use,
            "served_model_usage": served_model_usage,
            "served_model_mismatch": served_model_mismatch,
            "max_silence_s": max_silence_s,
            "stop_reason": stop_reason,
            "exit_code": exit_code,
            "idle_timeout_s": idle_timeout_s,
            "hard_cap_s": hard_cap_s,
        }
        for key, value in optional.items():
            if value is not None:
                record[key] = _jsonable(value)
        _append_event_line(obs_dir / SPAWN_RUNS_FILENAME, record)
    except BaseException as e:  # noqa: BLE001
        try:
            sys.stderr.write(f"SPAWN_RUN_RECORD_FAIL: {type(e).__name__}: {e}\n")
        except BaseException:
            pass
        return None
