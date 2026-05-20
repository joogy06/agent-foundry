"""test_lint_portability.py — corpus contamination guard.

This test runs the lint_registry.py script in 'portability-only' mode against
the actual installed skill corpora at:

    ~/.claude/skills/
    ~/.codex/skills/

The portability pass scans every SKILL.md body for slash-command tokens from
our own registry/*.yaml. Any genuine reference to a Claude Code slash command
inside a portable (cross-CLI) skill body is a contamination violation.

The test asserts:

  1. The lint pass returns CLEAN against the current corpus (acceptance criterion).
  2. Inserting a fake contamination into a temp skill body causes the lint to
     flag it. This guards against the lint silently degrading into a no-op.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import lint_registry


_REG_DIR = Path(__file__).resolve().parent.parent / "registry"


def test_lint_passes_against_current_corpus():
    """Acceptance criterion: portability pass is clean against ~/.claude + ~/.codex."""
    roots = [Path.home() / ".claude" / "skills",
             Path.home() / ".codex"  / "skills"]
    scanned, violations = lint_registry.portability_pass(_REG_DIR, roots)
    assert scanned > 0, "no skills were scanned — corpus path wrong?"
    assert violations == [], \
        f"contamination detected in {len(violations)} place(s):\n  " + \
        "\n  ".join(violations[:20])


def test_lint_catches_injected_slash_command(tmp_path):
    """Insert a synthetic SKILL.md that contains `/verify` and assert the lint flags it."""
    fake_root = tmp_path / "fake-skills"
    fake_root.mkdir()

    bad_skill = fake_root / "bad-skill"
    bad_skill.mkdir()
    (bad_skill / "SKILL.md").write_text(
        "---\nname: bad\ndescription: stub\n---\n\n"
        "Use this and then run /verify to drive the UI.\n",
        encoding="utf-8",
    )

    scanned, violations = lint_registry.portability_pass(_REG_DIR, [fake_root])
    assert scanned == 1
    assert any("/verify" in v for v in violations), \
        f"expected /verify violation, got: {violations}"


def test_lint_does_not_flag_run_inside_docker_tmpfs(tmp_path):
    """Defensive regression: '/run' inside a --tmpfs example should not flag."""
    fake_root = tmp_path / "fake-skills"
    fake_root.mkdir()

    safe_skill = fake_root / "docker-example"
    safe_skill.mkdir()
    (safe_skill / "SKILL.md").write_text(
        "---\nname: docker-example\ndescription: stub\n---\n\n"
        "```\ndocker run -d --read-only --tmpfs /run:rw,noexec myapp\n```\n",
        encoding="utf-8",
    )

    scanned, violations = lint_registry.portability_pass(_REG_DIR, [fake_root])
    assert scanned == 1
    assert violations == [], \
        f"unexpected hits on docker tmpfs example: {violations}"


def test_lint_does_not_flag_schtasks_slash_flags(tmp_path):
    """Defensive regression: Windows `schtasks /run /tn ...` should not flag."""
    fake_root = tmp_path / "fake-skills"
    fake_root.mkdir()

    win = fake_root / "windows-example"
    win.mkdir()
    (win / "SKILL.md").write_text(
        "---\nname: windows-example\ndescription: stub\n---\n\n"
        "Run a scheduled task immediately:\n\n"
        "```\nschtasks /run /tn \"NightlyBackup\"\n```\n",
        encoding="utf-8",
    )

    scanned, violations = lint_registry.portability_pass(_REG_DIR, [fake_root])
    assert scanned == 1
    assert violations == [], \
        f"unexpected hits on schtasks example: {violations}"


def test_lint_catches_diff_token(tmp_path):
    """A second slash-command token from a different family must also be caught."""
    fake_root = tmp_path / "fake-skills"
    fake_root.mkdir()

    bad = fake_root / "bad2"
    bad.mkdir()
    (bad / "SKILL.md").write_text(
        "---\nname: bad2\ndescription: stub\n---\n\n"
        "After implementation, run /diff and then /compact the context.\n",
        encoding="utf-8",
    )

    scanned, violations = lint_registry.portability_pass(_REG_DIR, [fake_root])
    assert scanned == 1
    cmds = [v.split("'")[1] for v in violations if "'" in v]
    assert "/diff" in cmds
    assert "/compact" in cmds
