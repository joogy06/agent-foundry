#!/usr/bin/env python3
"""test_g4_r7.py — signature validity."""
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


class G4R7Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g4-r7-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_good_signature_passes_r7(self):
        build_project(self.tmp, sign=True, bad_signature=False)
        result = check_G4(self.tmp, mode="strict")
        # Not asserting pass (R6 + R1 may fire depending on diff), but R7 must not be among violations
        rules = {v["rule"] for v in result["violations"]}
        self.assertNotIn("R7", rules)

    def test_bad_signature_fails_r7_hard(self):
        build_project(self.tmp, sign=True, bad_signature=True)
        result = check_G4(self.tmp, mode="strict")
        r7_violations = [v for v in result["violations"] if v["rule"] == "R7"]
        self.assertEqual(len(r7_violations), 1)
        self.assertEqual(r7_violations[0]["severity"], "hard")
        self.assertEqual(result["status"], "fail")

    def test_missing_session_key_fails_r7(self):
        build_project(self.tmp, sign=True)
        (self.tmp / ".forge" / "session.key").unlink()
        result = check_G4(self.tmp, mode="strict")
        r7_violations = [v for v in result["violations"] if v["rule"] == "R7"]
        self.assertGreaterEqual(len(r7_violations), 1)


if __name__ == "__main__":
    unittest.main()
