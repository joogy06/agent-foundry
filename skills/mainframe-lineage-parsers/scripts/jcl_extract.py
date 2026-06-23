#!/usr/bin/env python3
"""jcl_extract.py — the JCL extractor for ``mainframe-lineage-parsers`` (WP-5).

Part of the ``mainframe-lineage-parsers`` skill (the deterministic v1.1 plug-in
track under ``lineage-extract-static`` anti-pattern #7 — a *complement*, not a
replacement, of the LLM-as-parser family). This is the FIRST half of
precision-win edge class #1 (the JCL side):

    JCL DSN -> DDNAME (the bind key) -> step/pgm

The COBOL side (``SELECT file ASSIGN TO <ddname>`` -> FD record -> READ/WRITE)
is WP-6 (``cobol_extract.py``); the graph assembler (WP-8) stitches the two
halves together on the shared DDNAME so the physical-dataset-to-program-file
edge is connected end to end.

This module is **pure stdlib** — NO LLM, NO ``sqlglot``/``networkx``, NO new pip
deps, NO network, NO shell, NO runtime pip install (design D1). The deterministic
engine has no LLM in the loop, ever (C2). Everything this module emits flows
through :mod:`ir` (WP-4) and conforms BYTE-FOR-BYTE to the frozen
``references/naming-contract.md`` (WP-1, §2 / §4 / §5 / §6).

The language here is model-neutral. The extractor runs the same way regardless of
which CLI host invokes the engine (Claude Code, Codex CLI, Copilot CLI,
Antigravity CLI).

------------------------------------------------------------------------------
What it does (design §3 / §4, naming-contract §2 / §4)
------------------------------------------------------------------------------
Parses JCL — ``//name JOB``, ``//name EXEC``, ``//ddname DD`` statements — and:

  * resolves DDNAME -> DSN bindings (the DDNAME is the bind key, naming-contract
    §4);
  * expands PROCs (in-stream ``//name PROC ... //name PEND`` and cataloged via
    ``--jcl-proc-path``) and substitutes symbolic parameters (``&SYMBOL``)
    honouring override order: an EXEC-statement override beats a SET beats a PROC
    default (naming-contract §2 examples / design §4);
  * builds the JCL job identity per the naming contract:
        - namespace ``mainframe://<jobname>`` (case-folded, §6)
        - name ``<stepname>.<pgm>`` for a plain EXEC PGM=
        - name ``<stepname>.<procstep>.<pgm>`` for a program executed inside an
          expanded PROC step (PROC-step-qualified, §2);
  * emits IR edges DSN (dataset) -> step/pgm (job), with the DDNAME carried as a
    ``ddname`` provenance/raw facet (the bind key the WP-8 stitch joins on);
  * canonicalises physical DSNs (case-fold, GDG base + ``gdg_generation`` facet,
    §4);
  * for a DSN still holding an unresolved ``&SYMBOL`` after expansion, emits
    ``kind=unresolved`` -> forced ``confidence=speculative`` + a ``symbolic_dsn``
    gap node + the raw DSN as a ``raw_dsn`` facet (C3 — never an invented
    binding, naming-contract §4 / §5);
  * applies the canonical sort + dedupe by canonical edge key so output is
    byte-identical on re-run (naming-contract §6; the WP-8 assembler re-applies
    the global sort, but this extractor returns its own slice already sorted &
    deduped so it is deterministic in isolation and testable).

------------------------------------------------------------------------------
Edge direction convention
------------------------------------------------------------------------------
A DD statement's disposition tells us whether the step reads or writes the
dataset, but JCL DISP is not always reliable about read-vs-write intent (a
``DISP=SHR`` input and a ``DISP=(NEW,CATLG)`` output are clear, but ``DISP=MOD``
is ambiguous). The JCL side therefore emits a single ``dataset -> job`` *binding*
edge per (DSN, DDNAME, step) — the directionality (READ vs WRITE) is the COBOL
side's job (WP-6, from the ``READ``/``WRITE`` verbs against the SELECTed file).
The binding edge records the DISP as a facet so the assembler / downstream can
see it. ``kind=direct`` for a literal resolved DSN (forced ``grounded`` when the
token is literal); ``kind=unresolved`` for a symbolic DSN (forced
``speculative``).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ------------------------------------------------------------------------------
# Path-load the sibling IR module (WP-4) — keep the extractor runnable from any
# tree slice / CWD, matching the sibling convention (register in sys.modules
# BEFORE exec so dataclass annotation resolution under
# ``from __future__ import annotations`` succeeds on 3.12).
# ------------------------------------------------------------------------------
def _import_ir():
    name = "mlp_ir"
    if name in sys.modules:
        return sys.modules[name]
    target = Path(__file__).resolve().parent / "ir.py"
    spec = importlib.util.spec_from_file_location(name, target)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load ir.py from {target}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ir = _import_ir()


# ------------------------------------------------------------------------------
# Namespaces (naming-contract §2 / §4)
# ------------------------------------------------------------------------------
DSN_NAMESPACE = "mainframe://DSN"


def job_namespace(jobname: str) -> str:
    """``mainframe://<jobname>`` (jobname already case-folded, §6)."""
    return f"mainframe://{jobname}"


# ------------------------------------------------------------------------------
# Symbolic-parameter detection (naming-contract §4 rule 3)
# ------------------------------------------------------------------------------
# An unresolved JCL symbolic parameter after expansion: a leading ``&`` followed
# by a symbol name (letters/digits/#/@/$). ``&&`` is a temp-dataset marker, not a
# symbol, and is NOT treated as unresolved.
_SYMBOL_RE = re.compile(r"&[A-Z#@$][A-Z0-9#@$]*", re.IGNORECASE)
_TEMP_DSN_RE = re.compile(r"&&[A-Z#@$][A-Z0-9#@$]*", re.IGNORECASE)

# A symbol reference for substitution (used during expansion). JCL symbols can be
# delimited by a trailing ``.`` (``&HLQ..NEXT`` -> the ``.`` after the symbol is
# the delimiter and is consumed, leaving a literal ``.`` before NEXT). We capture
# the symbol name and whether a delimiter dot followed it.
_SYMBOL_SUB_RE = re.compile(r"&([A-Z#@$][A-Z0-9#@$]*)(\.?)", re.IGNORECASE)


def has_unresolved_symbol(text: str) -> bool:
    """True if ``text`` still contains an unresolved ``&SYMBOL`` (ignoring the
    ``&&temp`` temp-dataset marker). Used after expansion to decide symbolic_dsn."""
    # Remove temp markers first so ``&&TEMP`` does not count as a symbol.
    scrubbed = _TEMP_DSN_RE.sub("", text)
    return bool(_SYMBOL_RE.search(scrubbed))


def substitute_symbols(text: str, symbols: Dict[str, str]) -> str:
    """Substitute ``&SYMBOL`` references in ``text`` from the ``symbols`` map.

    JCL symbol substitution rules honoured:
      * ``&NAME`` is replaced by its value; a trailing ``.`` immediately after the
        symbol is the symbol *delimiter* and is consumed (``&HLQ..X`` with
        HLQ=PROD -> ``PROD.X``: the first ``.`` is the delimiter, the second is a
        literal dot).
      * ``&&`` (temp dataset) is left untouched.
      * an unknown symbol is left as-is (so :func:`has_unresolved_symbol` can flag
        it -> symbolic_dsn). It is NOT invented (C3).

    Deterministic; case-insensitive symbol names are folded to upper for lookup
    (JCL symbol names are case-insensitive)."""
    # Protect temp-dataset markers from the single-& substitution.
    sentinel = "\x00\x00TEMP\x00\x00"
    temp_markers: List[str] = []

    def _protect(m: "re.Match[str]") -> str:
        temp_markers.append(m.group(0))
        return f"{sentinel}{len(temp_markers) - 1}{sentinel}"

    protected = _TEMP_DSN_RE.sub(_protect, text)

    def _sub(m: "re.Match[str]") -> str:
        sym = m.group(1).upper()
        delim = m.group(2)  # "" or "."
        if sym in symbols:
            # Symbol resolved: substitute value; the delimiter dot is consumed.
            return symbols[sym]
        # Unknown symbol: leave the original token verbatim (not invented).
        return m.group(0)

    out = _SYMBOL_SUB_RE.sub(_sub, protected)

    # Restore temp markers.
    def _restore(m: "re.Match[str]") -> str:
        return temp_markers[int(m.group(1))]

    out = re.sub(re.escape(sentinel) + r"(\d+)" + re.escape(sentinel), _restore, out)
    return out


# ------------------------------------------------------------------------------
# DSN canonicalisation (naming-contract §4 rule 1 / 2)
# ------------------------------------------------------------------------------
# A GDG relative generation suffix: ``(+1)`` / ``(0)`` / ``(-1)`` etc.
_GDG_RE = re.compile(r"^(?P<base>.+?)\((?P<gen>[+-]?\d+)\)$")
# A member reference: ``PDS.LIB(MEMBER)`` — member is NOT a generation number.
_MEMBER_RE = re.compile(r"^(?P<base>.+?)\((?P<member>[A-Z#@$][A-Z0-9#@$]*)\)$", re.IGNORECASE)


@dataclass(frozen=True)
class CanonicalDSN:
    """The result of canonicalising a physical DSN (naming-contract §4)."""

    name: str                              # canonical DSN node name (base, upper)
    gdg_generation: Optional[str] = None   # "+1" / "0" / "-1" ... (facet, not in id)
    member: Optional[str] = None           # PDS member (facet, not in id)
    raw: str = ""                          # the raw DSN as supplied (facet)


def canonicalise_dsn(raw_dsn: str) -> CanonicalDSN:
    """Canonicalise a physical DSN per naming-contract §4.

    1. case-fold to upper;
    2. a GDG relative generation ``BASE(+1)`` -> name ``BASE`` + ``gdg_generation``
       facet ``+1`` (the generation is NOT folded into the name);
    3. a PDS member ``LIB(MEMBER)`` -> name ``LIB`` + ``member`` facet ``MEMBER``;
    4. otherwise the upper-cased DSN is the name.

    The raw value is always retained. (Symbolic detection is done by the caller
    BEFORE canonicalisation — a still-symbolic DSN is a gap, not a node here.)"""
    raw = raw_dsn.strip()
    folded = raw.upper()
    m = _GDG_RE.match(folded)
    if m:
        return CanonicalDSN(name=m.group("base"), gdg_generation=m.group("gen"), raw=raw)
    m = _MEMBER_RE.match(folded)
    if m:
        return CanonicalDSN(name=m.group("base"), member=m.group("member"), raw=raw)
    return CanonicalDSN(name=folded, raw=raw)


# ------------------------------------------------------------------------------
# JCL statement model
# ------------------------------------------------------------------------------
@dataclass
class JclStatement:
    """A logical JCL statement (continuations already joined).

    ``label`` is the name field (after ``//``), ``operation`` is JOB/EXEC/DD/
    PROC/PEND/SET/INCLUDE etc., ``operand`` is the raw operand text, ``params`` is
    the parsed keyword/positional operand map, and ``line`` is the 1-indexed line
    of the statement start in the (source) file."""

    label: str
    operation: str
    operand: str
    params: Dict[str, str]
    positionals: List[str]
    line: int
    file: str = ""


# A JCL statement line starts with ``//`` (or ``//*`` comment, or ``/*``
# delimiter). The label may be empty (a continuation-target or unnamed DD).
_JCL_STMT_RE = re.compile(r"^//(?P<label>[A-Z0-9#@$]*)\s+(?P<rest>.*)$", re.IGNORECASE)
_JCL_COMMENT_RE = re.compile(r"^//\*")
_JCL_DELIM_RE = re.compile(r"^/\*")  # in-stream data delimiter / null


def _strip_inline_comment(operand_region: str) -> str:
    """Strip a trailing inline comment from a JCL operand region.

    A JCL comment begins after the operand with whitespace then text that is not a
    continuation. We conservatively cut at the first run of whitespace that is
    followed by a non-operand word AND there is no trailing comma (continuations
    end with a comma). To stay deterministic and avoid corrupting operands, we
    only strip when there is a clear ``  <space> word`` after a complete operand
    (no unbalanced parens). The common safe case: ``PGM=IEFBR14   RUN STEP``."""
    # Walk respecting parentheses and quotes; the operand ends at the first
    # top-level whitespace that is not inside parens/quotes.
    depth = 0
    in_quote = False
    end = len(operand_region)
    for i, ch in enumerate(operand_region):
        if ch == "'":
            in_quote = not in_quote
        elif not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif ch.isspace() and depth == 0:
                end = i
                break
    return operand_region[:end]


def _is_continuation(prev_operand: str) -> bool:
    """A JCL statement continues when its operand field ends with a comma (after
    stripping any inline comment)."""
    return prev_operand.rstrip().endswith(",")


def split_logical_statements(text: str, *, file: str = "") -> List[JclStatement]:
    """Split raw JCL text into logical statements (continuations joined).

    Honours: ``//`` statement lines, ``//*`` comments (dropped), ``/*`` delimiter
    (drops in-stream data following a ``DD *``/``DD DATA`` — conservatively we just
    drop ``/*`` and ``//`` -less data lines), and comma-continuation across lines.
    Deterministic, pure stdlib."""
    statements: List[JclStatement] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        raw_line = lines[i]
        lineno = i + 1
        if _JCL_COMMENT_RE.match(raw_line):
            i += 1
            continue
        if _JCL_DELIM_RE.match(raw_line):
            i += 1
            continue
        m = _JCL_STMT_RE.match(raw_line)
        if not m:
            # An in-stream data line (no leading //) — skip (we do not model
            # SYSIN data content for lineage).
            i += 1
            continue
        label = m.group("label").upper()
        rest = m.group("rest").rstrip()
        # operation is the first token; the remainder is the operand.
        parts = rest.split(None, 1)
        operation = parts[0].upper() if parts else ""
        operand_region = parts[1] if len(parts) > 1 else ""
        operand = _strip_inline_comment(operand_region)
        start_line = lineno
        # Join continuation lines.
        while _is_continuation(operand) and (i + 1) < n:
            i += 1
            cont_raw = lines[i]
            cm = _JCL_STMT_RE.match(cont_raw)
            if cm is None:
                # A non-// continuation is malformed; stop joining.
                break
            cont_rest = cm.group("rest").strip()
            cont_operand = _strip_inline_comment(cont_rest)
            operand = operand.rstrip()
            # Drop the trailing comma's whitespace then append the continuation.
            operand = operand + cont_operand
        params, positionals = parse_operand(operand)
        statements.append(
            JclStatement(
                label=label,
                operation=operation,
                operand=operand,
                params=params,
                positionals=positionals,
                line=start_line,
                file=file,
            )
        )
        i += 1
    return statements


def parse_operand(operand: str) -> Tuple[Dict[str, str], List[str]]:
    """Parse a JCL operand field into a keyword map + positional list.

    Splits on top-level commas (respecting parens + quotes), then each item is
    either ``KEY=VALUE`` (keyword, key upper-cased) or a positional. Keyword keys
    are upper-cased; values are kept verbatim (case handled per-rule downstream).
    Deterministic, pure stdlib."""
    params: Dict[str, str] = {}
    positionals: List[str] = []
    for item in _split_top_level_commas(operand):
        item = item.strip()
        if not item:
            continue
        eq = _top_level_eq_index(item)
        if eq >= 0:
            key = item[:eq].strip().upper()
            val = item[eq + 1:].strip()
            params[key] = val
        else:
            positionals.append(item)
    return params, positionals


def _split_top_level_commas(s: str) -> List[str]:
    out: List[str] = []
    depth = 0
    in_quote = False
    cur: List[str] = []
    for ch in s:
        if ch == "'":
            in_quote = not in_quote
            cur.append(ch)
        elif ch == "," and depth == 0 and not in_quote:
            out.append("".join(cur))
            cur = []
        else:
            if not in_quote:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth = max(0, depth - 1)
            cur.append(ch)
    out.append("".join(cur))
    return out


def _top_level_eq_index(s: str) -> int:
    """Index of the first top-level ``=`` (not inside parens/quotes), else -1."""
    depth = 0
    in_quote = False
    for i, ch in enumerate(s):
        if ch == "'":
            in_quote = not in_quote
        elif not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif ch == "=" and depth == 0:
                return i
    return -1


def _unquote(val: str) -> str:
    """Strip surrounding JCL quotes from a value (``'A B'`` -> ``A B``)."""
    v = val.strip()
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


# ------------------------------------------------------------------------------
# PROC library / catalog
# ------------------------------------------------------------------------------
def _load_proc_libs(proc_paths: Optional[List[str]]) -> Dict[str, str]:
    """Load cataloged PROC members from ``--jcl-proc-path`` dirs.

    Returns a map of upper-cased PROC member name -> raw PROC text. A member name
    is the file stem (upper-cased); ``.jcl`` / ``.proc`` / no-extension are all
    accepted. Deterministic ordering (sorted dirs, sorted files) so a later
    duplicate name does not non-deterministically win — first-seen (lexicographic)
    wins and is the documented rule."""
    libs: Dict[str, str] = {}
    if not proc_paths:
        return libs
    for d in sorted(proc_paths):
        p = Path(d)
        if not p.is_dir():
            continue
        for f in sorted(p.iterdir()):
            if not f.is_file():
                continue
            stem = f.stem.upper()
            if stem in libs:
                continue  # first-seen (lexicographic) wins, deterministic
            try:
                libs[stem] = f.read_text(encoding="utf-8", errors="replace")
            except OSError:  # pragma: no cover - defensive
                continue
    return libs


# ------------------------------------------------------------------------------
# In-stream PROC extraction
# ------------------------------------------------------------------------------
def _extract_instream_procs(
    statements: List[JclStatement],
) -> Tuple[Dict[str, List[JclStatement]], List[JclStatement]]:
    """Split out in-stream PROCs (``//NAME PROC`` ... ``// PEND``) from the main
    statement stream.

    Returns ``(instream_procs, main_statements)`` where ``instream_procs`` maps
    upper PROC name -> its body statements (the PROC statement itself included as
    the first element, for its default symbols)."""
    instream: Dict[str, List[JclStatement]] = {}
    main: List[JclStatement] = []
    i = 0
    n = len(statements)
    while i < n:
        st = statements[i]
        if st.operation == "PROC" and st.label:
            body = [st]
            i += 1
            while i < n and statements[i].operation != "PEND":
                body.append(statements[i])
                i += 1
            # consume the PEND (if present)
            if i < n and statements[i].operation == "PEND":
                i += 1
            instream[st.label.upper()] = body
        else:
            main.append(st)
            i += 1
    return instream, main


# ------------------------------------------------------------------------------
# Resolved-step model (after PROC expansion)
# ------------------------------------------------------------------------------
@dataclass
class ResolvedDD:
    ddname: str
    raw_dsn: Optional[str]          # the DSN operand AFTER symbol substitution (None if no DSN=)
    disp: str = ""
    is_symbolic: bool = False       # still holds an unresolved &SYMBOL after expansion
    is_temp: bool = False           # &&temp dataset (no lineage edge)
    line: int = 0
    file: str = ""


@dataclass
class ResolvedStep:
    """A job step after PROC expansion.

    ``stepname`` is the job-level step label; ``procstep`` is the PROC-internal
    step name when the program ran inside an expanded PROC step (else None);
    ``pgm`` is the resolved ``PGM=``. ``dds`` are the DD statements for that
    (possibly PROC-internal) step, with EXEC-level DD overrides applied."""

    stepname: str
    pgm: Optional[str]
    procstep: Optional[str]
    dds: List[ResolvedDD] = field(default_factory=list)
    line: int = 0
    file: str = ""


def _parse_set_symbols(statements: List[JclStatement]) -> Dict[str, str]:
    """Collect symbols from job-level ``// SET A=1,B=2`` statements (override
    order: a later SET of the same symbol wins; SET beats PROC default; EXEC
    override beats SET — applied at expansion time)."""
    symbols: Dict[str, str] = {}
    for st in statements:
        if st.operation == "SET":
            for k, v in st.params.items():
                symbols[k.upper()] = _unquote(v)
    return symbols


def _proc_default_symbols(proc_stmt: JclStatement) -> Dict[str, str]:
    """The default symbol values declared on a ``//NAME PROC A=1,B=2`` statement."""
    out: Dict[str, str] = {}
    for k, v in proc_stmt.params.items():
        out[k.upper()] = _unquote(v)
    return out


def _exec_override_symbols(exec_stmt: JclStatement) -> Dict[str, str]:
    """Symbol overrides supplied on the EXEC that invoked a PROC.

    On ``//STEP EXEC PROC=LOADPRC,HLQ=PROD,QUAL=TEST`` the non-reserved keywords
    (everything except PGM/PROC) are symbol overrides for the invoked PROC."""
    reserved = {"PGM", "PROC", "COND", "PARM", "REGION", "TIME", "ADDRSPC",
                "DYNAMNBR", "ACCT", "PERFORM", "RD", "DPRTY"}
    out: Dict[str, str] = {}
    for k, v in exec_stmt.params.items():
        ku = k.upper()
        if ku in reserved:
            continue
        out[ku] = _unquote(v)
    return out


def _build_dd(st: JclStatement, symbols: Dict[str, str]) -> Optional[ResolvedDD]:
    """Build a :class:`ResolvedDD` from a DD statement, substituting symbols into
    the DSN. Returns None for a DD with no DSN= (e.g. ``DD SYSOUT=*`` — no
    dataset lineage)."""
    if "DSN" not in st.params and "DSNAME" not in st.params:
        return None
    raw_dsn_field = st.params.get("DSN", st.params.get("DSNAME", ""))
    raw_dsn_field = _unquote(raw_dsn_field)
    substituted = substitute_symbols(raw_dsn_field, symbols)
    is_temp = substituted.strip().startswith("&&")
    is_symbolic = has_unresolved_symbol(substituted)
    disp = _unquote(st.params.get("DISP", ""))
    return ResolvedDD(
        ddname=st.label.upper(),
        raw_dsn=substituted,
        disp=disp,
        is_symbolic=is_symbolic,
        is_temp=is_temp,
        line=st.line,
        file=st.file,
    )


def _merge_dd_overrides(
    base_dds: Dict[str, ResolvedDD], override_dds: List[ResolvedDD]
) -> List[ResolvedDD]:
    """Apply EXEC-level DD overrides to a PROC step's DDs.

    A job-level ``//STEP.PROCSTEP.DDNAME DD ...`` override (modelled here as a DD
    keyed by ddname) replaces the PROC's DD of the same ddname; new ddnames are
    added. Deterministic: result sorted by ddname."""
    merged: Dict[str, ResolvedDD] = dict(base_dds)
    for od in override_dds:
        merged[od.ddname] = od
    return [merged[k] for k in sorted(merged)]


def resolve_steps(
    text: str,
    *,
    file: str = "",
    proc_paths: Optional[List[str]] = None,
) -> Tuple[str, List[ResolvedStep]]:
    """Parse a JCL job and resolve its steps (PROC expansion + symbol substitution).

    Returns ``(jobname, steps)`` where ``jobname`` is the case-folded JOB name
    (or ``"<jobname>"`` if no JOB card was found) and ``steps`` is the ordered
    list of :class:`ResolvedStep`. Override order honoured: EXEC override > SET >
    PROC default (naming-contract §2)."""
    statements = split_logical_statements(text, file=file)
    instream_procs, main_stmts = _extract_instream_procs(statements)
    cataloged = _load_proc_libs(proc_paths)

    # Job name.
    jobname = "<jobname>"
    for st in main_stmts:
        if st.operation == "JOB" and st.label:
            jobname = st.label.upper()
            break

    job_set_symbols = _parse_set_symbols(main_stmts)

    steps: List[ResolvedStep] = []
    i = 0
    n = len(main_stmts)
    while i < n:
        st = main_stmts[i]
        if st.operation != "EXEC":
            i += 1
            continue
        stepname = st.label.upper() if st.label else f"STEP{len(steps) + 1:03d}"
        pgm = st.params.get("PGM")
        proc_name = st.params.get("PROC")
        # Some shops write ``EXEC LOADPRC`` (positional PROC name).
        if pgm is None and proc_name is None and st.positionals:
            cand = st.positionals[0].strip().upper()
            if cand and cand != "PGM":
                proc_name = cand
        if pgm is not None:
            pgm = _unquote(pgm).upper()

        # Collect the EXEC-step's own DD overrides (the DDs immediately following
        # the EXEC, until the next EXEC). These may be plain DDs (for a PGM= step)
        # OR ``PROCSTEP.DDNAME`` overrides (for a PROC step).
        j = i + 1
        step_dds_raw: List[JclStatement] = []
        while j < n and main_stmts[j].operation != "EXEC":
            if main_stmts[j].operation == "DD":
                step_dds_raw.append(main_stmts[j])
            j += 1

        if proc_name is not None:
            proc_name = _unquote(proc_name).upper()
            override_syms = _exec_override_symbols(st)
            proc_body = instream_procs.get(proc_name)
            if proc_body is None and proc_name in cataloged:
                proc_body = split_logical_statements(
                    cataloged[proc_name], file=f"PROCLIB({proc_name})"
                )
            if proc_body is None:
                # PROC not found on any path: emit a step whose pgm is unresolved.
                # Its DDs (if the EXEC carried plain DDs) still bind, but the PROC
                # body is missing -> we record a step with pgm=None (the assembler
                # / report can flag the missing PROC). We DON'T invent it.
                steps.append(
                    ResolvedStep(
                        stepname=stepname,
                        pgm=None,
                        procstep=None,
                        dds=_resolve_plain_dds(step_dds_raw, job_set_symbols, override_syms),
                        line=st.line,
                        file=st.file,
                    )
                )
                i = j
                continue
            steps.extend(
                _expand_proc(
                    proc_name=proc_name,
                    proc_body=proc_body,
                    stepname=stepname,
                    job_set_symbols=job_set_symbols,
                    exec_override_symbols=override_syms,
                    exec_dd_overrides=step_dds_raw,
                    exec_line=st.line,
                    exec_file=st.file,
                )
            )
            i = j
            continue

        # Plain PGM= step.
        dds = _resolve_plain_dds(step_dds_raw, job_set_symbols, {})
        steps.append(
            ResolvedStep(
                stepname=stepname,
                pgm=pgm,
                procstep=None,
                dds=dds,
                line=st.line,
                file=st.file,
            )
        )
        i = j

    return jobname, steps


def _resolve_plain_dds(
    dd_stmts: List[JclStatement],
    job_set_symbols: Dict[str, str],
    extra_symbols: Dict[str, str],
) -> List[ResolvedDD]:
    """Resolve a plain (non-PROC) step's DDs. Symbol precedence: SET then any
    extra (EXEC) symbols (extra wins)."""
    symbols = dict(job_set_symbols)
    symbols.update(extra_symbols)
    out: List[ResolvedDD] = []
    for st in dd_stmts:
        dd = _build_dd(st, symbols)
        if dd is not None:
            out.append(dd)
    # deterministic order
    return sorted(out, key=lambda d: (d.ddname, d.raw_dsn or ""))


def _expand_proc(
    *,
    proc_name: str,
    proc_body: List[JclStatement],
    stepname: str,
    job_set_symbols: Dict[str, str],
    exec_override_symbols: Dict[str, str],
    exec_dd_overrides: List[JclStatement],
    exec_line: int,
    exec_file: str,
) -> List[ResolvedStep]:
    """Expand one PROC invocation into its constituent PROC steps.

    Symbol precedence (naming-contract §2): EXEC override > job SET > PROC default.
    DD overrides keyed ``PROCSTEP.DDNAME`` on the EXEC step are applied to the
    matching PROC step; a bare ``DDNAME`` override (no procstep) applies to the
    PROC's first step (the common single-step PROC convention)."""
    # 1. PROC statement is body[0]; its params are the PROC defaults.
    proc_stmt = proc_body[0]
    proc_defaults = _proc_default_symbols(proc_stmt) if proc_stmt.operation == "PROC" else {}

    # symbol map: PROC default < job SET < EXEC override
    symbols: Dict[str, str] = {}
    symbols.update(proc_defaults)
    symbols.update(job_set_symbols)
    symbols.update(exec_override_symbols)

    # 2. Partition the EXEC's DD overrides into per-procstep buckets.
    #    A ``PROCSTEP.DDNAME`` override label has a dot; a bare ``DDNAME`` has none.
    overrides_by_procstep: Dict[str, List[JclStatement]] = {}
    bare_overrides: List[JclStatement] = []
    for od in exec_dd_overrides:
        if "." in od.label:
            ps, _, dd = od.label.partition(".")
            cloned = JclStatement(
                label=dd.upper(),
                operation=od.operation,
                operand=od.operand,
                params=od.params,
                positionals=od.positionals,
                line=od.line,
                file=od.file,
            )
            overrides_by_procstep.setdefault(ps.upper(), []).append(cloned)
        else:
            bare_overrides.append(od)

    # 3. Walk the PROC body's EXEC steps.
    steps: List[ResolvedStep] = []
    body = proc_body[1:] if proc_stmt.operation == "PROC" else proc_body
    i = 0
    n = len(body)
    first_proc_step = True
    while i < n:
        st = body[i]
        if st.operation != "EXEC":
            i += 1
            continue
        procstep = st.label.upper() if st.label else f"STEP{len(steps) + 1:03d}"
        pgm = st.params.get("PGM")
        if pgm is not None:
            pgm = _unquote(pgm).upper()
        # PROC steps may themselves invoke nested PROCs; v1 does not recurse PROC-
        # in-PROC (a documented non-goal — emit pgm as-resolved or None).
        # Collect this PROC step's DDs.
        j = i + 1
        proc_step_dds: List[JclStatement] = []
        while j < n and body[j].operation != "EXEC":
            if body[j].operation == "DD":
                proc_step_dds.append(body[j])
            j += 1

        base_dds: Dict[str, ResolvedDD] = {}
        for dst in proc_step_dds:
            dd = _build_dd(dst, symbols)
            if dd is not None:
                base_dds[dd.ddname] = dd

        # Apply overrides for this procstep.
        ov_stmts = list(overrides_by_procstep.get(procstep, []))
        if first_proc_step:
            ov_stmts = bare_overrides + ov_stmts  # bare overrides hit the first step
        override_dds: List[ResolvedDD] = []
        for ost in ov_stmts:
            dd = _build_dd(ost, symbols)
            if dd is not None:
                override_dds.append(dd)

        merged = _merge_dd_overrides(base_dds, override_dds)
        steps.append(
            ResolvedStep(
                stepname=stepname,
                pgm=pgm,
                procstep=procstep,
                dds=merged,
                line=st.line,
                file=st.file,
            )
        )
        first_proc_step = False
        i = j

    return steps


# ------------------------------------------------------------------------------
# IR emission (naming-contract §2 / §4 / §5 / §6)
# ------------------------------------------------------------------------------
def _job_node_name(step: ResolvedStep) -> str:
    """The job-identity name per naming-contract §2:
      * ``<stepname>.<pgm>`` for a plain EXEC PGM=
      * ``<stepname>.<procstep>.<pgm>`` for a PROC-step-qualified program."""
    pgm = step.pgm if step.pgm else "<pgm>"
    if step.procstep:
        return f"{step.stepname}.{step.procstep}.{pgm}"
    return f"{step.stepname}.{pgm}"


def extract_jcl(
    text: str,
    *,
    file: str = "",
    proc_paths: Optional[List[str]] = None,
    on_violation: str = "coerce",
) -> "ir.IR":
    """Extract lineage IR from a JCL job (the WP-5 public entry point).

    Parses + resolves the job (PROC expansion, symbol substitution), then emits,
    for every DD with a DSN:

      * a DSN dataset node (``mainframe://DSN`` + canonical name; GDG generation /
        PDS member / DISP / raw DSN / ddname carried as facets);
      * a job/step node (``mainframe://<jobname>`` + ``<stepname>[.<procstep>].<pgm>``);
      * a ``dataset -> job`` binding edge with ``kind=direct`` (forced
        ``grounded`` — literal resolved DSN) and the DDNAME as the bind-key facet.

    A still-symbolic DSN (unresolved ``&SYMBOL`` after expansion) emits instead:
      * ``kind=unresolved`` -> forced ``confidence=speculative``;
      * a ``symbolic_dsn`` gap node carrying ``raw_dsn``;
      * the edge still records the DDNAME bind key (so the assembler can see the
        attempted binding) but is honestly speculative — never an invented DSN.

    The returned IR slice is canonical-sorted + deduped by canonical edge key
    (naming-contract §6) so it is byte-identical on re-run."""
    jobname, steps = resolve_steps(text, file=file, proc_paths=proc_paths)
    out = ir.IR()
    ns_job = job_namespace(jobname)

    for step in steps:
        job_name = _job_node_name(step)
        job_node = ir.make_node(ns_job, job_name, node_type="job")
        for dd in step.dds:
            if dd.raw_dsn is None or dd.is_temp:
                # No DSN / temp dataset -> no physical-dataset lineage edge.
                continue
            span = ir.SourceSpan(dd.file or file, dd.line)
            if dd.is_symbolic:
                # C3: never an invented binding. Symbolic DSN -> gap + speculative.
                out.add_gap(
                    ir.gap_symbolic_dsn(dd.raw_dsn, source_span=span)
                )
                # Emit an unresolved edge so the attempted DSN->job binding is
                # visible (DDNAME bind key preserved), forced speculative.
                sym_node = ir.make_node(
                    DSN_NAMESPACE,
                    "<symbolic_dsn>",
                    facets={"raw_dsn": dd.raw_dsn, "ddname": dd.ddname},
                )
                prov = ir.Provenance(
                    parser="jcl",
                    engine="stdlib",
                    rule_id="jcl.dd.symbolic_dsn",
                    source_spans=[span],
                    dialect="jcl",
                    unresolved_deps=[dd.raw_dsn],
                    raw_tokens={"raw_dsn": dd.raw_dsn, "ddname": dd.ddname, "disp": dd.disp},
                )
                edge = ir.make_edge(
                    sym_node,
                    job_node,
                    kind="unresolved",
                    confidence="speculative",
                    symbolic=True,
                    provenance=prov,
                    on_violation=on_violation,
                )
                out.add_edge(edge)
                continue

            canon = canonicalise_dsn(dd.raw_dsn)
            ds_facets: Dict[str, str] = {"raw_dsn": canon.raw, "ddname": dd.ddname}
            if canon.gdg_generation is not None:
                ds_facets["gdg_generation"] = canon.gdg_generation
            if canon.member is not None:
                ds_facets["member"] = canon.member
            ds_node = ir.make_node(DSN_NAMESPACE, canon.name, facets=ds_facets)
            raw_tokens: Dict[str, str] = {
                "raw_dsn": canon.raw,
                "ddname": dd.ddname,
                "disp": dd.disp,
            }
            if canon.gdg_generation is not None:
                raw_tokens["gdg_generation"] = canon.gdg_generation
            if canon.member is not None:
                raw_tokens["member"] = canon.member
            prov = ir.Provenance(
                parser="jcl",
                engine="stdlib",
                rule_id="jcl.dd.dsn_bind",
                source_spans=[span],
                dialect="jcl",
                raw_tokens=raw_tokens,
            )
            edge = ir.make_edge(
                ds_node,
                job_node,
                kind="direct",
                confidence="grounded",
                literal=True,
                provenance=prov,
                on_violation=on_violation,
            )
            out.add_edge(edge)

    _canonical_sort_dedupe(out)
    return out


def _canonical_sort_dedupe(out: "ir.IR") -> None:
    """In-place canonical sort + dedupe of the IR's edges by canonical edge key
    (naming-contract §6 rule 2-4); gap nodes deduped + sorted; both deterministic.

    Duplicate edges (same canonical key) collapse to one with merged provenance.
    The WP-8 assembler re-applies the GLOBAL sort across all extractors; this
    keeps the extractor's own slice deterministic in isolation (and testable)."""
    # Dedupe edges by canonical key, merging provenance.
    by_key: Dict[Tuple[str, str, str], "ir.Edge"] = {}
    for e in out.edges:
        k = e.canonical_key
        if k in by_key:
            by_key[k].provenance.merge_from(e.provenance)
        else:
            by_key[k] = e
    out.edges = [by_key[k] for k in sorted(by_key)]

    # Dedupe + sort gap nodes deterministically (by type + raw evidence).
    def _gap_key(g: "ir.GapNode") -> Tuple[str, str]:
        raw = g.facets.get("raw_dsn") or g.facets.get("raw_copy_member") \
            or g.facets.get("raw_host_var") or ""
        return (g.gap_type, raw)

    seen_gaps: Dict[Tuple[str, str], "ir.GapNode"] = {}
    for g in out.gaps:
        seen_gaps.setdefault(_gap_key(g), g)
    out.gaps = [seen_gaps[k] for k in sorted(seen_gaps)]


# ------------------------------------------------------------------------------
# Convenience: extract from a file path
# ------------------------------------------------------------------------------
def extract_jcl_file(
    path: str,
    *,
    proc_paths: Optional[List[str]] = None,
    on_violation: str = "coerce",
) -> "ir.IR":
    """Read a JCL file from disk and extract its IR. Read-only; deterministic."""
    p = Path(path)
    raw_bytes = p.read_bytes()  # RAW on-disk bytes, PRE-symbol-substitution (INV-6)
    text = raw_bytes.decode("utf-8", errors="replace")
    out = extract_jcl(text, file=str(p), proc_paths=proc_paths, on_violation=on_violation)
    ir.stamp_content_sha256(out, ir.content_sha256_of_bytes(raw_bytes), source_file=str(p))
    return out


__all__ = [
    "DSN_NAMESPACE",
    "job_namespace",
    "has_unresolved_symbol",
    "substitute_symbols",
    "CanonicalDSN",
    "canonicalise_dsn",
    "JclStatement",
    "split_logical_statements",
    "parse_operand",
    "ResolvedDD",
    "ResolvedStep",
    "resolve_steps",
    "extract_jcl",
    "extract_jcl_file",
]
