#!/usr/bin/env python3
"""test_design_critique.py -- #352: the critic skill for rendered work.

Design docs/plans/2026-10-12-352-creative-studio-design.md, step 5 of "Shape of a run" (DW-4):
  TS-CRT-01   no line of the critic references equals a refuse-list row of either visual doctrine
  TS-CRT-02   the skill text names CONV-1 and holds no second definition of it
  and: the neutral floor is a table a program can read, with a dated primary source; the skill
  description leads with its subject.

TS-CRT-01 has two arms. The first builds doctrine files in a temp directory and always runs.
The LIVE arm reads the refuse list of every skills/web-craft-*/references/doctrine.md. It is
skipped only while no visual doctrine exists; once skills/web-craft-restrained is there it FAILS
when fewer than two doctrines, or an empty refuse list, are found.

WHAT A REFUSE LIST IS (the contract a doctrine file keeps): the section of doctrine.md whose
heading starts with "Refuse", up to the next heading of the same or a higher level. Its rows
are the list items (`- `, `* `, `1. `) and, in a table, the first cell of each data row.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SKILL = Path(__file__).resolve().parent.parent
_TREE = _SKILL.parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"

RULE_ID = "CONV-1"
RULE_FILE = "skills/_meta/convergence-rule.md"
VIEWPORTS = {390, 768, 1280}
#: Rows the design names; the capture must report each.
REQUIRED_ROWS = {"contrast-text", "contrast-large-text", "body-size", "overflow-x", "motion-reduced",
                 "page-weight", "line-length"}
#: A critic reference names no house and no source of one: the critic is blind to both.
HOUSE_WORDS = ("web-craft", "restrained", "expressive", "impeccable", "magicui")
#: A refuse row this short is matched only as a whole line, never as part of one.
MIN_WORDS_FOR_CONTAINMENT = 4


def critic_files(tree: Path = _TREE) -> list[Path]:
    """The skill text and reference files as shipped: the paths the fixture lists."""
    names = (FIX / "critic-refs-sample.txt").read_text(encoding="utf-8").split()
    return [tree / name for name in names]


def normalise(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def refuse_rows(doctrine_text: str) -> list[str]:
    """The rows of a doctrine's refuse list, normalised. See the module docstring for the format."""
    rows, level, seen_table_rule = [], 0, False
    for line in doctrine_text.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            if level and len(heading.group(1)) <= level:
                level = 0
            if not level and heading.group(2).strip().lower().startswith("refuse"):
                level, seen_table_rule = len(heading.group(1)), False
            continue
        if not level:
            continue
        item = re.match(r"^\s*(?:[-*+]|\d+\.)\s+(.*)$", line)
        if item:
            rows.append(normalise(item.group(1)))
        elif line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                seen_table_rule = True
            elif seen_table_rule:
                rows.append(normalise(cells[0]))
    return [r for r in rows if r]


def refuse_problems(critic: list[Path], doctrines: list[Path]) -> list[str]:
    """Every critic-reference line that is a refuse-list row of a doctrine. Empty is a pass."""
    problems = []
    for doctrine in doctrines:
        rows = refuse_rows(doctrine.read_text(encoding="utf-8"))
        for path in critic:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for cell in [line] + line.split("|"):
                    got = normalise(cell)
                    for row in rows:
                        whole = got == row
                        inside = len(row.split()) >= MIN_WORDS_FOR_CONTAINMENT and row in got
                        if got and (whole or inside):
                            problems.append(f"{path.name}:{number} holds a refuse-list row of {doctrine.parent.parent.name}")
    return sorted(set(problems))


def is_definition_line(line: str, rule_id: str = RULE_ID) -> bool:
    """The marker WP-1 fixed: the marker comment, or a heading whose text starts with the id."""
    if line.strip() == "<!-- convergence-rule.v1 id=" + rule_id + " -->":
        return True
    return re.match(r"^#{1,6}\s+" + re.escape(rule_id) + r"\b", line) is not None


def floor_table(text: str) -> list[dict]:
    """The rows between the floor-table markers of neutral-floor.md, as dicts keyed by header."""
    body = text.split("<!-- floor-table:start -->", 1)[1].split("<!-- floor-table:end -->", 1)[0]
    lines = [ln for ln in body.splitlines() if ln.strip().startswith("|")]
    cells = [[c.strip().strip("`") for c in ln.strip().strip("|").split("|")] for ln in lines]
    return [dict(zip(cells[0], row)) for row in cells[2:]]


def viewports(cell: str) -> set[int]:
    return set() if cell == "none" else {int(part) for part in cell.split(",")}


def frontmatter(text: str) -> dict:
    block = text.split("---", 2)[1]
    out = {}
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if sep and not key.startswith(" "):
            out[key.strip()] = value.strip().strip('"')
    return out


DOCTRINE_A = """# House A

## Axis table

| Axis | Value |
|---|---|
| motion | one entrance per section |

## Refuse list

- A gradient headline over a centred hero with three equal cards
- Decoration that answers no line of the brief
- Lorem ipsum

## References

- This row is outside the refuse list and may appear anywhere
"""

DOCTRINE_B = """# House B

### Refused patterns

| Pattern | Why |
|---|---|
| A page with no stated visual idea | timid |
| Motion that ignores a reduced-motion request | it shuts people out |

### Process

1. Fill the direction contract first
"""


class RefuseListRows(unittest.TestCase):
    def test_rows_come_from_the_refuse_section_only(self):
        self.assertEqual(refuse_rows(DOCTRINE_A), [
            "a gradient headline over a centred hero with three equal cards",
            "decoration that answers no line of the brief", "lorem ipsum"])

    def test_table_rows_give_their_first_cell(self):
        self.assertEqual(refuse_rows(DOCTRINE_B), [
            "a page with no stated visual idea", "motion that ignores a reduced motion request"])

    def test_a_doctrine_without_a_refuse_section_has_no_rows(self):
        self.assertEqual(refuse_rows("# House\n\n## Axis table\n\n- not a refusal\n"), [])


class CriticReferencesHoldNoRefuseRow(unittest.TestCase):
    def build(self, tmp: str) -> tuple[list[Path], list[Path]]:
        root = Path(tmp)
        doctrines = []
        for name, text in (("web-craft-a", DOCTRINE_A), ("web-craft-b", DOCTRINE_B)):
            path = root / "skills" / name / "references" / "doctrine.md"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")
            doctrines.append(path)
        critic = []
        for source in critic_files():
            copy = root / "critic" / source.name
            copy.parent.mkdir(exist_ok=True)
            copy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            critic.append(copy)
        return critic, doctrines

    def test_ts_crt_01_the_shipped_references_pass_against_test_built_refuse_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            critic, doctrines = self.build(tmp)
            self.assertEqual(len(critic), 4)
            self.assertEqual(refuse_problems(critic, doctrines), [])

    def test_ts_crt_01_a_reference_line_equal_to_a_refuse_row_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            critic, doctrines = self.build(tmp)
            floor = next(p for p in critic if p.name == "neutral-floor.md")
            floor.write_text(floor.read_text(encoding="utf-8") + "\n- Lorem ipsum\n", encoding="utf-8")
            self.assertEqual(refuse_problems(critic, doctrines),
                             [f"neutral-floor.md:{len(floor.read_text(encoding='utf-8').splitlines())} "
                              "holds a refuse-list row of web-craft-a"])

    def test_ts_crt_01_a_refuse_row_inside_a_table_cell_or_a_sentence_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            critic, doctrines = self.build(tmp)
            rubric = next(p for p in critic if p.name == "rubric.md")
            rubric.write_text(rubric.read_text(encoding="utf-8")
                              + "\n| `no-idea` | A page with no stated visual idea | fail |\n"
                              + "\nMark down **motion that ignores a reduced-motion request** every time.\n",
                              encoding="utf-8")
            problems = refuse_problems(critic, doctrines)
            self.assertEqual(len(problems), 2)
            self.assertTrue(all("web-craft-b" in p for p in problems))

    def test_ts_crt_01_a_short_row_is_not_matched_inside_a_longer_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            critic, doctrines = self.build(tmp)
            brief = next(p for p in critic if p.name == "critic-brief.md")
            brief.write_text(brief.read_text(encoding="utf-8") + "\nPlaceholder text such as lorem ipsum is content.\n",
                             encoding="utf-8")
            self.assertEqual(refuse_problems(critic, doctrines), [])

    def test_ts_crt_01_live_arm_against_the_real_visual_doctrines(self):
        doctrines = sorted((_TREE / "skills").glob("web-craft-*/references/doctrine.md"))
        if not (_TREE / "skills" / "web-craft-restrained").exists():
            self.skipTest("no visual doctrine exists yet; this arm runs once skills/web-craft-restrained is added")
        self.assertGreaterEqual(len(doctrines), 2, "fewer than two visual doctrines found")
        for doctrine in doctrines:
            self.assertTrue(refuse_rows(doctrine.read_text(encoding="utf-8")), f"empty refuse list: {doctrine}")
        self.assertEqual(refuse_problems(critic_files(), doctrines), [])

    def test_the_references_name_no_house(self):
        for path in critic_files():
            text = path.read_text(encoding="utf-8").lower()
            for word in HOUSE_WORDS:
                self.assertNotIn(word, text, f"{path.name} names {word}")


class CitesTheConvergenceRule(unittest.TestCase):
    def test_ts_crt_02_the_skill_names_the_id_and_where_it_is_defined(self):
        for name in ("SKILL.md", "references/critic-brief.md"):
            text = (_SKILL / name).read_text(encoding="utf-8")
            self.assertIn(RULE_ID, text, name)
            self.assertIn(RULE_FILE, text, name)

    def test_ts_crt_02_no_file_of_the_skill_defines_the_rule(self):
        for path in sorted(_SKILL.rglob("*")):
            if path.suffix not in (".md", ".txt", ".json") or not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                self.assertFalse(is_definition_line(line), f"{path.name} defines {RULE_ID}")

    def test_ts_crt_02_a_second_definition_would_be_seen(self):
        self.assertTrue(is_definition_line("## CONV-1 again"))
        self.assertTrue(is_definition_line("<!-- convergence-rule.v1 id=CONV-1 -->"))
        self.assertFalse(is_definition_line("The rule for that is `CONV-1`."))

    def test_the_skill_does_not_restate_the_applicability_questions(self):
        rule = (_TREE / RULE_FILE).read_text(encoding="utf-8")
        questions = re.findall(r"^\d+\.\s+(.*\?)\s*$", rule, flags=re.M)
        self.assertEqual(len(questions), 3)
        for path in critic_files():
            got = normalise(path.read_text(encoding="utf-8"))
            for question in questions:
                self.assertNotIn(normalise(question), got, path.name)

    def test_the_skill_is_listed_as_a_citing_place_of_the_rule(self):
        listed = (_TREE / "skills/_meta/tests/fixtures/convergence/citing-files-sample.json").read_text(encoding="utf-8")
        self.assertIn('"skills/design-critique/SKILL.md"', listed)


class NeutralFloor(unittest.TestCase):
    def setUp(self):
        self.text = (_SKILL / "references" / "neutral-floor.md").read_text(encoding="utf-8")
        self.rows = floor_table(self.text)

    def test_the_floor_table_has_the_rows_the_design_names(self):
        ids = [row["Row id"] for row in self.rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLessEqual(REQUIRED_ROWS, set(ids))
        for row_id in ids:
            self.assertRegex(row_id, r"^[a-z][a-z0-9-]{0,39}$")

    def test_every_row_has_a_number_a_comparison_and_a_scope(self):
        for row in self.rows:
            float(row["Threshold"])
            self.assertIn(row["Pass when"], (">=", "<="), row["Row id"])
            for column in ("Measures", "Element scope", "Unit"):
                self.assertTrue(row[column], f"{row['Row id']}: {column}")

    def test_every_row_is_blocking_or_advisory_at_each_viewport_and_never_both(self):
        for row in self.rows:
            blocking, advisory = viewports(row["Blocking at"]), viewports(row["Advisory at"])
            self.assertEqual(blocking | advisory, VIEWPORTS, row["Row id"])
            self.assertEqual(blocking & advisory, set(), row["Row id"])

    def test_which_rows_block(self):
        by_id = {row["Row id"]: row for row in self.rows}
        for row_id in REQUIRED_ROWS - {"line-length"}:
            self.assertEqual(viewports(by_id[row_id]["Blocking at"]), VIEWPORTS, row_id)
        self.assertEqual(viewports(by_id["line-length"]["Advisory at"]), {390})

    def test_the_contrast_thresholds_are_the_wcag_ratios(self):
        by_id = {row["Row id"]: row for row in self.rows}
        self.assertEqual(float(by_id["contrast-text"]["Threshold"]), 4.5)
        self.assertEqual(float(by_id["contrast-large-text"]["Threshold"]), 3.0)

    def test_the_floor_cites_its_primary_source_with_a_freshness_anchor(self):
        self.assertIn("https://www.w3.org/TR/WCAG22/#contrast-minimum", self.text)
        self.assertIn("1.4.3", self.text)
        anchor = re.search(r"\*\*Freshness anchor\.\*\*\s+Checked (\d{4}-\d{2}-\d{2})", self.text)
        self.assertIsNotNone(anchor)
        self.assertIn("Re-check", self.text)

    def test_the_verdict_sample_uses_floor_row_ids_of_this_table(self):
        sample = _TREE / "skills/creative-studio/tests/fixtures/verdict-draft-sample.json"
        if not sample.is_file():
            self.skipTest("the creative-studio sample is not in this tree")
        used = set(re.findall(r'"id": "([a-z0-9-]+)", "variant"', sample.read_text(encoding="utf-8")))
        self.assertTrue(used)
        self.assertLessEqual(used, {row["Row id"] for row in self.rows})


class SkillEntryFile(unittest.TestCase):
    def setUp(self):
        self.text = (_SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.meta = frontmatter(self.text)

    def test_the_description_leads_with_the_subject(self):
        description = self.meta["description"]
        self.assertTrue(description.startswith("Design critique"))
        self.assertNotRegex(description.lower(), r"^use when")
        self.assertIn("Use when", description)
        self.assertLessEqual(len(description), 250)
        self.assertNotRegex(description, r"\b(I|you|You)\b")

    def test_the_name_is_the_directory_and_no_family_is_declared(self):
        self.assertEqual(self.meta["name"], _SKILL.name)
        self.assertNotIn("family", self.text.split("---", 2)[1])

    def test_the_entry_file_names_each_reference_by_its_path(self):
        for reference in sorted((_SKILL / "references").glob("*.md")):
            self.assertIn("references/" + reference.name, self.text)

    def test_the_fixture_lists_exactly_the_shipped_text(self):
        shipped = sorted(p.relative_to(_TREE).as_posix() for p in [_SKILL / "SKILL.md"]
                         + list((_SKILL / "references").glob("*.md")))
        self.assertEqual(sorted(p.relative_to(_TREE).as_posix() for p in critic_files()), shipped)

    def test_the_critic_brief_holds_the_seat_rules(self):
        brief = (_SKILL / "references" / "critic-brief.md").read_text(encoding="utf-8")
        for phrase in ("variant-1", "order this brief gives", "could_not_judge", "open_to_user",
                       "Do not merge the variants", "selected_for_repair", "Do not compare tells across variants"):
            self.assertIn(phrase, brief)

    def test_360_l5_the_critic_brief_says_which_outcome_the_checker_takes(self):
        # The first live run: both critics named a winner "for repair" when every variant failed a blocking
        # row. The checker takes only no_award there; the brief said "and none is worth repairing".
        brief = " ".join((_SKILL / "references" / "critic-brief.md").read_text(encoding="utf-8").split())
        for phrase in ("**Every variant fails a blocking row.** The outcome is `no_award` with `all_fail_blocking`",
                       "a winner named here, marked for repair or not, is refused (`no_award_required`)",
                       "The checker answers with `repair_no_recapture`",
                       "**`selected_for_repair` is true in no other case**, and never with `no_award`",
                       "**`repair` stays null until the brief shows a re-capture of your winner.**",
                       "Do not name any winner when every variant fails a blocking row"):
            self.assertIn(phrase, brief)
        self.assertNotIn("none is worth repairing", brief)

    def test_the_skill_passes_the_skill_audit_and_the_frontmatter_lint(self):
        audit = _TREE / "skills" / "_meta" / "skill_audit.py"
        lint = _TREE / "skills" / "_meta" / "frontmatter_lint.py"
        if not (audit.is_file() and lint.is_file()):
            self.skipTest("the audit tools are not in this tree")
        skill = str(_SKILL / "SKILL.md")
        for command in ([str(audit), "check", "--repo", str(_TREE), "--tree", skill], [str(lint), "check", skill]):
            done = subprocess.run([sys.executable] + command, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=120)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
