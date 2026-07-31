#!/usr/bin/env python3
"""preprocess.py — the stdlib preprocessing core for ``mainframe-lineage-parsers``.

Part of the ``mainframe-lineage-parsers`` skill (the deterministic v1.1 plug-in
track under ``lineage-extract-static`` anti-pattern #7 — a *complement*, not a
replacement, of the LLM-as-parser family). This module is the FIRST stage of the
deterministic pipeline (design §3): it turns raw fixed-format COBOL source into a
clean program-area stream + a source-map that traces every clean line back to its
original ``(file, line)`` + the list of embedded ``EXEC SQL`` blocks with their
source spans, so the downstream extractors (``jcl_extract``, ``cobol_extract``,
``sql_extract``) keep full provenance.

It is **pure stdlib** — NO LLM, NO ``sqlglot``/``networkx``, NO new pip deps, NO
network, NO shell, NO runtime pip install (design D1). The deterministic engine
has no LLM in the loop, ever (C2). It is also **pure in-memory** by default: the
public entry points take source text (or read a file) and RETURN dataclasses; no
cache is written (the acceptance criterion prefers an in-memory return — the
atomic-write / 0700-dir idioms from the siblings are reused only if a caller
later opts a cache in, which v1 does not).

The language here is model-neutral. The deterministic engine runs the same way
regardless of which CLI host invokes it (Claude Code, Codex CLI, Copilot CLI,
Antigravity CLI).

------------------------------------------------------------------------------
Fixed-format column model (research §5 + design §3 + naming-contract §6)
------------------------------------------------------------------------------
A fixed-format COBOL line (IBM Enterprise COBOL baseline) is laid out as
1-indexed columns:

    cols  1-6   sequence-number area   -> dropped
    col   7     indicator area         -> '*' or '/' = comment, '-' = continuation,
                                          'D'/'d' = debugging line, ' ' = normal
    cols  8-72  program area           -> the code (Area A cols 8-11, Area B 12-72)
    cols 73-80  identification area     -> ignored

In 0-indexed Python slicing that is::

    seq        = line[0:6]
    indicator  = line[6]          (line[6:7] — safe on short lines)
    program    = line[7:72]       (cols 8-72)
    ignored    = line[72:80]      (cols 73-80; and anything past 80)

Research §5's reference used ``content_area = line[6:72]`` (indicator + program in
one slice, then it inspected ``content_area[0]`` for the comment marker). This
module keeps the indicator and program area as DISTINCT fields so the indicator
semantics (comment / continuation / debug) are explicit and testable, and the
program area is exactly cols 8-72. The clean program text this module returns is
the program area only.

------------------------------------------------------------------------------
Source-format detection (v1 is FIXED-only)
------------------------------------------------------------------------------
A ``>>SOURCE FORMAT FREE`` / ``>>SET SOURCEFORMAT"FREE"`` directive (in any case)
selects free-format, which v1 does NOT support. Rather than silently
best-effort-parsing free-format as if it were fixed (which would corrupt every
column offset), this module emits a typed ``free_format_unsupported`` gap and a
diagnostic, and does NOT attempt a fixed-format strip on the free-format body.
This is the same gap the LLM tool surfaces, named identically (naming-contract
§5). ``>>SOURCE FORMAT FIXED`` (the default) proceeds normally.

------------------------------------------------------------------------------
Continuation handling
------------------------------------------------------------------------------
A line whose indicator (col 7) is ``-`` continues the previous logical line. The
program-area text of the continuation joins onto the logical line being built.
Non-literal continuation simply concatenates the (left-stripped) continuation
program text onto the running logical line. Literal continuation (a continuation
of an unterminated quoted literal) must NOT inject a spurious token boundary: the
program text after the literal's leading quote is appended directly to the open
literal so the literal's bytes are preserved without a stray space. This
conservative join keeps tokens intact (the acceptance criterion: "literal
continuation does not corrupt tokens").

Every clean logical line records the ORIGINAL ``(file, line)`` of its FIRST
physical line in the source-map; continuation lines fold into that logical line.

------------------------------------------------------------------------------
EXEC SQL block extraction
------------------------------------------------------------------------------
A line-state machine scans the clean logical lines for ``EXEC SQL`` ... ``END-EXEC``
(case-insensitive, multi-line). The text BETWEEN the markers is collected as one
SQL block, with a source span = the original ``(file, start_line, end_line)`` of
the EXEC...END-EXEC region, so ``sql_extract`` (WP-7) can map a finding back to
the exact source location. The ``EXEC SQL`` and ``END-EXEC`` marker tokens are
NOT part of the emitted SQL text (only the statement body is handed to the SQL
extractor). The EXEC SQL region is also removed from the clean COBOL stream that
``cobol_extract`` (WP-6) consumes, so the COBOL extractor never trips over the
embedded SQL (design §3 / research §5: extracting the SQL out is easier and
cleaner than making a COBOL parser swallow it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# ------------------------------------------------------------------------------
# Fixed-format column constants (1-indexed cols -> 0-indexed slices)
# ------------------------------------------------------------------------------
SEQ_AREA = slice(0, 6)          # cols 1-6  sequence-number area (dropped)
INDICATOR_COL = 6               # col 7     indicator area
PROGRAM_AREA = slice(7, 72)     # cols 8-72 program area (the code)
# cols 73-80 (line[72:80]) are the identification area, ignored.

# Indicator-area semantics (col 7).
COMMENT_INDICATORS = ("*", "/")
CONTINUATION_INDICATOR = "-"
DEBUG_INDICATORS = ("D", "d")

# The frozen gap-type name for free-format source (naming-contract §5).
GAP_FREE_FORMAT_UNSUPPORTED = "free_format_unsupported"

# Source-format directive detection. Matches, case-insensitively:
#   >>SOURCE FORMAT FREE        (Enterprise COBOL)
#   >>SET SOURCEFORMAT"FREE"    (older / GnuCOBOL style)
#   >>SOURCE FORMAT IS FREE
# and the FIXED equivalents. Anywhere on the line (these directives are not
# constrained to the program area in practice; legacy estates put them in col 8+).
_SOURCE_FORMAT_RE = re.compile(
    r""">>\s*                                  # the >> directive lead-in
        (?:SET\s+SOURCEFORMAT|SOURCE\s+FORMAT)  # either spelling
        \s*(?:IS\s+)?                           # optional IS
        ["']?\s*                                # optional opening quote
        (FREE|FIXED)                            # the captured mode
        \s*["']?                                # optional closing quote
    """,
    re.IGNORECASE | re.VERBOSE,
)

# EXEC SQL / END-EXEC markers (case-insensitive, whitespace-flexible). These are
# matched against the CLEAN program text of a logical line.
_EXEC_SQL_RE = re.compile(r"\bEXEC\s+SQL\b", re.IGNORECASE)
_END_EXEC_RE = re.compile(r"\bEND-EXEC\b", re.IGNORECASE)


# ------------------------------------------------------------------------------
# Result dataclasses (the pure in-memory return shapes)
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class SourceRef:
    """An original source location: a file path + a 1-indexed physical line."""

    file: str
    line: int  # 1-indexed


@dataclass
class CleanLine:
    """One clean LOGICAL line of the program area.

    ``text`` is the program-area code (cols 8-72), with any continuation lines
    already folded in. ``origin`` is the original ``(file, line)`` of the FIRST
    physical line of this logical line. ``physical_lines`` is the full list of
    1-indexed original physical line numbers that fold into this logical line
    (the first plus any continuations), in order.
    """

    text: str
    origin: SourceRef
    physical_lines: List[int] = field(default_factory=list)


@dataclass
class SqlBlock:
    """One extracted ``EXEC SQL ... END-EXEC`` block.

    ``text`` is the SQL statement body BETWEEN the markers (markers excluded),
    joined with single spaces. ``span`` records the original ``(file, start, end)``
    physical line range of the whole ``EXEC SQL ... END-EXEC`` region so the SQL
    extractor (WP-7) keeps provenance back to the source.
    """

    text: str
    file: str
    start_line: int  # 1-indexed original line of the `EXEC SQL` marker
    end_line: int    # 1-indexed original line of the `END-EXEC` marker


@dataclass
class Gap:
    """A typed preprocessing gap (naming-contract §5).

    A gap is emitted in place of an honest result that cannot be produced — e.g.
    free-format source, which v1 does not support. ``detail`` is a human-readable
    diagnostic; ``ref`` is where it was detected. Gaps are NEVER silently swallowed
    and NEVER replaced by a best-effort guess (C2/C3).
    """

    type: str
    detail: str
    ref: Optional[SourceRef] = None


@dataclass
class PreprocessResult:
    """The full pure-in-memory return of :func:`preprocess_source`.

    * ``clean_lines`` — the clean logical lines of the program area with the
      EXEC SQL regions REMOVED (so the COBOL extractor never sees embedded SQL).
    * ``sql_blocks`` — the extracted EXEC SQL blocks with their source spans.
    * ``gaps`` — typed diagnostics (e.g. ``free_format_unsupported``).
    * ``source_format`` — the detected format ("fixed" or "free").
    * ``file`` — the source file label (for provenance).
    """

    clean_lines: List[CleanLine] = field(default_factory=list)
    sql_blocks: List[SqlBlock] = field(default_factory=list)
    gaps: List[Gap] = field(default_factory=list)
    source_format: str = "fixed"
    file: str = "<memory>"

    # --- convenience: the clean COBOL program text (EXEC SQL removed) ----------
    def clean_text(self) -> str:
        """The clean program-area text as a newline-joined string."""
        return "\n".join(cl.text for cl in self.clean_lines)

    # --- the source-map round-trip (acceptance criterion) ---------------------
    def origin_of(self, clean_index: int) -> SourceRef:
        """Map a 0-indexed clean-line index back to its original ``(file, line)``.

        This is the source-map round-trip the acceptance criterion requires: a
        clean line index resolves to the correct original physical location.
        Raises ``IndexError`` for an out-of-range index (deterministic, no
        silent clamp).
        """
        return self.clean_lines[clean_index].origin


# ------------------------------------------------------------------------------
# Source-format detection
# ------------------------------------------------------------------------------
def detect_source_format(text: str) -> str:
    """Return the source format declared by a ``>>SOURCE FORMAT`` directive.

    Returns ``"free"`` or ``"fixed"``. The LAST directive wins (Enterprise COBOL
    allows the format to switch mid-source; v1 only needs the prevailing one to
    decide fixed-vs-free, and a free anywhere means we cannot do a fixed strip).
    The default when no directive is present is ``"fixed"`` (the legacy estate
    default — research §5).
    """
    result = "fixed"
    for line in text.splitlines():
        m = _SOURCE_FORMAT_RE.search(line)
        if m:
            result = m.group(1).lower()
    return result


# ------------------------------------------------------------------------------
# Fixed-format physical-line decomposition
# ------------------------------------------------------------------------------
@dataclass
class _PhysicalLine:
    """Internal: a decomposed physical fixed-format line."""

    lineno: int            # 1-indexed
    indicator: str         # col 7 (or "" for a too-short line)
    program: str           # cols 8-72, right-stripped
    is_comment: bool
    is_continuation: bool
    is_debug: bool


def _decompose_fixed_line(line: str, lineno: int) -> _PhysicalLine:
    """Decompose ONE physical fixed-format line into its areas.

    Tabs are expanded first (a tab in the sequence area would otherwise shift the
    column positions). Cols 1-6 (sequence) are dropped, col 7 is the indicator,
    cols 8-72 are the program area, cols 73-80 are ignored. The program area is
    right-stripped (trailing blanks in the fixed field carry no meaning) but NOT
    left-stripped (Area A vs Area B indentation can matter to downstream parsers).
    """
    # Expand tabs to keep column math correct on tab-indented sources.
    expanded = line.expandtabs()
    indicator = expanded[INDICATOR_COL] if len(expanded) > INDICATOR_COL else ""
    program = expanded[PROGRAM_AREA].rstrip()
    is_comment = indicator in COMMENT_INDICATORS
    is_continuation = indicator == CONTINUATION_INDICATOR
    is_debug = indicator in DEBUG_INDICATORS
    return _PhysicalLine(
        lineno=lineno,
        indicator=indicator,
        program=program,
        is_comment=is_comment,
        is_continuation=is_continuation,
        is_debug=is_debug,
    )


def _join_continuation(running: str, continuation_program: str) -> str:
    """Join a continuation line's program text onto the running logical line.

    Conservative token-preserving join:

    * If the running logical line ends inside an UNTERMINATED quoted literal, the
      continuation's program text (after its own leading quote, if any) is
      appended DIRECTLY (no separating space) so the literal's bytes are
      preserved without a spurious token boundary (literal continuation rule).
    * Otherwise the continuation's left-stripped program text is appended with a
      single separating space, so two code tokens split across a continuation do
      not silently fuse into one (e.g. ``ASSIGN TO PAY`` + ``-MASTER`` would be
      wrong to fuse; COBOL non-literal continuation conventionally has Area B
      code that reads as separate tokens). A single space is the safe,
      deterministic choice that keeps tokens intact for the regex/word-boundary
      based extractors.
    """
    if _ends_in_open_literal(running):
        # Literal continuation: the continuation line's first non-blank char is
        # the continuation quote; drop one leading quote if present, then append
        # directly so the literal body is preserved with no injected space.
        cont = continuation_program.lstrip()
        if cont[:1] in ("'", '"'):
            cont = cont[1:]
        return running + cont
    cont = continuation_program.strip()
    if not cont:
        return running
    if not running:
        return cont
    return running + " " + cont


def _ends_in_open_literal(text: str) -> bool:
    """True if ``text`` ends inside an unterminated single/double-quoted literal.

    A simple deterministic scan: count quote toggles, honouring COBOL's doubled
    quote escape (``''`` inside a ``'``-literal is an escaped quote, not a
    terminator). Returns True iff a literal is still open at end of text.
    """
    quote: Optional[str] = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if quote is None:
            if ch in ("'", '"'):
                quote = ch
        else:
            if ch == quote:
                # Doubled quote == escaped quote inside the literal.
                if i + 1 < n and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        i += 1
    return quote is not None


# ------------------------------------------------------------------------------
# Logical-line folding (apply continuations)
# ------------------------------------------------------------------------------
def _fold_logical_lines(
    physicals: List[_PhysicalLine], file_label: str
) -> List[CleanLine]:
    """Fold physical program lines into clean LOGICAL lines.

    Comment lines and debug lines are dropped (debug lines are only active under
    ``WITH DEBUGGING MODE``, which v1 does not honour — they are not part of the
    lineage-bearing program text). Continuation lines fold into the preceding
    logical line. Blank program areas are skipped (they carry no code).
    """
    logical: List[CleanLine] = []
    for ph in physicals:
        if ph.is_comment or ph.is_debug:
            continue
        if ph.is_continuation and logical:
            current = logical[-1]
            current.text = _join_continuation(current.text, ph.program)
            current.physical_lines.append(ph.lineno)
            continue
        program = ph.program.rstrip()
        if not program.strip():
            # Blank line — no code; skip (keeps the clean stream tight and the
            # source-map meaningful: every clean line has real content).
            continue
        logical.append(
            CleanLine(
                text=program,
                origin=SourceRef(file=file_label, line=ph.lineno),
                physical_lines=[ph.lineno],
            )
        )
    return logical


# ------------------------------------------------------------------------------
# EXEC SQL block extraction
# ------------------------------------------------------------------------------
def _extract_sql_blocks(
    logical: List[CleanLine], file_label: str
) -> Tuple[List[CleanLine], List[SqlBlock]]:
    """Split EXEC SQL ... END-EXEC blocks out of the clean logical lines.

    Returns ``(cobol_lines, sql_blocks)`` where ``cobol_lines`` is the clean
    stream with the EXEC SQL regions removed, and ``sql_blocks`` carries each
    extracted SQL body with its original source span. The markers themselves are
    excluded from the SQL body.

    The state machine is line-oriented but tolerant of single-line blocks
    (``EXEC SQL ... END-EXEC`` on one logical line) and of an ``EXEC SQL`` marker
    that shares its line with the start of the SQL body.
    """
    cobol_lines: List[CleanLine] = []
    sql_blocks: List[SqlBlock] = []

    in_sql = False
    sql_parts: List[str] = []
    sql_start_line = 0

    for cl in logical:
        if not in_sql:
            m = _EXEC_SQL_RE.search(cl.text)
            if not m:
                cobol_lines.append(cl)
                continue
            # Enter SQL mode. Capture the text AFTER the `EXEC SQL` marker on
            # this same line (may already contain the start of the statement,
            # and possibly an END-EXEC on the same line for a single-line block).
            in_sql = True
            sql_parts = []
            sql_start_line = cl.origin.line
            after_marker = cl.text[m.end():]
            end_m = _END_EXEC_RE.search(after_marker)
            if end_m:
                # Single-line EXEC SQL ... END-EXEC.
                body = after_marker[: end_m.start()]
                sql_blocks.append(
                    _make_sql_block(
                        [body], file_label, sql_start_line, cl.origin.line
                    )
                )
                in_sql = False
                continue
            if after_marker.strip():
                sql_parts.append(after_marker)
            continue

        # Already inside an SQL block — look for END-EXEC on this line.
        end_m = _END_EXEC_RE.search(cl.text)
        if end_m:
            before = cl.text[: end_m.start()]
            if before.strip():
                sql_parts.append(before)
            sql_blocks.append(
                _make_sql_block(
                    sql_parts, file_label, sql_start_line, cl.origin.line
                )
            )
            in_sql = False
            sql_parts = []
            continue
        sql_parts.append(cl.text)

    # An unterminated EXEC SQL (no END-EXEC) still yields a block with what we
    # have, spanning to the last line seen — never silently drop the SQL.
    if in_sql and sql_parts:
        last_line = logical[-1].origin.line if logical else sql_start_line
        sql_blocks.append(
            _make_sql_block(sql_parts, file_label, sql_start_line, last_line)
        )

    return cobol_lines, sql_blocks


def _make_sql_block(
    parts: List[str], file_label: str, start_line: int, end_line: int
) -> SqlBlock:
    """Build a :class:`SqlBlock` from the collected body parts."""
    body = " ".join(p.strip() for p in parts if p.strip())
    return SqlBlock(
        text=body,
        file=file_label,
        start_line=start_line,
        end_line=end_line,
    )


# ------------------------------------------------------------------------------
# Public entry points
# ------------------------------------------------------------------------------
def preprocess_source(text: str, file_label: str = "<memory>") -> PreprocessResult:
    """Preprocess fixed-format COBOL source text (pure, in-memory).

    Pipeline (design §3 / research §5):

    1. Detect the source format. FREE -> emit a ``free_format_unsupported`` gap +
       diagnostic and return WITHOUT a fixed-format strip (no best-effort).
    2. Fixed-format column decomposition (seq 1-6 dropped, indicator col 7,
       program area 8-72, 73-80 ignored).
    3. Fold continuation lines into logical lines; drop comment/debug/blank lines.
    4. Extract EXEC SQL ... END-EXEC blocks out of the clean stream with spans.

    Returns a :class:`PreprocessResult` with the clean COBOL logical lines (SQL
    removed), the SQL blocks, any gaps, the detected format, and the file label.
    The source-map round-trip is :meth:`PreprocessResult.origin_of`.
    """
    fmt = detect_source_format(text)
    if fmt == "free":
        # v1 does not support free-format; emit the typed gap + diagnostic and
        # do NOT attempt a fixed-format strip (which would corrupt every column).
        return PreprocessResult(
            clean_lines=[],
            sql_blocks=[],
            gaps=[
                Gap(
                    type=GAP_FREE_FORMAT_UNSUPPORTED,
                    detail=(
                        "source declares >>SOURCE FORMAT FREE; v1 supports "
                        "fixed-format only. Use the LLM-as-parser flow "
                        "(lineage-extract-static) for free-format COBOL."
                    ),
                    ref=SourceRef(file=file_label, line=1),
                )
            ],
            source_format="free",
            file=file_label,
        )

    # Fixed-format path.
    physicals = [
        _decompose_fixed_line(line, i)
        for i, line in enumerate(text.splitlines(), start=1)
    ]
    logical = _fold_logical_lines(physicals, file_label)
    cobol_lines, sql_blocks = _extract_sql_blocks(logical, file_label)

    return PreprocessResult(
        clean_lines=cobol_lines,
        sql_blocks=sql_blocks,
        gaps=[],
        source_format="fixed",
        file=file_label,
    )


def preprocess_file(path) -> PreprocessResult:
    """Read a COBOL source file and preprocess it.

    Reads the file as UTF-8 (errors replaced — legacy EBCDIC-transcoded sources
    occasionally carry stray bytes; the deterministic engine must not crash on
    them) and delegates to :func:`preprocess_source` with the path as the file
    label so the source-map carries the real filename.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    return preprocess_source(text, file_label=str(p))


__all__ = [
    "SourceRef",
    "CleanLine",
    "SqlBlock",
    "Gap",
    "PreprocessResult",
    "detect_source_format",
    "preprocess_source",
    "preprocess_file",
    "GAP_FREE_FORMAT_UNSUPPORTED",
]
