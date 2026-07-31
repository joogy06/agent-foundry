#!/usr/bin/env python3
"""copybook_resolver.py — COPY ... REPLACING expansion for ``mainframe-lineage-parsers``.

Part of the ``mainframe-lineage-parsers`` skill (the deterministic v1.1 plug-in
track under ``lineage-extract-static`` anti-pattern #7 — a *complement*, not a
replacement, of the LLM-as-parser family). This module is the SECOND deterministic
stage (design §3 / §7 layout): after :mod:`preprocess` has produced a clean
fixed-format program stream, this resolver expands every ``COPY member`` directive
inline — resolving the member across configured search paths, applying token-aware
``REPLACING`` substitution, following the include graph with **cycle detection and
a depth cap**, and keeping a full **source-span + expansion-stack** map so every
expanded line traces back to ``(copybook-file:line)`` AND the stack of COPY sites
that pulled it in (the copybook-expansion stack that becomes a provenance facet on
every downstream edge — design §7 "provenance everywhere").

It is **pure stdlib** — NO LLM, NO ``sqlglot``/``networkx``, NO new pip deps, NO
network, NO shell, NO runtime pip install (design D1). The deterministic engine
has no LLM in the loop, ever (C2). It is **deterministic**: the same inputs (same
source + same search paths) produce the same expanded stream + the same gap list,
byte-for-byte, on re-run.

The language here is model-neutral. The deterministic engine runs the same way
regardless of which CLI host invokes it (Claude Code, Codex CLI, Copilot CLI,
Antigravity CLI).

------------------------------------------------------------------------------
CRITICAL CONTRACT (C3 — naming-contract §5): unresolved COPY -> gap, NEVER a guess
------------------------------------------------------------------------------
When a ``COPY member`` cannot be found on ANY configured ``--copybook-path`` search
directory, this module emits an explicit ``unresolved_copy`` gap node (the frozen
gap name from naming-contract §5, confidence ``speculative``) and keeps the raw
member token as a ``raw_copy_member`` facet. It NEVER invents the copybook's
content and NEVER fabricates an edge from a missing member. Whether an unresolved
COPY is a *gap* (default) or a *hard failure* is selected by
``--copybook-missing`` (``gap`` [default] | ``fail``); ``fail`` makes the CLI exit
non-zero.

------------------------------------------------------------------------------
COPY syntax handled (IBM Enterprise COBOL baseline)
------------------------------------------------------------------------------
The directive forms recognised on a clean (already col-8-72-stripped) logical
line::

    COPY member.
    COPY member OF library.
    COPY member IN library.
    COPY "member".
    COPY member REPLACING ==pseudo-a== BY ==pseudo-b== ==c== BY ==d==.
    COPY member REPLACING identifier-a BY identifier-b.

* ``member`` may be unquoted (an ordinary COBOL word) or a quoted literal. The
  optional ``OF``/``IN`` library qualifier is recognised and recorded but does NOT
  change the on-disk lookup in v1 (libraries map to the same search-path set; a
  library-qualified lookup that fails is still an ``unresolved_copy`` gap — never a
  guess).
* The directive is terminated by the ``.`` separator period; a ``COPY`` may span
  multiple logical lines until that period (REPLACING lists are commonly wrapped).
  This resolver folds the COPY statement up to its terminating period before
  parsing it.
* ``REPLACING`` operands come in two forms, BOTH token-aware:
  - **pseudo-text** ``==text==`` — the text BETWEEN the ``==`` delimiters is
    matched as a contiguous run of source characters at token boundaries (a
    pseudo-text operand can be a partial word like ``==PREFIX==`` and is matched
    on word boundaries so it does NOT corrupt an unrelated identifier that merely
    contains the same characters).
  - **identifier / word** form — a bare COBOL word matched as a WHOLE word only
    (word-boundary anchored), so ``COPY x REPLACING A BY B`` rewrites the word
    ``A`` but never the ``A`` inside ``PAYABLE``.

The substitution is applied LEFT-TO-RIGHT over the copybook's expanded text, and
nested COPYs inside a copybook inherit the active REPLACING set of their including
site is NOT done in v1 (Enterprise COBOL applies the *innermost* REPLACING; v1
applies each COPY's own REPLACING to its own body only — documented limitation,
deterministic, never silently wrong: a nested COPY's body is expanded with its own
(possibly empty) REPLACING, and the parent REPLACING is applied to the parent's
own directly-copied text only). This is conservative and avoids corrupting tokens.

------------------------------------------------------------------------------
Cycle / depth caps (no hang — gap instead)
------------------------------------------------------------------------------
The include graph is walked depth-first. A copybook that (directly or transitively)
COPYs itself is a CYCLE: the cyclic re-entry is refused and a ``copy_cycle`` gap is
emitted at the offending COPY site (the engine NEVER hangs). A configurable depth
cap (``max_depth``, default :data:`DEFAULT_MAX_DEPTH`) bounds the nesting; a COPY
that would exceed the cap is refused with a ``copy_depth_exceeded`` gap. Both are
honest gaps — the partial expansion up to the cap/cycle is kept; the refused branch
becomes a gap, never an invented body.

Note on the frozen gap set: naming-contract §5 freezes ``unresolved_copy`` as the
v1 *contract* gap for the OpenLineage output. ``copy_cycle`` and
``copy_depth_exceeded`` are **internal resolver diagnostics** (they describe a
*structural* refusal to expand, not a missing-member naming question) carried on
the :class:`ResolveResult` for the caller's logs; they are NOT emitted as
OpenLineage contract gap nodes (that closed set stays frozen). The downstream IR
(WP-4) maps only ``unresolved_copy`` to a contract gap node; cycle/depth refusals
surface as resolver diagnostics + an ``unresolved`` provenance note. This keeps
the frozen contract closed while still never hanging and never inventing.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# ------------------------------------------------------------------------------
# Frozen gap-type names
# ------------------------------------------------------------------------------
# The contract gap (naming-contract §5) — emitted to the OpenLineage output via
# the IR. Confidence is forced to "speculative" downstream.
GAP_UNRESOLVED_COPY = "unresolved_copy"

# Internal resolver diagnostics (NOT OpenLineage contract gap nodes — see module
# docstring). They describe a structural refusal to expand, never a guess.
DIAG_COPY_CYCLE = "copy_cycle"
DIAG_COPY_DEPTH_EXCEEDED = "copy_depth_exceeded"

# Default nesting cap. Real COBOL copybook nesting is shallow; this is generous
# while still refusing pathological / cyclic includes long before any hang.
DEFAULT_MAX_DEPTH = 50

# ------------------------------------------------------------------------------
# COPY directive recognition (operates on clean, col-stripped logical text)
# ------------------------------------------------------------------------------
# A clean logical line that STARTS a COPY statement. We capture the member token
# (quoted or bare word) and an optional OF/IN library qualifier. The full COPY
# statement (which may span lines and carry a REPLACING list) is then folded up to
# its terminating period before being parsed in full by ``_parse_copy_statement``.
_COPY_START_RE = re.compile(
    r"""^\s*COPY\b""",
    re.IGNORECASE | re.VERBOSE,
)

# Full COPY statement parse (applied to the period-terminated, single-spaced
# folded statement). Groups: member (quoted or bare), optional library.
_COPY_FULL_RE = re.compile(
    r"""^\s*COPY\s+
        (?P<member>"[^"]+"|'[^']+'|[A-Za-z0-9$#@_-]+)   # member: quoted or COBOL word
        (?:\s+(?:OF|IN)\s+
            (?P<library>"[^"]+"|'[^']+'|[A-Za-z0-9$#@_-]+))?  # optional OF/IN lib
        (?:\s+REPLACING\s+(?P<replacing>.*?))?           # optional REPLACING list
        \s*\.\s*$                                         # terminating period
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


# ------------------------------------------------------------------------------
# Result dataclasses
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class ExpansionFrame:
    """One frame on the copybook-expansion stack.

    ``file`` is the copybook (or root source) file the COPY site lives in; ``line``
    is the 1-indexed line of the COPY directive within that file; ``member`` is the
    copybook member name being expanded by that COPY. The stack of frames on an
    expanded line is the provenance trail "this line came from member X, pulled in
    by a COPY at file:line, which itself was pulled in by ...".
    """

    file: str
    line: int  # 1-indexed COPY-site line within ``file``
    member: str


@dataclass
class ExpandedLine:
    """One line of fully-expanded program text.

    * ``text`` — the program text of this line AFTER REPLACING substitution.
    * ``origin_file`` / ``origin_line`` — the ORIGINAL ``(copybook-file, line)``
      this line's text came from (the root source file for non-copied lines, or
      the copybook file for copied lines).
    * ``expansion_stack`` — the COPY-site stack that pulled this line in, OUTERMOST
      first. Empty for lines that live directly in the root source (not inside any
      COPY). This is the provenance facet the downstream edges carry.
    """

    text: str
    origin_file: str
    origin_line: int  # 1-indexed
    expansion_stack: Tuple[ExpansionFrame, ...] = ()


@dataclass
class Gap:
    """A typed resolver gap / diagnostic.

    ``type`` is one of :data:`GAP_UNRESOLVED_COPY` (the frozen contract gap),
    :data:`DIAG_COPY_CYCLE`, or :data:`DIAG_COPY_DEPTH_EXCEEDED`. ``raw_copy_member``
    keeps the raw member token so the user can see exactly what was unresolved
    (naming-contract §5 "a gap node keeps the raw evidence as a facet"). ``file`` /
    ``line`` locate the COPY site that produced the gap. ``expansion_stack`` is the
    stack at the point the gap was raised (so a deep unresolved COPY is traceable).
    """

    type: str
    raw_copy_member: str
    file: str
    line: int  # 1-indexed COPY-site line
    detail: str = ""
    expansion_stack: Tuple[ExpansionFrame, ...] = ()
    # The contract confidence for an unresolved_copy gap (speculative; §5).
    confidence: str = "speculative"


@dataclass
class ResolveResult:
    """The full result of resolving a source's COPYs.

    * ``lines`` — the fully-expanded program lines (root + copied), in order, each
      with its source-span + expansion-stack provenance.
    * ``gaps`` — typed gaps/diagnostics (unresolved COPY, cycle, depth-exceeded).
    * ``resolved_members`` — the set of member names successfully resolved (for
      the include-graph / dedupe diagnostics), as a sorted list.
    """

    lines: List[ExpandedLine] = field(default_factory=list)
    gaps: List[Gap] = field(default_factory=list)
    resolved_members: List[str] = field(default_factory=list)

    def text(self) -> str:
        """The fully-expanded program text as a newline-joined string."""
        return "\n".join(ln.text for ln in self.lines)

    def has_unresolved_copy(self) -> bool:
        """True iff any ``unresolved_copy`` contract gap was emitted."""
        return any(g.type == GAP_UNRESOLVED_COPY for g in self.gaps)


# ------------------------------------------------------------------------------
# REPLACING operand parsing + token-aware substitution
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class _Replacement:
    """One REPLACING pair compiled to a token-aware regex + replacement text."""

    pattern: "re.Pattern[str]"
    replacement: str
    raw_from: str
    raw_to: str


# A pseudo-text operand: ==text==. The text between the == delimiters is captured.
_PSEUDO_RE = re.compile(r"==(.*?)==", re.DOTALL)


def _strip_quotes(token: str) -> str:
    """Strip a single pair of matching surrounding quotes from a member token."""
    if len(token) >= 2 and token[0] in ("'", '"') and token[-1] == token[0]:
        return token[1:-1]
    return token


def _parse_replacing(replacing_text: str) -> List[_Replacement]:
    """Parse a ``REPLACING a BY b c BY d ...`` operand list into token-aware pairs.

    Both operand forms are handled:

    * pseudo-text ``==from== BY ==to==`` — the ``from`` text is matched as a
      contiguous run on WORD BOUNDARIES so a partial-word pseudo operand does not
      corrupt an unrelated identifier that merely contains the same characters.
    * identifier / word ``FROM BY TO`` — a bare COBOL word matched as a WHOLE word
      only (``\\b`` anchored).

    The list is split on the ``BY`` keyword (case-insensitive) between operands.
    Determinism: pairs are compiled in source order and applied in that order.
    """
    pairs: List[_Replacement] = []
    if not replacing_text:
        return pairs

    # Tokenise the REPLACING list into a flat operand stream, where each operand is
    # either a pseudo-text run ==...== or a bare word, separated by the BY keyword.
    operands = _tokenise_replacing(replacing_text)

    # Walk operands as (from, BY, to) triples.
    i = 0
    while i + 2 < len(operands) + 1:
        # We need from, BY, to. Defensive: stop if we run out.
        if i + 2 >= len(operands):
            break
        op_from = operands[i]
        by_kw = operands[i + 1]
        op_to = operands[i + 2]
        if by_kw.kind != "by":
            # Malformed/unsupported operand stream — stop deterministically rather
            # than guess. The remaining text is left unsubstituted (conservative).
            break
        repl = _compile_replacement(op_from, op_to)
        if repl is not None:
            pairs.append(repl)
        i += 3
    return pairs


@dataclass(frozen=True)
class _Operand:
    kind: str  # "pseudo" | "word" | "by"
    value: str  # pseudo body, the word, or "BY"


def _tokenise_replacing(text: str) -> List[_Operand]:
    """Tokenise a REPLACING operand list into pseudo / word / BY operands.

    Pseudo-text ``==...==`` runs are captured whole (including empty ``====``).
    Outside pseudo-text, the ``BY`` keyword (case-insensitive, whole word) is a
    separator operand; every other whitespace-separated COBOL word is a word
    operand. A trailing period (if any) has already been stripped by the COPY
    statement parser.
    """
    operands: List[_Operand] = []
    pos = 0
    n = len(text)
    word_re = re.compile(r"[A-Za-z0-9$#@_-]+")
    while pos < n:
        ch = text[pos]
        if ch.isspace():
            pos += 1
            continue
        if text.startswith("==", pos):
            m = _PSEUDO_RE.match(text, pos)
            if m:
                operands.append(_Operand(kind="pseudo", value=m.group(1)))
                pos = m.end()
                continue
            # An unterminated ==; consume the marker to avoid an infinite loop.
            pos += 2
            continue
        wm = word_re.match(text, pos)
        if wm:
            w = wm.group(0)
            if w.upper() == "BY":
                operands.append(_Operand(kind="by", value="BY"))
            else:
                operands.append(_Operand(kind="word", value=w))
            pos = wm.end()
            continue
        # Any other char (e.g. a stray separator) — skip it deterministically.
        pos += 1
    return operands


def _compile_replacement(op_from: _Operand, op_to: _Operand) -> Optional[_Replacement]:
    """Compile one (from, to) operand pair into a token-aware substitution.

    Both forms are token-aware so a partial-token near-match is NEVER corrupted
    (the acceptance criterion), but they anchor on DIFFERENT boundaries — matching
    Enterprise COBOL's distinct pseudo-text vs identifier ``REPLACING`` semantics:

    * **identifier / word form** (``REPLACING A BY ZZ``) — the operand is a whole
      COBOL WORD; the hyphen ``-`` is part of a COBOL word, so the boundary class
      INCLUDES ``-`` (``[A-Za-z0-9$#@_-]``). Thus ``A`` does not match inside
      ``A-TOTAL`` (one atomic COBOL word) nor inside ``PAYABLE``. Only the
      standalone word ``A`` is rewritten.

    * **pseudo-text form** (``REPLACING ==PREFIX== BY ==WS==``) — pseudo-text
      replaces a contiguous *partial-word* run delimited by COBOL separators, and
      the hyphen IS a separator in that context. So the boundary class EXCLUDES
      ``-`` (``[A-Za-z0-9_]`` only): ``==PREFIX==`` rewrites the ``PREFIX`` in
      ``PREFIX-ID`` (followed by ``-``, a separator) and in ``WS-PREFIX``
      (preceded by ``-``), but NOT the ``PREFIX`` inside ``PREFIXED`` (followed by
      a letter, NOT a separator). This is exactly the partial-token discipline the
      acceptance criterion pins.

    * For a pseudo-text ``from`` whose body is empty, no substitution is produced
      (an ``==== BY x`` operand is a no-op insert that v1 does not perform).
    """
    from_body = op_from.value
    to_body = op_to.value
    if op_from.kind == "by" or op_to.kind == "by":
        return None
    if from_body == "":
        return None
    # Boundary class differs by operand form (see docstring). Identifier form
    # treats COBOL words (incl. '-') as atomic; pseudo-text treats '-' as a
    # separator so partial-word prefixes/suffixes are matchable.
    if op_from.kind == "word":
        wc = r"[A-Za-z0-9$#@_-]"
    else:  # pseudo
        wc = r"[A-Za-z0-9_]"
    pattern = re.compile(
        r"(?<!" + wc + r")" + re.escape(from_body) + r"(?!" + wc + r")"
    )
    return _Replacement(
        pattern=pattern,
        replacement=to_body,
        raw_from=from_body,
        raw_to=to_body,
    )


def _apply_replacements(text: str, replacements: Sequence[_Replacement]) -> str:
    """Apply REPLACING pairs to one line of copybook text, left-to-right.

    Each pair is applied with :func:`re.sub` using a function replacement so the
    ``to`` body is inserted LITERALLY (no backslash/group interpretation of the
    replacement text). Determinism: pairs are applied in their source order.
    """
    out = text
    for r in replacements:
        out = r.pattern.sub(lambda _m, _t=r.replacement: _t, out)
    return out


# ------------------------------------------------------------------------------
# Member resolution across the search path
# ------------------------------------------------------------------------------
# Conventional copybook extensions tried (in this deterministic order) when the
# member token has no extension of its own. Bare (no-extension) is tried first so
# an exact filename match wins.
_COPYBOOK_EXTENSIONS = ("", ".cpy", ".CPY", ".cbl", ".CBL", ".cob", ".COB", ".copy")


def resolve_member_path(
    member: str, search_paths: Sequence[Path]
) -> Optional[Path]:
    """Resolve a COPY member name to a file on the search path (deterministic).

    The search is: for each search dir in the GIVEN order, try the member token
    verbatim, then with each conventional extension, then a case-insensitive
    directory match (mainframe member names are case-insensitive; on-disk PDS
    exports vary in case). The FIRST match in search-path order wins (deterministic
    precedence — earlier ``--copybook-path`` dirs shadow later ones). Returns the
    resolved :class:`Path`, or ``None`` if the member is not found anywhere.
    """
    member = _strip_quotes(member)
    member_upper = member.upper()
    for d in search_paths:
        if not d.is_dir():
            continue
        # 1. exact / extension match in deterministic extension order.
        for ext in _COPYBOOK_EXTENSIONS:
            cand = d / (member + ext)
            if cand.is_file():
                return cand
        # 2. case-insensitive scan of the directory (sorted for determinism), in
        #    case the on-disk filename case differs from the member token.
        try:
            entries = sorted(p.name for p in d.iterdir() if p.is_file())
        except OSError:
            continue
        for name in entries:
            stem_upper = Path(name).stem.upper()
            name_upper = name.upper()
            if name_upper == member_upper or stem_upper == member_upper:
                return d / name
    return None


# ------------------------------------------------------------------------------
# COPY statement folding + parsing
# ------------------------------------------------------------------------------
@dataclass
class _SourceLine:
    """A line of source being scanned for COPY directives."""

    text: str
    lineno: int  # 1-indexed within its file


def _is_copy_start(text: str) -> bool:
    """True if a clean logical line begins a COPY statement."""
    return bool(_COPY_START_RE.match(text))


def _fold_copy_statement(
    lines: List[_SourceLine], start_idx: int
) -> Tuple[str, int]:
    """Fold a COPY statement that may span lines up to its terminating period.

    Returns ``(folded_text, end_idx)`` where ``folded_text`` is the single-spaced
    COPY statement text up to and including the terminating ``.`` and ``end_idx``
    is the index of the LAST line consumed. If no terminating period is found
    before the source ends, the statement is folded to end-of-source (the parser
    then treats a periodless COPY conservatively as unresolved/malformed).
    """
    parts: List[str] = []
    i = start_idx
    n = len(lines)
    while i < n:
        seg = lines[i].text
        parts.append(seg.strip())
        # A terminating period ends the COPY statement. We look for a '.' that is
        # at end-of-segment or followed by whitespace (a COBOL separator period),
        # not the '.' inside a decimal in a literal (COPY operands here are member
        # names / pseudo-text, so a bare trailing '.' is the statement terminator).
        if seg.rstrip().endswith("."):
            break
        i += 1
    folded = " ".join(p for p in parts if p)
    return folded, i


def _parse_copy_statement(folded: str) -> Optional[Tuple[str, Optional[str], str]]:
    """Parse a folded COPY statement into ``(member, library, replacing_text)``.

    Returns ``None`` if the text is not a well-formed COPY directive (the caller
    then leaves the line as-is or marks it unresolved/malformed). ``member`` is the
    quote-stripped member token; ``library`` is the optional OF/IN library (or
    ``None``); ``replacing_text`` is the raw REPLACING operand list (or ``""``).
    """
    m = _COPY_FULL_RE.match(folded)
    if not m:
        return None
    member = _strip_quotes(m.group("member"))
    library = m.group("library")
    if library is not None:
        library = _strip_quotes(library)
    replacing_text = (m.group("replacing") or "").strip()
    return member, library, replacing_text


# ------------------------------------------------------------------------------
# The recursive expander
# ------------------------------------------------------------------------------
def _expand_lines(
    source_lines: List[_SourceLine],
    source_file: str,
    search_paths: Sequence[Path],
    parent_replacements: Sequence[_Replacement],
    expansion_stack: Tuple[ExpansionFrame, ...],
    active_members: Tuple[str, ...],
    max_depth: int,
    result: ResolveResult,
) -> None:
    """Recursively expand COPY directives in ``source_lines`` into ``result``.

    * ``parent_replacements`` — REPLACING pairs applied to the (non-COPY) text of
      THIS level (the lines copied in by the parent COPY carry the parent's
      REPLACING; the root source has none).
    * ``expansion_stack`` — the COPY-site frames that led here, outermost first.
    * ``active_members`` — the chain of member names currently being expanded, used
      for CYCLE detection (a member that re-enters its own chain is a cycle).
    * ``max_depth`` — the nesting cap; depth = len(expansion_stack).

    Every emitted :class:`ExpandedLine` carries its origin span + the current
    expansion stack. Unresolved COPY -> ``unresolved_copy`` gap (never a guess).
    Cycle / depth refusals -> diagnostics, partial expansion kept, never a hang.
    """
    i = 0
    n = len(source_lines)
    while i < n:
        sl = source_lines[i]
        if not _is_copy_start(sl.text):
            # Ordinary program line: apply THIS level's REPLACING and emit it with
            # its source span + the current expansion stack.
            text = _apply_replacements(sl.text, parent_replacements)
            result.lines.append(
                ExpandedLine(
                    text=text,
                    origin_file=source_file,
                    origin_line=sl.lineno,
                    expansion_stack=expansion_stack,
                )
            )
            i += 1
            continue

        # A COPY statement starts here — fold it to its terminating period.
        folded, end_idx = _fold_copy_statement(source_lines, i)
        copy_lineno = sl.lineno
        parsed = _parse_copy_statement(folded)
        if parsed is None:
            # Malformed COPY (e.g. no terminating period before EOF) — treat the
            # member as unresolved with the raw folded text, never a guess.
            result.gaps.append(
                Gap(
                    type=GAP_UNRESOLVED_COPY,
                    raw_copy_member=folded.strip(),
                    file=source_file,
                    line=copy_lineno,
                    detail="malformed COPY statement (no terminating period / "
                    "unparseable operands); not expanded",
                    expansion_stack=expansion_stack,
                )
            )
            i = end_idx + 1
            continue

        member, _library, replacing_text = parsed

        # Depth cap: refuse a COPY that would exceed the nesting cap.
        if len(expansion_stack) >= max_depth:
            result.gaps.append(
                Gap(
                    type=DIAG_COPY_DEPTH_EXCEEDED,
                    raw_copy_member=member,
                    file=source_file,
                    line=copy_lineno,
                    detail=f"copybook nesting depth cap ({max_depth}) exceeded at "
                    f"COPY {member}; branch refused (no expansion, no hang)",
                    expansion_stack=expansion_stack,
                )
            )
            i = end_idx + 1
            continue

        # Cycle detection: a member that re-enters its own active chain is a cycle.
        if member.upper() in {m.upper() for m in active_members}:
            result.gaps.append(
                Gap(
                    type=DIAG_COPY_CYCLE,
                    raw_copy_member=member,
                    file=source_file,
                    line=copy_lineno,
                    detail=f"copybook include cycle detected at COPY {member} "
                    f"(active chain: {' -> '.join(active_members)}); cyclic "
                    f"re-entry refused (no hang)",
                    expansion_stack=expansion_stack,
                )
            )
            i = end_idx + 1
            continue

        # Resolve the member on the search path.
        member_path = resolve_member_path(member, search_paths)
        if member_path is None:
            # CRITICAL (C3): unresolved COPY -> explicit gap, NEVER an invented edge.
            result.gaps.append(
                Gap(
                    type=GAP_UNRESOLVED_COPY,
                    raw_copy_member=member,
                    file=source_file,
                    line=copy_lineno,
                    detail=f"COPY {member} not found on any --copybook-path; "
                    f"emitted unresolved_copy gap (no guessed content)",
                    expansion_stack=expansion_stack,
                )
            )
            i = end_idx + 1
            continue

        # Resolved: read the copybook (deterministic), compile this COPY's own
        # REPLACING, and recurse into it with an extended stack + active chain.
        if member not in result.resolved_members:
            result.resolved_members.append(member)
        copy_replacements = _parse_replacing(replacing_text)
        member_lines = _read_member_lines(member_path)
        frame = ExpansionFrame(file=source_file, line=copy_lineno, member=member)
        _expand_lines(
            source_lines=member_lines,
            source_file=str(member_path),
            search_paths=search_paths,
            parent_replacements=copy_replacements,
            expansion_stack=expansion_stack + (frame,),
            active_members=active_members + (member,),
            max_depth=max_depth,
            result=result,
        )
        i = end_idx + 1


def _read_member_lines(path: Path) -> List[_SourceLine]:
    """Read a copybook member file into clean logical source lines.

    Copybooks are fixed-format COBOL fragments; we reuse the SAME column model as
    :mod:`preprocess` (drop seq cols 1-6, indicator col 7 for comment lines,
    program area cols 8-72) so the resolved text matches the clean stream the rest
    of the pipeline consumes. Comment lines are dropped; blank program areas are
    dropped. Each kept line keeps its 1-indexed line number within the member file.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    out: List[_SourceLine] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        expanded = raw.expandtabs()
        indicator = expanded[6] if len(expanded) > 6 else ""
        if indicator in ("*", "/"):
            continue  # comment line
        program = expanded[7:72].rstrip() if len(expanded) > 7 else ""
        if not program.strip():
            continue  # blank program area
        out.append(_SourceLine(text=program, lineno=lineno))
    return out


# ------------------------------------------------------------------------------
# Public entry points
# ------------------------------------------------------------------------------
def resolve_copybooks(
    clean_lines: Sequence[Tuple[str, int]],
    source_file: str,
    search_paths: Sequence[Path],
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ResolveResult:
    """Resolve all COPY directives in a clean COBOL line stream (pure, in-memory).

    ``clean_lines`` is a sequence of ``(text, lineno)`` pairs — the clean,
    col-stripped logical lines of the ROOT source (as produced by
    :func:`preprocess.preprocess_source`: iterate its ``clean_lines`` and pass
    ``(cl.text, cl.origin.line)``). ``source_file`` is the root source label (for
    provenance). ``search_paths`` are the ``--copybook-path`` directories, in
    precedence order. ``max_depth`` bounds nesting.

    Returns a :class:`ResolveResult` with the fully-expanded program lines (each
    with its source-span + expansion-stack provenance), the typed gaps, and the
    resolved-member list. Pure / deterministic — no LLM, no network.
    """
    root_lines = [_SourceLine(text=t, lineno=ln) for (t, ln) in clean_lines]
    result = ResolveResult()
    _expand_lines(
        source_lines=root_lines,
        source_file=source_file,
        search_paths=[Path(p) for p in search_paths],
        parent_replacements=(),
        expansion_stack=(),
        active_members=(),
        max_depth=max_depth,
        result=result,
    )
    result.resolved_members.sort()
    return result


def resolve_file(
    path,
    search_paths: Sequence,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ResolveResult:
    """Preprocess a COBOL source file and resolve its COPY directives.

    Convenience composing :func:`preprocess.preprocess_file` with
    :func:`resolve_copybooks`. Reads the source via the preprocessing core (so the
    fixed-format strip + continuation folding + EXEC SQL split happen first), then
    expands COPYs over the clean COBOL stream.
    """
    pp = _import_preprocess()
    pre = pp.preprocess_file(path)
    clean = [(cl.text, cl.origin.line) for cl in pre.clean_lines]
    return resolve_copybooks(
        clean_lines=clean,
        source_file=str(path),
        search_paths=[Path(p) for p in search_paths],
        max_depth=max_depth,
    )


def _import_preprocess():
    """Import the sibling preprocess module by path (path-robust, like the tests).

    Importing by file path (rather than a package import) keeps the resolver
    runnable from any tree slice / CWD, matching the path-load convention the unit
    tests use. Registers in ``sys.modules`` before exec so dataclass annotation
    resolution under ``from __future__ import annotations`` succeeds on 3.12.
    """
    import importlib.util

    name = "mlp_preprocess"
    if name in sys.modules:
        return sys.modules[name]
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(name, here / "preprocess.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------
# CLI (the --copybook-missing gap/fail selector)
# ------------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="copybook_resolver.py",
        description=(
            "Deterministic COBOL COPY...REPLACING expander (mainframe-lineage-"
            "parsers). Pure stdlib, no LLM, no network. Unresolved COPY -> "
            "explicit unresolved_copy gap (default) or non-zero exit (--copybook-"
            "missing=fail). Cycles / depth-cap refusals never hang."
        ),
    )
    p.add_argument("source", help="COBOL source file to expand")
    p.add_argument(
        "--copybook-path",
        action="append",
        default=[],
        metavar="DIR",
        help="copybook search directory (repeatable; earlier dirs win)",
    )
    p.add_argument(
        "--copybook-missing",
        choices=("gap", "fail"),
        default="gap",
        help="how to treat an unresolved COPY: 'gap' (default, emit "
        "unresolved_copy gap node) or 'fail' (exit non-zero)",
    )
    p.add_argument(
        "--max-depth",
        type=int,
        default=DEFAULT_MAX_DEPTH,
        help=f"copybook nesting depth cap (default {DEFAULT_MAX_DEPTH})",
    )
    p.add_argument(
        "--show-stack",
        action="store_true",
        help="annotate each expanded line with its expansion stack (diagnostic)",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry. Returns the process exit code.

    Exit codes:
      * 0 — expansion completed (gaps may be present when --copybook-missing=gap).
      * 2 — an unresolved COPY was found AND --copybook-missing=fail.
      * 1 — fatal input error (e.g. source file unreadable).
    """
    args = _build_arg_parser().parse_args(argv)
    src = Path(args.source)
    if not src.is_file():
        print(f"error: source file not found: {src}", file=sys.stderr)
        return 1

    try:
        result = resolve_file(
            src,
            search_paths=args.copybook_path,
            max_depth=args.max_depth,
        )
    except OSError as e:  # pragma: no cover - defensive I/O guard
        print(f"error: {e}", file=sys.stderr)
        return 1

    # Emit the expanded program text to stdout (deterministic).
    for ln in result.lines:
        if args.show_stack and ln.expansion_stack:
            stack = " <- ".join(
                f"{f.member}@{f.file}:{f.line}" for f in ln.expansion_stack
            )
            print(f"{ln.text}\t;; [{stack}]")
        else:
            print(ln.text)

    # Report gaps/diagnostics to stderr (never blocks; never a prompt).
    for g in result.gaps:
        print(
            f"gap: {g.type} member={g.raw_copy_member!r} "
            f"at {g.file}:{g.line} — {g.detail}",
            file=sys.stderr,
        )

    # --copybook-missing=fail makes an unresolved COPY a hard failure.
    if args.copybook_missing == "fail" and result.has_unresolved_copy():
        print(
            "error: unresolved COPY with --copybook-missing=fail",
            file=sys.stderr,
        )
        return 2
    return 0


__all__ = [
    "ExpansionFrame",
    "ExpandedLine",
    "Gap",
    "ResolveResult",
    "resolve_copybooks",
    "resolve_file",
    "resolve_member_path",
    "GAP_UNRESOLVED_COPY",
    "DIAG_COPY_CYCLE",
    "DIAG_COPY_DEPTH_EXCEEDED",
    "DEFAULT_MAX_DEPTH",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
