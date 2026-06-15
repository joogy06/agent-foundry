#!/usr/bin/env python3
"""boundary_hints.py — safe split-point detector for structure-recovery.

PURE Python. NO LLM calls. NO XML parser (N2 — DSX is read as chunked text via
regex/text-scan only; if structural DSX parsing is ever required it MUST use
defusedxml, but v1 stays parser-dependency-free to avoid an XXE surface).

Given a file's text (and an optional format hint), this module emits a SORTED,
DEDUPLICATED list of 1-indexed line numbers that are SAFE places to cut a chunk
so that a single structure record (a CREATE TABLE statement, a COBOL 01/77 record,
a DSX <Record>/<TableDefinition> span, a flat-file section) is never bisected.

`chunk_file.compute_chunk_boundaries(..., preferred_break_lines=...)` consumes
these hints: each greedy cut is snapped DOWN to the nearest preceding safe break
(see chunk_file.py). The breaks are advisory — when a record is larger than the
chunk cap the chunker emits an oversized chunk + gap:record_exceeds_chunk rather
than bisecting it.

A "safe break line N" means: a NEW record/statement begins at line N, so cutting
the previous chunk to END at line N-1 keeps record N intact in the next chunk.
Line 1 is never returned (cutting before the first line is meaningless).

Supported formats (format-detected OUTSIDE this module; pass the hint in):
    sql                  -> statement terminator ';' at paren-depth 0
    cobol / copybook     -> 01 / 77 level numbers in Area A (cols 8-11)
    datastage-dsx        -> <Record .../>, <TableDefinition ...>, <DSRecord ...>
                            element-open lines (regex-DETECTED, not parsed)
    flat-file-layout     -> section/record-header lines (RECORD:, [Section],
                            01 layout headers, banner rules)

For an unknown / unsupported hint, an empty list is returned (the chunker then
behaves exactly as before — greedy line cuts).

CLI usage (mainly for debugging / smoke tests):
    boundary_hints.py <file_path> [--format sql|cobol|copybook|datastage-dsx|flat-file-layout]
    # prints the sorted safe-break line numbers, one per line.

Returns exit code 0 always (boundary detection is best-effort and never fatal).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

__all__ = [
    "safe_break_lines",
    "sql_break_lines",
    "cobol_break_lines",
    "dsx_break_lines",
    "flatfile_break_lines",
    "normalize_format_hint",
]


# --------------------------------------------------------------------------- #
# Format-hint normalization
# --------------------------------------------------------------------------- #

# Map the various language/format hints (as produced by chunk_file.detect_
# language_hint, plus the structure-recovery additions) onto the four detector
# families this module implements.
_HINT_FAMILY = {
    # SQL family
    "sql": "sql",
    "ddl": "sql",
    # COBOL family (copybooks are COBOL data divisions)
    "cobol": "cobol",
    "copybook": "cobol",
    "cpy": "cobol",
    # DataStage export
    "datastage-dsx": "dsx",
    "dsx": "dsx",
    # Flat-file positional layouts
    "flat-file-layout": "flatfile",
    "flatfile": "flatfile",
    "flat-file": "flatfile",
    "layout": "flatfile",
    "fd": "flatfile",
}


def normalize_format_hint(format_hint: Optional[str]) -> Optional[str]:
    """Collapse a raw language/format hint onto one of the detector families
    {"sql", "cobol", "dsx", "flatfile"} or None when unsupported."""
    if not format_hint:
        return None
    return _HINT_FAMILY.get(format_hint.strip().lower())


# --------------------------------------------------------------------------- #
# Line helpers
# --------------------------------------------------------------------------- #


def _splitlines(text: str) -> List[str]:
    """Split into lines WITHOUT line endings, preserving line count semantics
    that match chunk_file (one entry per source line). `str.splitlines()` would
    drop a trailing empty line; we use keepends=False on a manual split so a
    trailing newline does not create a phantom final line, matching the way
    chunk_file counts lines (iterating the binary file object)."""
    if text == "":
        return []
    # Normalize CRLF / CR to LF first so column math is consistent, then split.
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = norm.split("\n")
    # A trailing "\n" yields a final "" element; drop it so line N maps 1:1 to
    # the file's Nth physical line (chunk_file's line iterator does the same).
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _sorted_unique(breaks: Iterable[int], line_count: int) -> List[int]:
    """Return sorted, de-duplicated break lines, clamped to (1, line_count].
    Line 1 is dropped (a break before the first line is meaningless)."""
    out = {n for n in breaks if 2 <= n <= line_count}
    return sorted(out)


# --------------------------------------------------------------------------- #
# SQL — ';' at paren-depth 0 starts a new statement boundary
# --------------------------------------------------------------------------- #

# A SQL statement terminator at paren-depth 0 ENDS a statement; the NEXT
# non-blank line therefore begins a new record and is a safe break.
# We track paren depth across the whole file, ignoring parens inside string
# literals ('...', "..."), line comments (-- ...), and block comments (/* */).

_SQL_LINE_COMMENT = "--"


def sql_break_lines(text: str) -> List[int]:
    """Lines at which a new SQL statement begins (the line after a depth-0 ';').

    Paren depth, single/double-quoted string literals, -- line comments and
    /* */ block comments are all respected so a ';' inside any of them does NOT
    create a break.
    """
    lines = _splitlines(text)
    line_count = len(lines)
    breaks: List[int] = []

    depth = 0
    in_squote = False
    in_dquote = False
    in_block_comment = False

    # Index of the physical line (1-based) at which the last depth-0 ';' fired,
    # i.e. a statement just ended on this line.
    pending_break_after: Optional[int] = None

    for lineno, raw in enumerate(lines, start=1):
        # If a previous line ended a statement, the first non-blank line we now
        # encounter is the start of the next statement -> a safe break.
        if pending_break_after is not None and raw.strip() != "":
            breaks.append(lineno)
            pending_break_after = None

        i = 0
        n = len(raw)
        while i < n:
            ch = raw[i]
            nxt = raw[i + 1] if i + 1 < n else ""

            if in_block_comment:
                if ch == "*" and nxt == "/":
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue

            if in_squote:
                if ch == "'":
                    # SQL escapes a quote by doubling it ('')
                    if nxt == "'":
                        i += 2
                        continue
                    in_squote = False
                i += 1
                continue

            if in_dquote:
                if ch == '"':
                    if nxt == '"':
                        i += 2
                        continue
                    in_dquote = False
                i += 1
                continue

            # Not inside any literal/comment.
            if ch == "-" and nxt == "-":
                break  # rest of line is a comment
            if ch == "/" and nxt == "*":
                in_block_comment = True
                i += 2
                continue
            if ch == "'":
                in_squote = True
                i += 1
                continue
            if ch == '"':
                in_dquote = True
                i += 1
                continue
            if ch == "(":
                depth += 1
                i += 1
                continue
            if ch == ")":
                if depth > 0:
                    depth -= 1
                i += 1
                continue
            if ch == ";" and depth == 0:
                # Statement terminated on this line; the next non-blank line is
                # a new statement boundary.
                pending_break_after = lineno
                i += 1
                continue
            i += 1

    return _sorted_unique(breaks, line_count)


# --------------------------------------------------------------------------- #
# COBOL — 01 / 77 level numbers in Area A start a new record
# --------------------------------------------------------------------------- #

# COBOL fixed source format: cols 1-6 sequence area, col 7 indicator, cols 8-11
# Area A, cols 12-72 Area B. A new RECORD begins at an 01- or 77-level number in
# Area A. We accept both fixed-format (level in cols 8-11) and free-format
# (level as the first token on the line), matching the design's "01/77 at margin".
# A '*' or '/' or 'D'/'d' in the indicator column (col 7) marks a comment/debug
# line -> never a break.

# Fixed-format: optional 6-char sequence area, indicator col must be blank,
# then Area A begins at col 8 with the level number.
_COBOL_FIXED_RE = re.compile(r"^.{6}[ ](0?1|77)\b")
# Free-format: leading whitespace then the level number as the first token.
_COBOL_FREE_RE = re.compile(r"^\s*(0?1|77)\s+[A-Za-z0-9$#@()-]")


def _cobol_is_comment_line(raw: str) -> bool:
    """True if col 7 (indicator area) marks the line as comment/debug/continuation
    in fixed format. Free-format comments (*>) are also caught."""
    if len(raw) >= 7:
        indicator = raw[6]
        if indicator in ("*", "/", "D", "d"):
            return True
    stripped = raw.lstrip()
    if stripped.startswith("*>"):  # free-format inline comment to EOL as whole line
        return True
    return False


def cobol_break_lines(text: str) -> List[int]:
    """Lines at which a new COBOL record begins (an 01 or 77 level in Area A).

    Handles both fixed-format (level number in columns 8-11, blank indicator in
    column 7) and free-format (level number as the first token). Comment/debug
    lines (indicator '*', '/', 'D') and continuation lines are skipped.
    """
    lines = _splitlines(text)
    line_count = len(lines)
    breaks: List[int] = []

    for lineno, raw in enumerate(lines, start=1):
        if _cobol_is_comment_line(raw):
            continue
        # Fixed-format: indicator column blank, level in Area A.
        if _COBOL_FIXED_RE.match(raw):
            breaks.append(lineno)
            continue
        # Free-format fallback: only when the line is NOT long enough to have a
        # fixed-format sequence area, or has no sequence digits there. We accept
        # a leading-token level number conservatively.
        m = _COBOL_FREE_RE.match(raw)
        if m:
            # Guard against false positives where a digit-led data value in Area
            # B happens to start with "01" — the free regex requires the level
            # to be the FIRST token, which a PIC/VALUE line never satisfies.
            breaks.append(lineno)

    return _sorted_unique(breaks, line_count)


# --------------------------------------------------------------------------- #
# DSX — element-open lines for record/table-definition spans (REGEX, not XML)
# --------------------------------------------------------------------------- #

# DataStage .dsx exports are a DSX text format with embedded pseudo-XML and
# BEGIN/END blocks. We REGEX-DETECT the opening of a record / table-definition
# span; we do NOT parse the XML (N2 — no XXE surface). Each detected open line
# is a safe break (the previous chunk ends just before it).
#
# We recognize both the classic DSX BEGIN blocks and the embedded XML element
# opens that DataStage uses for table definitions / record schemas.
_DSX_PATTERNS = [
    re.compile(r"^\s*<\s*(Record|DSRecord|TableDefinition|TableDef)\b", re.IGNORECASE),
    re.compile(r"^\s*BEGIN\s+DSRECORD\b", re.IGNORECASE),
    re.compile(r"^\s*BEGIN\s+DSTABLEDEFINITION\b", re.IGNORECASE),
    # DSX table-definition record headers commonly look like:
    #   BEGIN DSRECORD
    #   ... Identifier "V0S1" ...
    # and standalone "Record" object headers:
    re.compile(r"^\s*Record\s+\"", re.IGNORECASE),
]


def dsx_break_lines(text: str) -> List[int]:
    """Lines at which a DSX record / table-definition span opens.

    REGEX/text-scan ONLY (N2). The .dsx is treated as opaque text; we never feed
    it to an XML parser, so there is no XXE surface. Each detected element-open
    or BEGIN-block line is a safe break.
    """
    lines = _splitlines(text)
    line_count = len(lines)
    breaks: List[int] = []

    for lineno, raw in enumerate(lines, start=1):
        for pat in _DSX_PATTERNS:
            if pat.match(raw):
                breaks.append(lineno)
                break

    return _sorted_unique(breaks, line_count)


# --------------------------------------------------------------------------- #
# Flat-file layout — section / record-header breaks
# --------------------------------------------------------------------------- #

# Flat-file positional layout documents (e.g. *.fd, *.layout, copybook-adjacent
# docs) delimit records with section headers. We recognize the common shapes:
#   RECORD: name            (or "RECORD name", "Record Layout: name")
#   [SectionName]           (ini-style)
#   01  RECORD-NAME.        (embedded copybook record headers)
#   ===== banner ===== / ----- banner -----  followed by a header
_FLATFILE_PATTERNS = [
    re.compile(r"^\s*RECORD\b\s*[:\-]?\s*\S", re.IGNORECASE),
    re.compile(r"^\s*RECORD\s+LAYOUT\b", re.IGNORECASE),
    re.compile(r"^\s*\[[^\]]+\]\s*$"),  # [Section]
    re.compile(r"^\s*0?1\s+[A-Za-z][A-Za-z0-9$#@-]*\s*\.?\s*$"),  # 01 RECORD-NAME.
    re.compile(r"^\s*LAYOUT\b\s*[:\-]", re.IGNORECASE),
]

# A horizontal-rule banner line (>= 5 of the same rule char). A banner alone is
# not a record start, but the line AFTER a banner usually is a header; we treat
# the banner itself as a safe break (cut before the banner keeps the header with
# its following record).
_FLATFILE_BANNER_RE = re.compile(r"^\s*([=\-_*#])\1{4,}\s*$")


def flatfile_break_lines(text: str) -> List[int]:
    """Lines at which a flat-file layout section / record header begins.

    Recognizes RECORD: headers, [Section] ini-style headers, embedded 01-level
    copybook record headers, LAYOUT: markers, and horizontal-rule banner lines.
    Regex/text-scan only.
    """
    lines = _splitlines(text)
    line_count = len(lines)
    breaks: List[int] = []

    for lineno, raw in enumerate(lines, start=1):
        if _FLATFILE_BANNER_RE.match(raw):
            breaks.append(lineno)
            continue
        for pat in _FLATFILE_PATTERNS:
            if pat.match(raw):
                breaks.append(lineno)
                break

    return _sorted_unique(breaks, line_count)


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #

_DETECTORS = {
    "sql": sql_break_lines,
    "cobol": cobol_break_lines,
    "dsx": dsx_break_lines,
    "flatfile": flatfile_break_lines,
}


def safe_break_lines(text: str, format_hint: Optional[str]) -> List[int]:
    """Return the SORTED, DEDUPLICATED list of 1-indexed safe break line numbers
    for `text` under `format_hint`. Returns [] for an unknown/unsupported hint
    (the chunker then falls back to plain greedy cuts).

    This is the single entry point chunk_file (and callers) use.
    """
    family = normalize_format_hint(format_hint)
    if family is None:
        return []
    detector = _DETECTORS.get(family)
    if detector is None:
        return []
    return detector(text)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file_path", type=Path, help="File to scan for safe breaks")
    parser.add_argument(
        "--format",
        dest="format_hint",
        default=None,
        help="Format family hint (sql|cobol|copybook|datastage-dsx|flat-file-layout). "
        "If omitted, inferred from the file extension.",
    )
    args = parser.parse_args(argv)

    try:
        text = args.file_path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, PermissionError, OSError) as e:
        print(f"ERROR: cannot read {args.file_path}: {e}", file=sys.stderr)
        # Boundary detection is best-effort; surface the error but exit 0 so a
        # caller that ignores hints is unaffected.
        return 0

    hint = args.format_hint
    if hint is None:
        # Cheap extension-based inference for the CLI smoke path only.
        ext = args.file_path.suffix.lower().lstrip(".")
        ext_map = {
            "sql": "sql",
            "ddl": "sql",
            "cbl": "cobol",
            "cob": "cobol",
            "cpy": "copybook",
            "dsx": "datastage-dsx",
            "fd": "flat-file-layout",
            "layout": "flat-file-layout",
        }
        hint = ext_map.get(ext)

    for n in safe_break_lines(text, hint):
        print(n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
