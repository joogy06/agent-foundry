#!/usr/bin/env python3
"""Tests for skill_resolve.py and skill_overlap.py (S073).

    python -m pytest skills/_meta/tests/test_skill_resolve.py -v

Regression anchors: the two references that were live in `forge/SKILL.md` and
`team-manager/SKILL.md` for a long time while neither plugin was ever installed.
If either stops being detected, the guard has regressed.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import skill_overlap  # noqa: E402
import skill_resolve  # noqa: E402


def _mkskill(root: Path, name: str, description: str = "A skill.", family: str | None = None,
             boundary: str | None = None) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    fam = f"family: {family}\n" if family else ""
    # `boundary` writes the frontmatter key that declares how this skill differs from a
    # colliding neighbour — the thing --update-baseline now requires before accepting a pair.
    bnd = f"{boundary}\n" if boundary else ""
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n{fam}{bnd}---\n\n# {name}\n")


class ResolveCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.skills = self.home / "skills"
        self.skills.mkdir(parents=True)
        (self.home / "agents").mkdir()
        (self.home / "agents" / "bob.md").write_text("# bob\n")
        (self.home / "settings.json").write_text(json.dumps(
            {"enabledPlugins": {"superpowers@claude-plugins-official": True,
                                "disabled-thing@somewhere": False}}))
        _mkskill(self.skills, "ux-reviewer", "Review built UI for usability.")
        _mkskill(self.skills, "qa-reviewer", "Check code quality and regressions.")
        _mkskill(self.skills, "rhel-databases", "Databases on RHEL.", family="rhel")
        _mkskill(self.skills, "rhel-monitoring", "Monitoring on RHEL.", family="rhel")
        # sub-skill directory (founder/founder-ideation shape)
        sub = self.skills / "founder" / "founder-ideation"
        sub.mkdir(parents=True)
        (sub / "SKILL.md").write_text("---\nname: founder-ideation\ndescription: Ideate.\n---\n")
        _mkskill(self.skills, "founder", "Parent founder skill.")
        self.index = skill_resolve.build_index(self.skills)
        self.enabled = skill_resolve.load_enabled_plugins(self.home)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_enabled_plugins_strips_marketplace_suffix(self):
        self.assertIn("superpowers", self.enabled)

    def test_disabled_plugin_is_not_enabled(self):
        self.assertNotIn("disabled-thing", self.enabled)

    def test_bare_skill_resolves(self):
        r = skill_resolve.resolve(["ux-reviewer"], self.index, self.enabled)
        self.assertEqual(r["resolved"], ["ux-reviewer"])
        self.assertEqual(r["unresolved"], [])

    def test_missing_skill_is_unresolved(self):
        r = skill_resolve.resolve(["no-such-skill"], self.index, self.enabled)
        self.assertEqual(len(r["unresolved"]), 1)

    def test_enabled_plugin_skill_resolves(self):
        r = skill_resolve.resolve(["superpowers:test-driven-development"], self.index, self.enabled)
        self.assertEqual(r["unresolved"], [])

    def test_REGRESSION_uninstalled_plugin_skill_is_caught(self):
        """frontend-design:frontend-design — live in team-manager, never installed."""
        r = skill_resolve.resolve(["frontend-design:frontend-design"], self.index, self.enabled)
        self.assertEqual(len(r["unresolved"]), 1)
        self.assertIn("enabledPlugins", r["unresolved"][0]["reason"])

    def test_REGRESSION_uninstalled_plugin_agent_is_caught(self):
        """multi-platform-apps:ui-ux-designer — live in forge, never installed."""
        r = skill_resolve.resolve_agent_types(
            ["multi-platform-apps:ui-ux-designer"], self.home, self.enabled)
        self.assertEqual(len(r["unresolved"]), 1)

    def test_sub_skill_path_resolves(self):
        r = skill_resolve.resolve(["founder/founder-ideation"], self.index, self.enabled)
        self.assertEqual(r["unresolved"], [])

    def test_family_expands_to_members(self):
        r = skill_resolve.resolve(["family:rhel"], self.index, self.enabled)
        self.assertEqual(r["unresolved"], [])
        self.assertEqual(sorted(r["resolved"]), ["rhel-databases", "rhel-monitoring"])

    def test_empty_family_is_an_error_not_empty_success(self):
        r = skill_resolve.resolve(["family:nonexistent"], self.index, self.enabled)
        self.assertEqual(len(r["unresolved"]), 1)
        self.assertEqual(r["resolved"], [])

    def test_duplicates_are_collapsed(self):
        r = skill_resolve.resolve(["ux-reviewer", "ux-reviewer", "family:rhel", "rhel-databases"],
                                  self.index, self.enabled)
        self.assertEqual(len(r["resolved"]), len(set(r["resolved"])))

    def test_custom_agent_resolves(self):
        r = skill_resolve.resolve_agent_types(["bob"], self.home, self.enabled)
        self.assertEqual(r["unresolved"], [])

    def test_builtin_agent_resolves(self):
        r = skill_resolve.resolve_agent_types(["general-purpose"], self.home, self.enabled)
        self.assertEqual(r["unresolved"], [])

    def test_unknown_bare_agent_warns_but_does_not_fail(self):
        r = skill_resolve.resolve_agent_types(["mystery-agent"], self.home, self.enabled)
        self.assertEqual(r["unresolved"], [])
        self.assertEqual(len(r["warnings"]), 1)

    def test_main_exit_2_on_unresolvable(self):
        rc = skill_resolve.main(["no-such-skill", "--claude-home", str(self.home), "--json"])
        self.assertEqual(rc, 2)

    def test_main_exit_0_when_all_resolve(self):
        rc = skill_resolve.main(["ux-reviewer", "--claude-home", str(self.home), "--json"])
        self.assertEqual(rc, 0)


class OverlapCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.skills = Path(self.tmp.name) / "skills"
        self.skills.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_near_identical_descriptions_score_high(self):
        _mkskill(self.skills, "rhel-web", "Configure nginx apache web servers tuning tls certificates on RHEL hosts")
        _mkskill(self.skills, "ubuntu-web", "Configure nginx apache web servers tuning tls certificates on Ubuntu hosts")
        _mkskill(self.skills, "trading", "Backtest equity strategies walk forward analysis slippage models")
        v = skill_overlap.tfidf(skill_overlap.collect_descriptions(self.skills))
        pairs = skill_overlap.find_pairs(v, 0.30)
        self.assertTrue(pairs, "expected the near-identical pair to be detected")
        self.assertEqual({pairs[0][1], pairs[0][2]}, {"rhel-web", "ubuntu-web"})

    def test_unrelated_descriptions_do_not_pair(self):
        _mkskill(self.skills, "alpha", "Backtest equity strategies walk forward slippage")
        _mkskill(self.skills, "beta", "Configure kubernetes ingress controllers and service meshes")
        v = skill_overlap.tfidf(skill_overlap.collect_descriptions(self.skills))
        self.assertEqual(skill_overlap.find_pairs(v, 0.30), [])

    def test_skill_without_description_is_skipped(self):
        d = self.skills / "nodesc"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: nodesc\n---\n# no description\n")
        self.assertNotIn("nodesc", skill_overlap.collect_descriptions(self.skills))

    def test_pair_key_is_order_independent(self):
        self.assertEqual(skill_overlap._key("b", "a"), skill_overlap._key("a", "b"))

    def test_baseline_suppresses_known_pair(self):
        # These carry `applies_when:` because they are the environment-discriminated case:
        # near-identical BY DESIGN, resolved against the host inventory rather than by prose.
        # Accepting them into the baseline is legitimate precisely BECAUSE that is declared.
        _mkskill(self.skills, "rhel-web", "Configure nginx apache web servers tuning tls on RHEL hosts",
                 boundary="applies_when: os_family == rhel")
        _mkskill(self.skills, "ubuntu-web", "Configure nginx apache web servers tuning tls on Ubuntu hosts",
                 boundary="applies_when: os_family == ubuntu")
        base = Path(self.tmp.name) / "baseline.json"
        rc_before = skill_overlap.main(["--skills-root", str(self.skills), "--baseline", str(base), "--json"])
        self.assertEqual(rc_before, 2, "a fresh collision must fail")
        skill_overlap.main(["--skills-root", str(self.skills), "--baseline", str(base), "--update-baseline"])
        rc_after = skill_overlap.main(["--skills-root", str(self.skills), "--baseline", str(base), "--json"])
        self.assertEqual(rc_after, 0, "accepted pair must not re-flag")

    def test_update_baseline_refuses_an_undifferentiated_pair(self):
        """The baseline must not become a snooze button on the signal it exists to raise.

        A pair where NEITHER skill says anything about its neighbour has not been handled,
        only silenced. The scanner can check that a boundary EXISTS; judging whether the
        sentence is any good stays a human act.
        """
        _mkskill(self.skills, "alpha-thing", "Manage widget inventory levels and widget stock counts")
        _mkskill(self.skills, "beta-thing", "Manage widget inventory levels and widget stock counts")
        base = Path(self.tmp.name) / "refused.json"
        rc = skill_overlap.main(["--skills-root", str(self.skills), "--baseline", str(base), "--update-baseline"])
        self.assertEqual(rc, 2, "an undifferentiated pair must not be baselineable")
        self.assertFalse(base.exists(), "a refused run must not write a baseline")

    def test_update_baseline_accepts_once_one_side_declares_a_boundary(self):
        _mkskill(self.skills, "alpha-thing", "Manage widget inventory levels and widget stock counts")
        _mkskill(self.skills, "beta-thing", "Manage widget inventory levels and widget stock counts",
                 boundary="disambiguation: Counts stock. Inventory levels are alpha-thing.")
        base = Path(self.tmp.name) / "accepted.json"
        rc = skill_overlap.main(["--skills-root", str(self.skills), "--baseline", str(base), "--update-baseline"])
        self.assertEqual(rc, 0)
        self.assertTrue(base.exists())

    def test_unreadable_baseline_fails_closed(self):
        _mkskill(self.skills, "a", "one two three four five six")
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text("{ not json")
        rc = skill_overlap.main(["--skills-root", str(self.skills), "--baseline", str(bad), "--json"])
        self.assertEqual(rc, 2, "an unreadable baseline must never read as clean")


if __name__ == "__main__":
    unittest.main()
