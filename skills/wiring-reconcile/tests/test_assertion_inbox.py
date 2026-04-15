#!/usr/bin/env python3
"""Unit tests for assertion_inbox.py (WP-4).

Tests:
1. Valid edges normalize (agent provenance injected; evidence_source forced)
2. Malformed JSONL lines skipped + logged
3. Unmapped components tagged + skipped
4. Multiple per-agent files merge deterministically
5. Empty dir -> empty iterator, no crash
6. Missing asserted/ dir -> empty + no crash
7. Schema-invalid lines counted and skipped
8. Empty lines + whitespace-only lines silently ignored
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Make scripts importable regardless of install layout.
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from assertion_inbox import (  # noqa: E402
    AssertionStats,
    read_assertions,
    read_assertions_with_stats,
    load_component_ids,
)
from edge_identity import compute_edge_id  # noqa: E402


COMPONENTS = {"auth-service", "user-service", "db"}


def _make_edge(
    src_component="auth-service",
    src_symbol="auth-service.validateToken",
    dst_component="db",
    dst_symbol="db.User.select",
    edge_kind="calls",
    evidence_source="agent_asserted",
    extractor_id="bob-assertion",
    extractor_version="1.0.0",
    workspace_tree_hash="a" * 40,
    emitted_at="2026-04-14T12:00:00Z",
    **extra,
):
    e = {
        "schema_version": "1.0.0",
        "edge_id": compute_edge_id(
            src_component, src_symbol, dst_component, dst_symbol, edge_kind
        ),
        "src_component": src_component,
        "src_symbol": src_symbol,
        "dst_component": dst_component,
        "dst_symbol": dst_symbol,
        "edge_kind": edge_kind,
        "evidence_source": evidence_source,
        "extractor_id": extractor_id,
        "extractor_version": extractor_version,
        "workspace_tree_hash": workspace_tree_hash,
        "emitted_at": emitted_at,
    }
    e.update(extra)
    return e


def _write_asserted(run_dir: Path, agent_id: str, *edges):
    asserted = run_dir / "asserted"
    asserted.mkdir(parents=True, exist_ok=True)
    f = asserted / f"{agent_id}.jsonl"
    with f.open("w", encoding="utf-8") as fh:
        for e in edges:
            fh.write(json.dumps(e) + "\n")


class TestAssertionInbox(unittest.TestCase):

    def test_valid_edges_normalize(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            e1 = _make_edge()
            # Even if the file declared static_extract, we force it back to
            # agent_asserted: the inbox owns the evidence_source invariant.
            e2 = _make_edge(
                src_symbol="auth-service.login",
                evidence_source="static_extract",
            )
            _write_asserted(run_dir, "bob-challenger-1", e1, e2)
            edges, stats = read_assertions_with_stats(run_dir, COMPONENTS)
            self.assertEqual(len(edges), 2)
            self.assertEqual(stats.edges_valid, 2)
            self.assertEqual(stats.files_scanned, 1)
            self.assertEqual(stats.malformed_json, 0)
            self.assertEqual(stats.schema_invalid, 0)
            self.assertEqual(stats.unmapped_component, 0)
            for e in edges:
                self.assertEqual(e["evidence_source"], "agent_asserted")
                self.assertEqual(e["_agent_id"], "bob-challenger-1")

    def test_malformed_json_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            asserted = run_dir / "asserted"
            asserted.mkdir()
            (asserted / "agent-x.jsonl").write_text(
                json.dumps(_make_edge()) + "\n"
                + "{not json at all,\n"
                + json.dumps(_make_edge(src_symbol="auth-service.logout")) + "\n"
                + '"just-a-string"\n'
            )
            edges, stats = read_assertions_with_stats(run_dir, COMPONENTS)
            self.assertEqual(stats.files_scanned, 1)
            self.assertEqual(len(edges), 2)
            # One malformed JSON + one "not an object"
            self.assertGreaterEqual(stats.malformed_json, 2)

    def test_unmapped_components_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            e_ok = _make_edge()
            e_bad_src = _make_edge(src_component="ghost-service")
            e_bad_dst = _make_edge(
                src_symbol="auth-service.sendEmail",
                dst_component="nowhere",
                dst_symbol="nowhere.func",
            )
            _write_asserted(run_dir, "bob", e_ok, e_bad_src, e_bad_dst)
            edges, stats = read_assertions_with_stats(run_dir, COMPONENTS)
            self.assertEqual(len(edges), 1)
            self.assertEqual(stats.unmapped_component, 2)
            self.assertEqual(stats.edges_valid, 1)
            # unmapped_paths gives diagnostic breadcrumbs
            self.assertTrue(any("ghost-service" in p for p in stats.unmapped_paths))
            self.assertTrue(any("nowhere" in p for p in stats.unmapped_paths))

    def test_multiple_agent_files_merge_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_asserted(
                run_dir, "agent-b",
                _make_edge(src_symbol="auth-service.b1"),
                _make_edge(src_symbol="auth-service.b2"),
            )
            _write_asserted(
                run_dir, "agent-a",
                _make_edge(src_symbol="auth-service.a1"),
            )
            edges1, _ = read_assertions_with_stats(run_dir, COMPONENTS)
            edges2, _ = read_assertions_with_stats(run_dir, COMPONENTS)
            # Deterministic order: files sorted (agent-a first, then agent-b)
            order = [e["src_symbol"] for e in edges1]
            self.assertEqual(order, ["auth-service.a1", "auth-service.b1", "auth-service.b2"])
            self.assertEqual(
                [e["src_symbol"] for e in edges1],
                [e["src_symbol"] for e in edges2],
            )
            # Agent-id provenance preserved per file
            self.assertEqual(edges1[0]["_agent_id"], "agent-a")
            self.assertEqual(edges1[1]["_agent_id"], "agent-b")

    def test_empty_asserted_dir_is_empty_iterator(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "asserted").mkdir()
            edges = list(read_assertions(run_dir, COMPONENTS))
            self.assertEqual(edges, [])

    def test_missing_asserted_dir_empty(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            # No asserted/ subdir at all
            edges, stats = read_assertions_with_stats(run_dir, COMPONENTS)
            self.assertEqual(edges, [])
            self.assertEqual(stats.files_scanned, 0)

    def test_schema_invalid_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            bad = dict(_make_edge())
            del bad["schema_version"]  # required field
            _write_asserted(run_dir, "bob", _make_edge(), bad)
            edges, stats = read_assertions_with_stats(run_dir, COMPONENTS)
            self.assertEqual(len(edges), 1)
            self.assertEqual(stats.schema_invalid, 1)

    def test_empty_and_whitespace_lines_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            asserted = run_dir / "asserted"
            asserted.mkdir()
            (asserted / "bob.jsonl").write_text(
                "\n"
                "   \n"
                + json.dumps(_make_edge()) + "\n"
                + "\n"
            )
            edges, stats = read_assertions_with_stats(run_dir, COMPONENTS)
            self.assertEqual(len(edges), 1)
            # empty lines don't even count toward lines_read
            self.assertEqual(stats.lines_read, 1)
            self.assertEqual(stats.malformed_json, 0)


class TestLoadComponentIds(unittest.TestCase):

    def test_load_from_project_contract_map(self):
        # Use the live project's contract map (S023 has one pinned)
        cm = Path("/path/to/project/progress/contract-map.yaml")
        if not cm.is_file():
            self.skipTest("project contract map not present")
        ids = load_component_ids(cm)
        self.assertIn("wiring-extract-static", ids)
        self.assertIn("wiring-reconcile", ids)

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_component_ids(Path("/no/such/file.yaml")), [])


if __name__ == "__main__":
    unittest.main()
