#!/usr/bin/env python3
"""Tests for spawn_runs.record_spawn_run — the cost/latency sidecar writer.

S046 / S039-review #124 verification (observe-only cost telemetry):
  * a spawn-runs.jsonl record is written with ALL correlation fields;
  * the writer is best-effort never-raise (a broken backend cannot perturb the
    caller) -> telemetry byte-invariance under a forced writer ImportError;
  * the NEW sidecar never touches the existing friction ledger / gate-runs
    denominator (the taxonomy + efficacy denominator alf consumes stay clean).

Run:
    pytest skills/process-observation/tests/test_spawn_runs.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import spawn_runs  # noqa: E402


def _read_spawn_runs(root: Path):
    p = root / ".process-observations" / spawn_runs.SPAWN_RUNS_FILENAME
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# Happy path — full record with all correlation fields
# ---------------------------------------------------------------------------

def test_writes_record_with_all_correlation_fields(tmp_path):
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    spawn_runs.record_spawn_run(
        tool="verification_arbiter",
        status="VERIFIED",
        cost_usd=0.0123,
        duration_ms=4210,
        num_turns=2,
        wall_clock_s=4.4,
        model="claude-opus-4-6[1m]",
        cycle_id="S046",
        component_id="wiring-extract-static",
        bundle_hash="a" * 64,
        request_id="b" * 32,
        invocation_id="inv-123",
        project_root_override=root,
    )
    recs = _read_spawn_runs(root)
    assert len(recs) == 1
    r = recs[0]
    # Every required correlation field present (design §G).
    for k in ("ts", "invocation_id", "cycle_id", "component_id", "bundle_hash",
              "request_id", "tool", "model", "status", "cost_usd",
              "duration_ms", "num_turns", "wall_clock_s"):
        assert k in r, f"missing correlation field {k!r}"
    assert r["invocation_id"] == "inv-123"
    assert r["component_id"] == "wiring-extract-static"
    assert r["bundle_hash"] == "a" * 64
    assert r["request_id"] == "b" * 32
    assert r["tool"] == "verification_arbiter"
    assert r["status"] == "VERIFIED"
    assert r["cost_usd"] == 0.0123
    assert r["duration_ms"] == 4210
    assert r["num_turns"] == 2
    assert r["wall_clock_s"] == 4.4


def test_null_usage_fields_persist_as_null(tmp_path):
    """The Codex / non-JSON path passes None for cost/duration/turns -> the
    record stores JSON null, not 0 or a crash."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    spawn_runs.record_spawn_run(
        tool="audit_codex",
        status="pass",
        cost_usd=None,
        duration_ms=None,
        num_turns=None,
        wall_clock_s=12.0,
        component_id="comp-x",
        project_root_override=root,
    )
    r = _read_spawn_runs(root)[0]
    assert r["cost_usd"] is None
    assert r["duration_ms"] is None
    assert r["num_turns"] is None
    assert r["wall_clock_s"] == 12.0
    # Unsupplied optional correlation fields default to null, not absent.
    assert r["request_id"] is None
    assert r["bundle_hash"] is None
    assert r["cycle_id"] is None
    # invocation_id is always minted even when not supplied.
    assert isinstance(r["invocation_id"], str) and r["invocation_id"]


def test_numeric_string_coercion(tmp_path):
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    spawn_runs.record_spawn_run(
        tool="audit_claude", status="pass",
        cost_usd="0.0456", duration_ms="3300", num_turns="1",
        wall_clock_s="3.5", project_root_override=root)
    r = _read_spawn_runs(root)[0]
    assert r["cost_usd"] == 0.0456
    assert r["duration_ms"] == 3300
    assert r["num_turns"] == 1
    assert r["wall_clock_s"] == 3.5


def test_appends_multiple_records(tmp_path):
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    for i in range(3):
        spawn_runs.record_spawn_run(
            tool="verification_arbiter", status="VERIFIED",
            cost_usd=0.01 * (i + 1), duration_ms=100 * (i + 1), num_turns=1,
            wall_clock_s=1.0, project_root_override=root)
    recs = _read_spawn_runs(root)
    assert len(recs) == 3
    assert [r["cost_usd"] for r in recs] == [0.01, 0.02, 0.03]


# ---------------------------------------------------------------------------
# Never-raise + byte-invariance
# ---------------------------------------------------------------------------

def test_never_raises_on_broken_writer(tmp_path, monkeypatch):
    """If the underlying append explodes, record_spawn_run swallows it."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)

    def _boom(*a, **k):
        raise RuntimeError("simulated writer explosion")

    monkeypatch.setattr(spawn_runs, "_append_event_line", _boom)
    # Must NOT raise.
    spawn_runs.record_spawn_run(
        tool="verification_arbiter", status="VERIFIED",
        cost_usd=0.01, duration_ms=100, num_turns=1, wall_clock_s=1.0,
        project_root_override=root)
    # And nothing was written.
    assert _read_spawn_runs(root) == []


def test_no_project_root_is_noop(tmp_path, monkeypatch):
    """With no discoverable project root and no override -> silent no-op."""
    monkeypatch.setattr(spawn_runs, "_discover_project_root", lambda *a, **k: None)
    # Must NOT raise and must NOT write anywhere.
    spawn_runs.record_spawn_run(
        tool="audit_claude", status="pass",
        cost_usd=0.01, duration_ms=100, num_turns=1, wall_clock_s=1.0)


def test_sidecar_does_not_touch_friction_or_gate_runs(tmp_path):
    """Byte-invariance of the EXISTING ledgers: writing a spawn-run leaves
    active.yaml / events.jsonl / gate-runs.jsonl untouched (design §4 #5)."""
    root = tmp_path / "proj"
    obs = root / ".process-observations"
    obs.mkdir(parents=True)
    # Seed pre-existing sibling ledgers.
    (obs / "active.yaml").write_text("seed-active\n", encoding="utf-8")
    (obs / "events.jsonl").write_text('{"seed":"event"}\n', encoding="utf-8")
    (obs / "gate-runs.jsonl").write_text('{"seed":"gate"}\n', encoding="utf-8")
    before = {p.name: p.read_bytes() for p in obs.iterdir() if p.is_file()}

    spawn_runs.record_spawn_run(
        tool="verification_arbiter", status="VERIFIED",
        cost_usd=0.01, duration_ms=100, num_turns=1, wall_clock_s=1.0,
        project_root_override=root)

    # The siblings are byte-identical; only spawn-runs.jsonl is new.
    for name, data in before.items():
        assert (obs / name).read_bytes() == data, f"{name} was perturbed"
    assert (obs / spawn_runs.SPAWN_RUNS_FILENAME).is_file()


def test_records_are_canonical_json(tmp_path):
    """Each line is canonical JSON (sorted keys, compact) like events.jsonl."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    spawn_runs.record_spawn_run(
        tool="audit_claude", status="pass",
        cost_usd=0.01, duration_ms=100, num_turns=1, wall_clock_s=1.0,
        project_root_override=root)
    raw = (root / ".process-observations" / spawn_runs.SPAWN_RUNS_FILENAME
           ).read_text(encoding="utf-8").strip()
    # Re-serialize canonically and compare -> proves sorted-keys/compact.
    obj = json.loads(raw)
    assert raw == json.dumps(obj, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
