#!/usr/bin/env python3
"""Golden-fixture tests for rot_scan.py (Evergreening v1, S041).

§9.1: rot fixtures (known-RED/YELLOW/GREEN/VAGUE/UNANNOTATED tree -> exact report).
§6.13: golden-fixture self-rot defense.

stdlib unittest. Run:
  python3 -m unittest discover -s ~/.claude/skills/_meta/tests -p 'test_rot_scan.py' -v
"""
from __future__ import annotations

import importlib.util
import unittest
from datetime import date
from pathlib import Path

_META = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("rot_scan", _META / "rot_scan.py")
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)

_FIX = Path(__file__).resolve().parent / "fixtures" / "rot"
_TODAY = date(2026, 6, 5)


def _run():
    inv = rs.load_inventory(_FIX / "inventory.json")
    return rs.run_scan(_FIX / "skills", _FIX / "agents", inv, _TODAY,
                       exclude_fixtures=False)


class TestGoldenReport(unittest.TestCase):
    def setUp(self):
        self.report = _run()

    def test_exact_counts(self):
        # The defining golden assertion: one of each verdict class (+ extra GREEN agent).
        self.assertEqual(self.report["counts"],
                         {"RED": 1, "YELLOW": 1, "GREEN": 2, "VAGUE": 1, "UNANNOTATED": 1})

    def test_files_scanned(self):
        self.assertEqual(self.report["files_scanned"], 6)

    def test_red_is_the_stale_tool(self):
        reds = [f for f in self.report["findings"] if f["verdict"] == "RED"]
        self.assertEqual(len(reds), 1)
        self.assertIn("red-tool", reds[0]["file"])
        self.assertIn("0.118.0", reds[0]["anchor"])

    def test_yellow_is_the_deadline(self):
        yels = [f for f in self.report["findings"] if f["verdict"] == "YELLOW"]
        self.assertEqual(len(yels), 1)
        self.assertIn("yellow-deadline", yels[0]["file"])
        self.assertEqual(yels[0]["anchor"], "2026-06-18")

    def test_vague_is_the_band(self):
        vagues = [f for f in self.report["findings"] if f["verdict"] == "VAGUE"]
        self.assertEqual(len(vagues), 1)
        self.assertIn("vague-band", vagues[0]["file"])

    def test_unannotated_is_advisory(self):
        un = [f for f in self.report["findings"] if f["verdict"] == "UNANNOTATED"]
        self.assertEqual(len(un), 1)
        self.assertIn("unannotated", un[0]["file"])

    def test_self_rot_fields_present(self):
        for k in ("schema_version", "scanner_version", "last_success",
                  "last_error", "runtime_ms"):
            self.assertIn(k, self.report)
        self.assertEqual(self.report["schema_version"], "rot-report.v1")
        self.assertTrue(self.report["last_success"])
        self.assertIsNone(self.report["last_error"])


class TestGradingPrimitives(unittest.TestCase):
    def test_behind_by_minor_true(self):
        self.assertTrue(rs._behind_by_minor("0.118.0", "0.137.0"))

    def test_behind_by_minor_patch_only_false(self):
        # patch-only difference is NOT RED (patch-counted-not-RED).
        self.assertFalse(rs._behind_by_minor("0.137.0", "0.137.5"))

    def test_behind_by_minor_equal_false(self):
        self.assertFalse(rs._behind_by_minor("2.1.0", "2.1.0"))

    def test_behind_by_major(self):
        self.assertTrue(rs._behind_by_minor("1.9.0", "2.0.0"))

    def test_prose_date_not_red(self):
        # A bare "as of 2026-05" describing a fact (no "Status" prefix) must NOT
        # grade RED (prose-date FP suppression).
        text = "OWASP Top 10 as of 2026-05 lists supply-chain at #3."
        findings = rs._grade_regex("f.md", text, {}, _TODAY, annotated=False)
        self.assertFalse(any(f["verdict"] == "RED" for f in findings))

    def test_status_snapshot_stale_is_red(self):
        text = "Status as of 2026-04-14: WP-4 not yet implemented."
        findings = rs._grade_regex("f.md", text, {}, _TODAY, annotated=False)
        self.assertTrue(any(f["verdict"] == "RED" and f["kind"] == "status_snapshot"
                            for f in findings))

    def test_github_substring_not_attributed_to_gh(self):
        # "GitHub Actions ... WCAG 2.1" must not produce a gh-CLI RED (word-boundary).
        inv = {"tools": {"gh": {"installed": True, "version": "2.87.0"}}}
        text = "Covers GitHub Actions CI/CD and accessibility (WCAG 2.1 semantic HTML)."
        findings = rs._grade_regex("f.md", text, inv, _TODAY, annotated=False)
        self.assertFalse(any(f["verdict"] == "RED" for f in findings))


if __name__ == "__main__":
    unittest.main(verbosity=2)
