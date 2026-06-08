#!/usr/bin/env python3
"""test_spawn_cost_rollup.py — S046 / #124 additive cost/latency rollup.

Verifies rollup.compute_spawn_cost + its wiring into compute_rollup:
  * additive aggregates: total_cost_usd, p50/p95_latency_s, summed wall-clock;
  * per-tool breakout;
  * null-cost records (Codex / non-JSON) counted in `spawns` but not in cost;
  * windowing (out-of-window records excluded);
  * empty-ledger graceful (no div-by-zero -> None percentiles, 0 totals);
  * cost_per_verified DEFERRED (always None);
  * honest labels (coverage=partial, budget_enforced=False);
  * the FOUR existing efficacy metrics are unperturbed (pure-additive proof).

Run:
    pytest skills/process-observation/tests/test_spawn_cost_rollup.py -v
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import rollup  # noqa: E402
import spawn_runs  # noqa: E402


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_spawn_runs(root: Path, records):
    obs = root / ".process-observations"
    obs.mkdir(parents=True, exist_ok=True)
    p = obs / "spawn-runs.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")


def _rec(ts, tool, cost, dur_ms, wall, status="VERIFIED"):
    return {"ts": ts, "invocation_id": "i", "cycle_id": None,
            "component_id": "c", "bundle_hash": None, "request_id": None,
            "tool": tool, "model": "m", "status": status,
            "cost_usd": cost, "duration_ms": dur_ms, "num_turns": 1,
            "wall_clock_s": wall}


# ---------------------------------------------------------------------------
# Aggregate correctness
# ---------------------------------------------------------------------------

def test_total_cost_and_wall_clock_sum(tmp_path):
    now = _now_iso()
    _seed_spawn_runs(tmp_path, [
        _rec(now, "verification_arbiter", 0.01, 1000, 1.0),
        _rec(now, "audit_claude", 0.02, 3000, 3.0),
        _rec(now, "audit_codex", None, None, 5.0),  # null cost (non-JSON path)
    ])
    sc = rollup.compute_spawn_cost(rollup._read_jsonl(
        tmp_path / ".process-observations" / "spawn-runs.jsonl"),
        window_start_s=0.0)
    assert sc["spawns"] == 3
    assert sc["spawns_with_cost"] == 2
    assert sc["total_cost_usd"] == 0.03
    assert sc["total_wall_clock_s"] == 9.0  # 1+3+5, codex wall still counts
    assert sc["cost_per_verified"] is None  # DEFERRED
    assert sc["budget_enforced"] is False
    assert sc["coverage"].startswith("partial")


def test_latency_percentiles(tmp_path):
    now = _now_iso()
    # durations 1000ms..10000ms -> latencies 1.0s..10.0s
    recs = [_rec(now, "audit_claude", 0.01, ms, 1.0)
            for ms in (1000, 2000, 3000, 4000, 5000,
                       6000, 7000, 8000, 9000, 10000)]
    _seed_spawn_runs(tmp_path, recs)
    sc = rollup.compute_spawn_cost(rollup._read_jsonl(
        tmp_path / ".process-observations" / "spawn-runs.jsonl"), 0.0)
    # nearest-rank p50 of 10 items = rank ceil(0.5*10)=5 -> 5.0s
    assert sc["p50_latency_s"] == 5.0
    # p95 -> rank ceil(0.95*10)=10 -> 10.0s
    assert sc["p95_latency_s"] == 10.0


def test_per_tool_breakout(tmp_path):
    now = _now_iso()
    _seed_spawn_runs(tmp_path, [
        _rec(now, "verification_arbiter", 0.05, 2000, 2.0),
        _rec(now, "audit_claude", 0.02, 1000, 1.0),
        _rec(now, "audit_codex", None, None, 4.0),
    ])
    sc = rollup.compute_spawn_cost(rollup._read_jsonl(
        tmp_path / ".process-observations" / "spawn-runs.jsonl"), 0.0)
    pt = sc["per_tool"]
    assert set(pt) == {"verification_arbiter", "audit_claude", "audit_codex"}
    assert pt["verification_arbiter"]["total_cost_usd"] == 0.05
    assert pt["audit_codex"]["spawns_with_cost"] == 0
    assert pt["audit_codex"]["total_cost_usd"] == 0.0
    assert pt["audit_codex"]["p50_latency_s"] is None  # no duration_ms


def test_windowing_excludes_old_records(tmp_path):
    old = "2000-01-01T00:00:00Z"
    new = _now_iso()
    _seed_spawn_runs(tmp_path, [
        _rec(old, "audit_claude", 0.99, 9000, 9.0),  # out of window
        _rec(new, "audit_claude", 0.01, 1000, 1.0),  # in window
    ])
    # window_start = now - 1 day -> old excluded.
    import time
    win_start = time.time() - 86400
    sc = rollup.compute_spawn_cost(rollup._read_jsonl(
        tmp_path / ".process-observations" / "spawn-runs.jsonl"), win_start)
    assert sc["spawns"] == 1
    assert sc["total_cost_usd"] == 0.01


def test_empty_ledger_graceful(tmp_path):
    (tmp_path / ".process-observations").mkdir(parents=True)
    sc = rollup.compute_spawn_cost([], 0.0)
    assert sc["spawns"] == 0
    assert sc["spawns_with_cost"] == 0
    assert sc["total_cost_usd"] == 0.0
    assert sc["total_wall_clock_s"] == 0.0
    assert sc["p50_latency_s"] is None
    assert sc["p95_latency_s"] is None
    assert sc["per_tool"] == {}


def test_bool_cost_not_counted(tmp_path):
    """A stray bool in cost_usd must not read as 1.0."""
    now = _now_iso()
    r = _rec(now, "audit_claude", True, 1000, 1.0)
    _seed_spawn_runs(tmp_path, [r])
    sc = rollup.compute_spawn_cost(rollup._read_jsonl(
        tmp_path / ".process-observations" / "spawn-runs.jsonl"), 0.0)
    assert sc["spawns_with_cost"] == 0
    assert sc["total_cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# Wiring + non-perturbation of the four existing metrics
# ---------------------------------------------------------------------------

def test_compute_rollup_includes_spawn_cost(tmp_path):
    now = _now_iso()
    _seed_spawn_runs(tmp_path, [_rec(now, "verification_arbiter", 0.01, 1000, 1.0)])
    roll = rollup.compute_rollup(tmp_path, window_s=7 * 86400, window_label="7d")
    assert "spawn_cost" in roll
    assert roll["spawn_cost"]["total_cost_usd"] == 0.01
    # The four efficacy metrics are still present and well-formed.
    for k in ("gate_fail_rate", "false_positive_rate",
              "dual_verdict_disagreement_rate", "user_override_rate"):
        assert k in roll


def test_spawn_cost_does_not_perturb_efficacy_metrics(tmp_path):
    """Pure-additive: a rollup with NO spawn-runs and one WITH spawn-runs must
    have byte-identical four-metric blocks (the new block is purely additive)."""
    obs = tmp_path / ".process-observations"
    obs.mkdir(parents=True)
    # Seed a gate-run so gate_fail_rate has real content.
    (obs / "gate-runs.jsonl").write_text(
        json.dumps({"ts": _now_iso(), "gate": "G1", "run_id": "r1", "code": 0}) + "\n")
    roll_without = rollup.compute_rollup(tmp_path, 7 * 86400)
    # Now add spawn-runs and recompute.
    _seed_spawn_runs(tmp_path, [_rec(_now_iso(), "audit_claude", 0.5, 5000, 5.0)])
    roll_with = rollup.compute_rollup(tmp_path, 7 * 86400)
    for k in ("gate_fail_rate", "false_positive_rate",
              "dual_verdict_disagreement_rate", "user_override_rate"):
        assert roll_without[k] == roll_with[k], f"{k} was perturbed by spawn_cost"
    # And the new block appears only in the second.
    assert roll_without["spawn_cost"]["spawns"] == 0
    assert roll_with["spawn_cost"]["spawns"] == 1


def test_render_text_includes_spawn_cost_line(tmp_path):
    now = _now_iso()
    _seed_spawn_runs(tmp_path, [_rec(now, "verification_arbiter", 0.0789, 5120, 5.1)])
    roll = rollup.compute_rollup(tmp_path, 7 * 86400)
    text = rollup.render(roll, fmt="text")
    assert "spawn_cost (observe-only)" in text
    assert "0.0789" in text
    assert "budget_enforced=False" in text
    assert "coverage: partial" in text


def test_render_json_roundtrip(tmp_path):
    _seed_spawn_runs(tmp_path, [_rec(_now_iso(), "audit_claude", 0.01, 1000, 1.0)])
    roll = rollup.compute_rollup(tmp_path, 7 * 86400)
    out = rollup.render(roll, fmt="json")
    parsed = json.loads(out)
    assert parsed["spawn_cost"]["total_cost_usd"] == 0.01


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
