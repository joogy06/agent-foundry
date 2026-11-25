#!/usr/bin/env python3
"""Tests for cross-tool-portability/scripts/verify-skill-portability.sh (#344 WP-7, DW-3).

The verifier accepts the frontmatter keys the audit accepts and holds no list of its own:

  accepts     `metadata:` plus a Claude Code key; every key on the audit's two lists
  rejects     an unknown top-level key, and says where custom data goes
  one list    the keys are READ from skill_audit.py at run time: a stand-in audit module
              with a different list changes what the script accepts, and the script's own
              text names none of the optional keys
  fail closed without skill_audit.py nothing is accepted (exit 7)
  description an opening "Use when" is an error; subject first passes

Writes only under a TemporaryDirectory.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
REPO = SKILL.parents[1]
SCRIPT = SKILL / "cross-tool-portability" / "scripts" / "verify-skill-portability.sh"
AUDIT = REPO / "skills" / "_meta" / "skill_audit.py"

GOOD_DESCRIPTION = ("Widget calibration: tolerances and drift checks. "
                    "Use when a widget reading looks off.")
BODY = "\n# Fixture\n\n## Anti-Patterns\n\n| Don't | Why |\n|---|---|\n| x | y |\n"


def _audit():
    spec = importlib.util.spec_from_file_location("skill_audit_for_verify_test", AUDIT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sa = _audit()


class VerifyCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def skill(self, name: str, extra: str = "", description: str = GOOD_DESCRIPTION) -> Path:
        directory = self.tmp / name
        directory.mkdir()
        path = directory / "SKILL.md"
        path.write_text(f'---\nname: {name}\ndescription: "{description}"\n{extra}---\n{BODY}',
                        encoding="utf-8")
        return path

    def run_script(self, path: Path, audit_py: str | None = None):
        env = dict(os.environ)
        env.pop("SKILL_AUDIT_PY", None)
        if audit_py is not None:
            env["SKILL_AUDIT_PY"] = audit_py
        return subprocess.run(["bash", str(SCRIPT), str(path)], capture_output=True,
                              text=True, env=env, timeout=60)


class Keys(VerifyCase):
    def test_accepts_metadata_plus_a_claude_code_key(self):
        path = self.skill("good", 'disable-model-invocation: true\nmetadata:\n'
                                  '  version: "1.0.0"\n  family: "widgets"\n')
        r = self.run_script(path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("every top-level key is a specification key or a Claude Code key",
                      r.stdout)
        self.assertIn("PASS", r.stdout)
        # the Claude Code key is accepted, and named as Claude Code only
        self.assertIn("[WARN] Claude Code key(s): disable-model-invocation", r.stdout)

    def test_rejects_an_unknown_top_level_key(self):
        path = self.skill("bad", 'tags: [a, b]\nversion: 1.0.0\nmetadata:\n  family: "w"\n')
        r = self.run_script(path)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("neither specification nor Claude Code keys", r.stderr)
        self.assertRegex(r.stderr, r"(?m)^\s+tags$")
        self.assertRegex(r.stderr, r"(?m)^\s+version$")
        self.assertIn("custom data goes under 'metadata:' as quoted strings", r.stderr)
        self.assertNotIn("PASS", r.stdout)

    def test_a_key_under_metadata_is_never_read_as_a_top_level_key(self):
        path = self.skill("nested", 'metadata:\n  tags: "a, b"\n  version: "1.0.0"\n')
        r = self.run_script(path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_every_key_the_audit_allows_is_accepted(self):
        optional = sorted(sa.ALLOWED_KEYS - {"name", "description", "metadata"})
        self.assertGreater(len(optional), 10)
        extra = "".join(f'{key}: "x"\n' for key in optional) + 'metadata:\n  k: "v"\n'
        r = self.run_script(self.skill("all-keys", extra))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class OneList(VerifyCase):
    def stand_in(self, spec_keys, claude_code_keys) -> str:
        path = self.tmp / "stand_in_audit.py"
        path.write_text(
            f"SPEC_KEYS = {tuple(spec_keys)!r}\nCLAUDE_CODE_KEYS = {tuple(claude_code_keys)!r}\n"
            "DESCRIPTION_SPEC_MAX_CHARS = 1024\nDESCRIPTION_LIMIT = 250\n", encoding="utf-8")
        return str(path)

    def test_the_list_is_read_from_the_audit_module_at_run_time(self):
        stand_in = self.stand_in(("name", "description", "metadata"), ("zzz-invented",))
        accepted = self.skill("invented", 'zzz-invented: "x"\n')
        r = self.run_script(accepted, audit_py=stand_in)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # the same key is unknown to the real audit ...
        r = self.run_script(accepted)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertRegex(r.stderr, r"(?m)^\s+zzz-invented$")
        # ... and a real Claude Code key is unknown to the stand-in
        real = self.skill("real", "model: inherit\n")
        self.assertEqual(self.run_script(real).returncode, 0)
        r = self.run_script(real, audit_py=stand_in)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertRegex(r.stderr, r"(?m)^\s+model$")

    def test_the_script_holds_no_copy_of_the_list(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("SPEC_KEYS", source)
        self.assertIn("CLAUDE_CODE_KEYS", source)
        # name, description and metadata are named in messages; no other legal key is.
        for key in sorted(sa.ALLOWED_KEYS - {"name", "description", "metadata"}):
            self.assertNotRegex(source, r"(?<![\w-])" + key + r"(?![\w-])",
                                f"`{key}` is written into the script")

    def test_without_the_audit_module_nothing_is_accepted(self):
        path = self.skill("good")
        for audit_py in (str(self.tmp / "absent.py"), self.stand_in((), ())):
            r = self.run_script(path, audit_py=audit_py)
            self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
            self.assertNotIn("PASS", r.stdout)
            self.assertIn("skill_audit.py", r.stderr)

    def test_the_default_audit_path_is_the_meta_directory_beside_the_skill(self):
        r = self.run_script(self.skill("good"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"python3 {AUDIT} audit --root {self.tmp} --only good --strict",
                      r.stdout)


class Description(VerifyCase):
    def test_an_opening_use_when_is_an_error(self):
        for opening in ("Use when a widget reading looks off.",
                        "use  when widgets drift."):
            with self.subTest(opening=opening):
                name = "uw-" + str(len(opening))
                r = self.run_script(self.skill(name, description=opening))
                self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
                self.assertIn("description opens with 'Use when'", r.stderr)

    def test_a_single_quoted_use_when_is_still_seen(self):
        directory = self.tmp / "sq"
        directory.mkdir()
        path = directory / "SKILL.md"
        path.write_text("---\nname: sq\ndescription: 'Use when widgets drift.'\n---\n" + BODY,
                        encoding="utf-8")
        r = self.run_script(path)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("description opens with 'Use when'", r.stderr)

    def test_subject_first_with_a_later_use_when_passes_clean(self):
        r = self.run_script(self.skill("good"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("description does not open with 'Use when'", r.stdout)
        self.assertNotIn("never says when", r.stdout)

    def test_a_description_with_no_when_clause_is_a_warning_only(self):
        r = self.run_script(self.skill("nowhen", description="Widget calibration tables."))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[WARN] description never says when to use the skill", r.stdout)

    def test_over_the_audit_limit_warns_and_over_the_spec_limit_fails(self):
        over_limit = "Widget calibration. Use when needed. " + "x" * sa.DESCRIPTION_LIMIT
        r = self.run_script(self.skill("long", description=over_limit))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"the audit's limit is {sa.DESCRIPTION_LIMIT}", r.stdout)
        over_spec = "Widget calibration. Use when needed. " + "x" * sa.DESCRIPTION_SPEC_MAX_CHARS
        r = self.run_script(self.skill("too-long", description=over_spec))
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn(f"(max {sa.DESCRIPTION_SPEC_MAX_CHARS})", r.stderr)


class OwnSkill(unittest.TestCase):
    def test_research_for_skills_passes_its_own_verifier(self):
        env = dict(os.environ)
        env.pop("SKILL_AUDIT_PY", None)
        r = subprocess.run(["bash", str(SCRIPT), str(SKILL / "SKILL.md")],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
