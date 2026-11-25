#!/usr/bin/env python3
"""test_pattern_probe.py -- #352: the voice pattern probe of human-voice-writing.

Design docs/plans/2026-10-12-352-creative-studio-design.md, "Truth pack" (the probe paragraph), DW-6:
  TS-PRB-01   an English sample yields category and location rows and no score field anywhere
  TS-PRB-02   a non-English sample yields not_run: language
  and: the exit code is 0 whenever the probe ran, on a text full of hits as on a clean one; a row
  holds a category, a line, a heading and a paragraph number and nothing else; paragraphs count as
  the studio's claim check counts them; one focal word alone is not reported; the attribution names
  a licence, a commit and an intake verdict id and says nothing was copied; the skill says the probe
  is never a target, below its own rule against detector-gaming, and passes the skill audit and the
  frontmatter lint; the fixtures are what the manifest says they are.

Odd texts (another language, an empty file, a draft of nothing but hits) are built here at test time.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SKILL = Path(__file__).resolve().parent.parent
_TREE = _SKILL.parent.parent
SKILLS = _TREE / "skills"
FIX = Path(__file__).resolve().parent / "fixtures"
PROBE = _SKILL / "scripts" / "pattern_probe.py"
ENTRY = _SKILL / "SKILL.md"
ATTRIBUTION = _SKILL / "references" / "ATTRIBUTION.md"
sys.path.insert(0, str(_SKILL / "scripts"))

import pattern_probe  # noqa: E402

SAMPLE = (FIX / "text-sample.md").read_text(encoding="utf-8")
#: A key that would make the report a grade. None may appear at any depth.
GRADE_KEYS = re.compile(r"score|total|count|grade|rating|percent|pass|fail|verdict|result|sum|density|rate", re.I)
ROW_KEYS = {"category", "line", "heading", "paragraph"}
REPORT_KEYS = {"schema_version", "status", "not_run", "rows", "truncated", "categories", "reading"}
GERMAN = ("Der Stapellauf dauerte sechs Stunden. Niemand konnte sagen, warum das so war. Ein Ingenieur hat "
          "jeden Schritt gemessen und fand die Ursache im Schreiben der Zeilen.\n")
HITS = ("In today's fast-paced world, we delve into a robust and seamless tapestry.\n\n"
        "It's not a tool, it's a testament. It is not only pivotal but also holistic \u2014 truly \u2014 and vital.\n\n"
        "In conclusion, it could potentially help. The result? Pure magic.\n") * 40


def run_probe(*argv: str, stdin: str = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROBE), *argv], input=stdin, capture_output=True, text=True,
                          encoding="utf-8", timeout=120, check=False)


def keys_of(value) -> list:
    """Every key at every depth of a JSON value."""
    if isinstance(value, dict):
        return list(value) + [key for inner in value.values() for key in keys_of(inner)]
    if isinstance(value, list):
        return [key for inner in value for key in keys_of(inner)]
    return []


def numbers_of(value, path: str = "") -> list:
    """(path, number) for every number in a JSON value; booleans are not numbers here."""
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [(path, value)]
    if isinstance(value, dict):
        return [found for key, inner in value.items() for found in numbers_of(inner, f"{path}.{key}")]
    if isinstance(value, list):
        return [found for inner in value for found in numbers_of(inner, f"{path}[]")]
    return []


class EnglishSample(unittest.TestCase):
    """TS-PRB-01."""

    def test_ts_prb_01_the_sample_yields_category_and_location_rows(self) -> None:
        report = pattern_probe.probe(SAMPLE)
        self.assertEqual((report["status"], report["not_run"]), ("ran", None))
        self.assertGreaterEqual(len(report["rows"]), 5)
        for row in report["rows"]:
            self.assertEqual(set(row), ROW_KEYS)
            self.assertIn(row["category"], pattern_probe.CATEGORIES)
            self.assertIs(type(row["line"]), int)
            self.assertIs(type(row["paragraph"]), int)
            self.assertGreaterEqual(row["paragraph"], 1)
        seen = {(row["category"], row["line"], row["heading"], row["paragraph"]) for row in report["rows"]}
        self.assertIn(("stock-opener", 5, "", 1), seen)
        self.assertIn(("focal-word-cluster", 5, "", 1), seen)
        self.assertIn(("inverted-contrast", 9, "What changed", 1), seen)
        self.assertIn(("not-only-but", 9, "What changed", 1), seen)
        self.assertIn(("bold-lead-bullets", 17, "What it means", 2), seen)
        self.assertIn(("stock-closer", 21, "What it means", 3), seen)

    def test_ts_prb_01_no_score_field_anywhere_in_the_output(self) -> None:
        for text in (SAMPLE, HITS, GERMAN, ""):
            report = pattern_probe.probe(text)
            self.assertEqual(set(report), REPORT_KEYS)
            self.assertEqual([key for key in keys_of({k: v for k, v in report.items() if k != "categories"})
                              if GRADE_KEYS.search(key)], [])
            # The only numbers of a report are where a row is.
            self.assertEqual({path for path, _ in numbers_of(report)} - {".rows[].line", ".rows[].paragraph"}, set())
        printed = run_probe(str(FIX / "text-sample.md")).stdout
        self.assertNotRegex(printed, r"\d+\s*/\s*\d+|\bscore\b(?! *:)|\d+ (rows|hits|patterns|issues)|%")
        self.assertIn("not a score", printed)

    def test_the_report_fixture_is_what_the_probe_prints_for_the_sample(self) -> None:
        done = run_probe(str(FIX / "text-sample.md"), "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout),
                         json.loads((FIX / "pattern-report-sample.json").read_text(encoding="utf-8")))
        self.assertEqual(json.loads(done.stdout), pattern_probe.probe(SAMPLE))

    def test_rows_come_in_file_order_and_each_place_is_listed_once_per_category(self) -> None:
        rows = pattern_probe.probe(HITS)["rows"]
        places = [(row["line"], row["category"]) for row in rows]
        self.assertEqual(places, sorted(set(places)))

    def test_one_focal_word_alone_is_ordinary_and_is_not_reported(self) -> None:
        alone = "The bridge is robust. It was built in a year by a small crew that knew the river well.\n"
        self.assertEqual(pattern_probe.probe(alone)["rows"], [])
        pair = "The bridge is robust and its design is pivotal to the town that it was built for.\n"
        self.assertEqual([row["category"] for row in pattern_probe.probe(pair)["rows"]], ["focal-word-cluster"])

    def test_one_list_of_three_alone_is_not_reported(self) -> None:
        once = "We packed bread, cheese and apples for the walk that we had planned for the day.\n"
        self.assertEqual(pattern_probe.probe(once)["rows"], [])

    def test_sentences_of_one_length_in_a_row_are_a_rhythm_row(self) -> None:
        even = " ".join(["The team moved the nightly batch to the new host."] * 4) + "\n"
        self.assertIn("even-rhythm", [row["category"] for row in pattern_probe.probe(even)["rows"]])
        varied = ("The team moved the nightly batch to the new host. It took a week. Nobody had expected the old "
                  "scheduler to hold on to its locks for as long as it did. Then it was done.\n")
        self.assertNotIn("even-rhythm", [row["category"] for row in pattern_probe.probe(varied)["rows"]])


class WhereARowPoints(unittest.TestCase):

    def test_the_front_block_code_and_comments_are_not_read_and_lines_are_the_files_own(self) -> None:
        text = ("---\ntitle: In conclusion, a robust and pivotal title\n---\n\n"
                "```\nIn conclusion, this is code that is not prose and it is not read.\n```\n\n"
                "<!-- In conclusion, this is\na comment -->\n\n"
                "# The part\n\nThe work is done and the team has moved on.\n\nIn conclusion, it is the end of the note.\n")
        rows = pattern_probe.probe(text)["rows"]
        self.assertEqual(rows, [{"category": "stock-closer", "line": 16, "heading": "The part", "paragraph": 2}])
        self.assertEqual(text.splitlines()[15], "In conclusion, it is the end of the note.")

    def test_paragraphs_count_from_one_under_each_heading_and_lists_and_tables_count(self) -> None:
        text = ("Before the first heading of the note.\n\n# One\n\nA paragraph that is the first.\n\n"
                "- an item of the list\n- another item\n\n| a | b |\n|---|---|\n| c | d |\n\n"
                "In conclusion, this is the fourth block of the section.\n\n## Two\n\nIn summary, it is the first here.\n")
        rows = pattern_probe.probe(text)["rows"]
        self.assertEqual([(row["heading"], row["paragraph"]) for row in rows], [("One", 4), ("Two", 1)])
        blocks = pattern_probe.blocks_of(text)
        self.assertEqual([(b["heading"], b["paragraph"], b["line"]) for b in blocks],
                         [("", 1, 1), ("One", 1, 5), ("One", 2, 7), ("One", 3, 10), ("One", 4, 14), ("Two", 1, 18)])

    def test_a_heading_is_carried_as_printable_text_of_bounded_length(self) -> None:
        text = "# " + "A long heading " * 20 + "\x07\n\nIn conclusion, the heading above is long and it has a bell.\n"
        heading = pattern_probe.probe(text)["rows"][0]["heading"]
        self.assertLessEqual(len(heading), pattern_probe.MAX_HEADING)
        self.assertTrue(heading.isprintable())

    def test_a_report_is_cut_short_and_says_so(self) -> None:
        text = "".join(f"In conclusion, the note number {n} is done and it is over.\n\n" for n in range(400))
        report = pattern_probe.probe(text)
        self.assertEqual((len(report["rows"]), report["truncated"]), (pattern_probe.MAX_ROWS, True))
        self.assertIn("cut short", "\n".join(pattern_probe.report_lines(report)))


class OtherLanguages(unittest.TestCase):
    """TS-PRB-02."""

    def test_ts_prb_02_a_non_english_sample_yields_not_run_language(self) -> None:
        samples = {
            "german": GERMAN,
            "french": "Le traitement de nuit durait six heures. Personne ne savait pourquoi. Une ing\u00e9nieure a "
                      "mesur\u00e9 chaque \u00e9tape pendant deux semaines.\n",
            "spanish": "El proceso nocturno duraba seis horas. Nadie sab\u00eda por qu\u00e9. Una ingeniera midi\u00f3 cada "
                       "paso durante dos semanas.\n",
            "greek": "\u0397 \u03bd\u03c5\u03c7\u03c4\u03b5\u03c1\u03b9\u03bd\u03ae \u03b5\u03c1\u03b3\u03b1\u03c3\u03af\u03b1 "
                     "\u03b4\u03b9\u03b1\u03c1\u03ba\u03bf\u03cd\u03c3\u03b5 \u03ad\u03be\u03b9 \u03ce\u03c1\u03b5\u03c2.\n",
            # English pattern words inside a text that is not English are still not read.
            "german with a stock phrase": GERMAN + "In conclusion: robust, pivotal, seamless.\n" + GERMAN * 3,
        }
        for name, text in samples.items():
            with self.subTest(name):
                report = pattern_probe.probe(text)
                self.assertEqual((report["status"], report["not_run"], report["rows"]), ("not_run", "language", []))
        done = run_probe("-", stdin=GERMAN)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "pattern probe: not_run: language"))
        printed = json.loads(run_probe("-", "--json", stdin=GERMAN).stdout)
        self.assertEqual((printed["not_run"], printed["rows"]), ("language", []))

    def test_english_is_read_whether_it_is_long_or_a_single_cv_line(self) -> None:
        for text in (SAMPLE, "# A person\n\nCut the nightly batch from six hours to two.\n",
                     "Led the move of forty services to the new platform.\n"):
            self.assertEqual(pattern_probe.probe(text)["status"], "ran")
        self.assertTrue(pattern_probe.is_english("The caf\u00e9 was na\u00efve about its r\u00e9sum\u00e9 and it was closed."))

    def test_a_text_with_no_words_is_not_run_empty(self) -> None:
        for text in ("", "\n\n", "---\ntitle: only a front block\n---\n", "```\ncode only\n```\n", "12 34 !!\n"):
            report = pattern_probe.probe(text)
            self.assertEqual((report["status"], report["not_run"], report["rows"]), ("not_run", "empty", []))


class ExitCode(unittest.TestCase):

    def test_the_exit_code_is_zero_whenever_the_probe_ran(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pattern-probe-") as tmp:
            texts = {"hits.md": HITS, "clean.md": "The batch ran for six hours. Nobody could say why.\n",
                     "german.md": GERMAN, "empty.md": "", "bytes.md": None}
            for name, text in texts.items():
                path = Path(tmp) / name
                path.write_bytes(b"\xff\xfe not utf-8 \x80 but it is the text that was given\n" if text is None
                                 else text.encode("utf-8"))
                for flags in ((), ("--json",)):
                    with self.subTest(name=name, flags=flags):
                        done = run_probe(str(path), *flags)
                        self.assertEqual(done.returncode, 0, done.stderr)
            full = json.loads(run_probe(str(Path(tmp) / "hits.md"), "--json").stdout)
            self.assertEqual((full["status"], full["truncated"], len(full["rows"])), ("ran", True, pattern_probe.MAX_ROWS))
            self.assertGreaterEqual(len({row["category"] for row in full["rows"]}), 6)

    def test_only_an_input_that_cannot_be_read_is_not_zero(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pattern-probe-") as tmp:
            done = run_probe(str(Path(tmp) / "absent.md"))
            self.assertEqual((done.returncode, done.stdout), (2, ""))
            self.assertIn("cannot read the draft", done.stderr)
            self.assertEqual(run_probe(tmp).returncode, 2)       # a directory is no draft

    def test_the_probe_is_standard_library_only_and_writes_no_file(self) -> None:
        source = PROBE.read_text(encoding="utf-8")
        imports = set(re.findall(r"^(?:from|import) ([a-z_]+)", source, re.M))
        self.assertEqual(imports, {"__future__", "argparse", "json", "re", "sys", "pathlib", "typing"})
        self.assertNotRegex(source, r"\bopen\(|write_text|write_bytes|subprocess|socket|urllib|os\.")


class Attribution(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = ATTRIBUTION.read_text(encoding="utf-8")

    def test_the_attribution_names_a_licence_a_commit_and_a_verdict_id(self) -> None:
        self.assertIn("MIT License", self.text)
        self.assertIn("Copyright (c) 2026 Jack Roberts", self.text)
        self.assertRegex(self.text, r"\| Commit looked at \| `3fc9787d9337b57c599a80afbefbbb3be5a8eb0b` ")
        self.assertRegex(self.text, r"\| Intake verdict id \| `q\d{8}T\d{6}Z-[0-9a-f]{8}` \|")
        self.assertRegex(self.text, r"\| Verdict \| \*\*caution\*\*, not signed by a person \|")

    def test_it_says_truthfully_which_route_was_taken(self) -> None:
        flat = " ".join(self.text.split())
        self.assertIn("this library's OWN code", flat)
        self.assertIn("No code, no pattern, no word list and no passage of that project is in this library", flat)
        self.assertIn("nothing of it was installed, imported or run", flat)
        self.assertIn("**The second route was taken.**", flat)
        self.assertIn("a caution that no person has signed, so nothing of the source was adopted", flat)
        self.assertIn("that decision is the user's", flat)
        self.assertNotRegex(flat, r"(?i)\badapted from\b")

    def test_every_category_of_the_probe_is_traced_to_where_it_comes_from(self) -> None:
        for category in pattern_probe.CATEGORIES:
            self.assertIn(f"`{category}`", self.text)
        self.assertIn("career-coach/references/ai-tells-catalog.md", self.text)
        self.assertTrue((SKILLS / "career-coach" / "references" / "ai-tells-catalog.md").is_file())

    def test_it_states_what_differs_by_design(self) -> None:
        flat = " ".join(self.text.split())
        for phrase in ("it holds no score, no total and no pass or fail", "its exit code is 0 whenever it ran",
                       "`not_run: language`"):
            self.assertIn(phrase, flat)


class TheSkill(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = ENTRY.read_text(encoding="utf-8")

    def test_the_skill_says_the_probe_is_never_a_target_to_optimise_against(self) -> None:
        section = re.search(r"^## The Pattern Probe\s*$(.*?)(?=^## )", self.text, re.M | re.S).group(1)
        self.assertIn("never a target to optimise against", section)
        self.assertIn("HARD RULE 2 covers the probe", section)
        self.assertIn("no score, no total and no pass or fail", section)
        self.assertIn("exit code is 0 whenever it ran", section)
        self.assertIn("`not_run: language`", section)
        self.assertIn("references/ATTRIBUTION.md", section)
        for category in pattern_probe.CATEGORIES:
            self.assertIn(f"`{category}`", section)

    def test_the_rule_against_detector_gaming_stands_above_the_probe(self) -> None:
        rule = self.text.index("**No detector-gaming.**")
        self.assertIn("never optimize against a detector score", self.text)
        self.assertLess(self.text.index("## HARD RULES"), rule)
        self.assertLess(rule, self.text.index("## The Pattern Probe"))

    def test_the_skill_still_passes_the_skill_audit_and_the_frontmatter_lint(self) -> None:
        for tool, argv in (("skill_audit.py", ["check", "--tree", "--repo", str(_TREE), str(ENTRY)]),
                           ("frontmatter_lint.py", ["check", str(ENTRY)])):
            done = subprocess.run([sys.executable, str(SKILLS / "_meta" / tool), *argv], capture_output=True,
                                  text=True, encoding="utf-8", timeout=120, check=False)
            self.assertEqual(done.returncode, 0, f"{tool}\n{done.stdout}\n{done.stderr}")


class Fixtures(unittest.TestCase):

    def test_the_probe_manifest_hashes_match_the_files(self) -> None:
        manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
        component = manifest["components"]["voice-probe"]
        entries = [entry for side in ("inputs", "outputs") for value in component[side].values()
                   for entry in value["fixtures"]]
        self.assertEqual(sorted(Path(entry["path"]).name for entry in entries),
                         ["pattern-report-sample.json", "text-sample.md"])
        for entry in entries:
            digest = hashlib.sha256((_TREE / entry["path"]).read_bytes()).hexdigest()
            self.assertEqual(entry["hash"], f"sha256:{digest}", entry["path"])

    def test_the_sample_names_no_real_business_product_or_price(self) -> None:
        self.assertNotRegex(SAMPLE, r"[\u00a3$\u20ac]\s?\d|https?://|@\w+\.")


if __name__ == "__main__":
    unittest.main()
