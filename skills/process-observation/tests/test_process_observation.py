"""
Tests for process-observation skill (TS-OBS-01..07).

Run with:
    pytest ~/.claude/skills/process-observation/tests/ -v
"""

import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Make the scripts dir importable (no PYTHONPATH hacks required at runtime).
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import yaml  # noqa: E402

import write  # noqa: E402
from write import (  # noqa: E402
    claude_observe, compute_dedup_key, append_event_line,
    load_active, upsert_active, dump_active, _build_event,
    anonymize_for_global, shape_only, now_iso, parse_iso,
    discover_project_root, resolve_session_id,
)
import query  # noqa: E402
import sweep  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_root(tmp_path, monkeypatch):
    """Isolated project root with .process-observations/ pre-created."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    # Make project-root discovery deterministic for CLI subprocess tests.
    monkeypatch.chdir(root)
    # Point global rollup at a temp location so these tests never pollute ~/
    monkeypatch.setattr(
        write, "GLOBAL_ROLLUP_PATH",
        tmp_path / "state" / "observations.jsonl",
    )
    monkeypatch.setenv("CLAUDE_SESSION_ID", "test-session-fixed")
    monkeypatch.delenv("FORGE_SESSION_ID", raising=False)
    return root


def _read_events(obs_dir: Path):
    path = obs_dir / "events.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _read_active(obs_dir: Path):
    path = obs_dir / "active.yaml"
    if not path.is_file():
        return {"observations": {}}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"observations": {}}


# ---------------------------------------------------------------------------
# TS-OBS-01: first write creates aggregate + event; second same dedup_key
# increments count, refreshes last_seen.
# ---------------------------------------------------------------------------

def test_ts_obs_01_first_write_creates_second_increments(project_root):
    claude_observe(
        category="agent_drift",
        subject_id="bob",
        what_happened="bob attempted UI-VERIFIED transition without verdict",
        fingerprint="hardrule-6",
        subject_type="agent",
        severity="blocking",
        project_root_override=project_root,
    )

    obs_dir = project_root / ".process-observations"
    active = _read_active(obs_dir)
    events = _read_events(obs_dir)
    assert len(events) == 1
    assert len(active["observations"]) == 1

    key = "agent_drift:bob:hardrule-6"
    entry = active["observations"][key]
    assert entry["count"] == 1
    assert entry["count_last_7d"] == 1
    assert entry["first_seen"] == entry["last_seen"]
    assert entry["severity"] == "blocking"

    first_last_seen = entry["last_seen"]

    # Ensure a distinct timestamp on the second write
    time.sleep(1.1)

    claude_observe(
        category="agent_drift",
        subject_id="bob",
        what_happened="bob attempted UI-VERIFIED transition without verdict (again)",
        fingerprint="hardrule-6",
        subject_type="agent",
        severity="blocking",
        project_root_override=project_root,
    )

    active = _read_active(obs_dir)
    events = _read_events(obs_dir)
    assert len(events) == 2
    assert len(active["observations"]) == 1
    entry = active["observations"][key]
    assert entry["count"] == 2
    assert entry["last_seen"] > first_last_seen
    assert entry["first_seen"] == first_last_seen
    assert len(entry["evidence_tail"]) == 2


# ---------------------------------------------------------------------------
# TS-OBS-02: P95 < 50ms latency over 100 sequential writes.
# ---------------------------------------------------------------------------

def test_ts_obs_02_latency_p95_under_50ms(project_root):
    latencies = []
    for i in range(100):
        t0 = time.perf_counter()
        claude_observe(
            category="external_tool_fail",
            subject_id="codex",
            what_happened=f"returncode-2 on request {i}",
            fingerprint=f"returncode-{i % 5}",   # 5 dedup buckets
            subject_type="external_tool",
            severity="degraded",
            project_root_override=project_root,
        )
        latencies.append((time.perf_counter() - t0) * 1000.0)

    p50 = statistics.median(latencies)
    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    p99 = latencies[int(len(latencies) * 0.99) - 1]
    # Emit for CI visibility
    sys.stderr.write(
        f"LATENCY p50={p50:.2f}ms p95={p95:.2f}ms p99={p99:.2f}ms "
        f"max={max(latencies):.2f}ms\n"
    )
    assert p95 < 50.0, f"P95 latency {p95:.2f}ms exceeds 50ms budget"


# ---------------------------------------------------------------------------
# TS-OBS-03: sweep demotes 15-day-old observation to stale.yaml, evidence_tail
# removed.
# ---------------------------------------------------------------------------

def test_ts_obs_03_sweep_demotes_aged_and_resolved(project_root):
    obs_dir = project_root / ".process-observations"
    # Seed an aged open entry and a resolved entry directly via upsert
    doc = load_active(obs_dir, project_root.name)
    fifteen_days_ago = (datetime.now(timezone.utc) - timedelta(days=15)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    aged = _build_event(
        dedup_key="gate_false_block:g1:aged-case",
        category="gate_false_block",
        severity="blocking",
        subject_type="gate",
        subject_id="g1",
        subject_version="old",
        session_id="s-old",
        observed_by="test",
        what_happened="aged gate refusal from 15 days ago",
        related=[],
        root_cause_hypothesis=None,
        suggested_fix=None,
    )
    aged["ts"] = fifteen_days_ago
    doc = upsert_active(doc, aged)
    # Force first_seen + last_seen to 15-day-old for this entry
    doc["observations"]["gate_false_block:g1:aged-case"]["first_seen"] = fifteen_days_ago
    doc["observations"]["gate_false_block:g1:aged-case"]["last_seen"] = fifteen_days_ago
    doc["observations"]["gate_false_block:g1:aged-case"]["evidence_tail"] = [{
        "event_id": "ev-old", "ts": fifteen_days_ago, "session_id": "s-old",
        "observed_by": "test", "severity": "blocking",
    }]

    resolved = _build_event(
        dedup_key="skill_bug:foo:resolved-case",
        category="skill_bug",
        severity="degraded",
        subject_type="skill",
        subject_id="foo",
        subject_version="v1",
        session_id="s-new",
        observed_by="test",
        what_happened="skill foo had a bug (since fixed)",
        related=[],
        root_cause_hypothesis=None,
        suggested_fix=None,
    )
    resolved["ts"] = recent
    doc = upsert_active(doc, resolved)
    doc["observations"]["skill_bug:foo:resolved-case"]["status"] = "resolved"
    doc["observations"]["skill_bug:foo:resolved-case"]["last_seen"] = recent
    doc["observations"]["skill_bug:foo:resolved-case"]["resolution"] = {
        "by": "test", "at": recent, "note": "fixed",
    }

    # Also seed a fresh active-still entry that MUST stay in active.yaml
    fresh = _build_event(
        dedup_key="flow_gap:pa:fresh-case",
        category="flow_gap",
        severity="degraded",
        subject_type="skill",
        subject_id="pa",
        subject_version="v1",
        session_id="s-new",
        observed_by="test",
        what_happened="pa flow gap seen today",
        related=[],
        root_cause_hypothesis=None,
        suggested_fix=None,
    )
    fresh["ts"] = recent
    doc = upsert_active(doc, fresh)
    dump_active(obs_dir, doc)

    # Run sweep
    result = sweep.run_sweep(project_root, force=True)
    assert result["demoted_age"] >= 1
    assert result["demoted_resolved"] >= 1
    assert result["retained"] >= 1

    active = _read_active(obs_dir)
    assert "gate_false_block:g1:aged-case" not in active.get("observations", {})
    assert "skill_bug:foo:resolved-case" not in active.get("observations", {})
    assert "flow_gap:pa:fresh-case" in active.get("observations", {})

    stale_doc = yaml.safe_load((obs_dir / "stale.yaml").read_text(encoding="utf-8"))
    stale_obs = stale_doc.get("observations") or {}
    assert "gate_false_block:g1:aged-case" in stale_obs
    assert "skill_bug:foo:resolved-case" in stale_obs
    # Compressed: evidence_tail MUST be absent
    assert "evidence_tail" not in stale_obs["gate_false_block:g1:aged-case"]
    assert "evidence_tail" not in stale_obs["skill_bug:foo:resolved-case"]
    # Sentinel written
    assert (obs_dir / ".last_sweep").is_file()


# ---------------------------------------------------------------------------
# TS-OBS-04: rebuild from events.jsonl regenerates active.yaml byte-for-byte.
# ---------------------------------------------------------------------------

def _rebuild_from_events(obs_dir: Path, project_id: str) -> dict:
    """Synthesize an active.yaml doc by replaying events.jsonl."""
    doc = {
        "schema": write.SCHEMA_AGGREGATE,
        "project_id": project_id,
        "generated_at": now_iso(),
        "observations": {},
    }
    events_path = obs_dir / "events.jsonl"
    if not events_path.is_file():
        return doc
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        ev = json.loads(line)
        doc = upsert_active(doc, ev)
    return doc


def test_ts_obs_04_rebuild_from_events_matches_active(project_root):
    # Fire a mix of writes across a few dedup keys
    for i in range(6):
        claude_observe(
            category="external_tool_slow",
            subject_id="gemini",
            what_happened=f"timeout-60s attempt {i}",
            fingerprint="timeout-60s",
            subject_type="external_tool",
            severity="slow",
            project_root_override=project_root,
        )
    for i in range(3):
        claude_observe(
            category="agent_drift",
            subject_id="bob",
            what_happened=f"hardrule-3 attempt {i}",
            fingerprint="hardrule-3",
            subject_type="agent",
            severity="blocking",
            project_root_override=project_root,
        )

    obs_dir = project_root / ".process-observations"
    # Compare normalized observation maps (ignore generated_at which is
    # always "now"). The rebuild should yield the same count + last_seen
    # shape as the accumulated active.yaml.
    rebuilt = _rebuild_from_events(obs_dir, project_root.name)
    active = load_active(obs_dir, project_root.name)

    def _canon(doc):
        obs = doc.get("observations") or {}
        out = {}
        for k, entry in obs.items():
            out[k] = {
                "count": entry.get("count"),
                "first_seen": entry.get("first_seen"),
                "last_seen": entry.get("last_seen"),
                "dedup_key": entry.get("dedup_key"),
                "category": entry.get("category"),
                "severity": entry.get("severity"),
                "subject": entry.get("subject"),
                "evidence_tail_len": len(entry.get("evidence_tail") or []),
            }
        return out

    assert _canon(rebuilt) == _canon(active)


# ---------------------------------------------------------------------------
# TS-OBS-05: anonymization - subject.id 'bob' redacted, paths/UUIDs redacted.
# ---------------------------------------------------------------------------

def test_ts_obs_05_anonymization_redacts_pii(project_root):
    event = _build_event(
        dedup_key="agent_drift:bob:hardrule-3",
        category="agent_drift",
        severity="blocking",
        subject_type="agent",
        subject_id="bob",
        subject_version="5ddc0cb",
        session_id="s-1234",
        observed_by="test",
        what_happened=(
            "bob at /home/adm01/.claude/skills/foo violated "
            "uuid abc123def4567890abcdef0123456789 "
            'with message "secret data" on task://43'
        ),
        related=["file:///tmp/evidence/abc.log"],
        root_cause_hypothesis=None,
        suggested_fix=None,
    )
    anon = anonymize_for_global(event, str(project_root))
    # subject.id must not appear; subject_type preserved
    assert "bob" not in json.dumps(anon), anon
    assert anon["subject_type"] == "agent"
    assert anon["category"] == "agent_drift"
    assert anon["severity"] == "blocking"
    # what_shape: paths, quoted strings, hashes redacted; task id normalized
    shape = anon["what_shape"]
    assert "/home/adm01" not in shape
    assert "abc123def4567890" not in shape
    assert '"secret data"' not in shape
    assert "<path>" in shape or "<hash>" in shape  # at least one redaction
    assert "task://<N>" in shape


# ---------------------------------------------------------------------------
# TS-OBS-06: query hot with severity-keyed thresholds; count_last_7d drives
# promotion.
# ---------------------------------------------------------------------------

def test_ts_obs_06_query_hot_severity_thresholds(project_root):
    # blocking -> threshold 2: fire twice to be hot
    for i in range(2):
        claude_observe(
            category="gate_false_block",
            subject_id="g1",
            what_happened="g1 refused unsigned contract map",
            fingerprint="unsigned",
            subject_type="gate",
            severity="blocking",
            project_root_override=project_root,
        )
    # degraded -> threshold 5: fire 5 to be hot
    for i in range(5):
        claude_observe(
            category="external_tool_fail",
            subject_id="codex",
            what_happened=f"returncode-2 attempt {i}",
            fingerprint="returncode-2",
            subject_type="external_tool",
            severity="degraded",
            project_root_override=project_root,
        )
    # noisy -> threshold 20: fire only 3 (should NOT appear)
    for i in range(3):
        claude_observe(
            category="external_tool_slow",
            subject_id="copilot",
            what_happened=f"noisy-{i}",
            fingerprint="slow-noise",
            subject_type="external_tool",
            severity="noisy",
            project_root_override=project_root,
        )

    # count_last_7d is derived from evidence_tail which has max 10 entries
    # and was incremented atomically in upsert. Re-check the aggregate:
    active = _read_active(project_root / ".process-observations")
    blk = active["observations"]["gate_false_block:g1:unsigned"]
    assert blk["count"] == 2
    deg = active["observations"]["external_tool_fail:codex:returncode-2"]
    assert deg["count"] == 5

    hot = query.op_hot(project_root, threshold=None, window_s=7 * 86400, min_severity="noisy")
    hot_keys = {h["dedup_key"] for h in hot}
    assert "gate_false_block:g1:unsigned" in hot_keys
    assert "external_tool_fail:codex:returncode-2" in hot_keys
    assert "external_tool_slow:copilot:slow-noise" not in hot_keys

    # With min-severity=blocking only blocking should remain hot
    hot2 = query.op_hot(project_root, threshold=None, window_s=7 * 86400,
                        min_severity="blocking")
    assert {h["dedup_key"] for h in hot2} == {"gate_false_block:g1:unsigned"}


# ---------------------------------------------------------------------------
# TS-OBS-07: self-referential guard - claude-observe bypasses its own hook.
# ---------------------------------------------------------------------------

def test_ts_obs_07_self_referential_guard_bypasses_hook(project_root, capsys):
    # Issue an observation with subject_id == "process-observation".
    claude_observe(
        category="skill_bug",
        subject_id="process-observation",
        what_happened="this would infinite-loop if not guarded",
        fingerprint="self-ref",
        subject_type="skill",
        severity="blocking",
        project_root_override=project_root,
    )
    captured = capsys.readouterr()
    assert "OBSERVATION_SELF_REFERENTIAL" in captured.err
    obs_dir = project_root / ".process-observations"
    active = _read_active(obs_dir)
    # Nothing persisted
    assert active.get("observations") == {} or active.get("observations") is None
    # events.jsonl either absent or empty
    evp = obs_dir / "events.jsonl"
    if evp.is_file():
        assert evp.read_text(encoding="utf-8").strip() == ""


# ---------------------------------------------------------------------------
# Bonus: dedup key canonicalization tested directly.
# ---------------------------------------------------------------------------

def test_compute_dedup_key_auto_fingerprint_shape():
    key = compute_dedup_key("agent_drift", "bob", None, "hello world")
    expected_fp = hashlib.sha256(b"hello world").hexdigest()[:8]
    assert key == f"agent_drift:bob:{expected_fp}"


def test_compute_dedup_key_explicit_fingerprint_lower_and_truncated():
    raw = "X" * 200
    key = compute_dedup_key("AGENT_DRIFT", "BoB!?", raw, "text")
    # All lowercase, punctuation replaced with '-', truncated <= 120
    assert key == key.lower()
    assert len(key) <= 120
    assert ":" in key
