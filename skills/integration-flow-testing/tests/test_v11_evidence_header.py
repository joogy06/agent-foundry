#!/usr/bin/env python3
"""test_v11_evidence_header.py — evidence header injected when snapshot present."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate import generate_tests  # type: ignore  # noqa: E402
from fixture_helpers import write_contract_map, write_snapshot, DEFAULT_MAP  # noqa: E402


class EvidenceHeaderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ift11-ev-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_flow_test_contains_evidence_corroboration(self):
        write_contract_map(self.tmp, DEFAULT_MAP)
        write_snapshot(self.tmp)
        result = generate_tests(
            component_id="auth-service",
            contract_map_path=self.tmp / "progress" / "contract-map.yaml",
            project_root=self.tmp, output_root=self.tmp,
        )
        self.assertTrue(result["snapshot_present"])
        flow_content = Path(result["flow_tests"][0]).read_text()
        self.assertIn("Evidence corroboration", flow_content)
        self.assertIn("Wiring snapshot: gen=", flow_content)
        # auth-service -> user-service via static_extract should appear
        self.assertIn("auth-service -> user-service", flow_content)
        self.assertIn("static_extract", flow_content)


if __name__ == "__main__":
    unittest.main()
