"""Regression tests: an installed tree made of symlinks into a repo (2026-11-25).

The engine used to (1) skip symlinked skill directories, staging no skills, and (2) copy
symlinked files as links, so the scrub phase wrote its replacements through the link into the
live repo files. Both must stay fixed: staging holds real content, and the live tree is never
written.
"""
import importlib.util as ilu
import os
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "publish_prep.py"


def _load():
    spec = ilu.spec_from_file_location("_publish_prep_links", SCRIPT)
    m = ilu.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def _linked_home(tmp_path):
    repo = tmp_path / "repo"
    (repo / "skills" / "alpha").mkdir(parents=True)
    (repo / "skills" / "alpha" / "SKILL.md").write_text("path /private/x\n", encoding="utf-8")
    (repo / "agents").mkdir()
    (repo / "agents" / "a.md").write_text("see /private/y\n", encoding="utf-8")
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    (home / "agents").mkdir()
    os.symlink(repo / "skills" / "alpha", home / "skills" / "alpha")
    os.symlink(repo / "agents" / "a.md", home / "agents" / "a.md")
    return repo, home


def _stage(m, home, stg):
    for sub in ("skills", "agents"):
        m.copy_tree_with_exclusions(home / sub, stg, home, exclusions=[])


def test_symlinked_skill_dir_is_staged_as_real_files(tmp_path):
    m = _load()
    repo, home = _linked_home(tmp_path)
    stg = tmp_path / "stg"
    _stage(m, home, stg)
    staged = stg / "skills" / "alpha" / "SKILL.md"
    assert staged.is_file() and not staged.is_symlink()
    assert not (stg / "agents" / "a.md").is_symlink()
    unexplained, _ = m.check_skill_completeness(home, stg, exclusions=[])
    assert unexplained == []


def test_scrub_never_writes_through_to_the_live_tree(tmp_path):
    m = _load()
    repo, home = _linked_home(tmp_path)
    stg = tmp_path / "stg"
    _stage(m, home, stg)
    scrubs = [{"file": f, "replacements": [{"find": "/private", "replace": "/path/to"}]}
              for f in ("skills/alpha/SKILL.md", "agents/a.md")]
    res = m.apply_scrubs(stg, scrubs)
    assert [r["status"] for r in res] == ["modified", "modified"]
    assert (repo / "skills" / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "path /private/x\n"
    assert (repo / "agents" / "a.md").read_text(encoding="utf-8") == "see /private/y\n"
    assert "/path/to/y" in (stg / "agents" / "a.md").read_text(encoding="utf-8")


def test_scrub_refuses_a_staged_symlink(tmp_path):
    m = _load()
    live = tmp_path / "live.md"
    live.write_text("secret\n", encoding="utf-8")
    stg = tmp_path / "stg"
    stg.mkdir()
    os.symlink(live, stg / "x.md")
    res = m.apply_scrubs(stg, [{"file": "x.md", "replacements": [{"find": "secret", "replace": "s"}]}])
    assert res[0]["status"] == "refused-outside-staging"
    assert live.read_text(encoding="utf-8") == "secret\n"


def test_dangling_link_is_kept_for_the_scan(tmp_path):
    m = _load()
    home = tmp_path / "home"
    (home / "skills" / "beta").mkdir(parents=True)
    (home / "skills" / "beta" / "SKILL.md").write_text("b\n", encoding="utf-8")
    os.symlink(tmp_path / "gone", home / "skills" / "beta" / "ref.md")
    stg = tmp_path / "stg"
    m.copy_tree_with_exclusions(home / "skills", stg, home, exclusions=[])
    assert (stg / "skills" / "beta" / "ref.md").is_symlink()


def test_link_loop_terminates(tmp_path):
    m = _load()
    home = tmp_path / "home"
    (home / "skills" / "gamma").mkdir(parents=True)
    (home / "skills" / "gamma" / "SKILL.md").write_text("g\n", encoding="utf-8")
    os.symlink(home / "skills", home / "skills" / "gamma" / "loop")
    stg = tmp_path / "stg"
    m.copy_tree_with_exclusions(home / "skills", stg, home, exclusions=[])
    assert (stg / "skills" / "gamma" / "SKILL.md").is_file()


def test_dated_hand_backup_is_excluded(tmp_path):
    m = _load()
    assert m.should_exclude(Path("skills/_meta/x.py.bak-20260916-argv"), [])
    assert not m.should_exclude(Path("skills/_meta/x.py"), [])
