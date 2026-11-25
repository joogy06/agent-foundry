"""test_skill_corpus.py -- the two readers a test uses on a split skill (#344 WP-4).

`corpus()` is what an ABSENT assertion reads, so the property worth pinning is that text in a
reference is in it; `file_of()` is what a location pin reads, so the property worth pinning is
that it refuses to answer when the needle is in no file or in two.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import skill_corpus  # noqa: E402

_SKILLS = _HERE.parents[1]


@pytest.fixture()
def tree(tmp_path):
    skill = tmp_path / "demo"
    (skill / "references").mkdir(parents=True)
    (skill / "tests").mkdir()
    (skill / "SKILL.md").write_text("# entry\nonly-in-entry\nin-two-files\n", encoding="utf-8")
    (skill / "references" / "02-b.md").write_text("only-in-b\nin-two-files\nends-b", encoding="utf-8")
    (skill / "references" / "01-a.md").write_text("starts-a\nonly-in-a\n", encoding="utf-8")
    (skill / "references" / "notes.txt").write_text("not-markdown\n", encoding="utf-8")
    (skill / "tests" / "fixture.md").write_text("only-in-a-test-fixture\n", encoding="utf-8")
    (skill / "patterns.md").write_text("only-beside-the-entry\n", encoding="utf-8")
    (skill / "notes.txt").write_text("beside-but-not-markdown\n", encoding="utf-8")
    return tmp_path


def test_paths_are_the_entry_file_then_the_references_by_name(tree):
    got = [skill_corpus.rel("demo", p, root=tree) for p in skill_corpus.paths("demo", root=tree)]
    assert got == ["SKILL.md", "references/01-a.md", "references/02-b.md"]


def test_the_corpus_holds_reference_text_and_the_entry_file_alone_does_not(tree):
    assert "only-in-a" in skill_corpus.corpus("demo", root=tree)
    assert "only-in-a" not in skill_corpus.read("demo", root=tree)            # the vacuous reader
    assert "not-markdown" not in skill_corpus.corpus("demo", root=tree)
    assert "only-in-a-test-fixture" not in skill_corpus.corpus("demo", root=tree)


def test_a_file_beside_the_entry_is_in_the_corpus_only_on_request(tree):
    # #344 WP-5: codex-orchestration keeps patterns.md and templates.md beside SKILL.md. The default
    # corpus is unchanged (forge's superpowers-tracked.md stays out of every forge test).
    assert "only-beside-the-entry" not in skill_corpus.corpus("demo", root=tree)
    assert skill_corpus.holders("demo", "only-beside-the-entry", root=tree) == []
    got = [skill_corpus.rel("demo", p, root=tree)
           for p in skill_corpus.paths("demo", root=tree, root_level=True)]
    assert got == ["SKILL.md", "references/01-a.md", "references/02-b.md", "patterns.md"]
    whole = skill_corpus.corpus("demo", root=tree, root_level=True)
    assert "only-beside-the-entry" in whole and "only-in-a" in whole
    assert "beside-but-not-markdown" not in whole and "only-in-a-test-fixture" not in whole
    assert skill_corpus.rel("demo", skill_corpus.file_of("demo", "only-beside-the-entry", root=tree,
                                                         root_level=True), root=tree) == "patterns.md"
    assert skill_corpus.text_of("demo", "only-beside-the-entry", root=tree, root_level=True) \
        == "only-beside-the-entry\n"


def test_the_live_codex_orchestration_corpus_reaches_its_root_level_references():
    names = [skill_corpus.rel("codex-orchestration", p, root=_SKILLS)
             for p in skill_corpus.paths("codex-orchestration", root=_SKILLS, root_level=True)]
    assert names[0] == "SKILL.md" and names[-2:] == ["patterns.md", "templates.md"]
    assert [n for n in names[1:-2] if not n.startswith("references/")] == [] and len(names) > 3
    default = [skill_corpus.rel("codex-orchestration", p, root=_SKILLS)
               for p in skill_corpus.paths("codex-orchestration", root=_SKILLS)]
    assert default == names[:-2]


def test_a_needle_cannot_match_across_a_file_boundary(tree):
    # `02-b.md` ends "ends-b" with no newline and nothing follows it; `01-a.md` precedes it.
    assert "only-in-a\nonly-in-b" not in skill_corpus.corpus("demo", root=tree)
    assert "in-two-files\nstarts-a" not in skill_corpus.corpus("demo", root=tree)


def test_file_of_names_the_one_holder_and_refuses_none_or_two(tree):
    assert skill_corpus.rel("demo", skill_corpus.file_of("demo", "only-in-b", root=tree), root=tree) \
        == "references/02-b.md"
    assert skill_corpus.text_of("demo", "only-in-entry", root=tree).startswith("# entry")
    with pytest.raises(AssertionError, match="found 0"):
        skill_corpus.file_of("demo", "in-no-file", root=tree)
    with pytest.raises(AssertionError, match="found 2"):
        skill_corpus.file_of("demo", "in-two-files", root=tree)
    with pytest.raises(AssertionError, match="empty needle"):
        skill_corpus.file_of("demo", "", root=tree)


def test_an_unknown_skill_is_an_error_not_an_empty_corpus(tree):
    with pytest.raises(AssertionError, match="no SKILL.md"):
        skill_corpus.corpus("absent", root=tree)


def test_the_live_forge_corpus_is_the_entry_file_plus_its_step_references():
    names = [skill_corpus.rel("forge", p, root=_SKILLS) for p in skill_corpus.paths("forge", root=_SKILLS)]
    assert names[0] == "SKILL.md" and len(names) > 10
    assert names[1:] == sorted(names[1:]) and all(n.startswith("references/") for n in names[1:])
    # a HARD-RULE tag line is in the entry file and in no reference
    assert all(skill_corpus.rel("forge", p, root=_SKILLS) == "SKILL.md"
               for p in skill_corpus.holders("forge", "\n<HARD-RULE>\n", root=_SKILLS))
