"""Tests for sync_metadata.py — the catalog README + GitHub About reconciler."""
import importlib.util as ilu
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sync_metadata.py"


def _load():
    spec = ilu.spec_from_file_location("_sync_metadata_t", SCRIPT)
    m = ilu.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def test_excluded_matches_dirs_and_globs():
    m = _load()
    ex = ["skills/entrepreneur-webstore", "state/", "**/__pycache__"]
    assert m._excluded("skills/entrepreneur-webstore", ex)
    assert m._excluded("skills/foo/__pycache__", ex)
    assert m._excluded("state/freshness", ex)
    assert not m._excluded("skills/forge", ex)


def test_live_counts_applies_exclusions(tmp_path):
    m = _load()
    root = tmp_path / ".claude"
    (root / "skills" / "forge").mkdir(parents=True)
    (root / "skills" / "env-readiness").mkdir(parents=True)
    (root / "skills" / "entrepreneur-webstore").mkdir(parents=True)  # excluded
    (root / "agents").mkdir(parents=True)
    (root / "agents" / "bob.md").write_text("x")
    (root / "agents" / "alf.md").write_text("x")
    cfg = {"source": {"root": str(root), "subdirs": ["skills", "agents"]},
           "exclusions": ["skills/entrepreneur-webstore"]}
    c = m.live_counts(cfg)
    assert c["skills"] == 2, c   # 3 dirs minus 1 excluded
    assert c["agents"] == 2, c


def test_readme_fixes_stale_counts_and_bumps_version(tmp_path):
    m = _load()
    rd = tmp_path / "README.md"
    rd.write_text(
        "> **Version:** 1.1.0 · **Last published:** 2026-01-01 · "
        "**159 skills · 4 agents · 8 workflows · 2 commands**\n\n"
        "- **159 skills** — stuff\n- **4 agents** — stuff\n- **8 saved workflows** — stuff\n"
    )
    counts = {"skills": 182, "agents": 5, "workflows": 9, "commands": 2}
    changes = m.sync_readme(rd, counts, "2026-06-23", bump="minor")
    out = rd.read_text()
    assert "**182 skills**" in out and "**5 agents**" in out and "**9 saved workflows**" in out
    assert "**182 skills · 5 agents · 9 workflows · 2 commands**" in out
    assert "**Last published:** 2026-06-23" in out
    assert "**Version:** 1.2.0" in out          # minor bump from 1.1.0
    assert changes                               # reported changes
    # idempotent: a second run with same counts/date and no bump = no change
    assert m.sync_readme(rd, counts, "2026-06-23", bump=None) == []


def test_readme_does_not_corrupt_changelog_or_body_prose(tmp_path):
    """Count rewrites are anchored to `- **N skills**` bullets — changelog history
    (`159 -> **182 skills**`) and inline bold prose must NOT be touched (Codex #2)."""
    m = _load()
    rd = tmp_path / "README.md"
    rd.write_text(
        "- **159 skills** — the live catalog bullet\n\n"
        "## Changelog\n"
        "- Counts: 159 -> **182 skills**, 4 -> **5 agents**\n"
        "Inline note about **3 skills** in a sentence.\n"
    )
    m.sync_readme(rd, {"skills": 200, "agents": 9, "workflows": 9, "commands": 2}, "2026-06-23", None)
    out = rd.read_text()
    assert "- **200 skills** — the live catalog bullet" in out      # the bullet WAS updated
    assert "159 -> **182 skills**, 4 -> **5 agents**" in out         # changelog UNTOUCHED
    assert "**3 skills** in a sentence" in out                       # inline prose UNTOUCHED


def test_about_substitutes_counts():
    m = _load()
    cfg = {"about": {"o/r": {"description": "{skills} skills + {agents} agents", "topics": ["x"]}}}
    a = m.about_for(cfg, "o/r", {"skills": 182, "agents": 5, "workflows": 9, "commands": 2})
    assert a["description"] == "182 skills + 5 agents"
    assert a["topics"] == ["x"]


def test_about_missing_block_returns_none():
    m = _load()
    assert m.about_for({"about": {}}, "o/r", {"skills": 1, "agents": 1, "workflows": 1, "commands": 1}) is None
