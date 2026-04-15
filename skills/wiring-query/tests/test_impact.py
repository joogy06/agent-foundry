#!/usr/bin/env python3
"""test_impact.py — impact() op tests.

Covers contract-map test_scenarios for wiring-query:
  - impact_basic
  - anchor_not_found
  - snapshot_missing (covered in test_loader)
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(FIXTURE_DIR))

from graph_ops import impact, build_symbol_index  # noqa: E402
from make_fixture_snapshot import build_snapshot  # noqa: E402


class ImpactCase(unittest.TestCase):
    def setUp(self):
        self.snap = build_snapshot(snapshot_generation=42)
        self.idx = build_symbol_index(self.snap)

    def test_impact_basic(self):
        """impact(validateToken, depth=3) returns live reachable edges."""
        res = impact(self.snap, "auth-service.validateToken",
                     max_depth=3, index=self.idx)
        self.assertTrue(res["anchor_found"])
        self.assertEqual(res["snapshot_generation"], 42)
        # Expected reachable live edges (exclude stale/orphan/suppressed):
        #   validateToken -> lookupSession (calls)
        #   validateToken -> getUser (calls)
        #   getUser       -> db.users.select (reads_from)  [via getUser hop2]
        #   lookupSession -> db.sessions.select (reads_from) [hop2]
        #   validateToken -> audit-log.append (emits) [agent_asserted only]
        #   audit-log.append -> db.audit.insert (persists_to) [hop2 via audit-log]
        # Note: db.users.select, db.sessions.select, db.audit.insert can also
        # expose in-edges to include ALL reads_from/persists_to targets.
        # Our BFS walks both out and in, so at depth 3 we should see >= 5 edges.
        self.assertGreaterEqual(len(res["edges"]), 5)
        self.assertIn("auth-service", res["components_touched"])
        self.assertIn("db", res["components_touched"])
        # Agent-asserted edge should have blocking_eligible=false
        agent_edges = [e for e in res["edges"]
                        if "agent_asserted" in ":".join(e.get("evidence_summary", []))]
        if agent_edges:
            self.assertFalse(agent_edges[0]["blocking_eligible"])

    def test_impact_excludes_stale_by_default(self):
        # deprecatedFn edge is stale; must NOT show up unless include_stale=True
        res = impact(self.snap, "auth-service.deprecatedFn",
                     max_depth=3, index=self.idx, include_stale=False)
        self.assertEqual(len(res["edges"]), 0)
        # Now with include_stale=True the stale edge is walked
        res2 = impact(self.snap, "auth-service.deprecatedFn",
                      max_depth=3, index=self.idx, include_stale=True)
        self.assertGreater(len(res2["edges"]), 0)

    def test_anchor_not_found_returns_suggestions(self):
        res = impact(self.snap, "auth-service.validateTokn",  # typo
                     max_depth=3, index=self.idx)
        self.assertFalse(res["anchor_found"])
        self.assertIn("suggestions", res)
        # At least one suggestion should point to the real symbol
        joined = " ".join(res["suggestions"])
        self.assertIn("validateToken", joined)

    def test_impact_respects_depth(self):
        # depth=1 from validateToken => only direct edges (not multi-hop DB reads)
        res = impact(self.snap, "auth-service.validateToken",
                     max_depth=1, index=self.idx)
        # Depth=1: only edges touching validateToken directly
        hop1_count = res["hop_counts"].get("1", 0)
        self.assertGreater(hop1_count, 0)
        self.assertEqual(res["hop_counts"].get("2", 0), 0)

    def test_impact_depth3_under_50ms_10k_edges(self):
        """Performance target: BFS depth 3 on 10k edges <50ms per design §5.3."""
        import time
        # Build a 10k-edge synthetic snapshot
        edges = []
        from edge_identity import compute_edge_id  # type: ignore
        for i in range(10_000):
            s_sym = f"comp-A.func_{i}"
            d_sym = f"comp-B.func_{i % 500}"  # some clustering
            eid = compute_edge_id("comp-A", s_sym, "comp-B", d_sym, "calls")
            edges.append({
                "edge_id": eid,
                "src_component": "comp-A",
                "src_symbol": s_sym,
                "dst_component": "comp-B",
                "dst_symbol": d_sym,
                "edge_kind": "calls",
                "status": "live",
                "blocking_eligible": True,
                "evidence": [{
                    "evidence_source": "static_extract",
                    "extractor_id": "x", "extractor_version": "1.0.0",
                    "last_seen_at": "2026-04-15T02:00:00Z",
                    "workspace_tree_hash": "a" * 40,
                }],
            })
        snap = {
            "schema_version": "1.0.0",
            "snapshot_id": "0" * 16,
            "snapshot_generation": 1,
            "run_id": "00000000-0000-0000-0000-000000000001",
            "workspace_tree_hash": "0" * 40,
            "generated_at": "2026-04-15T02:00:00Z",
            "generated_by": "wiring-reconcile@1.0.0",
            "source_statuses": {},
            "edges": edges,
        }
        idx = build_symbol_index(snap)
        t0 = time.perf_counter()
        impact(snap, "comp-A.func_0", max_depth=3, index=idx)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 50.0,
                        f"BFS took {elapsed_ms:.2f}ms, budget 50ms")

    def test_deterministic_output(self):
        """Same inputs -> same edges list in the same order."""
        r1 = impact(self.snap, "auth-service.validateToken", max_depth=3,
                    index=self.idx)
        r2 = impact(self.snap, "auth-service.validateToken", max_depth=3,
                    index=self.idx)
        self.assertEqual([e["edge_id"] for e in r1["edges"]],
                         [e["edge_id"] for e in r2["edges"]])


if __name__ == "__main__":
    unittest.main()
