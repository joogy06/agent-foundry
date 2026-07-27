#!/usr/bin/env python3
"""test_scan_hard_rules.py — classification, locally-handled filter,
suppression filter, plain/hook output parity, mixed-source coexistence.

Uses subprocess to exercise the script end-to-end so the test reflects
real hook + plain-CLI behavior. STATE_FILE and CLAUDE.md paths are
redirected by patching the module's globals from inside a pytest tmpdir.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_META = Path(__file__).resolve().parent.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import scan_hard_rules as S  # noqa: E402
from hard_rules_common import directive_hash  # noqa: E402


def _patch_globals(
    global_md: Path,
    project_md: Path | None,
    checklist: Path,
    state_file: Path,
    cwd: Path,
):
    """Returns a list of started patchers; caller must stop them."""
    patches = [
        mock.patch.object(S, "GLOBAL_CLAUDE_MD", global_md),
        mock.patch.object(S, "CHECKLIST", checklist),
        mock.patch.object(S, "STATE_FILE", state_file),
    ]

    # find_project_claude_md walks PROJECT_CLAUDE_MD_CANDIDATES from cwd.
    # We redirect by monkey-patching find_project_claude_md to return
    # `project_md` directly.
    def fake_find():
        if project_md is None:
            return None
        return project_md.resolve()

    patches.append(mock.patch.object(S, "find_project_claude_md", fake_find))

    # Also patch canonical_project_id so it doesn't walk the real FS.
    def fake_project_id(start=None):
        if project_md is not None:
            return str(project_md.parent.resolve())
        return str(cwd.resolve())

    patches.append(mock.patch.object(S, "canonical_project_id", fake_project_id))

    started = []
    for p in patches:
        p.start()
        started.append(p)
    return started


def _stop_patches(patches):
    for p in patches:
        p.stop()


def _capture_main_plain() -> str:
    """Invoke S.main() with argv set to plain mode, capture stdout."""
    import io
    buf = io.StringIO()
    argv_save = sys.argv
    sys.argv = ["scan_hard_rules.py"]
    try:
        with mock.patch("sys.stdout", buf):
            S.main()
    finally:
        sys.argv = argv_save
    return buf.getvalue()


def _capture_main_hook() -> dict:
    """Invoke S.main() with argv=['--hook'], parse stdout as JSON."""
    import io
    buf = io.StringIO()
    argv_save = sys.argv
    sys.argv = ["scan_hard_rules.py", "--hook"]
    try:
        # Pretend stdin is a tty so the drain doesn't block.
        with mock.patch("sys.stdout", buf), mock.patch(
            "sys.stdin.isatty", return_value=True
        ):
            S.main()
    finally:
        sys.argv = argv_save
    out = buf.getvalue().strip()
    return json.loads(out) if out else {}


class ClassificationCase(unittest.TestCase):
    def test_classify_splits_by_label(self):
        missing = [
            "[global] HARD-RULE: A",
            "[project:/x] HARD-RULE: B",
            "[project:/x] HARD-RULE: C",
        ]
        g, p = S.classify_missing(missing)
        self.assertEqual(g, ["[global] HARD-RULE: A"])
        self.assertEqual(p, [
            "[project:/x] HARD-RULE: B",
            "[project:/x] HARD-RULE: C",
        ])


class LocallyHandledFilterCase(unittest.TestCase):
    def test_extract_locally_handled_returns_canonical_set(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "CLAUDE.md"
            p.write_text(
                "# Project\n\n"
                "## Project HARD-RULEs\n\n"
                f"{S.PROJECT_HARD_RULES_MARKER}\n\n"
                "- already declared rule\n"
                "- another one\n\n"
                "## Other\n",
                encoding="utf-8",
            )
            handled = S.extract_locally_handled(p)
            self.assertIn("already declared rule", handled)
            self.assertIn("another one", handled)

    def test_extract_locally_handled_missing_section(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "CLAUDE.md"
            p.write_text("# Project\n\nno section here\n", encoding="utf-8")
            self.assertEqual(S.extract_locally_handled(p), set())

    def test_extract_locally_handled_skips_fenced_bullets(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "CLAUDE.md"
            p.write_text(
                "## Project HARD-RULEs\n\n"
                f"{S.PROJECT_HARD_RULES_MARKER}\n\n"
                "```\n"
                "- not a real bullet\n"
                "```\n\n"
                "- real bullet\n",
                encoding="utf-8",
            )
            handled = S.extract_locally_handled(p)
            self.assertIn("real bullet", handled)
            self.assertNotIn("not a real bullet", handled)

    def test_filter_locally_handled(self):
        rules = [
            "[project:/x] - already declared rule",
            "[project:/x] - fresh rule",
        ]
        handled = {"already declared rule"}
        out = S.filter_locally_handled(rules, handled)
        self.assertEqual(len(out), 1)
        self.assertIn("fresh rule", out[0])


class SuppressionFilterCase(unittest.TestCase):
    def test_load_suppressed_missing_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(
                S, "STATE_FILE", Path(td) / "no-such-file.json"
            ):
                self.assertEqual(S.load_suppressed("/proj/x"), set())

    def test_load_suppressed_reads_hashes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            state_file = Path(td) / "state.json"
            payload = {
                "/proj/x": {
                    "suppressed": [
                        {"hash": "abc", "directive": "x", "ts": "now"},
                        {"hash": "def", "directive": "y", "ts": "now"},
                    ]
                }
            }
            state_file.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(S, "STATE_FILE", state_file):
                got = S.load_suppressed("/proj/x")
            self.assertEqual(got, {"abc", "def"})

    def test_load_suppressed_corrupt_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            state_file = Path(td) / "state.json"
            state_file.write_text("not json", encoding="utf-8")
            with mock.patch.object(S, "STATE_FILE", state_file):
                self.assertEqual(S.load_suppressed("/proj/x"), set())

    def test_filter_suppressed(self):
        rules = ["[project:/x] - rule a", "[project:/x] - rule b"]
        # directive_hash() strips the source label, so we can hash either form.
        h_a = directive_hash(rules[0])
        out = S.filter_suppressed(rules, {h_a})
        self.assertEqual(len(out), 1)
        self.assertIn("rule b", out[0])


class HookOutputContractCase(unittest.TestCase):
    """End-to-end: synthesize fake global + project CLAUDE.md, run the
    scanner in both modes, verify the hook payload matches the design."""

    def _setup_project(self, td: Path) -> tuple[Path, Path, Path, Path]:
        global_md = td / "global_CLAUDE.md"
        project_md = td / "project_CLAUDE.md"
        checklist = td / "checklist.md"
        state_file = td / "state.json"
        # Global CLAUDE.md: contains a hard-rule line whose tokens land in
        # the checklist (so it's NOT missing). Use plain text section
        # headers that don't trip HARD_RULE_PATTERNS' heading regex.
        global_md.write_text(
            "# Global\n\n"
            "## Notes\n"
            "- **carefully read** the design document each session\n",
            encoding="utf-8",
        )
        # Project CLAUDE.md: contains 3 project hard-rule directives that
        # are NOT in the checklist. Section header chosen to NOT trip the
        # ##+ heading regex (no 'mandatory/checkpoint/routing/...' words).
        # Each directive carries MANDATE LANGUAGE, because extract_rules()
        # applies a second-stage MANDATE_LANGUAGE_RE filter to bold-led bullets
        # (a weak signal on its own — any wrapped reference line starting with
        # bold would otherwise be captured). The trailing non-mandate bullet is
        # the false-positive guard: it MUST NOT be reported as a directive.
        project_md.write_text(
            "# Project\n\n"
            "## Notes\n"
            "- **inprogress-01 working branch only, never commit to main**\n"
            "- **production-deploy requires explicit user approval**\n"
            "- **private-only push to foundry-lab, public remotes forbidden**\n"
            "- **Other modes:** `-i` interactive, `-c` continue\n",
            encoding="utf-8",
        )
        # Checklist: contains tokens for the global rule only.
        checklist.write_text(
            "# Checklist\n\n"
            "- carefully read design document session\n",
            encoding="utf-8",
        )
        return global_md, project_md, checklist, state_file

    def test_plain_mode_emits_y_n_edit_proposal(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            global_md, project_md, checklist, state_file = self._setup_project(td)
            patches = _patch_globals(
                global_md, project_md, checklist, state_file, cwd=td
            )
            try:
                out = _capture_main_plain()
            finally:
                _stop_patches(patches)
            # Must contain the new Project-Scoped section.
            self.assertIn("## Project-Scoped Directives Need Action", out)
            # Must contain all three directives.
            self.assertIn("inprogress-01 working branch only", out)
            self.assertIn("production-deploy requires explicit user approval", out)
            self.assertIn("private-only push to foundry-lab", out)
            # Must contain the fully-formed apply command with --rule for each.
            self.assertIn("apply_project_hard_rules.py apply", out)
            self.assertEqual(out.count("--rule "), 6)  # 3 in apply + 3 in suppress
            # Must mention the project CLAUDE.md path.
            self.assertIn(str(project_md.resolve()), out)

    def test_hook_mode_emits_same_context(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            global_md, project_md, checklist, state_file = self._setup_project(td)
            patches = _patch_globals(
                global_md, project_md, checklist, state_file, cwd=td
            )
            try:
                payload = _capture_main_hook()
            finally:
                _stop_patches(patches)
            self.assertTrue(payload.get("continue"))
            ctx = payload["hookSpecificOutput"]["additionalContext"]
            # Same content as plain mode (build_context is the single
            # renderer per Codex #6).
            self.assertIn("## Project-Scoped Directives Need Action", ctx)
            self.assertIn("inprogress-01 working branch only", ctx)
            self.assertIn("apply_project_hard_rules.py apply", ctx)

    def test_suppressed_rules_do_not_renudge(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            global_md, project_md, checklist, state_file = self._setup_project(td)
            # Pre-populate state file with all 3 directive hashes.
            h1 = directive_hash("- **inprogress-01 working branch only, never commit to main**")
            h2 = directive_hash(
                "- **production-deploy requires explicit user approval**"
            )
            h3 = directive_hash("- **private-only push to foundry-lab, public remotes forbidden**")
            state_file.write_text(json.dumps({
                str(project_md.parent.resolve()): {
                    "suppressed": [
                        {"hash": h1, "directive": "x", "ts": "t"},
                        {"hash": h2, "directive": "x", "ts": "t"},
                        {"hash": h3, "directive": "x", "ts": "t"},
                    ]
                }
            }), encoding="utf-8")
            patches = _patch_globals(
                global_md, project_md, checklist, state_file, cwd=td
            )
            try:
                payload = _capture_main_hook()
            finally:
                _stop_patches(patches)
            # No actionable context -> benign hook JSON (no
            # hookSpecificOutput).
            self.assertNotIn("hookSpecificOutput", payload)
            self.assertTrue(payload.get("continue"))

    def test_locally_handled_rules_do_not_nudge(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            global_md, project_md, checklist, state_file = self._setup_project(td)
            # Append a Project HARD-RULEs section containing the SAME
            # 3 canonical directives.
            with project_md.open("a", encoding="utf-8") as fp:
                fp.write(
                    "\n## Project HARD-RULEs\n\n"
                    f"{S.PROJECT_HARD_RULES_MARKER}\n\n"
                    "- inprogress-01 working branch only, never commit to main\n"
                    "- production-deploy requires explicit user approval\n"
                    "- private-only push to foundry-lab, public remotes forbidden\n"
                )
            patches = _patch_globals(
                global_md, project_md, checklist, state_file, cwd=td
            )
            try:
                payload = _capture_main_hook()
            finally:
                _stop_patches(patches)
            # The "locally handled" filter removes the 3 project rules
            # BEFORE the missing-context emit, so the hook is benign.
            # But the scanner now ALSO sees them in the section itself
            # (HARD_RULE_PATTERNS matches '- **x**' specifically — the
            # "- bare" bullets in the new section don't match the bold
            # pattern, so they won't re-appear as extracted rules).
            self.assertTrue(payload.get("continue"))
            self.assertNotIn("hookSpecificOutput", payload)


class MixedSourceCoexistenceCase(unittest.TestCase):
    def test_both_sections_emitted(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            global_md = td / "global.md"
            project_md = td / "project.md"
            checklist = td / "checklist.md"
            state_file = td / "state.json"
            # Global has a rule NOT in checklist.
            global_md.write_text(
                "# Global\n"
                "- **global-only-rule must be in checklist**\n",
                encoding="utf-8",
            )
            # Project has a rule NOT in checklist.
            project_md.write_text(
                "# Project\n"
                "- **project-only-rule must be surfaced**\n",
                encoding="utf-8",
            )
            checklist.write_text(
                "# Checklist\n\nirrelevant content\n",
                encoding="utf-8",
            )
            patches = _patch_globals(
                global_md, project_md, checklist, state_file, cwd=td
            )
            try:
                out = _capture_main_plain()
            finally:
                _stop_patches(patches)
            # Both sections present, neither hides the other.
            self.assertIn("## Project-Scoped Directives Need Action", out)
            self.assertIn("## Global-Scoped Directives", out)
            self.assertIn("global-only-rule", out)
            self.assertIn("project-only-rule", out)


class NoMissingCase(unittest.TestCase):
    def test_no_rules_no_action(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            global_md = td / "g.md"
            project_md = None
            checklist = td / "c.md"
            state_file = td / "s.json"
            global_md.write_text("# nothing\n", encoding="utf-8")
            checklist.write_text("# checklist\n", encoding="utf-8")
            patches = _patch_globals(
                global_md, project_md, checklist, state_file, cwd=td
            )
            try:
                out = _capture_main_plain()
            finally:
                _stop_patches(patches)
            self.assertIn("No hard-rule directives found", out)


if __name__ == "__main__":
    unittest.main()
