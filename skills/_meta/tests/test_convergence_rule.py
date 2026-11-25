#!/usr/bin/env python3
"""test_convergence_rule.py -- #352: the convergence rule CONV-1, defined once and cited by id.

Design docs/plans/2026-10-12-352-creative-studio-design.md, "The convergence rule" (DW-5):
  the rule text    skills/_meta/convergence-rule.md carries three numbered applicability questions,
                   the eligible-winner clause, named borrows and an exclusion table in which every
                   row says what to do instead
  TS-CNV-01        a citing file without the id fails
  TS-CNV-02        a second definition of the rule in another file fails
  the portfolio    adversarial-team-brainstorm keeps its merge step, renamed "Merge near-duplicates"

What counts as a DEFINITION (the stated marker): a line that is exactly the marker comment
`<!-- convergence-rule.v1 id=<ID> -->`, or a markdown heading whose text starts with the id.
Anything else that names the id is a citation.

The list of citing files is data: fixtures/convergence/citing-files-sample.json. A later package
that adds a citing place appends its path there.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

_META = Path(__file__).resolve().parent.parent
_TREE = _META.parent.parent
FIX = Path(__file__).resolve().parent / "fixtures" / "convergence"

#: Roots searched for a second definition, relative to the tree.
SCAN_ROOTS = ("skills", "agents", "commands", "workflows", "global")
SCAN_SUFFIXES = (".md", ".js", ".mjs", ".py", ".json", ".yaml", ".yml", ".txt")
RULE_BASENAME = "convergence-rule.md"


def load_citing(path: Path = FIX / "citing-files-sample.json") -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def marker_line(rule_id: str) -> str:
    return "<!-- convergence-rule.v1 id=" + rule_id + " -->"


def is_definition_line(line: str, rule_id: str) -> bool:
    stripped = line.strip()
    if stripped == marker_line(rule_id):
        return True
    return re.match(r"^#{1,6}\s+" + re.escape(rule_id) + r"\b", line) is not None


def definition_files(root: Path, rule_id: str) -> list[str]:
    """Every file under the scan roots that DEFINES the rule, as tree-relative posix paths."""
    found = []
    for name in SCAN_ROOTS:
        base = root / name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in SCAN_SUFFIXES or not path.is_file():
                continue
            if "__pycache__" in path.parts or "node_modules" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if rule_id not in text:
                continue
            if any(is_definition_line(line, rule_id) for line in text.splitlines()):
                found.append(path.relative_to(root).as_posix())
    return found


def check_tree(root: Path, spec: dict) -> list[str]:
    """The pinned-text check. Returns problems; an empty list is a pass."""
    rule_id = spec["rule_id"]
    definition = spec["definition_file"]
    problems = []
    for rel in spec["citing_files"]:
        path = root / rel
        if not path.is_file():
            problems.append(f"citing file missing: {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        if rule_id not in text:
            problems.append(f"citing file does not name {rule_id}: {rel}")
        if RULE_BASENAME not in text:
            problems.append(f"citing file does not say where {rule_id} is defined ({RULE_BASENAME}): {rel}")
    defined_in = definition_files(root, rule_id)
    if definition not in defined_in:
        problems.append(f"{rule_id} is not defined in {definition}")
    for rel in defined_in:
        if rel != definition:
            problems.append(f"second definition of {rule_id}: {rel}")
    return problems


def section(text: str, heading: str) -> str:
    """The body of a `## <heading>` section, up to the next `## ` heading."""
    lines = text.splitlines()
    try:
        start = lines.index("## " + heading)
    except ValueError:
        return ""
    body = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def numbered_questions(body: str) -> list[tuple[int, str]]:
    out = []
    for line in body.splitlines():
        m = re.match(r"^(\d+)\.\s+(.*\?)\s*$", line)
        if m:
            out.append((int(m.group(1)), m.group(2)))
    return out


def table_rows(body: str) -> tuple[list[str], list[list[str]]]:
    """(header cells, data rows) of the first markdown table in the body."""
    rows = [ln for ln in body.splitlines() if ln.lstrip().startswith("|")]
    cells = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in rows]
    if len(cells) < 2:
        return [], []
    return cells[0], [r for r in cells[2:]]


def rule_text_problems(text: str, rule_id: str) -> list[str]:
    """Shape of a rule text: questions, the eligible winner, named borrows, the exclusion table."""
    problems = []
    lines = text.splitlines()
    if sum(1 for ln in lines if ln.strip() == marker_line(rule_id)) != 1:
        problems.append("the definition marker must appear exactly once")
    numbers = [n for n, _ in numbered_questions(section(text, "Applicability"))]
    if numbers != [1, 2, 3]:
        problems.append(f"Applicability must hold exactly three numbered questions, found {numbers}")
    winner = " ".join(section(text, "The eligible winner").split())
    for phrase in ("eligible candidate", "passes the blocking checks", "selected for repair", "re-checked"):
        if phrase not in winner:
            problems.append(f"the eligible-winner clause lacks: {phrase}")
    borrows = " ".join(section(text, "Borrowed parts").split())
    for phrase in ("named part", "re-made by the winner"):
        if phrase not in borrows:
            problems.append(f"the borrow clause lacks: {phrase}")
    header, rows = table_rows(section(text, "Exclusions"))
    if [h.lower() for h in header] != ["when", "instead"]:
        problems.append(f"the exclusion table needs the columns When | Instead, found {header}")
    if not rows:
        problems.append("the exclusion table has no rows")
    for row in rows:
        if len(row) != 2 or not row[0] or not row[1]:
            problems.append(f"exclusion row without an instead cell: {row}")
    return problems


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_tree(root: Path, spec: dict) -> None:
    """A minimal passing tree: the rule (made from the shape fixture) and the citing files."""
    rule_id = spec["rule_id"]
    sample = (FIX / "rule-text-sample.md").read_text(encoding="utf-8")
    _write(root, spec["definition_file"], sample.replace("SAMPLE-0", rule_id))
    for rel in spec["citing_files"]:
        _write(root, rel, f"Merge rival outputs under {rule_id} (`skills/_meta/{RULE_BASENAME}`).\n")


class LiveTreeTests(unittest.TestCase):
    """The repository as it stands."""

    @classmethod
    def setUpClass(cls):
        cls.spec = load_citing()
        cls.rule_id = cls.spec["rule_id"]
        cls.rule = (_TREE / cls.spec["definition_file"]).read_text(encoding="utf-8")

    def test_live_tree_every_citing_file_names_the_id_and_one_file_defines_it(self):
        self.assertEqual(check_tree(_TREE, self.spec), [])

    def test_live_fixture_lists_the_four_design_citing_places(self):
        self.assertEqual(self.rule_id, "CONV-1")
        self.assertEqual(self.spec["definition_file"], "skills/_meta/convergence-rule.md")
        for rel in (
            "skills/forge/references/04-agy-and-converge.md",
            "workflows/design-tournament.js",
            "skills/avengers/SKILL.md",
            "skills/adversarial-team-brainstorm/references/arbiter-synthesis.md",
        ):
            self.assertIn(rel, self.spec["citing_files"])

    def test_live_rule_text_has_the_required_shape(self):
        self.assertEqual(rule_text_problems(self.rule, self.rule_id), [])

    def test_live_rule_asks_the_three_design_questions(self):
        questions = " ".join(q.lower() for _, q in numbered_questions(section(self.rule, "Applicability")))
        for phrase in ("same slot", "exactly one output", "clear the bar"):
            self.assertIn(phrase, questions)
        self.assertIn("three", section(self.rule, "Applicability").lower())

    def test_live_rule_states_one_winner_named_borrows_never_a_blend(self):
        flat = " ".join(self.rule.split()).lower()
        for phrase in ("one winner", "named borrowed parts", "never a blend"):
            self.assertIn(phrase, flat)

    def test_live_exclusion_table_covers_the_eight_design_cases(self):
        _, rows = table_rows(section(self.rule, "Exclusions"))
        self.assertEqual(len(rows), 8)
        table = " ".join(" ".join(r) for r in rows).lower()
        for phrase in (
            "complementary layers or slices", "record the interface",
            "portfolio", "near-duplicates",
            "review findings", "union",
            "research synthesis", "conflicts listed",
            "dispute", "evidence or a test",
            "taste or business", "the user",
            "no candidate clears the bar", "`no_award`",
            "core mechanism", "new candidate",
        ):
            self.assertIn(phrase, table)

    def test_live_citing_files_do_not_restate_the_rule(self):
        # A citation names the id; the three questions live in the rule file only.
        for rel in self.spec["citing_files"]:
            text = (_TREE / rel).read_text(encoding="utf-8").lower()
            self.assertNotIn("do the candidates fill the same slot", text, rel)

    def test_live_workflow_names_the_id_in_a_comment_and_in_the_synthesis_instruction(self):
        lines = (_TREE / "workflows" / "design-tournament.js").read_text(encoding="utf-8").splitlines()
        hits = [ln.strip() for ln in lines if self.rule_id in ln]
        self.assertTrue(any(ln.startswith("//") for ln in hits), hits)
        self.assertTrue(any(ln.startswith('"') for ln in hits), hits)

    def test_live_portfolio_step_is_renamed_and_named_an_exclusion(self):
        text = (_TREE / "skills/adversarial-team-brainstorm/references/arbiter-synthesis.md").read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertIn("## Step 2: Merge near-duplicates", lines)
        headings = [ln for ln in lines if re.match(r"^#{1,6}\s", ln)]
        self.assertEqual([h for h in headings if "hybridization" in h.lower()], [])
        step = section(text, "Step 2: Merge near-duplicates")
        self.assertIn(self.rule_id, step)
        self.assertIn("exclusion", step.lower())
        # The portfolio path keeps its behaviour: the merge rules are still there.
        self.assertIn("overlaps >60%", step)
        self.assertIn('source_team: "hybrid(A+B)"', step)

    def test_live_brainstorm_skill_names_the_new_step(self):
        text = (_TREE / "skills/adversarial-team-brainstorm/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("merge near-duplicates", text.lower())
        self.assertNotIn("hybridization rules", text)


class ShapeFixtureTests(unittest.TestCase):
    def test_fixture_rule_text_sample_has_the_shape_and_defines_nothing_real(self):
        sample = (FIX / "rule-text-sample.md").read_text(encoding="utf-8")
        self.assertEqual(rule_text_problems(sample, "SAMPLE-0"), [])
        self.assertNotIn(load_citing()["rule_id"], sample)

    def test_fixture_manifest_hashes_match_the_files(self):
        import hashlib
        manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
        component = manifest["components"]["convergence-rule"]
        entries = [f for group in ("inputs", "outputs") for v in component[group].values() for f in v["fixtures"]]
        self.assertEqual(len(entries), 2)
        for entry in entries:
            digest = hashlib.sha256((FIX / Path(entry["path"]).name).read_bytes()).hexdigest()
            self.assertEqual(entry["hash"], "sha256:" + digest, entry["path"])


class SyntheticTreeTests(unittest.TestCase):
    """TS-CNV-01 and TS-CNV-02 on a throwaway tree."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.spec = load_citing()
        build_tree(self.root, self.spec)

    def tearDown(self):
        self._tmp.cleanup()

    def test_synthetic_clean_tree_passes(self):
        self.assertEqual(check_tree(self.root, self.spec), [])

    def test_ts_cnv_01_citing_file_without_the_id_fails(self):
        for rel in self.spec["citing_files"]:
            with self.subTest(rel=rel):
                original = (self.root / rel).read_text(encoding="utf-8")
                _write(self.root, rel, "Merge rival outputs: pick a winner (`skills/_meta/convergence-rule.md`).\n")
                problems = check_tree(self.root, self.spec)
                self.assertEqual(problems, [f"citing file does not name CONV-1: {rel}"])
                _write(self.root, rel, original)

    def test_ts_cnv_01_missing_citing_file_fails(self):
        rel = self.spec["citing_files"][0]
        (self.root / rel).unlink()
        self.assertEqual(check_tree(self.root, self.spec), [f"citing file missing: {rel}"])

    def test_ts_cnv_02_second_definition_by_marker_fails(self):
        rule = (self.root / self.spec["definition_file"]).read_text(encoding="utf-8")
        _write(self.root, "skills/other-skill/references/merge.md", rule)
        self.assertEqual(
            check_tree(self.root, self.spec),
            ["second definition of CONV-1: skills/other-skill/references/merge.md"],
        )

    def test_ts_cnv_02_second_definition_by_heading_in_a_citing_file_fails(self):
        rel = self.spec["citing_files"][0]
        _write(self.root, rel, "### CONV-1: pick a winner\n\nSee `skills/_meta/convergence-rule.md`.\n")
        self.assertEqual(check_tree(self.root, self.spec), [f"second definition of CONV-1: {rel}"])

    def test_ts_cnv_02_definition_moved_out_of_the_rule_file_fails(self):
        _write(self.root, self.spec["definition_file"], "The rule moved.\n")
        self.assertEqual(
            check_tree(self.root, self.spec),
            ["CONV-1 is not defined in skills/_meta/convergence-rule.md"],
        )

    def test_synthetic_a_citation_is_not_a_definition(self):
        _write(self.root, "skills/other-skill/SKILL.md",
               "Heading text may mention it later.\n\n## Merging (see CONV-1)\n\nUse CONV-1.\n")
        _write(self.root, "workflows/other.js", '// the marker quoted, not on its own line: "<!-- convergence-rule.v1 id=CONV-1 -->"\n')
        self.assertEqual(check_tree(self.root, self.spec), [])

    def test_synthetic_exclusion_row_without_an_instead_cell_fails(self):
        sample = (FIX / "rule-text-sample.md").read_text(encoding="utf-8")
        broken = sample.replace("| a sample of what to do instead |", "| |")
        problems = rule_text_problems(broken, "SAMPLE-0")
        self.assertEqual(len(problems), 1)
        self.assertIn("without an instead cell", problems[0])

    def test_synthetic_a_fourth_question_fails(self):
        sample = (FIX / "rule-text-sample.md").read_text(encoding="utf-8")
        broken = sample.replace("3. Does at least", "3. Is it Tuesday?\n4. Does at least")
        problems = rule_text_problems(broken, "SAMPLE-0")
        self.assertEqual(problems, ["Applicability must hold exactly three numbered questions, found [1, 2, 3, 4]"])

    def test_synthetic_missing_eligible_winner_clause_fails(self):
        sample = (FIX / "rule-text-sample.md").read_text(encoding="utf-8")
        broken = sample.replace("or one selected for repair and\nre-checked before the award is confirmed", "or any other")
        problems = rule_text_problems(broken, "SAMPLE-0")
        self.assertEqual(
            problems,
            ["the eligible-winner clause lacks: selected for repair", "the eligible-winner clause lacks: re-checked"],
        )


if __name__ == "__main__":
    unittest.main()
