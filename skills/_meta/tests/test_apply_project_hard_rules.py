#!/usr/bin/env python3
"""test_apply_project_hard_rules.py — apply / suppress / list / unsuppress.

Covers:
  - apply to missing CLAUDE.md -> creates file with section
  - apply to file without section -> appends section at end
  - apply to file with existing section -> inserts bullets, skips dups
  - apply with code-fenced bullets is fence-aware (does not dedupe against
    examples inside fences)
  - CRLF preservation
  - symlink-aware atomic write
  - suppress + load + dedupe by hash
  - suppress with corrupted state file -> quarantines + starts fresh
  - list-suppressed
  - unsuppress --all / --hash
  - error handling: zero rules, oversized rule, directory target
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

_META = Path(__file__).resolve().parent.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import apply_project_hard_rules as A  # noqa: E402
from hard_rules_common import directive_hash  # noqa: E402


def _run_main(*argv: str, env_state_dir: Path | None = None) -> int:
    """Invoke A.main() with patched STATE_DIR if provided."""
    patches = []
    if env_state_dir is not None:
        state_file = env_state_dir / "hard-rules-suppressed.json"
        patches.append(mock.patch.object(A, "STATE_DIR", env_state_dir))
        patches.append(mock.patch.object(A, "STATE_FILE", state_file))
    for p in patches:
        p.start()
    try:
        return A.main(list(argv))
    finally:
        for p in patches:
            p.stop()


class ApplyMissingFileCase(unittest.TestCase):
    def test_creates_file_with_section(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "CLAUDE.md"
            rc = _run_main(
                "apply",
                "--project-claude-md", str(target),
                "--rule", "first directive",
                "--rule", "second directive",
            )
            self.assertEqual(rc, 0)
            content = target.read_text(encoding="utf-8")
            self.assertIn("## Project HARD-RULEs", content)
            self.assertIn("- first directive", content)
            self.assertIn("- second directive", content)
            self.assertIn(A.PROJECT_HARD_RULES_MARKER, content)


class ApplyAppendSectionCase(unittest.TestCase):
    def test_appends_section_at_end(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "CLAUDE.md"
            target.write_text(
                "# Project\n\nSome existing content here.\n",
                encoding="utf-8",
            )
            rc = _run_main(
                "apply",
                "--project-claude-md", str(target),
                "--rule", "rule alpha",
            )
            self.assertEqual(rc, 0)
            content = target.read_text(encoding="utf-8")
            self.assertIn("Some existing content here.", content)
            self.assertIn("## Project HARD-RULEs", content)
            self.assertIn("- rule alpha", content)
            # New section should come AFTER existing content.
            self.assertGreater(
                content.find("## Project HARD-RULEs"),
                content.find("existing content"),
            )


class ApplyExistingSectionCase(unittest.TestCase):
    def test_inserts_after_existing_bullets_dedup_canonical(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "CLAUDE.md"
            target.write_text(
                "# Project\n\n"
                "## Project HARD-RULEs\n\n"
                f"{A.PROJECT_HARD_RULES_MARKER}\n\n"
                "- existing rule one\n"
                "- existing rule two\n"
                "\n"
                "## Next Section\n\n"
                "stuff\n",
                encoding="utf-8",
            )
            rc = _run_main(
                "apply",
                "--project-claude-md", str(target),
                "--rule", "Existing Rule One",  # canonical dup
                "--rule", "fresh rule three",
            )
            self.assertEqual(rc, 0)
            content = target.read_text(encoding="utf-8")
            # Dup should not be inserted twice.
            self.assertEqual(content.lower().count("existing rule one"), 1)
            # New rule inserted.
            self.assertIn("- fresh rule three", content)
            # Order: fresh rule three should come AFTER existing rule two,
            # BEFORE "## Next Section".
            idx_two = content.find("existing rule two")
            idx_three = content.find("fresh rule three")
            idx_next = content.find("## Next Section")
            self.assertLess(idx_two, idx_three)
            self.assertLess(idx_three, idx_next)

    def test_section_without_bullets_inserts_after_marker(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "CLAUDE.md"
            target.write_text(
                "# Project\n\n"
                "## Project HARD-RULEs\n\n"
                f"{A.PROJECT_HARD_RULES_MARKER}\n\n"
                "## Next Section\n",
                encoding="utf-8",
            )
            rc = _run_main(
                "apply",
                "--project-claude-md", str(target),
                "--rule", "fresh rule",
            )
            self.assertEqual(rc, 0)
            content = target.read_text(encoding="utf-8")
            idx_marker = content.find(A.PROJECT_HARD_RULES_MARKER)
            idx_rule = content.find("- fresh rule")
            idx_next = content.find("## Next Section")
            self.assertGreater(idx_rule, idx_marker)
            self.assertLess(idx_rule, idx_next)


class ApplyCodeFenceAwareCase(unittest.TestCase):
    def test_does_not_dedupe_against_fenced_example(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "CLAUDE.md"
            target.write_text(
                "## Project HARD-RULEs\n\n"
                f"{A.PROJECT_HARD_RULES_MARKER}\n\n"
                "```markdown\n"
                "- fenced example rule\n"
                "```\n",
                encoding="utf-8",
            )
            rc = _run_main(
                "apply",
                "--project-claude-md", str(target),
                "--rule", "fenced example rule",  # would be dup if fence ignored
            )
            self.assertEqual(rc, 0)
            content = target.read_text(encoding="utf-8")
            # The fenced example still there; the real bullet also added.
            self.assertEqual(content.count("- fenced example rule"), 2)

    def test_fenced_h2_does_not_end_section(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "CLAUDE.md"
            target.write_text(
                "## Project HARD-RULEs\n\n"
                f"{A.PROJECT_HARD_RULES_MARKER}\n\n"
                "```markdown\n"
                "## Not A Real Heading\n"
                "```\n\n"
                "- real bullet here\n\n"
                "## Next Section\n",
                encoding="utf-8",
            )
            rc = _run_main(
                "apply",
                "--project-claude-md", str(target),
                "--rule", "another real rule",
            )
            self.assertEqual(rc, 0)
            content = target.read_text(encoding="utf-8")
            idx_real = content.find("- real bullet here")
            idx_another = content.find("- another real rule")
            idx_next = content.find("## Next Section")
            # "another real rule" must be inserted BEFORE the next H2 (i.e.
            # inside the Project HARD-RULEs section, after the real bullet).
            self.assertGreater(idx_another, idx_real)
            self.assertLess(idx_another, idx_next)


class CRLFPreservationCase(unittest.TestCase):
    def test_crlf_preserved_on_write(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "CLAUDE.md"
            target.write_bytes(b"# Project\r\n\r\nExisting line.\r\n")
            rc = _run_main(
                "apply",
                "--project-claude-md", str(target),
                "--rule", "crlf rule",
            )
            self.assertEqual(rc, 0)
            raw = target.read_bytes()
            self.assertIn(b"\r\n", raw)
            # Should not produce any lone \n outside of a \r\n.
            lone_lf = raw.count(b"\n") - raw.count(b"\r\n")
            self.assertEqual(lone_lf, 0)


class SymlinkAtomicWriteCase(unittest.TestCase):
    def test_symlink_target_modified_and_symlink_preserved(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            real = root / "real.md"
            real.write_text("# Project\n\nstuff\n", encoding="utf-8")
            link = root / "CLAUDE.md"
            link.symlink_to(real)
            rc = _run_main(
                "apply",
                "--project-claude-md", str(link),
                "--rule", "via-symlink rule",
            )
            self.assertEqual(rc, 0)
            self.assertTrue(link.is_symlink(), "symlink should be preserved")
            self.assertEqual(link.resolve(), real.resolve())
            self.assertIn("via-symlink rule", real.read_text(encoding="utf-8"))


class SuppressCase(unittest.TestCase):
    def test_suppress_writes_entry(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            rc = _run_main(
                "suppress",
                "--project-id", "/proj/x",
                "--rule", "skip me",
                env_state_dir=state_dir,
            )
            self.assertEqual(rc, 0)
            data = json.loads(
                (state_dir / "hard-rules-suppressed.json").read_text("utf-8")
            )
            entries = data["/proj/x"]["suppressed"]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["hash"], directive_hash("skip me"))
            self.assertEqual(entries[0]["directive"], "skip me")
            self.assertIn("ts", entries[0])

    def test_suppress_dedupes_by_hash(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            _run_main(
                "suppress",
                "--project-id", "/proj/x",
                "--rule", "rule a",
                env_state_dir=state_dir,
            )
            rc = _run_main(
                "suppress",
                "--project-id", "/proj/x",
                "--rule", "rule a",  # same hash
                "--rule", "rule b",
                env_state_dir=state_dir,
            )
            self.assertEqual(rc, 0)
            data = json.loads(
                (state_dir / "hard-rules-suppressed.json").read_text("utf-8")
            )
            entries = data["/proj/x"]["suppressed"]
            self.assertEqual(len(entries), 2)
            hashes = {e["hash"] for e in entries}
            self.assertEqual(
                hashes,
                {directive_hash("rule a"), directive_hash("rule b")},
            )

    def test_corrupted_state_quarantined(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            state_file = state_dir / "hard-rules-suppressed.json"
            state_file.write_text("not json {{{", encoding="utf-8")
            rc = _run_main(
                "suppress",
                "--project-id", "/proj/y",
                "--rule", "after corruption",
                env_state_dir=state_dir,
            )
            self.assertEqual(rc, 0)
            # New state file should be valid JSON.
            data = json.loads(state_file.read_text("utf-8"))
            self.assertIn("/proj/y", data)
            # A backup should exist.
            baks = list(state_dir.glob("hard-rules-suppressed.json.bak.*"))
            self.assertGreaterEqual(len(baks), 1)


class ListSuppressedCase(unittest.TestCase):
    def test_list_all(self):
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            _run_main(
                "suppress",
                "--project-id", "/proj/x",
                "--rule", "rule a",
                env_state_dir=state_dir,
            )
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = _run_main("list-suppressed", env_state_dir=state_dir)
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn("/proj/x", out)
            self.assertIn(directive_hash("rule a"), out)

    def test_list_no_state_file(self):
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = _run_main("list-suppressed", env_state_dir=state_dir)
            self.assertEqual(rc, 0)
            self.assertIn("no suppression state", buf.getvalue())


class UnsuppressCase(unittest.TestCase):
    def test_unsuppress_specific_hash(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            _run_main(
                "suppress",
                "--project-id", "/proj/x",
                "--rule", "rule a",
                "--rule", "rule b",
                env_state_dir=state_dir,
            )
            rc = _run_main(
                "unsuppress",
                "--project-id", "/proj/x",
                "--hash", directive_hash("rule a"),
                env_state_dir=state_dir,
            )
            self.assertEqual(rc, 0)
            data = json.loads(
                (state_dir / "hard-rules-suppressed.json").read_text("utf-8")
            )
            entries = data["/proj/x"]["suppressed"]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["hash"], directive_hash("rule b"))

    def test_unsuppress_all_clears_project(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            _run_main(
                "suppress",
                "--project-id", "/proj/x",
                "--rule", "a",
                env_state_dir=state_dir,
            )
            rc = _run_main(
                "unsuppress",
                "--project-id", "/proj/x",
                "--all",
                env_state_dir=state_dir,
            )
            self.assertEqual(rc, 0)
            data = json.loads(
                (state_dir / "hard-rules-suppressed.json").read_text("utf-8")
            )
            self.assertNotIn("/proj/x", data)


class ErrorPathCase(unittest.TestCase):
    def test_apply_zero_rules_errors(self):
        # argparse rejects missing required --rule on its own (exit 2).
        # We invoke as subprocess to capture argparse's exit cleanly.
        proc = subprocess.run(
            [
                sys.executable,
                str(_META / "apply_project_hard_rules.py"),
                "apply",
                "--project-claude-md", "/tmp/some-file.md",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_apply_rule_too_long_errors(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "CLAUDE.md"
            target.write_text("# x\n", encoding="utf-8")
            rc = _run_main(
                "apply",
                "--project-claude-md", str(target),
                "--rule", "x" * 1000,
            )
            self.assertEqual(rc, 2)

    def test_apply_target_is_directory_errors(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "somedir"
            target.mkdir()
            rc = _run_main(
                "apply",
                "--project-claude-md", str(target),
                "--rule", "any",
            )
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
