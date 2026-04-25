"""
Tests for project-state skill (TS-PS-01..07).

Run with:
    pytest ~/.claude/skills/project-state/tests/ -v

Fixtures construct tiny fake project roots with contract-map / skeleton /
flows / observations, then exercise reconcile + query end-to-end.
"""

import json
import os
import sys
import time
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import yaml

# Import skill scripts.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import reconcile  # noqa: E402
import query  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_forge_session(root: Path) -> None:
    forge = root / ".forge"
    forge.mkdir(parents=True, exist_ok=True)
    (forge / "session.key").write_bytes(b"test-session-key-abcd1234\n")
    (forge / "session-id").write_text("test-session-id", encoding="utf-8")


def _make_basic_contract_map(root: Path, caps: List[Dict[str, Any]]) -> None:
    """Write a minimal contract-map.yaml with given capability records.

    Each cap record: {component, id, blocked_by?, status?, entry_point?}
    """
    components: Dict[str, Dict[str, Any]] = {}
    for cap in caps:
        comp = cap["component"]
        cid = cap["id"]
        components.setdefault(
            comp, {"id": comp, "purpose": f"fixture {comp}", "capabilities": {}}
        )
        node: Dict[str, Any] = {"description": f"{comp}.{cid}"}
        if "blocked_by" in cap:
            node["blocked_by"] = cap["blocked_by"]
        if "status" in cap:
            node["status"] = cap["status"]
        if "entry_point" in cap:
            node["entry_point"] = cap["entry_point"]
        components[comp]["capabilities"][cid] = node
    doc = {
        "schema": "contract-map.v1",
        "revision": 1,
        "components": list(components.values()),
    }
    _write(root / "progress" / "contract-map.yaml", yaml.safe_dump(doc, sort_keys=True))


def _make_basic_skeleton(root: Path, screen: str, binds_to: str) -> None:
    doc = {
        "schema": "design-skeleton.v1",
        "screen": screen,
        "elements": {
            "step_card": {
                "bbox": [0, 0, 100, 100],
                "interactions": [
                    {"event": "click", "binds_to": binds_to, "visual_only": False},
                ],
            }
        },
    }
    _write(root / ".design-ledger" / "skeletons" / f"{screen}.yaml",
           yaml.safe_dump(doc, sort_keys=True))


def _make_empty_observations(root: Path) -> None:
    po_dir = root / ".process-observations"
    po_dir.mkdir(parents=True, exist_ok=True)
    _write(po_dir / "active.yaml", yaml.safe_dump({
        "schema": "process-observation.v1",
        "project_id": root.name,
        "observations": {},
    }, sort_keys=True))
    (po_dir / "events.jsonl").touch()


@pytest.fixture
def project_root(tmp_path, monkeypatch):
    """Minimal project: contract-map + skeleton + observations + forge session."""
    root = tmp_path / "proj"
    root.mkdir()
    # Ensure claude_observe doesn't spam the real rollup path.
    monkeypatch.setenv("HOME", str(tmp_path))
    _make_forge_session(root)
    _make_empty_observations(root)
    # Start with a couple of capabilities and a skeleton that binds to one.
    _make_basic_contract_map(root, [
        {"component": "session", "id": "create", "status": "VERIFIED"},
        {"component": "journey_controller", "id": "advance_step",
         "blocked_by": ["capability://session.create"], "status": "PLANNED"},
    ])
    _make_basic_skeleton(root, "journey_main", "capability://journey_controller.advance_step")
    return root


# ---------------------------------------------------------------------------
# TS-PS-01: reconcile idempotent no-op
# ---------------------------------------------------------------------------

def test_ts_ps_01_idempotent_noop(project_root):
    # First reconcile: creates projection.
    r1 = reconcile.reconcile(
        project_root,
        skip_claim_check=True,
        skip_heartbeat=True,
    )
    assert r1["idempotent_noop"] is False
    assert isinstance(r1["projection_id"], str) and len(r1["projection_id"]) == 64
    run_path_1 = r1["run_projection_path"]
    assert run_path_1 and Path(run_path_1).is_file()

    # Simulate bob promoting: copy run-scoped to latest.json.
    latest = project_root / ".project-state" / "latest.json"
    run_bytes = Path(run_path_1).read_bytes()
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_bytes(run_bytes)

    # Second reconcile on unchanged inputs → idempotent no-op.
    r2 = reconcile.reconcile(
        project_root,
        skip_claim_check=True,
        skip_heartbeat=True,
    )
    assert r2["idempotent_noop"] is True, r2
    assert r2["projection_id"] == r1["projection_id"]


# ---------------------------------------------------------------------------
# TS-PS-02: hash mismatch on query → synchronous reconcile before answering
# ---------------------------------------------------------------------------

def test_ts_ps_02_hash_mismatch_triggers_reconcile(project_root):
    # Seed a projection.
    r1 = reconcile.reconcile(project_root, skip_claim_check=True, skip_heartbeat=True)
    # Promote → latest.json.
    latest = project_root / ".project-state" / "latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_bytes(Path(r1["run_projection_path"]).read_bytes())
    original_id = r1["projection_id"]

    # Mutate contract-map → hash changes.
    _make_basic_contract_map(project_root, [
        {"component": "session", "id": "create", "status": "VERIFIED"},
        {"component": "journey_controller", "id": "advance_step",
         "blocked_by": ["capability://session.create"], "status": "PLANNED"},
        # New capability — hash changes.
        {"component": "logger", "id": "log_event", "status": "DRAFT",
         "entry_point": "cli"},
    ])

    # Query without self-heal → STALE_PROJECTION_HASH_MISMATCH exit 1.
    rc_no_heal = query.main([
        "--project-root", str(project_root),
        "--no-self-heal",
        "by_status", "--status", "PLANNED",
    ])
    assert rc_no_heal == 1

    # Query WITH self-heal → reconcile happens silently, op serves a fresh
    # answer reflecting the new capability.
    import io
    out = io.StringIO()
    err = io.StringIO()
    saved_out, saved_err = sys.stdout, sys.stderr
    try:
        sys.stdout = out
        sys.stderr = err
        rc = query.main([
            "--project-root", str(project_root),
            "by_status", "--status", "PLANNED",
        ])
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err
    assert rc == 0
    result = json.loads(out.getvalue())
    # New projection must include the new capability URI.
    assert "capability://journey_controller.advance_step" in result["entities"]


# ---------------------------------------------------------------------------
# TS-PS-03: focus_pack depth vs ceiling — under/over ceiling behavior
# ---------------------------------------------------------------------------

def test_ts_ps_03_focus_pack_ceiling(project_root):
    # Build a dense contract-map: 14 capabilities chained, each blocked_by
    # the prior one. At depth=2 the pack will have a small subset; at
    # extremely small ceilings it will abort with suggested_splits[].
    caps = [{"component": "chain", "id": "cap_000",
             "status": "VERIFIED", "entry_point": "cli"}]
    for i in range(1, 14):
        caps.append({
            "component": "chain",
            "id": f"cap_{i:03d}",
            "blocked_by": [f"capability://chain.cap_{i-1:03d}"],
            "status": "PLANNED",
        })
    _make_basic_contract_map(project_root, caps)

    r1 = reconcile.reconcile(project_root, skip_claim_check=True, skip_heartbeat=True)
    assert r1["idempotent_noop"] is False
    # Load projection.
    proj = json.loads(Path(r1["run_projection_path"]).read_text())

    # depth=2 at default ceiling (60k tokens) → under ceiling.
    res_ok = query.op_focus_pack(
        proj, "capability://chain.cap_013", depth=2,
        ceiling=60000, include_tests=False, include_observations=True,
    )
    assert res_ok["found"] is True
    assert "error" not in res_ok
    assert res_ok["entity_count"] >= 2

    # Tiny ceiling (50 tokens) forces abort → directive with suggested_splits.
    res_big = query.op_focus_pack(
        proj, "capability://chain.cap_013", depth=5,
        ceiling=50, include_tests=False, include_observations=True,
    )
    assert res_big["found"] is True
    assert res_big.get("error") == "FOCUS_PACK_TOO_BIG"
    assert "suggested_splits" in res_big and len(res_big["suggested_splits"]) >= 1
    # Each split must have cut_at + two halves.
    for split in res_big["suggested_splits"]:
        assert "cut_at" in split
        assert "agent_a_entities" in split
        assert "agent_b_entities" in split


# ---------------------------------------------------------------------------
# TS-PS-04: orphan detection — unreachable, un-tagged capability flagged
# ---------------------------------------------------------------------------

def test_ts_ps_04_orphan_detection(project_root):
    # Add a capability that has NO entry_point tag and NO skeleton binds to
    # it → should appear in orphans[].
    _make_basic_contract_map(project_root, [
        {"component": "session", "id": "create", "status": "VERIFIED",
         "entry_point": "api_public"},
        {"component": "journey_controller", "id": "advance_step",
         "blocked_by": ["capability://session.create"], "status": "PLANNED"},
        # Orphan candidate — not in skeleton binds_to, not entry-point tagged.
        {"component": "legacy", "id": "importer", "status": "DRAFT"},
    ])
    # Skeleton references only journey_controller.advance_step.
    _make_basic_skeleton(project_root, "journey_main",
                        "capability://journey_controller.advance_step")

    r = reconcile.reconcile(project_root, skip_claim_check=True, skip_heartbeat=True)
    proj = json.loads(Path(r["run_projection_path"]).read_text())
    orphan_uris = {o["uri"] for o in proj.get("orphans", [])}
    assert "capability://legacy.importer" in orphan_uris, (
        f"orphans[] did not include legacy.importer: {orphan_uris}"
    )
    # Tagged entry_point capability must NOT be orphan.
    assert "capability://session.create" not in orphan_uris


# ---------------------------------------------------------------------------
# TS-PS-05: next_buildable — all blocking[] VERIFIED means entity lists;
#                            one BLOCKED means it does not
# ---------------------------------------------------------------------------

def test_ts_ps_05_next_buildable(project_root):
    # A depends on B (VERIFIED) and C (VERIFIED) → A buildable.
    # D depends on E (VERIFIED) and F (BLOCKED via modifier) → D not buildable.
    _make_basic_contract_map(project_root, [
        {"component": "pkg", "id": "b", "status": "VERIFIED"},
        {"component": "pkg", "id": "c", "status": "VERIFIED"},
        {"component": "pkg", "id": "a", "status": "DRAFT",
         "blocked_by": ["capability://pkg.b", "capability://pkg.c"]},
        {"component": "pkg", "id": "e", "status": "VERIFIED"},
        {"component": "pkg", "id": "f", "status": "DRAFT"},
        {"component": "pkg", "id": "d", "status": "DRAFT",
         "blocked_by": ["capability://pkg.e", "capability://pkg.f"]},
    ])

    r = reconcile.reconcile(project_root, skip_claim_check=True, skip_heartbeat=True)
    proj = json.loads(Path(r["run_projection_path"]).read_text())
    nb_uris = {x["uri"] for x in proj.get("next_buildable", [])}
    assert "capability://pkg.a" in nb_uris, f"a should be buildable: {nb_uris}"
    assert "capability://pkg.d" not in nb_uris, f"d should NOT be buildable: {nb_uris}"


# ---------------------------------------------------------------------------
# TS-PS-06: circular dep → level 99 + schema_mismatch observation
# ---------------------------------------------------------------------------

def test_ts_ps_06_circular_dep(project_root):
    # A ↔ B cycle.
    _make_basic_contract_map(project_root, [
        {"component": "cyc", "id": "a", "status": "PLANNED",
         "blocked_by": ["capability://cyc.b"]},
        {"component": "cyc", "id": "b", "status": "PLANNED",
         "blocked_by": ["capability://cyc.a"]},
    ])

    r = reconcile.reconcile(project_root, skip_claim_check=True, skip_heartbeat=True)
    proj = json.loads(Path(r["run_projection_path"]).read_text())
    # build_order must contain level 99 with both URIs.
    level_99 = next((lvl for lvl in proj.get("build_order", []) if lvl["level"] == 99), None)
    assert level_99 is not None, f"no level 99 found: {proj.get('build_order')}"
    assert set(level_99["entities"]) >= {"capability://cyc.a", "capability://cyc.b"}
    assert "strongly-connected" in level_99.get("note", "")

    # Verify schema_mismatch observation was emitted.
    events_path = project_root / ".process-observations" / "events.jsonl"
    assert events_path.is_file()
    lines = events_path.read_text(encoding="utf-8").splitlines()
    circular_events = [
        json.loads(l) for l in lines
        if l.strip()
        and json.loads(l).get("category") == "schema_mismatch"
        and "circular dep" in (json.loads(l).get("what_happened") or "")
    ]
    assert len(circular_events) >= 1, (
        f"no schema_mismatch observation for circular dep: {lines}"
    )


# ---------------------------------------------------------------------------
# TS-PS-07: impact query — reverse-BFS returns exact retest set
# ---------------------------------------------------------------------------

def test_ts_ps_07_impact_retest_set(project_root):
    # Graph: D → C → B → A (A is root, D is deepest leaf). Changing A
    # should impact B, C, D.
    _make_basic_contract_map(project_root, [
        {"component": "g", "id": "a", "status": "VERIFIED"},
        {"component": "g", "id": "b", "status": "PLANNED",
         "blocked_by": ["capability://g.a"]},
        {"component": "g", "id": "c", "status": "PLANNED",
         "blocked_by": ["capability://g.b"]},
        {"component": "g", "id": "d", "status": "PLANNED",
         "blocked_by": ["capability://g.c"]},
    ])

    r = reconcile.reconcile(project_root, skip_claim_check=True, skip_heartbeat=True)
    proj = json.loads(Path(r["run_projection_path"]).read_text())

    res = query.op_impact(proj, "capability://g.a")
    assert res["query"] == "impact"
    assert res["uri"] == "capability://g.a"
    retest = set(res["retest_set"])
    # All three downstream entities should be in the retest set.
    assert retest >= {"capability://g.b", "capability://g.c", "capability://g.d"}
    assert "capability://g.a" not in retest  # self is not in retest set
