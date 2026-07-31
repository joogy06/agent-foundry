#!/usr/bin/env python3
"""cobol_extract.py — the COBOL extractor for ``mainframe-lineage-parsers`` (WP-6).

Part of the ``mainframe-lineage-parsers`` skill (the deterministic v1.1 plug-in
track under ``lineage-extract-static`` anti-pattern #7 — a *complement*, not a
replacement, of the LLM-as-parser family). This is the SECOND half of
precision-win edge class #1 (the COBOL side):

    JCL DSN -> DDNAME (WP-5)  ==  COBOL SELECT...ASSIGN TO <ddname>
                                       -> FD record -> READ/WRITE direction

The graph assembler (WP-8) stitches the JCL side (WP-5) and this COBOL side
together on the shared DDNAME so the physical-dataset-to-program-file edge is
connected end to end (precision-win join #1).

------------------------------------------------------------------------------
THE REUSE CRUX (design §3 "reuse, don't reinvent" — WP-6 acceptance #1)
------------------------------------------------------------------------------
This module does **NOT** reimplement COBOL parsing. It IMPORTS
``structure-recovery/scripts/cobol_offset_calc.py`` as a MODULE and reuses its
deterministic COBOL record machinery:

  * ``parse_pic``            — PICTURE -> position counts
  * ``normalize_usage``      — USAGE normalisation
  * ``elementary_length``    — elementary-item byte length
  * ``build_tree``           — reconstruct the COBOL level hierarchy
  * ``compute_offsets``      — byte offsets + record-length rollup
  * ``compute_finding_offsets`` — the whole-finding convenience wrapper

The file is imported by path (``_import_cobol_offset_calc``); it is NOT copied or
forked. The test (``test_cobol_extract.py``) asserts the imported module identity
(same file on disk) so a future fork would fail the suite.

This skill adds ONLY the LINEAGE layer on top of that machinery:

  (a) ENVIRONMENT DIVISION ``SELECT file ASSIGN TO <ddname>`` -> the join key that
      bridges the JCL DDNAME (WP-5) to the COBOL file (a ``direct`` literal edge:
      file dataset -> program, ``grounded``);
  (b) DATA DIVISION ``FD``/``SD`` record layouts -> build the field level-tree via
      the reused ``build_tree`` and compute record offsets via the reused
      ``compute_offsets`` (for record identity / length, NOT new offset logic —
      the record length lives as a ``record_length`` facet on the file node);
  (c) PROCEDURE DIVISION ``READ`` / ``REWRITE`` / ``DELETE`` -> a file -> program
      DIRECTION edge (the program reads the file); ``WRITE`` -> a program -> file
      DIRECTION edge (the program writes the file);
  (d) ``MOVE a TO b`` field flow edges, CONSERVATIVELY — a MOVE between fields is a
      structurally-indirect ``inferred``-kind edge (NEVER ``grounded``; its
      confidence ceiling is ``inferred`` per ir.py).

v1 ships file/record + ASSIGN-TO + READ/WRITE as high-confidence
(``grounded`` / ``inferred``); deeper field-level dataflow
(REDEFINES / OCCURS / PERFORM / CALL / COMPUTE / STRING / UNSTRING / SORT) is
``kind=inferred`` or ``kind=interproc_unknown`` (forced ``speculative``) or an
explicit non-goal diagnostic, NEVER confidently claimed (design §4 / §8, Codex M).

The COBOL program job identity is ``name=<program-id>`` in namespace
``mainframe://<program-id>`` per naming-contract §3.

------------------------------------------------------------------------------
Inputs (the pipeline upstream)
------------------------------------------------------------------------------
This extractor consumes the PREPROCESSED clean source (WP-2,
``preprocess.preprocess_*``) and the RESOLVED copybooks (WP-3,
``copybook_resolver.resolve_*``): EXEC SQL was already split out by preprocess
BEFORE copybook expansion, so the resolver sees pure COBOL and this extractor
sees a clean, COPY-expanded COBOL stream of :class:`ExpandedLine`-equivalent
records carrying ``(text, origin_file, origin_line, expansion_stack)``. The
``expansion_stack`` is attached to every edge derived from a copied line as the
``copybook_expansion_stack`` provenance facet (design §7 "provenance everywhere").

A WP-3 ``unresolved_copy`` gap is mapped to an ir ``gap_unresolved_copy`` contract
gap; ``copy_cycle`` / ``copy_depth_exceeded`` resolver diagnostics surface as an
``unresolved`` provenance note (NOT a contract gap — the frozen §5 set stays
closed).

------------------------------------------------------------------------------
Purity / determinism
------------------------------------------------------------------------------
This module is **pure stdlib** — NO LLM, NO ``sqlglot``/``networkx``, NO new pip
deps, NO network, NO shell, NO runtime pip install (design D1). The deterministic
engine has no LLM in the loop, ever (C2). Everything this module emits flows
through :mod:`ir` (WP-4) and conforms BYTE-FOR-BYTE to
``references/naming-contract.md`` (WP-1, §3 / §4 / §6). The returned IR slice is
canonical-sorted + deduped by canonical edge key so output is byte-identical on
re-run (naming-contract §6; the WP-8 assembler re-applies the global sort).

The language here is model-neutral. The extractor runs the same way regardless of
which CLI host invokes the engine (Claude Code, Codex CLI, Copilot CLI,
Antigravity CLI).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


# ------------------------------------------------------------------------------
# Path-load the sibling modules (WP-2 preprocess, WP-3 copybook_resolver, WP-4 ir,
# and the structure-recovery cobol_offset_calc REUSE crux) — keep the extractor
# runnable from any tree slice / CWD, matching the sibling convention (register in
# sys.modules BEFORE exec so dataclass annotation resolution under
# ``from __future__ import annotations`` succeeds on 3.12).
# ------------------------------------------------------------------------------
def _path_load(name: str, target: Path):
    """Load a module by file path and register it in ``sys.modules`` before exec.

    Path-load (not a package import) keeps the extractor runnable from any tree
    slice / CWD, mirroring the WP-2/3/4/5 convention. Registering in sys.modules
    BEFORE ``exec_module`` is required so that ``from __future__ import
    annotations`` dataclass annotation resolution finds the module on 3.12."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, target)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {name} from {target}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _import_ir():
    return _path_load("mlp_ir", Path(__file__).resolve().parent / "ir.py")


def _import_preprocess():
    return _path_load("mlp_preprocess", Path(__file__).resolve().parent / "preprocess.py")


def _import_copybook_resolver():
    return _path_load(
        "mlp_copybook_resolver",
        Path(__file__).resolve().parent / "copybook_resolver.py",
    )


def _cobol_offset_calc_path() -> Path:
    """The on-disk path to the structure-recovery REUSE crux.

    ``skills/mainframe-lineage-parsers/scripts/cobol_extract.py`` ->
    ``skills/structure-recovery/scripts/cobol_offset_calc.py`` is two parents up
    from ``scripts`` (``skills/``), then down the sibling skill tree."""
    here = Path(__file__).resolve().parent  # .../mainframe-lineage-parsers/scripts
    return here.parent.parent / "structure-recovery" / "scripts" / "cobol_offset_calc.py"


def _import_cobol_offset_calc():
    """Import the structure-recovery COBOL machinery as a MODULE (the reuse crux).

    We IMPORT — never copy/fork — ``cobol_offset_calc.py`` so there is exactly one
    source of truth for the deterministic COBOL record machinery (WP-6 acceptance
    #1; the test asserts the imported module's ``__file__`` is this very path)."""
    return _path_load("sr_cobol_offset_calc", _cobol_offset_calc_path())


ir = _import_ir()
_coc = _import_cobol_offset_calc()


# ------------------------------------------------------------------------------
# Namespaces (naming-contract §3 / §4)
# ------------------------------------------------------------------------------
DSN_NAMESPACE = "mainframe://DSN"      # physical dataset namespace (shared w/ JCL)
FILE_NAMESPACE = "mainframe://FILE"    # a COBOL logical file (the SELECT name)


def program_namespace(program_id: str) -> str:
    """``mainframe://<program-id>`` (program-id already case-folded, §3 / §6)."""
    return f"mainframe://{program_id}"


# ------------------------------------------------------------------------------
# COBOL token / clause recognition (operates on clean, col-8-72-stripped lines)
# ------------------------------------------------------------------------------
# PROGRAM-ID. name. (the period is optional on the clean logical line; the value
# may be followed by IS INITIAL / IS COMMON / RECURSIVE clauses we ignore).
_PROGRAM_ID_RE = re.compile(
    r"\bPROGRAM-ID\b\s*\.?\s*(?P<name>[A-Za-z0-9$#@_-]+)",
    re.IGNORECASE,
)

# SELECT [OPTIONAL] file-name ASSIGN [TO] ... ddname ...
# The ASSIGN target in IBM Enterprise COBOL is usually a system-name of the form
# ``[device-]ddname`` or a literal ``"ddname"`` or an environment-name. We take
# the LAST identifier/literal token of the ASSIGN clause as the ddname (the
# external name JCL binds to), upper-cased.
_SELECT_RE = re.compile(
    r"\bSELECT\b\s+(?:OPTIONAL\s+)?(?P<file>[A-Za-z0-9$#@_-]+)\b"
    r"(?P<rest>.*?)(?=\bSELECT\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_ASSIGN_RE = re.compile(
    r"\bASSIGN\b\s+(?:TO\s+)?(?P<target>.+?)(?:\bORGANIZATION\b|\bACCESS\b|"
    r"\bFILE\s+STATUS\b|\bRESERVE\b|\bPADDING\b|\bRECORD\b|\bLOCK\b|\.|$)",
    re.IGNORECASE | re.DOTALL,
)
# The trailing token of an ASSIGN target — strip a device/medium prefix
# (``UT-S-`` / ``DA-`` etc.) and any quotes; the ddname is the last word.
_ASSIGN_TOKEN_RE = re.compile(r"[A-Za-z0-9$#@_-]+")

# FD / SD file-name ... (record description follows on later lines).
_FD_RE = re.compile(r"\b(?P<kind>FD|SD)\b\s+(?P<file>[A-Za-z0-9$#@_-]+)", re.IGNORECASE)

# A data-description entry: level-number  name  [clauses].  The level is 01-49 /
# 66 / 77 / 88; the name may be FILLER. We capture the level + name + the rest
# (PIC / USAGE / OCCURS / REDEFINES live in the rest) and feed the reused machinery.
_DATA_ENTRY_RE = re.compile(
    r"^\s*(?P<level>\d{1,2})\s+(?P<name>[A-Za-z0-9$#@_-]+|FILLER)\b(?P<rest>.*)$",
    re.IGNORECASE,
)
_PIC_RE = re.compile(r"\b(?:PIC|PICTURE)\b(?:\s+IS)?\s+(?P<pic>\S+)", re.IGNORECASE)
_USAGE_RE = re.compile(
    r"\b(?:USAGE\s+(?:IS\s+)?)?(?P<usage>COMP-[1-5]|COMP|COMPUTATIONAL(?:-[1-5])?|"
    r"BINARY|PACKED-DECIMAL|DISPLAY-1|DISPLAY|INDEX|POINTER|NATIONAL)\b",
    re.IGNORECASE,
)
# OCCURS <n> [TO <m>] [TIMES] — capture both the lower bound (n) and the optional
# upper bound (m) so the reused machinery sizes a ``1 TO 10`` ODO table correctly
# (its schema: ``occurs`` == lower, ``occurs_max`` == TO upper, when DEPENDING ON).
_OCCURS_RE = re.compile(r"\bOCCURS\b\s+(?P<n>\d+)(?:\s+TO\s+(?P<m>\d+))?", re.IGNORECASE)
_OCCURS_DEPENDING_RE = re.compile(r"\bOCCURS\b.*\bDEPENDING\s+ON\b", re.IGNORECASE)
# OCCURS ... DEPENDING ON <ctrl> — capture the controlling data-name (the key the
# reused machinery reads as ``occurs_depending_on`` to trigger min/max rollup).
_OCCURS_DEPENDING_TGT_RE = re.compile(
    r"\bDEPENDING\s+(?:ON\s+)?(?P<ctrl>[A-Za-z0-9$#@_-]+)", re.IGNORECASE
)
_REDEFINES_RE = re.compile(r"\bREDEFINES\b\s+(?P<target>[A-Za-z0-9$#@_-]+)", re.IGNORECASE)

# PROCEDURE-DIVISION I/O verbs against a file (READ/WRITE/REWRITE/DELETE/START).
# WRITE/REWRITE take a RECORD name, not the file name, so they are resolved via
# the record->file map built from the FD section.
_READ_RE = re.compile(r"\bREAD\b\s+(?P<file>[A-Za-z0-9$#@_-]+)", re.IGNORECASE)
_START_RE = re.compile(r"\bSTART\b\s+(?P<file>[A-Za-z0-9$#@_-]+)", re.IGNORECASE)
_DELETE_RE = re.compile(r"\bDELETE\b\s+(?P<file>[A-Za-z0-9$#@_-]+)", re.IGNORECASE)
_WRITE_RE = re.compile(r"\bWRITE\b\s+(?P<rec>[A-Za-z0-9$#@_-]+)", re.IGNORECASE)
_REWRITE_RE = re.compile(r"\bREWRITE\b\s+(?P<rec>[A-Za-z0-9$#@_-]+)", re.IGNORECASE)

# MOVE a TO b  (conservative single-source single-target form; MOVE CORRESPONDING
# and multi-target MOVE a TO b c are handled as inferred edges to each target).
_MOVE_RE = re.compile(
    r"\bMOVE\b\s+(?P<src>(?:CORRESPONDING\s+|CORR\s+)?[A-Za-z0-9$#@_().:-]+(?:\s+OF\s+[A-Za-z0-9$#@_-]+)?)"
    r"\s+TO\s+(?P<dst>.+?)(?:\.|$)",
    re.IGNORECASE,
)

# Deeper-dataflow verbs we flag as interproc/inferred non-goals (never grounded).
_PERFORM_RE = re.compile(r"\bPERFORM\b", re.IGNORECASE)
_CALL_RE = re.compile(r"\bCALL\b\s+(?P<tgt>'[^']+'|\"[^\"]+\"|[A-Za-z0-9$#@_-]+)", re.IGNORECASE)

# Division headers (for sectioning the clean stream).
_DIVISION_RE = re.compile(
    r"\b(?P<div>IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b",
    re.IGNORECASE,
)


# ------------------------------------------------------------------------------
# A clean COBOL line with provenance (mirrors copybook_resolver.ExpandedLine so we
# can accept either the resolver's output OR a plain (text, file, line) tuple).
# ------------------------------------------------------------------------------
@dataclass
class CleanCobolLine:
    """One clean, COPY-expanded COBOL logical line + its provenance.

    ``expansion_stack`` is the COPY-site member trail (member names, outermost
    first) that pulled the line in — empty for root-source lines. It becomes the
    ``copybook_expansion_stack`` provenance facet on every edge derived from a
    copied line (design §7)."""

    text: str
    origin_file: str
    origin_line: int
    expansion_stack: Tuple[str, ...] = ()


def _lines_from_resolve_result(rr) -> List[CleanCobolLine]:
    """Adapt a copybook_resolver.ResolveResult into CleanCobolLine records.

    The resolver's ``ExpandedLine.expansion_stack`` is a tuple of
    ``ExpansionFrame`` (file/line/member); we flatten it to the member-name trail
    for the provenance facet (the full file:line trail is recoverable from the
    resolver's own gaps; the edge facet keeps the member trail, which is what the
    user diffs against the LLM tool)."""
    out: List[CleanCobolLine] = []
    for el in rr.lines:
        stack = tuple(fr.member for fr in el.expansion_stack)
        out.append(
            CleanCobolLine(
                text=el.text,
                origin_file=el.origin_file,
                origin_line=el.origin_line,
                expansion_stack=stack,
            )
        )
    return out


# ------------------------------------------------------------------------------
# Sectioning
# ------------------------------------------------------------------------------
@dataclass
class _Sections:
    identification: List[CleanCobolLine] = field(default_factory=list)
    environment: List[CleanCobolLine] = field(default_factory=list)
    data: List[CleanCobolLine] = field(default_factory=list)
    procedure: List[CleanCobolLine] = field(default_factory=list)


def _section_lines(lines: Sequence[CleanCobolLine]) -> _Sections:
    """Partition the clean COBOL lines into the four divisions.

    Deterministic: the first division header seen switches the active bucket;
    lines before any header land in IDENTIFICATION (a forgiving default)."""
    sec = _Sections()
    active = "IDENTIFICATION"
    bucket = {
        "IDENTIFICATION": sec.identification,
        "ID": sec.identification,
        "ENVIRONMENT": sec.environment,
        "DATA": sec.data,
        "PROCEDURE": sec.procedure,
    }
    for ln in lines:
        m = _DIVISION_RE.search(ln.text)
        if m:
            div = m.group("div").upper()
            active = "IDENTIFICATION" if div == "ID" else div
            # The header line itself carries no field/verb content we need.
            continue
        bucket[active].append(ln)
    return sec


# ------------------------------------------------------------------------------
# IDENTIFICATION DIVISION -> PROGRAM-ID (naming-contract §3)
# ------------------------------------------------------------------------------
def extract_program_id(lines: Sequence[CleanCobolLine]) -> Optional[str]:
    """Return the upper-cased PROGRAM-ID, or ``None`` if not declared.

    Case-folded per naming-contract §6 BEFORE node construction so the program
    node id is stable across case variants."""
    for ln in lines:
        m = _PROGRAM_ID_RE.search(ln.text)
        if m:
            return m.group("name").upper()
    return None


# ------------------------------------------------------------------------------
# ENVIRONMENT DIVISION -> SELECT ... ASSIGN TO <ddname>  (the bridge to JCL)
# ------------------------------------------------------------------------------
@dataclass
class SelectClause:
    """A COBOL ``SELECT file ASSIGN TO ddname`` binding.

    ``ddname`` is upper-cased — it is the SAME bind key the JCL side (WP-5) puts
    on its DD edges, so the WP-8 assembler can stitch on it (precision-win #1).
    ``file`` is the COBOL logical file name (upper-cased)."""

    file: str
    ddname: str
    origin_file: str
    origin_line: int
    expansion_stack: Tuple[str, ...] = ()


def _assign_ddname(rest: str) -> Optional[str]:
    """Extract the DDNAME from a SELECT clause body (the ASSIGN target).

    IBM Enterprise COBOL ASSIGN targets look like ``ASSIGN TO UT-S-PAYIN`` or
    ``ASSIGN TO PAYIN`` or ``ASSIGN TO "PAYIN"``: the external DDNAME is the LAST
    token of the system-name (device/medium prefixes like ``UT-S-`` are dropped).
    Returns the upper-cased ddname, or ``None`` if no ASSIGN target is present."""
    am = _ASSIGN_RE.search(rest)
    if not am:
        return None
    target = am.group("target").strip().strip('"').strip("'")
    if not target:
        return None
    # The assign target may be a hyphenated system-name (UT-S-DDNAME). IBM treats
    # the portion after the last device/organisation qualifier as the ddname, but
    # the safe deterministic rule is: the LAST hyphen-delimited token IF the token
    # is preceded by a recognised device prefix, else the whole token. We take the
    # last token of the last whitespace-separated word, then its last hyphen group.
    words = _ASSIGN_TOKEN_RE.findall(target)
    if not words:
        return None
    last_word = words[-1]
    # Split a hyphenated system-name; the ddname is the final segment when there
    # is a device/medium prefix (>=2 segments). A bare name stays whole.
    segments = last_word.split("-")
    ddname = segments[-1] if len(segments) >= 2 else last_word
    return ddname.upper()


def extract_selects(lines: Sequence[CleanCobolLine]) -> List[SelectClause]:
    """Extract every ``SELECT file ASSIGN TO ddname`` from the ENVIRONMENT lines.

    The SELECT statements live in INPUT-OUTPUT SECTION / FILE-CONTROL; we scan the
    whole ENVIRONMENT division text (joined) so a SELECT split across continuation
    lines is captured. Deterministic; ddname upper-cased (the JCL bind key)."""
    # Join with a space + keep a per-char map back to the originating clean line
    # so each SELECT's provenance is the line its ``SELECT`` keyword started on.
    selects: List[SelectClause] = []
    # Build a single text but remember each clean line's start offset.
    parts: List[str] = []
    starts: List[Tuple[int, CleanCobolLine]] = []
    pos = 0
    for ln in lines:
        starts.append((pos, ln))
        parts.append(ln.text)
        pos += len(ln.text) + 1  # +1 for the joining space
    joined = " ".join(parts)

    def _line_at(offset: int) -> CleanCobolLine:
        chosen = starts[0][1] if starts else CleanCobolLine("", "", 0)
        for off, ln in starts:
            if off <= offset:
                chosen = ln
            else:
                break
        return chosen

    for sm in _SELECT_RE.finditer(joined):
        file_name = sm.group("file").upper()
        rest = sm.group("rest") or ""
        ddname = _assign_ddname(rest)
        if ddname is None:
            # A SELECT with no resolvable ASSIGN target is not a JCL bind point;
            # skip it (no invented ddname — C3).
            continue
        src_line = _line_at(sm.start())
        selects.append(
            SelectClause(
                file=file_name,
                ddname=ddname,
                origin_file=src_line.origin_file,
                origin_line=src_line.origin_line,
                expansion_stack=src_line.expansion_stack,
            )
        )
    return selects


# ------------------------------------------------------------------------------
# DATA DIVISION -> FD records (reuse the structure-recovery offset machinery)
# ------------------------------------------------------------------------------
@dataclass
class FileRecord:
    """An FD/SD file's record layout result.

    ``record_names`` are the 01-level record names under the FD (the WRITE/REWRITE
    verbs name a record, which we map back to the file). ``record_length`` is the
    record byte length computed by the REUSED ``compute_offsets`` (None when the
    record is variable/unknown — never guessed). ``field_count`` is the number of
    declared data-description entries fed to the reused machinery."""

    file: str
    record_names: List[str]
    record_length: Optional[int]
    record_length_min: Optional[int]
    record_length_max: Optional[int]
    variable_length: bool
    field_count: int
    offset_confidence: str
    origin_file: str
    origin_line: int
    expansion_stack: Tuple[str, ...] = ()
    copybook_sourced: bool = False


def _parse_data_entry(text: str) -> Optional[dict]:
    """Parse one clean data-description line into a field dict for the REUSED
    ``cobol_offset_calc`` machinery.

    Returns the field shape ``cobol_offset_calc.build_tree`` / ``compute_offsets``
    expect — note the EXACT key names the reused machinery reads (verified against
    the structure-recovery source): ``level`` + ``name`` + ``pic_clause`` +
    ``usage`` + ``occurs`` + ``occurs_depending_on`` + ``redefines``. We do NOT
    compute any byte offset here — that is the reused machinery's job (the safety
    crux: Python is the calculator, this layer is the reader). Returns ``None`` if
    the line is not a data-description entry."""
    m = _DATA_ENTRY_RE.match(text)
    if not m:
        return None
    level = int(m.group("level"))
    name = m.group("name").upper()
    rest = m.group("rest") or ""
    fld: dict = {"level": level, "name": name}
    pm = _PIC_RE.search(rest)
    if pm:
        # The reused machinery reads ``pic_clause`` (NOT ``pic``).
        fld["pic_clause"] = pm.group("pic").rstrip(".")
    um = _USAGE_RE.search(rest)
    if um:
        fld["usage"] = um.group("usage").upper()
    om = _OCCURS_RE.search(rest)
    if om:
        # ``occurs`` is the lower (fixed) bound; ``occurs_max`` is the TO upper bound
        # when present (an ``OCCURS 1 TO 10`` range). The reused machinery uses
        # both for the ODO min/max rollup.
        fld["occurs"] = int(om.group("n"))
        if om.group("m"):
            fld["occurs_max"] = int(om.group("m"))
    odm = _OCCURS_DEPENDING_TGT_RE.search(rest)
    if odm:
        # The reused machinery reads ``occurs_depending_on`` (the controlling
        # data-name), which triggers the variable-length / min-max rollup.
        fld["occurs_depending_on"] = odm.group("ctrl").upper()
    rm = _REDEFINES_RE.search(rest)
    if rm:
        fld["redefines"] = rm.group("target").upper()
    return fld


def extract_file_records(lines: Sequence[CleanCobolLine]) -> List[FileRecord]:
    """Extract every FD/SD file + its record layout from the DATA DIVISION lines.

    For each FD/SD: collect the following data-description entries (until the next
    FD/SD or a non-data line that is clearly outside the record), feed them to the
    REUSED ``compute_offsets`` for the record length + the field level-tree, and
    record the 01-level record names (for the WRITE/REWRITE record->file map)."""
    records: List[FileRecord] = []
    i = 0
    n = len(lines)
    while i < n:
        fdm = _FD_RE.search(lines[i].text)
        if not fdm:
            i += 1
            continue
        file_name = fdm.group("file").upper()
        fd_line = lines[i]
        i += 1
        # Collect data-description entries until the next FD/SD or a WORKING-STORAGE
        # / division boundary (defensive: a non-entry, non-blank, non-clause line
        # that is not a continuation of the record). A SINGLE data-description entry
        # may span several clean lines (a COBOL clause list wraps freely without any
        # continuation marker, e.g. ``OCCURS 1 TO 10 TIMES DEPENDING ON X`` on the
        # next line). We fold each entry up to its terminating period before parsing
        # so the OCCURS/DEPENDING/REDEFINES clauses are seen on the right field.
        fields: List[dict] = []
        record_names: List[str] = []
        copybook_sourced = False
        rec_expansion_stack: Tuple[str, ...] = ()
        while i < n:
            txt = lines[i].text
            if _FD_RE.search(txt):
                break
            up = txt.strip().upper()
            if up.startswith("WORKING-STORAGE") or up.startswith("LINKAGE") \
                    or up.startswith("LOCAL-STORAGE") or _DIVISION_RE.search(txt):
                break
            # Fold the entry: start at a level-numbered line, append following lines
            # that are NOT themselves a new data-description entry (no leading
            # level number) until a terminating period is seen.
            entry_lines = [lines[i]]
            folded = txt
            i += 1
            if _DATA_ENTRY_RE.match(txt):
                while i < n and "." not in folded:
                    nxt = lines[i].text
                    if _DATA_ENTRY_RE.match(nxt) or _FD_RE.search(nxt) \
                            or _DIVISION_RE.search(nxt):
                        break  # a new entry / boundary starts; do not swallow it
                    folded = folded.rstrip() + " " + nxt.strip()
                    entry_lines.append(lines[i])
                    i += 1
            entry = _parse_data_entry(folded)
            if entry is not None:
                fields.append(entry)
                if entry["level"] == 1:  # 01-level record name
                    record_names.append(entry["name"])
                # Capture the copybook expansion stack of any copied field line so
                # the FD record (and the SELECT edge) carry the provenance.
                for el in entry_lines:
                    if el.expansion_stack:
                        copybook_sourced = True
                        if not rec_expansion_stack:
                            rec_expansion_stack = el.expansion_stack

        # REUSE the structure-recovery offset machinery for the record length +
        # field level-tree (the crux). Never compute offsets ourselves.
        rec_len: Optional[int] = None
        rec_min: Optional[int] = None
        rec_max: Optional[int] = None
        variable = False
        offset_conf = "speculative"
        if fields:
            try:
                comp = _coc.compute_offsets(fields)
                rec_len = comp.record_length
                rec_min = comp.record_length_min
                rec_max = comp.record_length_max
                variable = comp.variable_length
                offset_conf = comp.confidence
            except Exception:
                # The reused machinery never raises on a well-formed field list;
                # a parse anomaly degrades to speculative (never an invented size).
                offset_conf = "speculative"

        records.append(
            FileRecord(
                file=file_name,
                record_names=record_names,
                record_length=rec_len,
                record_length_min=rec_min,
                record_length_max=rec_max,
                variable_length=variable,
                field_count=len(fields),
                offset_confidence=offset_conf,
                origin_file=fd_line.origin_file,
                origin_line=fd_line.origin_line,
                # The FD line itself is rarely copybook-sourced, but its record
                # body often is — carry the copied fields' expansion stack so the
                # SELECT/ASSIGN edge's provenance shows the copybook trail.
                expansion_stack=rec_expansion_stack or fd_line.expansion_stack,
                copybook_sourced=copybook_sourced,
            )
        )
    return records


# ------------------------------------------------------------------------------
# PROCEDURE DIVISION -> READ/WRITE direction + MOVE flow
# ------------------------------------------------------------------------------
@dataclass
class IOAccess:
    """A PROCEDURE-DIVISION I/O access against a file.

    ``direction`` is ``read`` (file -> program: READ/START/DELETE) or ``write``
    (program -> file: WRITE/REWRITE). ``file`` is the resolved file name
    (upper-cased)."""

    file: str
    direction: str          # "read" | "write"
    verb: str               # READ / WRITE / REWRITE / DELETE / START
    origin_file: str
    origin_line: int
    expansion_stack: Tuple[str, ...] = ()


@dataclass
class MoveFlow:
    """A conservative ``MOVE src TO dst`` field-flow (an inferred-kind edge)."""

    src: str
    dst: str
    origin_file: str
    origin_line: int
    expansion_stack: Tuple[str, ...] = ()


@dataclass
class DeeperDataflow:
    """A deeper-dataflow construct flagged as a non-goal diagnostic (never claimed
    as a grounded edge): PERFORM / CALL / OCCURS-DEPENDING / REDEFINES etc."""

    construct: str          # perform | call | occurs_depending | redefines
    detail: str
    origin_file: str
    origin_line: int
    expansion_stack: Tuple[str, ...] = ()


def extract_io_and_flow(
    lines: Sequence[CleanCobolLine],
    record_to_file: Dict[str, str],
) -> Tuple[List[IOAccess], List[MoveFlow], List[DeeperDataflow]]:
    """Scan the PROCEDURE DIVISION for I/O verbs + conservative MOVE flow.

    ``record_to_file`` maps an 01-level record name -> its FD file (so WRITE/REWRITE
    <record> resolves to the file). Returns (io_accesses, move_flows,
    deeper_dataflow_diagnostics). Deterministic; no invented targets (C3)."""
    ios: List[IOAccess] = []
    moves: List[MoveFlow] = []
    deeper: List[DeeperDataflow] = []

    for ln in lines:
        txt = ln.text
        # READ file -> file reads into the program (file -> program).
        for rx, verb, direction in (
            (_READ_RE, "READ", "read"),
            (_START_RE, "START", "read"),
            (_DELETE_RE, "DELETE", "read"),
        ):
            m = rx.search(txt)
            if m:
                ios.append(IOAccess(
                    file=m.group("file").upper(), direction=direction, verb=verb,
                    origin_file=ln.origin_file, origin_line=ln.origin_line,
                    expansion_stack=ln.expansion_stack,
                ))
        # WRITE/REWRITE name a RECORD; map it back to its file (program -> file).
        for rx, verb in ((_WRITE_RE, "WRITE"), (_REWRITE_RE, "REWRITE")):
            m = rx.search(txt)
            if m:
                rec = m.group("rec").upper()
                file_name = record_to_file.get(rec)
                if file_name is None:
                    # Cannot resolve the record to a file -> a deeper/interproc
                    # diagnostic, NOT an invented file edge (C3).
                    deeper.append(DeeperDataflow(
                        construct="unresolved_record",
                        detail=f"{verb} {rec}: record not mapped to an FD file",
                        origin_file=ln.origin_file, origin_line=ln.origin_line,
                        expansion_stack=ln.expansion_stack,
                    ))
                else:
                    ios.append(IOAccess(
                        file=file_name, direction="write", verb=verb,
                        origin_file=ln.origin_file, origin_line=ln.origin_line,
                        expansion_stack=ln.expansion_stack,
                    ))
        # MOVE a TO b ... (conservative; multi-target -> one edge per target).
        mm = _MOVE_RE.search(txt)
        if mm:
            src_raw = mm.group("src").strip()
            dst_raw = mm.group("dst").strip().rstrip(".")
            src = _normalise_operand(src_raw)
            corresponding = src_raw.upper().startswith(("CORRESPONDING", "CORR"))
            for dst_tok in _split_move_targets(dst_raw):
                dst = _normalise_operand(dst_tok)
                if not src or not dst:
                    continue
                moves.append(MoveFlow(
                    src=src, dst=dst,
                    origin_file=ln.origin_file, origin_line=ln.origin_line,
                    expansion_stack=ln.expansion_stack,
                ))
            if corresponding:
                deeper.append(DeeperDataflow(
                    construct="move_corresponding",
                    detail="MOVE CORRESPONDING expands by matching subordinate "
                           "names; the field-level edges are inferred, not grounded",
                    origin_file=ln.origin_file, origin_line=ln.origin_line,
                    expansion_stack=ln.expansion_stack,
                ))
        # Deeper-dataflow non-goals (flag, never claim a grounded edge).
        if _PERFORM_RE.search(txt):
            deeper.append(DeeperDataflow(
                construct="perform",
                detail="PERFORM control flow — intra/inter-paragraph dataflow is "
                       "interproc_unknown, not a grounded data edge",
                origin_file=ln.origin_file, origin_line=ln.origin_line,
                expansion_stack=ln.expansion_stack,
            ))
        cm = _CALL_RE.search(txt)
        if cm:
            deeper.append(DeeperDataflow(
                construct="call",
                detail=f"CALL {cm.group('tgt')} — interprogram dataflow is "
                       "interproc_unknown (the callee is not analysed here)",
                origin_file=ln.origin_file, origin_line=ln.origin_line,
                expansion_stack=ln.expansion_stack,
            ))
    return ios, moves, deeper


def _split_move_targets(dst: str) -> List[str]:
    """Split a MOVE's target list (``MOVE a TO b c d``) into individual targets.

    Conservative: split on whitespace, keeping ``OF``/``IN`` qualified references
    intact (``b OF GRP``)."""
    tokens = dst.split()
    targets: List[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if i + 2 < len(tokens) and tokens[i + 1].upper() in ("OF", "IN"):
            targets.append(f"{tok} {tokens[i+1]} {tokens[i+2]}")
            i += 3
        else:
            targets.append(tok)
            i += 1
    return targets


def _normalise_operand(tok: str) -> str:
    """Normalise a MOVE operand to a canonical upper-cased field key.

    Drops a CORRESPONDING/CORR prefix, subscripts, and reference-modification;
    keeps an ``OF``/``IN`` qualifier folded to ``name`` (the qualified parent is
    provenance, not identity, in v1's conservative field model)."""
    t = tok.strip()
    t = re.sub(r"^(?:CORRESPONDING|CORR)\s+", "", t, flags=re.IGNORECASE)
    # Drop subscripts / reference-modification: NAME(1) / NAME(1:3).
    t = re.sub(r"\(.*?\)", "", t)
    # Keep only the leading qualified name (NAME OF GRP -> NAME).
    t = re.split(r"\bOF\b|\bIN\b", t, flags=re.IGNORECASE)[0]
    return t.strip().upper()


# ------------------------------------------------------------------------------
# The IR emitter (the lineage layer that produces ir.Edge / ir.GapNode)
# ------------------------------------------------------------------------------
def extract_cobol(
    lines: Sequence[CleanCobolLine],
    *,
    resolver_gaps: Optional[Sequence] = None,
    on_violation: str = "coerce",
) -> "ir.IR":
    """Extract lineage IR from a clean, COPY-expanded COBOL program (WP-6 entry).

    Parameters
    ----------
    lines : sequence of :class:`CleanCobolLine`
        The clean, COPY-expanded COBOL stream (from preprocess + copybook_resolver;
        see :func:`extract_cobol_resolve_result` / :func:`extract_cobol_file` for
        the convenience wrappers that build this).
    resolver_gaps : optional
        The WP-3 ``ResolveResult.gaps``. An ``unresolved_copy`` resolver gap is
        mapped to an ir ``gap_unresolved_copy`` contract gap; ``copy_cycle`` /
        ``copy_depth_exceeded`` diagnostics surface as an ``unresolved`` provenance
        note on the program (NOT a contract gap — the §5 set stays closed).
    on_violation : {"coerce", "reject"}
        Forwarded to :func:`ir.make_edge`.

    Emits (naming-contract §3 / §4):
      * a program job node ``mainframe://<program-id>`` (name ``<program-id>``);
      * for each ``SELECT file ASSIGN TO ddname``: a file node + a
        ``file -> program`` ``direct`` literal edge (``grounded``) carrying the
        ``ddname`` bind-key facet (the WP-8 stitch join key) + the record length
        (from the reused offset machinery) when the FD is known;
      * for each READ/START/DELETE: a ``file -> program`` ``direct`` direction edge
        (the program reads the file); for each WRITE/REWRITE: a
        ``program -> file`` ``direct`` direction edge (the program writes it);
      * for each ``MOVE a TO b``: an ``inferred``-kind field-flow edge (NEVER
        grounded — its ceiling is ``inferred``);
      * deeper-dataflow constructs (PERFORM/CALL/OCCURS-DEPENDING/...) are NOT
        emitted as grounded edges; they are honest diagnostics on the IR.

    The returned IR slice is canonical-sorted + deduped by canonical edge key
    (naming-contract §6) so it is byte-identical on re-run."""
    out = ir.IR()
    sec = _section_lines(lines)

    program_id = extract_program_id(sec.identification) or extract_program_id(lines)
    if program_id is None:
        program_id = "UNKNOWN-PROGRAM"  # honest placeholder, never invented as real
    ns_pgm = program_namespace(program_id)
    pgm_node = ir.make_node(ns_pgm, program_id, node_type="job")

    selects = extract_selects(sec.environment)
    file_records = extract_file_records(sec.data)

    # Map an FD file -> its record layout, and a record name -> its file (for the
    # WRITE/REWRITE <record> resolution).
    rec_by_file: Dict[str, FileRecord] = {fr.file: fr for fr in file_records}
    record_to_file: Dict[str, str] = {}
    for fr in file_records:
        for rn in fr.record_names:
            record_to_file.setdefault(rn, fr.file)

    # SELECT file -> ddname bind map (the JCL bridge).
    ddname_by_file: Dict[str, str] = {s.file: s.ddname for s in selects}

    def _file_node(file_name: str) -> "ir.Node":
        """Build the file node carrying the ddname bind key + record-length facet."""
        facets: Dict[str, str] = {"cobol_file": file_name}
        ddname = ddname_by_file.get(file_name)
        if ddname is not None:
            facets["ddname"] = ddname
        fr = rec_by_file.get(file_name)
        if fr is not None:
            if fr.record_length is not None:
                facets["record_length"] = str(fr.record_length)
            if fr.variable_length:
                facets["variable_length"] = "true"
                if fr.record_length_min is not None:
                    facets["record_length_min"] = str(fr.record_length_min)
                if fr.record_length_max is not None:
                    facets["record_length_max"] = str(fr.record_length_max)
            if fr.record_names:
                facets["record_names"] = ",".join(sorted(fr.record_names))
        return ir.make_node(FILE_NAMESPACE, file_name, facets=facets)

    # (a) SELECT...ASSIGN-TO -> a direct literal file->program binding (grounded);
    #     this is the COBOL-side join key for the WP-8 stitch (precision-win #1).
    for s in selects:
        file_node = _file_node(s.file)
        span = ir.SourceSpan(s.origin_file, s.origin_line)
        fr = rec_by_file.get(s.file)
        prov = ir.Provenance(
            parser="cobol",
            engine="stdlib",
            rule_id="cobol.select.assign_to",
            source_spans=[span],
            copybook_expansion_stack=list(s.expansion_stack),
            dialect="cobol",
            raw_tokens={"ddname": s.ddname, "cobol_file": s.file},
        )
        if fr is not None and fr.copybook_sourced:
            # A copybook-sourced record carries the FD's expansion-stack provenance.
            prov.copybook_expansion_stack = _merge_stacks(
                prov.copybook_expansion_stack, list(fr.expansion_stack)
            )
        edge = ir.make_edge(
            file_node, pgm_node,
            kind="direct", confidence="grounded", literal=True,
            provenance=prov, on_violation=on_violation,
        )
        out.add_edge(edge)

    # (b)+(c) READ/WRITE direction edges (file<->program). The record length comes
    #     from the reused offset machinery via the file node facet.
    ios, moves, deeper = extract_io_and_flow(sec.procedure, record_to_file)
    for io in ios:
        file_node = _file_node(io.file)
        span = ir.SourceSpan(io.origin_file, io.origin_line)
        fr = rec_by_file.get(io.file)
        # A READ/WRITE against a file with a KNOWN FD is a direct literal edge
        # (grounded). A verb against a file with no FD in this program is still a
        # direct edge but NOT literal -> it keeps the declared "inferred" (we lack
        # the record evidence), never silently grounded.
        literal = fr is not None
        confidence = "grounded" if literal else "inferred"
        prov = ir.Provenance(
            parser="cobol",
            engine="stdlib",
            rule_id=f"cobol.io.{io.verb.lower()}",
            source_spans=[span],
            copybook_expansion_stack=list(io.expansion_stack),
            dialect="cobol",
            raw_tokens={"verb": io.verb, "cobol_file": io.file, "direction": io.direction},
        )
        if io.direction == "read":
            edge = ir.make_edge(
                file_node, pgm_node,
                kind="direct", confidence=confidence, literal=literal,
                provenance=prov, on_violation=on_violation,
            )
        else:  # write
            edge = ir.make_edge(
                pgm_node, file_node,
                kind="direct", confidence=confidence, literal=literal,
                provenance=prov, on_violation=on_violation,
            )
        out.add_edge(edge)

    # (d) MOVE flow edges — conservative, ALWAYS inferred-kind (ceiling inferred;
    #     never grounded — a MOVE is structurally indirect dataflow, design §4/§8).
    for mv in moves:
        src_node = ir.make_node(_field_namespace(program_id), mv.src, node_type="dataset")
        dst_node = ir.make_node(_field_namespace(program_id), mv.dst, node_type="dataset")
        span = ir.SourceSpan(mv.origin_file, mv.origin_line)
        prov = ir.Provenance(
            parser="cobol",
            engine="stdlib",
            rule_id="cobol.move.flow",
            source_spans=[span],
            copybook_expansion_stack=list(mv.expansion_stack),
            dialect="cobol",
            raw_tokens={"src": mv.src, "dst": mv.dst},
        )
        edge = ir.make_edge(
            src_node, dst_node,
            kind="inferred", confidence="inferred",
            provenance=prov, on_violation=on_violation,
        )
        out.add_edge(edge)

    # Deeper-dataflow diagnostics -> a provenance note on the program node (not a
    # contract gap; the §5 closed set has no field-dataflow gap type in v1). We
    # surface them as an inferred->interproc_unknown self-note so they are visible
    # in the IR without inventing edges. We keep them in IR.nodes facets.
    if deeper:
        notes = sorted({f"{d.construct}: {d.detail}" for d in deeper})
        pgm_node.facets.setdefault("deeper_dataflow_diagnostics", " | ".join(notes))

    # Map WP-3 resolver gaps -> contract gaps / provenance notes.
    if resolver_gaps:
        _map_resolver_gaps(out, pgm_node, resolver_gaps)

    _canonical_sort_dedupe(out)
    return out


def _field_namespace(program_id: str) -> str:
    """The namespace for an intra-program COBOL field (MOVE flow endpoints).

    Fields are program-scoped (a MOVE between two fields is meaningful only inside
    the program), so the namespace is the program job namespace; the field name is
    the canonical upper-cased data-name."""
    return f"mainframe://{program_id}/field"


def _merge_stacks(a: List[str], b: List[str]) -> List[str]:
    """Merge two expansion stacks deterministically (outer order preserved, deduped
    while keeping the first occurrence). Used when a SELECT's file has a
    copybook-sourced FD record."""
    out: List[str] = []
    for s in list(a) + list(b):
        if s and s not in out:
            out.append(s)
    return out


def _map_resolver_gaps(out: "ir.IR", pgm_node: "ir.Node", resolver_gaps: Sequence) -> None:
    """Map WP-3 ResolveResult gaps onto the IR.

    ``unresolved_copy`` -> an ir ``gap_unresolved_copy`` contract gap (frozen §5).
    ``copy_cycle`` / ``copy_depth_exceeded`` -> an ``unresolved`` provenance note
    on the program node (internal diagnostics, NOT contract gaps — the §5 closed
    set stays frozen, per the WP-3 resolver contract)."""
    cr = _import_copybook_resolver()
    notes: List[str] = []
    for g in resolver_gaps:
        gtype = getattr(g, "type", None)
        member = getattr(g, "raw_copy_member", "") or ""
        if gtype == cr.GAP_UNRESOLVED_COPY:
            span = None
            gfile = getattr(g, "file", "") or ""
            gline = getattr(g, "line", 0) or 0
            if gfile:
                span = ir.SourceSpan(gfile, gline)
            out.add_gap(ir.gap_unresolved_copy(member, source_span=span))
        elif gtype in (cr.DIAG_COPY_CYCLE, cr.DIAG_COPY_DEPTH_EXCEEDED):
            notes.append(f"{gtype}: {member}".rstrip(": "))
    if notes:
        existing = pgm_node.facets.get("resolver_diagnostics", "")
        merged = sorted({n for n in (existing.split(" | ") if existing else []) + notes if n})
        pgm_node.facets["resolver_diagnostics"] = " | ".join(merged)


def _canonical_sort_dedupe(out: "ir.IR") -> None:
    """In-place canonical sort + dedupe of the IR's edges by canonical edge key
    (naming-contract §6 rule 2-4); gap nodes deduped + sorted; both deterministic.

    Duplicate edges (same canonical key) collapse to one with merged provenance.
    The WP-8 assembler re-applies the GLOBAL sort across all extractors; this keeps
    the extractor's own slice deterministic in isolation (and testable). Mirrors
    the WP-5 ``jcl_extract._canonical_sort_dedupe`` shape exactly."""
    by_key: Dict[Tuple[str, str, str], "ir.Edge"] = {}
    for e in out.edges:
        k = e.canonical_key
        if k in by_key:
            by_key[k].provenance.merge_from(e.provenance)
        else:
            by_key[k] = e
    out.edges = [by_key[k] for k in sorted(by_key)]

    def _gap_key(g: "ir.GapNode") -> Tuple[str, str]:
        raw = g.facets.get("raw_copy_member") or g.facets.get("raw_dsn") \
            or g.facets.get("raw_host_var") or ""
        return (g.gap_type, raw)

    seen_gaps: Dict[Tuple[str, str], "ir.GapNode"] = {}
    for g in out.gaps:
        seen_gaps.setdefault(_gap_key(g), g)
    out.gaps = [seen_gaps[k] for k in sorted(seen_gaps)]


# ------------------------------------------------------------------------------
# Convenience wrappers (build the CleanCobolLine stream from the pipeline)
# ------------------------------------------------------------------------------
def extract_cobol_resolve_result(rr, *, on_violation: str = "coerce") -> "ir.IR":
    """Extract IR from a copybook_resolver.ResolveResult (post-COPY-expansion).

    This is the in-pipeline entry: WP-2 preprocess + WP-3 copybook_resolver have
    already produced ``rr`` (the COPY-expanded clean stream + the resolver gaps);
    this maps it onto the CleanCobolLine stream and runs :func:`extract_cobol`."""
    lines = _lines_from_resolve_result(rr)
    return extract_cobol(lines, resolver_gaps=rr.gaps, on_violation=on_violation)


def extract_cobol_file(
    path,
    *,
    copybook_paths: Optional[Sequence] = None,
    on_violation: str = "coerce",
) -> "ir.IR":
    """Read + preprocess + COPY-resolve a COBOL file, then extract its IR.

    Composes WP-2 (preprocess) -> WP-3 (copybook_resolver) -> this extractor. The
    EXEC SQL was split out by preprocess BEFORE copybook expansion, so the resolver
    sees pure COBOL. Read-only; deterministic; no LLM, no network."""
    cr = _import_copybook_resolver()
    search = [Path(p) for p in (copybook_paths or [])]
    # INV-6: hash the RAW on-disk source bytes BEFORE copybook inline-expansion /
    # pre-symbol-substitution, no encoding normalization. The byte definition is
    # IDENTICAL to the lineage WP-9 facet so the v1.1 JOB<->artifact join holds.
    raw_bytes = Path(path).read_bytes()
    rr = cr.resolve_file(Path(path), search)
    out = extract_cobol_resolve_result(rr, on_violation=on_violation)
    ir.stamp_content_sha256(out, ir.content_sha256_of_bytes(raw_bytes),
                            source_file=str(path))
    return out


def extract_cobol_text(
    text: str,
    *,
    file: str = "",
    on_violation: str = "coerce",
) -> "ir.IR":
    """Extract IR from a raw COBOL source string (preprocess only, no COPY paths).

    Convenience for tests / inline source: runs WP-2 preprocess (fixed-format
    strip + EXEC SQL split + continuation fold) over the text, then extracts.
    COPY directives with no search path resolve to ``unresolved_copy`` gaps via the
    resolver path; use :func:`extract_cobol_file` when copybooks must be resolved."""
    pp = _import_preprocess()
    cr = _import_copybook_resolver()
    pre = pp.preprocess_source(text, file)  # preprocess_source(text, file_label)
    clean = [(cl.text, cl.origin.line) for cl in pre.clean_lines]
    rr = cr.resolve_copybooks(clean_lines=clean, source_file=file, search_paths=[])
    return extract_cobol_resolve_result(rr, on_violation=on_violation)


__all__ = [
    # namespaces
    "DSN_NAMESPACE",
    "FILE_NAMESPACE",
    "program_namespace",
    # dataclasses
    "CleanCobolLine",
    "SelectClause",
    "FileRecord",
    "IOAccess",
    "MoveFlow",
    "DeeperDataflow",
    # division extractors
    "extract_program_id",
    "extract_selects",
    "extract_file_records",
    "extract_io_and_flow",
    # the IR emitter + wrappers
    "extract_cobol",
    "extract_cobol_resolve_result",
    "extract_cobol_file",
    "extract_cobol_text",
]


# ------------------------------------------------------------------------------
# CLI (diagnostic — prints the emitted IR slice as a readable summary)
# ------------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog="cobol_extract.py",
        description=(
            "Deterministic COBOL lineage extractor (mainframe-lineage-parsers). "
            "Pure stdlib, no LLM, no network. Reuses structure-recovery "
            "cobol_offset_calc for the record machinery; emits SELECT/ASSIGN-TO, "
            "FD record, READ/WRITE direction, and conservative MOVE-flow IR edges."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("source", type=Path, help="COBOL source file")
    p.add_argument(
        "--copybook-path", action="append", default=[], metavar="DIR",
        help="copybook search directory (repeatable)",
    )
    args = p.parse_args(argv)

    out = extract_cobol_file(args.source, copybook_paths=args.copybook_path)
    print(f"program edges: {len(out.edges)}  gaps: {len(out.gaps)}")
    for e in out.edges:
        print(f"  {e.kind:18s} {e.confidence:11s} "
              f"{e.source.node_id}  ->  {e.target.node_id}  [{e.provenance.rule_id}]")
    for g in out.gaps:
        raw = g.facets.get("raw_copy_member") or g.facets.get("raw_dsn") or ""
        print(f"  GAP {g.gap_type:22s} {g.confidence:11s} {raw}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
