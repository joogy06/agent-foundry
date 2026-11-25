#!/usr/bin/env python3
"""skill_frontmatter.py -- #344. One reader for CUSTOM frontmatter keys of a SKILL.md.

The skill standard keeps custom data under `metadata:` as strings. This library grew its
custom keys (`disambiguation`, `family`, `applies_when`, `version`) at the top level, and
several tools read them there with their own regular expression. This module is the one
place that knows both layouts, so a skill can move a key under `metadata:` without any
reader losing sight of it.

    has(fm_text, key)    -> bool         is the key declared at all (presence)
    value(fm_text, key)  -> str | None   its decoded value, None when it is absent
    read(fm_text, key)   -> Lookup       both, plus why a value could not be read

`fm_text` is the text between the two `---` lines (`frontmatter_of(text)` cuts it out of
a whole file). Pass `path=` so an error can name the file.

PRECEDENCE. `metadata.<key>` first, then the top-level key. When both are present their
decoded values must be equal; if they differ, `FrontmatterConflict` is raised and names
the file and the key. Two copies that disagree are never resolved silently.

PARSING. PyYAML when it is importable. Otherwise, and whenever the frontmatter is not
valid YAML (an unquoted `: ` in a description is the usual cause), a line reader:
top-level keys at column 0 (bare, or a quoted key such as `"metadata":`), and the
children of a block `metadata:` at exactly two spaces, each a plain or a single- or
double-quoted scalar on ONE line. Whatever the line reader cannot read faithfully -- a
flow map, a block scalar, a value that continues on the next line, tab indentation,
`metadata` that is not a mapping, and ANY column-0 line that is not `key: value` (it is
mapping syntax that could hold the key asked for) -- is reported as `unsupported`, never
guessed: `read` returns it in `Lookup.status`, and `has` / `value` raise
`FrontmatterUnsupported`. CRLF line ends are accepted.

A DUPLICATED key (the key itself at one level, or `metadata` twice) is `unsupported` in
BOTH engines: PyYAML alone would keep the last copy without a word, and two engines that
answer one file differently are worse than no answer.

Standard fields (`name`, `description`, ...) are NOT this module's job; the tools that
parse them keep their own parsers.

Stdlib only; PyYAML is optional.
"""
from __future__ import annotations

import re
import sys
from typing import List, NamedTuple, Optional, Tuple

try:  # optional: the line reader below serves when PyYAML is absent
    import yaml as _yaml
except Exception:  # pragma: no cover - exercised by forcing engine="lines"
    _yaml = None

OK = "ok"
UNSUPPORTED = "unsupported"
ENGINES = ("auto", "yaml", "lines")

_KEY = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
_TOP_RE = re.compile(rf"^({_KEY}):(?:[ \t]+(.*))?$")
_CHILD_RE = re.compile(rf"^({_KEY}):(?:[ \t]+(.*))?$")
_QUOTED_TOP_RE = re.compile(
    r"""^("(?:[^"\\]|\\.)*"|'(?:[^']|'')*')[ \t]*:(?:[ \t]+(.*))?$""")
_COMMENT_RE = re.compile(r"(?:^|[ \t]+)#.*$")
_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v",
    "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\",
    "N": "\x85", "_": "\xa0", "L": " ", "P": " ",
}
_HEX_ESCAPES = {"x": 2, "u": 4, "U": 8}


class FrontmatterConflict(ValueError):
    """A key is set at the top level AND under `metadata:` with different values."""

    def __init__(self, path, key: str, top: str, meta: str) -> None:
        self.path = str(path) if path is not None else None
        self.key = key
        self.top = top
        self.meta = meta
        super().__init__(
            f"{self.path or '<frontmatter>'}: frontmatter key `{key}` is set at the top level "
            f"and under `metadata:` with different values (top level {top!r}, metadata {meta!r}); "
            "keep one copy")


class FrontmatterUnsupported(ValueError):
    """The frontmatter uses a form this reader will not guess at."""

    def __init__(self, path, key: str, reason: str) -> None:
        self.path = str(path) if path is not None else None
        self.key = key
        self.reason = reason
        super().__init__(f"{self.path or '<frontmatter>'}: frontmatter key `{key}`: {reason}")


class Lookup(NamedTuple):
    """What one key resolves to.

    status   "ok" or "unsupported"
    present  True / False, or None when presence itself could not be decided
    value    the decoded string; None when absent or unreadable
    source   "metadata", "top", "both" (present twice with equal values) or None
    reason   why the status is "unsupported" ("" otherwise)
    engine   "yaml" or "lines" -- the reader that produced the answer
    """
    status: str
    present: Optional[bool]
    value: Optional[str]
    source: Optional[str]
    reason: str
    engine: str


class _Slot(NamedTuple):
    """One place a key can live. `value` None with `present` True = present, unreadable."""
    present: bool
    value: Optional[str] = None
    reason: str = ""


class _Undecidable(Exception):
    """The reader cannot say whether the key is present (whole-scope problem)."""


_ABSENT = _Slot(False)


def have_yaml() -> bool:
    return _yaml is not None


def frontmatter_of(text: str) -> Optional[str]:
    """The text between the opening and the closing `---` line, or None.

    Line ends are returned as they are in the file; every reader here accepts CRLF.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n").rstrip() == "---":
            return "".join(lines[1:i])
    return None


# ---------------------------------------------------------------------------- line reader

def _normalise(fm_text: str) -> List[str]:
    return fm_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _is_noise(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _decode_double(rest: str) -> Tuple[Optional[str], str]:
    out = []
    i = 1
    while i < len(rest):
        ch = rest[i]
        if ch == '"':
            tail = rest[i + 1:]
            if tail.strip() and not re.match(r"^[ \t]+#", tail):
                return None, "text after the closing quote"
            return "".join(out), ""
        if ch == "\\":
            i += 1
            if i >= len(rest):
                return None, "a quoted value that continues on the next line"
            esc = rest[i]
            if esc in _ESCAPES:
                out.append(_ESCAPES[esc])
            elif esc in _HEX_ESCAPES:
                digits = rest[i + 1:i + 1 + _HEX_ESCAPES[esc]]
                if len(digits) != _HEX_ESCAPES[esc] or not re.fullmatch(r"[0-9A-Fa-f]+", digits):
                    return None, f"a malformed \\{esc} escape"
                try:
                    out.append(chr(int(digits, 16)))
                except (ValueError, OverflowError):
                    return None, f"a malformed \\{esc} escape"
                i += _HEX_ESCAPES[esc]
            else:
                return None, f"an unknown escape \\{esc}"
        else:
            out.append(ch)
        i += 1
    return None, "a quoted value that is not closed on its line"


def _decode_single(rest: str) -> Tuple[Optional[str], str]:
    out = []
    i = 1
    while i < len(rest):
        ch = rest[i]
        if ch == "'":
            if rest[i + 1:i + 2] == "'":
                out.append("'")
                i += 2
                continue
            tail = rest[i + 1:]
            if tail.strip() and not re.match(r"^[ \t]+#", tail):
                return None, "text after the closing quote"
            return "".join(out), ""
        out.append(ch)
        i += 1
    return None, "a quoted value that is not closed on its line"


def _decode_scalar(rest: Optional[str], continued: bool) -> Tuple[Optional[str], str]:
    """Decode the text after `key:` on one line. (None, reason) = present but unreadable."""
    rest = (rest or "").strip()
    if not rest or rest.startswith("#"):
        if continued:
            return None, "a nested or multi-line value"
        return "", ""
    first = rest[0]
    if first in "|>":
        return None, "a block scalar"
    if first in "{[":
        return None, "a flow collection"
    if first in "&*!":
        return None, "an anchor, alias or tag"
    if continued:
        return None, "a value that continues on the next line"
    if first == '"':
        return _decode_double(rest)
    if first == "'":
        return _decode_single(rest)
    return _COMMENT_RE.sub("", rest).rstrip(), ""


def _top_key(line: str) -> Tuple[Optional[str], Optional[str]]:
    """(key, rest) of a column-0 line; key None when it is not a `key: value` line this
    reader can parse (a flow map, a complex key, a tagged key, a quoted key it cannot
    decode)."""
    m = _TOP_RE.match(line)
    if m:
        return m.group(1), m.group(2)
    q = _QUOTED_TOP_RE.match(line)
    if q:
        token = q.group(1)
        key, _why = _decode_double(token) if token[0] == '"' else _decode_single(token)
        if key is not None:
            return key, q.group(2)
    return None, None


def _entries(lines: List[str]) -> List[Tuple[Optional[str], Optional[str], List[str]]]:
    """Group the frontmatter into top-level entries: (key or None, rest, continuation lines).

    A line indented before any key is an entry with key None too: nothing is dropped.
    """
    out: List[Tuple[Optional[str], Optional[str], List[str]]] = []
    for line in lines:
        if not line.strip():
            if out:
                out[-1][2].append(line)
            continue
        if line[:1] in (" ", "\t"):
            if out:
                out[-1][2].append(line)
            elif not line.strip().startswith("#"):
                out.append((None, None, []))
            continue
        if line.startswith("#"):
            continue
        key, rest = _top_key(line.rstrip())
        out.append((key, rest, []))
    return out


def _lines_slots(fm_text: str, key: str) -> Tuple[_Slot, _Slot]:
    """(top-level slot, metadata slot) by the line reader. Raises _Undecidable."""
    entries = _entries(_normalise(fm_text))
    if any(e[0] is None for e in entries):
        # Unparsed mapping syntax could hold the key (or `metadata`): absent would be a guess.
        raise _Undecidable("a top-level line that is not `key: value` (a flow map, a complex "
                           "or tagged key, or a quoted key that cannot be decoded)")

    tops = [e for e in entries if e[0] == key]
    if len(tops) > 1:
        raise _Undecidable(f"`{key}` appears {len(tops)} times at the top level")
    if tops:
        _k, rest, cont = tops[0]
        val, why = _decode_scalar(rest, any(not _is_noise(c) for c in cont))
        top = _Slot(True, val, why)
    else:
        top = _ABSENT

    metas = [e for e in entries if e[0] == "metadata"]
    if key == "metadata" or not metas:
        return top, _ABSENT
    if len(metas) > 1:
        raise _Undecidable("`metadata` appears more than once")
    _k, rest, cont = metas[0]
    rest = _COMMENT_RE.sub("", rest or "").strip()
    children = [c for c in cont if not _is_noise(c)]
    if rest in ("~", "null", "Null", "NULL") and not children:
        return top, _ABSENT
    if rest:
        raise _Undecidable("`metadata` is not a block mapping (a flow map or a scalar)")

    found: List[_Slot] = []
    for child in children:
        indent = child[:len(child) - len(child.lstrip(" \t"))]
        if "\t" in indent:
            raise _Undecidable("tab indentation under `metadata`")
        if len(indent) != 2:
            raise _Undecidable("a `metadata` child that is not indented by two spaces "
                               "(a nested value, a block scalar or a continuation line)")
        m = _CHILD_RE.match(child[2:].rstrip())
        if not m:
            raise _Undecidable("a line under `metadata` that is not `key: value`")
        if m.group(1) == key:
            val, why = _decode_scalar(m.group(2), False)
            found.append(_Slot(True, val, why))
    if len(found) > 1:
        raise _Undecidable(f"`metadata.{key}` appears {len(found)} times")
    return top, (found[0] if found else _ABSENT)


# ---------------------------------------------------------------------------- YAML reader

def _yaml_slot(container: dict, key: str, raw: _Slot) -> _Slot:
    if key not in container:
        return _ABSENT
    val = container[key]
    if isinstance(val, str):
        return _Slot(True, val)
    if isinstance(val, (dict, list)):
        return _Slot(True, None, "a mapping or a list, not a string")
    # null, bool, number, date: YAML resolved the text to another type. The value a reader
    # wants is the text as written, so take it from the line reader -- or say unsupported.
    if raw.present and raw.value is not None:
        return _Slot(True, raw.value)
    return _Slot(True, None, f"a {type(val).__name__} whose source text cannot be recovered")


def _key_count(node, wanted: str) -> int:
    """How often `wanted` is a scalar key of a mapping node (0 for any other node)."""
    if not isinstance(node, _yaml.MappingNode):
        return 0
    return sum(1 for k, _v in node.value
               if isinstance(k, _yaml.ScalarNode) and k.value == wanted)


def _refuse_duplicates(root, key: str) -> None:
    """PyYAML keeps the LAST copy of a duplicated key and says nothing. Refuse it, with
    the line reader's own wording, so both engines give one answer."""
    n = _key_count(root, key)
    if n > 1:
        raise _Undecidable(f"`{key}` appears {n} times at the top level")
    if key == "metadata" or not isinstance(root, _yaml.MappingNode):
        return
    if _key_count(root, "metadata") > 1:
        raise _Undecidable("`metadata` appears more than once")
    for k, v in root.value:
        if isinstance(k, _yaml.ScalarNode) and k.value == "metadata":
            n = _key_count(v, key)
            if n > 1:
                raise _Undecidable(f"`metadata.{key}` appears {n} times")


def _yaml_slots(fm_text: str, key: str) -> Tuple[_Slot, _Slot]:
    if _yaml is None:
        raise _Undecidable("PyYAML is not importable")
    text = fm_text.replace("\r\n", "\n").replace("\r", "\n")
    try:
        data = _yaml.safe_load(text)
        root = _yaml.compose(text, Loader=_yaml.SafeLoader)
    except _yaml.YAMLError as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise _Undecidable(f"not valid YAML ({first})") from None
    _refuse_duplicates(root, key)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise _Undecidable("the frontmatter is not a mapping")
    try:
        raw_top, raw_meta = _lines_slots(fm_text, key)
    except _Undecidable:
        raw_top, raw_meta = _ABSENT, _ABSENT
    top = _yaml_slot(data, key, raw_top)
    if key == "metadata" or "metadata" not in data or data["metadata"] is None:
        return top, _ABSENT
    meta = data["metadata"]
    if not isinstance(meta, dict):
        raise _Undecidable("`metadata` is not a mapping")
    return top, _yaml_slot(meta, key, raw_meta)


# ---------------------------------------------------------------------------- public API

def _combine(top: _Slot, meta: _Slot, key: str, path, engine: str) -> Lookup:
    if meta.present and top.present:
        if meta.value is None or top.value is None:
            why = meta.reason or top.reason
            return Lookup(UNSUPPORTED, True, None, "both",
                          f"set twice and one copy cannot be compared: {why}", engine)
        if meta.value != top.value:
            raise FrontmatterConflict(path, key, top.value, meta.value)
        return Lookup(OK, True, meta.value, "both", "", engine)
    for slot, source in ((meta, "metadata"), (top, "top")):
        if slot.present:
            if slot.value is None:
                return Lookup(UNSUPPORTED, True, None, source, slot.reason, engine)
            return Lookup(OK, True, slot.value, source, "", engine)
    return Lookup(OK, False, None, None, "", engine)


def read(fm_text: str, key: str, *, path=None, engine: str = "auto") -> Lookup:
    """Resolve one key. Raises FrontmatterConflict; never raises for `unsupported`.

    engine "auto"  PyYAML when importable and the text is valid YAML, else the line reader
           "yaml"  PyYAML only (unsupported when it is absent or the text is not YAML)
           "lines" the line reader only
    """
    if engine not in ENGINES:
        raise ValueError(f"engine must be one of {ENGINES}, not {engine!r}")
    if engine in ("auto", "yaml") and (_yaml is not None or engine == "yaml"):
        try:
            top, meta = _yaml_slots(fm_text, key)
            return _combine(top, meta, key, path, "yaml")
        except _Undecidable as exc:
            if engine == "yaml":
                return Lookup(UNSUPPORTED, None, None, None, str(exc), "yaml")
    try:
        top, meta = _lines_slots(fm_text, key)
    except _Undecidable as exc:
        return Lookup(UNSUPPORTED, None, None, None, str(exc), "lines")
    return _combine(top, meta, key, path, "lines")


def has(fm_text: str, key: str, *, path=None, engine: str = "auto") -> bool:
    """True when the key is declared, at the top level or under `metadata:`.

    Presence only: an empty value counts. Raises FrontmatterConflict, and
    FrontmatterUnsupported when presence cannot be decided without guessing.
    """
    found = read(fm_text, key, path=path, engine=engine)
    if found.present is None:
        raise FrontmatterUnsupported(path, key, found.reason)
    return found.present


def value(fm_text: str, key: str, *, path=None, engine: str = "auto") -> Optional[str]:
    """The decoded value, "" for an empty one, None when the key is absent.

    Raises FrontmatterConflict, and FrontmatterUnsupported when the key is (or may be)
    there but its value cannot be read without guessing.
    """
    found = read(fm_text, key, path=path, engine=engine)
    if found.status == UNSUPPORTED:
        raise FrontmatterUnsupported(path, key, found.reason)
    return found.value if found.present else None


def main(argv: Optional[List[str]] = None) -> int:
    """`skill_frontmatter.py FILE KEY [--engine E]` -- print what a key resolves to."""
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Read one custom frontmatter key of a SKILL.md.")
    ap.add_argument("file")
    ap.add_argument("key")
    ap.add_argument("--engine", choices=ENGINES, default="auto")
    args = ap.parse_args(argv)
    try:
        with open(args.file, encoding="utf-8") as fh:
            fm_text = frontmatter_of(fh.read())
    except OSError as exc:
        print(f"skill_frontmatter: cannot read {args.file} ({exc})", file=sys.stderr)
        return 2
    if fm_text is None:
        print(f"skill_frontmatter: {args.file} has no frontmatter", file=sys.stderr)
        return 2
    try:
        found = read(fm_text, args.key, path=args.file, engine=args.engine)
    except FrontmatterConflict as exc:
        print(f"skill_frontmatter: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(found._asdict(), indent=2, ensure_ascii=False))
    return 0 if found.status == OK else 1


if __name__ == "__main__":
    sys.exit(main())
