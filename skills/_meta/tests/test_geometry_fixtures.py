#!/usr/bin/env python3
"""Browser-integration tests for the geometry corpora (S073).

    python -m pytest skills/_meta/tests/test_geometry_fixtures.py -v

These render REAL HTML through a REAL browser, unlike test_geometry_rules.py which feeds
the evaluator hand-written JSON. That distinction earned its keep immediately: the JSON
tests all passed while the first adversarial run produced TEN false positives, because
hand-written fixtures only prove the rules match the author's mental model, whereas
Chrome's layout engine is where the surprises are.

Two corpora, opposite obligations:

  adversarial.html   every construct is legitimate  -> MUST yield zero findings
  incident-cart.html every construct is a defect    -> MUST yield findings for each shape

Skipped rather than failed when the browser runtime is absent, since that is an
environment gap, not a regression — but never silently passed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

META = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "geometry"
sys.path.insert(0, str(META))

import geometry_rules as gr  # noqa: E402

MEASURE = META / "geometry_measure.mjs"
CHROME_CANDIDATES = ["/bin/google-chrome", "/usr/bin/google-chrome", "/usr/bin/chromium"]


def _runtime_available() -> str:
    """Return a reason string when the browser runtime is unusable, else ''."""
    if not shutil.which("node"):
        return "node not on PATH"
    if not any(Path(c).exists() for c in CHROME_CANDIDATES):
        return "no chrome binary found"
    probe = Path.home() / ".claude" / "node_modules" / "puppeteer-core"
    if not probe.exists():
        return "puppeteer-core not installed at ~/.claude/node_modules"
    return ""


SKIP_REASON = _runtime_available()


def measure(fixture: str, *, discover_root: str = "body", specs=None, viewports=None) -> dict:
    payload = {
        "product_url": f"file://{(FIXTURES / fixture).resolve()}",
        "breakpoints": viewports or {
            "mobile": {"width": 390, "height": 844},
            "desktop": {"width": 1440, "height": 900},
        },
        "specs": specs or [],
        "discover": {"root": discover_root, "min_members": 2},
    }
    proc = subprocess.run(
        ["node", str(MEASURE)], input=json.dumps(payload),
        capture_output=True, text=True, timeout=180,
    )
    if not proc.stdout.strip():
        raise AssertionError(f"measure produced no output (rc={proc.returncode}): {proc.stderr[:400]}")
    return json.loads(proc.stdout)


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class AdversarialCorpusCase(unittest.TestCase):
    """Every construct here is CORRECT. Any finding is a false positive."""

    @classmethod
    def setUpClass(cls):
        cls.measurement = measure("adversarial.html")

    def test_measurement_completed(self):
        self.assertEqual(self.measurement["outcome"], "MEASURED", self.measurement.get("errors"))

    def test_zero_findings_at_the_most_sensitive_floor(self):
        report = gr.evaluate(self.measurement, {"severity_floor": "info"})
        self.assertEqual(
            report["findings"], [],
            "false positives on the adversarial corpus:\n"
            + "\n".join(f"  {f['rule']}: {f['summary']}" for f in report["findings"]),
        )
        self.assertEqual(report["verdict"], "PASS")

    def test_sticky_scroll_pane_is_not_clipped_content(self):
        report = gr.evaluate(self.measurement, {"severity_floor": "info"})
        self.assertNotIn("clipped_content", {f["rule"] for f in report["findings"]})

    def test_repeated_sections_are_discovered_but_not_flagged(self):
        """Discovery must still FIND the repeated sections — silence here would mean the
        corpus passes only because nothing was looked at."""
        groups = self.measurement["measurements"]["desktop"]["groups"]
        self.assertTrue(groups, "no repeated groups discovered — corpus proves nothing")


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class IncidentRegressionCase(unittest.TestCase):
    """Every construct here is a real defect from the incident."""

    @classmethod
    def setUpClass(cls):
        cls.measurement = measure(
            "incident-cart.html",
            discover_root="#cart",
            specs=[
                {"id": "price", "selector": ".price", "cardinality": "many"},
                {"id": "totals", "selector": "#totals"},
                {"id": "cardnum", "selector": "#cardnum"},
            ],
        )
        cls.report = gr.evaluate(cls.measurement, {"severity_floor": "info"})
        cls.fired = {f["rule"] for f in cls.report["findings"]}

    def test_measurement_completed(self):
        self.assertEqual(self.measurement["outcome"], "MEASURED", self.measurement.get("errors"))

    def test_verdict_is_fail(self):
        self.assertEqual(self.report["verdict"], "FAIL")

    def test_every_price_is_measured_not_just_the_first(self):
        """The original primitive used querySelector and saw one of three prices."""
        prices = [e for e in self.measurement["measurements"]["desktop"]["elements"]
                  if e.get("spec_id") == "price"]
        self.assertGreaterEqual(len(prices), 3)

    def test_collapsed_line_prices_detected(self):
        self.assertIn("repeated_collapse", self.fired)

    def test_table_overflowing_its_panel_detected(self):
        self.assertIn("containment_breach", self.fired)

    def test_clipped_card_digits_detected(self):
        self.assertIn("text_clipping", self.fired)

    def test_findings_carry_numbers_not_adjectives(self):
        """A human must be able to confirm a fix from the report. 'Adjusted the CSS' is
        unconfirmable; a before/after number is checkable."""
        for f in self.report["findings"]:
            numeric = any(
                isinstance(v, (int, float))
                for k, v in f.items() if k not in ("severity", "rule")
            ) or any(ch.isdigit() for ch in f["summary"])
            self.assertTrue(numeric, f"finding carries no measurement: {f}")


class CorpusPresenceCase(unittest.TestCase):
    """Runs even without a browser: the corpora themselves must not go missing."""

    def test_both_corpora_exist(self):
        self.assertTrue((FIXTURES / "adversarial.html").exists())
        self.assertTrue((FIXTURES / "incident-cart.html").exists())

    def test_runtime_gap_is_reported_not_hidden(self):
        if SKIP_REASON:
            sys.stderr.write(f"\n[geometry fixtures skipped] {SKIP_REASON}\n")
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
