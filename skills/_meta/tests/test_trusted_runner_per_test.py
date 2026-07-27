"""Tests for trusted_runner._run_pytest per-test granularity (RT1 fix).

Verifies that the bundle emits tests[] with {nodeid, outcome, duration_s, keywords}
for each pytest-json-report test entry, while preserving backward-compatible
failed_tests[] and aggregate summary{} fields.

These tests create tiny temporary test files, run _run_pytest against them,
and assert on the returned bundle shape.
"""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

# Make the _meta package importable.
_META_DIR = Path(__file__).resolve().parent.parent
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

from trusted_runner import _run_pytest  # noqa: E402


def _write_test_file(tmpdir: Path, name: str, body: str) -> Path:
    p = tmpdir / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


class TestPerTestGranularityPassing(unittest.TestCase):
    def test_emits_tests_array_with_passing_nodeids(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            _write_test_file(tmp_p, "test_alpha.py", """
                def test_one():
                    assert 1 + 1 == 2

                def test_two():
                    assert True

                def test_three():
                    assert 'a' in 'abc'
            """)
            result = _run_pytest(tmp_p / "test_alpha.py", timeout=60)

        # Aggregate summary still present (backward compat).
        self.assertEqual(result["summary"]["total"], 3)
        self.assertEqual(result["summary"]["passed"], 3)
        self.assertEqual(result["summary"]["failed"], 0)

        # New tests[] field present, 3 entries, all passed.
        self.assertIn("tests", result)
        self.assertEqual(len(result["tests"]), 3)

        nodeids = [t["nodeid"] for t in result["tests"]]
        self.assertTrue(any("test_one" in n for n in nodeids))
        self.assertTrue(any("test_two" in n for n in nodeids))
        self.assertTrue(any("test_three" in n for n in nodeids))

        for t in result["tests"]:
            self.assertEqual(t["outcome"], "passed")
            self.assertIn("duration_s", t)
            self.assertIsInstance(t["duration_s"], float)
            self.assertGreaterEqual(t["duration_s"], 0.0)
            self.assertIn("keywords", t)
            self.assertIsInstance(t["keywords"], list)

    def test_failed_tests_preserved_backward_compat(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            _write_test_file(tmp_p, "test_mixed.py", """
                def test_pass_1():
                    assert True

                def test_fail_1():
                    assert 1 == 2

                def test_pass_2():
                    assert 'x' * 2 == 'xx'
            """)
            result = _run_pytest(tmp_p / "test_mixed.py", timeout=60)

        self.assertEqual(result["summary"]["total"], 3)
        self.assertEqual(result["summary"]["passed"], 2)
        self.assertEqual(result["summary"]["failed"], 1)

        # failed_tests[] kept for backward compat.
        self.assertIn("failed_tests", result)
        self.assertEqual(len(result["failed_tests"]), 1)
        self.assertIn("test_fail_1", result["failed_tests"][0]["nodeid"])
        self.assertEqual(result["failed_tests"][0]["outcome"], "failed")

        # tests[] has all 3 outcomes.
        self.assertEqual(len(result["tests"]), 3)
        outcomes = sorted(t["outcome"] for t in result["tests"])
        self.assertEqual(outcomes, ["failed", "passed", "passed"])


class TestKeywordsAndMarkers(unittest.TestCase):
    def test_pytest_markers_appear_in_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            _write_test_file(tmp_p, "conftest.py", """
                def pytest_configure(config):
                    config.addinivalue_line(
                        "markers",
                        "criterion(id): mark test as covering a specific success_criterion"
                    )
            """)
            _write_test_file(tmp_p, "test_marked.py", """
                import pytest

                @pytest.mark.criterion("SC2")
                def test_with_criterion_marker():
                    assert 1 == 1

                def test_without_marker():
                    assert 2 == 2
            """)
            result = _run_pytest(tmp_p / "test_marked.py", timeout=60)

        self.assertEqual(result["summary"]["total"], 2)
        self.assertEqual(len(result["tests"]), 2)

        marked = next(
            t for t in result["tests"] if "test_with_criterion_marker" in t["nodeid"]
        )
        # Markers are only recoverable from pytest-json-report. pytest's built-in
        # JUnit XML carries no marker data at all, so on that path the runner MUST
        # declare `keywords_available: False` rather than emit [] — an empty list
        # is indistinguishable from "this test genuinely has no markers", and an
        # auditor tying tests to success_criteria would silently find none.
        if result.get("keywords_available") is False:
            self.assertEqual(
                result.get("granularity"), "junit",
                "keywords_available=False is only legitimate on the JUnit path",
            )
            self.assertEqual(
                marked["keywords"], [],
                "JUnit path must emit [] alongside the keywords_available=False flag",
            )
            self.skipTest(
                "marker capture requires pytest-json-report; runner correctly "
                "declared keywords_available=False on the JUnit fallback"
            )
        else:
            self.assertTrue(
                any("criterion" in kw for kw in marked["keywords"]),
                f"expected 'criterion' marker in keywords, got {marked['keywords']!r}",
            )

        unmarked = next(
            t for t in result["tests"] if "test_without_marker" in t["nodeid"]
        )
        self.assertFalse(
            any("criterion" in kw for kw in unmarked["keywords"]),
        )


class TestBundleShapeInvariants(unittest.TestCase):
    def test_every_test_record_has_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            _write_test_file(tmp_p, "test_fields.py", """
                def test_a():
                    assert True

                def test_b():
                    assert True
            """)
            result = _run_pytest(tmp_p / "test_fields.py", timeout=60)

        required = {"nodeid", "outcome", "duration_s", "keywords"}
        for t in result["tests"]:
            self.assertTrue(required.issubset(t.keys()),
                            f"missing fields in {t!r}")

    def test_tests_field_absent_in_fallback_returncode_path(self):
        # Sanity check: _result_from_returncode (the fallback) does NOT
        # include a tests[] field. That's the existing shape, unchanged.
        from trusted_runner import _result_from_returncode
        r = _result_from_returncode(Path("/tmp/xyz"), 0)
        self.assertNotIn("tests", r)
        self.assertIn("failed_tests", r)  # still there


if __name__ == "__main__":
    unittest.main()
