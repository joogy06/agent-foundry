#!/usr/bin/env python3
"""test_contract_lint.py -- #313: the describe -> question -> done-when contract, checked.

Design docs/plans/2026-09-25-apply-the-contract-design.md sections 3, 4, 6, 7 and 10:
  DW-1 (fixture half)  design -> plan -> WP -> review verdict keeps its DW ids at every hand-off
  DW-2                 the repo lints with 0 errors; the inventory matches the markers; every
                       template carries the fields and every section-4 loop a bound + on_exhaust
  DW-5                 CLAUDE.md and vs-code/AGENTS.md carry the ask-size block; the Autonomy
                       "still pause and ask" list is intact
  DW-6                 forge's question and presentation steps apply the ask-size rule
plus the rules themselves (C001-C005) on synthetic trees, and the schema halves of section 3.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_META = Path(__file__).resolve().parent.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import contract_lint as cl  # noqa: E402

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import skill_corpus  # noqa: E402

_TREE = _META.parent.parent
#: Every live-tree read names THIS tree, so the module that was imported first cannot choose it.
_SKILLS = _TREE / "skills"
FIX = _TREE / "tests" / "fixtures" / "contract"
SCRIPT = _META / "contract_lint.py"

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

BLOCK_LINES = (
    "## Ask size sets the contract",
    "- TRIVIAL/SIMPLE (interactive): the ask is the brief; ask only if readings genuinely split; done is implicit.",
    "- MEDIUM: restate the ask and your done-when in one line; ask at most one material question.",
    "- COMPLEX/long: agree goal, non-goals, constraints and a checkable done-when first; one bounded question round.",
    "- Stop at done-when or a blocker; at most 2 automatic fix rounds, then the user decides; existing gates still apply.",
)

FULL = ("Goal: g\nNon-goals: n\nOpen questions: none\nDone when: d\nStop when: s\n")


def _tree(files):
    td = tempfile.TemporaryDirectory()
    root = Path(td.name)
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return td, root


def _codes(findings, severity="E"):
    return sorted(f.code for f in findings if f.severity == severity)


class TheRepo(unittest.TestCase):
    """DW-2: the shipped tree."""

    @classmethod
    def setUpClass(cls):
        cls.findings = cl.lint_tree(_TREE)

    def test_the_repo_lints_with_zero_errors(self):
        errors = [str(f) for f in self.findings if f.severity == "E"]
        self.assertEqual(errors, [])

    def test_every_pinned_template_and_loop_has_its_marker(self):
        spawns, loops = {}, {}
        for path in cl.iter_targets(_TREE):
            rel = path.relative_to(_TREE).as_posix()
            _, s, lp, _ = cl.scan_text(rel, path.read_text(encoding="utf-8"))
            spawns.update({k: rel for k in s})
            loops.update({k: (rel, v[1], v[2]) for k, v in lp.items()})
        self.assertEqual(spawns, dict(cl.SPAWN_BRIEFS))
        self.assertEqual(loops, dict(cl.LOOPS))

    def test_the_section_4_loops_are_all_pinned_with_a_bound(self):
        wanted = {"forge.d21-fix-loop", "development-lifecycle.review", "qa-reviewer.re-review",
                  "challenger.re-challenge", "alf.carry-over"}
        self.assertTrue(wanted <= set(cl.LOOPS))
        for lid, (_p, bound, oe) in cl.LOOPS.items():
            self.assertIn(bound, cl.BOUND_RANGE, lid)
            self.assertIn(oe, cl.ON_EXHAUST, lid)
        self.assertEqual(cl.LOOPS["forge.d21-fix-loop"][1:], (2, "user"))

    def test_the_section_3_templates_are_all_pinned(self):
        wanted = {"forge.approach", "forge.ux", "forge.challenger-claude", "forge.challenger-codex",
                  "forge.explorer-codex", "forge.bob", "alf.bob", "agent-teams.lead",
                  "team-manager.specialist", "cross-cli-deliberation.ballot", "bob-stage.stage",
                  "codex-orchestration.delta-challenger", "adversarial-team-brainstorm.team"}
        self.assertTrue(wanted <= set(cl.SPAWN_BRIEFS))

    def test_every_template_points_at_the_canonical_block(self):
        for sid, rel in cl.SPAWN_BRIEFS.items():
            if sid == "spawn-brief.canonical":
                continue
            self.assertIn("skills/_meta/spawn-brief.md", (_TREE / rel).read_text(encoding="utf-8"), sid)

    def test_the_exclusions_carry_reasons(self):
        self.assertIn("agents/pa.md", cl.EXCLUSIONS)
        self.assertIn("agents/wiki.md", cl.EXCLUSIONS)
        for rel, why in cl.EXCLUSIONS.items():
            self.assertGreater(len(why), 20, rel)

    def test_the_lint_lints_its_own_source_cleanly(self):
        findings, spawns, loops, _ = cl.scan_text("contract_lint.py", SCRIPT.read_text(encoding="utf-8"))
        self.assertEqual((findings, spawns, loops), ([], {}, {}))

    def test_the_cli_exits_zero_on_the_repo(self):
        proc = subprocess.run([sys.executable, str(SCRIPT), "lint", str(_TREE), "--json"],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["errors"], [])


class TheRules(unittest.TestCase):
    def test_c001_a_missing_or_empty_field_fails(self):
        for drop in ("Goal: g\n", "Non-goals: n\n", "Open questions: none\n", "Done when: d\n", "Stop when: s\n"):
            text = "<!-- spawn-brief.v1 id=x.y -->\n```\n" + FULL.replace(drop, "") + "```\n"
            f, _, _, _ = cl.scan_text("a.md", text)
            self.assertEqual(_codes(f), ["C001"], drop)
        empty = "<!-- spawn-brief.v1 id=x.y -->\n```\n" + FULL.replace("Done when: d", "Done when:   ") + "```\n"
        self.assertEqual(_codes(cl.scan_text("a.md", empty)[0]), ["C001"])
        whole = "<!-- spawn-brief.v1 id=x.y -->\n```\n" + FULL + "```\n"
        self.assertEqual(cl.scan_text("a.md", whole)[0], [])

    def test_c001_a_field_outside_the_fenced_extent_does_not_count(self):
        text = "<!-- spawn-brief.v1 id=x.y -->\n```\nGoal: g\n```\n" + FULL
        self.assertEqual(_codes(cl.scan_text("a.md", text)[0]), ["C001"])

    def test_c001_markers_in_a_comment_lead_and_an_end_marker(self):
        text = "// <!-- spawn-brief.v1 id=x.y -->\nconst p = `" + FULL + "`;\n// <!-- /spawn-brief.v1 -->\nGoal: late\n"
        self.assertEqual(cl.scan_text("a.js", text)[0], [])
        cut = "# <!-- spawn-brief.v1 id=x.y -->\nGoal: g\n# <!-- /spawn-brief.v1 -->\n" + FULL
        self.assertEqual(_codes(cl.scan_text("a.md", cut)[0]), ["C001"])

    def test_only_an_exact_marker_line_counts(self):
        prose = ("Put `<!-- spawn-brief.v1 id=x.y -->` on the line before a template, and\n"
                 "a loop gets `<!-- contract:loop id=z bound=9 -->` beside it.\n")
        f, spawns, loops, _ = cl.scan_text("a.md", prose)
        self.assertEqual((f, spawns, loops), ([], {}, {}))

    def test_c002_a_loop_needs_a_bound_in_1_to_5_and_an_on_exhaust(self):
        good = "<!-- contract:loop id=a.b bound=2 on_exhaust=user -->\n"
        self.assertEqual(cl.scan_text("a.md", good)[0], [])
        for bad in ("<!-- contract:loop id=a.b on_exhaust=user -->", "<!-- contract:loop id=a.b bound=0 on_exhaust=user -->",
                    "<!-- contract:loop id=a.b bound=6 on_exhaust=stop -->", "<!-- contract:loop id=a.b bound=two on_exhaust=stop -->",
                    "<!-- contract:loop id=a.b bound=2 -->", "<!-- contract:loop id=a.b bound=2 on_exhaust=retry -->"):
            self.assertEqual(_codes(cl.scan_text("a.md", bad + "\n")[0]), ["C002"], bad)

    def test_c003_inventory_drift_fails(self):
        td, root = _tree({"skills/a/SKILL.md": "text\n"})
        with td:
            codes = _codes(cl.lint_tree(root))
            self.assertIn("C003", codes)                           # every pinned marker is missing
            msgs = " ".join(str(f) for f in cl.lint_tree(root))
            self.assertIn("forge.bob", msgs)
            self.assertIn("forge.d21-fix-loop", msgs)

    def test_c003_an_unpinned_or_duplicated_marker_fails(self):
        text = "<!-- spawn-brief.v1 id=nobody.pinned -->\n```\n" + FULL + "```\n"
        f, spawns, loops, _ = cl.scan_text("x.md", text)
        extra = cl.check_inventory(Path("."), {"nobody.pinned": ("x.md", 1)}, {})
        self.assertTrue(any("not in the pinned inventory" in x.message for x in extra))
        dup = text + text
        self.assertIn("C003", _codes(cl.scan_text("x.md", dup)[0]))

    def test_c004_an_unmarked_candidate_is_only_a_warning(self):
        td, root = _tree({"skills/a/SKILL.md": 'Agent(subagent_type="general-purpose"):\n"do it"\n'})
        with td:
            f = cl.lint_tree(root, inventory=False)
            self.assertEqual(_codes(f, "W"), ["C004"])
            self.assertEqual(_codes(f), [])


class TheDoneWhenChain(unittest.TestCase):
    """DW-1, the fixture-driven half: design -> plan -> WP -> review verdict."""

    def setUp(self):
        self.design = (FIX / "design.md").read_text(encoding="utf-8")
        self.plan = cl.load_plan(FIX / "plan.json")

    def test_the_design_dws_are_read_with_their_integration_mark(self):
        self.assertEqual(cl.design_dws(self.design), {"DW-1": False, "DW-2": False, "DW-3": True})
        self.assertIsNone(cl.design_dws("# no done when here\n"))

    def test_the_plan_covers_exactly_the_non_integration_dws(self):
        self.assertEqual(cl.check_plan(self.plan, cl.design_dws(self.design)), [])
        union = {d for wp in self.plan["work_packages"] for d in wp["covers"]}
        self.assertEqual(union, {"DW-1", "DW-2"})

    def test_the_verdict_rules_every_dw_with_evidence(self):
        verdict = json.loads((FIX / "verdict.json").read_text(encoding="utf-8"))
        problems, done = cl.verdict_problems(verdict, cl.design_dws(self.design))
        self.assertEqual((problems, done), ([], True))

    def test_the_ids_survive_every_hand_off(self):
        dws = set(cl.design_dws(self.design))
        verdict = json.loads((FIX / "verdict.json").read_text(encoding="utf-8"))
        covered = {d for wp in self.plan["work_packages"] for d in wp["covers"]}
        integration = {d for d, i in cl.design_dws(self.design).items() if i}
        self.assertEqual(covered | integration, dws)
        self.assertEqual(set(verdict), dws)

    def test_c005_an_uncovered_or_unknown_or_integration_dw_fails(self):
        dws = cl.design_dws(self.design)
        plan = json.loads(json.dumps(self.plan))
        plan["work_packages"][1]["covers"] = []
        self.assertIn("uncovered DWs: DW-2", " ".join(f.message for f in cl.check_plan(plan, dws)))
        plan["work_packages"][1]["covers"] = ["DW-2", "DW-9"]
        self.assertIn("covers unknown DW-9", " ".join(f.message for f in cl.check_plan(plan, dws)))
        plan["work_packages"][1]["covers"] = ["DW-2", "DW-3"]
        self.assertIn("(integration)", " ".join(f.message for f in cl.check_plan(plan, dws)))
        del plan["work_packages"][1]["covers"]
        self.assertIn("no `covers`", " ".join(f.message for f in cl.check_plan(plan, dws)))
        plan["work_packages"][1]["covers"] = ["DW-2"]
        plan["work_packages"][1]["acceptance_criteria"] = []
        self.assertIn("acceptance_criteria is empty", " ".join(f.message for f in cl.check_plan(plan, dws)))

    def test_covers_is_optional_when_the_design_has_no_done_when(self):
        plan = json.loads(json.dumps(self.plan))
        for wp in plan["work_packages"]:
            del wp["covers"]
        self.assertEqual(cl.check_plan(plan, None), [])

    def test_a_verdict_that_skips_a_dw_or_lacks_evidence_or_is_unverified_is_not_done(self):
        dws = cl.design_dws(self.design)
        verdict = json.loads((FIX / "verdict.json").read_text(encoding="utf-8"))
        v = dict(verdict)
        del v["DW-3"]
        self.assertEqual(cl.verdict_problems(v, dws), (["DW-3: not ruled"], False))
        v = dict(verdict, **{"DW-2": {"ruling": "met", "evidence": ""}})
        self.assertFalse(cl.verdict_problems(v, dws)[1])
        v = dict(verdict, **{"DW-2": {"ruling": "unverified", "evidence": "no runner here"}})
        self.assertEqual(cl.verdict_problems(v, dws), ([], False))       # unverified counts as not met
        v = dict(verdict, **{"DW-7": {"ruling": "met", "evidence": "own bar"}})
        self.assertIn("not a DW of the design", " ".join(cl.verdict_problems(v, dws)[0]))

    def test_the_cli_check_plan_and_check_verdict(self):
        ok = subprocess.run([sys.executable, str(SCRIPT), "check-plan", str(FIX / "plan.json"), "--json"],
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertEqual(json.loads(ok.stdout)["dws"], ["DW-1", "DW-2", "DW-3"])
        v = subprocess.run([sys.executable, str(SCRIPT), "check-verdict", str(FIX / "verdict.json"),
                            "--design", str(FIX / "design.md"), "--json"],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        self.assertTrue(json.loads(v.stdout)["done"])

    def test_this_cycles_own_design_has_a_parseable_done_when(self):
        doc = (_TREE / "docs" / "plans" / "2026-09-25-apply-the-contract-design.md").read_text(encoding="utf-8")
        self.assertEqual(sorted(cl.design_dws(doc), key=lambda d: int(d[3:])), [f"DW-{i}" for i in range(1, 9)])


@unittest.skipIf(jsonschema is None, "jsonschema not installed")
class TheSchemas(unittest.TestCase):
    def setUp(self):
        self.wp_schema = json.loads((_META / "schemas" / "work-packages.v1.json").read_text(encoding="utf-8"))
        self.er_schema = json.loads((_META / "schemas" / "execution-report.v1.json").read_text(encoding="utf-8"))
        self.plan = json.loads((FIX / "plan.json").read_text(encoding="utf-8"))

    def _valid(self, schema, inst):
        return not list(jsonschema.Draft202012Validator(schema).iter_errors(inst))

    def test_the_fixture_plan_validates(self):
        self.assertTrue(self._valid(self.wp_schema, self.plan))

    def test_work_packages_rejects_empty_acceptance_criteria(self):
        plan = json.loads(json.dumps(self.plan))
        plan["work_packages"][0]["acceptance_criteria"] = []
        self.assertFalse(self._valid(self.wp_schema, plan))

    def test_work_packages_rejects_a_covers_value_that_does_not_match(self):
        for bad in (["dw-1"], ["DW-"], ["DW-1", "DW-1"], "DW-1", ["Done when 1"]):
            plan = json.loads(json.dumps(self.plan))
            plan["work_packages"][0]["covers"] = bad
            self.assertFalse(self._valid(self.wp_schema, plan), bad)

    def test_execution_report_clarification_shape(self):
        good = {"status": "PARTIAL", "built": [], "files_changed": [], "verification": {},
                "needs": {"kind": "clarification", "payload": {
                    "questions": [{"question": "SQLite or JSON?", "work_changes_if": "JSON: new lock, no migration"}],
                    "default_if_unanswered": "SQLite"}}}
        self.assertTrue(self._valid(self.er_schema, good))
        for mutate in (lambda r: r.update(status="COMPLETE"),
                       lambda r: r.update(files_changed=[{"path": "x"}]),
                       lambda r: r["needs"]["payload"].update(questions=[]),
                       lambda r: r["needs"]["payload"]["questions"].extend([{"question": "q", "work_changes_if": "w"}] * 3),
                       lambda r: r["needs"]["payload"].pop("default_if_unanswered"),
                       lambda r: r["needs"]["payload"]["questions"][0].pop("work_changes_if")):
            r = json.loads(json.dumps(good))
            mutate(r)
            self.assertFalse(self._valid(self.er_schema, r))
        other = {"status": "PARTIAL", "built": [], "files_changed": [{"path": "x"}], "verification": {},
                 "needs": {"kind": "user-decision", "payload": "why"}}
        self.assertTrue(self._valid(self.er_schema, other))          # other kinds are unchanged
        self.assertTrue(self._valid(self.er_schema, dict(other, needs=None)))


class StartupAndForge(unittest.TestCase):
    """DW-5 and DW-6."""

    def test_dw5_claude_md_and_agents_md_carry_the_block(self):
        for rel in ("global/CLAUDE.md", "vs-code/AGENTS.md"):
            text = (_TREE / rel).read_text(encoding="utf-8")
            for line in BLOCK_LINES:
                self.assertIn(line, text, rel)
            self.assertIn("`quick:` skips questions; `contract:` forces the full contract.", text, rel)

    def test_dw5_the_autonomy_pause_and_ask_list_is_intact(self):
        text = (_TREE / "global" / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("**Still pause and ask before:**\n- Design questions (architecture choices, UX decisions, "
                      "approach selection)\n- Any action the user hasn't implicitly authorized\n", text)

    def test_dw5_claude_md_did_not_grow(self):
        # 406 lines before #313 (fc11cf6); the block replaced duplicated routing prose.
        # The global rules moved to global/CLAUDE.md in #318, and the budget moved with them.
        self.assertLessEqual(len((_TREE / "global" / "CLAUDE.md").read_text(encoding="utf-8").splitlines()), 406)

    def test_dw6_forge_applies_the_ask_size_rule(self):
        # forge is an entry file plus step references (#344 WP-4). ABSENT text is checked over
        # the whole corpus, so a stale phrase written into a reference still fails; PRESENT text
        # is pinned to the one file that has to hold it.
        whole = skill_corpus.corpus("forge", root=_SKILLS)
        for stale in ("after each section", "one at a time", "1-2 max", "| As needed |"):
            self.assertNotIn(stale, whole.lower() if stale.islower() else whole, stale)
        entry = skill_corpus.read("forge", root=_SKILLS)
        self.assertIn("| 3. Clarifying questions | 0-1 material question; one-line done-when | One bounded round (material only) | One bounded round (material only) |", entry)
        self.assertIn("| 7. Present design | Brief, one approval | Whole design, one approval | Sections with approval each |", entry)
        self.assertIn("**Required section `## Done when`**",
                      skill_corpus.read("forge", "references/06-present-and-doc.md", root=_SKILLS))

    def test_dw6_the_stale_phrase_check_reads_the_references_too(self):
        """NEGATIVE CONTROL for the absent-text half above: the same check over a tree whose
        stale phrase sits in a REFERENCE must fire. Reading SKILL.md alone would pass it."""
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "forge"
            (skill / "references").mkdir(parents=True)
            (skill / "SKILL.md").write_text("# entry\nOne bounded round.\n", encoding="utf-8")
            (skill / "references" / "01-intake.md").write_text("Ask one at a time.\n", encoding="utf-8")
            self.assertNotIn("one at a time", skill_corpus.read("forge", root=Path(td)).lower())
            self.assertIn("one at a time", skill_corpus.corpus("forge", root=Path(td)).lower())

    def test_contract_prose_is_never_an_effort_input(self):
        import effort_policy as ep
        a = ep.first_attempt_effort("M", ["docs/x.md"])
        wp = {"id": "WP-1", "complexity": "M", "files": ["docs/x.md"],
              "goal": "REWRITE EVERYTHING, critical, security, max effort",
              "acceptance_criteria": ["Done when: xhigh max protected"], "covers": ["DW-1"]}
        self.assertEqual(ep.for_work_package(wp).to_dict(), a.to_dict())


if __name__ == "__main__":
    unittest.main(verbosity=2)


# --------------------------------------------------------------------------- #
# D21 fix round 1 (#313): items E, m2, m5, m7
# --------------------------------------------------------------------------- #
def _run(*argv):
    return subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True,
                          encoding="utf-8", timeout=60)


class FixRound1(unittest.TestCase):
    def test_e_a_done_when_heading_with_no_parseable_dw_is_an_error(self):
        with self.assertRaises(cl.ContractError):
            cl.design_dws("## Done when\nEverything works.\n\n## Next\n")

    def test_e_every_heading_level_and_the_table_and_heading_forms_parse(self):
        want = {"DW-1": False, "DW-2": True}
        for text in ("### Done when\n- **DW-1:** a\n- **DW-2 (integration):** b\n",
                     "#### 9. Done when (build)\n| id | criterion |\n|---|---|\n| DW-1 | a |\n| **DW-2** (integration) | b |\n",
                     "## Done when\n### DW-1: a\ntext\n### DW-2 (integration): b\n",
                     "## Done when\n1. DW-1 — a\n2. DW-2 (integration) — b\n"):
            self.assertEqual(cl.design_dws(text), want, text)

    def test_e_the_section_ends_at_a_heading_of_the_same_or_higher_level_only(self):
        text = "## Done when\n### DW-1: a\n### DW-2: b\n## Out of scope\n- DW-3: not a DW here\n"
        self.assertEqual(cl.design_dws(text), {"DW-1": False, "DW-2": False})

    def test_e_integration_is_anchored_right_after_the_id(self):
        text = "## Done when\n- **DW-1:** unlike the (integration) tests, this is unit-level.\n- DW-2 (integration): e2e\n"
        self.assertEqual(cl.design_dws(text), {"DW-1": False, "DW-2": True})

    def test_e_check_plan_errors_when_the_design_cannot_be_resolved(self):
        with tempfile.TemporaryDirectory() as td:
            plan = json.loads((FIX / "plan.json").read_text(encoding="utf-8"))
            plan["design_doc"] = "docs/plans/missing.md"
            plan["project_root"] = td
            p = Path(td) / "plan.json"
            p.write_text(json.dumps(plan), encoding="utf-8")
            out = _run("check-plan", str(p), "--json")
            self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
            self.assertIn("cannot be resolved", out.stdout)

    def test_e_check_plan_errors_on_a_heading_without_dws(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "design.md"
            d.write_text("# x\n\n### Done when\n| criterion |\n|---|\n| works |\n", encoding="utf-8")
            out = _run("check-plan", str(FIX / "plan.json"), "--design", str(d), "--json")
            self.assertEqual(out.returncode, 2, out.stdout + out.stderr)

    def test_e_check_plan_and_check_verdict_share_one_parser(self):
        self.assertIs(cl.check_plan.__globals__["design_dws"], cl.design_dws)
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "design.md"
            d.write_text("## Done when\n### DW-1: a\n### DW-2 (integration): b\n", encoding="utf-8")
            v = Path(td) / "v.json"
            v.write_text(json.dumps({"DW-1": {"ruling": "met", "evidence": "e"},
                                     "DW-2": {"ruling": "met", "evidence": ["e"]}}), encoding="utf-8")
            self.assertEqual(_run("check-verdict", str(v), "--design", str(d)).returncode, 0)
            plan = json.loads((FIX / "plan.json").read_text(encoding="utf-8"))
            plan["work_packages"] = plan["work_packages"][:1]
            p = Path(td) / "plan.json"
            p.write_text(json.dumps(plan), encoding="utf-8")
            self.assertEqual(_run("check-plan", str(p), "--design", str(d)).returncode, 0)

    def test_m2_evidence_must_be_a_non_empty_string_or_list_of_them(self):
        dws = {"DW-1": False}
        for ev in ("", " ", [], [""], ["ok", " "], [1], {"a": "b"}, 7, None):
            problems, done = cl.verdict_problems({"DW-1": {"ruling": "met", "evidence": ev}}, dws)
            self.assertTrue(problems, ev)
            self.assertFalse(done)
        self.assertEqual(cl.verdict_problems({"DW-1": {"ruling": "met", "evidence": ["a", "b"]}}, dws), ([], True))

    def test_m2_a_non_object_verdict_exits_3_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            for body in ("[1, 2]", "\"met\"", "{\"DW-1\": \"met\"}", "not json"):
                v = Path(td) / "v.json"
                v.write_text(body, encoding="utf-8")
                out = _run("check-verdict", str(v), "--design", str(FIX / "design.md"))
                self.assertIn(out.returncode, (2, 3), body)
                self.assertNotIn("Traceback", out.stderr, body)
                if body in ("[1, 2]", "\"met\"", "not json"):
                    self.assertEqual(out.returncode, 3, body)

    def test_m5_c004_matches_lowercase_agent_in_workflows(self):
        td, root = _tree({"workflows/w.js": "const r = await agent(prompt, {agentType: 'bob'});\n",
                          "skills/a/SKILL.md": "the agent(s) we spawn\n"})
        with td:
            f = cl.lint_tree(root, inventory=False)
            self.assertEqual([(x.path, x.code) for x in f if x.severity == "W"], [("workflows/w.js", "C004")])

    def test_m5_the_d21_and_spec_reviewer_spawns_are_pinned(self):
        self.assertEqual(cl.SPAWN_BRIEFS.get("forge.d21-reviewer"), "skills/forge/references/10-close-out.md")
        self.assertEqual(cl.SPAWN_BRIEFS.get("forge.spec-reviewer"), "skills/forge/references/08-spec-review.md")

    def test_345_a_reviewer_brief_without_purpose_fails_and_the_instructions_do_not_stand_in(self):
        """DW-2: the real template with only its `Purpose:` field removed. The instruction lines stay
        in place and mention the Purpose, so passing them would mean the pattern is too loose."""
        for sid in ("forge.spec-reviewer", "forge.d21-reviewer"):
            rel = cl.SPAWN_BRIEFS[sid]
            text = (_TREE / rel).read_text(encoding="utf-8")
            self.assertEqual(cl.scan_text(rel, text)[0], [], sid)
            lines = text.splitlines()
            cut = [ln for ln in lines if not ln.startswith("Purpose: [")]
            self.assertEqual(len(cut), len(lines) - 1, sid)
            self.assertIn("work against the Purpose.", "\n".join(cut), sid)
            self.assertIn("challengeable, not binding", "\n".join(cut), sid)
            found = cl.scan_text(rel, "\n".join(cut))[0]
            self.assertEqual(_codes(found), ["C001"], sid)
            self.assertIn("Purpose", found[0].message, sid)

    def test_345_purpose_is_case_sensitive_line_anchored_and_only_on_the_two_templates(self):
        body = FULL
        for sid in ("forge.spec-reviewer", "forge.d21-reviewer"):
            head = f"<!-- spawn-brief.v1 id={sid} -->\n```\n"
            self.assertEqual(_codes(cl.scan_text("a.md", head + body + "```\n")[0]), ["C001"], "absent")
            self.assertEqual(_codes(cl.scan_text("a.md", head + "purpose: p\n" + body + "```\n")[0]), ["C001"], "case")
            self.assertEqual(_codes(cl.scan_text("a.md", head + "The Purpose: p\n" + body + "```\n")[0]), ["C001"], "inline")
            self.assertEqual(_codes(cl.scan_text("a.md", head + "Purpose:   \n" + body + "```\n")[0]), ["C001"], "empty")
            self.assertEqual(cl.scan_text("a.md", head + "Purpose: p\n" + body + "```\n")[0], [], "present")
        self.assertEqual(cl.scan_text("a.md", "<!-- spawn-brief.v1 id=x.y -->\n```\n" + body + "```\n")[0], [])

    def test_345_missing_fields_keeps_its_outside_contract(self):
        """The extra field lives in scan_text: missing_fields answers for FIELDS alone."""
        self.assertEqual(cl.missing_fields(FULL), [])

    def test_344_every_forge_marker_is_pinned_to_the_file_that_holds_it(self):
        """#344 WP-4: forge's templates and its loop moved into step references. Each pin names
        the file whose text carries the marker -- found here by reading the files, not by
        repeating the map -- and none is left pointing at the entry file."""
        pins = {sid: path for sid, path in cl.SPAWN_BRIEFS.items() if sid.startswith("forge.")}
        pins.update({lid: path for lid, (path, _b, _o) in cl.LOOPS.items() if lid.startswith("forge.")})
        self.assertEqual(len(pins), 9)
        for ident, pinned in sorted(pins.items()):
            marker = ("<!-- contract:loop id=" + ident + " " if ident in cl.LOOPS
                      else "<!-- spawn-brief.v1 id=" + ident + " -->")
            holder = skill_corpus.file_of("forge", marker, root=_SKILLS)
            self.assertEqual("skills/forge/" + skill_corpus.rel("forge", holder, root=_SKILLS), pinned, ident)
            self.assertNotEqual(pinned, "skills/forge/SKILL.md", ident)

    def test_m5_the_script_brief_producers_are_a_documented_gap(self):
        text = (_META / "spawn-brief.md").read_text(encoding="utf-8")
        for producer in ("audit_spawn.py", "verification_arbiter_spawn.py", "visual_arbiter_spawn.py",
                         "design_drift_arbiter_spawn.py"):
            self.assertIn(producer, text)

    def test_m6_the_codex_challenger_uses_the_policy_severities(self):
        import effort_policy as ep
        # PRESENT: in the codex challenger's own brief (the codex-seats reference). ABSENT: nowhere
        # in forge, entry file or reference (#344 WP-4).
        self.assertIn("Severity (" + "/".join(ep.SEVERITIES) + ")",
                      skill_corpus.read("forge", "references/03-codex-seats.md", root=_SKILLS))
        self.assertNotIn("Severity (critical/moderate/minor)", skill_corpus.corpus("forge", root=_SKILLS))

    def test_m7_the_fixture_brief_n_a_line_matches_classify(self):
        import classify
        text = (FIX / "underspecified-bob-brief.md").read_text(encoding="utf-8")
        self.assertTrue(classify.N1_RE.search(text.split("\n---\n", 1)[1]))

    def test_c_bob_writes_nothing_when_it_asks(self):
        text = (_TREE / "agents" / "bob.md").read_text(encoding="utf-8")
        q = text[text.index("**Question before work (#313"):]
        q = q[:q.index("\n\n")]
        self.assertNotIn("Record `clarification_used: true`\nin `.bob-checkpoint.md`", q)
        self.assertIn("write\nnothing, not even `.bob-checkpoint.md`", q)
        self.assertNotIn("releases any claim", text)


# --------------------------------------------------------------------------- #
# D21 fix round 2 (#313): items 1 and 2 -- fences, duplicate headings, strict DW lines
# --------------------------------------------------------------------------- #
class FixRound2(unittest.TestCase):
    def test_1_a_hash_line_inside_a_fence_does_not_end_the_section(self):
        text = ("## Done when\n- DW-1: a\n```bash\n# a comment, not a heading\nrun it\n```\n"
                "- DW-2: b\n- DW-3 (integration): c\n")
        self.assertEqual(cl.design_dws(text), {"DW-1": False, "DW-2": False, "DW-3": True})

    def test_1_a_fenced_example_heading_is_not_the_section(self):
        text = ("# Design\n```markdown\n## Done when\n- DW-9: an example\n```\n\n## Done when\n- DW-1: real\n")
        self.assertEqual(cl.design_dws(text), {"DW-1": False})
        self.assertIsNone(cl.design_dws("```\n## Done when\n- DW-1: example only\n```\n"))

    def test_1_a_fenced_dw_is_not_a_definition(self):
        text = "## Done when\n- DW-1: a\n```\n- DW-2: quoted inside a fence\n```\n"
        self.assertEqual(cl.design_dws(text), {"DW-1": False})

    def test_2_more_than_one_done_when_heading_is_an_error(self):
        with self.assertRaises(cl.ContractError):
            cl.design_dws("### Done when (spike)\n- DW-1: a\n\n## Done when\n- DW-2: b\n")

    def test_2_integration_is_case_insensitive_and_checkboxes_parse(self):
        text = "## Done when\n- [ ] DW-1: a\n- [x] DW-2 (Integration): b\n- [X] **DW-3:** c\n"
        self.assertEqual(cl.design_dws(text), {"DW-1": False, "DW-2": True, "DW-3": False})

    def test_2_a_dw_line_that_does_not_parse_is_an_error(self):
        for bad in ("+ DW-2: plus bullet", "1) DW-2: paren", "- DW 2: space", "- `DW-2`: code", "- DW_2: underscore"):
            with self.assertRaises(cl.ContractError, msg=bad):
                cl.design_dws("## Done when\n- DW-1: a\n" + bad + "\n")

    def test_1_2_the_fence_case_no_longer_passes_check_plan_vacuously(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "design.md"
            d.write_text("## Done when\n- DW-1: a\n```\n# not a heading\n```\n- DW-2: b\n", encoding="utf-8")
            plan = json.loads((FIX / "plan.json").read_text(encoding="utf-8"))
            plan["work_packages"] = plan["work_packages"][:1]                       # covers DW-1 only
            p = Path(td) / "plan.json"
            p.write_text(json.dumps(plan), encoding="utf-8")
            out = _run("check-plan", str(p), "--design", str(d))
            self.assertEqual(out.returncode, 2, out.stdout)
            self.assertIn("uncovered DWs: DW-2", out.stdout)


# --------------------------------------------------------------------------- #
# #313 user-directed round 3: items 1 and 2 -- fences and fail-closed classification
# --------------------------------------------------------------------------- #
DW2 = "## Done when\n- DW-1: a\n{mid}\n- DW-2: b\n"


class Round3(unittest.TestCase):
    def ok(self, text, want):
        self.assertEqual(cl.design_dws(text), want, repr(text))

    def bad(self, text):
        with self.assertRaises(cl.ContractError, msg=repr(text)):
            cl.design_dws(text)

    # ---- item 1: fences ----
    def test_1_a_three_backtick_line_does_not_close_a_four_backtick_fence(self):
        self.ok("## Done when\n- DW-1: a\n````\n```\n- DW-9: example\n```\n````\n- DW-2: b\n",
                {"DW-1": False, "DW-2": False})

    def test_1_tilde_inside_backtick_and_short_tilde_inside_long_tilde(self):
        self.ok("## Done when\n- DW-1: a\n```\n~~~\n- DW-9: x\n~~~\n```\n- DW-2: b\n", {"DW-1": False, "DW-2": False})
        self.ok("## Done when\n- DW-1: a\n~~~~\n~~~\n- DW-9: x\n~~~\n~~~~\n- DW-2: b\n", {"DW-1": False, "DW-2": False})

    def test_1_an_inline_triple_backtick_line_is_not_a_fence(self):
        self.ok(DW2.format(mid="```x``` is inline code"), {"DW-1": False, "DW-2": False})

    def test_1_a_fence_indented_four_spaces_is_not_a_fence(self):
        self.ok(DW2.format(mid="    ```\n- DW-3: c"), {"DW-1": False, "DW-2": False, "DW-3": False})

    def test_1_form_feed_and_line_separator_do_not_split_lines(self):
        self.ok("## Done when\n- DW-1: a \x0c ## Out of scope\n- DW-2: b\n", {"DW-1": False, "DW-2": False})
        self.ok("## Done when\n- DW-1: a  ## Out of scope\n- DW-2: b\n", {"DW-1": False, "DW-2": False})
        self.ok("## Done when\r\n- DW-1: a\r\n- DW-2: b\r\n", {"DW-1": False, "DW-2": False})

    def test_1_an_unterminated_fence_before_or_in_the_section_is_an_error(self):
        self.bad("## Done when\n- DW-1: a\n```\n- DW-2: b\n")
        self.bad("```\nstray\n## Done when\n- DW-1: a\n")
        self.ok("## Done when\n- DW-1: a\n## Later\n```\nunterminated after the section\n", {"DW-1": False})

    # ---- item 2: fail closed ----
    def test_2_dash_like_and_spaced_ids_are_errors(self):
        for mid in ("- DW–2: en dash", "- DW‑2: nb hyphen", "- DW 2: space", "- DW_2: underscore",
                    "> DW-3: quoted", "• DW-3: bullet", "- [DW-3](x): link", "- ~~DW-3~~: struck",
                    "see DW–1 for the dash"):
            self.bad(DW2.format(mid=mid))

    def test_2_prose_referencing_a_defined_dw_is_fine(self):
        self.ok(DW2.format(mid="  Both DW-1 and its checks stay green."), {"DW-1": False, "DW-2": False})
        self.bad(DW2.format(mid="  This depends on DW-7."))                         # undefined reference

    def test_2_ids_normalise_and_duplicates_are_errors(self):
        self.ok("## Done when\n- DW-01: a\n- DW-2: b\n", {"DW-1": False, "DW-2": False})
        self.bad("## Done when\n- DW-01: a\n- DW-1: again\n")

    def test_2_heading_forms(self):
        want = {"DW-1": False}
        for text in ("   ## Done when\n- DW-1: a\n", "## **Done when**\n- DW-1: a\n",
                     "Done when\n---------\n- DW-1: a\n", "Done when\n=========\n- DW-1: a\n",
                     "\ufeff## Done when\n- DW-1: a\n"):
            self.ok(text, want)
        self.bad("Done when\n---\n- DW-1: a\n\n## Done when\n- DW-2: b\n")            # setext + ATX = two
        for text in ("####### Done when\n- DW-1: a\n", "**Done when**\n- DW-1: a\n", "<h2>Done when</h2>\n- DW-1: a\n"):
            self.bad(text)                                                             # heading-like, unclassifiable

    def test_2_the_real_designs_still_parse(self):
        doc = (_TREE / "docs" / "plans" / "2026-09-25-apply-the-contract-design.md").read_text(encoding="utf-8-sig")
        self.assertEqual(len(cl.design_dws(doc)), 8)
        self.assertEqual(len(cl.design_dws((FIX / "design.md").read_text(encoding="utf-8-sig"))), 3)


class Round3Tail(unittest.TestCase):
    """R3-N1: a wrapped DW bullet followed by `---` is not a setext heading."""

    def test_r3_n1_a_list_continuation_then_dashes_does_not_end_the_section(self):
        text = "## Done when\n- DW-1: a\n  continued text\n---\n- DW-2: b\n"
        self.assertEqual(cl.design_dws(text), {"DW-1": False, "DW-2": False})
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "design.md"
            d.write_text(text, encoding="utf-8")
            plan = json.loads((FIX / "plan.json").read_text(encoding="utf-8"))
            plan["work_packages"] = plan["work_packages"][:1]                     # covers DW-1 only
            p = Path(td) / "plan.json"
            p.write_text(json.dumps(plan), encoding="utf-8")
            out = _run("check-plan", str(p), "--design", str(d))
            self.assertEqual(out.returncode, 2, out.stdout)
            self.assertIn("uncovered DWs: DW-2", out.stdout)

    def test_r3_n1_an_ambiguous_underline_in_the_section_is_an_error(self):
        for para in ("  indented text", "> quoted", "| a | b |"):
            with self.assertRaises(cl.ContractError, msg=para):
                cl.design_dws(f"## Done when\n- DW-1: a\n\n{para}\n---\n- DW-2: b\n")

    def test_r3_n1_a_column_zero_paragraph_is_still_a_setext_heading(self):
        text = "## Done when\n- DW-1: a\n\nOut of scope\n---\n- DW-2: not in the section\n"
        self.assertEqual(cl.design_dws(text), {"DW-1": False})
