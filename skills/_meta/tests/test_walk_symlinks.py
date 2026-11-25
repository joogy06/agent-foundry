"""rot_scan and freshness must see skills that a link-mode install exposes as symlinks."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import freshness  # noqa: E402
import review_by_lint  # noqa: E402
import rot_scan  # noqa: E402


def _tree(tmp_path):
    real = tmp_path / "repo" / "skill-a"
    real.mkdir(parents=True)
    (real / "SKILL.md").write_text("x", encoding="utf-8")
    (real / "tool.js").write_text("x", encoding="utf-8")
    root = tmp_path / "home"
    root.mkdir()
    os.symlink(real, root / "skill-a")
    (root / "plain.md").write_text("x", encoding="utf-8")
    return root, real


def test_rot_scan_follows_a_symlinked_skill(tmp_path):
    root, _ = _tree(tmp_path)
    names = {p.relative_to(root).as_posix() for p in freshness.walk_files(root, ("*.md",))}
    assert names == {"plain.md", "skill-a/SKILL.md"}


def test_freshness_follows_a_symlinked_skill(tmp_path):
    root, _ = _tree(tmp_path)
    names = {p.relative_to(root).as_posix() for p in freshness.walk_files(root, ("*.md", "*.js"))}
    assert names == {"plain.md", "skill-a/SKILL.md", "skill-a/tool.js"}


def test_a_link_cycle_ends(tmp_path):
    root, real = _tree(tmp_path)
    os.symlink(root, real / "back")
    assert freshness.walk_files(root, ("*.md",))


def test_a_target_reached_twice_is_scanned_once(tmp_path):
    root, real = _tree(tmp_path)
    os.symlink(real, root / "skill-b")
    hits = [p for p in freshness.walk_files(root, ("*.md",)) if p.name == "SKILL.md"]
    assert len(hits) == 1


def test_rot_scan_targets_follow_a_symlinked_skill(tmp_path):
    root, _ = _tree(tmp_path)
    names = {p.name for p in rot_scan.iter_targets(root, tmp_path / "none")}
    assert "SKILL.md" in names


def test_the_index_skips_tests_and_fixtures_but_not_a_fixture_root(tmp_path):
    root, real = _tree(tmp_path)
    (real / "tests").mkdir()
    (real / "tests" / "t.md").write_text("x", encoding="utf-8")
    (real / "fixtures").mkdir()
    (real / "fixtures" / "f.md").write_text("x", encoding="utf-8")
    assert {p.name for p in freshness._iter_md_files(root)} == {"plain.md", "SKILL.md"}
    assert {p.name for p in freshness._iter_md_files(real / "fixtures")} == {"f.md"}


def test_two_skills_reference_files_keep_distinct_deadline_keys():
    base = freshness.SKILLS_ROOT
    a = freshness._deadline_key(str(base / "a" / "references" / "x.md"))
    b = freshness._deadline_key(str(base / "b" / "references" / "x.md"))
    assert a != b
    assert freshness._deadline_key(str(base / "a" / "SKILL.md")) == "a/SKILL.md"


# Codex review C4: an excluded alias sorts first and used to claim the live skill's real path.
def _aliased(tmp_path, *excluded):
    root = tmp_path / "skills"
    live = root / "zz-live"
    live.mkdir(parents=True)
    (live / "SKILL.md").write_text("x", encoding="utf-8")
    alias = root.joinpath(*excluded)
    alias.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(live, alias)
    return root


def test_an_archived_alias_does_not_hide_a_live_skill_from_freshness(tmp_path):
    root = _aliased(tmp_path, "archive", "zz-live")
    assert [p.relative_to(root).as_posix() for p in freshness._iter_md_files(root)] == ["zz-live/SKILL.md"]


def test_an_archived_alias_does_not_hide_a_live_skill_from_rot_scan(tmp_path):
    root = _aliased(tmp_path, "archive", "zz-live")
    got = [p.relative_to(root).as_posix() for p in rot_scan.iter_targets(root, tmp_path / "none")]
    assert got == ["zz-live/SKILL.md"]


def test_a_fixture_alias_does_not_hide_a_live_skill_from_rot_scan(tmp_path):
    root = _aliased(tmp_path, "tests", "fixtures", "zz-live")
    got = [p.relative_to(root).as_posix() for p in rot_scan.iter_targets(root, tmp_path / "none")]
    assert got == ["zz-live/SKILL.md"]


def test_a_fixture_alias_does_not_hide_a_live_skill_from_review_by_lint(tmp_path):
    root = _aliased(tmp_path, "aa", "tests", "fixtures", "zz-live")
    got = [rel.as_posix() for _p, rel in review_by_lint.iter_tree([root])]
    assert got == ["zz-live/SKILL.md"]


def test_a_pair_skip_needs_both_parts_and_the_root_is_never_pruned(tmp_path):
    root = tmp_path / "tests"
    (root / "keep").mkdir(parents=True)
    (root / "keep" / "a.md").write_text("x", encoding="utf-8")
    (root / "fixtures").mkdir()
    (root / "fixtures" / "b.md").write_text("x", encoding="utf-8")
    assert {p.name for p in freshness.walk_files(root, ("*.md",), {"tests/fixtures"})} == {"a.md", "b.md"}
    assert {p.name for p in freshness.walk_files(root, ("*.md",), {"tests"})} == {"a.md", "b.md"}


def test_an_old_form_deadline_row_migrates_by_its_full_target(tmp_path):
    """C6: the row is matched by target path, so another skill's `references/x.md` row stays."""
    base = freshness.SKILLS_ROOT
    mine, other = str(base / "a" / "references" / "x.md"), str(base / "b" / "references" / "x.md")
    old = freshness._ROW_SENTINEL.format(key="references/x.md")
    tasks = tmp_path / "tasks.md"
    tasks.write_text(f"- [ ] old row `{mine}` {old}\n- [ ] other row `{other}` {old}\n", encoding="utf-8")
    updated, inserted = freshness.upsert_tasks_md(tasks, [{"target": mine, "date": "2027-01-01"}])
    assert (updated, inserted) == (1, 0)
    text = tasks.read_text(encoding="utf-8")
    assert "old row" not in text and "other row" in text
    assert freshness._ROW_SENTINEL.format(key="a/references/x.md") in text
    assert freshness.upsert_tasks_md(tasks, [{"target": mine, "date": "2027-01-01"}]) == (1, 0)   # stable

