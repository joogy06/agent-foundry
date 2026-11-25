#!/usr/bin/env python3
"""test_social_post.py -- #352: the social-post skill, the one member of the family `social`.

Design docs/plans/2026-10-12-352-creative-studio-design.md, "Families" and "Social and CV rivals":
  TS-SOC-01   the family `social` resolves to social-post through skill_resolve
  TS-SOC-02   references/platform-formats.md carries a dated freshness anchor on every platform row
  and: the skill passes the skill audit and the frontmatter lint with a subject-first description;
  a platform row is Confirmed with a source and a figure, or Not confirmed with no figure; the entry
  file and the reference are read by BOTH copy schools of a studio run, so they hold neither school's
  label word, no rule about how a post sounds and no axis table; the fixtures are what the manifest
  says they are.

TS-SOC-02 has two arms: the shipped reference, and references built at test time that each break the
rule one way (a row with no anchor, an anchor with no date, a figure on a row that is not confirmed).
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
sys.path.insert(0, str(SKILLS / "_meta"))
sys.path.insert(0, str(SKILLS / "creative-studio" / "scripts"))

import freshness  # noqa: E402
import skill_resolve  # noqa: E402
import studio  # noqa: E402
import studio_axes  # noqa: E402

ENTRY = _SKILL / "SKILL.md"
FORMATS = _SKILL / "references" / "platform-formats.md"
#: The label word of each copy school. A file both schools read holds neither (the runner refuses the brief).
SCHOOL_WORDS = ("plain", "voiced", "business-writing", "content-writer", "copy-plain", "copy-voiced")
#: Words that make a rule about how a piece sounds. The platform reference holds none of them.
VOICE_WORDS = ("tone", "voice", "humour", "humor", "first person", "second person", "rhythm", "persona",
               "opinion", "verdict", "witty", "formal", "informal", "conversational", "sentence length")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FIGURE = re.compile(r"\d")


def frontmatter(text: str) -> dict:
    meta = {}
    for line in text.split("---", 2)[1].splitlines():
        found = re.match(r"^([a-z_-]+):\s*(.*)$", line)
        if found:
            meta[found.group(1)] = found.group(2).strip().strip('"')
    return meta


def platform_rows(text: str) -> list:
    """The data rows of the table under `## Platforms`, each as {column name: cell}."""
    section = re.search(r"^## Platforms\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not section:
        return []
    lines = [line for line in section.group(1).splitlines() if line.lstrip().startswith("|")]
    if len(lines) < 3:
        return []
    cells = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    return [dict(zip(cells[0], row)) for row in cells[2:]]


def anchors_of(text: str) -> dict:
    """{subject: anchor} over every FRESHNESS:v1 block of the text."""
    found = {}
    for body in freshness.extract_blocks(text):
        for anchor in freshness.parse_freshness_yaml(body)["anchors"]:
            found[str(anchor.get("subject"))] = anchor
    return found


def anchor_problems(text: str) -> list:
    """Why the platform table of a reference is not dated: [(code, platform)]. Empty when it is."""
    rows = platform_rows(text)
    if not rows:
        return [("no_platform_table", "")]
    anchors = anchors_of(text)
    problems = []
    for row in rows:
        name = row.get("Platform", "")
        anchor = anchors.get(row.get("Anchor", "").strip("`"))
        if anchor is None:
            problems.append(("row_has_no_anchor", name))
            continue
        review = str(anchor.get("review_by") or "")
        if not _DATE.match(review) or row.get("Re-check by") != review:
            problems.append(("anchor_has_no_review_date", name))
        confirmed = row.get("Status") == "Confirmed"
        if row.get("Status") not in ("Confirmed", "Not confirmed"):
            problems.append(("status_unknown", name))
        elif confirmed:
            read = str(anchor.get("verified_on") or "")
            if anchor.get("kind") != "external_fact" or not _DATE.match(read) or not row.get("Read on", "").startswith(read):
                problems.append(("confirmed_row_has_no_read_date", name))
            url = str(anchor.get("source_url") or "")
            if not url.startswith("https://") or f"]({url})" not in row.get("Source", ""):
                problems.append(("confirmed_row_has_no_source", name))
            if not _FIGURE.search(row.get("Text limit of one post", "")):
                problems.append(("confirmed_row_has_no_figure", name))
        elif _FIGURE.search(row.get("Text limit of one post", "")):
            problems.append(("unconfirmed_row_quotes_a_figure", name))
    return problems


def build_reference(rows: list, anchors: list) -> str:
    """A platform reference written the way the shipped one is, from rows and anchors given at test time."""
    block = "\n".join("  - " + "\n    ".join(f"{k}: {v}" for k, v in anchor.items()) for anchor in anchors)
    head = "| Platform | Text limit of one post | Status | Read on | Re-check by | Source | Anchor |\n|---|---|---|---|---|---|---|\n"
    return ("# Platform formats\n\n<!-- FRESHNESS:v1\nvolatility: high\nanchors:\n" + block + "\n-->\n\n## Platforms\n\n"
            + head + "\n".join("| " + " | ".join(row) + " |" for row in rows) + "\n")


GOOD_ANCHOR = {"kind": "external_fact", "subject": "sample-net", "source_url": "https://example.invalid/limits",
               "verified_on": "2026-10-12", "review_by": "2027-01-12", "claim": '"A post holds 400 characters."'}
GOOD_ROW = ["Sample Net", "400 characters", "Confirmed", "2026-10-12", "2027-01-12",
            "[Sample Net help](https://example.invalid/limits)", "`sample-net`"]


class TheSocialFamily(unittest.TestCase):

    def test_ts_soc_01_the_social_family_resolves_to_social_post(self) -> None:
        index = skill_resolve.build_index(SKILLS)
        result = skill_resolve.resolve(["family:social"], index, set())
        self.assertEqual((list(result["resolved"]), list(result["unresolved"])), (["social-post"], []))

    def test_ts_soc_01_the_resolver_command_exits_zero_on_the_repository_tree(self) -> None:
        done = subprocess.run([sys.executable, str(SKILLS / "_meta" / "skill_resolve.py"), "--skills-root", str(SKILLS),
                               "family:social", "social-post"], capture_output=True, text=True, encoding="utf-8",
                              timeout=120, check=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("family:social -> social-post", done.stdout)

    def test_the_family_has_one_member_and_it_is_declared_in_the_frontmatter(self) -> None:
        meta = frontmatter(ENTRY.read_text(encoding="utf-8"))
        self.assertEqual((meta["name"], meta["family"]), ("social-post", "social"))
        declared = [p.parent.name for p in SKILLS.glob("*/SKILL.md")
                    if frontmatter(p.read_text(encoding="utf-8")).get("family") == "social"]
        self.assertEqual(declared, ["social-post"])

    def test_the_description_opens_with_the_subject_and_fits_the_listing(self) -> None:
        description = frontmatter(ENTRY.read_text(encoding="utf-8"))["description"]
        self.assertTrue(description.startswith("Social media post"), description)
        self.assertNotRegex(description, r"^(Use|This skill|When)\b")
        self.assertIn("Use when", description)
        self.assertLessEqual(len(description), 250)

    def test_the_skill_passes_the_skill_audit_and_the_frontmatter_lint(self) -> None:
        for tool, argv in (("skill_audit.py", ["check", "--tree", "--repo", str(_TREE), str(ENTRY)]),
                           ("frontmatter_lint.py", ["check", str(ENTRY)])):
            done = subprocess.run([sys.executable, str(SKILLS / "_meta" / tool), *argv], capture_output=True, text=True,
                                  encoding="utf-8", timeout=120, check=False, cwd=str(_TREE))
            self.assertEqual(done.returncode, 0, tool + ": " + done.stdout + done.stderr)
            self.assertNotIn("SA-E", done.stdout)


class PlatformRowsAreDated(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = FORMATS.read_text(encoding="utf-8")
        cls.rows = platform_rows(cls.text)

    def test_ts_soc_02_every_platform_row_carries_a_dated_freshness_anchor(self) -> None:
        self.assertGreaterEqual(len(self.rows), 6)
        self.assertEqual(anchor_problems(self.text), [])
        anchors = anchors_of(self.text)
        for row in self.rows:
            self.assertIn(row["Anchor"].strip("`"), anchors, row["Platform"])

    def test_ts_soc_02_the_block_is_one_the_freshness_tooling_reads_without_a_warning(self) -> None:
        bodies = freshness.extract_blocks(self.text)
        self.assertEqual(len(bodies), 1)
        self.assertEqual(freshness.lint_block(freshness.parse_freshness_yaml(bodies[0])), [])
        self.assertEqual(len(freshness.parse_file(FORMATS)[0]["anchors"]), len(self.rows))

    def test_ts_soc_02_a_row_with_no_anchor_or_no_date_is_caught(self) -> None:
        self.assertEqual(anchor_problems(build_reference([GOOD_ROW], [GOOD_ANCHOR])), [])
        other = dict(GOOD_ANCHOR, subject="another-net")
        self.assertEqual(anchor_problems(build_reference([GOOD_ROW], [other])), [("row_has_no_anchor", "Sample Net")])
        undated = {k: v for k, v in GOOD_ANCHOR.items() if k != "review_by"}
        self.assertIn(("anchor_has_no_review_date", "Sample Net"), anchor_problems(build_reference([GOOD_ROW], [undated])))
        unread = {k: v for k, v in GOOD_ANCHOR.items() if k != "verified_on"}
        self.assertIn(("confirmed_row_has_no_read_date", "Sample Net"), anchor_problems(build_reference([GOOD_ROW], [unread])))
        unsourced = dict(GOOD_ANCHOR, source_url="https://example.invalid/elsewhere")
        self.assertIn(("confirmed_row_has_no_source", "Sample Net"), anchor_problems(build_reference([GOOD_ROW], [unsourced])))
        self.assertEqual(anchor_problems("# A reference with no table\n"), [("no_platform_table", "")])

    def test_a_row_that_is_not_confirmed_quotes_no_figure(self) -> None:
        review = {"kind": "date_review", "subject": "sample-net", "review_by": '"2027-01-12"'}
        remembered = ["Sample Net", "about 60,000 characters", "Not confirmed", "2026-10-12", "2027-01-12", "none", "`sample-net`"]
        self.assertEqual(anchor_problems(build_reference([remembered], [review])),
                         [("unconfirmed_row_quotes_a_figure", "Sample Net")])
        silent = remembered[:1] + ["no figure given"] + remembered[2:]
        self.assertEqual(anchor_problems(build_reference([silent], [review])), [])
        unconfirmed = [row for row in self.rows if row["Status"] == "Not confirmed"]
        self.assertTrue(unconfirmed)                          # the shipped file says so where it could not confirm
        for row in unconfirmed:
            self.assertNotRegex(row["Text limit of one post"], r"\d", row["Platform"])

    def test_every_platform_has_its_own_section_and_every_fact_a_status(self) -> None:
        for row in self.rows:
            section = re.search(rf"^## {re.escape(row['Platform'])}\s*$(.*?)(?=^## |\Z)", self.text, re.M | re.S)
            self.assertIsNotNone(section, row["Platform"])
            facts = [line for line in section.group(1).splitlines() if line.startswith("| ")][1:]
            self.assertTrue(facts, row["Platform"])
            for line in facts:
                self.assertRegex(line, r"\| (Confirmed( \([a-z]+\))?|Not confirmed) \|$", line)
            if row["Status"] == "Confirmed":
                self.assertIn(anchors_of(self.text)[row["Anchor"].strip("`")]["source_url"], section.group(1))

    def test_the_reference_says_how_a_row_is_re_checked_and_what_no_platform_documents(self) -> None:
        for words in ("## Re-checking a row", "## What no platform documents", "Not confirmed", "on the date in the row",
                      "never moves to Confirmed on a figure from a third party"):
            self.assertIn(words, self.text)


class ReadByBothSchools(unittest.TestCase):

    def test_neither_file_holds_a_school_word_or_takes_a_side_on_an_axis(self) -> None:
        for path in (ENTRY, FORMATS):
            text = path.read_text(encoding="utf-8")
            for word in SCHOOL_WORDS:
                self.assertNotRegex(text.lower(), rf"\b{re.escape(word)}\b", f"{path.name}: {word}")
            with self.assertRaises(studio_axes.AxisError):
                studio_axes.axis_table(text)
            for _, values in studio_axes.COPY_AXES:           # naming an axis is fine; choosing its value is the school's
                for value in values:
                    self.assertNotIn(f"`{value}`", text, f"{path.name}: {value}")

    def test_the_platform_reference_carries_no_rule_about_how_a_post_sounds(self) -> None:
        text = FORMATS.read_text(encoding="utf-8").lower()
        for word in VOICE_WORDS:
            self.assertNotRegex(text, rf"\b{re.escape(word)}\b", word)
        self.assertIn("both schools", text)

    def test_the_entry_file_leaves_the_opening_and_the_proof_place_to_the_school(self) -> None:
        text = ENTRY.read_text(encoding="utf-8")
        for words in ("the school file sets it", "the school decides between these places", "`opening` axis",
                      "`proof-placement` axis"):
            self.assertIn(words, text)


class EntryFile(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = ENTRY.read_text(encoding="utf-8")

    def test_it_says_what_a_post_brief_holds(self) -> None:
        profile, _ = studio.load_profile("social-post")
        for field in profile["brief"]["required"]:
            self.assertIn(f"| `{field}` |", self.text)
        self.assertEqual(profile["brief"]["required"], ["platform", "reader", "action", "proof"])

    def test_it_names_the_reference_the_placeholder_the_link_slot_and_the_bands(self) -> None:
        for words in ("references/platform-formats.md", "[FACT NEEDED: what is missing]", "[LINK: ", "| `brief` |",
                      "| `standard` |", "| `full` |", "## The hand-over for a post", "## The file a writer hands in",
                      "link-placement:", "# Post", "never posts"):
            self.assertIn(words, self.text)

    def test_it_quotes_no_platform_limit_itself(self) -> None:
        body = self.text.split("---", 2)[2]
        for figure in re.findall(r"\b\d[\d,]{2,}\b", body):  # the limits live in the dated reference only
            self.fail(f"a figure in the entry file: {figure}")


class Fixtures(unittest.TestCase):

    def test_the_manifest_hashes_match_the_files(self) -> None:
        manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
        component = manifest["components"]["social-post"]
        listed = [f for side in ("inputs", "outputs") for item in component[side].values() for f in item["fixtures"]]
        self.assertEqual(sorted(Path(f["path"]).name for f in listed), ["post-brief-sample.json", "post-doctrine-sample.md"])
        for entry in listed:
            digest = hashlib.sha256((_TREE / entry["path"]).read_bytes()).hexdigest()
            self.assertEqual(entry["hash"], "sha256:" + digest, entry["path"])

    def test_the_brief_fixture_is_a_brief_the_social_profile_takes(self) -> None:
        profile, _ = studio.load_profile("social-post")
        brief = studio.load_brief(FIX / "post-brief-sample.json", profile)
        self.assertEqual([key for key in profile["brief"]["required"] if key in brief], profile["brief"]["required"])

    def test_the_doctrine_fixture_is_the_two_files_of_this_skill_as_a_brief_inlines_them(self) -> None:
        text = (FIX / "post-doctrine-sample.md").read_text(encoding="utf-8")
        blocks = re.findall(r"<!-- doctrine:start file=(\S+) sha256=[0-9a-f]{64} -->\n(.*?)\n<!-- doctrine:end file=\1 -->",
                            text, re.S)
        self.assertEqual([name for name, _ in blocks], ["social-post/SKILL.md", "social-post/references/platform-formats.md"])
        for (_, sample), path in zip(blocks, (ENTRY, FORMATS)):
            live = path.read_text(encoding="utf-8")
            for heading in re.findall(r"^## .+$", sample, re.M):
                self.assertIn(heading, live, f"{path.name}: the sample holds a heading the file no longer has")


if __name__ == "__main__":
    unittest.main()
