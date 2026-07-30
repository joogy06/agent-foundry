#!/usr/bin/env python3
"""Tests for geometry_rules.py and dom_geometry_probe.js (S073).

    python -m pytest skills/_meta/tests/test_geometry_rules.py -v

Rule evaluation is deliberately browser-free so false-positive tuning — the hard part of
this design — is testable against saved JSON. The two `test_FP_*` cases are regression
anchors for false positives caught on the first real fixture run: a bordered box being
reported as a doubled divider, and an empty spacer div being reported as clipped text.
Both are the cry-wolf behaviour that gets a check ignored.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

META = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(META))

import geometry_rules as gr  # noqa: E402


def el(eid, x, y, w, h, *, parent=None, computed=None, text=False, clip=None, **extra):
    """Build one measured element the way the probe emits it."""
    d = {
        "spec_id": eid, "element_id": eid, "kind": "found", "hidden_reason": None,
        "bbox": {"x": x, "y": y, "w": w, "h": h},
        "padding_box": {"x": x, "y": y, "w": w, "h": h},
        "parent_bbox": parent, "parent_padding_box": parent,
        "clip_chain": clip or [], "depth": 3,
        "has_direct_text": text, "direct_text_length": 5 if text else 0,
        "computed": {"position": "static", "display": "block", "visibility": "visible",
                     "opacity": "1", "line-height": "normal",
                     "padding-top": "0px", "padding-bottom": "0px",
                     "border-top-width": "0px", "border-bottom-width": "0px"},
    }
    if computed:
        d["computed"].update(computed)
    d.update(extra)
    return d


def wrap(elements, groups=None, outcome="MEASURED"):
    return {
        "probe_version": "dom-geometry-probe.v1", "outcome": outcome,
        "breakpoints_expected": 1, "breakpoints_measured": 1, "errors": [],
        "measurements": {"desktop": {
            "breakpoint": "desktop", "stable": True,
            "viewport": {"w": 1440, "h": 900, "dpr": 1},
            "elements": elements, "groups": groups or [], "errors": [],
        }},
    }


def rules_fired(report):
    return {f["rule"] for f in report["findings"]}


class RepeatedCollapseCase(unittest.TestCase):
    def _leaves(self, y0, y1):
        return [
            el("g#0", 10, y0, 40, 18, group_id="g", role="member_leaf",
               member_index=0, leaf_path="SPAN:0", text=True),
            el("g#1", 10, y1, 40, 18, group_id="g", role="member_leaf",
               member_index=1, leaf_path="SPAN:0", text=True),
        ]

    def test_collapsed_leaves_are_critical(self):
        r = gr.evaluate(wrap(self._leaves(335, 335)))
        self.assertIn("repeated_collapse", rules_fired(r))
        self.assertEqual(r["verdict"], "FAIL")

    def test_distinct_leaves_do_not_fire(self):
        r = gr.evaluate(wrap(self._leaves(335, 605)))
        self.assertNotIn("repeated_collapse", rules_fired(r))

    def test_different_leaf_paths_are_not_compared(self):
        leaves = [
            el("g#0", 10, 335, 40, 18, group_id="g", role="member_leaf",
               member_index=0, leaf_path="SPAN:0", text=True),
            el("g#1", 10, 335, 40, 18, group_id="g", role="member_leaf",
               member_index=1, leaf_path="DIV:2>SPAN:1", text=True),
        ]
        self.assertNotIn("repeated_collapse", rules_fired(gr.evaluate(wrap(leaves))))

    def test_two_leaves_of_the_SAME_member_are_not_a_collapse(self):
        leaves = [
            el("g#0a", 10, 335, 40, 18, group_id="g", role="member_leaf",
               member_index=0, leaf_path="SPAN:0", text=True),
            el("g#0b", 10, 335, 40, 18, group_id="g", role="member_leaf",
               member_index=0, leaf_path="SPAN:0", text=True),
        ]
        self.assertNotIn("repeated_collapse", rules_fired(gr.evaluate(wrap(leaves))))


class ContainmentCase(unittest.TestCase):
    PANEL = {"x": 0, "y": 0, "w": 400, "h": 200}

    def test_incident_45px_overflow_is_critical(self):
        e = el("table", 1, 19, 520, 30, parent=self.PANEL)
        r = gr.evaluate(wrap([e]))
        self.assertIn("containment_breach", rules_fired(r))

    def test_clipped_TEXT_reports_clipped_content_not_breach(self):
        e = el("cell", 1, 19, 520, 30, parent=self.PANEL, text=True,
               clip=[{"bbox": self.PANEL, "overflow_x": "hidden", "overflow_y": "hidden"}])
        fired = rules_fired(gr.evaluate(wrap([e])))
        self.assertIn("clipped_content", fired)
        self.assertNotIn("containment_breach", fired)

    def test_FP_clipped_non_text_is_intentional_cropping(self):
        """overflow:hidden is the standard idiom for cropping an image or decoration."""
        e = el("crop", 1, 19, 520, 30, parent=self.PANEL, text=False,
               clip=[{"bbox": self.PANEL, "overflow_x": "hidden", "overflow_y": "hidden"}])
        self.assertNotIn("clipped_content", rules_fired(gr.evaluate(wrap([e]))))

    def test_FP_scrollable_container_is_not_clipped_content(self):
        """overflow:auto means reachable by scrolling — that is what scrolling is for.
        Fired on every scroll pane before this was distinguished from overflow:hidden."""
        e = el("para", 1, 19, 520, 30, parent=self.PANEL, text=True,
               clip=[{"bbox": self.PANEL, "overflow_x": "visible", "overflow_y": "auto"}])
        fired = rules_fired(gr.evaluate(wrap([e])))
        self.assertNotIn("clipped_content", fired)
        self.assertNotIn("containment_breach", fired)

    def test_child_inside_parent_does_not_fire(self):
        self.assertNotIn("containment_breach",
                         rules_fired(gr.evaluate(wrap([el("ok", 10, 10, 100, 20, parent=self.PANEL)]))))

    def test_FP_absolutely_positioned_badge_is_excluded(self):
        """Badges/overlays escape their parent by design — generic inference must ignore."""
        e = el("badge", 390, -8, 40, 20, parent=self.PANEL, computed={"position": "absolute"})
        self.assertNotIn("containment_breach", rules_fired(gr.evaluate(wrap([e]))))

    def test_FP_sticky_header_is_excluded(self):
        e = el("hdr", 0, -50, 500, 60, parent=self.PANEL, computed={"position": "sticky"})
        self.assertNotIn("containment_breach", rules_fired(gr.evaluate(wrap([e]))))

    def test_subpixel_overflow_is_below_tolerance(self):
        e = el("hair", 0, 0, 400.3, 20, parent=self.PANEL)
        self.assertNotIn("containment_breach", rules_fired(gr.evaluate(wrap([e]))))


class TextClippingCase(unittest.TestCase):
    def test_incident_frame_vs_line_height(self):
        """14.25px frame against a 17.875px line-height — card digits cut off."""
        e = el("digits", 0, 0, 200, 14.25, text=True, computed={"line-height": "17.875px"})
        self.assertIn("text_clipping", rules_fired(gr.evaluate(wrap([e]))))

    def test_adequate_box_does_not_fire(self):
        e = el("ok", 0, 0, 200, 24, text=True, computed={"line-height": "18px"})
        self.assertNotIn("text_clipping", rules_fired(gr.evaluate(wrap([e]))))

    def test_FP_empty_element_is_not_clipped_text(self):
        """Regression: an empty spacer div reported 'glyphs are cut off' on first run."""
        e = el("spacer", 0, 0, 200, 8, text=False, computed={"line-height": "19.2px"})
        self.assertNotIn("text_clipping", rules_fired(gr.evaluate(wrap([e]))))

    def test_line_height_normal_is_not_guessed(self):
        e = el("t", 0, 0, 200, 4, text=True, computed={"line-height": "normal"})
        self.assertNotIn("text_clipping", rules_fired(gr.evaluate(wrap([e]))))


class RuleRhythmCase(unittest.TestCase):
    PARENT = {"x": 0, "y": 0, "w": 400, "h": 600}

    def test_incident_doubled_rule_17px_apart(self):
        a = el("a", 0, 463, 400, 0, parent=self.PARENT, computed={"border-top-width": "1px"})
        b = el("b", 0, 480, 400, 0, parent=self.PARENT, computed={"border-top-width": "2px"})
        self.assertIn("doubled_rule", rules_fired(gr.evaluate(wrap([a, b]))))

    def test_well_spaced_rules_do_not_fire(self):
        a = el("a", 0, 100, 400, 0, parent=self.PARENT, computed={"border-top-width": "1px"})
        b = el("b", 0, 300, 400, 0, parent=self.PARENT, computed={"border-top-width": "1px"})
        self.assertNotIn("doubled_rule", rules_fired(gr.evaluate(wrap([a, b]))))

    def test_FP_a_bordered_box_is_not_a_doubled_rule(self):
        """Regression: one element's own top+bottom border is a box, not two dividers."""
        box = el("box", 0, 0, 200, 24, parent=self.PARENT,
                 computed={"border-top-width": "1px", "border-bottom-width": "1px"})
        self.assertNotIn("doubled_rule", rules_fired(gr.evaluate(wrap([box]))))

    def test_FP_adjacent_boxes_across_a_normal_margin(self):
        """Two stacked bordered sections 24px apart are ordinary spacing rhythm, not a
        doubled divider. A 40px threshold flagged these on every real page."""
        a = el("a", 0, 0, 400, 40, parent=self.PARENT,
               computed={"border-bottom-width": "1px"})
        b = el("b", 0, 64, 400, 40, parent=self.PARENT,
               computed={"border-top-width": "1px"})
        self.assertNotIn("doubled_rule", rules_fired(gr.evaluate(wrap([a, b]))))

    def test_FP_negative_margin_overlap_is_deliberate_layering(self):
        """Overlapping source boxes signal intentional stacking, not one rule drawn twice."""
        a = el("a", 0, 0, 120, 42, parent=self.PARENT,
               computed={"border-bottom-width": "1px"})
        b = el("b", 0, 30, 120, 42, parent=self.PARENT,
               computed={"border-top-width": "1px"})
        self.assertNotIn("doubled_rule", rules_fired(gr.evaluate(wrap([a, b]))))

    def test_FP_rules_in_different_columns_are_unrelated(self):
        """Close in y, but no horizontal overlap — different columns, different dividers."""
        a = el("a", 0, 100, 100, 0, parent=self.PARENT,
               computed={"border-top-width": "1px"})
        b = el("b", 300, 108, 100, 0, parent=self.PARENT,
               computed={"border-top-width": "1px"})
        self.assertNotIn("doubled_rule", rules_fired(gr.evaluate(wrap([a, b]))))

    def test_three_distinct_widths_flag_inconsistency(self):
        els = [el(f"r{i}", 0, 100 * (i + 1), 400, 0, parent=self.PARENT,
                  computed={"border-top-width": f"{w}px"})
               for i, w in enumerate([1, 2, 3])]
        r = gr.evaluate(wrap(els), {"severity_floor": "minor"})
        self.assertIn("rule_weight_inconsistency", rules_fired(r))


class OutcomeCase(unittest.TestCase):
    def test_clean_page_passes(self):
        self.assertEqual(gr.evaluate(wrap([el("ok", 0, 0, 100, 20)]))["verdict"], "PASS")

    def test_partial_measurement_can_never_pass(self):
        r = gr.evaluate(wrap([el("ok", 0, 0, 100, 20)], outcome="PARTIAL"))
        self.assertEqual(r["verdict"], "UNMEASURED")

    def test_inconclusive_measurement_can_never_pass(self):
        r = gr.evaluate(wrap([el("ok", 0, 0, 100, 20)], outcome="INCONCLUSIVE"))
        self.assertEqual(r["verdict"], "INCONCLUSIVE")

    def test_missing_outcome_is_unmeasured_not_pass(self):
        m = wrap([el("ok", 0, 0, 100, 20)])
        del m["outcome"]
        self.assertEqual(gr.evaluate(m)["verdict"], "UNMEASURED")

    def test_paint_bounds_limit_is_declared_not_silently_passed(self):
        r = gr.evaluate(wrap([el("ok", 0, 0, 100, 20)]))
        self.assertTrue(r["unmeasured_by_design"])

    def test_duplicate_findings_are_collapsed(self):
        """Same node measured as a declared spec AND a discovered leaf."""
        a = el("spec", 1, 19, 520, 30, parent={"x": 0, "y": 0, "w": 400, "h": 200})
        b = el("grp#0", 1, 19, 520, 30, parent={"x": 0, "y": 0, "w": 400, "h": 200})
        r = gr.evaluate(wrap([a, b]))
        self.assertEqual(len([f for f in r["findings"] if f["rule"] == "containment_breach"]), 1)

    def test_hidden_elements_are_skipped(self):
        e = el("h", 1, 19, 520, 30, parent={"x": 0, "y": 0, "w": 400, "h": 200})
        e["kind"] = "hidden"
        e["hidden_reason"] = "display-none"
        self.assertEqual(gr.evaluate(wrap([e]))["findings"], [])

    def test_main_exit_2_on_findings(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(wrap([el("t", 1, 19, 520, 30, parent={"x": 0, "y": 0, "w": 400, "h": 200})]), fh)
            path = fh.name
        self.assertEqual(gr.main(["--input", path, "--json"]), 2)


class ProbeSourceCase(unittest.TestCase):
    PROBE = META / "dom_geometry_probe.js"

    def test_probe_file_exists(self):
        self.assertTrue(self.PROBE.exists())

    def test_probe_is_syntactically_valid_js(self):
        r = subprocess.run(["node", "--check", str(self.PROBE)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    @staticmethod
    def _code_only(src: str) -> str:
        """Strip comments — the docstring legitimately NAMES the things it refuses to
        collect, so a whole-file grep flags the very sentence promising safety."""
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        return re.sub(r"^\s*//.*$", "", src, flags=re.M)

    def test_probe_never_exports_page_text_or_html(self):
        """The reviewed page is untrusted and this output reaches an LLM."""
        code = self._code_only(self.PROBE.read_text())
        for forbidden in (".outerHTML", ".innerHTML", ".innerText"):
            self.assertNotIn(forbidden, code, f"probe must never emit {forbidden}")
        # textContent is permitted ONLY to derive a length/boolean, never emitted raw.
        for m in re.finditer(r"textContent", code):
            tail = code[m.end():m.end() + 60]
            self.assertRegex(
                tail, r"\|\|\s*\"\"\)\.trim\(\)\.length",
                "textContent may only feed a length check, never be emitted",
            )

    def test_probe_includes_root_in_enumeration(self):
        """`root.querySelectorAll('*')` excludes root — that omission caused a false clean."""
        self.assertIn("[root, ...root.querySelectorAll", self.PROBE.read_text())


if __name__ == "__main__":
    unittest.main()
