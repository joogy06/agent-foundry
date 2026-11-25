#!/usr/bin/env python3
"""test_copy_schools.py -- #352: the two rival copy schools, their format files and the cv rivals.

Design docs/plans/2026-10-12-352-creative-studio-design.md, "Families" (DW-2):
  TS-CPY-01   two school files agreeing on four of the six axes fail the distance test
  TS-CPY-02   the cv profile's seats load the same skill and differ only in angle
  and: the two real schools fill the same six named axes and differ on at least three; the two
  skills declare the families copy-plain and copy-voiced and both resolve through skill_resolve;
  "rivals share nothing" is a rule about the family tokens of a rival pair, not about a skill both
  seats name; the format files carry no voice rule and are read by both schools; content-writer
  says the school file replaces the persona in a studio run; the text critic's reference holds no
  row of either school's refuse list and names no school.

TS-CPY-01 builds its school files at test time. The arms named "real" read the shipped files.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

_SKILL = Path(__file__).resolve().parent.parent
_TREE = _SKILL.parent.parent
SKILLS = _TREE / "skills"
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(_SKILL / "scripts"))
sys.path.insert(0, str(SKILLS / "_meta"))

import studio  # noqa: E402
import studio_axes as sa  # noqa: E402

SCHOOLS = {"business-writing": ("copy-plain", "references/school-plain.md"),
           "content-writer": ("copy-voiced", "references/school-voiced.md")}
FORMATS = ("format-article.md", "format-page-copy.md")
AXES = [axis for axis, _ in sa.COPY_AXES]
#: What binds both schools alike. No axis and no refuse row is about it.
SHARED_GROUND = ("truth", "unsupported", "placeholder", "outline", "length band", "search question", "link slot")
#: Words that make a rule about how a piece sounds. A format file holds none of them.
VOICE_WORDS = ("tone", "voice", "humour", "humor", "first person", "second person", "rhythm", "persona",
               "opinion", "verdict", "witty", "formal", "informal", "conversational", "sentence length")


def school_text(skill: str) -> str:
    return (SKILLS / skill / SCHOOLS[skill][1]).read_text(encoding="utf-8")


def real_table(skill: str) -> dict:
    return sa.axis_table(school_text(skill))


def build_school(values: dict) -> str:
    """A school file with an axis table holding `values`, written the way a real one is."""
    rows = "\n".join(f"| `{axis}` | `{value}` | none | prose that is not read |" for axis, value in values.items())
    return ("# A school\n\n## Axis table\n\n| Axis | Value | Also allowed | In practice |\n|---|---|---|---|\n"
            + rows + "\n\n## Refuse list\n\n- A thing this school never writes\n")


FIRST = {axis: values[0] for axis, values in sa.COPY_AXES}
LAST = {axis: values[-1] for axis, values in sa.COPY_AXES}


def frontmatter(text: str) -> dict:
    meta = {}
    for line in text.split("---", 2)[1].splitlines():
        found = re.match(r"^([a-z_-]+):\s*(.*)$", line)
        if found:
            meta[found.group(1)] = found.group(2).strip().strip('"')
    return meta


class TheCopyAxes(unittest.TestCase):

    def test_there_are_six_named_axes_with_three_distinct_values_each(self) -> None:
        self.assertEqual(AXES, ["opening", "claims", "rhythm", "person", "proof-placement", "call-to-action"])
        for axis, values in sa.COPY_AXES:
            self.assertEqual(len(set(values)), 3, axis)
        self.assertIs(sa.AXIS_SETS["copy"], sa.COPY_AXES)

    def test_no_axis_is_about_the_ground_both_schools_share(self) -> None:
        words = " ".join([axis for axis, _ in sa.COPY_AXES] + [v for _, values in sa.COPY_AXES for v in values])
        for shared in SHARED_GROUND + ("true", "length", "fact"):
            self.assertNotIn(shared.replace(" ", "-"), words)

    def test_the_command_line_reads_a_school_with_the_copy_set(self) -> None:
        path = SKILLS / "business-writing" / SCHOOLS["business-writing"][1]
        done = subprocess.run([sys.executable, str(_SKILL / "scripts" / "studio_axes.py"), "parse", str(path),
                               "--set", "copy"], capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual((done.returncode, done.stdout.splitlines()[-1]), (0, "problems: none"))
        wrong = subprocess.run([sys.executable, str(_SKILL / "scripts" / "studio_axes.py"), "parse", str(path)],
                               capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual(wrong.returncode, 2)                # the visual set is not this file's vocabulary


class DistanceBetweenBuiltSchools(unittest.TestCase):

    def problems(self, a: dict, b: dict) -> list:
        return sa.pair_problems(sa.axis_table(build_school(a)), sa.axis_table(build_school(b)), sa.COPY_AXES)

    def test_ts_cpy_01_two_schools_agreeing_on_four_axes_fail(self) -> None:
        near = dict(FIRST, opening=LAST["opening"], claims=LAST["claims"])
        self.assertEqual(len(sa.differing_axes(sa.axis_table(build_school(FIRST)), sa.axis_table(build_school(near)))), 2)
        self.assertEqual(self.problems(FIRST, near), ["too-close:2<3", "too-close-permitted:2<3"])

    def test_ts_cpy_01_identical_schools_fail_and_three_differing_axes_pass(self) -> None:
        self.assertIn("too-close:0<3", self.problems(FIRST, FIRST))
        self.assertEqual(self.problems(FIRST, dict(FIRST, opening=LAST["opening"], claims=LAST["claims"],
                                                  rhythm=LAST["rhythm"])), [])
        self.assertEqual(self.problems(FIRST, LAST), [])

    def test_a_school_written_on_the_visual_axes_is_not_a_copy_school(self) -> None:
        visual = {axis: values[0] for axis, values in sa.VISUAL_AXES}
        problems = sa.table_problems(sa.axis_table(build_school(visual)), sa.COPY_AXES)
        self.assertIn("axis-missing:opening", problems)
        self.assertIn("axis-unknown:colour", problems)


class RealSchools(unittest.TestCase):

    def setUp(self) -> None:
        self.plain, self.voiced = real_table("business-writing"), real_table("content-writer")

    def test_both_fill_the_same_six_axes_from_the_vocabulary(self) -> None:
        for table in (self.plain, self.voiced):
            self.assertEqual(sa.table_problems(table, sa.COPY_AXES), [])
        self.assertEqual(list(self.plain), AXES)
        self.assertEqual(list(self.voiced), AXES)

    def test_they_differ_on_at_least_three_of_the_six_axes(self) -> None:
        self.assertGreaterEqual(len(sa.differing_axes(self.plain, self.voiced)), sa.MIN_DISTANCE)
        self.assertEqual(sa.pair_problems(self.plain, self.voiced, sa.COPY_AXES), [])

    def test_no_pair_of_writers_inside_their_schools_can_be_closer_than_three_axes(self) -> None:
        self.assertGreaterEqual(len(sa.disjoint_axes(self.plain, self.voiced)), sa.MIN_DISTANCE)

    def test_each_school_prints_the_shared_vocabulary_as_the_module_holds_it(self) -> None:
        for skill in SCHOOLS:
            section = school_text(skill).split("## Axis vocabulary", 1)[1].split("\n## ", 1)[0]
            rows = [sa._cells(line) for line in section.splitlines() if line.startswith("| `")]
            printed = tuple((row[0].strip("`"), tuple(v.strip().strip("`") for v in row[1].split(","))) for row in rows)
            self.assertEqual(printed, sa.COPY_AXES, skill)

    def test_each_school_has_a_refuse_list_of_its_own_with_nothing_of_the_shared_ground(self) -> None:
        lists = {skill: sa.refuse_rows(school_text(skill)) for skill in SCHOOLS}
        for skill, rows in lists.items():
            self.assertGreaterEqual(len(rows), 6, skill)
            for refused in rows:
                for shared in SHARED_GROUND:
                    self.assertNotIn(shared, refused, f"{skill}: {refused}")
        self.assertFalse(set(lists["business-writing"]) & set(lists["content-writer"]))

    def test_each_school_says_what_both_share_and_names_its_three_lines(self) -> None:
        for skill in SCHOOLS:
            text = school_text(skill)
            share = text.split("## What both schools share", 1)[1].split("\n## ", 1)[0]
            for words in ("truth pack", "[FACT NEEDED:", "constraints.md", "format file"):
                self.assertIn(words, share, skill)
            self.assertIn("then three lines", text.split("## Process", 1)[1], skill)

    def test_neither_school_names_the_other(self) -> None:
        for skill, other in (("business-writing", "content-writer"), ("content-writer", "business-writing")):
            text = school_text(skill)
            self.assertNotIn(other, text)
            self.assertNotIn(SCHOOLS[other][0], text)
            self.assertNotRegex(text, rf"(?i)\b{SCHOOLS[other][0].split('-')[1]}\b")

    def test_the_fixtures_hold_these_files_and_these_tables(self) -> None:
        listed = json.loads((FIX / "school-files-sample.json").read_text(encoding="utf-8"))
        self.assertEqual({s["skill"]: s["family"] for s in listed["schools"]}, {k: v[0] for k, v in SCHOOLS.items()})
        for entry in listed["schools"]:
            self.assertEqual(entry["school"], f"skills/{entry['skill']}/{SCHOOLS[entry['skill']][1]}")
        for rel in [s["school"] for s in listed["schools"]] + listed["formats"]:
            self.assertTrue((_TREE / rel).is_file(), rel)
        sample = json.loads((FIX / "school-axes-sample.json").read_text(encoding="utf-8"))
        self.assertEqual(sample["axes"], [[axis, list(values)] for axis, values in sa.COPY_AXES])
        self.assertEqual(sample["tables"], {"business-writing": self.plain, "content-writer": self.voiced})
        self.assertEqual(sample["differing"], sa.differing_axes(self.plain, self.voiced))
        self.assertEqual(sample["disjoint"], sa.disjoint_axes(self.plain, self.voiced))
        self.assertEqual(sample["minimum"], sa.MIN_DISTANCE)

    def test_the_fixture_manifest_hashes_match_the_files(self) -> None:
        manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
        component = manifest["components"]["copy-schools"]
        entries = [f for side in ("inputs", "outputs") for port in component[side].values() for f in port["fixtures"]]
        self.assertEqual(sorted(Path(e["path"]).name for e in entries), ["school-axes-sample.json", "school-files-sample.json"])
        for entry in entries:
            digest = hashlib.sha256((_TREE / entry["path"]).read_bytes()).hexdigest()
            self.assertEqual(entry["hash"], "sha256:" + digest, entry["path"])


class Families(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        import skill_resolve
        cls.resolver = skill_resolve
        cls.index = skill_resolve.build_index(SKILLS)

    def members(self, family: str) -> list:
        return self.resolver.resolve([f"family:{family}"], self.index, set())["resolved"]

    def test_the_two_skills_declare_their_families_in_frontmatter(self) -> None:
        for skill, (family, _) in SCHOOLS.items():
            meta = frontmatter((SKILLS / skill / "SKILL.md").read_text(encoding="utf-8"))
            self.assertEqual((meta["name"], meta["family"]), (skill, family))

    def test_both_families_resolve_and_share_no_member(self) -> None:
        self.assertEqual(self.members("copy-plain"), ["business-writing"])
        self.assertEqual(self.members("copy-voiced"), ["content-writer"])

    def test_each_entry_file_points_at_its_new_references(self) -> None:
        plain = (SKILLS / "business-writing" / "SKILL.md").read_text(encoding="utf-8")
        voiced = (SKILLS / "content-writer" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/school-plain.md", plain)
        for name in ("references/school-voiced.md", "references/format-article.md", "references/format-page-copy.md"):
            self.assertIn(name, voiced)

    def test_content_writer_says_the_school_file_replaces_the_persona_in_a_studio_run(self) -> None:
        lines = [line for line in (SKILLS / "content-writer" / "SKILL.md").read_text(encoding="utf-8").splitlines()
                 if "school file" in line and "persona" in line]
        self.assertEqual(len(lines), 1)
        for words in ("creative-studio run", "takes the place of the persona", "no persona is loaded",
                      "unless the run's brief names one"):
            self.assertIn(words, lines[0])

    def test_the_two_skills_pass_the_skill_audit_and_the_frontmatter_lint(self) -> None:
        audit, lint = SKILLS / "_meta" / "skill_audit.py", SKILLS / "_meta" / "frontmatter_lint.py"
        for skill in SCHOOLS:
            entry = str(SKILLS / skill / "SKILL.md")
            for command in ([str(audit), "check", "--repo", str(_TREE), "--tree", entry], [str(lint), "check", entry]):
                done = subprocess.run([sys.executable] + command, capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=120, check=False)
                self.assertEqual(done.returncode, 0, (done.stdout + done.stderr)[-800:])


class RivalsShareNoFamilyToken(unittest.TestCase):
    """The doctrine rule "rivals share nothing" is about the family tokens of a pair."""

    def function(self, a: list, b: list) -> dict:
        profile, _ = studio.load_profile("article")
        profile = json.loads(json.dumps(profile))
        profile["functions"][0]["seats"][0]["loads"], profile["functions"][0]["seats"][1]["loads"] = a, b
        return profile

    def codes(self, profile: dict) -> list:
        return [code for code, _ in studio.profile_problems(profile)]

    def test_two_seats_under_one_family_are_refused(self) -> None:
        self.assertIn("rivals_share_family", self.codes(self.function(["family:copy-plain"], ["family:copy-plain"])))

    def test_a_skill_both_seats_name_beside_different_families_is_allowed(self) -> None:
        self.assertEqual(self.codes(self.function(["family:copy-plain", "human-voice-writing"],
                                                  ["family:copy-voiced", "human-voice-writing"])), [])

    def test_the_real_profiles_seat_the_two_schools_under_different_families(self) -> None:
        for name in ("article", "website-page"):
            profile, _ = studio.load_profile(name)
            function = next(f for f in profile["functions"] if f["axis_set"] == "copy")
            self.assertEqual([seat["loads"] for seat in function["seats"]], [["family:copy-plain"], ["family:copy-voiced"]])
            self.assertEqual([seat["school_file"] for seat in function["seats"]],
                             ["business-writing/references/school-plain.md", "content-writer/references/school-voiced.md"])
            self.assertEqual(len({seat["format_file"] for seat in function["seats"]}), 1, name)


class CvRivals(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.profile, _ = studio.load_profile("cv")
        cls.seats = cls.profile["functions"][0]["seats"]

    def test_ts_cpy_02_the_seats_load_the_same_skill_and_differ_only_in_angle(self) -> None:
        self.assertEqual([seat["loads"] for seat in self.seats], [["career-application-writer"]] * 2)
        stripped = [{k: v for k, v in seat.items() if k not in ("id", "angle", "angle_brief")} for seat in self.seats]
        self.assertEqual(stripped[0], stripped[1])
        self.assertEqual(sorted(seat["angle"] for seat in self.seats), ["impact-led", "scope-led"])
        for seat in self.seats:
            self.assertNotIn("school_file", seat)
            self.assertNotIn("doctrine", seat)

    def test_ts_cpy_02_equal_angles_or_an_angle_off_the_axis_are_refused(self) -> None:
        for angles, code in ((("impact-led", "impact-led"), "angles_equal"), (("impact-led", "loudest"), "angle_unknown")):
            profile = json.loads(json.dumps(self.profile))
            for seat, angle in zip(profile["functions"][0]["seats"], angles):
                seat["angle"] = angle
            self.assertIn(code, [c for c, _ in studio.profile_problems(profile)])

    def test_the_voice_is_decided_once_in_the_brief_and_the_run_directory_is_private(self) -> None:
        self.assertIn("voice", self.profile["brief"]["required"])
        self.assertTrue(self.profile["private"])
        self.assertEqual(self.profile["functions"][0]["axis_set"], "angle")
        self.assertEqual([axis for axis, _ in sa.ANGLE_AXES], ["angle"])
        self.assertEqual(self.profile["critic"]["reference"], "creative-studio/references/text-critic.md")
        self.assertFalse(self.profile["evidence"]["text_check"]["truth_pack"])

    def test_the_skill_resolves_and_the_fixture_names_the_same_rivals(self) -> None:
        loads = studio.resolve_loads(self.profile, SKILLS)
        self.assertEqual([loads[seat["id"]]["members"] for seat in self.seats], [["career-application-writer"]] * 2)
        listed = json.loads((FIX / "school-files-sample.json").read_text(encoding="utf-8"))["cv"]
        self.assertEqual(listed, {"skill": "career-application-writer", "angles": [seat["angle"] for seat in self.seats]})


class FormatFiles(unittest.TestCase):

    def test_both_format_files_are_read_by_both_schools(self) -> None:
        for name, article in (("article", "format-article.md"), ("website-page", "format-page-copy.md")):
            profile, _ = studio.load_profile(name)
            function = next(f for f in profile["functions"] if f["axis_set"] == "copy")
            self.assertEqual([seat["format_file"] for seat in function["seats"]], [f"content-writer/references/{article}"] * 2)

    def test_a_format_file_carries_no_voice_rule_and_names_no_school(self) -> None:
        for name in FORMATS:
            text = (SKILLS / "content-writer" / "references" / name).read_text(encoding="utf-8").lower()
            for word in VOICE_WORDS + ("plain", "voiced", "business-writing", "copy-plain", "copy-voiced"):
                self.assertNotRegex(text, rf"\b{re.escape(word)}\b", f"{name}: {word}")
            self.assertIn("both schools", text)
            with self.assertRaises(sa.AxisError):
                sa.axis_table(text)                         # a format file takes no side on any axis

    def test_the_article_format_says_where_title_description_and_headings_go(self) -> None:
        text = (SKILLS / "content-writer" / "references" / "format-article.md").read_text(encoding="utf-8")
        for words in ("title:", "description:", "structured-data:", "heading outline", "length band",
                      "[FACT NEEDED: what is missing]", "[LINK: anchor text -> slot name]", "truth pack"):
            self.assertIn(words, text)

    def test_the_page_copy_format_takes_no_truth_pack_and_uses_labelled_placeholders(self) -> None:
        text = (SKILLS / "content-writer" / "references" / "format-page-copy.md").read_text(encoding="utf-8")
        for words in ("takes no truth pack", "[FACT NEEDED: what is missing]", "# Hero", "## States", "copy.md"):
            self.assertIn(words, text)


class TextCritic(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = (_SKILL / "references" / "text-critic.md").read_text(encoding="utf-8")

    def test_it_holds_no_row_of_either_schools_refuse_list(self) -> None:
        lines = [sa._normalise(line) for line in self.text.splitlines()]
        for skill in SCHOOLS:
            for refused in sa.refuse_rows(school_text(skill)):
                if len(refused.split()) >= 4:
                    self.assertFalse([line for line in lines if refused in line], f"{skill}: {refused}")

    def test_it_names_no_school_and_no_writer_skill(self) -> None:
        self.assertNotRegex(self.text, r"(?i)business-writing|content-writer|copy-plain|copy-voiced|\bplain school\b"
                                       r"|\bvoiced\b|career-application-writer")

    def test_it_holds_the_floor_the_rubric_the_text_borrow_cards_and_the_rule_by_id(self) -> None:
        for words in ("no-unsupported-claims", "no-unlabelled-placeholder", "outline-met", "length-band-met",
                      "`first-screen`", "The named reader gets what they came for",
                      "Each technical point is explained at the level the brief sets", "`locator.text`",
                      "`outline`", "`term_set`", "`evidence_region.text`", "human-voice-writing",
                      "OWN direction contract", "CONV-1", "skills/_meta/convergence-rule.md",
                      "the claim check on the repaired draft"):
            self.assertIn(words, self.text)

    def test_it_is_a_citing_place_of_the_rule_and_does_not_define_or_restate_it(self) -> None:
        citing = json.loads((SKILLS / "_meta" / "tests" / "fixtures" / "convergence" / "citing-files-sample.json")
                            .read_text(encoding="utf-8"))["citing_files"]
        self.assertIn("skills/creative-studio/references/text-critic.md", citing)
        self.assertNotIn("<!-- convergence-rule.v1", self.text)
        self.assertFalse([line for line in self.text.splitlines() if re.match(r"^#+\s*CONV-1", line)])
        self.assertNotIn("exactly one output", self.text.lower())


if __name__ == "__main__":
    unittest.main()
