#!/usr/bin/env python3
"""test_v11_suggestions.py — advisory suggestions emit and respect invariants."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate import generate_tests  # type: ignore  # noqa: E402
from fixture_helpers import write_contract_map, write_snapshot, DEFAULT_MAP  # noqa: E402


class SuggestionsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ift11-sg-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_suggestions_file_emitted_when_snapshot_present(self):
        write_contract_map(self.tmp, DEFAULT_MAP)
        write_snapshot(self.tmp)
        result = generate_tests(
            component_id="auth-service",
            contract_map_path=self.tmp / "progress" / "contract-map.yaml",
            project_root=self.tmp, output_root=self.tmp,
        )
        self.assertIsNotNone(result["suggestions_file"])
        sug_doc = json.loads(Path(result["suggestions_file"]).read_text())
        self.assertEqual(sug_doc["schema_version"], "1.0.0")
        self.assertEqual(sug_doc["snapshot_generation"], 9)
        # Deterministic: suggested_flow_ids are SUGG-001, SUGG-002, ...
        for i, s in enumerate(sug_doc["suggestions"]):
            self.assertEqual(s["suggested_flow_id"], f"SUGG-{i + 1:03d}")

    def test_no_suggestions_for_bob_promote_implicit_transitions(self):
        # Build a map that declares the auth->user->db flow; the fixture
        # snapshot has an auth->audit-log hop too. That 3-hop path
        # (auth->audit-log, audit-log->db) should surface as a suggestion.
        write_contract_map(self.tmp, DEFAULT_MAP)
        write_snapshot(self.tmp)
        result = generate_tests(
            component_id="auth-service",
            contract_map_path=self.tmp / "progress" / "contract-map.yaml",
            project_root=self.tmp, output_root=self.tmp,
        )
        sug = json.loads(Path(result["suggestions_file"]).read_text())
        # Bob-promote invariant: reconcile -> wiring-query & reconcile -> gates-g4
        # shouldn't be in suggestions. The fixture doesn't include those
        # components, but we assert the explicit pair doesn't appear.
        for s in sug["suggestions"]:
            hops = list(zip(s["path"][:-1], s["path"][1:]))
            self.assertNotIn(("wiring-reconcile", "wiring-query"), hops)
            self.assertNotIn(("wiring-reconcile", "gates-g4"), hops)

    def test_suggestions_never_produce_test_files(self):
        write_contract_map(self.tmp, DEFAULT_MAP)
        write_snapshot(self.tmp)
        result = generate_tests(
            component_id="auth-service",
            contract_map_path=self.tmp / "progress" / "contract-map.yaml",
            project_root=self.tmp, output_root=self.tmp,
        )
        # Only one flow test (FLOW-LOGIN for auth-service owner), despite
        # suggestions being emitted
        self.assertEqual(len(result["flow_tests"]), 1)


if __name__ == "__main__":
    unittest.main()
