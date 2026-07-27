#!/usr/bin/env python3
"""test_worktree_merge.py — WP-9 (S055 §6.6 / R17).

Covers: forbidden-path diff rejected; clean diff applied; rejection fails the
WP and drops NOTHING silently; every forbidden path in the list is detected.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_META_DIR = Path(__file__).resolve().parent.parent
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

import worktree_merge as wm  # noqa: E402


def _diff_touching(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )


class ForbiddenPathDetection(unittest.TestCase):
    def test_each_forbidden_path_rejected(self):
        for path in [
            ".ledger/requests/x.request.yaml",
            "progress/integration-ledger.md",
            ".bob-checkpoint.md",
            "progress/work-packages.yaml",
            ".forge/session.key",
            "progress/workflow-runs.jsonl",
        ]:
            clean, hits = wm.check_diff(_diff_touching(path))
            self.assertFalse(clean, f"{path} should be forbidden")
            self.assertIn(path, hits)

    def test_clean_path_allowed(self):
        clean, hits = wm.check_diff(_diff_touching("src/demo/api.py"))
        self.assertTrue(clean)
        self.assertEqual(hits, [])

    def test_nested_ledger_path_rejected(self):
        clean, hits = wm.check_diff(_diff_touching(".ledger/evidence/comp/x.bundle.json"))
        self.assertFalse(clean)

    def test_delete_of_forbidden_path_caught(self):
        # A delete still names the path in the git-diff header.
        d = (
            "diff --git a/.bob-checkpoint.md b/.bob-checkpoint.md\n"
            "deleted file mode 100644\n"
            "--- a/.bob-checkpoint.md\n"
            "+++ /dev/null\n"
        )
        clean, hits = wm.check_diff(d)
        self.assertFalse(clean)
        self.assertIn(".bob-checkpoint.md", hits)


class ApplyMerge(unittest.TestCase):
    def setUp(self):
        self.canon = Path(tempfile.mkdtemp(prefix="canon-"))
        subprocess.run(["git", "init", "-q", str(self.canon)], check=True)
        subprocess.run(["git", "-C", str(self.canon), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(self.canon), "config", "user.name", "t"], check=True)
        (self.canon / "src").mkdir()
        (self.canon / "src" / "api.py").write_text("old\n")
        subprocess.run(["git", "-C", str(self.canon), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.canon), "commit", "-qm", "init"], check=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.canon, ignore_errors=True)

    def test_clean_diff_applies(self):
        diff = (
            "diff --git a/src/api.py b/src/api.py\n"
            "--- a/src/api.py\n"
            "+++ b/src/api.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        ok, msg = wm.apply_diff(self.canon, diff)
        self.assertTrue(ok, msg)
        self.assertEqual((self.canon / "src" / "api.py").read_text(), "new\n")

    def test_forbidden_diff_refused_drops_nothing(self):
        before = (self.canon / "src" / "api.py").read_text()
        diff = _diff_touching("progress/integration-ledger.md")
        ok, msg = wm.apply_diff(self.canon, diff)
        self.assertFalse(ok)
        self.assertIn("REJECTED", msg)
        # Nothing was applied/dropped: canonical tree unchanged, no ledger file created.
        self.assertEqual((self.canon / "src" / "api.py").read_text(), before)
        self.assertFalse((self.canon / "progress" / "integration-ledger.md").exists())


if __name__ == "__main__":
    unittest.main()
