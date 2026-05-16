#!/usr/bin/env python3
"""test_hard_rules_common.py — canonical project id / directive text / hash.

Covers the shared canonicalization module that scanner + helper both import.
The hash is load-bearing for suppression; equality is load-bearing for
locally-handled filtering. Any drift between these tests and either caller
will manifest as nudge-loop bugs.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Make ~/.claude/skills/_meta importable.
_META = Path(__file__).resolve().parent.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

from hard_rules_common import (  # noqa: E402
    canonical_directive_text,
    canonical_project_id,
    directive_hash,
    display_directive_text,
)


class DisplayDirectiveTextCase(unittest.TestCase):
    def test_strips_label_and_bullet_and_emphasis(self):
        self.assertEqual(
            display_directive_text(
                "[project:/tmp/x] - **smoke-rule alpha works**"
            ),
            "smoke-rule alpha works",
        )

    def test_preserves_casing(self):
        self.assertEqual(
            display_directive_text("- **SMOKE-Rule Alpha**"),
            "SMOKE-Rule Alpha",
        )

    def test_collapses_whitespace(self):
        self.assertEqual(
            display_directive_text("foo   bar  baz"),
            "foo bar baz",
        )


class CanonicalDirectiveTextCase(unittest.TestCase):
    def test_strips_global_label(self):
        self.assertEqual(
            canonical_directive_text("[global] HARD-RULE: ship it"),
            "hard-rule: ship it",
        )

    def test_strips_project_label_with_path(self):
        self.assertEqual(
            canonical_directive_text(
                "[project:/mnt/data/foo bar] HARD-RULE: ship it"
            ),
            "hard-rule: ship it",
        )

    def test_strips_dash_bullet(self):
        self.assertEqual(
            canonical_directive_text("- inprogress-01 working branch only"),
            "inprogress-01 working branch only",
        )

    def test_strips_star_bullet(self):
        self.assertEqual(
            canonical_directive_text("* foo bar baz"),
            "foo bar baz",
        )

    def test_strips_plus_bullet(self):
        self.assertEqual(
            canonical_directive_text("+ foo bar baz"),
            "foo bar baz",
        )

    def test_strips_numbered_list(self):
        self.assertEqual(
            canonical_directive_text("1. foo bar baz"),
            "foo bar baz",
        )

    def test_strips_bold_emphasis(self):
        self.assertEqual(
            canonical_directive_text("**inprogress-01** working branch"),
            "inprogress-01 working branch",
        )

    def test_strips_italic_underscore(self):
        self.assertEqual(
            canonical_directive_text("_inprogress-01_ working branch"),
            "inprogress-01 working branch",
        )

    def test_strips_backticks(self):
        self.assertEqual(
            canonical_directive_text("use `git push` carefully"),
            "use git push carefully",
        )

    def test_strips_html_comment(self):
        self.assertEqual(
            canonical_directive_text(
                "rule one <!-- TODO: refine --> end here"
            ),
            "rule one  end here".replace("  ", " "),
        )

    def test_collapses_whitespace(self):
        self.assertEqual(
            canonical_directive_text("foo   bar\tbaz\n\nqux"),
            "foo bar baz qux",
        )

    def test_lowercase(self):
        self.assertEqual(
            canonical_directive_text("FOO Bar BAZ"),
            "foo bar baz",
        )

    def test_empty_string(self):
        self.assertEqual(canonical_directive_text(""), "")

    def test_combined_source_label_bullet_emphasis(self):
        a = canonical_directive_text(
            "[project:/tmp/x] - **inprogress-01** working branch"
        )
        b = canonical_directive_text(
            "- inprogress-01 working branch"
        )
        self.assertEqual(a, b)


class DirectiveHashCase(unittest.TestCase):
    def test_deterministic(self):
        h1 = directive_hash("HARD-RULE: ship it")
        h2 = directive_hash("HARD-RULE: ship it")
        self.assertEqual(h1, h2)

    def test_hash_after_canonicalization(self):
        # Source label + bullet + emphasis should not change the hash.
        h_raw = directive_hash(
            "[project:/foo] - **HARD-RULE: ship it**"
        )
        h_canon = directive_hash("hard-rule: ship it")
        self.assertEqual(h_raw, h_canon)

    def test_different_content_different_hash(self):
        self.assertNotEqual(
            directive_hash("rule A"),
            directive_hash("rule B"),
        )

    def test_hex_length_64(self):
        # sha256-hex = 64 chars.
        self.assertEqual(len(directive_hash("anything")), 64)


class CanonicalProjectIdCase(unittest.TestCase):
    def test_finds_claude_md_in_cwd(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / "CLAUDE.md").write_text("# proj\n")
            result = canonical_project_id(root)
            self.assertEqual(result, str(root))

    def test_finds_dotclaude_claude_md(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / ".claude").mkdir()
            (root / ".claude" / "CLAUDE.md").write_text("# proj\n")
            result = canonical_project_id(root)
            self.assertEqual(result, str(root))

    def test_walks_up_to_find_claude_md(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / "CLAUDE.md").write_text("# proj\n")
            nested = root / "a" / "b" / "c"
            nested.mkdir(parents=True)
            result = canonical_project_id(nested)
            self.assertEqual(result, str(root))

    def test_fallback_when_no_claude_md(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            # No CLAUDE.md anywhere down to root — fallback to start.
            result = canonical_project_id(root)
            self.assertEqual(result, str(root))

    def test_returns_string_not_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / "CLAUDE.md").write_text("# proj\n")
            result = canonical_project_id(root)
            self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
