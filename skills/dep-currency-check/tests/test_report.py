"""Tests for report.py — assembly + rendering."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from dep_currency_check.compare import Gap
from dep_currency_check.manifests import Dependency, Manifest
from dep_currency_check.registry import CVE
from dep_currency_check.report import (
    Finding, Report, assemble_report, compute_blocks_build,
    render_json, render_markdown, render_osv_records, render_table,
    render_yaml, SCHEMA_VERSION,
)


def make_finding(name: str = "requests", is_transitive: bool = False,
                  is_dev: bool = False, with_critical_cve: bool = False,
                  with_fix: bool = True) -> Finding:
    d = Dependency(
        name=name, declared_version="2.27.1", constraint_type="exact",
        ecosystem="python", is_transitive=is_transitive, is_dev=is_dev,
    )
    g = Gap(
        dep=d, declared_resolves_to="2.27.1", latest_stable="2.32.3",
        gap_kind="major_behind", semver_distance=(0, 5, 2),
        last_release_age_days=None,
    )
    cves = tuple()
    if with_critical_cve:
        cve = CVE(
            id="CVE-2024-35195", severity="critical", cvss_score=7.5,
            summary="...", affected_range="<2.32.0",
            fixed_versions=("2.32.0",) if with_fix else tuple(),
            published=None, source="osv", osv_id="GHSA-x",
        )
        cves = (cve,)
    blocks = compute_blocks_build({"dep": d, "cves": cves})
    return Finding(dep=d, gap=g, cves=cves, blocks_build=blocks)


class TestBlocksBuild(unittest.TestCase):
    def test_blocks_build_true_for_critical_direct_prod_with_fix(self):
        f = make_finding(with_critical_cve=True, with_fix=True)
        self.assertTrue(f.blocks_build)

    def test_blocks_build_false_for_transitive(self):
        f = make_finding(is_transitive=True, with_critical_cve=True,
                          with_fix=True)
        self.assertFalse(f.blocks_build)

    def test_blocks_build_false_for_dev(self):
        f = make_finding(is_dev=True, with_critical_cve=True, with_fix=True)
        self.assertFalse(f.blocks_build)

    def test_blocks_build_false_when_no_fix_available(self):
        f = make_finding(with_critical_cve=True, with_fix=False)
        self.assertFalse(f.blocks_build)


class TestRenderJSON(unittest.TestCase):
    def test_schema_version_field(self):
        r = assemble_report(Path("/tmp"), [], [], grounding_mode="full")
        out = json.loads(render_json(r))
        self.assertEqual(out["schema_version"], SCHEMA_VERSION)

    def test_findings_in_output(self):
        f = make_finding(with_critical_cve=True)
        r = assemble_report(Path("/tmp"), [], [f], grounding_mode="full")
        out = json.loads(render_json(r))
        self.assertEqual(len(out["findings"]), 1)
        self.assertEqual(out["findings"][0]["package"], "requests")
        self.assertTrue(out["findings"][0]["blocks_build"])

    def test_osv_records_embedded_when_cves_present(self):
        f = make_finding(with_critical_cve=True)
        r = assemble_report(Path("/tmp"), [], [f], grounding_mode="full")
        out = json.loads(render_json(r))
        self.assertEqual(len(out["osv_records"]), 1)
        self.assertEqual(out["osv_records"][0]["id"], "CVE-2024-35195")


class TestRenderMarkdown(unittest.TestCase):
    def test_renders_table_for_findings(self):
        f = make_finding(with_critical_cve=True)
        r = assemble_report(Path("/tmp"), [], [f], grounding_mode="full")
        out = render_markdown(r)
        self.assertIn("dep-currency-check", out)
        self.assertIn("requests", out)
        self.assertIn("YES", out)  # blocks?


class TestRenderTable(unittest.TestCase):
    def test_table_with_findings(self):
        f = make_finding(with_critical_cve=True)
        r = assemble_report(Path("/tmp"), [], [f], grounding_mode="full")
        out = render_table(r)
        self.assertIn("requests", out)
        self.assertIn("|", out)

    def test_table_no_findings(self):
        r = assemble_report(Path("/tmp"), [], [], grounding_mode="full")
        out = render_table(r)
        self.assertIn("No findings", out)


class TestRenderYAML(unittest.TestCase):
    def test_yaml_dumps(self):
        f = make_finding(with_critical_cve=True)
        r = assemble_report(Path("/tmp"), [], [f], grounding_mode="full")
        out = render_yaml(r)
        self.assertIn("schema_version: dep-currency.v1", out)
        self.assertIn("requests", out)


class TestRenderOSV(unittest.TestCase):
    def test_osv_records_only(self):
        f = make_finding(with_critical_cve=True)
        r = assemble_report(Path("/tmp"), [], [f], grounding_mode="full")
        out = json.loads(render_osv_records(r))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "CVE-2024-35195")


if __name__ == "__main__":
    unittest.main()
