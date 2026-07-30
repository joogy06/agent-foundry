#!/usr/bin/env python3
"""S074 (#216) — Tier B declared geometric relations.

Tier A infers structure generically and is conservative by necessity: it skips
fixed/sticky/absolute elements, because geometry alone cannot distinguish an element that
legitimately escapes its parent from one that escaped by accident.

Tier B is where the project supplies that judgement. The single most important property
here is that a DECLARED relation does NOT inherit Tier A's positional exclusion — if it
did, declaring a relation over a sticky header would silently be a no-op, and that case is
the entire reason the tier exists.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

META = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(META))
import geometry_rules as gr  # noqa: E402

CFG = dict(gr.DEFAULT_CONFIG)


def el(eid, x, y, w, h, *, spec=None, selector=None, pos="static", padding=None):
    return {
        "element_id": eid, "spec_id": spec, "selector": selector, "kind": "found",
        "hidden_reason": None,
        "bbox": {"x": x, "y": y, "w": w, "h": h},
        "padding_box": padding or {"x": x, "y": y, "w": w, "h": h},
        "computed": {"position": pos},
    }


class TestPositionalExclusionIsBypassed(unittest.TestCase):
    """The design point of #216, pinned."""

    def test_declared_containment_still_fires_on_a_sticky_child(self):
        elements = [
            el("box", 0, 0, 100, 100, selector=".box"),
            el("kid", 0, 0, 400, 20, selector=".kid", pos="sticky"),
        ]
        rel = [{"id": "R1", "kind": "contain", "container": ".box", "children": [".kid"]}]
        out = gr.rule_declared_relations(elements, rel, CFG)
        self.assertTrue(any(f["rule"] == "containment_breach" for f in out),
                        "a declared relation must not inherit Tier A's sticky exclusion")

    def test_tier_a_still_skips_the_same_sticky_child(self):
        """Proves the two tiers genuinely differ rather than the test being trivially true."""
        kid = el("kid", 0, 0, 400, 20, selector=".kid", pos="sticky")
        kid["parent_padding_box"] = {"x": 0, "y": 0, "w": 100, "h": 100}
        out = gr.rule_containment([kid], CFG)
        self.assertEqual(out, [], "Tier A must remain conservative about escaping positions")


class TestRelationKinds(unittest.TestCase):
    def test_repeat_reports_a_missing_item(self):
        out = gr.rule_declared_relations(
            [el("a", 0, 0, 10, 10, selector=".row")],
            [{"id": "R", "kind": "repeat", "selector": ".row", "min_count": 3}], CFG)
        self.assertEqual(out[0]["rule"], "repeat_missing")
        self.assertEqual(out[0]["observed"], 1)

    def test_repeat_is_silent_when_satisfied(self):
        els = [el(f"a{i}", 0, i * 20, 10, 10, selector=".row") for i in range(3)]
        out = gr.rule_declared_relations(
            els, [{"id": "R", "kind": "repeat", "selector": ".row", "min_count": 3}], CFG)
        self.assertEqual(out, [])

    def test_collision_free_detects_overlap(self):
        els = [el("a", 0, 0, 50, 50, selector=".a"), el("b", 10, 10, 50, 50, selector=".b")]
        out = gr.rule_declared_relations(
            els, [{"id": "R", "kind": "collision_free", "members": [".a", ".b"]}], CFG)
        self.assertEqual(out[0]["rule"], "collision")
        self.assertGreater(out[0]["overlap_area_px"], 0)

    def test_align_reports_the_spread_and_both_coordinates(self):
        els = [el("a", 10, 0, 50, 20, selector=".a"), el("b", 24, 30, 50, 20, selector=".b")]
        out = gr.rule_declared_relations(
            els, [{"id": "R", "kind": "align", "members": [".a", ".b"], "edge": "left"}], CFG)
        self.assertEqual(out[0]["rule"], "misaligned")
        self.assertAlmostEqual(out[0]["spread_px"], 14.0, places=1)

    def test_align_is_silent_within_tolerance(self):
        els = [el("a", 10, 0, 50, 20, selector=".a"), el("b", 10.2, 30, 50, 20, selector=".b")]
        out = gr.rule_declared_relations(
            els, [{"id": "R", "kind": "align", "members": [".a", ".b"], "edge": "left"}], CFG)
        self.assertEqual(out, [])

    def test_must_not_occlude_reports_the_scroll_checkpoint(self):
        els = [el("hdr", 0, 0, 100, 40, selector=".hdr", pos="fixed"),
               el("cta", 0, 20, 100, 40, selector=".cta")]
        out = gr.rule_declared_relations(
            els, [{"id": "R", "kind": "must_not_occlude", "occluder": ".hdr",
                   "protected": ".cta", "at_scroll": 800}], CFG)
        self.assertEqual(out[0]["rule"], "occlusion")
        self.assertEqual(out[0]["at_scroll"], 800)

    def test_owned_by_resolves_by_spec_id(self):
        els = [el("c", 0, 0, 100, 100, spec="container"),
               el("k", 0, 0, 200, 20, spec="kid")]
        out = gr.rule_declared_relations(
            els, [{"id": "R", "kind": "owned_by", "container": "container", "child": "kid"}], CFG)
        self.assertEqual(out[0]["rule"], "containment_breach")


class TestHonestLimits(unittest.TestCase):
    def test_paint_within_is_reported_unmeasured_never_passed(self):
        """DOM geometry cannot see shadows, outlines, pseudo-elements or glyph overflow."""
        out = gr.rule_declared_relations(
            [el("a", 0, 0, 10, 10, selector=".a")],
            [{"id": "R", "kind": "paint_within", "child": ".a", "container": ".b"}], CFG)
        self.assertEqual(out[0]["rule"], "paint_within_unmeasured")
        self.assertEqual(out[0]["requires"], "pixel_verification")

    def test_unresolvable_container_is_a_finding_not_a_silent_pass(self):
        out = gr.rule_declared_relations(
            [el("a", 0, 0, 10, 10, selector=".a")],
            [{"id": "R", "kind": "contain", "container": ".missing", "children": [".a"]}], CFG)
        self.assertEqual(out[0]["rule"], "relation_unresolved")

    def test_unknown_kind_is_surfaced(self):
        out = gr.rule_declared_relations(
            [], [{"id": "R", "kind": "teleports_nicely"}], CFG)
        self.assertEqual(out[0]["rule"], "relation_unknown")


class TestPaintWithinReachesTheOutput(unittest.TestCase):
    """Regression: the unit test passed while the integrated path dropped it.

    `paint_within` was emitted as an info-severity FINDING, and evaluate() filters findings
    below the severity floor — so the honest limit vanished before anyone could read it.
    It now routes to `unmeasured_by_design`, which is the field the evidence schema
    defines for exactly this ("reported unmeasured, never passed").
    """

    def _measurement(self, relations):
        return {
            "outcome": "MEASURED", "breakpoints_expected": 1, "breakpoints_measured": 1,
            "measurements": {"m": {
                "breakpoint": "m", "viewport": {"dpr": 1}, "groups": [],
                "elements": [el("a", 0, 0, 10, 10, selector=".a")],
            }},
        }

    def test_paint_within_survives_the_default_severity_floor(self):
        out = gr.evaluate(self._measurement(None), {
            "relations": [{"id": "R-paint", "kind": "paint_within",
                           "child": ".a", "container": "body"}]})
        joined = " ".join(out["unmeasured_by_design"])
        self.assertIn("R-paint", joined)
        self.assertIn("pixel verification", joined)

    def test_paint_within_is_not_left_in_findings(self):
        out = gr.evaluate(self._measurement(None), {
            "relations": [{"id": "R-paint", "kind": "paint_within",
                           "child": ".a", "container": "body"}]})
        self.assertFalse([f for f in out["findings"] if f["rule"] == "paint_within_unmeasured"])

    def test_the_standing_limit_is_stated_even_with_no_relations(self):
        out = gr.evaluate(self._measurement(None), {})
        self.assertTrue(out["unmeasured_by_design"])


class TestWiring(unittest.TestCase):
    def test_relations_absent_means_tier_a_only(self):
        bp = {"breakpoint": "m", "viewport": {"dpr": 1}, "elements": [], "groups": []}
        self.assertEqual(gr.evaluate_breakpoint(bp, dict(CFG)), [])

    def test_relations_flow_through_evaluate_breakpoint(self):
        bp = {
            "breakpoint": "m", "viewport": {"dpr": 1}, "groups": [],
            "elements": [el("a", 0, 0, 10, 10, selector=".row")],
        }
        cfg = dict(CFG)
        cfg["relations"] = [{"id": "R", "kind": "repeat", "selector": ".row", "min_count": 3}]
        out = gr.evaluate_breakpoint(bp, cfg)
        self.assertTrue(any(f["rule"] == "repeat_missing" for f in out))
        self.assertEqual(out[0]["breakpoint"], "m")


if __name__ == "__main__":
    unittest.main()
