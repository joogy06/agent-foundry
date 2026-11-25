"""claims_lint unsourced: a statistic with no source, date or label on its line is a WARN."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
LINT = SCRIPTS / "claims_lint.py"
SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS))

import claims_lint  # noqa: E402

#: The search and AI-visibility family: `family: seo` members plus these, which carry no
#: family key so they stay portable.
EXTRA = "ai-search-optimizer,agentic-commerce-readiness,ai-assistant-referrals,ecommerce-growth"
#: 8 `family: seo` skills + the 4 above; fewer scanned means the scope silently shrank.
MIN_SCANNED = 12


def hits(text: str) -> list[int]:
    return [n for n, _ in claims_lint.unsourced_stats(text)]


class UnsourcedStats(unittest.TestCase):
    def test_bare_percentage_warns(self):
        self.assertEqual(hits("Titles earn 33.3% higher CTR.\n"), [1])

    def test_multiplier_warns_but_image_size_does_not(self):
        self.assertEqual(hits("Callouts get 2.3x citations.\n"), [1])
        self.assertEqual(hits("Minimum size 1200x630px.\n"), [])

    def test_url_date_label_or_heuristic_sources_it(self):
        for line in (
            "Bing is 5.67% of UK search https://gs.statcounter.com/x\n",
            "Bing is 5.67% of UK search (StatCounter, Aug 2026)\n",
            "Bing is 5.67% of UK search [V]\n",
            "Alert when clicks drop 20% (heuristic)\n",
            "FORECAST: 40% by next year\n",
        ):
            self.assertEqual(hits(line), [], line)

    def test_table_row_is_one_unit(self):
        row = "| Brand mentions | 66% | https://example.com/study |\n"
        self.assertEqual(hits(row), [])
        self.assertEqual(hits("| Brand mentions | 66% | Ahrefs |\n"), [1])

    def test_code_comments_and_frontmatter_are_skipped(self):
        text = ("---\nname: x\ndescription: 50% off\n---\n"
                "```\nwidth: 100%\n```\n"
                "<!-- FRESHNESS:v1\n  claim: 90% share\n-->\n"
                "Real claim 12%.\n")
        self.assertEqual(hits(text), [11])


class FixRound1(unittest.TestCase):
    """C5: a bare year is not a source; percent words, x-signs and post-comment text count."""

    def test_bare_year_does_not_source_a_statistic(self):
        self.assertEqual(hits("In 2025 titles earned 33% more clicks.\n"), [1])
        self.assertEqual(hits("| 2026 | 40% |\n"), [1])

    def test_source_like_dates_do(self):
        for line in ("Clicks fell 40% (Ahrefs study, 2025).\n",
                     "Clicks fell 40% (Ahrefs, Mar 2026).\n",
                     "Clicks fell 40% as of 2026-09-27.\n",
                     "Clicks fell 40% (Q1 2025 study).\n",
                     "Clicks fell 40% in September 2026.\n"):
            self.assertEqual(hits(line), [], line)

    def test_percent_word_and_multiplication_signs_are_statistics(self):
        self.assertEqual(hits("Lifts CVR by 12 percent.\n"), [1])
        self.assertEqual(hits("Cited 3\u00d7 more often.\n"), [1])
        self.assertEqual(hits("Cited 3X more often.\n"), [1])

    def test_text_after_a_closing_comment_is_scanned(self):
        self.assertEqual(hits("<!-- note --> Lifts CVR by 12%.\n"), [1])
        self.assertEqual(hits("<!-- FRESHNESS:v1\n  claim: 9%\n--> Lifts CVR by 12%.\n"), [3])


class FixRound2(unittest.TestCase):
    """Finding 8: the statistic words match in any case ("12 Percent", "12 PER CENT")."""

    def test_percent_words_match_case_insensitively(self):
        for line in ("Lifts CVR by 12 Percent.\n", "Lifts CVR by 12 PERCENT.\n",
                     "Lifts CVR by 12 Per Cent.\n", "Lifts CVR by 12 per Cent.\n"):
            self.assertEqual(hits(line), [1], line)

    def test_percentile_is_still_not_a_percentage(self):
        self.assertEqual(hits("Measured at the 75 Percentile.\n"), [])


class Cli(unittest.TestCase):
    def run_lint(self, root: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(LINT), "--root", str(root), *args],
                              capture_output=True, text=True, encoding="utf-8")

    def test_family_selection_and_references_are_scanned(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a" / "references").mkdir(parents=True)
            (root / "a" / "SKILL.md").write_text("---\nname: a\nfamily: seo\n---\nok\n", encoding="utf-8")
            (root / "a" / "references" / "r.md").write_text("Lift of 40%.\n", encoding="utf-8")
            (root / "b").mkdir()
            (root / "b" / "SKILL.md").write_text("---\nname: b\n---\nLift of 40%.\n", encoding="utf-8")
            r = self.run_lint(root, "unsourced", "--family", "seo")
            self.assertEqual(r.returncode, 0)
            self.assertIn("a/references/r.md:1", r.stdout)
            self.assertNotIn("b/SKILL.md", r.stdout)
            self.assertEqual(self.run_lint(root, "unsourced", "--family", "seo",
                                           "--fail-on-warn").returncode, 1)

    def test_unknown_skill_is_bad_input(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a").mkdir()
            (Path(d) / "a" / "SKILL.md").write_text("---\nname: a\n---\nok\n", encoding="utf-8")
            r = self.run_lint(Path(d), "--skills", "a,no-such-skill", "unsourced")
            self.assertEqual(r.returncode, 3)
            self.assertIn("no-such-skill", r.stderr)

    def test_no_selection_is_bad_input(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_lint(Path(d), "unsourced").returncode, 3)

    def test_search_family_is_clean(self):
        """Regression guard: the family was cleaned on 2026-09-27 (98 warnings before)."""
        r = self.run_lint(SKILLS, "--skills", EXTRA, "unsourced", "--family", "seo", "--fail-on-warn")
        self.assertEqual(r.returncode, 0, r.stdout)
        scanned = int(r.stdout.strip().splitlines()[-1].split("across ")[1].split(" skill")[0])
        self.assertGreaterEqual(scanned, MIN_SCANNED, r.stdout)

