#!/usr/bin/env python3
"""Unit tests for reconciler.reconcile() (WP-5 core).

Tests:
- P1 (static + agent): evidence merged, both sources in evidence[]
- P4 (manual): treated as assertion with confidence 0.8
- Orphan: src or dst component not in contract map -> status=orphan
- Stale: evidence tree hashes all older than current workspace_tree_hash
- Live: at least one evidence entry has current workspace_tree_hash
- Suppressed: edge_id in suppress list
- blocking_eligible: TRUE iff >=1 static_extract evidence AND static source status in {succeeded, partial}
- No static source succeeded -> blocking_eligible=FALSE even with static evidence
- Empty inputs -> 0 edges, valid snapshot
- All-agent-only -> blocking=0
- Deterministic: edges sorted by edge_id
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from reconciler import reconcile  # noqa: E402
from edge_identity import compute_edge_id  # noqa: E402


COMPONENTS = ["auth-service", "user-service", "db"]
TREE = "a" * 40
OLD_TREE = "b" * 40


def _edge(
    src="auth-service", src_sym="auth-service.validateToken",
    dst="db", dst_sym="db.User.select",
    kind="calls",
    source="static_extract",
    extractor="fastapi",
    version="1.0.0",
    tree=TREE,
    emitted="2026-04-14T12:00:00Z",
    confidence=None,
):
    e = {
        "schema_version": "1.0.0",
        "edge_id": compute_edge_id(src, src_sym, dst, dst_sym, kind),
        "src_component": src,
        "src_symbol": src_sym,
        "dst_component": dst,
        "dst_symbol": dst_sym,
        "edge_kind": kind,
        "evidence_source": source,
        "extractor_id": extractor,
        "extractor_version": version,
        "workspace_tree_hash": tree,
        "emitted_at": emitted,
    }
    if confidence is not None:
        e["confidence"] = confidence
    return e


def _manifest(static_status="succeeded"):
    return {
        "schema_version": "1.0.0",
        "run_id": "00000000-0000-0000-0000-000000000000",
        "workspace_tree_hash": TREE,
        "project_dir": "/tmp/x",
        "started_at": "2026-04-14T12:00:00Z",
        "sources": [
            {
                "source_id": "wiring-extract-static.fastapi",
                "evidence_source": "static_extract",
                "status": static_status,
                "output_path": "static.jsonl",
                "edge_count": 1,
                "completed_at": "2026-04-14T12:01:00Z",
            },
        ],
    }


def _reconcile(
    statics=(),
    asserteds=(),
    manuals=(),
    static_status="succeeded",
    components=COMPONENTS,
    tree=TREE,
    suppressed=(),
    previous=None,
):
    return reconcile(
        static_edges=list(statics),
        asserted_edges=list(asserteds),
        manual_edges=list(manuals),
        manifest=_manifest(static_status),
        contract_map_components=components,
        run_id="00000000-0000-0000-0000-000000000000",
        workspace_tree_hash=tree,
        generated_at="2026-04-14T12:02:00Z",
        snapshot_generation=1,
        previous_snapshot=previous,
        suppressed_edge_ids=list(suppressed),
    )


class TestPromotionRules(unittest.TestCase):

    def test_static_plus_agent_P1(self):
        s = _edge(source="static_extract", extractor="fastapi")
        a = _edge(source="agent_asserted", extractor="bob-assertion")
        snap = _reconcile(statics=[s], asserteds=[a])
        self.assertEqual(len(snap["edges"]), 1)
        ev = snap["edges"][0]["evidence"]
        self.assertEqual(len(ev), 2)
        sources = {e["evidence_source"] for e in ev}
        self.assertEqual(sources, {"static_extract", "agent_asserted"})
        self.assertTrue(snap["edges"][0]["blocking_eligible"])

    def test_manual_edge_P4(self):
        m = _edge(source="manual", extractor="human")
        snap = _reconcile(manuals=[m])
        self.assertEqual(len(snap["edges"]), 1)
        ev = snap["edges"][0]["evidence"][0]
        self.assertEqual(ev["evidence_source"], "manual")
        self.assertEqual(ev["confidence"], 0.8)
        # manual alone gives blocking_eligible=False (no static evidence)
        self.assertFalse(snap["edges"][0]["blocking_eligible"])

    def test_custom_confidence_round2(self):
        s = _edge(source="static_extract", confidence=0.87654321)
        snap = _reconcile(statics=[s])
        self.assertEqual(snap["edges"][0]["evidence"][0]["confidence"], 0.88)


class TestStatusDetermination(unittest.TestCase):

    def test_orphan_src(self):
        e = _edge(src="ghost", src_sym="ghost.doTrump", dst="db", dst_sym="db.go")
        snap = _reconcile(asserteds=[e], components=COMPONENTS)
        self.assertEqual(snap["edges"][0]["status"], "orphan")

    def test_orphan_dst(self):
        e = _edge(dst="nowhere", dst_sym="nowhere.stuff")
        snap = _reconcile(statics=[e], components=COMPONENTS)
        self.assertEqual(snap["edges"][0]["status"], "orphan")

    def test_stale_all_old(self):
        e = _edge(tree=OLD_TREE)
        snap = _reconcile(statics=[e], tree=TREE)
        self.assertEqual(snap["edges"][0]["status"], "stale")

    def test_live_at_least_one_current(self):
        new = _edge(tree=TREE, src_sym="a.new")
        snap = _reconcile(statics=[new], tree=TREE)
        self.assertEqual(snap["edges"][0]["status"], "live")

    def test_suppressed(self):
        e = _edge()
        eid = e["edge_id"]
        snap = _reconcile(statics=[e], suppressed=[eid])
        self.assertEqual(snap["edges"][0]["status"], "suppressed")


class TestBlockingEligibility(unittest.TestCase):

    def test_static_succeeded_sets_blocking(self):
        s = _edge()
        snap = _reconcile(statics=[s], static_status="succeeded")
        self.assertTrue(snap["edges"][0]["blocking_eligible"])

    def test_static_partial_sets_blocking(self):
        s = _edge()
        snap = _reconcile(statics=[s], static_status="partial")
        self.assertTrue(snap["edges"][0]["blocking_eligible"])

    def test_static_failed_no_blocking(self):
        s = _edge()
        snap = _reconcile(statics=[s], static_status="failed")
        self.assertFalse(snap["edges"][0]["blocking_eligible"])

    def test_agent_only_no_blocking(self):
        a = _edge(source="agent_asserted", extractor="bob-assertion")
        snap = _reconcile(asserteds=[a])
        self.assertFalse(snap["edges"][0]["blocking_eligible"])


class TestEmptyAndDeterminism(unittest.TestCase):

    def test_empty_inputs(self):
        snap = _reconcile()
        self.assertEqual(snap["edges"], [])
        self.assertEqual(snap["statistics"]["total_edges"], 0)
        self.assertEqual(snap["schema_version"], "1.0.0")

    def test_edges_sorted_by_edge_id(self):
        es = [
            _edge(src_sym="auth-service.f1"),
            _edge(src_sym="auth-service.f2"),
            _edge(src_sym="auth-service.f3"),
        ]
        snap = _reconcile(statics=es)
        ids = [e["edge_id"] for e in snap["edges"]]
        self.assertEqual(ids, sorted(ids))

    def test_components_aggregation(self):
        es = [
            _edge(src_sym="auth-service.f1", dst="user-service", dst_sym="user-service.get"),
            _edge(src_sym="auth-service.f2"),
        ]
        snap = _reconcile(statics=es)
        comps = {c["name"]: c for c in snap["components"]}
        self.assertIn("auth-service", comps)
        self.assertEqual(comps["auth-service"]["outbound_edge_count"], 2)
        self.assertEqual(comps["db"]["inbound_edge_count"], 1)

    def test_dedup_same_source_same_tree(self):
        # Two emissions of same edge from same extractor/tree/version collapse
        s1 = _edge()
        s2 = _edge(emitted="2026-04-14T13:00:00Z")
        snap = _reconcile(statics=[s1, s2])
        self.assertEqual(len(snap["edges"]), 1)
        self.assertEqual(len(snap["edges"][0]["evidence"]), 1)
        # last_seen_at updated to the latest
        self.assertEqual(snap["edges"][0]["evidence"][0]["last_seen_at"], "2026-04-14T13:00:00Z")

    def test_statistics_by_evidence_source(self):
        s = _edge(source="static_extract")
        a = _edge(source="agent_asserted", extractor="bob",
                  src_sym="auth-service.x")
        snap = _reconcile(statics=[s], asserteds=[a])
        bs = snap["statistics"]["by_evidence_source"]
        self.assertGreaterEqual(bs.get("static_extract", 0), 1)
        self.assertGreaterEqual(bs.get("agent_asserted", 0), 1)


if __name__ == "__main__":
    unittest.main()
