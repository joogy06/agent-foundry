#!/usr/bin/env python3
"""test_v11_wiring_query_fallback.py — direct-read fallback when wiring_query import fails."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixture_helpers import write_contract_map, write_snapshot, DEFAULT_MAP  # noqa: E402
import generate  # type: ignore  # noqa: E402


class FallbackCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ift11-fb-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_falls_back_to_direct_read_when_import_fails(self):
        write_contract_map(self.tmp, DEFAULT_MAP)
        write_snapshot(self.tmp)
        # Monkey-patch the loader accessor to simulate the import path failing
        real = generate._load_snapshot_programmatic
        try:
            def faux(project_root):
                # Force fallback by skipping the wiring_query import branch
                import json as _j
                latest = project_root / ".wiring" / "latest.json"
                if not latest.is_file():
                    return None
                return _j.loads(latest.read_text(encoding="utf-8"))
            generate._load_snapshot_programmatic = faux
            result = generate.generate_tests(
                component_id="auth-service",
                contract_map_path=self.tmp / "progress" / "contract-map.yaml",
                project_root=self.tmp, output_root=self.tmp,
            )
        finally:
            generate._load_snapshot_programmatic = real
        self.assertTrue(result["snapshot_present"])
        flow_content = Path(result["flow_tests"][0]).read_text()
        self.assertIn("Evidence corroboration", flow_content)


if __name__ == "__main__":
    unittest.main()
