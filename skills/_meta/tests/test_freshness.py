#!/usr/bin/env python3
"""Tests for freshness.py (Evergreening v1, S041).

Covers: FRESHNESS:v1 parse round-trip (SKILL.md AND a frontmatter-less reference);
lint; restamp (in-place update + insert); reindex by_tool/by_deadline; deadline
idempotency INCLUDING the §9.1 changed-date sub-case (same target, new date -> SAME
row updated in place, no orphan).

stdlib unittest. Run:
  python3 -m unittest discover -s ~/.claude/skills/_meta/tests -p 'test_freshness.py' -v
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path

_META = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("freshness", _META / "freshness.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)


_BLOCK = """<!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: codex
    verified_against: "0.137.0"
    verified_on: "2026-06-04"
  - kind: date_review
    review_by: "2027-01"
volatility: high
-->"""


class TestParse(unittest.TestCase):
    def test_parse_block(self):
        parsed = fr.parse_freshness_yaml(_BLOCK.split("\n", 1)[1].rsplit("\n", 1)[0])
        self.assertEqual(len(parsed["anchors"]), 2)
        self.assertEqual(parsed["anchors"][0]["subject"], "codex")
        self.assertEqual(parsed["anchors"][0]["verified_against"], "0.137.0")
        self.assertEqual(parsed["volatility"], "high")

    def test_extract_from_skill_md(self):
        text = f"# Skill\n\nsome prose\n\n{_BLOCK}\n\nmore prose\n"
        bodies = fr.extract_blocks(text)
        self.assertEqual(len(bodies), 1)

    def test_extract_from_frontmatterless_reference(self):
        # A reference .md with NO YAML frontmatter must still yield the block
        # (the whole point of the HTML-comment form — Adjudication 1).
        text = f"Just a reference doc, no frontmatter.\n\n{_BLOCK}\n"
        bodies = fr.extract_blocks(text)
        self.assertEqual(len(bodies), 1)
        parsed = fr.parse_freshness_yaml(bodies[0])
        self.assertEqual(parsed["anchors"][0]["subject"], "codex")

    def test_inline_comment_stripped(self):
        body = "anchors:\n  - kind: tool_version  # a comment\n    subject: codex"
        parsed = fr.parse_freshness_yaml(body)
        self.assertEqual(parsed["anchors"][0]["kind"], "tool_version")


class TestRoundTrip(unittest.TestCase):
    def test_render_reparse_stable(self):
        body = _BLOCK.split("\n", 1)[1].rsplit("\n", 1)[0]
        parsed = fr.parse_freshness_yaml(body)
        rendered = fr.render_block(parsed)
        reparsed_bodies = fr.extract_blocks(rendered)
        self.assertEqual(len(reparsed_bodies), 1)
        reparsed = fr.parse_freshness_yaml(reparsed_bodies[0])
        self.assertEqual(reparsed, parsed)


class TestLint(unittest.TestCase):
    def test_lint_clean_block(self):
        body = _BLOCK.split("\n", 1)[1].rsplit("\n", 1)[0]
        warns = fr.lint_block(fr.parse_freshness_yaml(body))
        self.assertEqual(warns, [])

    def test_lint_missing_subject(self):
        body = "anchors:\n  - kind: tool_version\n    verified_against: \"1.0\""
        warns = fr.lint_block(fr.parse_freshness_yaml(body))
        self.assertTrue(any("subject" in w for w in warns))

    def test_lint_bad_kind(self):
        body = "anchors:\n  - kind: bogus_kind\n    subject: x"
        warns = fr.lint_block(fr.parse_freshness_yaml(body))
        self.assertTrue(any("kind" in w for w in warns))


class TestRestamp(unittest.TestCase):
    def test_restamp_updates_in_place(self):
        text = f"# Skill\n\n{_BLOCK}\n"
        new_text, changed = fr.restamp_text(text, "codex", "0.138.0", "2026-06-05", None)
        self.assertTrue(changed)
        self.assertIn("0.138.0", new_text)
        self.assertNotIn("0.137.0", new_text)
        # re-parse confirms structure preserved
        parsed = fr.parse_freshness_yaml(fr.extract_blocks(new_text)[0])
        codex = next(a for a in parsed["anchors"] if a.get("subject") == "codex")
        self.assertEqual(codex["verified_against"], "0.138.0")
        self.assertEqual(codex["verified_on"], "2026-06-05")

    def test_restamp_inserts_when_no_block(self):
        text = "# Skill with no freshness block\n"
        new_text, changed = fr.restamp_text(text, "codex", "0.137.0", "2026-06-05", None)
        self.assertTrue(changed)
        self.assertIn("FRESHNESS:v1", new_text)
        parsed = fr.parse_freshness_yaml(fr.extract_blocks(new_text)[0])
        self.assertEqual(parsed["anchors"][0]["subject"], "codex")

    def test_restamp_noop_when_current(self):
        text = f"{_BLOCK}\n"
        # already 0.137.0 on 2026-06-04; restamp to same version+date -> no change
        new_text, changed = fr.restamp_text(text, "codex", "0.137.0", "2026-06-04", None)
        self.assertFalse(changed)


class TestReindex(unittest.TestCase):
    def test_build_index(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "skill-a").mkdir()
            (root / "skill-a" / "SKILL.md").write_text(f"# a\n{_BLOCK}\n")
            idx = fr.build_index(root, root / "no-agents")
            self.assertIn("codex", idx["by_tool"])
            self.assertEqual(len(idx["by_deadline"]), 1)
            self.assertEqual(idx["by_deadline"][0]["date"], "2027-01")
            self.assertEqual(idx["schema_version"], "freshness-index.v1")


class TestDeadlineIdempotency(unittest.TestCase):
    def _index(self, target, date_str, kind="retirement"):
        return {"by_deadline": [{"target": target, "date": date_str,
                                 "kind": kind, "volatility": "medium"}]}

    def test_same_target_twice_one_row(self):
        with tempfile.TemporaryDirectory() as td:
            tasks = Path(td) / "tasks.md"
            idx = self._index("skills/gemini-cli/SKILL.md", "2026-06-18")
            today = date(2026, 6, 5)
            due = fr.deadlines_within_horizon(idx, today, 30)
            u1, i1 = fr.upsert_tasks_md(tasks, due)
            self.assertEqual((u1, i1), (0, 1))  # first run inserts
            u2, i2 = fr.upsert_tasks_md(tasks, due)
            self.assertEqual((u2, i2), (1, 0))  # second run updates, no dup
            content = tasks.read_text()
            self.assertEqual(content.count("freshness-deadline:"), 1)

    def test_changed_date_updates_same_row_no_orphan(self):
        # §9.1 changed-date sub-case: same target, NEW date -> SAME row updated in
        # place; the upsert key is `target` alone, the date is a mutable field.
        with tempfile.TemporaryDirectory() as td:
            tasks = Path(td) / "tasks.md"
            today = date(2026, 6, 5)
            idx1 = self._index("skills/gemini-cli/SKILL.md", "2026-06-18")
            due1 = fr.deadlines_within_horizon(idx1, today, 30)
            fr.upsert_tasks_md(tasks, due1)
            # date shifts:
            idx2 = self._index("skills/gemini-cli/SKILL.md", "2026-06-25")
            due2 = fr.deadlines_within_horizon(idx2, today, 30)
            u, i = fr.upsert_tasks_md(tasks, due2)
            self.assertEqual((u, i), (1, 0))  # updated, NOT a new orphan row
            content = tasks.read_text()
            self.assertEqual(content.count("freshness-deadline:"), 1)  # still ONE row
            self.assertIn("2026-06-25", content)   # date field updated
            self.assertNotIn("2026-06-18", content)  # old date gone (no orphan)

    def test_past_deadline_within_horizon(self):
        idx = self._index("skills/x/SKILL.md", "2026-06-01")  # past
        today = date(2026, 6, 5)
        due = fr.deadlines_within_horizon(idx, today, 30)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["days_remaining"], -4)

    def test_beyond_horizon_excluded(self):
        idx = self._index("skills/x/SKILL.md", "2027-12-01")
        today = date(2026, 6, 5)
        due = fr.deadlines_within_horizon(idx, today, 30)
        self.assertEqual(due, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
