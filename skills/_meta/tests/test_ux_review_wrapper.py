#!/usr/bin/env python3
"""S074 — tests for the ux-review wrapper and its CI adapter.

The bias here is toward the ways this component can LIE, not the ways it can crash. A
wrapper that reports a clean pass on an unmeasured page is worse than one that throws,
because the first is trusted. One of these tests exists because exactly that happened
during development: discovery was rooted at the collection selector, so Tier A searched
inside each row, never saw the rows as siblings, and returned a confident PASS on the one
fixture in the tree guaranteed to be defective.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

META = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(META))

import ux_review  # noqa: E402
import ux_review_ci  # noqa: E402

FIXTURES = META / "tests" / "fixtures" / "geometry"


def plan_for(fixture_file: str, *, cardinality: int = 3, selector: str = ".row", **extra):
    surface = {
        "id": "cart",
        "url": f"file://{FIXTURES / fixture_file}",
        "fixtures": [{"id": "n3", "expected_cardinality": cardinality, "collection_selector": selector}],
    }
    surface.update(extra)
    return {
        "schema_version": "ux-review-plan.v1",
        "plan_id": "test-plan",
        "severity_floor": "major",
        "viewports": [{"id": "mobile", "width": 390, "height": 844}],
        "surfaces": [surface],
    }


class TestUrlResolution(unittest.TestCase):
    """A fixture measured in the wrong state is worse than one not measured at all."""

    def test_no_setup_uses_surface_url(self):
        url, refusal = ux_review.resolve_cell_url({"id": "s", "url": "http://x/"}, {"id": "f"}, {})
        self.assertEqual(url, "http://x/")
        self.assertIsNone(refusal)

    def test_url_setup_uses_its_ref(self):
        url, refusal = ux_review.resolve_cell_url(
            {"id": "s", "url": "http://x/"}, {"id": "f", "setup": {"kind": "url", "ref": "http://x/cart?n=3"}}, {}
        )
        self.assertEqual(url, "http://x/cart?n=3")
        self.assertIsNone(refusal)

    def test_script_setup_refuses_rather_than_guessing(self):
        url, refusal = ux_review.resolve_cell_url(
            {"id": "s", "url": "http://x/"}, {"id": "f", "setup": {"kind": "script", "ref": "seed.js"}}, {}
        )
        self.assertIsNone(url)
        self.assertIn("cannot be established", refusal)

    def test_override_beats_everything(self):
        url, _ = ux_review.resolve_cell_url(
            {"id": "s", "url": "http://x/"},
            {"id": "f", "setup": {"kind": "manual"}},
            {("s", "f"): "http://override/"},
        )
        self.assertEqual(url, "http://override/")


class TestMeasureConfig(unittest.TestCase):
    def test_discovery_is_rooted_at_document_not_the_collection_selector(self):
        """Regression for the S074 development bug that returned PASS on the incident page.

        Rooting Tier A discovery at `collection_selector` searches INSIDE each item, so the
        items are never seen as siblings of one another and the entire repeated-structure
        defect class silently disappears.
        """
        cfg = ux_review.build_measure_config(
            "http://x/", {"id": "mobile", "width": 390, "height": 844},
            {"id": "f", "collection_selector": ".row"}, None, False,
        )
        self.assertEqual(cfg["discover"]["root"], "body")
        self.assertNotEqual(cfg["discover"]["root"], ".row")
        # the selector is still used — for COUNTING, which is a different question
        self.assertEqual(cfg["specs"][0]["selector"], ".row")

    def test_sandbox_is_not_weakened_unless_asked(self):
        cfg = ux_review.build_measure_config(
            "http://x/", {"id": "m", "width": 390, "height": 844}, {"id": "f"}, None, False)
        self.assertNotIn("allow_no_sandbox", cfg)


class TestCapabilityGating(unittest.TestCase):
    def test_missing_capability_never_reaches_measurement(self):
        cell, measurement = ux_review.build_cell(
            {"id": "checkout", "url": "http://x/", "required_capabilities": ["payment_gateway"]},
            {"id": "f", "expected_cardinality": 1}, {"id": "m", "width": 390, "height": 844},
            declared_capabilities=set(), overrides={}, chrome_path=None, allow_no_sandbox=False,
        )
        self.assertEqual(cell["status"], "inconclusive")
        self.assertEqual(cell["capabilities_missing"], ["payment_gateway"])
        self.assertIsNone(measurement, "an unrenderable surface must not be measured at all")

    def test_declared_capability_allows_the_cell_through(self):
        cell, _ = ux_review.build_cell(
            {"id": "checkout", "url": f"file://{FIXTURES / 'adversarial.html'}",
             "required_capabilities": ["payment_gateway"]},
            {"id": "f", "expected_cardinality": 0}, {"id": "m", "width": 390, "height": 844},
            declared_capabilities={"payment_gateway"}, overrides={}, chrome_path=None, allow_no_sandbox=False,
        )
        self.assertNotEqual(cell["status"], "inconclusive")


class TestEvidenceAssembly(unittest.TestCase):
    def test_probe_attribution_is_never_defaulted(self):
        """No measurement means no probe_hash, which the validator treats as structural."""
        plan = plan_for("incident-cart.html")
        plan["surfaces"][0]["required_capabilities"] = ["absent_thing"]
        ev = ux_review.run_review(plan, run_id="t1")
        self.assertNotIn("probe_hash", ev)

    def test_enforcement_is_recorded_by_the_wrapper(self):
        plan = plan_for("incident-cart.html")
        plan["surfaces"][0]["required_capabilities"] = ["absent_thing"]
        ev = ux_review.run_review(plan, run_id="t2", enforcement="ci")
        self.assertEqual(ev["enforcement"], "ci")

    def test_plan_hash_binds_the_artifact_to_the_plan(self):
        plan = plan_for("incident-cart.html")
        plan["surfaces"][0]["required_capabilities"] = ["absent_thing"]
        ev = ux_review.run_review(plan, run_id="t3")
        self.assertTrue(ev["plan_hash"].endswith(__import__("ux_evidence").canonical_hash(plan)))


class TestCiAdapter(unittest.TestCase):
    def setUp(self):
        self.plan = plan_for("incident-cart.html")

    def test_non_ui_diff_is_not_applicable_not_pass(self):
        r = ux_review_ci.evaluate(root=META, plan=self.plan, evidence_path=None,
                                  changed=["README.md", "setup.py"], ui_globs=ux_review_ci.DEFAULT_UI_GLOBS)
        self.assertEqual(r["outcome"], "NOT_APPLICABLE")

    def test_ui_change_without_evidence_is_blocked(self):
        r = ux_review_ci.evaluate(root=META, plan=self.plan, evidence_path=None,
                                  changed=["theme/cart.css"], ui_globs=ux_review_ci.DEFAULT_UI_GLOBS)
        self.assertEqual(r["outcome"], "BLOCKED")

    def test_evidence_for_a_different_build_is_stale(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "a.css").write_text("body{}")
            ev = td / "e.json"
            ev.write_text(json.dumps({
                "schema_version": "ux-evidence.v1", "product_hash": "0" * 64, "cells": [],
            }))
            r = ux_review_ci.evaluate(root=td, plan=self.plan, evidence_path=ev,
                                      changed=["a.css"], ui_globs=["*.css"])
        self.assertEqual(r["outcome"], "STALE")

    def test_product_hash_changes_when_content_moves_between_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "a.css").write_text("body{color:red}")
            first = ux_review_ci.product_hash(td, ["a.css"])
            (td / "a.css").unlink()
            (td / "b.css").write_text("body{color:red}")
            second = ux_review_ci.product_hash(td, ["b.css"])
        self.assertNotEqual(first, second, "a moved template is a different page")

    def test_evidence_without_product_hash_cannot_bind(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "a.css").write_text("x")
            ev = td / "e.json"
            ev.write_text(json.dumps({"schema_version": "ux-evidence.v1", "cells": []}))
            r = ux_review_ci.evaluate(root=td, plan=self.plan, evidence_path=ev,
                                      changed=["a.css"], ui_globs=["*.css"])
        self.assertEqual(r["outcome"], "BLOCKED")
        self.assertIn("product_hash", r["reasons"][0])


class TestLiveWrapperRun(unittest.TestCase):
    """End-to-end through a real browser. Skipped when the transport is unavailable."""

    @classmethod
    def setUpClass(cls):
        import shutil
        if not shutil.which("node"):
            raise unittest.SkipTest("node not on PATH")
        probe = subprocess.run(
            [sys.executable, str(META / "ux_review.py"), "--help"], capture_output=True, text=True)
        if probe.returncode != 0:
            raise unittest.SkipTest("wrapper not runnable here")

    def _run(self, plan, floor=None):
        import tempfile, yaml
        with tempfile.TemporaryDirectory() as td:
            pp = Path(td) / "plan.yaml"
            pp.write_text(yaml.safe_dump(plan))
            cmd = [sys.executable, str(META / "ux_review.py"), "--plan", str(pp),
                   "--run-id", "test", "--json"]
            if floor:
                cmd += ["--severity-floor", floor]
            return subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    def test_incident_fixture_fails(self):
        proc = self._run(plan_for("incident-cart.html"))
        if proc.returncode == 3:
            self.skipTest(f"transport unavailable: {proc.stderr[:120]}")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["outcome"], "FAIL")

    def test_adversarial_fixture_passes_at_the_strictest_floor(self):
        proc = self._run(plan_for("adversarial.html", cardinality=0, selector=".nonexistent-xyz"), floor="info")
        if proc.returncode == 3:
            self.skipTest(f"transport unavailable: {proc.stderr[:120]}")
        self.assertEqual(proc.returncode, 0, f"false positives: {proc.stdout[:400]}")
        self.assertEqual(json.loads(proc.stdout)["outcome"], "PASS")

    def test_cardinality_mismatch_cannot_pass(self):
        """A fixture that did not materialise cannot support a verdict, however clean."""
        proc = self._run(plan_for("incident-cart.html", cardinality=99))
        if proc.returncode == 3:
            self.skipTest(f"transport unavailable: {proc.stderr[:120]}")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["outcome"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
