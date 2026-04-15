#!/usr/bin/env python3
"""test_v11_backward_compat.py — v1.0 behaviour preserved when no snapshot."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate import generate_tests  # type: ignore  # noqa: E402
from fixture_helpers import write_contract_map, DEFAULT_MAP  # noqa: E402


class BackwardCompatCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ift11-bc-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_snapshot_produces_tests_without_evidence_header(self):
        write_contract_map(self.tmp, DEFAULT_MAP)
        result = generate_tests(
            component_id="auth-service",
            contract_map_path=self.tmp / "progress" / "contract-map.yaml",
            project_root=self.tmp,
            language_target="pytest",
            output_root=self.tmp,
        )
        self.assertFalse(result["snapshot_present"])
        self.assertGreaterEqual(len(result["integration_tests"]), 1)
        self.assertGreaterEqual(len(result["flow_tests"]), 1)
        # No suggestions file without a snapshot
        self.assertIsNone(result["suggestions_file"])
        # Flow test content does NOT include evidence corroboration header
        flow_content = Path(result["flow_tests"][0]).read_text()
        self.assertNotIn("Evidence corroboration", flow_content)
        self.assertIn("wiring snapshot not available", flow_content)

    def test_version_string_appears(self):
        write_contract_map(self.tmp, DEFAULT_MAP)
        result = generate_tests(
            component_id="auth-service",
            contract_map_path=self.tmp / "progress" / "contract-map.yaml",
            project_root=self.tmp, output_root=self.tmp,
        )
        int_content = Path(result["integration_tests"][0]).read_text()
        self.assertIn("integration-flow-testing@1.1.0", int_content)


if __name__ == "__main__":
    unittest.main()
