#!/usr/bin/env python3
"""test_subgraph.py — subgraph_for_llm() op tests.

Covers contract-map test_scenarios for wiring-query:
  - subgraph_token_budget
  - (anchor_not_found covered in test_impact.py)
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(FIXTURE_DIR))

from graph_ops import subgraph_for_llm, build_symbol_index  # noqa: E402
from make_fixture_snapshot import build_snapshot  # noqa: E402


class SubgraphCase(unittest.TestCase):
    def setUp(self):
        self.snap = build_snapshot(snapshot_generation=7)
        self.idx = build_symbol_index(self.snap)

    def test_single_anchor_yields_edges(self):
        res = subgraph_for_llm(
            self.snap,
            anchors=["auth-service.validateToken"],
            max_edges=40, max_tokens=50000, max_depth=2,
            index=self.idx,
        )
        self.assertEqual(res["snapshot_generation"], 7)
        self.assertTrue(res["anchors_found"]["auth-service.validateToken"])
        self.assertGreater(len(res["edges"]), 0)
        self.assertFalse(res["truncated"])

    def test_multiple_anchors_union(self):
        res = subgraph_for_llm(
            self.snap,
            anchors=["auth-service.validateToken", "audit-log.append"],
            max_edges=40, max_tokens=50000, max_depth=2,
            index=self.idx,
        )
        # Both anchors should be found
        self.assertTrue(all(res["anchors_found"].values()))
        # audit-log.append pulls its in-edge plus out-edge
        self.assertIn("audit-log", res["components_touched"])

    def test_max_edges_truncation(self):
        # Use a tiny budget to force truncation
        res = subgraph_for_llm(
            self.snap,
            anchors=["auth-service.validateToken"],
            max_edges=2, max_tokens=50000, max_depth=3,
            index=self.idx,
        )
        self.assertTrue(res["truncated"])
        self.assertEqual(len(res["edges"]), 2)
        self.assertGreater(res["omitted_edge_count"], 0)

    def test_max_tokens_truncation(self):
        # Very small token budget => truncation by tokens
        res = subgraph_for_llm(
            self.snap,
            anchors=["auth-service.validateToken"],
            max_edges=40,
            max_tokens=200,  # only 1 edge fits at 160 tokens/edge
            max_depth=3,
            index=self.idx,
        )
        self.assertTrue(res["truncated"])
        self.assertLessEqual(len(res["edges"]), 1)

    def test_missing_anchor_gets_suggestions(self):
        res = subgraph_for_llm(
            self.snap,
            anchors=["auth-service.validateTokn"],  # typo
            max_edges=40, max_tokens=50000, max_depth=2,
            index=self.idx,
        )
        self.assertFalse(res["anchors_found"]["auth-service.validateTokn"])
        self.assertIn("auth-service.validateTokn", res["suggestions"])

    def test_summary_md_present(self):
        res = subgraph_for_llm(
            self.snap,
            anchors=["auth-service.validateToken"],
            max_edges=40, max_tokens=50000, max_depth=2,
            index=self.idx,
        )
        self.assertIn("summary_md", res)
        self.assertIn("Subgraph for anchors", res["summary_md"])

    def test_deterministic(self):
        kwargs = dict(
            anchors=["auth-service.validateToken"],
            max_edges=40, max_tokens=50000, max_depth=2,
            index=self.idx,
        )
        r1 = subgraph_for_llm(self.snap, **kwargs)
        r2 = subgraph_for_llm(self.snap, **kwargs)
        self.assertEqual([e["edge_id"] for e in r1["edges"]],
                         [e["edge_id"] for e in r2["edges"]])


if __name__ == "__main__":
    unittest.main()
