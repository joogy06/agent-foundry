#!/usr/bin/env python3
"""test_g4_r6.py — snapshot freshness."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gates import check_G4  # type: ignore  # noqa: E402
from g4_fixture import build_project  # noqa: E402


class G4R6Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g4-r6-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_strict_exact_tree_hash_passes(self):
        ctx = build_project(self.tmp)
        # snap_tree == cur_tree by default
        result = check_G4(self.tmp, mode="strict")
        rules = {v["rule"] for v in result["violations"]}
        self.assertNotIn("R6", rules)

    def test_strict_tree_hash_mismatch_fails(self):
        build_project(self.tmp, snapshot_tree_hash="0" * 40)
        result = check_G4(self.tmp, mode="strict")
        r6 = [v for v in result["violations"] if v["rule"] == "R6"]
        self.assertGreaterEqual(len(r6), 1)
        self.assertEqual(r6[0]["severity"], "hard")

    def test_advisory_old_generated_at_fails(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        build_project(self.tmp, generated_at=old)
        result = check_G4(self.tmp, mode="advisory")
        r6 = [v for v in result["violations"] if v["rule"] == "R6"]
        self.assertGreaterEqual(len(r6), 1)

    def test_advisory_fresh_snapshot_passes_r6(self):
        # Fresh generated_at + identical tree hash
        build_project(self.tmp)
        result = check_G4(self.tmp, mode="advisory")
        rules = {v["rule"] for v in result["violations"]}
        self.assertNotIn("R6", rules)


if __name__ == "__main__":
    unittest.main()
