#!/usr/bin/env python3
"""test_g4_r3.py — removed code must not retain live edges."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gates import check_G4  # type: ignore  # noqa: E402
from g4_fixture import build_project, make_edge  # noqa: E402


class G4R3Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g4-r3-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_removed_component_with_live_edge_fails_r3(self):
        # Edge references `ghost-service` which is NOT in contract map's components
        edges = [make_edge("ghost-service", "ghost.x", "user-service", "user-service.y",
                           "calls", status="live")]
        build_project(self.tmp, edges=edges,
                      components=("auth-service", "user-service"))
        result = check_G4(self.tmp, mode="strict")
        r3 = [v for v in result["violations"] if v["rule"] == "R3"]
        self.assertGreaterEqual(len(r3), 1)
        self.assertEqual(r3[0]["severity"], "hard")

    def test_removed_component_with_orphan_status_passes_r3(self):
        edges = [make_edge("ghost-service", "ghost.x", "user-service", "user-service.y",
                           "calls", status="orphan")]
        build_project(self.tmp, edges=edges,
                      components=("auth-service", "user-service"))
        result = check_G4(self.tmp, mode="strict")
        rules = {v["rule"] for v in result["violations"]}
        self.assertNotIn("R3", rules)

    def test_all_known_components_no_r3(self):
        edges = [make_edge("auth-service", "auth.x", "user-service", "user-service.y",
                           "calls", status="live")]
        build_project(self.tmp, edges=edges,
                      components=("auth-service", "user-service"))
        result = check_G4(self.tmp, mode="strict")
        rules = {v["rule"] for v in result["violations"]}
        self.assertNotIn("R3", rules)


if __name__ == "__main__":
    unittest.main()
