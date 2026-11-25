#!/usr/bin/env python3
"""skill_audit.py -- #344. Audit skills against the Anthropic skill standard, and prove
that a split moved text without changing it.

    audit [--root DIR] [--only NAMES] [--json] [--strict] [--verbose]
    check [--repo DIR] [--index | --tree] [--paths-from -] [--] FILE...  (pre-commit arm)
    listing-budget [--root DIR] [--fraction F] [--context-tokens N] [--json]
    inventory SKILL [--root DIR] [--ref REF] [--against REF] [--json]
    conserve --before REF --skill SKILL [--root DIR] [--manifest FILE] [--json]

The default root is the REPO `skills/` tree this file sits in (`<repo>/skills`), never
`~/.claude/skills`: the home tree is installer output, and the repo is what a commit
changes.

RULES (a `fail` blocks only for a skill on the conformant list; see LEVELS)

  A1   top-level frontmatter key outside the spec set and the Claude Code set, a key
       that appears twice, or a column-0 frontmatter line that is not a `key:` line at
       all (a quoted key, a flow map, a stray word)
  A2   a `metadata` value that is not a string (a number, boolean, null, date or
       sexagesimal as YAML types it; a tagged, anchored or aliased value), a line
       under `metadata` that is not `key: value`, or `metadata` that is not a mapping
  A3   `name`: missing, over 64 chars, bad charset, holding a reserved word, or not
       equal to the skill's directory name
  A4   `description` missing, not decodable, over 1024 chars, or holding an XML-like
       tag once DECODED (`"\x3ctag\x3e"` is a tag)
  A5   `description` over its limit (250; see DESCRIPTION_LIMIT_OVERRIDES) or opening
       with "Use when"
  A6   SKILL.md over 500 lines
  A7   a reference .md under the skill that SKILL.md does not name, and no other
       reference names either
  A8   a reference .md over 100 lines with no contents list in its first 30 lines
  A9   a hard-coded home path to the skill's OWN directory, on a line that is not on
       the exemption list
  A10  a reference that SKILL.md does not name and only another reference does (nested)
  A11  a HARD-RULE or HARD-GATE block that starts at or after byte 20,000 of SKILL.md,
       or that has no closing tag
  N1   SKILL.md over about 5,000 tokens (bytes / 4)                              note
  N2   a home path to a shared helper or another skill; or an exempt A9 line     note

DEFINITIONS, so a finding can be reproduced by hand

  reference    every `*.md` under the skill directory except its SKILL.md, skipping the
               directories in NON_REFERENCE_DIRS, hidden directories, and any
               sub-directory that holds its own SKILL.md (a nested skill, listed in the
               JSON as `nested_skills` and NOT audited).
  named        the file's path relative to the skill directory appears in SKILL.md
               (`references/x.md`); a longer spelling that ends in it counts.
  contents     in the first 30 lines, a line that reads `Contents` or `Table of
  list         contents`, as a heading (`## Contents`), in bold (`**Contents**`) or
               plain (`Contents:`), in any letter case.
  home path    `~/.claude/skills/<name>`, `$HOME/.claude/skills/<name>` or
               `${HOME}/.claude/skills/<name>`; scanned in SKILL.md and every reference.
  tag line     `<HARD-RULE>` / `<HARD-GATE>` (attributes allowed) as the FIRST thing on
               a line, after optional indentation. A prose mention of the words, or
               the tag in inline code, is never a tag line. A block runs to its
               closing tag; one with none ends before the next tag line (or at the
               end of the file) and is reported as unterminated.

FRONTMATTER. Read by a small stdlib reader that FAILS CLOSED: what it does not recognise
is a finding, never a value glued onto the key above. When PyYAML is importable and the
header is valid YAML, its typed reading is a SECOND check on top (a key, a non-string
`metadata` value or a decoded tag in the description that the stdlib reader missed).

LEVELS. Every A-rule finding is a `fail`. Whether it BLOCKS depends on the skill: a
skill named in `standard-conformant.txt` (beside this file, or beside the audited repo's
`skills/_meta/` for `check`) is held to the rules, so `audit` exits 1 and `check` prints
`SA-E`; for any other skill the same finding is reported (`SA-W`) and the exit code is
0. `--strict` holds every audited skill to the rules (a skill written into a temp
directory is on no list). Notes are printed in their own section with counts and never
change the exit code.

CHECK reads what is being COMMITTED. When `--repo` is the top of a git checkout, the
skill's files, `standard-conformant.txt` and `standard-exemptions.json` are read from the
git INDEX, so an unstaged edit can neither hide a staged failure nor change which skills
are held to the rules. `--tree` reads the working tree instead (a look before staging);
outside a checkout the tree is all there is, and `--index` is then refused. A `--repo`
BELOW the top of a checkout is refused (exit 2) unless `--tree` is given, and a SKILL.md
staged as a symbolic link is a finding (A3), since no skill can be read from it.

A9 EXEMPTIONS are explicit data in `standard-exemptions.json`: per skill, a `file`, the
exact `line` text and a one-line `reason`. An own-directory home path on a listed line
is demoted to an N2 note; on any other line it fails.

CONSERVE compares two corpora of one skill: at REF (`git show`) and now. A corpus is
SKILL.md plus every reference .md plus the manifest's `extra_files`. For every non-blank
line the count now must equal the count at REF, minus the manifest's deletes, plus its
adds. Inside each file now, lines that occur exactly once on both sides must keep the
order they had in their old file. Every OTHER line (a fence, a table rule, a line that
repeats) must answer to its own old occurrence, each old occurrence answering for one
new line: between two neighbours from the same old file it must come from the old lines
between them, in order; before the first neighbour of a file or after its last, from
the old lines next to that neighbour. The manifest excuses a COUNT, never a text: `adds:
fi x1` lets one new `fi` go without an old occurrence, and every other `fi` is held to
the rule above (a line that is added and deleted once each is a declared move). A span
that moved out of order is legal only when the manifest records it under `reorders` (an
old SKILL.md line range and the file it went to); it must then sit there whole and in
order, and the lines around it are held to the neighbours on either side of it, as if
the span were not there. A HARD-RULE /
HARD-GATE block that was in SKILL.md must still be in SKILL.md, unless the manifest
records where it went under `block_moves`; `inventory --against` holds the same rule.

`.split-manifest.json` (beside the skill's SKILL.md), every entry with a `reason`:

    {"schema": "split-manifest.v1", "skill": "forge",
     "extra_files": ["_meta/codex_top_seat.sh"],            # relative to the skills root
     "deletes":  [{"text": "<line>", "count": 2, "reason": "..."},
                  {"lines": ["<line>", "<line>"], "count": 1, "reason": "..."}],
     "adds":     [{"text": "<line>", "reason": "..."}],
     "changes":  [{"old": "<line>", "new": "<line>", "reason": "..."}],
     "reorders": [{"old_lines": [568, 572], "file": "SKILL.md", "reason": "..."}],
     "block_moves": [{"sha256": "<block hash, 12+ hex>", "file": "references/x.md",
                      "reason": "..."}]}

Stdlib only; PyYAML is optional. Exit: 0 clean, 1 findings that block (or a failed comparison), 2 bad input
or an environment problem (not a git checkout, unknown skill).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

try:  # optional: a second, typed reading of the frontmatter (see FRONTMATTER above)
    import yaml as _yaml
except Exception:  # pragma: no cover - exercised by setting _yaml to None
    _yaml = None

# --------------------------------------------------------------------------------------
# DATA. Other tools read these tables at run time (verify-skill-portability.sh, #344
# WP-7); change a rule here and nowhere else.
# --------------------------------------------------------------------------------------

#: agentskills.io specification keys.
SPEC_KEYS = ("name", "description", "license", "compatibility", "metadata", "allowed-tools")

#: Keys Claude Code reads on top of the specification.
CLAUDE_CODE_KEYS = (
    "when_to_use", "argument-hint", "arguments", "disable-model-invocation",
    "user-invocable", "disallowed-tools", "model", "effort", "context", "agent",
    "background", "hooks", "paths", "shell",
)

ALLOWED_KEYS = frozenset(SPEC_KEYS) | frozenset(CLAUDE_CODE_KEYS)

NAME_MAX_CHARS = 64
NAME_RESERVED_WORDS = ("anthropic", "claude")
DESCRIPTION_SPEC_MAX_CHARS = 1024
DESCRIPTION_LIMIT = 250
#: Skills triggered by phrase rather than by name keep their trigger phrases.
DESCRIPTION_LIMIT_OVERRIDES = {"avengers": 400, "codex-orchestration": 400}
SKILL_MD_MAX_LINES = 500
REFERENCE_CONTENTS_OVER_LINES = 100
REFERENCE_CONTENTS_WITHIN_LINES = 30
HARD_BLOCK_BYTE_LIMIT = 20_000
TOKEN_NOTE_LIMIT = 5_000
BYTES_PER_TOKEN = 4

#: Directories under a skill whose .md files are not references.
NON_REFERENCE_DIRS = frozenset({"tests", "test", "evals", "fixtures", "__pycache__",
                                "node_modules"})

#: Claude Code truncates description + when_to_use per entry in the skill listing.
LISTING_ENTRY_MAX_CHARS = 1536
LISTING_DEFAULT_FRACTION = 0.01
LISTING_ENTRY_OVERHEAD_CHARS = 6      # "- name: description\n" punctuation, an estimate

RULES = {
    "A1": "top-level frontmatter key outside the spec and Claude Code sets, or a "
          "frontmatter line that is not a `key:` line",
    "A2": "metadata value that is not a string",
    "A3": "name missing, over 64 chars, bad charset, reserved word or not the directory "
          "name",
    "A4": "description missing, undecodable, over 1024 chars or holding an XML-like tag",
    "A5": "description over its limit or opening with \"Use when\"",
    "A6": "SKILL.md over 500 lines",
    "A7": "reference .md that SKILL.md does not name",
    "A8": "reference .md over 100 lines with no contents list in its first 30 lines",
    "A9": "hard-coded home path to the skill's own directory",
    "A10": "reference reachable only through another reference (nested)",
    "A11": "HARD-RULE or HARD-GATE block starting at or after byte 20,000 of SKILL.md, "
           "or with no closing tag",
    "N1": "SKILL.md over about 5,000 tokens (bytes / 4)",
    "N2": "home path to a shared helper or another skill, or an exempt own-directory line",
}

CONFORMANT_FILE = "standard-conformant.txt"
EXEMPTIONS_FILE = "standard-exemptions.json"
MANIFEST_FILE = ".split-manifest.json"

_HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = _HERE.parent                      # <repo>/skills

EXIT_OK, EXIT_FINDINGS, EXIT_BAD_INPUT = 0, 1, 2

# --------------------------------------------------------------------------------------
# Patterns
# --------------------------------------------------------------------------------------

_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)[ \t]*:(?:[ \t]+(.*))?$")
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_XML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9_.:-]*(?:\s[^<>]*)?/?>")
_USE_WHEN_RE = re.compile(r"^use\s+when\b", re.IGNORECASE)
_HOME_SKILL_RE = re.compile(
    r"(?:~|\$HOME|\$\{HOME\})/\.claude/skills/([A-Za-z0-9_][A-Za-z0-9_-]*)")
_TAG_OPEN_RE = re.compile(r"^[ \t]*<(HARD-RULE|HARD-GATE)(?:\s[^>]*)?>")
_CONTENTS_RE = re.compile(
    r"^\s*(?:#{1,6}\s+|\*\*|__)?(?:table\s+of\s+contents|contents)\b", re.IGNORECASE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_STEP_RE = re.compile(r"\bStep\s+([0-9][0-9A-Za-z]*(?:\.[0-9][0-9A-Za-z]*)*\+?)")
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
_SPAWN_BRIEF_RE = re.compile(r"<!--\s*spawn-brief\.v1\s+id=([^\s>]+)\s*-->")
_CONTRACT_LOOP_RE = re.compile(r"<!--\s*contract:loop\s+(.*?)\s*-->")

# Plain YAML scalars that are NOT strings (YAML 1.1, which PyYAML and Codex read).
_YAML_NON_STRING_RE = re.compile(
    r"^(?:"
    r"~|null|true|false|yes|no|on|off"
    r"|[-+]?(?:0|[1-9][0-9_]*)"
    r"|[-+]?0b[01_]+|[-+]?0x[0-9a-fA-F_]+|[-+]?0o?[0-7_]+"
    r"|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+(?:\.[0-9_]*)?"          # sexagesimal: 12:30
    r"|[-+]?(?:[0-9][0-9_]*)?\.[0-9_]*(?:[eE][-+]?[0-9]+)?"
    r"|[-+]?[0-9][0-9_]*[eE][-+]?[0-9]+"
    r"|[-+]?\.(?:inf|nan)"
    r"|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}(?:[Tt ].*)?"
    r")$", re.IGNORECASE)


def _harden_streams() -> None:
    """UTF-8 with backslashreplace: findings quote file text, and a cp1252 console that
    cannot encode one must not turn a finding into a silent exit 0."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


class AuditError(Exception):
    """Bad input or an environment problem: exit 2, message on stderr."""


# --------------------------------------------------------------------------------------
# Frontmatter (a small, deliberate YAML subset: what a SKILL.md header uses)
# --------------------------------------------------------------------------------------

def split_frontmatter(text: str) -> tuple[str | None, str]:
    """(frontmatter text without the fences, body). None when there is no header."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        # Only a `---` at column 0 ends the header: an indented one is text inside a
        # block scalar, and cutting there would hide every key after it.
        if lines[i].rstrip() == "---":
            return "".join(lines[1:i]), "".join(lines[i + 1:])
    return None, text


def _strip_comment(value: str) -> str:
    """Drop a trailing ` # comment` from a PLAIN scalar."""
    m = re.search(r"\s#", value)
    return value[:m.start()].rstrip() if m else value.rstrip()


#: YAML double-quoted escapes. Anything else after a backslash is not decodable.
_DQ_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v",
    "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\",
    "N": "\x85", "_": "\xa0", "L": " ", "P": " ",
}
_DQ_HEX = {"x": 2, "u": 4, "U": 8}


def _decode_double(body: str) -> str | None:
    """The text of a double-quoted scalar's inside, or None when an escape is unknown
    or malformed (the caller fails closed: a value nobody can decode is not a string)."""
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        esc = body[i + 1:i + 2]
        if esc in _DQ_HEX:
            digits = body[i + 2:i + 2 + _DQ_HEX[esc]]
            if len(digits) != _DQ_HEX[esc] or not re.fullmatch(r"[0-9A-Fa-f]+", digits):
                return None
            try:
                out.append(chr(int(digits, 16)))
            except (ValueError, OverflowError):
                return None
            i += 2 + _DQ_HEX[esc]
        elif esc and esc in _DQ_ESCAPES:
            out.append(_DQ_ESCAPES[esc])
            i += 2
        else:
            return None
    return "".join(out)


def _unquote(value: str) -> tuple[str | None, bool]:
    """(decoded text, closed) for a value that starts with a quote. The text is None
    when the scalar is closed but cannot be read: an escape that cannot be decoded, or
    anything but a ` # comment` after the closing quote (`"Fine" <b>x</b>`)."""
    quote = value[0]
    if quote == "'":
        m = re.match(r"'((?:[^']|'')*)'", value)
        if not m:
            return value[1:], False
        text: str | None = m.group(1).replace("''", "'")
    else:
        m = re.match(r'"((?:[^"\\]|\\.)*)"', value)
        if not m:
            return value[1:], False
        text = _decode_double(m.group(1))
    if not re.fullmatch(r"\s*(?:\s#.*)?", value[m.end():], re.DOTALL):
        return None, True
    return text, True


def _ends_in_escape(piece: str) -> bool:
    """True when a line of a double-quoted scalar ends in an unescaped backslash."""
    return (len(piece) - len(piece.rstrip("\\"))) % 2 == 1


def _scalar(inline: str, cont: list[str]) -> tuple[str, str]:
    """(kind, decoded text). kind: string | non-string | tagged | undecodable | mapping
    | sequence | empty. Only `string` is a string; every other kind is refused by the
    rule that wanted one."""
    inline = (inline or "").strip()
    cont_text = [c.strip() for c in cont if c.strip()]
    if inline[:1] in (">", "|"):
        return "string", " ".join(cont_text)
    if inline[:1] in ('"', "'"):
        text, closed = _unquote(inline)
        if not closed:                          # a quoted scalar folded over lines
            pieces = [inline] + cont_text
            if inline[:1] == '"' and any(_ends_in_escape(piece) for piece in pieces[:-1]):
                return "undecodable", inline    # an escaped line break joins `<` to `b>`
            text, closed = _unquote(" ".join(pieces))
        if text is None or not closed:
            return "undecodable", inline
        return "string", text
    # In a plain scalar and under a bare `key:`, a line that is only a comment is not
    # part of the value: `version: 12` stays a number whatever comment follows it.
    cont_text = [c for c in cont_text if not c.startswith("#")]
    if inline[:1] in ("!", "&", "*"):
        return "tagged", inline                 # a tag, an anchor or an alias: not plain
    if inline[:1] == "[":
        return "sequence", inline
    if inline[:1] == "{":
        return "mapping", inline
    if not inline:
        if not cont_text:
            return "empty", ""
        first = cont_text[0]
        if first.startswith("- ") or first == "-":
            return "sequence", ""
        if _KEY_RE.match(first):
            return "mapping", ""
        return "string", " ".join(_strip_comment(c) for c in cont_text)
    plain = " ".join([_strip_comment(inline)] + cont_text)
    if not cont_text and _YAML_NON_STRING_RE.match(plain):
        return "non-string", plain
    return "string", plain


def _open_quote(inline: str, cont: list[str]) -> bool:
    """True while a quoted scalar that started on the key's line is still open."""
    inline = (inline or "").strip()
    if inline[:1] not in ('"', "'"):
        return False
    return not _unquote(" ".join([inline] + [c.strip() for c in cont if c.strip()]))[1]


def _entries(lines: list[str], indent: int, unrecognised: list[tuple[int, str]] | None = None
             ) -> list[tuple[str, str, list[str], int]]:
    """Mapping entries at exactly `indent`: (key, inline value, continuation, line index).

    A line AT `indent` (or shallower) that is not a `key:` line belongs to the value above
    only while that value is a quoted scalar still open. Otherwise it is appended to
    `unrecognised` as (line index, text) and joins nothing: a quoted key, a flow map or a
    stray word must not vanish into the previous key (fail closed).
    """
    out: list[tuple[str, str, list[str], int]] = []
    for idx, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        cur = len(line) - len(line.lstrip(" \t"))
        if not stripped or (stripped.startswith("#") and (cur <= indent or not out)):
            if out:
                out[-1][2].append("")
            continue
        m = _KEY_RE.match(line[indent:]) if cur == indent else None
        if m and not (out and _open_quote(out[-1][1], out[-1][2])):
            inline = m.group(2) or ""
            if inline.lstrip().startswith("#"):          # `key: # comment` has no value
                inline = ""
            out.append((m.group(1), inline, [], idx))
        elif out and (cur > indent or _open_quote(out[-1][1], out[-1][2])):
            out[-1][2].append(line)
        elif unrecognised is not None:
            unrecognised.append((idx, stripped))
        elif out:
            out[-1][2].append(line)
    return out


class Frontmatter:
    """Top-level keys, decoded scalars, and the children of `metadata`."""

    def __init__(self, fm_text: str | None):
        self.present = fm_text is not None
        self.keys: list[str] = []
        self.kinds: dict[str, str] = {}
        self.values: dict[str, str] = {}
        self.line_of: dict[str, int] = {}
        self.metadata: list[tuple[str, str, str]] = []      # (key, kind, text)
        self.unrecognised: list[tuple[int, str]] = []       # (1-based file line, text)
        self.metadata_unrecognised: list[tuple[int, str]] = []
        self.duplicates: list[tuple[str, int]] = []         # (key, 1-based file line)
        self.typed: dict | None = None                      # PyYAML's reading, if any
        if fm_text is None:
            return
        lines = fm_text.splitlines()
        stray: list[tuple[int, str]] = []
        for key, inline, cont, idx in _entries(lines, 0, stray):
            kind, text = _scalar(inline, cont)
            if key in self.kinds:
                self.duplicates.append((key, idx + 2))
            else:
                self.keys.append(key)
            self.kinds[key] = kind
            self.values[key] = text
            self.line_of[key] = idx + 2                      # 1-based, after the fence
            if key == "metadata" and kind == "mapping" and not inline.strip():
                body = [c for c in cont if c.strip() and not c.lstrip().startswith("#")]
                child_indent = len(body[0]) - len(body[0].lstrip(" \t"))
                child_stray: list[tuple[int, str]] = []
                for ckey, cinline, ccont, _ in _entries(cont, child_indent, child_stray):
                    ckind, ctext = _scalar(cinline, ccont)
                    self.metadata.append((ckey, ckind, ctext))
                self.metadata_unrecognised = [(idx + 3 + i, t) for i, t in child_stray]
        self.unrecognised = [(i + 2, t) for i, t in stray]
        self.typed = _typed_frontmatter(fm_text)

    def text(self, key: str) -> str | None:
        """Whitespace-collapsed string value, or None when absent or not a string."""
        if self.kinds.get(key) != "string":
            return None
        return " ".join(self.values[key].split())


def _typed_frontmatter(fm_text: str) -> dict | None:
    """PyYAML's reading of the header, or None (no PyYAML, not valid YAML, not a
    mapping). Never the only reading: the stdlib reader above decides on its own."""
    if _yaml is None:
        return None
    try:
        data = _yaml.safe_load(fm_text.replace("\r\n", "\n").replace("\r", "\n"))
    except Exception:           # YAMLError, and whatever a hostile tag makes it raise
        return None
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------------------
# Skill files: the working tree, or one git revision
# --------------------------------------------------------------------------------------

def _is_reference(rel: str, nested: tuple[str, ...]) -> bool:
    parts = rel.split("/")
    if not rel.lower().endswith(".md") or rel == "SKILL.md":
        return False
    if any(p in NON_REFERENCE_DIRS or p.startswith(".") for p in parts[:-1]):
        return False
    return not any(rel.startswith(n + "/") for n in nested)


def _nested_skill_dirs(rels: list[str]) -> tuple[str, ...]:
    return tuple(sorted(r[:-len("/SKILL.md")] for r in rels
                        if r.endswith("/SKILL.md")
                        and not any(p in NON_REFERENCE_DIRS for p in r.split("/")[:-1])))


class SkillFiles:
    """SKILL.md plus its references, as text, in a stable order (SKILL.md first)."""

    def __init__(self, name: str, files: dict[str, str], nested: tuple[str, ...]):
        self.name = name
        self.files = files                       # rel -> text; SKILL.md first
        self.nested = nested

    @property
    def skill_md(self) -> str:
        return self.files["SKILL.md"]

    @property
    def references(self) -> list[str]:
        return [r for r in self.files if r != "SKILL.md"]

    @classmethod
    def from_tree(cls, root: Path, name: str) -> "SkillFiles":
        base = root / name
        if not (base / "SKILL.md").is_file():
            raise AuditError(f"no SKILL.md for skill {name!r} under {root}")
        rels: list[str] = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for fn in sorted(filenames):
                rels.append((Path(dirpath) / fn).relative_to(base).as_posix())
        nested = _nested_skill_dirs(rels)
        files = {"SKILL.md": _read(base / "SKILL.md")}
        for rel in sorted(r for r in rels if _is_reference(r, nested)):
            files[rel] = _read(base / rel)
        return cls(name, files, nested)

    @classmethod
    def from_ref(cls, root: Path, name: str, ref: str) -> "SkillFiles":
        top, prefix = _git_top(root)
        skill_prefix = f"{prefix}{name}/"
        listing = _git(top, "ls-tree", "-r", "--name-only", "-z", ref, "--", skill_prefix)
        rels = [p[len(skill_prefix):] for p in listing.split("\0") if p]
        if "SKILL.md" not in rels:
            raise AuditError(f"{ref}:{skill_prefix}SKILL.md does not exist")
        nested = _nested_skill_dirs(rels)
        files = {"SKILL.md": _git(top, "show", f"{ref}:{skill_prefix}SKILL.md")}
        for rel in sorted(r for r in rels if _is_reference(r, nested)):
            files[rel] = _git(top, "show", f"{ref}:{skill_prefix}{rel}")
        return cls(name, files, nested)

    @classmethod
    def from_index(cls, index: "GitIndex", name: str) -> "SkillFiles":
        """The skill as it is STAGED: what the next commit will hold."""
        skill_prefix = f"skills/{name}/"
        rels = sorted(p[len(skill_prefix):] for p in index.paths(skill_prefix))
        if "SKILL.md" not in rels:
            raise AuditError(f"no staged SKILL.md for skill {name!r}")
        nested = _nested_skill_dirs(rels)
        files = {"SKILL.md": index.read(skill_prefix + "SKILL.md")}
        for rel in (r for r in rels if _is_reference(r, nested)):
            files[rel] = index.read(skill_prefix + rel)
        return cls(name, files, nested)


class GitIndex:
    """Regular files of the git index (stage 0), by repository path. `git` inherits the
    environment, so a commit that uses its own index file (GIT_INDEX_FILE: `git commit
    -a`, `git commit <path>`) is read from that one."""

    def __init__(self, top: Path):
        self.top = top
        self._blobs: dict[str, str] = {}
        self._links: set[str] = set()            # staged as a symbolic link (120000)
        for record in _git(top, "ls-files", "-s", "-z").split("\0"):
            if not record:
                continue
            meta, _, path = record.partition("\t")
            mode, sha, stage = meta.split()
            if stage == "0" and mode in ("100644", "100755"):
                self._blobs[path] = sha
            elif stage == "0" and mode == "120000":
                self._links.add(path)

    @classmethod
    def at(cls, repo: Path) -> "GitIndex | None":
        """The index when `repo` is the top of a checkout; None when it is in no
        checkout at all. A directory BELOW the top of one is refused: it has no index of
        its own, and its working tree is not what a commit holds."""
        try:
            top = _git(repo, "rev-parse", "--show-toplevel").strip()
        except AuditError:
            return None
        if not top:
            return None
        if Path(top).resolve() != repo.resolve():
            raise AuditError(f"{repo} is inside the checkout {top} but is not its top level: "
                             "pass the top level as --repo, or --tree to read the working "
                             "tree of this directory")
        return cls(repo)

    def paths(self, prefix: str) -> list[str]:
        return [p for p in self._blobs if p.startswith(prefix)]

    def has(self, path: str) -> bool:
        return path in self._blobs

    def is_link(self, path: str) -> bool:
        return path in self._links

    def read(self, path: str) -> str:
        return _git(self.top, "cat-file", "blob", self._blobs[path])


def _read(path: Path) -> str:
    with open(path, "r", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        return fh.read()


def _git(top: Path, *args: str) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(top), *args], capture_output=True)
    except OSError as exc:
        raise AuditError(f"git could not be run: {exc}") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise AuditError(f"git {' '.join(args[:2])} failed: {err}")
    return proc.stdout.decode("utf-8", errors="surrogateescape")


def _git_top(root: Path) -> tuple[Path, str]:
    """(repository top, the root's path inside it with a trailing slash)."""
    if not root.is_dir():
        raise AuditError(f"not a directory: {root}")
    top = Path(_git(root, "rev-parse", "--show-toplevel").strip())
    prefix = _git(root, "rev-parse", "--show-prefix").strip()
    return top, prefix


def discover(root: Path) -> list[str]:
    if not root.is_dir():
        raise AuditError(f"not a directory: {root}")
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and not p.name.startswith(("_", "."))
                  and (p / "SKILL.md").is_file())


# --------------------------------------------------------------------------------------
# The lists
# --------------------------------------------------------------------------------------

def parse_conformant(text: str) -> frozenset[str]:
    names = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(line)
    return frozenset(names)


def load_conformant(meta_dir: Path) -> frozenset[str]:
    path = meta_dir / CONFORMANT_FILE
    return parse_conformant(_read(path)) if path.is_file() else frozenset()


def parse_exemptions(text: str, label: str) -> dict[str, dict[tuple[str, str], str]]:
    """skill -> {(file, exact line text): reason}. An entry with no reason is refused."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AuditError(f"{label}: not valid JSON ({exc})") from exc
    out: dict[str, dict[tuple[str, str], str]] = {}
    for skill, entries in (data.get("exemptions") or {}).items():
        for entry in entries:
            reason = str(entry.get("reason") or "").strip()
            if not reason or "file" not in entry or "line" not in entry:
                raise AuditError(
                    f"{label}: an exemption for {skill!r} lacks file, line or reason")
            out.setdefault(skill, {})[(entry["file"], entry["line"])] = reason
    return out


def load_exemptions(meta_dir: Path) -> dict[str, dict[tuple[str, str], str]]:
    path = meta_dir / EXEMPTIONS_FILE
    return parse_exemptions(_read(path), str(path)) if path.is_file() else {}


# --------------------------------------------------------------------------------------
# Scanning helpers shared by audit and inventory
# --------------------------------------------------------------------------------------

def hard_blocks(text: str) -> list[dict]:
    """Every HARD-RULE / HARD-GATE block, found by its TAG LINE (the tag is the first
    thing on the line, indentation allowed).

    A block runs to the line that holds its closing tag. One with NO closing tag ends
    before the next tag line (or at the end of the file) and carries `terminated: False`:
    it must not swallow the blocks after it, and it is a finding wherever it is seen.
    """
    out: list[dict] = []
    lines = text.splitlines(keepends=True)
    sizes = [len(l.encode("utf-8", errors="surrogateescape")) for l in lines]
    i = 0
    while i < len(lines):
        m = _TAG_OPEN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        kind, start = m.group(1), i
        close = f"</{kind}>"
        closed = close in lines[i][m.end():]
        j = i
        while not closed and j + 1 < len(lines):
            if _TAG_OPEN_RE.match(lines[j + 1]):
                break                              # the next block starts: unterminated
            j += 1
            closed = close in lines[j]
        if not closed:                             # do not count trailing blank lines
            while j > start and not lines[j].strip():
                j -= 1
        normal = "\n".join(l.rstrip("\r\n") for l in lines[start:j + 1])
        out.append({
            "kind": kind, "line": start + 1, "end_line": j + 1,
            "byte_offset": sum(sizes[:start]), "terminated": closed,
            "sha256": hashlib.sha256(normal.encode("utf-8", "surrogateescape")).hexdigest(),
        })
        i = j + 1
    return out


def headings(text: str) -> list[dict]:
    """ATX headings outside fenced code (a `# comment` in a bash block is not one)."""
    out: list[dict] = []
    fence: tuple[str, int] | None = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        f = _FENCE_RE.match(raw)
        if f:
            marker = f.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
                continue
            if marker[0] == fence[0] and len(marker) >= fence[1] and not f.group(2).strip():
                fence = None
                continue
        if fence is not None:
            continue
        m = _HEADING_RE.match(raw)
        if m:
            entry = {"level": len(m.group(1)), "text": m.group(2), "line": lineno}
            step = _STEP_RE.search(m.group(2))
            if step:
                entry["step"] = step.group(1)
            out.append(entry)
    return out


def anchors(text: str) -> list[dict]:
    out: list[dict] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        for m in _SPAWN_BRIEF_RE.finditer(raw):
            out.append({"kind": "spawn-brief", "id": m.group(1), "line": lineno})
        for m in _CONTRACT_LOOP_RE.finditer(raw):
            out.append({"kind": "contract-loop", "id": m.group(1), "line": lineno})
    return out


def _mentions(text: str, rel: str) -> bool:
    return re.search(r"(?<![\w.-])" + re.escape(rel) + r"(?![\w-])", text) is not None


# --------------------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------------------

def description_limit(name: str) -> int:
    return DESCRIPTION_LIMIT_OVERRIDES.get(name, DESCRIPTION_LIMIT)


def audit_skill(skill: SkillFiles, exemptions: dict[tuple[str, str], str] | None = None
                ) -> dict:
    """One skill's findings and notes. Pure: reads nothing beyond `skill`."""
    exemptions = exemptions or {}
    name = skill.name
    findings: list[dict] = []
    notes: list[dict] = []

    def fail(code: str, file: str, message: str, line: int | None = None) -> None:
        findings.append({"code": code, "level": "fail", "file": file, "line": line,
                         "message": message})

    def note(code: str, file: str, message: str, line: int | None = None) -> None:
        notes.append({"code": code, "level": "note", "file": file, "line": line,
                      "message": message})

    text = skill.skill_md
    fm_text, _body = split_frontmatter(text)
    fm = Frontmatter(fm_text)

    # A1 / A2 -- keys
    for key in fm.keys:
        if key not in ALLOWED_KEYS:
            fail("A1", "SKILL.md", f"frontmatter key `{key}` is not a spec or Claude Code "
                 "key (custom data goes under `metadata:` as a string)", fm.line_of[key])
    for key, lineno in fm.duplicates:
        fail("A1", "SKILL.md", f"frontmatter key `{key}` appears more than once (a YAML "
             "reader keeps one copy and says nothing; which one is not yours to choose)",
             lineno)
    for lineno, shown in fm.unrecognised:
        fail("A1", "SKILL.md", f"frontmatter line is not a `key: value` line the audit can "
             f"read: {shown[:60]!r} (write keys bare, one per line)", lineno)
    meta_flagged: set[str] = set()
    metadata_shape_failed = False
    if "metadata" in fm.kinds:
        if fm.kinds["metadata"] not in ("mapping", "empty") or (
                fm.kinds["metadata"] == "mapping" and fm.values["metadata"]):
            metadata_shape_failed = True
            fail("A2", "SKILL.md", "`metadata` must be a block mapping of string values",
                 fm.line_of["metadata"])
        for ckey, ckind, ctext in fm.metadata:
            if ckind != "string":
                meta_flagged.add(ckey)
                shown = f" ({ctext})" if ctext else ""
                fail("A2", "SKILL.md", f"`metadata.{ckey}` is not a string: {ckind}{shown}; "
                     "quote it", fm.line_of["metadata"])
        for lineno, shown in fm.metadata_unrecognised:
            fail("A2", "SKILL.md", f"line under `metadata` is not `key: value`: "
                 f"{shown[:60]!r}", lineno)
    # The typed reading (PyYAML, when it could parse the header) may only ADD findings,
    # and says nothing where the stdlib reader already reported the line.
    if fm.typed is not None:
        for key in fm.typed:
            if fm.unrecognised:
                break
            if key not in fm.keys and (not isinstance(key, str) or key not in ALLOWED_KEYS):
                fail("A1", "SKILL.md", f"frontmatter key `{key}` (as YAML reads it) is not "
                     "a spec or Claude Code key", 1)
        typed_meta = fm.typed.get("metadata")
        if isinstance(typed_meta, dict):
            for ckey, cval in typed_meta.items():
                if not isinstance(cval, str) and ckey not in meta_flagged \
                        and not fm.metadata_unrecognised:
                    fail("A2", "SKILL.md", f"`metadata.{ckey}` is not a string: YAML reads "
                         f"it as {type(cval).__name__}; quote it",
                         fm.line_of.get("metadata", 1))
        elif typed_meta is not None and not metadata_shape_failed:
            fail("A2", "SKILL.md", "`metadata` must be a block mapping of string values",
                 fm.line_of.get("metadata", 1))

    # A3 -- name
    declared = fm.text("name")
    if not fm.present:
        fail("A3", "SKILL.md", "no frontmatter, so no `name`", 1)
    elif declared is None:
        fail("A3", "SKILL.md", "`name` is missing or not a string", fm.line_of.get("name"))
    else:
        problems = []
        if len(declared) > NAME_MAX_CHARS:
            problems.append(f"{len(declared)} chars (limit {NAME_MAX_CHARS})")
        if not _NAME_RE.match(declared):
            problems.append("charset: lowercase letters, digits and single hyphens only")
        for word in NAME_RESERVED_WORDS:
            if word in declared.lower():
                problems.append(f"reserved word `{word}`")
        if declared != name:
            problems.append(f"not the directory name `{name}`")
        if problems:
            fail("A3", "SKILL.md", f"`name: {declared}` -- " + "; ".join(problems),
                 fm.line_of["name"])

    # A4 / A5 -- description
    description = fm.text("description")
    desc_chars = len(description) if description is not None else 0
    desc_line = fm.line_of.get("description", 1)
    if not description:
        fail("A4", "SKILL.md", "`description` is missing, empty or not a string", desc_line)
    else:
        if desc_chars > DESCRIPTION_SPEC_MAX_CHARS:
            fail("A4", "SKILL.md", f"description is {desc_chars} chars "
                 f"(spec limit {DESCRIPTION_SPEC_MAX_CHARS})", desc_line)
        tag = _XML_TAG_RE.search(description)
        typed_desc = fm.typed.get("description") if fm.typed is not None else None
        if not tag and isinstance(typed_desc, str):
            tag = _XML_TAG_RE.search(typed_desc)     # the second reading, decoded by YAML
        if tag:
            fail("A4", "SKILL.md", f"description holds an XML-like tag `{tag.group(0)}`",
                 desc_line)
        limit = description_limit(name)
        if desc_chars > limit:
            fail("A5", "SKILL.md", f"description is {desc_chars} chars (limit {limit})",
                 desc_line)
        if _USE_WHEN_RE.match(description):
            fail("A5", "SKILL.md", "description opens with \"Use when\"; open with the "
                 "subject", desc_line)

    # A6 / N1 -- size
    line_count = len(text.splitlines())
    byte_count = len(text.encode("utf-8", errors="surrogateescape"))
    if line_count > SKILL_MD_MAX_LINES:
        fail("A6", "SKILL.md", f"SKILL.md is {line_count} lines (limit {SKILL_MD_MAX_LINES})")
    tokens = byte_count // BYTES_PER_TOKEN
    if tokens > TOKEN_NOTE_LIMIT:
        note("N1", "SKILL.md", f"SKILL.md is about {tokens} tokens ({byte_count} bytes / "
             f"{BYTES_PER_TOKEN}); only the first {TOKEN_NOTE_LIMIT} are re-attached after "
             "a compaction")

    # A7 / A10 / A8 -- references
    refs = skill.references
    for rel in refs:
        body = skill.files[rel]
        if not _mentions(text, rel):
            via = []
            for other in refs:
                if other == rel:
                    continue
                other_dir = os.path.dirname(other)
                local = os.path.relpath(rel, other_dir or ".").replace(os.sep, "/")
                if _mentions(skill.files[other], rel) or _mentions(skill.files[other], local):
                    via.append(other)
            if via:
                fail("A10", rel, "not named in SKILL.md; reachable only through "
                     + ", ".join(via[:3]) + (" ..." if len(via) > 3 else ""))
            else:
                fail("A7", rel, "reference is not named in SKILL.md")
        ref_lines = body.splitlines()
        if len(ref_lines) > REFERENCE_CONTENTS_OVER_LINES and not any(
                _CONTENTS_RE.match(l) for l in ref_lines[:REFERENCE_CONTENTS_WITHIN_LINES]):
            fail("A8", rel, f"{len(ref_lines)} lines and no contents list in the first "
                 f"{REFERENCE_CONTENTS_WITHIN_LINES}")

    # A9 / N2 -- home paths
    for rel, body in skill.files.items():
        for lineno, raw in enumerate(body.splitlines(), 1):
            targets = _HOME_SKILL_RE.findall(raw)
            if not targets:
                continue
            if name in targets:
                reason = exemptions.get((rel, raw))
                if reason is None:
                    fail("A9", rel, "home path to the skill's own directory; use a "
                         "skill-relative path or list the line in " + EXEMPTIONS_FILE, lineno)
                else:
                    note("N2", rel, f"exempt own-directory home path ({reason})", lineno)
            others = sorted({t for t in targets if t != name})
            if others:
                note("N2", rel, "home path to " + ", ".join(others), lineno)

    # A11 -- must-hold blocks inside what survives a compaction
    blocks = hard_blocks(text)
    for block in blocks:
        if block["byte_offset"] >= HARD_BLOCK_BYTE_LIMIT:
            fail("A11", "SKILL.md", f"{block['kind']} block starts at byte "
                 f"{block['byte_offset']} (limit {HARD_BLOCK_BYTE_LIMIT})", block["line"])
        if not block["terminated"]:
            fail("A11", "SKILL.md", f"{block['kind']} block has no closing "
                 f"</{block['kind']}> tag", block["line"])

    return {
        "name": name,
        "skill_md_lines": line_count,
        "skill_md_bytes": byte_count,
        "description_chars": desc_chars,
        "description_limit": description_limit(name),
        "frontmatter_keys": fm.keys,
        "hard_blocks": len(blocks),
        "reference_files": refs,
        "nested_skills": list(skill.nested),
        "findings": findings,
        "notes": notes,
    }


def _display_root(root: Path) -> str:
    try:
        return root.resolve().relative_to(DEFAULT_ROOT.parent).as_posix()
    except ValueError:
        return str(root)


def run_audit(root: Path, only: list[str] | None, conformant: frozenset[str],
              exemptions: dict[str, dict[tuple[str, str], str]], strict: bool = False
              ) -> dict:
    names = discover(root)
    if only:
        unknown = [n for n in only if n not in names]
        if unknown:
            raise AuditError("unknown skill(s) under " + str(root) + ": " + ", ".join(unknown))
        names = [n for n in names if n in set(only)]
    skills: dict[str, dict] = {}
    fails_by_code: Counter = Counter()
    notes_by_code: Counter = Counter()
    fails_listed = fails_unlisted = 0
    for name in names:
        record = audit_skill(SkillFiles.from_tree(root, name), exemptions.get(name))
        record["listed"] = strict or name in conformant
        record["fail_count"] = len(record["findings"])
        record["note_count"] = len(record["notes"])
        skills[name] = record
        for f in record["findings"]:
            fails_by_code[f["code"]] += 1
        for n in record["notes"]:
            notes_by_code[n["code"]] += 1
        if record["listed"]:
            fails_listed += record["fail_count"]
        else:
            fails_unlisted += record["fail_count"]
    return {
        "schema": "skill-audit.v1",
        "root": _display_root(root),
        "strict": strict,
        "rules": RULES,
        "limits": {
            "description": DESCRIPTION_LIMIT,
            "description_overrides": DESCRIPTION_LIMIT_OVERRIDES,
            "description_spec_max": DESCRIPTION_SPEC_MAX_CHARS,
            "skill_md_lines": SKILL_MD_MAX_LINES,
            "hard_block_byte": HARD_BLOCK_BYTE_LIMIT,
            "token_note": TOKEN_NOTE_LIMIT,
        },
        "skills": skills,
        "summary": {
            "skills": len(skills),
            "listed": sum(1 for r in skills.values() if r["listed"]),
            "skills_with_fails": sum(1 for r in skills.values() if r["fail_count"]),
            "fails_listed": fails_listed,
            "fails_unlisted": fails_unlisted,
            "fails_by_code": dict(sorted(fails_by_code.items(), key=_code_key)),
            "notes_by_code": dict(sorted(notes_by_code.items(), key=_code_key)),
        },
        "exit_code": EXIT_FINDINGS if fails_listed else EXIT_OK,
    }


def _code_key(item) -> tuple[str, int]:
    code = item[0] if isinstance(item, tuple) else item
    return code[0], int(code[1:])


def _where(skill: str, finding: dict, prefix: str = "") -> str:
    loc = f"{prefix}{skill}/{finding['file']}"
    return f"{loc}:{finding['line']}" if finding.get("line") else loc


def render_audit(report: dict, verbose: bool = False) -> str:
    out: list[str] = []
    s = report["summary"]
    out.append(f"skill_audit: {report['root']} -- {s['skills']} skill(s), "
               f"{s['listed']} held to the standard"
               + (" (--strict)" if report["strict"] else ""))
    out.append("")
    out.append("FAILS -- skills held to the standard (these set the exit code)")
    any_listed = False
    for name, rec in report["skills"].items():
        if rec["listed"] and rec["findings"]:
            any_listed = True
            for f in rec["findings"]:
                out.append(f"  {f['code']:<3} {_where(name, f)}: {f['message']}")
    if not any_listed:
        out.append("  none")
    unlisted = [(n, r) for n, r in report["skills"].items()
                if not r["listed"] and r["findings"]]
    if unlisted:
        out.append("")
        out.append("REPORTED ONLY -- skills not on the conformant list (exit code unaffected)")
        for name, rec in unlisted:
            if verbose:
                for f in rec["findings"]:
                    out.append(f"  {f['code']:<3} {_where(name, f)}: {f['message']}")
            else:
                codes = Counter(f["code"] for f in rec["findings"])
                out.append(f"  {name}: " + " ".join(
                    f"{c}x{n}" for c, n in sorted(codes.items(), key=_code_key)))
    out.append("")
    out.append("NOTES -- never affect the exit code")
    counts = s["notes_by_code"]
    out.append("  N1: {}   N2: {}".format(counts.get("N1", 0), counts.get("N2", 0)))
    for name, rec in report["skills"].items():
        if not rec["notes"]:
            continue
        if verbose:
            for n in rec["notes"]:
                out.append(f"  {n['code']:<3} {_where(name, n)}: {n['message']}")
        else:
            codes = Counter(n["code"] for n in rec["notes"])
            out.append(f"  {name}: " + " ".join(
                f"{c}x{n}" for c, n in sorted(codes.items(), key=_code_key)))
    out.append("")
    by_code = " ".join(f"{c}={n}" for c, n in s["fails_by_code"].items()) or "none"
    out.append(f"SUMMARY: {s['fails_listed']} fail(s) in skills held to the standard, "
               f"{s['fails_unlisted']} reported only; by rule: {by_code}")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------------------
# check (the pre-commit arm)
# --------------------------------------------------------------------------------------

def run_check(repo: Path, paths: list[str], source: str = "auto") -> tuple[int, str]:
    """Audit every skill a staged path belongs to. `SA-E` blocks, `SA-W` advises.

    The whole skill is judged, not one staged blob: most rules are about the skill (is
    this reference named, how long is SKILL.md). WHICH copy of the skill is the point of
    `source`:

      index  what is staged -- the skill's files, the conformant list and the exemption
             list are read from the git index, so the verdict is about the commit
      tree   the working tree
      auto   index when `repo` is the top of a git checkout; tree when it is in no
             checkout; refused (AuditError) when it is a directory below the top of one
    """
    if source not in ("auto", "index", "tree"):
        raise AuditError(f"unknown source {source!r}")
    root = repo / "skills"
    meta = root / "_meta"
    index = None if source == "tree" else GitIndex.at(repo)
    if source == "index" and index is None:
        raise AuditError(f"--index needs {repo} to be the top of a git checkout")
    if index is not None:
        listed_path = f"skills/_meta/{CONFORMANT_FILE}"
        exempt_path = f"skills/_meta/{EXEMPTIONS_FILE}"
        conformant = (parse_conformant(index.read(listed_path)) if index.has(listed_path)
                      else frozenset())
        exemptions = (parse_exemptions(index.read(exempt_path), f"staged {exempt_path}")
                      if index.has(exempt_path) else {})
    else:
        conformant = load_conformant(meta)
        exemptions = load_exemptions(meta)

    def exists(name: str) -> bool:
        if index is not None:
            return index.has(f"skills/{name}/SKILL.md")
        return (root / name / "SKILL.md").is_file()

    def linked(name: str) -> bool:
        return index is not None and index.is_link(f"skills/{name}/SKILL.md")

    names: list[str] = []
    for raw in paths:
        parts = Path(raw.replace("\\", "/")).as_posix().split("/")
        if len(parts) < 3 or parts[0] != "skills":
            continue
        name = parts[1]
        if name.startswith(("_", ".")) or name in names:
            continue
        if exists(name) or linked(name):
            names.append(name)
    lines: list[str] = []
    blocking = advisory = 0
    for name in sorted(names):
        if linked(name):
            # The blob of a symbolic link is a path, not a skill: nothing can be read
            # from the commit, and a skill that cannot be read has not passed.
            record = {"findings": [{
                "code": "A3", "file": "SKILL.md", "line": None,
                "message": "SKILL.md is staged as a symbolic link, not a regular file: "
                           "the skill cannot be read from the commit, so it has no "
                           "`name` and nothing else was checked"}]}
        else:
            skill = (SkillFiles.from_index(index, name) if index is not None
                     else SkillFiles.from_tree(root, name))
            record = audit_skill(skill, exemptions.get(name))
        listed = name in conformant
        for f in record["findings"]:
            tag = "SA-E" if listed else "SA-W"
            blocking += listed
            advisory += not listed
            lines.append(f"{tag} {f['code']} {_where(name, f, 'skills/')}: {f['message']}")
    if lines:
        lines.append(f"skill_audit check: {len(names)} skill(s), {blocking} blocking "
                     f"(conformant list), {advisory} advisory")
    return (EXIT_FINDINGS if blocking else EXIT_OK), "\n".join(lines) + ("\n" if lines else "")


# --------------------------------------------------------------------------------------
# listing-budget
# --------------------------------------------------------------------------------------

def run_listing_budget(root: Path, fraction: float, context_tokens: int) -> dict:
    """An ESTIMATE. Claude Code does not publish the listing's exact format, counts
    plugin, bundled and project skills this tool cannot see, and drops descriptions
    starting with the least-invoked skills, which a static tool cannot know either."""
    entries = []
    for name in discover(root):
        fm = Frontmatter(split_frontmatter(_read(root / name / "SKILL.md"))[0])
        desc = " ".join(filter(None, (fm.text("description"), fm.text("when_to_use"))))
        listed = min(len(desc), LISTING_ENTRY_MAX_CHARS)
        entries.append({"name": name, "description_chars": len(desc),
                        "name_only_cost": len(name) + LISTING_ENTRY_OVERHEAD_CHARS,
                        "full_cost": len(name) + LISTING_ENTRY_OVERHEAD_CHARS + listed})
    budget = int(context_tokens * fraction * BYTES_PER_TOKEN)
    names_cost = sum(e["name_only_cost"] for e in entries)
    full_cost = sum(e["full_cost"] for e in entries)

    def fit(order: list[dict]) -> int:
        left = budget - names_cost            # every name is always listed
        count = 0
        for e in order:
            extra = e["full_cost"] - e["name_only_cost"]
            if extra > left:
                break
            left -= extra
            count += 1
        return count

    return {
        "schema": "skill-listing-budget.v1",
        "estimate": True,
        "root": _display_root(root),
        "skills": len(entries),
        "fraction": fraction,
        "context_tokens": context_tokens,
        "chars_per_token_assumed": BYTES_PER_TOKEN,
        "budget_chars": budget,
        "names_only_chars": names_cost,
        "all_descriptions_chars": full_cost,
        "description_chars_total": sum(e["description_chars"] for e in entries),
        "description_chars_mean": round(
            sum(e["description_chars"] for e in entries) / max(len(entries), 1), 1),
        "fits_with_description": {
            "shortest_first": fit(sorted(entries, key=lambda e: e["full_cost"])),
            "longest_first": fit(sorted(entries, key=lambda e: -e["full_cost"])),
            "alphabetical": fit(entries),
        },
        "fraction_needed_for_all": round(full_cost / (context_tokens * BYTES_PER_TOKEN), 4),
        "largest": [{"name": e["name"], "description_chars": e["description_chars"]}
                    for e in sorted(entries, key=lambda e: -e["description_chars"])[:10]],
    }


def render_listing_budget(r: dict) -> str:
    fit = r["fits_with_description"]
    return "\n".join([
        "skill listing budget -- ESTIMATE, not a measurement",
        f"  root: {r['root']} ({r['skills']} skills; plugin, bundled and project skills "
        "are not counted)",
        f"  budget: {r['fraction']:.2%} of a {r['context_tokens']:,}-token window at "
        f"{r['chars_per_token_assumed']} chars/token = {r['budget_chars']:,} chars",
        f"  every name, no description: {r['names_only_chars']:,} chars",
        f"  every name with its description: {r['all_descriptions_chars']:,} chars "
        f"(descriptions total {r['description_chars_total']:,}, mean "
        f"{r['description_chars_mean']})",
        f"  skills that fit WITH a description: {fit['shortest_first']} if the shortest "
        f"are kept, {fit['longest_first']} if the longest are, {fit['alphabetical']} "
        "alphabetically (Claude Code keeps the most-invoked, which this cannot see)",
        f"  fraction needed for every description: {r['fraction_needed_for_all']:.2%}",
        "  largest: " + ", ".join(f"{e['name']} {e['description_chars']}"
                                  for e in r["largest"][:5]),
    ]) + "\n"


# --------------------------------------------------------------------------------------
# inventory
# --------------------------------------------------------------------------------------

def run_inventory(skill: SkillFiles) -> dict:
    files = []
    for rel, text in skill.files.items():
        blocks = hard_blocks(text)
        for b in blocks:
            b["file"] = rel
        heads = headings(text)
        files.append({
            "file": rel,
            "bytes": len(text.encode("utf-8", errors="surrogateescape")),
            "lines": len(text.splitlines()),
            "hard_blocks": blocks,
            "headings": heads,
            "steps": [{"id": h["step"], "line": h["line"], "heading": h["text"]}
                      for h in heads if "step" in h],
            "anchors": anchors(text),
        })
    return {"schema": "skill-inventory.v1", "skill": skill.name, "files": files}


def inventory_problems(inv: dict) -> list[str]:
    """What is wrong with one inventory on its own: a block with no closing tag."""
    return [f"{b['kind']} block at {f['file']}:{b['line']} has no closing </{b['kind']}> tag"
            for f in inv["files"] for b in f["hard_blocks"] if not b["terminated"]]


def _block_move_allowed(moves, digest: str, target_files: set[str]) -> bool:
    return any(digest.startswith(m["sha256"]) and m["file"] in target_files
               for m in moves or ())


def blocks_that_left_skill_md(old_blocks: list[dict], new_blocks: list[dict],
                              new_elsewhere: dict[str, set[str]], moves) -> list[str]:
    """A must-hold block that was in SKILL.md and is no longer there, although the same
    block exists in another file (so a corpus-wide count sees nothing). `new_elsewhere`
    is sha256 -> the other files that hold it now. Legal only through `block_moves`."""
    problems: list[str] = []
    gone = (Counter((b["kind"], b["sha256"]) for b in old_blocks)
            - Counter((b["kind"], b["sha256"]) for b in new_blocks))
    for (kind, digest), n in gone.items():
        targets = new_elsewhere.get(digest, set())
        if not targets or _block_move_allowed(moves, digest, targets):
            continue                     # absent everywhere is reported as missing/changed
        was = next(b["line"] for b in old_blocks if b["sha256"] == digest)
        problems.append(
            f"{kind} block {digest[:12]} (was SKILL.md:{was}) left SKILL.md for "
            f"{', '.join(sorted(targets))}: a must-hold block stays in SKILL.md unless the "
            f"manifest records the move under `block_moves`" + (f" ({n} of them)" if n > 1 else ""))
    return problems


def compare_inventories(old: dict, new: dict, block_moves=None, reorders=None) -> list[str]:
    """What DW-8 asks: the same must-hold blocks by hash -- and those of SKILL.md still IN
    SKILL.md --, every block closed, the same step ids with their order kept inside every
    file, the same anchors. Returns the differences.

    `block_moves` and `reorders` are the manifest's reviewed exceptions: a block that
    left SKILL.md for the file named, and a step heading inside an old SKILL.md line
    range that `conserve` already holds to "whole and in order" where it went."""
    problems: list[str] = inventory_problems(new)

    def skill_md_blocks(inv: dict) -> list[dict]:
        return [b for f in inv["files"] if f["file"] == "SKILL.md" for b in f["hard_blocks"]]

    elsewhere: dict[str, set[str]] = {}
    for f in new["files"]:
        if f["file"] != "SKILL.md":
            for b in f["hard_blocks"]:
                elsewhere.setdefault(b["sha256"], set()).add(f["file"])
    problems += blocks_that_left_skill_md(skill_md_blocks(old), skill_md_blocks(new),
                                          elsewhere, block_moves)

    def blocks(inv: dict) -> Counter:
        return Counter((b["kind"], b["sha256"]) for f in inv["files"] for b in f["hard_blocks"])

    old_b, new_b = blocks(old), blocks(new)
    for (kind, digest), n in (old_b - new_b).items():
        where = next((f"{f['file']}:{b['line']}" for f in old["files"]
                      for b in f["hard_blocks"] if b["sha256"] == digest), "?")
        problems.append(f"{kind} block {digest[:12]} (was {where}) is missing or changed "
                        f"({n} fewer)")
    for (kind, digest), n in (new_b - old_b).items():
        where = next((f"{f['file']}:{b['line']}" for f in new["files"]
                      for b in f["hard_blocks"] if b["sha256"] == digest), "?")
        problems.append(f"{kind} block {digest[:12]} ({where}) is new or changed ({n} more)")

    old_steps = [s["id"] for f in old["files"] for s in f["steps"]]
    new_steps = [s["id"] for f in new["files"] for s in f["steps"]]
    if Counter(old_steps) != Counter(new_steps):
        gone = Counter(old_steps) - Counter(new_steps)
        came = Counter(new_steps) - Counter(old_steps)
        problems.append("step ids differ: missing " + (", ".join(sorted(gone)) or "none")
                        + "; new " + (", ".join(sorted(came)) or "none"))
    # A reviewed reorder exempts the HEADINGS inside its old line range, each once, by
    # their text -- never every step that shares their id. The rest keep their order.
    spans = [r["old_lines"] for r in reorders or ()]

    def in_span(f: dict, s: dict) -> bool:
        return f["file"] == "SKILL.md" and any(a <= s["line"] <= b for a, b in spans)

    moved = Counter((s["id"], s["heading"]) for f in old["files"] for s in f["steps"]
                    if in_span(f, s))
    kept_order = [s["id"] for f in old["files"] for s in f["steps"] if not in_span(f, s)]
    for f in new["files"]:
        pos = 0
        for s in f["steps"]:
            if moved[(s["id"], s["heading"])] > 0:
                moved[(s["id"], s["heading"])] -= 1
                continue                 # a reviewed reorder: its order is conserve's to hold
            try:
                pos = kept_order.index(s["id"], pos) + 1
            except ValueError:
                if s["id"] in old_steps:
                    problems.append(f"step order changed: Step {s['id']} at "
                                    f"{f['file']}:{s['line']} now precedes a step it followed")
                break

    def anchor_set(inv: dict) -> Counter:
        return Counter((a["kind"], a["id"]) for f in inv["files"] for a in f["anchors"])

    old_a, new_a = anchor_set(old), anchor_set(new)
    for (kind, ident), _n in (old_a - new_a).items():
        problems.append(f"anchor {kind} `{ident}` is missing")
    for (kind, ident), _n in (new_a - old_a).items():
        problems.append(f"anchor {kind} `{ident}` is new")
    return problems


def render_inventory(inv: dict) -> str:
    out = [f"inventory: {inv['skill']}"]
    for f in inv["files"]:
        out.append(f"\n== {f['file']} ({f['lines']} lines, {f['bytes']} bytes)")
        for b in f["hard_blocks"]:
            out.append(f"  {b['kind']:<9} line {b['line']:>5}-{b['end_line']:<5} byte "
                       f"{b['byte_offset']:>7}  sha256 {b['sha256']}"
                       + ("" if b["terminated"] else "  UNTERMINATED"))
        for s in f["steps"]:
            out.append(f"  step {s['id']:<8} line {s['line']:>5}  {s['heading']}")
        for a in f["anchors"]:
            out.append(f"  anchor    line {a['line']:>5}  {a['kind']} {a['id']}")
        out.append(f"  headings: {len(f['headings'])}")
        for h in f["headings"]:
            out.append(f"    {'#' * h['level']} {h['text']}  (line {h['line']})")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------------------
# conserve
# --------------------------------------------------------------------------------------

def _nonblank(text: str) -> list[tuple[int, str]]:
    """(1-based line number, line text) for every non-blank line."""
    return [(i, l) for i, l in enumerate(text.splitlines(), 1) if l.strip()]


def load_manifest(path: Path) -> dict:
    """Normalised manifest. A missing file is an empty manifest (a pure move needs none)."""
    empty = {"extra_files": [], "deletes": Counter(), "adds": Counter(), "reorders": [],
             "block_moves": []}
    if not path.is_file():
        return empty
    try:
        data = json.loads(_read(path))
    except ValueError as exc:
        raise AuditError(f"{path}: not valid JSON ({exc})") from exc

    def reason_of(entry: dict, kind: str) -> None:
        if not str(entry.get("reason") or "").strip():
            raise AuditError(f"{path}: a `{kind}` entry has no reason (every entry is a "
                             "reviewed exception and says why)")

    def texts(entry: dict, kind: str) -> list[str]:
        if "lines" in entry:
            return [str(t) for t in entry["lines"]]
        if "text" in entry:
            return [str(entry["text"])]
        raise AuditError(f"{path}: a `{kind}` entry needs `text` or `lines`")

    out = dict(empty, extra_files=[str(p) for p in data.get("extra_files", [])],
               reorders=[], block_moves=[])
    for kind in ("deletes", "adds"):
        counter: Counter = Counter()
        for entry in data.get(kind, []):
            reason_of(entry, kind)
            for t in texts(entry, kind):
                if t.strip():
                    counter[t] += int(entry.get("count", 1))
        out[kind] = counter
    for entry in data.get("changes", []):
        reason_of(entry, "changes")
        if "old" not in entry or "new" not in entry:
            raise AuditError(f"{path}: a `changes` entry needs `old` and `new`")
        n = int(entry.get("count", 1))
        if str(entry["old"]).strip():
            out["deletes"][str(entry["old"])] += n
        if str(entry["new"]).strip():
            out["adds"][str(entry["new"])] += n
    for entry in data.get("reorders", []):
        reason_of(entry, "reorders")
        span = entry.get("old_lines")
        if (not isinstance(span, list) or len(span) != 2
                or not all(isinstance(v, int) for v in span) or span[0] > span[1]
                or not entry.get("file")):
            raise AuditError(f"{path}: a `reorders` entry needs `old_lines: [first, last]` "
                             "(line numbers of the old SKILL.md) and `file`")
        out["reorders"].append({"old_lines": (span[0], span[1]), "file": str(entry["file"])})
    for entry in data.get("block_moves", []):
        reason_of(entry, "block_moves")
        digest = str(entry.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{12,64}", digest) or not entry.get("file"):
            raise AuditError(f"{path}: a `block_moves` entry needs `sha256` (the block's "
                             "hash from `inventory`, 12 or more hex digits) and `file`")
        out["block_moves"].append({"sha256": digest, "file": str(entry["file"])})
    return out


def _find_run(haystack: list[str], needle: list[str]) -> int:
    """Index of the first contiguous occurrence of `needle` in `haystack`, or -1."""
    if not needle:
        return -1
    for i in range(len(haystack) - len(needle) + 1):
        if haystack[i:i + len(needle)] == needle:
            return i
    return -1


def conserve(old_files: dict[str, str], new_files: dict[str, str], manifest: dict
             ) -> dict:
    """Compare two corpora (rel -> text). Pure, so the tests can drive it directly."""
    problems: list[str] = []
    old_seq = {rel: _nonblank(text) for rel, text in old_files.items()}
    new_seq = {rel: _nonblank(text) for rel, text in new_files.items()}
    old_count = Counter(t for seq in old_seq.values() for _, t in seq)
    new_count = Counter(t for seq in new_seq.values() for _, t in seq)
    deletes, adds = manifest["deletes"], manifest["adds"]

    # 1. Counts: now == then - deletes + adds, for every line.
    def first(seqs: dict, text: str) -> str:
        for rel, seq in seqs.items():
            for lineno, t in seq:
                if t == text:
                    return f"{rel}:{lineno}"
        return "?"

    count_problems = 0
    for text in sorted(set(old_count) | set(new_count) | set(deletes) | set(adds)):
        expected = old_count[text] - deletes[text] + adds[text]
        actual = new_count[text]
        if actual == expected:
            continue
        count_problems += 1
        shown = text if len(text) <= 110 else text[:107] + "..."
        if actual < expected:
            problems.append(f"line lost or changed ({old_count[text]} before, {actual} now, "
                            f"{expected} expected), was {first(old_seq, text)}: {shown!r}")
        else:
            problems.append(f"line added or changed ({old_count[text]} before, {actual} now, "
                            f"{expected} expected), now {first(new_seq, text)}: {shown!r}")

    # 2. Reviewed reorders: the span must sit whole, in order, in the file it names.
    #    The manifest excuses a COUNT of lines, never a text: `adds: fi x1` lets one new
    #    `fi` go without an old place, and every other `fi` is checked like any line.
    add_left, del_left = Counter(adds), Counter(deletes)

    def all_added(text: str) -> bool:        # every occurrence now is a manifest add
        return 0 < new_count[text] <= adds[text]

    def all_deleted(text: str) -> bool:      # every occurrence then is a manifest delete
        return 0 < old_count[text] <= deletes[text]

    old_skill = old_seq.get("SKILL.md", [])
    skip_old: set[tuple[str, int]] = set()       # (old rel, index into its sequence)
    skip_new: set[tuple[str, int]] = set()

    def align(span: list[tuple[int, str]], kept: list[tuple[int, str]], start: int):
        """The span laid over `kept` from `start`: (new indices used, old indices used,
        adds spent, deletes spent), or None. A new line is passed over only against the
        manifest's remaining adds of that text, an old one only against its deletes."""
        used_new: list[int] = []
        used_old: list[int] = []
        spent_add: Counter = Counter()
        spent_del: Counter = Counter()
        a, b = 0, start
        while a < len(span):
            old_i, old_t = span[a]
            new_i, new_t = kept[b] if b < len(kept) else (-1, None)
            if new_t == old_t:
                used_old.append(old_i)
                used_new.append(new_i)
                a, b = a + 1, b + 1
            elif used_old and new_t is not None and add_left[new_t] - spent_add[new_t] > 0:
                spent_add[new_t] += 1
                used_new.append(new_i)
                b += 1
            elif del_left[old_t] - spent_del[old_t] > 0:
                spent_del[old_t] += 1
                used_old.append(old_i)
                a += 1
            else:
                return None
        return (used_new, used_old, spent_add, spent_del) if used_new else None

    for entry in manifest["reorders"]:
        first_line, last_line = entry["old_lines"]
        span = [(i, t) for i, (lineno, t) in enumerate(old_skill)
                if first_line <= lineno <= last_line and not all_deleted(t)
                and ("SKILL.md", i) not in skip_old]
        target = entry["file"]
        if not span:
            problems.append(f"reorder {first_line}-{last_line}: no lines in the old SKILL.md")
            continue
        if target not in new_seq:
            problems.append(f"reorder {first_line}-{last_line}: {target} is not in the corpus")
            continue
        kept = [(i, t) for i, (_, t) in enumerate(new_seq[target])
                if not all_added(t) and (target, i) not in skip_new]
        at = _find_run([t for _, t in kept], [t for _, t in span])
        if at >= 0:                              # the usual case: one verbatim run
            found = ([i for i, _ in kept[at:at + len(span)]], [i for i, _ in span],
                     Counter(), Counter())
        else:
            found = next((hit for hit in (align(span, kept, start)
                                          for start in range(len(kept))) if hit), None)
        if found is None:
            problems.append(f"reorder {first_line}-{last_line}: the span is not whole and "
                            f"in order in {target} (first line {span[0][1][:80]!r})")
            continue
        used_new, used_old, spent_add, spent_del = found
        add_left -= spent_add
        del_left -= spent_del
        skip_old.update(("SKILL.md", i) for i in used_old)
        skip_new.update((target, i) for i in used_new)

    # 3. Order. Anchors (lines that occur once on each side) keep their old order inside
    #    every new file. Every other line -- one that repeats: a fence, a table rule --
    #    must CLAIM an old occurrence of its own, and no old occurrence is claimed twice.
    #    Where it may look depends on its neighbours in the new file:
    #      between two anchors of one old file, in old order   the old lines between them
    #      anything else (start or end of a file, neighbours   the old lines next to the
    #      from two old files)                                 anchor it leans on
    #    A line of a moved span is passed over, so its neighbours are the anchors on
    #    either side of the span.
    old_pos: dict[str, tuple[str, int]] = {}
    for rel, seq in old_seq.items():
        for i, (_, t) in enumerate(seq):
            if old_count[t] == 1 and new_count[t] == 1 and not adds[t] and not deletes[t] \
                    and (rel, i) not in skip_old:
                old_pos[t] = (rel, i)
    anchor_idx = {rel: [i for i, (_, t) in enumerate(seq) if old_pos.get(t) == (rel, i)]
                  for rel, seq in old_seq.items()}
    order_problems = 0
    Anchor = tuple[str, int]
    #: (new file, anchor before or None, anchor after or None, the lines between)
    gaps: list[tuple[str, Anchor | None, Anchor | None, list[tuple[int, str]]]] = []
    for rel, seq in new_seq.items():
        last: dict[str, tuple[int, int, str]] = {}      # old rel -> (old idx, lineno, text)
        prev: Anchor | None = None
        between: list[tuple[int, str]] = []
        for i, (lineno, text) in enumerate(seq):
            if (rel, i) in skip_new:
                # A moved span is NOT an edge: the lines around it still sit between the
                # anchor before it and the anchor after it, and are held to that.
                continue
            if text not in old_pos:
                if not all_added(text):
                    between.append((lineno, text))
                continue
            src, idx = old_pos[text]
            if src in last and idx < last[src][0]:
                order_problems += 1
                problems.append(
                    f"order changed in {rel}: line {lineno} {text[:80]!r} now follows line "
                    f"{last[src][1]} {last[src][2][:60]!r}, which it preceded in {src}")
            gaps.append((rel, prev, (src, idx), between))
            last[src] = (idx, lineno, text)      # one report per break, not per line
            prev, between = (src, idx), []
        gaps.append((rel, prev, None, between))

    claimed: set[tuple[str, int]] = set()

    def free(src: str, j: int, text: str) -> bool:
        return (old_seq[src][j][1] == text and (src, j) not in claimed
                and (src, j) not in skip_old)

    Claims = tuple[list[tuple[str, int]], Counter]

    def take(src: str, positions, wanted: list[str], sparing: bool = False) -> Claims | None:
        """Claims for `wanted`, in order, walking `positions` once, and the lines left
        without one; None when a line has no free old occurrence on the way. Only a
        `sparing` call may leave a line unclaimed, and only against the manifest's
        remaining adds of that text -- with as few such lines as the order allows."""
        got: list[tuple[str, int]] = []
        it = iter(positions)
        for text in wanted:
            for j in it:
                if free(src, j, text):
                    got.append((src, j))
                    break
            else:
                break
        else:
            return got, Counter()
        if not sparing or not any(add_left[t] > 0 for t in wanted):
            return None
        texts = set(wanted)
        spots = [j for j in positions if old_seq[src][j][1] in texts
                 and (src, j) not in claimed and (src, j) not in skip_old]
        n, m = len(wanted), len(spots)
        inf = n + 1
        spare = [add_left[t] > 0 for t in wanted]
        # cost[i][j]: fewest unclaimed lines placing wanted[i:] on spots[j:]
        cost = [[inf] * (m + 1) for _ in range(n)] + [[0] * (m + 1)]
        for i in range(n - 1, -1, -1):
            row, below = cost[i], cost[i + 1]
            row[m] = min(inf, below[m] + 1) if spare[i] else inf
            for j in range(m - 1, -1, -1):
                best = row[j + 1]
                if old_seq[src][spots[j]][1] == wanted[i]:
                    best = min(best, below[j + 1])
                if spare[i]:
                    best = min(best, below[j] + 1)
                row[j] = best
        if cost[0][0] >= inf:
            return None
        got, spared = [], Counter()
        i = j = 0
        while i < n:
            if j < m and old_seq[src][spots[j]][1] == wanted[i] \
                    and cost[i][j] == cost[i + 1][j + 1]:
                got.append((src, spots[j]))
                i, j = i + 1, j + 1
            elif j < m and cost[i][j] == cost[i][j + 1]:
                j += 1
            else:
                spared[wanted[i]] += 1
                i += 1
        if any(n_spared > add_left[t] for t, n_spared in spared.items()):
            return None
        return got, spared

    def settle(*parts: Claims) -> bool:
        """Record the claims, and charge the unclaimed lines to the manifest's adds."""
        spared: Counter = Counter()
        for _got, part in parts:
            spared += part
        if any(n > add_left[t] for t, n in spared.items()):
            return False
        for got, _part in parts:
            claimed.update(got)
        add_left.subtract(spared)
        return True

    def neighbour(src: str, idx: int, step: int) -> int:
        """The old anchor next to `idx` in direction `step`, or the file's edge."""
        ids = anchor_idx[src]
        if step > 0:
            return next((a for a in ids if a > idx), len(old_seq[src]))
        return next((a for a in reversed(ids) if a < idx), -1)

    def lean(gap, tight: bool, sparing: bool = False) -> bool:
        """Split the lines: the first k follow the anchor before, the rest precede the
        anchor after. `tight` stops at the next old anchor; loose runs to the file's edge."""
        _rel, before, after, lines = gap
        texts = [t for _, t in lines]
        if not before and not after:
            # No unique line to lean on (a file made only of lines that repeat): the lines
            # must still be free, in order, in ONE old file. Only tried once nothing else
            # is waiting for them.
            if tight:
                return False
            for src in old_seq:
                got = take(src, range(len(old_seq[src])), texts, sparing)
                if got is not None and settle(got):
                    return True
            return False
        nothing: Claims = ([], Counter())
        for k in range(len(texts) if before else 0, (-1 if after else len(texts) - 1), -1):
            head: Claims | None = nothing
            tail: Claims | None = nothing
            if k:
                src, idx = before
                stop = neighbour(src, idx, +1) if tight else len(old_seq[src])
                head = take(src, range(idx + 1, stop), texts[:k], sparing)
            if head is not None and k < len(texts):
                src, idx = after
                stop = neighbour(src, idx, -1) if tight else -1
                tail = take(src, range(idx - 1, stop, -1), texts[k:][::-1], sparing)
            if head is not None and tail is not None and not set(head[0]) & set(tail[0]) \
                    and settle(head, tail):
                return True
        return False

    def bounded(gap) -> bool:
        _rel, before, after, _lines = gap
        return bool(before and after and before[0] == after[0] and before[1] < after[1])

    def fits_between(gap, sparing: bool = False) -> bool:
        _rel, before, after, lines = gap
        got = take(before[0], range(before[1] + 1, after[1]), [t for _, t in lines], sparing)
        return got is not None and settle(got)

    def unplaced(gap, where: str) -> None:
        nonlocal order_problems
        rel, _before, _after, lines = gap
        order_problems += 1
        b_line, b_text = lines[0]
        more = f" (and {len(lines) - 1} more line(s) to line {lines[-1][0]})" \
            if len(lines) > 1 else ""
        problems.append(f"order changed in {rel}: line {b_line} {b_text[:80]!r}{more} is not "
                        f"where it was {where}")

    work = [g for g in gaps if g[3]]
    # Most constrained first, so a line that can only come from one place gets it:
    # leaning lines beside their own anchor, then lines between two anchors, then the
    # leaning lines that found nothing close by. Every line is asked to claim an old
    # occurrence first; only what is left over is set against the manifest's adds.
    deferred = [g for g in work if not bounded(g) and not lean(g, tight=True)]
    leftover = [g for g in work if bounded(g) and not fits_between(g)]
    leftover += [g for g in deferred if not lean(g, tight=False)]
    for gap in leftover:
        if bounded(gap):
            if not fits_between(gap, sparing=True):
                unplaced(gap, f"between its neighbours in {gap[1][0]}")
        elif not (lean(gap, tight=True, sparing=True) or lean(gap, tight=False, sparing=True)):
            unplaced(gap, "beside its neighbours (at the start or end of a file, a repeated "
                          "line must come from the old lines there)")

    # 4. A must-hold block that was in SKILL.md is still in SKILL.md.
    elsewhere: dict[str, set[str]] = {}
    for rel, text in new_files.items():
        if rel != "SKILL.md":
            for b in hard_blocks(text):
                elsewhere.setdefault(b["sha256"], set()).add(rel)
    block_problems = blocks_that_left_skill_md(
        hard_blocks(old_files.get("SKILL.md", "")), hard_blocks(new_files.get("SKILL.md", "")),
        elsewhere, manifest.get("block_moves"))
    problems += block_problems

    return {
        "schema": "skill-conserve.v1",
        "ok": not problems,
        "old_files": list(old_files),
        "new_files": list(new_files),
        "old_nonblank_lines": sum(old_count.values()),
        "new_nonblank_lines": sum(new_count.values()),
        "manifest": {"deletes": sum(deletes.values()), "adds": sum(adds.values()),
                     "reorders": len(manifest["reorders"]),
                     "block_moves": len(manifest.get("block_moves") or []),
                     "extra_files": manifest["extra_files"]},
        "count_problems": count_problems,
        "order_problems": order_problems,
        "block_problems": len(block_problems),
        "problems": problems,
    }


def run_conserve(root: Path, name: str, ref: str, manifest_path: Path | None = None) -> dict:
    manifest = load_manifest(manifest_path or (root / name / MANIFEST_FILE))
    old = SkillFiles.from_ref(root, name, ref)
    new = SkillFiles.from_tree(root, name)
    old_files, new_files = dict(old.files), dict(new.files)
    top, prefix = _git_top(root)
    for extra in manifest["extra_files"]:
        key = "../" + extra
        if not (root / extra).is_file():
            raise AuditError(f"manifest extra file does not exist: {root / extra}")
        new_files[key] = _read(root / extra)
        listed = _git(top, "ls-tree", "--name-only", ref, "--", prefix + extra).strip()
        if listed:
            old_files[key] = _git(top, "show", f"{ref}:{prefix}{extra}")
    result = conserve(old_files, new_files, manifest)
    result.update(skill=name, before=ref)
    return result


def render_conserve(r: dict) -> str:
    m = r["manifest"]
    out = [f"conserve: {r.get('skill', '?')} against {r.get('before', '?')} -- "
           + ("PASS" if r["ok"] else "FAIL"),
           f"  then: {len(r['old_files'])} file(s), {r['old_nonblank_lines']} non-blank lines"
           f"   now: {len(r['new_files'])} file(s), {r['new_nonblank_lines']} non-blank lines",
           f"  manifest: {m['deletes']} delete(s), {m['adds']} add(s), {m['reorders']} "
           f"reviewed reorder(s), extra files: {', '.join(m['extra_files']) or 'none'}"]
    if not r["ok"]:
        out.append(f"  {r['count_problems']} count problem(s), {r['order_problems']} order "
                   f"problem(s), {r.get('block_problems', 0)} must-hold block problem(s):")
        out.extend("    " + p for p in r["problems"][:60])
        if len(r["problems"]) > 60:
            out.append(f"    ... and {len(r['problems']) - 60} more (--json lists all)")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="skill_audit.py",
        description="Audit skills against the Anthropic skill standard (#344).")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audit", help="audit a skills tree")
    a.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                   help="skills directory (default: the repo skills/ beside this file)")
    a.add_argument("--only", default="", help="comma-separated skill names")
    a.add_argument("--json", action="store_true")
    a.add_argument("--strict", action="store_true",
                   help="hold every audited skill to the rules, listed or not")
    a.add_argument("--verbose", action="store_true",
                   help="print every finding and note, not per-skill counts")

    c = sub.add_parser("check", help="audit the skills that staged files belong to")
    c.add_argument("--repo", type=Path, default=DEFAULT_ROOT.parent,
                   help="repository root (default: the repo this file sits in)")
    where = c.add_mutually_exclusive_group()
    where.add_argument("--index", dest="source", action="store_const", const="index",
                       help="read the skill and both lists from the git index (the "
                            "default when --repo is the top of a checkout)")
    where.add_argument("--tree", dest="source", action="store_const", const="tree",
                       help="read the working tree instead of what is staged")
    c.set_defaults(source="auto")
    c.add_argument("--paths-from", default=None,
                   help="`-`: read NUL-separated paths from stdin")
    c.add_argument("files", nargs="*")

    b = sub.add_parser("listing-budget", help="ESTIMATE the skill listing's context cost")
    b.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    b.add_argument("--fraction", type=float, default=LISTING_DEFAULT_FRACTION,
                   help="skillListingBudgetFraction (default 0.01)")
    b.add_argument("--context-tokens", type=int, default=200_000)
    b.add_argument("--json", action="store_true")

    i = sub.add_parser("inventory", help="must-hold blocks, steps and anchors of a skill")
    i.add_argument("skill")
    i.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    i.add_argument("--ref", default=None, help="read the skill at this git revision")
    i.add_argument("--against", default=None,
                   help="compare with the inventory at this git revision; exit 1 on a "
                        "difference")
    i.add_argument("--json", action="store_true")

    v = sub.add_parser("conserve", help="prove a split moved text without changing it")
    v.add_argument("--before", required=True, help="git revision of the unsplit skill")
    v.add_argument("--skill", required=True)
    v.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    v.add_argument("--manifest", type=Path, default=None,
                   help="default: <skill>/" + MANIFEST_FILE)
    v.add_argument("--json", action="store_true")
    return p


def _dump(obj: dict) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    _harden_streams()
    args = _parser().parse_args(argv)
    try:
        if args.cmd == "audit":
            root = args.root.resolve()
            only = [n.strip() for n in args.only.split(",") if n.strip()]
            report = run_audit(root, only, load_conformant(_HERE), load_exemptions(_HERE),
                               strict=args.strict)
            sys.stdout.write(_dump(report) if args.json
                             else render_audit(report, verbose=args.verbose))
            return report["exit_code"]

        if args.cmd == "check":
            paths = list(args.files)
            if args.paths_from == "-":
                data = sys.stdin.buffer.read().decode("utf-8", errors="surrogateescape")
                paths += [p for p in data.split("\0") if p]
            elif args.paths_from is not None:
                raise AuditError("--paths-from accepts only `-` (NUL-separated stdin)")
            rc, out = run_check(args.repo.resolve(), paths, source=args.source)
            sys.stdout.write(out)
            return rc

        if args.cmd == "listing-budget":
            if not 0 < args.fraction <= 1 or args.context_tokens <= 0:
                raise AuditError("--fraction must be in (0, 1] and --context-tokens positive")
            result = run_listing_budget(args.root.resolve(), args.fraction,
                                        args.context_tokens)
            sys.stdout.write(_dump(result) if args.json else render_listing_budget(result))
            return EXIT_OK

        if args.cmd == "inventory":
            root = args.root.resolve()
            skill = (SkillFiles.from_ref(root, args.skill, args.ref) if args.ref
                     else SkillFiles.from_tree(root, args.skill))
            inv = run_inventory(skill)
            if args.ref:
                inv["ref"] = args.ref
            own = inventory_problems(inv)
            inv["problems"] = own
            problems: list[str] = []
            if args.against:
                reviewed = load_manifest(root / args.skill / MANIFEST_FILE)
                problems = compare_inventories(
                    run_inventory(SkillFiles.from_ref(root, args.skill, args.against)), inv,
                    block_moves=reviewed["block_moves"], reorders=reviewed["reorders"])
                inv["against"] = {"ref": args.against, "ok": not problems,
                                  "problems": problems}
            if args.json:
                sys.stdout.write(_dump(inv))
            else:
                sys.stdout.write(render_inventory(inv))
                if own:
                    sys.stdout.write("\nPROBLEMS\n" + "".join(f"  {p}\n" for p in own))
                if args.against:
                    sys.stdout.write(
                        f"\nagainst {args.against}: "
                        + ("SAME must-hold blocks, step ids and anchors\n" if not problems
                           else "DIFFERENT\n" + "".join(f"  {p}\n" for p in problems)))
            return EXIT_FINDINGS if (problems or own) else EXIT_OK

        if args.cmd == "conserve":
            result = run_conserve(args.root.resolve(), args.skill, args.before, args.manifest)
            sys.stdout.write(_dump(result) if args.json else render_conserve(result))
            return EXIT_OK if result["ok"] else EXIT_FINDINGS
    except AuditError as exc:
        sys.stderr.write(f"skill_audit: {exc}\n")
        return EXIT_BAD_INPUT
    return EXIT_BAD_INPUT


if __name__ == "__main__":
    sys.exit(main())
