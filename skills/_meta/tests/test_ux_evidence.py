#!/usr/bin/env python3
"""Tests for ux_evidence.py and the G_UX_EVIDENCE gate (S073).

    python -m pytest skills/_meta/tests/test_ux_evidence.py -v

The contract under test: a reviewing agent cannot talk its way to a PASS. Coverage comes
from the plan, the driver reports only what it observed, and `outcome` is recomputed here
regardless of what the artifact claims. Several cases deliberately submit an artifact
asserting `outcome: PASS` while the cells say otherwise.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

META = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(META))

import ux_evidence as ux  # noqa: E402

PLAN = {
    "schema_version": "ux-review-plan.v1",
    "plan_id": "demo",
    "severity_floor": "major",
    "viewports": [
        {"id": "mobile", "width": 390, "height": 844},
        {"id": "desktop", "width": 1440, "height": 900},
    ],
    "surfaces": [{
        "id": "cart", "url": "/cart", "hot_spot": True,
        "fixtures": [
            {"id": "n1", "expected_cardinality": 1, "collection_selector": ".row"},
            {"id": "n2", "expected_cardinality": 2, "collection_selector": ".row"},
        ],
    }],
}
HASH64 = "a" * 64


def cell(fixture, viewport, *, card=None, status="measured", readiness="stable",
         findings=None, errors=None, caps=None):
    if card is None:
        card = 1 if fixture == "n1" else 2
    return {
        "surface_id": "cart", "fixture_id": fixture, "viewport_id": viewport,
        "status": status, "observed_cardinality": card, "readiness": readiness,
        "findings": findings or [], "errors": errors or [],
        "capabilities_missing": caps or [],
    }


def evidence(cells, **over):
    ev = {
        "schema_version": "ux-evidence.v1", "run_id": "r1", "plan_id": "demo",
        "plan_hash": ux.canonical_hash(PLAN),
        "probe_version": "dom-geometry-probe.v1", "probe_hash": HASH64,
        "product_url": "http://x/cart", "product_hash": "deadbeef",
        # Deliberately asserts PASS. The validator must ignore it.
        "expected_cells": 4, "observed_cells": 4, "outcome": "PASS",
        "enforcement": "gate", "cells": cells,
    }
    ev.update(over)
    return ev


def full_clean():
    return [cell("n1", "mobile"), cell("n1", "desktop"),
            cell("n2", "mobile"), cell("n2", "desktop")]


class ExpectedMatrixCase(unittest.TestCase):
    def test_matrix_is_derived_from_plan_not_evidence(self):
        self.assertEqual(len(ux.expected_cells(PLAN)), 4)

    def test_surface_can_narrow_viewports(self):
        plan = json.loads(json.dumps(PLAN))
        plan["surfaces"][0]["viewport_ids"] = ["desktop"]
        self.assertEqual(len(ux.expected_cells(plan)), 2)

    def test_plan_hash_is_order_independent(self):
        a = ux.canonical_hash({"x": 1, "y": 2})
        b = ux.canonical_hash({"y": 2, "x": 1})
        self.assertEqual(a, b)


class OutcomeCase(unittest.TestCase):
    def test_full_clean_run_passes(self):
        self.assertEqual(ux.validate(evidence(full_clean()), PLAN)["outcome"], "PASS")

    def test_n1_desktop_only_cannot_satisfy_the_plan(self):
        """The headline requirement: one desktop cell is not a reviewed surface."""
        v = ux.validate(evidence([cell("n1", "desktop")]), PLAN)
        self.assertEqual(v["outcome"], "UNMEASURED")
        self.assertEqual(v["observed_cells"], 1)
        self.assertEqual(len(v["missing_cells"]), 3)

    def test_claimed_outcome_is_ignored(self):
        """Artifact says PASS with one cell; recomputation must overrule it."""
        ev = evidence([cell("n1", "desktop")], outcome="PASS", observed_cells=4)
        self.assertNotEqual(ux.validate(ev, PLAN)["outcome"], "PASS")

    def test_cardinality_mismatch_is_inconclusive(self):
        cells = full_clean()
        cells[2]["observed_cardinality"] = 1  # n2 should hold 2
        v = ux.validate(evidence(cells), PLAN)
        self.assertEqual(v["outcome"], "INCONCLUSIVE")
        self.assertTrue(any("did not materialise" in r for r in v["outcome_reasons"]))

    def test_missing_observed_cardinality_is_inconclusive_not_pass(self):
        cells = full_clean()
        cells[0]["observed_cardinality"] = None
        self.assertEqual(ux.validate(evidence(cells), PLAN)["outcome"], "INCONCLUSIVE")

    def test_unstable_geometry_is_inconclusive(self):
        cells = full_clean()
        cells[1]["readiness"] = "unstable"
        self.assertEqual(ux.validate(evidence(cells), PLAN)["outcome"], "INCONCLUSIVE")

    def test_missing_capability_is_inconclusive(self):
        """Dev without a payment gateway returned a clean pass on an absent surface."""
        cells = full_clean()
        cells[3]["capabilities_missing"] = ["payment_gateway"]
        v = ux.validate(evidence(cells), PLAN)
        self.assertEqual(v["outcome"], "INCONCLUSIVE")
        self.assertTrue(any("not rendered" in r for r in v["outcome_reasons"]))

    def test_cell_errors_are_inconclusive(self):
        cells = full_clean()
        cells[0]["errors"] = ["selector invalid"]
        self.assertEqual(ux.validate(evidence(cells), PLAN)["outcome"], "INCONCLUSIVE")

    def test_finding_at_floor_fails(self):
        cells = full_clean()
        cells[2]["findings"] = [{"severity": "critical", "rule": "repeated_collapse"}]
        v = ux.validate(evidence(cells), PLAN)
        self.assertEqual(v["outcome"], "FAIL")
        self.assertEqual(v["findings_at_floor"], 1)

    def test_finding_below_floor_still_passes_but_is_counted(self):
        cells = full_clean()
        cells[2]["findings"] = [{"severity": "minor", "rule": "rule_weight_inconsistency"}]
        v = ux.validate(evidence(cells), PLAN)
        self.assertEqual(v["outcome"], "PASS")
        self.assertEqual(v["finding_count"], 1)
        self.assertEqual(v["findings_at_floor"], 0)

    def test_unmeasured_outranks_findings(self):
        """A missing cell is not redeemed by findings elsewhere."""
        cells = [cell("n1", "mobile", findings=[{"severity": "critical"}])]
        self.assertEqual(ux.validate(evidence(cells), PLAN)["outcome"], "UNMEASURED")


class BindingCase(unittest.TestCase):
    def test_wrong_plan_hash_is_rejected(self):
        ev = evidence(full_clean(), plan_hash="b" * 64)
        v = ux.validate(ev, PLAN)
        self.assertEqual(v["outcome"], "UNMEASURED")
        self.assertTrue(any("different plan revision" in r for r in v["outcome_reasons"]))

    def test_missing_probe_hash_is_rejected(self):
        ev = evidence(full_clean())
        del ev["probe_hash"]
        self.assertEqual(ux.validate(ev, PLAN)["outcome"], "UNMEASURED")

    def test_wrong_schema_version_is_rejected(self):
        ev = evidence(full_clean(), schema_version="ux-evidence.v0")
        self.assertEqual(ux.validate(ev, PLAN)["outcome"], "UNMEASURED")

    def test_absent_product_hash_is_noted_but_not_fatal(self):
        ev = evidence(full_clean())
        ev["product_hash"] = None
        v = ux.validate(ev, PLAN)
        self.assertEqual(v["outcome"], "PASS")
        self.assertTrue(any("not bound to a specific reviewed build" in r for r in v["outcome_reasons"]))

    def test_enforcement_defaults_to_convention_when_absent(self):
        """A bare standalone run must not read as gated."""
        ev = evidence(full_clean())
        del ev["enforcement"]
        self.assertEqual(ux.validate(ev, PLAN)["enforcement"], "convention")

    def test_cells_outside_the_plan_are_ignored_and_reported(self):
        cells = full_clean() + [cell("n9", "desktop")]
        v = ux.validate(evidence(cells), PLAN)
        self.assertEqual(v["outcome"], "PASS")
        self.assertTrue(any("not in the plan" in r for r in v["outcome_reasons"]))


class GateCase(unittest.TestCase):
    GATES = META / "gates.py"

    def _run(self, plan, ev):
        with tempfile.TemporaryDirectory() as td:
            p, e = Path(td) / "plan.json", Path(td) / "ev.json"
            p.write_text(json.dumps(plan))
            e.write_text(json.dumps(ev))
            return subprocess.run(
                [sys.executable, str(self.GATES), "G_UX_EVIDENCE",
                 "--plan", str(p), "--evidence", str(e)],
                capture_output=True, text=True)

    def test_gate_exit_0_on_pass(self):
        r = self._run(PLAN, evidence(full_clean()))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("G_UX_EVIDENCE_PASS", r.stdout + r.stderr)

    def test_gate_exit_2_on_partial_coverage(self):
        r = self._run(PLAN, evidence([cell("n1", "desktop")]))
        self.assertEqual(r.returncode, 2)
        self.assertIn("G_UX_EVIDENCE_FAIL", r.stderr)

    def test_gate_exit_2_on_critical_finding(self):
        cells = full_clean()
        cells[2]["findings"] = [{"severity": "critical", "rule": "repeated_collapse"}]
        self.assertEqual(self._run(PLAN, evidence(cells)).returncode, 2)

    def test_gate_exit_3_on_unreadable_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            p, e = Path(td) / "plan.json", Path(td) / "ev.json"
            p.write_text(json.dumps(PLAN))
            e.write_text("{ not json")
            r = subprocess.run(
                [sys.executable, str(self.GATES), "G_UX_EVIDENCE",
                 "--plan", str(p), "--evidence", str(e)],
                capture_output=True, text=True)
        self.assertEqual(r.returncode, 3)

    def test_gate_requires_both_flags(self):
        r = subprocess.run([sys.executable, str(self.GATES), "G_UX_EVIDENCE"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 3)


if __name__ == "__main__":
    unittest.main()
