#!/usr/bin/env python3
"""test_v11_unconfirmed_marker.py — blocking_eligible=false marks flow as unconfirmed."""
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


class UnconfirmedMarkerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ift11-uc-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_flow_with_agent_only_edge_gets_unconfirmed_marker(self):
        # Build a map whose flow path traverses auth -> audit-log (agent-only
        # in the snapshot fixture). validateToken has an agent_asserted-only
        # emits edge to audit-log.
        custom_map = dict(DEFAULT_MAP)
        custom_map = {
            "schema_version": "1.0.0",
            "revision": 3,
            "components": DEFAULT_MAP["components"],
            "flows": [
                {
                    "id": "FLOW-AUDIT",
                    "name": "audit",
                    "path": ["auth-service", "audit-log", "db"],
                    "entry_input": {"component": "auth-service",
                                     "input": "session_token"},
                    "terminal_output": {"component": "db"},
                    "expected_outcome": "200",
                    "priority": "normal",
                },
            ],
        }
        write_contract_map(self.tmp, custom_map)
        write_snapshot(self.tmp)
        result = generate_tests(
            component_id="auth-service",
            contract_map_path=self.tmp / "progress" / "contract-map.yaml",
            project_root=self.tmp, output_root=self.tmp,
        )
        flow_content = Path(result["flow_tests"][0]).read_text()
        self.assertIn("unconfirmed_wiring", flow_content)
        self.assertIn("@pytest.mark.unconfirmed_wiring", flow_content)


if __name__ == "__main__":
    unittest.main()
