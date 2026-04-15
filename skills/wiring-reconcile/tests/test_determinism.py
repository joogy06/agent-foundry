#!/usr/bin/env python3
"""Determinism test: run reconcile twice on the same inputs, snapshot bytes
MUST be identical (modulo top-level `generated_at` which the caller sets).

We pin `generated_at` across the two calls to prove bit-identical output.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from reconciler import reconcile  # noqa: E402
from snapshot_writer import canonical_json_bytes  # noqa: E402
from edge_identity import compute_edge_id  # noqa: E402


COMPONENTS = ["auth-service", "user-service", "db"]
TREE = "a" * 40


def _edge(src_sym, dst="db", dst_sym="db.User.select", kind="calls",
          extractor="fastapi"):
    return {
        "schema_version": "1.0.0",
        "edge_id": compute_edge_id("auth-service", src_sym, dst, dst_sym, kind),
        "src_component": "auth-service",
        "src_symbol": src_sym,
        "dst_component": dst,
        "dst_symbol": dst_sym,
        "edge_kind": kind,
        "evidence_source": "static_extract",
        "extractor_id": extractor,
        "extractor_version": "1.0.0",
        "workspace_tree_hash": TREE,
        "emitted_at": "2026-04-14T12:00:00Z",
    }


def _manifest():
    return {
        "schema_version": "1.0.0",
        "run_id": "11111111-1111-1111-1111-111111111111",
        "workspace_tree_hash": TREE,
        "project_dir": "/tmp",
        "started_at": "2026-04-14T12:00:00Z",
        "sources": [{
            "source_id": "wiring-extract-static.fastapi",
            "evidence_source": "static_extract",
            "status": "succeeded",
            "output_path": "static.jsonl",
            "edge_count": 5,
            "completed_at": "2026-04-14T12:01:00Z",
        }],
    }


class TestDeterminism(unittest.TestCase):

    def test_bit_identical_two_runs(self):
        statics = [
            _edge("auth-service.f1"),
            _edge("auth-service.f2"),
            _edge("auth-service.f3"),
            _edge("auth-service.f4"),
            _edge("auth-service.f5", extractor="generic-treesitter"),
        ]
        generated_at = "2026-04-14T12:02:00Z"
        kwargs = dict(
            static_edges=statics,
            asserted_edges=[],
            manifest=_manifest(),
            contract_map_components=COMPONENTS,
            run_id="11111111-1111-1111-1111-111111111111",
            workspace_tree_hash=TREE,
            generated_at=generated_at,
            snapshot_generation=1,
        )
        snap1 = reconcile(**kwargs)
        snap2 = reconcile(**kwargs)
        b1 = canonical_json_bytes(snap1)
        b2 = canonical_json_bytes(snap2)
        self.assertEqual(b1, b2, "snapshot bytes must be bit-identical")
        # snapshot_id must match
        self.assertEqual(snap1["snapshot_id"], snap2["snapshot_id"])

    def test_input_order_independence(self):
        """Edges supplied in different order must yield same bytes."""
        statics1 = [
            _edge("auth-service.a"),
            _edge("auth-service.b"),
            _edge("auth-service.c"),
        ]
        statics2 = list(reversed(statics1))
        kw = dict(
            asserted_edges=[],
            manifest=_manifest(),
            contract_map_components=COMPONENTS,
            run_id="11111111-1111-1111-1111-111111111111",
            workspace_tree_hash=TREE,
            generated_at="2026-04-14T12:02:00Z",
            snapshot_generation=1,
        )
        snap1 = reconcile(static_edges=statics1, **kw)
        snap2 = reconcile(static_edges=statics2, **kw)
        self.assertEqual(canonical_json_bytes(snap1), canonical_json_bytes(snap2))


if __name__ == "__main__":
    unittest.main()
