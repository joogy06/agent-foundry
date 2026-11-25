#!/usr/bin/env python3
"""
rollup.py - efficacy-telemetry read-only projection (S039 WP2).

Computes the four efficacy metrics for the forge->bob->alf->pa orchestration
flow, read-only, over a `--window` (default 7d). Wired as the `rollup` op in
query.py (B1: on-demand CLI; alf reads it during sweeps).

The rollup is PURE READ. It NEVER writes `.ledger/`, `.process-observations/
active.yaml`, or anything else — it only reads existing on-disk data
(design §4 CB4, §8). It cannot break a gate because it never runs in the gate
path.

The four metrics (design §6):
    1. gate_fail_rate            <- gate-runs.jsonl  (THIS feature's denominator)
    2. false_positive_rate       <- events.jsonl gate_false_block / gate-runs.jsonl
    3. dual_verdict_disagreement_rate <- .ledger/verdicts/*.verdict.yaml
    4. user_override_rate        <- scope_delta records (.ledger/scope-deltas/)

Output schema: efficacy-rollup.v1 (canonical JSON), or a human text table.

Design refs:
    docs/plans/2026-06-03-efficacy-telemetry-v1-design.md §6, §8, §9
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    from write import parse_iso as _parse_iso  # noqa: E402
except Exception:  # pragma: no cover
    def _parse_iso(s: str) -> datetime:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

try:
    from gate_runs import read_window_start as _read_window_start  # noqa: E402
except Exception:  # pragma: no cover
    def _read_window_start(project_root: Path) -> Optional[str]:
        try:
            sentinel = (
                Path(project_root) / ".process-observations" / ".telemetry_window"
            )
            if not sentinel.is_file():
                return None
            val = sentinel.read_text(encoding="utf-8").strip()
            return val or None
        except Exception:
            return None

try:
    import yaml  # noqa: E402
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


SCHEMA = "efficacy-rollup.v1"

# ---------------------------------------------------------------------------
# §6.1 exit-code policy table — classification happens HERE at read time, not
# at write time (design §5). The write path stores the RAW normalized exit code
# so a future change to a gate's exit semantics only updates THIS table, never
# the writer. Policy:
#   2 = hard block  -> the ONLY "fail" (the gate said NO)
#   3 = advisory OR env-error (overloaded: G4 advisory uses 3; env_error() also
#       exits 3) -> broken out as advisory_or_env_count, NOT counted as fail
#   4 = skip / not-applicable -> skip_count, NOT counted as fail
#   0 = pass
#   null = process killed before terminal exit caught -> in denominator, not in
#          any outcome tally
# ---------------------------------------------------------------------------
FAIL_CODE = 2
ADVISORY_OR_ENV_CODE = 3
SKIP_CODE = 4
PASS_CODE = 0

# ---------------------------------------------------------------------------
# N1 disagreement normalization (design §6.3) — documented constant mapping
# from the canonical-key vocabulary {VERIFIED, VERIFIED_WITH_CONCERNS,
# REJECTED, AUDIT_UNAVAILABLE} to the pass/fail/indeterminate axis.
#   VERIFIED, VERIFIED_WITH_CONCERNS -> "pass"
#   REJECTED                         -> "fail"
#   AUDIT_UNAVAILABLE                -> "indeterminate" (excluded from denom)
# A missing / non-canonical value -> "indeterminate" (fail-safe, never guess).
# ---------------------------------------------------------------------------
VERDICT_AXIS = {
    "VERIFIED": "pass",
    "VERIFIED_WITH_CONCERNS": "pass",
    "REJECTED": "fail",
    "AUDIT_UNAVAILABLE": "indeterminate",
}

# FP numerator exists for only these 6 gates (gates.py:998 _GATE_FALSE_BLOCK_SET).
FALSE_BLOCK_GATES = frozenset({"G1", "G2", "G3", "G4", "G_V", "G_XR"})


# ---------------------------------------------------------------------------
# Window + JSONL reading helpers
# ---------------------------------------------------------------------------

def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _in_window(ts_iso: str, window_start_s: float) -> bool:
    """True if ts_iso (ISO Z) is at or after window_start_s. Malformed ts ->
    excluded (fail-safe: don't count records we can't place in time)."""
    try:
        return _parse_iso(ts_iso).timestamp() >= window_start_s
    except Exception:
        return False


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Read a JSONL truth log. Malformed lines are skipped (best-effort).
    active.yaml's 10-event ring + count_last_7d approximation cannot do
    arbitrary windows, so the rollup reads the JSONL truth logs directly
    (design §10 spec-review note)."""
    out: List[Dict[str, Any]] = []
    if not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _obs_dir(project_root: Path) -> Path:
    return project_root / ".process-observations"


def _safe_rate(num: int, denom: int) -> Optional[float]:
    """num/denom rounded to 4dp; None on empty denominator (no div-by-zero,
    design §11 empty-ledger graceful)."""
    if denom <= 0:
        return None
    return round(num / denom, 4)


# ---------------------------------------------------------------------------
# Metric 1 — gate-fail rate (design §6.1)
# ---------------------------------------------------------------------------

def _fold_gate_runs(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Fold same-run_id records (bump code:null + outcome real-code) into one
    logical run. last non-null code wins; null if no outcome seen. Returns
    {run_id: {"gate":..., "code":int|None, "ts":...}}."""
    runs: Dict[str, Dict[str, Any]] = {}
    for r in records:
        rid = r.get("run_id")
        if not rid:
            continue
        gate = r.get("gate") or "unknown"
        code = r.get("code", None)
        ts = r.get("ts")
        cur = runs.get(rid)
        if cur is None:
            runs[rid] = {"gate": gate, "code": code, "ts": ts}
        else:
            # Prefer the latest non-null code; keep earliest ts (bump time).
            if code is not None:
                cur["code"] = code
            if ts and (cur.get("ts") is None or ts < cur["ts"]):
                cur["ts"] = ts
    return runs


def compute_gate_fail_rate(
    gate_runs_records: List[Dict[str, Any]],
    window_start_s: float,
) -> Dict[str, Any]:
    runs = _fold_gate_runs(gate_runs_records)
    # Per-gate tallies.
    per_gate: Dict[str, Dict[str, int]] = {}
    total_denom = 0
    total_fail = 0
    total_advisory_or_env = 0
    total_skip = 0
    for _rid, run in runs.items():
        if not _in_window(run.get("ts") or "", window_start_s):
            continue
        gate = run["gate"]
        code = run["code"]
        pg = per_gate.setdefault(
            gate, {"numerator": 0, "denominator": 0,
                   "advisory_or_env_count": 0, "skip_count": 0}
        )
        pg["denominator"] += 1
        total_denom += 1
        if code == FAIL_CODE:
            pg["numerator"] += 1
            total_fail += 1
        elif code == ADVISORY_OR_ENV_CODE:
            pg["advisory_or_env_count"] += 1
            total_advisory_or_env += 1
        elif code == SKIP_CODE:
            pg["skip_count"] += 1
            total_skip += 1
        # code == 0 (pass) or None (killed) -> denominator only.
    # Attach per-gate rates.
    per_gate_out: Dict[str, Any] = {}
    for gate in sorted(per_gate):
        pg = per_gate[gate]
        per_gate_out[gate] = {
            "numerator": pg["numerator"],
            "denominator": pg["denominator"],
            "rate": _safe_rate(pg["numerator"], pg["denominator"]),
            "advisory_or_env_count": pg["advisory_or_env_count"],
            "skip_count": pg["skip_count"],
        }
    return {
        "numerator": total_fail,
        "denominator": total_denom,
        "rate": _safe_rate(total_fail, total_denom),
        "advisory_or_env_count": total_advisory_or_env,
        "skip_count": total_skip,
        "per_gate": per_gate_out,
    }


# ---------------------------------------------------------------------------
# Metric 2 — false-positive rate (design §6.2)
# ---------------------------------------------------------------------------

def compute_false_positive_rate(
    events_records: List[Dict[str, Any]],
    gate_runs_records: List[Dict[str, Any]],
    window_start_s: float,
) -> Dict[str, Any]:
    """count(gate_false_block events in window) / count(gate-runs records).

    Caveats (both printed in coverage, design §6.2):
      (a) gate_false_block means "blocked", not "blocked AND human-accepted"
          -> the rate is an UPPER BOUND.
      (b) FP numerator exists for only 6 of ~12 gates -> the others report
          fp_rate null with coverage "no_false_block_numerator".
    """
    # Per-gate FP numerator from events.jsonl gate_false_block.
    # The friction event's subject.id is the gate name (gates.py
    # exit_with_observation passes subject_id=<gate>); fingerprint dedup
    # collapses repeats in active.yaml but events.jsonl keeps each fire.
    fp_per_gate: Dict[str, int] = {}
    for ev in events_records:
        if ev.get("category") != "gate_false_block":
            continue
        if not _in_window(ev.get("ts") or "", window_start_s):
            continue
        subj = ev.get("subject") or {}
        gate = subj.get("id") or "unknown"
        fp_per_gate[gate] = fp_per_gate.get(gate, 0) + 1

    # Per-gate denominator from gate-runs.jsonl (folded, windowed).
    runs = _fold_gate_runs(gate_runs_records)
    denom_per_gate: Dict[str, int] = {}
    for _rid, run in runs.items():
        if not _in_window(run.get("ts") or "", window_start_s):
            continue
        gate = run["gate"]
        denom_per_gate[gate] = denom_per_gate.get(gate, 0) + 1

    total_num = sum(fp_per_gate.get(g, 0) for g in FALSE_BLOCK_GATES)
    total_denom = sum(denom_per_gate.get(g, 0) for g in FALSE_BLOCK_GATES)

    per_gate_out: Dict[str, Any] = {}
    for gate in sorted(set(denom_per_gate) | set(fp_per_gate)):
        denom = denom_per_gate.get(gate, 0)
        if gate in FALSE_BLOCK_GATES:
            num = fp_per_gate.get(gate, 0)
            per_gate_out[gate] = {
                "numerator": num,
                "denominator": denom,
                "rate": _safe_rate(num, denom),
                "coverage": "upper_bound",
            }
        else:
            per_gate_out[gate] = {
                "numerator": None,
                "denominator": denom,
                "rate": None,
                "coverage": "no_false_block_numerator",
            }

    return {
        "numerator": total_num,
        "denominator": total_denom,
        "rate": _safe_rate(total_num, total_denom),
        "coverage": "6_of_12_gates; upper_bound",
        "per_gate": per_gate_out,
    }


# ---------------------------------------------------------------------------
# Metric 3 — dual-verdict disagreement rate (design §6.3, N1)
#
# PINNED field paths (verified against 24 real verdict files): the two arms are
# stored under ASYMMETRIC keys —
#     audit axis   = audit_arm.result
#     arbiter axis = arbiter_arm.verdict     (note .result vs .verdict)
# Read the axis from THESE TWO KEYS ONLY. Do NOT read
# audit_arm.claude_verdict / audit_arm.codex_verdict (a DECOY sub-vocabulary
# pass/pass_with_concerns/fail for the intra-audit arms). Do NOT substring-grep
# the file for AUDIT_UNAVAILABLE (it appears in a free-text
# rerun_notes.first_run_result field while the canonical audit_arm.result is
# REJECTED -> mis-bucketing a determinate verdict as indeterminate).
# ---------------------------------------------------------------------------

def _axis_for(canonical_value: Any) -> str:
    """Map a canonical-key value to pass/fail/indeterminate. Missing /
    non-canonical -> indeterminate (fail-safe, never guess)."""
    if not isinstance(canonical_value, str):
        return "indeterminate"
    return VERDICT_AXIS.get(canonical_value, "indeterminate")


def classify_verdict_file(doc: Dict[str, Any]) -> Tuple[str, str]:
    """Return (audit_axis, arbiter_axis) for one verdict doc, reading ONLY the
    two pinned canonical keys."""
    audit_arm = doc.get("audit_arm") if isinstance(doc, dict) else None
    arbiter_arm = doc.get("arbiter_arm") if isinstance(doc, dict) else None
    audit_value = audit_arm.get("result") if isinstance(audit_arm, dict) else None
    arbiter_value = (
        arbiter_arm.get("verdict") if isinstance(arbiter_arm, dict) else None
    )
    return _axis_for(audit_value), _axis_for(arbiter_value)


def compute_dual_verdict_disagreement_rate(
    verdict_docs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """count(both determinate AND audit_axis != arbiter_axis) /
    count(both determinate). Indeterminate (AUDIT_UNAVAILABLE on either arm)
    reported separately as indeterminate_count, excluded from denominator."""
    determinate = 0
    disagree = 0
    indeterminate = 0
    for doc in verdict_docs:
        audit_axis, arbiter_axis = classify_verdict_file(doc)
        if audit_axis == "indeterminate" or arbiter_axis == "indeterminate":
            indeterminate += 1
            continue
        determinate += 1
        if audit_axis != arbiter_axis:
            disagree += 1
    return {
        "numerator": disagree,
        "denominator": determinate,
        "rate": _safe_rate(disagree, determinate),
        "indeterminate_count": indeterminate,
    }


# ---------------------------------------------------------------------------
# Metric — triple-arm disagreement (S048 / #116, read-only, observe-only)
#
# The HEADLINE caught-correlated-error signal: the deterministic (non-LLM)
# evidence arm is RED or INDETERMINATE while BOTH LLM axes (audit_arm.result +
# arbiter_arm.verdict) report pass. That is exactly the failure class the
# non-LLM arm exists to catch — a VERIFIED that contradicts the on-disk
# evidence — empirically observed in the archive.
#
# PINNED field paths: the deterministic arm result is recorded by bob in the
# verdict archive (dual-verdict envelope, additionalProperties:true) under
# `deterministic_arm.state` (preferred) or the legacy/alt `deterministic_evidence
# .state`, with a string value in {GREEN, RED, INDETERMINATE}. Pre-S048 archives
# carry no such key -> counted as `unrecorded` (excluded from numerator AND
# denominator; never guessed). This is OBSERVE-ONLY telemetry: it READS what bob
# archived; the SECURITY enforcement is R6 deriving the verdict from the bundle
# itself (a forged archive boolean cannot pass R6, but COULD hide a row from
# this read-only count — acknowledged; telemetry is not a security control).
#
# evidence_quality + citation status are surfaced as additive counters for
# alf-sweep visibility (degraded-bundle prevalence + citation-veto prevalence).
# ---------------------------------------------------------------------------

_DET_STATES = frozenset({"GREEN", "RED", "INDETERMINATE"})


def _deterministic_state(doc: Dict[str, Any]) -> Optional[str]:
    """Return the recorded deterministic-arm state for one verdict doc, reading
    `deterministic_arm.state` then `deterministic_evidence.state`. None if
    neither is present/valid (pre-S048 archive -> unrecorded)."""
    if not isinstance(doc, dict):
        return None
    for key in ("deterministic_arm", "deterministic_evidence"):
        arm = doc.get(key)
        if isinstance(arm, dict):
            st = arm.get("state")
            if isinstance(st, str) and st in _DET_STATES:
                return st
        elif isinstance(arm, str) and arm in _DET_STATES:
            return arm
    return None


def compute_triple_arm_disagreement(
    verdict_docs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """count(deterministic RED/INDETERMINATE AND both LLM axes pass) /
    count(verdicts with a recorded deterministic state AND both LLM axes
    determinate). The numerator is the caught correlated-LLM-error.

    Also surfaces additive counters (no effect on the rate):
      - unrecorded_count: archives with no deterministic state (pre-S048)
      - red_while_llms_pass / indeterminate_while_llms_pass: numerator split
      - evidence_quality_degraded_count / citation_veto_count: alf visibility
    """
    denom = 0
    disagree = 0
    red_while_pass = 0
    indet_while_pass = 0
    unrecorded = 0
    degraded = 0
    citation_veto = 0
    for doc in verdict_docs:
        # additive quality/citation counters (independent of the rate).
        if isinstance(doc, dict):
            det_arm = doc.get("deterministic_arm")
            if isinstance(det_arm, dict):
                if det_arm.get("evidence_quality") == "degraded":
                    degraded += 1
                cit = det_arm.get("citation")
                if isinstance(cit, dict) and cit.get("status") == "veto":
                    citation_veto += 1

        det_state = _deterministic_state(doc)
        if det_state is None:
            unrecorded += 1
            continue
        audit_axis, arbiter_axis = classify_verdict_file(doc)
        if audit_axis == "indeterminate" or arbiter_axis == "indeterminate":
            # Can't call it a triple-arm disagreement if an LLM axis is itself
            # indeterminate — excluded from the denominator (fail-safe).
            continue
        denom += 1
        both_llm_pass = (audit_axis == "pass" and arbiter_axis == "pass")
        if both_llm_pass and det_state == "RED":
            disagree += 1
            red_while_pass += 1
        elif both_llm_pass and det_state == "INDETERMINATE":
            disagree += 1
            indet_while_pass += 1
    return {
        "numerator": disagree,
        "denominator": denom,
        "rate": _safe_rate(disagree, denom),
        "red_while_llms_pass": red_while_pass,
        "indeterminate_while_llms_pass": indet_while_pass,
        "unrecorded_count": unrecorded,
        "evidence_quality_degraded_count": degraded,
        "citation_veto_count": citation_veto,
    }


# ---------------------------------------------------------------------------
# Additive aggregate — spawn cost/latency (S046 / #124, observe-only)
#
# Reads the NEW spawn-runs.jsonl sidecar (written by audit_spawn.py +
# verification_arbiter_spawn.py via spawn_runs.record_spawn_run). This is PURE
# ADDITIVE: it does not touch the four efficacy metrics above and never writes.
#
# HONEST COVERAGE (design §G): this captures ONLY the Claude-verifier spend that
# rides the `claude -p --output-format json` envelope (the audit-Claude arm + the
# verification-arbiter arm). It does NOT capture forge approach-agent spend, the
# Codex arm (codex exec is not a JSON-cost envelope -> null), or agy. So the
# rollup labels coverage="partial" and budget_enforced=false.
#
# cost_per_verified is DEFERRED (design §G): it needs to join an actually-APPLIED
# VERIFIED ledger transition (a passing verdict != an applied transition). Not
# faked here.
# ---------------------------------------------------------------------------

def _percentile(sorted_vals: List[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile over a NON-empty pre-sorted list. pct in [0,1].
    Returns None on empty input (graceful empty-ledger, no div-by-zero)."""
    n = len(sorted_vals)
    if n == 0:
        return None
    if n == 1:
        return round(sorted_vals[0], 4)
    # Nearest-rank: rank = ceil(pct * n), 1-indexed, clamped to [1, n].
    import math
    rank = max(1, min(n, math.ceil(pct * n)))
    return round(sorted_vals[rank - 1], 4)


def compute_spawn_cost(
    spawn_runs_records: List[Dict[str, Any]],
    window_start_s: float,
) -> Dict[str, Any]:
    """Additive cost/latency aggregate over spawn-runs.jsonl (observe-only).

    Aggregates (design §G):
      * total_cost_usd     sum of non-null cost_usd over windowed records.
      * p50_latency_s      median of per-spawn latency (duration_ms -> seconds).
      * p95_latency_s      95th-percentile of the same.
      * total_wall_clock_s sum of non-null wall_clock_s over windowed records.
      * spawns             count of windowed records (the denominator context).
      * spawns_with_cost   how many had a non-null cost (the rest are Codex /
                           non-JSON / truncated -> null, by design).
      * per_tool           same tallies broken out by tool tag.

    cost_per_verified is intentionally absent (DEFERRED -> needs an applied
    VERIFIED join). coverage + budget_enforced are stamped honestly.
    """
    total_cost = 0.0
    cost_count = 0
    wall_sum = 0.0
    latencies_s: List[float] = []
    per_tool: Dict[str, Dict[str, Any]] = {}
    spawns = 0

    for rec in spawn_runs_records:
        if not _in_window(rec.get("ts") or "", window_start_s):
            continue
        spawns += 1
        tool = rec.get("tool") or "unknown"
        pt = per_tool.setdefault(
            tool, {"spawns": 0, "total_cost_usd": 0.0, "spawns_with_cost": 0,
                   "total_wall_clock_s": 0.0, "_lat": []})
        pt["spawns"] += 1

        cost = rec.get("cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            total_cost += float(cost)
            cost_count += 1
            pt["total_cost_usd"] += float(cost)
            pt["spawns_with_cost"] += 1

        wc = rec.get("wall_clock_s")
        if isinstance(wc, (int, float)) and not isinstance(wc, bool):
            wall_sum += float(wc)
            pt["total_wall_clock_s"] += float(wc)

        dur_ms = rec.get("duration_ms")
        if isinstance(dur_ms, (int, float)) and not isinstance(dur_ms, bool):
            lat_s = float(dur_ms) / 1000.0
            latencies_s.append(lat_s)
            pt["_lat"].append(lat_s)

    latencies_s.sort()
    per_tool_out: Dict[str, Any] = {}
    for tool in sorted(per_tool):
        pt = per_tool[tool]
        lat = sorted(pt.pop("_lat"))
        per_tool_out[tool] = {
            "spawns": pt["spawns"],
            "spawns_with_cost": pt["spawns_with_cost"],
            "total_cost_usd": round(pt["total_cost_usd"], 6),
            "total_wall_clock_s": round(pt["total_wall_clock_s"], 3),
            "p50_latency_s": _percentile(lat, 0.50),
            "p95_latency_s": _percentile(lat, 0.95),
        }

    return {
        "schema": "spawn-cost.v1",
        "spawns": spawns,
        "spawns_with_cost": cost_count,
        "total_cost_usd": round(total_cost, 6),
        "p50_latency_s": _percentile(latencies_s, 0.50),
        "p95_latency_s": _percentile(latencies_s, 0.95),
        "total_wall_clock_s": round(wall_sum, 3),
        "per_tool": per_tool_out,
        # Honest labels (design §G): observe-only, partial coverage.
        "coverage": "partial: claude-verifier spend only "
                    "(codex/agy/forge-approach-agents NOT captured)",
        "budget_enforced": False,
        "cost_per_verified": None,  # DEFERRED -> needs an applied VERIFIED join
    }


# ---------------------------------------------------------------------------
# Metric 4 — user-override rate (design §6.4)
# ---------------------------------------------------------------------------

def compute_user_override_rate(
    scope_delta_records: List[Dict[str, Any]],
    window_start_s: float,
) -> Dict[str, Any]:
    """count(scope_delta status in {amended, excluded}) / count(all in window).

    scope_delta.py:52 STATUSES = (undecided, amended, excluded) — no defer/
    reject. --no-verify (git layer) and escalation-override (no code hook) have
    no instrumentation -> reported under not_yet_instrumented, NOT faked."""
    override_statuses = {"amended", "excluded"}
    total = 0
    overrides = 0
    for rec in scope_delta_records:
        # Window on created_at (scope_delta.v1 required field).
        if not _in_window(rec.get("created_at") or "", window_start_s):
            continue
        total += 1
        if rec.get("status") in override_statuses:
            overrides += 1
    return {
        "numerator": overrides,
        "denominator": total,
        "rate": _safe_rate(overrides, total),
        "not_yet_instrumented": ["git_no_verify", "escalation_override"],
    }


# ---------------------------------------------------------------------------
# Data loaders (read-only, never raise on missing/corrupt input)
# ---------------------------------------------------------------------------

def _load_verdict_docs(project_root: Path) -> List[Dict[str, Any]]:
    """Read every .ledger/verdicts/*.verdict.yaml. Read-only; bob remains the
    sole writer of that directory (design §4 CB4)."""
    docs: List[Dict[str, Any]] = []
    if yaml is None:
        return docs
    vdir = project_root / ".ledger" / "verdicts"
    if not vdir.is_dir():
        return docs
    for p in sorted(vdir.glob("*.verdict.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(doc, dict):
            docs.append(doc)
    return docs


def _load_scope_delta_records(project_root: Path) -> List[Dict[str, Any]]:
    """Read every .ledger/scope-deltas/scope-delta-*.yaml. Read-only."""
    recs: List[Dict[str, Any]] = []
    if yaml is None:
        return recs
    sdir = project_root / ".ledger" / "scope-deltas"
    if not sdir.is_dir():
        return recs
    for p in sorted(sdir.glob("scope-delta-*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(doc, dict):
            recs.append(doc)
    return recs


# ---------------------------------------------------------------------------
# Top-level rollup
# ---------------------------------------------------------------------------

def compute_rollup(
    project_root: Path,
    window_s: int,
    window_label: str = "7d",
    *,
    now_s: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute the efficacy-rollup.v1 object. Pure read; never writes."""
    project_root = Path(project_root)
    obs_dir = _obs_dir(project_root)
    now = now_s if now_s is not None else _now()
    window_start_s = now - float(window_s)

    denominator_window_start = _read_window_start(project_root)

    gate_runs_records = _read_jsonl(obs_dir / "gate-runs.jsonl")
    events_records = _read_jsonl(obs_dir / "events.jsonl")
    spawn_runs_records = _read_jsonl(obs_dir / "spawn-runs.jsonl")
    verdict_docs = _load_verdict_docs(project_root)
    scope_delta_records = _load_scope_delta_records(project_root)

    return {
        "schema": SCHEMA,
        "window": window_label,
        "denominator_window_start": denominator_window_start,
        "gate_fail_rate": compute_gate_fail_rate(
            gate_runs_records, window_start_s
        ),
        "false_positive_rate": compute_false_positive_rate(
            events_records, gate_runs_records, window_start_s
        ),
        "dual_verdict_disagreement_rate": compute_dual_verdict_disagreement_rate(
            verdict_docs
        ),
        # S048 / #116 — the caught correlated-LLM-error (deterministic RED/
        # INDETERMINATE while both LLM arms pass). Read-only, observe-only.
        "triple_arm_disagreement": compute_triple_arm_disagreement(
            verdict_docs
        ),
        "user_override_rate": compute_user_override_rate(
            scope_delta_records, window_start_s
        ),
        # S046 / #124 additive observe-only cost/latency aggregate.
        "spawn_cost": compute_spawn_cost(
            spawn_runs_records, window_start_s
        ),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fmt_rate(r: Optional[float]) -> str:
    return "n/a" if r is None else f"{r:.4f}"


def render_text(roll: Dict[str, Any]) -> str:
    """Human-readable table for ad-hoc use. Every metric prints
    numerator + denominator + denominator_window_start + coverage (design §8)."""
    lines: List[str] = []
    lines.append(f"efficacy-rollup  schema={roll.get('schema')}  "
                 f"window={roll.get('window')}")
    lines.append(f"denominator_window_start: "
                 f"{roll.get('denominator_window_start') or '(none — no gate run yet)'}")
    lines.append("-" * 72)

    gf = roll["gate_fail_rate"]
    lines.append(
        f"gate_fail_rate:        {gf['numerator']}/{gf['denominator']}  "
        f"rate={_fmt_rate(gf['rate'])}  "
        f"advisory_or_env={gf['advisory_or_env_count']}  skip={gf['skip_count']}"
    )
    for gate in sorted(gf.get("per_gate", {})):
        pg = gf["per_gate"][gate]
        lines.append(
            f"    {gate:<20} {pg['numerator']}/{pg['denominator']}  "
            f"rate={_fmt_rate(pg['rate'])}  "
            f"advisory_or_env={pg['advisory_or_env_count']}  skip={pg['skip_count']}"
        )

    fp = roll["false_positive_rate"]
    lines.append(
        f"false_positive_rate:   {fp['numerator']}/{fp['denominator']}  "
        f"rate={_fmt_rate(fp['rate'])}  coverage=[{fp['coverage']}]"
    )

    dv = roll["dual_verdict_disagreement_rate"]
    lines.append(
        f"dual_verdict_disagreement_rate: {dv['numerator']}/{dv['denominator']}  "
        f"rate={_fmt_rate(dv['rate'])}  indeterminate={dv['indeterminate_count']}"
    )

    ta = roll.get("triple_arm_disagreement")
    if ta is not None:
        lines.append(
            f"triple_arm_disagreement: {ta['numerator']}/{ta['denominator']}  "
            f"rate={_fmt_rate(ta['rate'])}  "
            f"(RED-while-LLMs-pass={ta['red_while_llms_pass']}, "
            f"INDET-while-LLMs-pass={ta['indeterminate_while_llms_pass']}, "
            f"unrecorded={ta['unrecorded_count']})"
        )
        lines.append(
            f"    evidence_quality_degraded={ta['evidence_quality_degraded_count']}  "
            f"citation_veto={ta['citation_veto_count']}"
        )

    uo = roll["user_override_rate"]
    lines.append(
        f"user_override_rate:    {uo['numerator']}/{uo['denominator']}  "
        f"rate={_fmt_rate(uo['rate'])}  "
        f"not_yet_instrumented={','.join(uo['not_yet_instrumented'])}"
    )

    sc = roll.get("spawn_cost")
    if sc is not None:
        def _f(v):
            return "n/a" if v is None else f"{v}"

        def _fs(v):
            # latency formatter: "n/a" (no unit suffix) when null, else "<v>s".
            return "n/a" if v is None else f"{v}s"
        lines.append("-" * 72)
        lines.append(
            f"spawn_cost (observe-only): ${_f(sc['total_cost_usd'])} across "
            f"{sc['spawns']} spawns ({sc['spawns_with_cost']} with cost); "
            f"summed wall-clock {_fs(sc['total_wall_clock_s'])}"
        )
        lines.append(
            f"    latency p50={_fs(sc['p50_latency_s'])}  "
            f"p95={_fs(sc['p95_latency_s'])}  "
            f"budget_enforced={sc['budget_enforced']}  "
            f"cost_per_verified={_f(sc['cost_per_verified'])} (deferred)"
        )
        lines.append(f"    coverage: {sc['coverage']}")
        for tool in sorted(sc.get("per_tool", {})):
            pt = sc["per_tool"][tool]
            lines.append(
                f"    {tool:<22} {pt['spawns']} spawns  "
                f"${_f(pt['total_cost_usd'])}  "
                f"p50={_fs(pt['p50_latency_s'])} p95={_fs(pt['p95_latency_s'])}"
            )
    return "\n".join(lines) + "\n"


def render(roll: Dict[str, Any], fmt: str = "json") -> str:
    if fmt == "text":
        return render_text(roll)
    return _canon(roll) + "\n"
