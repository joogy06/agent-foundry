#!/usr/bin/env python3
"""test_doctrine_distance.py -- #352: the two rival visual houses and the reader of their axis tables.

Design docs/plans/2026-10-12-352-creative-studio-design.md, "Families" (DW-2, DW-6):
  TS-DOC-01   two doctrines differing on fewer than three axes fail the distance test
  TS-DOC-02   the attribution file names a licence, a commit and an intake verdict id
  and: the two real doctrines fill the same named axes and differ on at least three; the two
  skills declare different families with no shared member, and both families resolve through
  skill_resolve against this tree; each doctrine has a refuse list that holds no neutral-floor
  row; every reference file that carries a date carries a freshness anchor; the catalogue the
  expressive house names is a reference only.

TS-DOC-01 and the negative arms of TS-DOC-02 build their files at test time. The arms named
"real" read skills/web-craft-restrained and skills/web-craft-expressive as shipped.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SKILL = Path(__file__).resolve().parent.parent
_TREE = _SKILL.parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(_SKILL / "scripts"))

import studio_axes as sa  # noqa: E402

SOURCE_COMMIT = "c63b8dd7dd5a5f3c32eaabe1af76d0694f863ed2"
HOUSES = {"web-craft-restrained": "visual-craft-restrained", "web-craft-expressive": "visual-craft-expressive"}
#: Words of the neutral floor and of the ground both houses share. No refuse row holds one.
SHARED_GROUND = ("contrast", "body size", "font size", "overflow", "reduced motion", "page weight",
                 "line length", "wcag", "accessib", "usab", "keyboard", "screen reader", "focus")
INTAKE_ID = re.compile(r"\bq\d{8}T\d{6}Z-[0-9a-f]{8}\b")
ANCHOR = re.compile(r"\*\*Freshness anchor\.\*\*\s+Checked (\d{4}-\d{2}-\d{2})")
DATED = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")


def doctrine_path(skill: str) -> Path:
    return _TREE / "skills" / skill / "references" / "doctrine.md"


def real_table(skill: str) -> dict:
    return sa.axis_table(doctrine_path(skill).read_text(encoding="utf-8"))


def frontmatter(text: str) -> dict:
    block = text.split("---", 2)[1]
    meta = {}
    for line in block.splitlines():
        found = re.match(r"^([a-z_-]+):\s*(.*)$", line)
        if found:
            meta[found.group(1)] = found.group(2).strip().strip('"')
    return meta


def build_doctrine(values: dict[str, str], also: dict[str, str] | None = None) -> str:
    """A doctrine file with an axis table holding `values`, written the way a real one is."""
    also = also or {}
    rows = "\n".join(f"| `{axis}` | `{value}` | {also.get(axis, 'none')} | prose that is not read |"
                     for axis, value in values.items())
    return ("# A house\n\n## The position\n\n| Axis | Value |\n|---|---|\n| `type` | `outside-the-section` |\n\n"
            "## Axis table\n\nIntro line.\n\n| Axis | Value | Also allowed | In practice |\n|---|---|---|---|\n"
            + rows + "\n\n## Refuse list\n\n| Refused | Why |\n|---|---|\n| A first refusal | because |\n"
            "- A second refusal\n\n## Later\n\n- not a refusal\n")


QUIET = {axis: values[0] for axis, values in sa.VISUAL_AXES}
LOUD = {axis: values[-1] for axis, values in sa.VISUAL_AXES}


def moved(base: dict[str, str], **changes: str) -> dict[str, str]:
    return {**base, **changes}


def attribution_problems(text: str) -> list[str]:
    """What an attribution file lacks. Empty is a pass (TS-DOC-02)."""
    problems = []
    if not ("Apache License" in text and "Version 2.0, January 2004" in text
            and "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in text
            and "END OF TERMS AND CONDITIONS" in text and "9. Accepting Warranty or Additional Liability" in text):
        problems.append("licence-text")
    if not re.search(r"\b[0-9a-f]{40}\b", text):
        problems.append("commit")
    if not INTAKE_ID.search(text):
        problems.append("intake-verdict-id")
    if not re.search(r"\|\s*Verdict\s*\|\s*\**block\**\s*\|", text):
        problems.append("verdict")
    if not re.search(r"(?im)^##\s+What was adapted", text) or "changed" not in text.lower():
        problems.append("changes")
    if "https://www.w3.org/TR/WCAG22/" not in text or not re.search(r"(?im)^##\s+Primary sources", text):
        problems.append("primary-sources")
    return problems


def freshness_problems(text: str) -> list[str]:
    """A reference that carries a date carries a freshness anchor with a date and a re-check line."""
    if not DATED.search(text):
        return []
    problems = []
    if not ANCHOR.search(text):
        problems.append("no-anchor")
    if "Re-check" not in text:
        problems.append("no-re-check")
    return problems


class AxisTableParser(unittest.TestCase):
    def test_the_table_of_the_axis_section_is_read_and_nothing_else(self):
        table = sa.axis_table(build_doctrine(QUIET, {"type": "`two-roles`, `display-led`", "colour": "-"}))
        self.assertEqual(list(table), [axis for axis, _ in sa.VISUAL_AXES])
        self.assertEqual(table["type"], {"value": "one-family", "also": ["two-roles", "display-led"]})
        self.assertEqual(table["colour"], {"value": "neutral-accent", "also": []})
        self.assertEqual(table["ornament"], {"value": "none", "also": []})

    def test_a_backticked_none_is_the_value_none_and_a_bare_one_is_an_empty_cell(self):
        # The ornament axis has a value called none: a house may permit it, and says so in backticks.
        for cell, also in (("`none`", ["none"]), ("`none`, `thematic`", ["none", "thematic"]),
                           ("none", []), ("None", []), ("-", []), ("\u2014", []), ("", []),
                           ("thematic, none", ["thematic"])):
            table = sa.axis_table(build_doctrine(moved(QUIET, ornament="structural"), {"ornament": cell}))
            self.assertEqual(table["ornament"], {"value": "structural", "also": also}, cell)
        table = sa.axis_table(build_doctrine(moved(QUIET, ornament="structural"), {"ornament": "`none`"}))
        self.assertEqual(sa.table_problems(table), [])
        self.assertEqual(sa.permitted(table)["ornament"], {"structural", "none"})
        chosen = sa.axis_table(build_doctrine(QUIET))
        self.assertEqual(sa.contract_problems(chosen, table), [])
        bare = sa.axis_table(build_doctrine(moved(QUIET, ornament="structural"), {"ornament": "none"}))
        self.assertEqual(sa.contract_problems(chosen, bare), ["outside-house:ornament=none"])

    def test_a_backticked_none_on_an_axis_with_no_such_value_is_named(self):
        table = sa.axis_table(build_doctrine(QUIET, {"imagery": "`none`"}))
        self.assertEqual(sa.table_problems(table), ["also-unknown:imagery=none"])

    def test_columns_are_found_by_name_and_also_allowed_is_optional(self):
        text = "## Axis table\n\n| In practice | Value | Axis |\n|---|:---:|---|\n| words | Still | Motion |\n"
        self.assertEqual(sa.axis_table(text), {"motion": {"value": "still", "also": []}})

    def test_a_deeper_heading_stays_inside_the_section_and_a_second_table_is_not_read(self):
        text = ("### Axis table\n\n| Axis | Value |\n|---|---|\n| type | one-family |\n\nA paragraph.\n\n"
                "| Axis | Value |\n|---|---|\n| colour | tonal |\n\n## Next\n\n| Axis | Value |\n|---|---|\n| x | y |\n")
        self.assertEqual(list(sa.axis_table(text)), ["type"])

    def test_text_without_the_section_or_without_a_table_is_refused(self):
        for text in ("# House\n\n| Axis | Value |\n|---|---|\n| type | one-family |\n",
                     "## Axis table\n\nNo table here.\n\n## Next\n",
                     "## Axis table\n\n| Axis | Value |\n| type | one-family |\n",
                     "## Axis table\n\n| Axis | Value |\n|---|---|\n",
                     "## Axis table\n\n| Name | Value |\n|---|---|\n| type | one-family |\n",
                     "## Axis table\n\n| Axis | Value |\n|---|---|\n| type |  |\n"):
            with self.assertRaises(sa.AxisError, msg=text):
                sa.axis_table(text)

    def test_an_axis_listed_twice_is_refused(self):
        text = "## Axis table\n\n| Axis | Value |\n|---|---|\n| type | one-family |\n| type | display-led |\n"
        with self.assertRaises(sa.AxisError):
            sa.axis_table(text)

    def test_table_problems_name_what_is_outside_the_vocabulary(self):
        table = sa.axis_table(build_doctrine(moved(QUIET, motion="frantic"), {"type": "enormous", "colour": "neutral-accent"}))
        del table["ornament"]
        table["sound"] = {"value": "loud", "also": []}
        self.assertEqual(sorted(sa.table_problems(table)),
                         ["also-repeats-value:colour", "also-unknown:type=enormous", "axis-missing:ornament",
                          "axis-unknown:sound", "value-unknown:motion=frantic"])

    def test_axes_out_of_order_are_a_problem(self):
        table = sa.axis_table(build_doctrine(dict(reversed(list(QUIET.items())))))
        self.assertEqual(sa.table_problems(table), ["axis-order"])

    def test_the_vocabulary_is_seven_axes_with_three_distinct_values_each(self):
        self.assertEqual([axis for axis, _ in sa.VISUAL_AXES],
                         ["type", "colour", "density", "motion", "layout", "imagery", "ornament"])
        for axis, values in sa.VISUAL_AXES:
            self.assertEqual(len(set(values)), 3, axis)
        self.assertEqual(sa.MIN_DISTANCE, 3)
        self.assertIs(sa.AXIS_SETS["visual"], sa.VISUAL_AXES)

    def test_no_axis_is_about_the_ground_both_houses_share(self):
        words = " ".join([axis for axis, _ in sa.VISUAL_AXES] + [v for _, values in sa.VISUAL_AXES for v in values])
        for term in SHARED_GROUND:
            self.assertNotIn(term.replace(" ", "-"), words)
            self.assertNotIn(term, words)


class DistanceBetweenBuiltDoctrines(unittest.TestCase):
    """TS-DOC-01, on files built here."""

    def pair(self, a: dict, b: dict, also_a=None, also_b=None) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            one, two = Path(tmp) / "a.md", Path(tmp) / "b.md"
            one.write_text(build_doctrine(a, also_a), encoding="utf-8")
            two.write_text(build_doctrine(b, also_b), encoding="utf-8")
            return sa.pair_problems(sa.axis_table(one.read_text(encoding="utf-8")),
                                    sa.axis_table(two.read_text(encoding="utf-8")))

    def test_ts_doc_01_two_doctrines_differing_on_two_axes_fail(self):
        problems = self.pair(QUIET, moved(QUIET, type="display-led", motion="authored"))
        self.assertIn("too-close:2<3", problems)

    def test_ts_doc_01_identical_doctrines_fail(self):
        self.assertIn("too-close:0<3", self.pair(QUIET, dict(QUIET)))

    def test_ts_doc_01_three_differing_axes_pass(self):
        self.assertEqual(self.pair(QUIET, moved(QUIET, type="display-led", motion="authored", ornament="thematic")), [])

    def test_ts_doc_01_opposed_doctrines_pass(self):
        self.assertEqual(self.pair(QUIET, LOUD), [])

    def test_ts_doc_01_values_that_differ_but_may_be_moved_together_fail(self):
        # Three axes differ, but on two of them one house permits the other's value.
        far = moved(QUIET, type="display-led", motion="authored", ornament="thematic")
        problems = self.pair(QUIET, far, also_a={"type": "`display-led`"}, also_b={"motion": "`still`"})
        self.assertEqual(problems, ["too-close-permitted:1<3"])

    def test_tables_naming_different_axes_are_not_a_pair(self):
        short = {axis: value for axis, value in LOUD.items() if axis != "ornament"}
        problems = self.pair(QUIET, short)
        self.assertIn("axes-not-shared", problems)
        self.assertIn("b:axis-missing:ornament", problems)

    def test_differing_and_disjoint_axes_are_listed_in_table_order(self):
        a = sa.axis_table(build_doctrine(QUIET, {"colour": "tonal"}))
        b = sa.axis_table(build_doctrine(moved(QUIET, colour="tonal", layout="broken-grid", type="display-led")))
        self.assertEqual(sa.differing_axes(a, b), ["type", "colour", "layout"])
        self.assertEqual(sa.disjoint_axes(a, b), ["type", "layout"])

    def test_a_contract_outside_its_house_is_named(self):
        house = sa.axis_table(build_doctrine(QUIET, {"type": "`two-roles`"}))
        inside = sa.axis_table(build_doctrine(moved(QUIET, type="two-roles")))
        outside = sa.axis_table(build_doctrine(moved(QUIET, type="display-led", motion="authored")))
        self.assertEqual(sa.contract_problems(inside, house), [])
        self.assertEqual(sa.contract_problems(outside, house),
                         ["outside-house:type=display-led", "outside-house:motion=authored"])

    def test_the_cli_exits_two_on_a_close_pair_and_zero_on_a_far_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = {}
            for name, values in (("quiet", QUIET), ("near", moved(QUIET, type="display-led")), ("loud", LOUD)):
                files[name] = Path(tmp) / f"{name}.md"
                files[name].write_text(build_doctrine(values), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                close = sa.main(["distance", str(files["quiet"]), str(files["near"]), "--json"])
            self.assertEqual(close, 2)
            self.assertEqual(json.loads(out.getvalue())["differing"], ["type"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sa.main(["distance", str(files["quiet"]), str(files["loud"])]), 0)
                self.assertEqual(sa.main(["parse", str(files["loud"])]), 0)
                self.assertEqual(sa.main(["parse", str(Path(tmp) / "absent.md")]), 2)


class RealDoctrines(unittest.TestCase):
    def setUp(self):
        self.tables = {skill: real_table(skill) for skill in HOUSES}
        self.restrained = self.tables["web-craft-restrained"]
        self.expressive = self.tables["web-craft-expressive"]

    def test_both_fill_the_same_named_axes_from_the_vocabulary(self):
        for skill, table in self.tables.items():
            self.assertEqual(sa.table_problems(table), [], skill)
        self.assertEqual(list(self.restrained), list(self.expressive))

    def test_they_differ_on_at_least_three_axes(self):
        self.assertGreaterEqual(len(sa.differing_axes(self.restrained, self.expressive)), sa.MIN_DISTANCE)
        self.assertEqual(sa.pair_problems(self.restrained, self.expressive), [])

    def test_the_restrained_house_permits_ornament_none_and_no_imagery_beyond_its_own(self):
        self.assertEqual(sa.permitted(self.restrained)["ornament"], {"structural", "none"})
        self.assertEqual(sa.permitted(self.restrained)["imagery"], {"content-only"})
        plain = {axis: dict(row) for axis, row in self.restrained.items()}
        plain["ornament"] = {"value": "none", "also": []}
        self.assertEqual(sa.contract_problems(plain, self.restrained), [])

    def test_no_pair_of_makers_inside_their_houses_can_be_closer_than_three_axes(self):
        self.assertGreaterEqual(len(sa.disjoint_axes(self.restrained, self.expressive)), sa.MIN_DISTANCE)

    def test_each_doctrine_prints_the_shared_vocabulary_as_the_module_holds_it(self):
        for skill in HOUSES:
            text = doctrine_path(skill).read_text(encoding="utf-8")
            section = text.split("## Axis vocabulary", 1)[1].split("\n## ", 1)[0]
            rows = [sa._cells(line) for line in section.splitlines() if line.startswith("| `")]
            printed = tuple((row[0].strip("`"), tuple(v.strip().strip("`") for v in row[1].split(","))) for row in rows)
            self.assertEqual(printed, sa.VISUAL_AXES, skill)

    def test_the_fixtures_hold_these_files_and_these_tables(self):
        listed = json.loads((FIX / "doctrine-files-sample.json").read_text(encoding="utf-8"))
        self.assertEqual({d["skill"]: d["family"] for d in listed["doctrines"]}, HOUSES)
        for entry in listed["doctrines"]:
            self.assertEqual(entry["doctrine"], doctrine_path(entry["skill"]).relative_to(_TREE).as_posix())
            self.assertTrue((_TREE / entry["doctrine"]).is_file())
        self.assertTrue((_TREE / listed["attribution"]).is_file())
        sample = json.loads((FIX / "axis-tables-sample.json").read_text(encoding="utf-8"))
        self.assertEqual(sample["axes"], [[axis, list(values)] for axis, values in sa.VISUAL_AXES])
        self.assertEqual(sample["tables"], self.tables)
        self.assertEqual(sample["differing"], sa.differing_axes(self.restrained, self.expressive))
        self.assertEqual(sample["disjoint"], sa.disjoint_axes(self.restrained, self.expressive))
        self.assertEqual(sample["minimum"], sa.MIN_DISTANCE)

    def test_the_fixture_manifest_hashes_match_the_files(self):
        manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
        component = manifest["components"]["visual-doctrines"]
        entries = [f for side in ("inputs", "outputs") for port in component[side].values() for f in port["fixtures"]]
        self.assertEqual(sorted(Path(e["path"]).name for e in entries),
                         ["axis-tables-sample.json", "doctrine-files-sample.json"])
        for entry in entries:
            digest = hashlib.sha256((_TREE / entry["path"]).read_bytes()).hexdigest()
            self.assertEqual(entry["hash"], "sha256:" + digest, entry["path"])


class Families(unittest.TestCase):
    def resolve(self, family: str) -> list[str]:
        tool = _TREE / "skills" / "_meta" / "skill_resolve.py"
        if not tool.is_file():
            self.skipTest("skill_resolve is not in this tree")
        done = subprocess.run([sys.executable, str(tool), "--skills-root", str(_TREE / "skills"), "--json",
                               "family:" + family], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual(report["unresolved"], [])
        return report["expanded"]["family:" + family]

    def test_the_two_skills_declare_different_families(self):
        declared = {}
        for skill in HOUSES:
            meta = frontmatter((_TREE / "skills" / skill / "SKILL.md").read_text(encoding="utf-8"))
            self.assertEqual(meta["name"], skill)
            declared[skill] = meta["family"]
        self.assertEqual(declared, HOUSES)
        self.assertEqual(len(set(declared.values())), 2)

    def test_both_families_resolve_and_share_no_member(self):
        members = {family: self.resolve(family) for family in HOUSES.values()}
        self.assertEqual(members, {family: [skill] for skill, family in HOUSES.items()})
        self.assertFalse(set(members["visual-craft-restrained"]) & set(members["visual-craft-expressive"]))

    def test_a_family_nobody_declares_does_not_resolve(self):
        tool = _TREE / "skills" / "_meta" / "skill_resolve.py"
        if not tool.is_file():
            self.skipTest("skill_resolve is not in this tree")
        done = subprocess.run([sys.executable, str(tool), "--skills-root", str(_TREE / "skills"), "--json",
                               "family:visual-craft-nobody"], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120)
        self.assertNotEqual(done.returncode, 0)


class RefuseLists(unittest.TestCase):
    def setUp(self):
        self.rows = {skill: sa.refuse_rows(doctrine_path(skill).read_text(encoding="utf-8")) for skill in HOUSES}

    def test_the_reader_takes_list_items_and_first_cells_of_the_refuse_section_only(self):
        self.assertEqual(sa.refuse_rows(build_doctrine(QUIET)), ["a first refusal", "a second refusal"])
        self.assertEqual(sa.refuse_rows("# House\n\n## Axis table\n\n- not a refusal\n"), [])

    def test_each_house_has_a_refuse_list_of_its_own(self):
        for skill, rows in self.rows.items():
            self.assertGreaterEqual(len(rows), 8, skill)
            self.assertEqual(len(rows), len(set(rows)), skill)
            for row in rows:
                self.assertGreaterEqual(len(row.split()), 4, row)
        self.assertFalse(set(self.rows["web-craft-restrained"]) & set(self.rows["web-craft-expressive"]))

    def test_no_refuse_row_is_a_neutral_floor_row_or_shared_ground(self):
        floor = _TREE / "skills" / "design-critique" / "references" / "neutral-floor.md"
        terms = list(SHARED_GROUND)
        if floor.is_file():
            ids = re.findall(r"^\| `([a-z-]+)` \|", floor.read_text(encoding="utf-8"), flags=re.M)
            self.assertIn("contrast-text", ids)
            terms += [row_id.replace("-", " ") for row_id in ids]
        for skill, rows in self.rows.items():
            for row in rows:
                for term in terms:
                    self.assertNotIn(term, row, f"{skill}: '{row}' is shared ground ({term})")

    def test_a_refuse_row_about_the_floor_would_be_seen(self):
        rows = sa.refuse_rows("## Refuse list\n\n- Motion that ignores the reduced motion preference\n")
        self.assertTrue(any("reduced motion" in row for row in rows))

    def test_the_reader_agrees_with_the_critic_test_on_the_real_doctrines(self):
        other = _TREE / "skills" / "design-critique" / "tests" / "test_design_critique.py"
        if not other.is_file():
            self.skipTest("the design-critique test is not in this tree")
        spec = importlib.util.spec_from_file_location("critic_test_for_doctrines", other)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for skill in HOUSES:
            text = doctrine_path(skill).read_text(encoding="utf-8")
            self.assertEqual(sa.refuse_rows(text), module.refuse_rows(text), skill)
        doctrines = [doctrine_path(skill) for skill in HOUSES]
        self.assertEqual(module.refuse_problems(module.critic_files(), doctrines), [])


class Attribution(unittest.TestCase):
    """TS-DOC-02."""

    def setUp(self):
        self.path = _TREE / "skills" / "web-craft-restrained" / "references" / "ATTRIBUTION.md"
        self.text = self.path.read_text(encoding="utf-8")

    def test_ts_doc_02_the_real_file_names_a_licence_a_commit_and_an_intake_verdict_id(self):
        self.assertEqual(attribution_problems(self.text), [])
        self.assertIn(SOURCE_COMMIT, self.text)
        self.assertIn("https://github.com/pbakaus/impeccable", self.text)
        self.assertNotIn("PENDING", self.text)

    def test_ts_doc_02_a_file_missing_any_one_of_them_fails(self):
        cut = {
            "licence-text": self.text.replace("END OF TERMS AND CONDITIONS", ""),
            "commit": self.text.replace(SOURCE_COMMIT, SOURCE_COMMIT[:8]),
            "intake-verdict-id": INTAKE_ID.sub("(not recorded)", self.text),
            "verdict": re.sub(r"\|\s*Verdict\s*\|[^\n]*\n", "", self.text),
            "changes": self.text.replace("## What was adapted", "## Notes"),
            "primary-sources": self.text.replace("https://www.w3.org/TR/WCAG22/", "https://example.invalid/"),
        }
        for missing, text in cut.items():
            self.assertEqual(attribution_problems(text), [missing])
        self.assertEqual(len(attribution_problems("# Attribution\n\nAdapted from somewhere.\n")), 6)

    def test_the_licence_text_is_whole(self):
        licence = self.text.split("```text", 1)[1].split("```", 1)[0]
        for section in range(1, 10):
            self.assertRegex(licence, rf"(?m)^\s+{section}\. [A-Z]")
        self.assertIn("APPENDIX: How to apply the Apache License to your work.", licence)
        self.assertGreater(len(licence), 10000)

    def test_it_says_nothing_was_installed_and_cites_primary_sources_for_facts(self):
        self.assertIn("nothing of it is installed or run", self.text)
        for address in ("https://www.w3.org/TR/WCAG22/#contrast-minimum", "https://www.w3.org/TR/css-values-4/",
                        "https://www.w3.org/TR/mediaqueries-5/"):
            self.assertIn(address, self.text)

    def test_only_the_adapted_house_carries_an_attribution_and_names_its_source(self):
        self.assertFalse((_TREE / "skills" / "web-craft-expressive" / "references" / "ATTRIBUTION.md").exists())
        expressive = "".join(p.read_text(encoding="utf-8")
                             for p in (_TREE / "skills" / "web-craft-expressive").rglob("*.md"))
        self.assertNotIn("impeccable", expressive.lower())
        doctrine = doctrine_path("web-craft-restrained").read_text(encoding="utf-8")
        self.assertIn("ATTRIBUTION.md", doctrine)


class DatedReferences(unittest.TestCase):
    def references(self) -> list[Path]:
        return sorted(p for skill in HOUSES for p in (_TREE / "skills" / skill / "references").glob("*.md"))

    def test_every_reference_that_carries_a_date_has_a_freshness_anchor(self):
        files = self.references()
        self.assertEqual(len(files), 3)
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertTrue(DATED.search(text), f"{path} carries no date")
            self.assertEqual(freshness_problems(text), [], str(path))

    def test_a_dated_reference_without_an_anchor_fails(self):
        self.assertEqual(freshness_problems("Fonts seen on 2026-10-12.\n"), ["no-anchor", "no-re-check"])
        self.assertEqual(freshness_problems("**Freshness anchor.** Checked 2026-10-12 against X.\n"), ["no-re-check"])
        self.assertEqual(freshness_problems("No date here.\n"), [])

    def test_the_catalogue_is_a_named_reference_only(self):
        text = doctrine_path("web-craft-expressive").read_text(encoding="utf-8")
        section = "\n".join(sa._section(text, "reference catalogue") or [])
        self.assertIn("REFERENCE ONLY", section)
        self.assertRegex(section, r"\b[0-9a-f]{40}\b")
        self.assertEqual(text.lower().count("magicui"), section.lower().count("magicui"))
        self.assertNotIn("```", text)
        self.assertNotRegex(text, r"(?i)\b(npx|npm|pnpm|yarn|shadcn)\b")
        restrained = "".join(p.read_text(encoding="utf-8")
                             for p in (_TREE / "skills" / "web-craft-restrained").rglob("*.md"))
        self.assertNotIn("magicui", restrained.lower())


class SkillEntryFiles(unittest.TestCase):
    def test_the_descriptions_lead_with_the_subject(self):
        for skill, opening in (("web-craft-restrained", "Restrained web page craft"),
                               ("web-craft-expressive", "Expressive web page craft")):
            description = frontmatter((_TREE / "skills" / skill / "SKILL.md").read_text(encoding="utf-8"))["description"]
            self.assertTrue(description.startswith(opening), skill)
            self.assertIn("Use when", description)
            self.assertLessEqual(len(description), 250, skill)
            self.assertNotRegex(description, r"\b(I|you|You)\b")

    def test_each_entry_file_names_its_references_and_its_rival(self):
        for skill in HOUSES:
            text = (_TREE / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
            for reference in sorted((_TREE / "skills" / skill / "references").glob("*.md")):
                self.assertIn("references/" + reference.name, text, skill)
            rival = next(other for other in HOUSES if other != skill)
            self.assertIn("`" + rival + "`", text)
            self.assertIn("direction contract", text)

    def test_neither_house_claims_the_shared_ground_as_its_own(self):
        for skill in HOUSES:
            entry = (_TREE / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
            doctrine = doctrine_path(skill).read_text(encoding="utf-8")
            self.assertIn("They bind both houses equally", " ".join(entry.split()))
            self.assertIn("## What both houses share", doctrine)
            description = frontmatter(entry)["description"].lower()
            for term in ("accessib", "usab", "wcag"):
                self.assertNotIn(term, description)

    def test_the_skills_pass_the_skill_audit_and_the_frontmatter_lint(self):
        audit = _TREE / "skills" / "_meta" / "skill_audit.py"
        lint = _TREE / "skills" / "_meta" / "frontmatter_lint.py"
        if not (audit.is_file() and lint.is_file()):
            self.skipTest("the audit tools are not in this tree")
        for skill in HOUSES:
            entry = str(_TREE / "skills" / skill / "SKILL.md")
            for command in ([str(audit), "check", "--repo", str(_TREE), "--tree", entry], [str(lint), "check", entry]):
                done = subprocess.run([sys.executable] + command, capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=120)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
