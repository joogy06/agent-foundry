"""skill_corpus.py -- a split skill's text, as a test must read it (#344 WP-4).

A core skill is an entry file (`SKILL.md`) plus one-level references (`references/*.md`).
A test that reads only `SKILL.md` goes wrong in two ways once text has moved out of it:

  * an assertion that some text is ABSENT passes for ever, because the text it guards
    against would now be written in a reference the test never opens;
  * an assertion that some text is PRESENT fails, or -- worse -- is "fixed" by pointing
    it at the whole corpus, which stops it saying where the text has to live.

So there are two readers, and a test picks by what it asserts:

  corpus(skill)            `SKILL.md` + `references/*.md`, in a stable order. For every
                           ABSENT assertion, and for counts over the whole skill.
  file_of(skill, needle)   the ONE file that holds `needle`. For a PRESENT assertion that
                           pins a location: the test then reads that file and nothing else.

Some skills also keep reference files beside `SKILL.md` (codex-orchestration: `patterns.md`,
`templates.md`). They are outside the default corpus; pass `root_level=True` to add every
`*.md` at the skill root, after the references (#344 WP-5). The default is unchanged, so a
test that does not ask for them reads exactly what it read before.

Not a test module (no `test_` prefix): import it from a test after putting this directory
on `sys.path`. Stdlib only. Paths resolve next to this file, so the same code reads the
repo tree and an installed home tree.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

#: `<tree>/skills` -- this file is `<tree>/skills/_meta/tests/skill_corpus.py`.
SKILLS = Path(__file__).resolve().parents[2]

ENTRY = "SKILL.md"
REFERENCES_DIR = "references"

#: What joins two files in `corpus()`. It names the boundary, so a needle can never match
#: across the end of one file and the start of the next.
BOUNDARY = "\n<!-- skill_corpus: file boundary -->\n"


def skill_dir(skill: str, root: Optional[Path] = None) -> Path:
    base = (root or SKILLS) / skill
    if not (base / ENTRY).is_file():
        raise AssertionError(f"no {ENTRY} for skill {skill!r} under {root or SKILLS}")
    return base


def paths(skill: str, root: Optional[Path] = None, root_level: bool = False) -> List[Path]:
    """`SKILL.md` first, then `references/*.md` sorted by name; with `root_level`, then every
    other `*.md` beside `SKILL.md`, sorted by name."""
    base = skill_dir(skill, root)
    refs = base / REFERENCES_DIR
    found = sorted(p for p in refs.glob("*.md") if p.is_file()) if refs.is_dir() else []
    beside = sorted(p for p in base.glob("*.md") if p.is_file() and p.name != ENTRY) if root_level else []
    return [base / ENTRY] + found + beside


def read(skill: str, rel: str = ENTRY, root: Optional[Path] = None) -> str:
    """One file of the skill, by its path relative to the skill directory."""
    return (skill_dir(skill, root) / rel).read_text(encoding="utf-8")


def corpus(skill: str, root: Optional[Path] = None, root_level: bool = False) -> str:
    """The whole skill as one string: `SKILL.md`, then each reference."""
    return BOUNDARY.join(p.read_text(encoding="utf-8") for p in paths(skill, root, root_level))


def holders(skill: str, needle: str, root: Optional[Path] = None, root_level: bool = False) -> List[Path]:
    """Every file of the corpus that holds `needle`, in corpus order."""
    if not needle:
        raise AssertionError("an empty needle is in every file; name the text you mean")
    return [p for p in paths(skill, root, root_level) if needle in p.read_text(encoding="utf-8")]


def file_of(skill: str, needle: str, root: Optional[Path] = None, root_level: bool = False) -> Path:
    """The ONE file holding `needle`. No file, or more than one, is an AssertionError:
    a location pin that could mean two places is not a pin."""
    found = holders(skill, needle, root, root_level)
    if len(found) != 1:
        base = skill_dir(skill, root)
        names = [p.relative_to(base).as_posix() for p in found]
        raise AssertionError(
            f"expected exactly one file of skill {skill!r} to hold {needle!r}, found "
            f"{len(found)}: {names}")
    return found[0]


def rel(skill: str, path: Path, root: Optional[Path] = None) -> str:
    """`path` relative to the skill directory, as a posix string (`references/x.md`)."""
    return path.relative_to(skill_dir(skill, root)).as_posix()


def text_of(skill: str, needle: str, root: Optional[Path] = None, root_level: bool = False) -> str:
    """The text of the one file holding `needle`."""
    return file_of(skill, needle, root, root_level).read_text(encoding="utf-8")
