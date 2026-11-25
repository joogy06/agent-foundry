#!/usr/bin/env python3
"""Tests for review_by_lint.py and the check-deadlines honesty line (#281).

DW-1  every real dated prose REVIEW-BY marker reaches freshness.build_index's by_deadline
      (rates-2026-27.md named explicitly; the tree test covers the rest).
DW-2  the lint fails a prose-only marker and a mismatched date, passes a matching pair,
      ignores an undated mention, normalizes YYYY-MM -- known-positive / known-negative, in
      the precedent of tests/secrets-scan/test_every_rule_fires.py: every rule code ships a
      sample that fires it.
DW-4  check-deadlines distinguishes "none registered" from "N registered, none due".

Reads the repo tree; writes only under a TemporaryDirectory.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_META = Path(__file__).resolve().parent.parent
REPO = _META.parents[1]
LINT = _META / "review_by_lint.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fr = _load("freshness", _META / "freshness.py")
rb = _load("review_by_lint", LINT)


def _block(date: str, kind: str = "date_review", key: str = "review_by") -> str:
    return (f"<!-- FRESHNESS:v1\nanchors:\n  - kind: {kind}\n    subject: thing\n"
            f"    {key}: \"{date}\"\n-->\n")


def _lint_text(text: str, name: str = "doc.md") -> list[tuple[str, int, str]]:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return rb.lint_file(p)


def _codes(findings) -> list[str]:
    return [f[0] for f in findings]


# One known-positive per rule. A rule with no sample here fails test_every_rule_has_a_sample.
POSITIVE = {
    "E1": "# Doc\n\n<!-- REVIEW-BY: 2027-01-31 -->\nbody\n",
    "E2": "# Doc\n\n" + _block("2027-02-28") + "<!-- REVIEW-BY: 2027-01-31 -->\n",
    "E3": "# Doc\n\n<!-- REVIEW-BY: 2027-02-30 -->\n",
    "E4": "# Doc\n\n<!-- FRESHNESS:v1\nanchors:\n  stray indented line\n-->\n"
          "<!-- REVIEW-BY: 2027-01-31 -->\n",
}


class TestEveryRuleFires(unittest.TestCase):
    def test_every_error_rule_has_a_sample(self):
        # E5 (unreadable) and E6 (lint crash) cannot be expressed as text; their
        # known-positives are the byte-level and monkeypatched tests below.
        covered = set(POSITIVE) | {"E5", "E6"}
        missing = [c for c in rb.RULES if c.startswith("E") and c not in covered]
        self.assertEqual(missing, [], "every E-rule ships a known-positive sample")

    def test_each_sample_fires_its_rule(self):
        for code, text in POSITIVE.items():
            with self.subTest(code=code):
                self.assertIn(code, _codes(_lint_text(text)))

    def test_e5_undecodable_file_with_review_text_is_an_error(self):
        # m2: a file the lint cannot read might hold a marker -- it cannot pass.
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bin.md"
            p.write_bytes(b"\xff\xfe REVIEW-BY: 2027-01-31\n")
            self.assertEqual(_codes(rb.lint_file(p)), ["E5"])
            p.write_bytes(b"\xff\xfe r\x00e\x00v\x00i\x00e\x00w\x00")   # UTF-16-ish
            self.assertEqual(_codes(rb.lint_file(p)), ["E5"])

    def test_w1_undecodable_file_without_review_text_warns(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bin.md"
            p.write_bytes(b"\xff\xfe nothing to see\n")
            self.assertEqual(_codes(rb.lint_file(p)), ["W1"])

    def test_e6_a_crash_on_one_file_is_an_error_and_hides_nothing(self):
        # M6: one file that breaks the lint must not abort the batch or pass.
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "skills").mkdir()
            boom = Path(td) / "skills" / "boom.md"
            boom.write_text("CRASH\n", encoding="utf-8")
            bad = Path(td) / "skills" / "bad.md"
            bad.write_text(POSITIVE["E1"], encoding="utf-8")
            real = rb.find_markers

            def flaky(text):
                if "CRASH" in text:
                    raise RuntimeError("boom")
                return real(text)
            rb.find_markers = flaky
            try:
                self.assertEqual(_codes(rb.lint_file(boom)), ["E6"])
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = rb.main(["check", "--repo", td, str(boom), str(bad)])
            finally:
                rb.find_markers = real
            self.assertEqual(rc, 1)
            self.assertIn("RB-E6", buf.getvalue())
            self.assertIn("RB-E1", buf.getvalue())


class TestKnownPositives(unittest.TestCase):
    def test_prose_only_marker_fails(self):
        f = _lint_text("# X\n\n<!-- REVIEW-BY: 2027-01-31 -->\n")
        self.assertEqual(_codes(f), ["E1"])
        self.assertEqual(f[0][1], 3, "the finding names the marker's line")
        self.assertIn("2027-01-31", f[0][2])

    def test_block_with_different_date_fails(self):
        f = _lint_text("# X\n\n" + _block("2027-01-30") + "<!-- REVIEW-BY: 2027-01-31 -->\n")
        self.assertEqual(_codes(f), ["E2"])

    def test_bold_and_bare_forms_are_markers(self):
        for line in ("**REVIEW-BY: 2027-04-06** . verified 2026-07-28",
                     "REVIEW-BY: 2027-04 (purge point)",
                     "REVIEW_BY 2027-04-06",
                     "> **REVIEW-BY**: 2027-04-06",
                     "- REVIEW-BY: 2027-04-06"):
            with self.subTest(line=line):
                self.assertEqual(_codes(_lint_text(f"# X\n\n{line}\n")), ["E1"])

    def test_one_finding_per_marker_line(self):
        text = "# X\n\n<!-- REVIEW-BY: 2027-04-06 -->\n**REVIEW-BY: 2027-04-06** . x\n"
        self.assertEqual([f[1] for f in _lint_text(text)], [3, 4])

    def test_block_without_a_deadline_anchor_does_not_count(self):
        tool_only = ("<!-- FRESHNESS:v1\nanchors:\n  - kind: tool_version\n    subject: x\n"
                     "    verified_against: \"1.0\"\n-->\n")
        f = _lint_text("# X\n\n" + tool_only + "\n<!-- REVIEW-BY: 2027-01-31 -->\n")
        self.assertEqual(_codes(f), ["E2"])


class TestKnownNegatives(unittest.TestCase):
    def test_matching_pair_passes(self):
        text = "# X\n\n" + _block("2027-01-31") + "<!-- REVIEW-BY: 2027-01-31 -->\n"
        self.assertEqual(_lint_text(text), [])

    def test_retirement_and_external_fact_anchors_also_match(self):
        for kind, key in (("retirement", "retire_on"), ("external_fact", "review_by")):
            with self.subTest(kind=kind):
                text = "# X\n\n" + _block("2027-01-31", kind, key) + "REVIEW-BY: 2027-01-31\n"
                self.assertEqual(_lint_text(text), [])

    def test_undated_mention_is_not_a_marker(self):
        text = ("# X\n\nA reference file with a `REVIEW_BY` date works everywhere.\n\n"
                "REVIEW_BY dates rot silently.\n\n- Keeping facts without a `REVIEW_BY`\n")
        self.assertEqual(_lint_text(text), [])

    def test_mention_passes_only_with_the_explicit_suppression(self):
        # M1: a mention of ANOTHER file's marker is exempt only when it says so.
        bare = "- `market-snapshot.md` -- the dated home (REVIEW-BY 2027-01)\n"
        self.assertEqual(_codes(_lint_text(bare)), ["E1"], "fail closed: flagged by default")
        self.assertEqual(_lint_text(bare.rstrip("\n") + " " + rb.SUPPRESSION + "\n"), [])

    def test_hard_wrapped_mention_needs_the_suppression_on_its_line(self):
        # skills/_meta/refresh-recipes.md: another file's deadline, wrapped onto a line start.
        text = ("**When:** a dated snapshot is in horizon (e.g. `market-snapshot-2026-06.md`\n"
                "REVIEW-BY 2027-01; the OWASP/NIST freshness anchors).\n")
        self.assertEqual(_codes(_lint_text(text)), ["E1"])
        fixed = text.replace("anchors).\n", "anchors). <!-- review-by: mention -->\n")
        self.assertEqual(_lint_text(fixed), [])

    def test_inline_code_marker_is_a_mention(self):
        text = "# X\n\nWrite `REVIEW-BY: 2027-01-31` next to the block.\n"
        self.assertEqual(_lint_text(text), [])

    def test_code_span_without_the_keyword_does_not_hide_the_date(self):
        text = "# X\n\n**REVIEW-BY**: `2027-04-06`\n"
        self.assertEqual(_codes(_lint_text(text)), ["E1"])

    def test_fenced_example_is_not_a_marker(self):
        text = "# X\n\n```markdown\n<!-- REVIEW-BY: 2027-01-31 -->\n```\n"
        self.assertEqual(_lint_text(text), [])

    def test_fixture_paths_are_exempt(self):
        text = "# X\n\n<!-- REVIEW-BY: 2027-01-31 -->\n"
        rel = Path("tests/fixtures/yellow-deadline/SKILL.md")
        self.assertEqual(rb.lint_bytes(text.encode(), rel), [])
        self.assertTrue(rb.is_exempt(Path("skills/_meta/tests/fixtures/x/SKILL.md")))
        self.assertFalse(rb.is_exempt(Path("skills/_meta/tests/test_x.md")))

    def test_marker_date_inside_the_block_is_not_a_second_marker(self):
        text = ("# X\n\n<!-- FRESHNESS:v1\nanchors:\n  - kind: date_review\n"
                "REVIEW-BY: 2031-01-01\n-->\n")
        self.assertEqual(rb.find_markers(text), [])


class TestNormalize(unittest.TestCase):
    def test_year_month_is_last_day(self):
        self.assertEqual(rb.normalize("2027-01"), "2027-01-31")
        self.assertEqual(rb.normalize("2028-02"), "2028-02-29")
        self.assertEqual(rb.normalize("2027-04"), "2027-04-30")

    def test_full_date_is_itself_and_invalid_is_none(self):
        self.assertEqual(rb.normalize("2027-04-06"), "2027-04-06")
        self.assertIsNone(rb.normalize("2027-13"))
        self.assertIsNone(rb.normalize("2027-02-30"))
        self.assertIsNone(rb.normalize("2027-1-5"))

    def test_year_month_marker_needs_the_normalized_block_date(self):
        ok = "# X\n\n" + _block("2027-01-31") + "REVIEW-BY: 2027-01 (purge point)\n"
        self.assertEqual(_lint_text(ok), [])
        raw = "# X\n\n" + _block("2027-01") + "REVIEW-BY: 2027-01 (purge point)\n"
        self.assertEqual(_codes(_lint_text(raw)), ["E2"],
                         "a bare YYYY-MM anchor is harvested as the 1st, so it must not match")


class TestCli(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(LINT), *args],
                              capture_output=True, text=True, encoding="utf-8")

    def test_check_exit_codes_and_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "skills").mkdir()
            bad = Path(td) / "skills" / "bad.md"
            bad.write_text(POSITIVE["E1"], encoding="utf-8")
            good = Path(td) / "skills" / "good.md"
            good.write_text("# fine\n", encoding="utf-8")
            r = self._run("check", "--repo", td, str(bad), str(good))
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertRegex(r.stdout, r"(?m)^RB-E1 ")
            r = self._run("check", "--repo", td, str(good), "skills/gone.md", "x.py")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_lint_root_mode(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.md").write_text(POSITIVE["E1"], encoding="utf-8")
            self.assertEqual(self._run("lint", "--root", td).returncode, 1)
            self.assertEqual(self._run("lint", "--root", str(Path(td) / "nope")).returncode, 2)


# -- fix round 1: fail closed (M1-M4, M6, m4) ------------------------------------

M = "REVIEW-BY: 2027-04-06"
# Built with chr() so this source stays ASCII (portability_lint W003).
NBSP, MIDDOT, EMDASH, BOM = chr(0xA0), chr(0xB7), chr(0x2014), chr(0xFEFF)

# M1: every shape the round-0 block-start rule let escape. Each is (text, marker line).
ESCAPED_SHAPES = {
    "after_sentence": ("Some sentence ends here.\n" + M + "\n", 2),
    "after_frontmatter": ("---\nname: x\n---\n" + M + "\n", 4),
    "after_hr": ("para\n\n***\n" + M + "\n", 4),
    "blockquote_continuation": ("> quoted sentence\n> " + M + "\n", 2),
    "after_list_item": ("- item one\n" + M + "\n", 2),
    "after_details": ("<details>\n" + M + "\n</details>\n", 2),
    "table_cell": ("| Item | Deadline |\n|---|---|\n| rates | " + M + " |\n", 3),
    "table_cell_split": ("| rates | REVIEW-BY | 2027-04-06 |\n", 1),
    "after_bold_label": ("**Deadline:** " + M + "\n", 1),
    "numbered_list": ("1. " + M + "\n", 1),
    "heading": ("## REVIEW-BY 2027-04-06\n", 1),
    "mid_line": ("Verified 2026-07-28 " + MIDDOT + " " + M + "\n", 1),
    "inline_comment_after_text": ("Rates table <!-- " + M + " -->\n", 1),
    "multiline_comment": ("<!--\n" + M + "\n-->\n", 2),
    "wrapped_date": ("the figures are good until REVIEW-BY\n2027-04-06 at the latest\n", 1),
    "nbsp": ("REVIEW-BY:" + NBSP + "2027-04-06\n", 1),
    "nbsp_entity": ("REVIEW-BY:&nbsp;2027-04-06\n", 1),
    "lower_case": ("review by 2027-04-06\n", 1),
    "title_case": ("Review-By: 2027-04-06\n", 1),
    "space_form": ("REVIEW BY 2027-04-06\n", 1),
    "html_bold": ("<b>REVIEW-BY:</b> 2027-04-06\n", 1),
    "em_dash": ("REVIEW-BY " + EMDASH + " 2027-04-06\n", 1),
    "bom_first_line": (BOM + M + "\n", 1),
    # fix round 2 (N2 / m-A): shapes that still escaped round 1.
    "quoted_date": ('REVIEW-BY: "2027-04-06"\n', 1),
    "keyword_then_date_word": ("REVIEW-BY DATE: 2027-04-06\n", 1),
    "title_then_date_word": ("Review-by date: 2027-04-06\n", 1),
    "parenthetical": ("REVIEW-BY (UK rates): 2027-04-06\n", 1),
    "on": ("REVIEW-BY: on 2027-04-06\n", 1),
    "before": ("REVIEW-BY: before 2027-04-06\n", 1),
    "until": ("REVIEW-BY: until 2027-04-06\n", 1),
    "angle_brackets": ("REVIEW-BY: <2027-04-06>\n", 1),
    "keyword_only_code_span": ("`REVIEW-BY:` 2027-04-06\n", 1),
    "hyphen_u2010": ("REVIEW" + chr(0x2010) + "BY: 2027-04-06\n", 1),
    "nb_hyphen_u2011": ("REVIEW" + chr(0x2011) + "BY: 2027-04-06\n", 1),
    "en_dash_keyword": ("REVIEW" + chr(0x2013) + "BY: 2027-04-06\n", 1),
    "nbsp_entity_keyword": ("REVIEW&nbsp;BY: 2027-04-06\n", 1),
    "fullwidth_colon": ("REVIEW-BY" + chr(0xFF1A) + " 2027-04-06\n", 1),
    "struck_old_date": ("REVIEW-BY: ~~2026-01-01~~ 2027-04-06\n", 1),
    "html_struck_old_date": ("REVIEW-BY: <del>2026-01-01</del> 2027-04-06\n", 1),
}


class TestFailClosedShapes(unittest.TestCase):
    def test_every_shape_is_a_marker(self):
        for name, (text, line) in ESCAPED_SHAPES.items():
            with self.subTest(shape=name):
                f = _lint_text(text)
                self.assertEqual(_codes(f), ["E1"], f)
                self.assertEqual(f[0][1], line)

    def test_every_shape_passes_with_the_matching_block(self):
        for name, (text, _line) in ESCAPED_SHAPES.items():
            with self.subTest(shape=name):
                self.assertEqual(_lint_text(text + "\n" + _block("2027-04-06")), [])

    def test_consecutive_markers_each_count(self):
        text = "REVIEW-BY: 2027-04-06\nREVIEW-BY: 2027-05-06\n"
        self.assertEqual([(c, ln) for c, ln, _m in _lint_text(text)], [("E1", 1), ("E1", 2)])
        both = text + _block("2027-04-06")
        self.assertEqual([(c, ln) for c, ln, _m in _lint_text(both)], [("E2", 2)])

    def test_struck_date_is_not_judged(self):
        (mk,) = rb.find_markers("REVIEW-BY: ~~2026-01-01~~ 2027-04-06\n")
        self.assertEqual(mk.date, "2027-04-06", "the LAST, live date")

    def test_iso_date_followed_by_a_word_is_still_a_marker(self):
        self.assertEqual(_codes(_lint_text("review by 2027-04-06 at the latest\n")), ["E1"])
        self.assertEqual(_codes(_lint_text("review by 2027 at the latest.\n")), [])
        self.assertEqual(_codes(_lint_text("REVIEW-BY: 2027.\n")), ["E3"],
                         "a bare year before punctuation is still date-like")

    def test_two_markers_on_one_line_each_count(self):
        text = "| a | REVIEW-BY 2027-04-06 | b | REVIEW-BY 2027-05-06 |\n"
        self.assertEqual(len(rb.find_markers(text)), 2)

    def test_non_markers_stay_quiet(self):
        for text in ("REVIEW_BY dates rot silently.\n",
                     "Ask for a review by the team.\n",
                     "A preview by 2027-01-01 is planned.\n",
                     "The file was reviewed by 2026-01-01.\n",
                     "REVIEW-BY: TBD\n",
                     "review by 2 reviewers\n",
                     "review by marking 5 items\n",
                     # m-C: a bare number, or a numeric date followed by a word, is prose.
                     "Peer review by 1000 users\n",
                     "The review by 2025 McKinsey found it\n",
                     "peer review by\n2000 more people\n",
                     "Code review by 12/10/2027 standards\n",
                     "Code review by 20270406 standards\n"):
            with self.subTest(text=text):
                self.assertEqual(_lint_text(text), [])


class TestNonIsoDates(unittest.TestCase):
    """M2: a date-like token that is not YYYY-MM-DD / YYYY-MM is E3, never ignored."""

    def test_each_non_iso_form_is_e3(self):
        for token in ("2027/04/06", "06 April 2027", "April 2027", "Apr. 6, 2027",
                      "6th April 2027", "2027", "2027-4-6", "20270406", "06/04/2027",
                      "Q2 2027", "0000-01", "2027-13", "2027-02-30"):
            with self.subTest(token=token):
                f = _lint_text(f"REVIEW-BY: {token}\n")
                self.assertEqual(_codes(f), ["E3"], f)
                self.assertIn("YYYY-MM-DD", f[0][2])

    def test_impossible_dates_never_raise(self):
        # M6: `0000-01` used to raise ValueError out of normalize() and abort the batch.
        for raw in ("0000-01", "0000-01-01", "9999-12", "2027-00", "2027-02-29"):
            with self.subTest(raw=raw):
                rb.normalize(raw)          # must not raise
        self.assertIsNone(rb.normalize("0000-01"))

    def test_bad_date_in_one_file_does_not_hide_another(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "agents").mkdir()
            zero = Path(td) / "agents" / "zero.md"
            zero.write_text("REVIEW-BY: 0000-01\n", encoding="utf-8")
            bad = Path(td) / "agents" / "bad.md"
            bad.write_text(POSITIVE["E1"], encoding="utf-8")
            r = subprocess.run([sys.executable, str(LINT), "check", "--repo", td,
                                str(zero), str(bad)],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            self.assertRegex(r.stdout, r"(?m)^RB-E3 .*zero\.md")
            self.assertRegex(r.stdout, r"(?m)^RB-E1 .*bad\.md")


class TestEffectiveDeadline(unittest.TestCase):
    """M3: the lint accepts exactly the date build_index registers."""

    BOTH = ("<!-- FRESHNESS:v1\nanchors:\n  - kind: retirement\n    subject: x\n"
            "    review_by: \"2027-01-31\"\n    retire_on: \"2027-06-30\"\n-->\n")

    def test_review_by_wins_over_retire_on(self):
        self.assertEqual(_lint_text(self.BOTH + "REVIEW-BY: 2027-01-31\n"), [])
        self.assertEqual(_codes(_lint_text(self.BOTH + "REVIEW-BY: 2027-06-30\n")), ["E2"],
                         "retire_on is not registered when review_by is present")

    def test_lint_dates_equal_index_dates(self):
        with tempfile.TemporaryDirectory() as td:
            skills = Path(td) / "skills"
            (skills / "x").mkdir(parents=True)
            p = skills / "x" / "doc.md"
            p.write_text(self.BOTH, encoding="utf-8")
            idx = fr.build_index(skills, Path(td) / "agents", Path(td) / "workflows")
            indexed = {d["date"] for d in idx["by_deadline"]}
            parsed = [fr.parse_freshness_yaml(b) for b in fr.extract_blocks(self.BOTH)]
            self.assertEqual(rb.anchor_dates(parsed), indexed)
            self.assertEqual(indexed, {"2027-01-31"})


class TestFences(unittest.TestCase):
    """M4: CommonMark fences -- same char, >= length, blockquoted, unclosed."""

    def test_tilde_inside_backtick_fence_does_not_toggle(self):
        text = "```\n~~~\n```\n" + M + "\n"
        self.assertEqual([f[1] for f in _lint_text(text)], [4])

    def test_shorter_fence_does_not_close_a_longer_one(self):
        inside = "````markdown\n```\n" + M + "\n```\n````\n"
        self.assertEqual(_lint_text(inside), [], "the marker is inside the 4-tick fence")
        after = "````\n```\n````\n" + M + "\n"
        self.assertEqual([f[1] for f in _lint_text(after)], [4])

    def test_blockquoted_fence_hides_its_example(self):
        self.assertEqual(_lint_text("> ```\n> " + M + "\n> ```\n"), [])

    def test_blockquoted_fence_ends_with_the_blockquote(self):
        # A later bare ``` must not close the blockquote's fence and swallow the marker.
        text = "> ```\n> code\n\n" + M + "\n```\n"
        self.assertEqual([f[1] for f in _lint_text(text)], [4])

    def test_unclosed_fence_does_not_hide_the_rest_of_the_file(self):
        text = "intro\n```\n" + M + "\n"
        self.assertEqual([f[1] for f in _lint_text(text)], [3])

    def test_four_space_indent_is_not_a_fence(self):
        # n-A: CommonMark caps a fence's indent at 3 spaces.
        text = "    ```\n" + M + "\n    ```\n"
        self.assertEqual([f[1] for f in _lint_text(text)], [2])
        self.assertEqual(_lint_text("   ```\n" + M + "\n   ```\n"), [], "3 spaces is a fence")

    def test_many_unclosed_openers_are_linear(self):
        # N7: 20k stray openers took ~97 s when each rescanned to EOF.
        import time
        text = "```a\n" * 20000 + M + "\n"
        t0 = time.monotonic()
        f = rb.lint_bytes(text.encode("utf-8"))
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertEqual([x[1] for x in f], [20001])
        t0 = time.monotonic()
        rb.lint_bytes(("```a\n" * 20000).encode("utf-8"))
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_bom_before_a_first_line_fence(self):
        text = BOM + "```\n" + M + "\n```\n"
        self.assertEqual(_lint_text(text), [])


class TestRepoRelativeExemption(unittest.TestCase):
    """m4: only the repo-relative path can exempt a file."""

    def test_absolute_fixture_path_is_not_exempt(self):
        self.assertFalse(rb.is_exempt(Path("/srv/tests/fixtures/x.md").resolve()))
        self.assertFalse(rb.is_exempt(None))

    def test_checkout_living_under_a_fixtures_dir_is_still_linted(self):
        with tempfile.TemporaryDirectory() as td:
            skills = Path(td) / "tests" / "fixtures" / "repo" / "skills"
            skills.mkdir(parents=True)
            (skills / "a.md").write_text(POSITIVE["E1"], encoding="utf-8")
            self.assertEqual(_codes(rb.lint_file(skills / "a.md")), ["E1"])
            r = subprocess.run([sys.executable, str(LINT), "lint", "--root", str(skills)],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 1, r.stdout)
            checkout = skills.parent
            r = subprocess.run([sys.executable, str(LINT), "check", str(skills / "a.md")],
                               capture_output=True, text=True, encoding="utf-8",
                               cwd=str(checkout))
            self.assertEqual(r.returncode, 1, "relative to the checkout it is skills/a.md")
            r = subprocess.run([sys.executable, str(LINT), "check", "skills/a.md",
                                "--repo", str(checkout)],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 1)


class TestScope(unittest.TestCase):
    """C1: `check` judges exactly the harvester's roots; everything else is read by nothing."""

    MID = "Some notes. The rates table is good until REVIEW-BY 2027-01 at the latest.\n"

    def _check(self, repo: str, *names: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(LINT), "check", "--repo", repo, *names],
                              capture_output=True, text=True, encoding="utf-8")

    def test_roots_come_from_freshness(self):
        self.assertEqual(rb.scope_roots(), (fr.SKILLS_ROOT.name, fr.AGENTS_ROOT.name,
                                            fr.WORKFLOWS_ROOT.name))
        self.assertEqual(set(rb.scope_roots()), {"skills", "agents", "workflows"})

    def test_out_of_scope_paths_pass_silently(self):
        with tempfile.TemporaryDirectory() as td:
            for rel in ("tasks.md", "history.md", "docs/x.md", "vs-code/y.md",
                        "progress/z.md", "docs/skills/w.md"):
                p = Path(td) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(self.MID, encoding="utf-8")
                with self.subTest(rel=rel):
                    r = self._check(td, rel)
                    self.assertEqual(r.returncode, 0, r.stdout)
                    self.assertEqual(r.stdout, "", "skipped silently")

    def test_in_scope_paths_are_judged(self):
        with tempfile.TemporaryDirectory() as td:
            for rel in ("skills/x/SKILL.md", "agents/bob.md", "workflows/w.md",
                        "skills/x/NOTES.MD"):
                p = Path(td) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(self.MID, encoding="utf-8")
                with self.subTest(rel=rel):
                    r = self._check(td, rel)
                    self.assertEqual(r.returncode, 1, r.stdout)
                    self.assertIn("RB-E1", r.stdout)

    def test_path_outside_the_repo_is_not_judged(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as other:
            p = Path(other) / "skills" / "a.md"
            p.parent.mkdir()
            p.write_text(self.MID, encoding="utf-8")
            self.assertEqual(self._check(td, str(p)).returncode, 0)

    def test_paths_from_stdin_and_double_dash(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "skills" / "a.md"
            p.parent.mkdir()
            p.write_text(self.MID, encoding="utf-8")
            r = subprocess.run([sys.executable, str(LINT), "check", "--repo", td,
                                "--paths-from", "-"], input="tasks.md\0skills/a.md\0",
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertRegex(r.stdout, r"(?m)^RB-E1 skills/a\.md:1 ")
            r = self._check(td, "--", "-dash.md", "skills/a.md")
            self.assertEqual(r.returncode, 1, r.stderr)

    def test_missing_dependency_is_a_distinct_exit(self):
        # N4: without freshness.py the linter is unavailable (exit 3 + RB-W2), not crashed.
        with tempfile.TemporaryDirectory() as td:
            lone = Path(td) / "review_by_lint.py"
            lone.write_bytes(LINT.read_bytes())
            r = subprocess.run([sys.executable, str(lone), "check", "skills/a.md"],
                               capture_output=True, text=True, encoding="utf-8", cwd=td)
            self.assertEqual(r.returncode, rb.EXIT_UNAVAILABLE, r.stdout + r.stderr)
            self.assertEqual(r.returncode, 3)
            self.assertRegex(r.stdout, r"(?m)^RB-W2 ")
            self.assertNotIn("Traceback", r.stderr)


class TestStagedMode(unittest.TestCase):
    """M5 (lint side): `check --staged` judges the index, not the working tree."""

    def _git(self, repo, *a):
        return subprocess.run(["git", "-C", str(repo), *a], check=True,
                              capture_output=True, text=True)

    def test_staged_blob_is_what_is_judged(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._git(repo, "init", "-q")
            (repo / "skills").mkdir()
            doc = repo / "skills" / "doc.md"
            doc.write_text(POSITIVE["E1"], encoding="utf-8")
            self._git(repo, "add", "skills/doc.md")
            doc.write_text(POSITIVE["E1"] + "\n" + _block("2027-01-31"), encoding="utf-8")
            args = [sys.executable, str(LINT), "check", "--staged", "--repo", str(repo),
                    "skills/doc.md"]
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertRegex(r.stdout, r"(?m)^RB-E1 skills/doc\.md:3 ")
            r = subprocess.run([sys.executable, str(LINT), "check", "--repo", str(repo),
                                "skills/doc.md"], capture_output=True, text=True,
                               encoding="utf-8")
            self.assertEqual(r.returncode, 0, "the working tree alone is clean")
            self._git(repo, "add", "skills/doc.md")
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stdout)

    def test_unreadable_staged_path_is_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "-C", td, "init", "-q"], check=True, capture_output=True)
            r = subprocess.run([sys.executable, str(LINT), "check", "--staged", "--repo", td,
                                "skills/not-staged.md"], capture_output=True, text=True,
                               encoding="utf-8")
            self.assertEqual(r.returncode, 1)
            self.assertIn("RB-E5", r.stdout)


# -- the real tree -----------------------------------------------------------


def _tree_index() -> dict:
    with tempfile.TemporaryDirectory() as td:
        return fr.build_index(REPO / "skills", REPO / "agents", Path(td) / "workflows")


class TestTree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = _tree_index()
        cls.by_target: dict[str, set[str]] = {}
        for d in cls.index["by_deadline"]:
            cls.by_target.setdefault(d["target"], set()).add(d["date"])

    def test_uk_tax_rates_deadline_is_registered(self):
        target = str(REPO / "skills" / "accounting-uk-ltd" / "references" / "rates-2026-27.md")
        self.assertIn("2027-04-06", self.by_target.get(target, set()))

    def test_every_dated_prose_marker_reaches_by_deadline(self):
        roots = [REPO / "skills"] + ([REPO / "agents"] if (REPO / "agents").is_dir() else [])
        missing, seen = [], 0
        for p, _rel in rb.iter_tree(roots):
            text = p.read_text(encoding="utf-8", errors="replace")
            for mk in rb.find_markers(text):
                seen += 1
                if mk.date not in self.by_target.get(str(p), set()):
                    missing.append(f"{p.relative_to(REPO)}:{mk.line} {mk.raw}")
        self.assertGreaterEqual(seen, 20, "the #281 markers should still be found")
        self.assertEqual(missing, [])

    def test_independent_broad_scan_finds_nothing_find_markers_missed(self):
        """m1: a check that does NOT use find_markers. Any `review by` (any case/separator)
        within ~40 chars of a date-like token, outside fences and FRESHNESS blocks, must be a
        find_markers marker line or carry the explicit suppression -- so a rule that quietly
        narrows cannot also pass this test."""
        broad = re.compile(r"(?is)review[\s_-]*by.{0,40}?(\d{4}|\d{1,2}[/.-]\d{1,2}|"
                           r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d)")
        roots = [REPO / "skills"] + ([REPO / "agents"] if (REPO / "agents").is_dir() else [])
        escaped = []
        for p, _rel in rb.iter_tree(roots):
            text = p.read_text(encoding="utf-8", errors="replace")
            masked = re.sub(r"(?s)<!--\s*FRESHNESS:v1.*?-->",
                            lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
            lines = masked.splitlines()
            in_fence, fence = False, ""
            keep = []
            for line in lines:
                body = line.lstrip(" \t>")
                tick = re.match(r"(`{3,}|~{3,})", body)
                if tick and (not in_fence or (tick.group(1)[0] == fence[0]
                                               and len(tick.group(1)) >= len(fence)
                                               and not body[len(tick.group(1)):].strip())):
                    in_fence, fence = (not in_fence), tick.group(1)
                    keep.append("")
                    continue
                keep.append("" if in_fence else line)
            marker_lines = {mk.line for mk in rb.find_markers(text)}
            flat = "\n".join(keep)
            starts = [0] + [i + 1 for i, ch in enumerate(flat) if ch == "\n"]
            for m in broad.finditer(flat):
                line_no = next(i for i in range(len(starts), 0, -1)
                               if starts[i - 1] <= m.start())
                if line_no in marker_lines:
                    continue
                if "review-by: mention" in lines[line_no - 1].lower():
                    continue
                snippet = flat[m.start():m.end()].replace("\n", " ")
                if "`" in flat[max(0, m.start() - 1):m.start()] or re.search(
                        r"`[^`]*$", flat[starts[line_no - 1]:m.start()]):
                    continue                   # inside an inline code span: a mention
                escaped.append(f"{p.relative_to(REPO)}:{line_no} {snippet!r}")
        self.assertEqual(escaped, [], "a review-by + date the rule does not see")

    def test_tree_lints_clean(self):
        r = subprocess.run([sys.executable, str(LINT), "lint",
                            "--root", str(REPO / "skills"), "--root", str(REPO / "agents")],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout[-4000:])


# -- DW-4: check-deadlines honesty -------------------------------------------


class TestCheckDeadlinesHonesty(unittest.TestCase):
    def _run(self, by_deadline: list[dict]) -> str:
        with tempfile.TemporaryDirectory() as td:
            idx = Path(td) / "index.json"
            idx.write_text(json.dumps({"by_deadline": by_deadline}), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = fr.main(["check-deadlines", "--index", str(idx), "--today", "2026-09-29"])
            self.assertEqual(rc, 0)
            return buf.getvalue()

    def test_none_registered_is_not_an_all_clear(self):
        out = self._run([])
        self.assertIn("NO deadlines indexed", out)
        self.assertNotIn("none within", out)
        # m3: it measured the index, so it must not claim no anchor exists on disk.
        self.assertNotIn("was found", out)
        self.assertNotIn("no FRESHNESS:v1", out)

    def test_registered_but_none_due_says_how_many(self):
        far = [{"target": "a.md", "date": "2030-01-01", "kind": "date_review"},
               {"target": "b.md", "date": "2031-01-01", "kind": "date_review"}]
        out = self._run(far)
        self.assertIn("2 deadline(s) registered; none within 30d of 2026-09-29", out)
        self.assertNotIn("NO deadlines", out)


if __name__ == "__main__":
    unittest.main()


def test_hostile_tag_runs_lint_fast():
    """Post-review m1: the marker grammar is matched inside a bounded window, so a line of
    hundreds of inline tags after the keyword cannot hang the pre-commit hook."""
    import time as _time
    text = "REVIEW-BY " + "<b>" * 500 + "\n"
    start = _time.monotonic()
    rb.find_markers(text)
    assert _time.monotonic() - start < 2.0
