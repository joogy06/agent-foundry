#!/usr/bin/env python3
"""sql_extract.py — the embedded-``EXEC SQL`` (DB2) extractor for
``mainframe-lineage-parsers`` (WP-7, precision-win edge class #2).

Part of the ``mainframe-lineage-parsers`` skill — the deterministic v1.1 plug-in
track under ``lineage-extract-static`` anti-pattern #7 (a *complement*, not a
replacement, of the LLM-as-parser family). This module consumes the
``EXEC SQL ... END-EXEC`` blocks that ``preprocess.py`` (WP-2) already split out
of the COBOL stream and emits the ONE internal IR (WP-4):

    preprocess (WP-2)  ── sql_blocks ──▶  sql_extract (WP-7)  ──▶  IR  ──▶
        graph_assemble (WP-8)  ──▶  openlineage_emit (WP-9)

------------------------------------------------------------------------------
Engine selection is EXPLICIT (design §3/§4, C2 — NO silent LLM fallback)
------------------------------------------------------------------------------
``sqlglot`` is an OPTIONAL, pure-Python dependency. The engine is chosen as:

  * ``engine="sqlglot-sql"`` — REQUIRE sqlglot. If it is not importable this is a
    fatal handoff (the caller / CLI prints the documented "use
    lineage-extract-static for the LLM path" pointer and exits non-zero). We
    NEVER auto-invoke an LLM (C2).
  * ``engine="auto"`` (default) — use sqlglot IF importable, else degrade to the
    stdlib REGEX engine and record a diagnostic. Still NO LLM.
  * ``engine="regex"`` — force the stdlib regex engine even if sqlglot is present.

The chosen engine is STAMPED into ``Provenance.engine`` ("sqlglot" | "regex") on
every edge so a side-by-side diff vs the LLM tool is attributable, and so the
user can see exactly which precision tier produced each edge.

There is **no automatic LLM tier**. Absent ``sqlglot`` degrades SQL precision
(regex) and emits a diagnostic — it NEVER silently invokes a model. The
deterministic engine has no LLM in the loop, ever.

------------------------------------------------------------------------------
DB2 dataset identity (naming-contract §1) — placeholders emitted VERBATIM
------------------------------------------------------------------------------
A DB2 table referenced from embedded SQL is a dataset:

  * Namespace: ``db2://<host>:<port>/<db>``
  * Name:      ``<schema>.<table>``

DB2 z/OS has **no default schema** and the host/port/db are usually not visible
in the source. When a component is not resolvable from the supplied inputs
(no ``--db2-catalog`` / no ``--schema`` / no connection metadata), the
placeholder token is emitted **verbatim** (``<host>``, ``<port>``, ``<db>``,
``<schema>``) — never invented. This is the SAME gap the LLM tool emits, written
identically, so a diff shows real differences not naming noise (C3).

------------------------------------------------------------------------------
The two precision targets (design §8)
------------------------------------------------------------------------------
1. **Table-level read/write edges** — ``FROM`` / ``JOIN`` (read),
   ``INSERT INTO`` (write), ``UPDATE`` (write), ``DELETE`` (write),
   ``SELECT ... INTO`` host-vars (read). These connect the program job node
   (``mainframe://<program-id>``) to the DB2 table dataset:
     * read   →  table  →  program   (the table feeds the program)
     * write  →  program → table     (the program feeds the table)

2. **Host-variable → column edges** — ``:host-var`` bound to a DB2
   ``table.column`` where derivable. These are **advisory-until-gold (#158)**:
   they MUST NEVER feed a gate, and a catalog-less column (no ``--db2-catalog`` /
   ``--schema``) is forced to ``speculative`` confidence with a
   ``catalog_less_column`` gap (naming-contract §1/§5).

------------------------------------------------------------------------------
Non-goals (design §8) — typed diagnostics, never silent best-effort
------------------------------------------------------------------------------
  * **Dynamic SQL** (``EXECUTE IMMEDIATE`` / ``PREPARE`` / a host-var statement
    string) — the statement text is not statically known. We emit an explicit
    ``sql.dynamic_sql`` diagnostic note (NOT a contract gap — the frozen §5
    closed gap set has no ``dynamic_sql`` member in v1) and never guess tables.
  * **non-DB2 dialects** — out of scope for the deterministic engine.

------------------------------------------------------------------------------
Purity (design D1)
------------------------------------------------------------------------------
Pure stdlib + the OPTIONAL ``sqlglot`` (import-if-present). NO ``networkx``, NO
new MANDATORY pip deps, NO network, NO shell beyond python3, NO runtime pip
install, NO LLM. The module is model-neutral: identical regardless of which CLI
host (Claude Code, Codex CLI, Copilot CLI, Antigravity CLI) invokes the engine.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


# ------------------------------------------------------------------------------
# Path-load the sibling modules (WP-2 preprocess, WP-4 ir) — keep the extractor
# runnable from any tree slice / CWD, matching the WP-2/3/4/5/6 convention
# (register in sys.modules BEFORE exec so dataclass annotation resolution under
# ``from __future__ import annotations`` succeeds on 3.12).
# ------------------------------------------------------------------------------
def _path_load(name: str, target: Path):
    """Load a module by file path and register it in ``sys.modules`` before exec.

    Path-load (not a package import) keeps the extractor runnable from any tree
    slice / CWD, mirroring the sibling convention. Registering in sys.modules
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


ir = _import_ir()


# ------------------------------------------------------------------------------
# Namespaces (naming-contract §1 / §3)
# ------------------------------------------------------------------------------
DB2_HOST_PLACEHOLDER = "<host>"
DB2_PORT_PLACEHOLDER = "<port>"
DB2_DB_PLACEHOLDER = "<db>"
DB2_SCHEMA_PLACEHOLDER = "<schema>"


def db2_namespace(host: Optional[str] = None, port: Optional[str] = None,
                  db: Optional[str] = None) -> str:
    """``db2://<host>:<port>/<db>`` (naming-contract §1).

    Each unresolved component is emitted as its placeholder token VERBATIM — never
    invented (C3). When --db2-catalog later supplies real host/port/db they
    replace the placeholders; until then the placeholder shows the diff parity
    with the LLM tool exactly."""
    h = host if host else DB2_HOST_PLACEHOLDER
    p = port if port else DB2_PORT_PLACEHOLDER
    d = db if db else DB2_DB_PLACEHOLDER
    return f"db2://{h}:{p}/{d}"


def program_namespace(program_id: str) -> str:
    """``mainframe://<program-id>`` (program-id already case-folded, §3 / §6)."""
    return f"mainframe://{program_id}"


# ------------------------------------------------------------------------------
# Engine selection (design §3/§4, C2)
# ------------------------------------------------------------------------------
ENGINE_AUTO = "auto"
ENGINE_REGEX = "regex"
ENGINE_SQLGLOT = "sqlglot-sql"
ENGINE_CHOICES = (ENGINE_AUTO, ENGINE_REGEX, ENGINE_SQLGLOT)

# The documented handoff printed when sqlglot is REQUIRED but absent (NEVER an
# LLM call — this is the deterministic engine's fail-loud boundary, C2).
SQLGLOT_HANDOFF = (
    "engine=sqlglot-sql requested but the optional 'sqlglot' package is not "
    "importable. Install it (pip install sqlglot) OR re-run with --engine regex "
    "for the stdlib regex engine. For the LLM-as-parser path use the sibling "
    "skill 'lineage-extract-static' — this deterministic engine NEVER invokes a "
    "model (C2)."
)


class SqlglotUnavailableError(RuntimeError):
    """Raised when ``engine='sqlglot-sql'`` is REQUIRED but sqlglot is absent.

    The CLI / run_lineage (WP-10) catches this, prints :data:`SQLGLOT_HANDOFF`,
    and exits non-zero. It is NEVER an LLM fallback (C2)."""


def _try_import_sqlglot():
    """Return the ``sqlglot`` module if importable, else ``None``.

    This is the ONLY place sqlglot is touched. The import is OPTIONAL; absence is
    a first-class, expected state (the live host at plan time has no sqlglot)."""
    if importlib.util.find_spec("sqlglot") is None:
        return None
    try:  # pragma: no cover - exercised only when sqlglot is installed
        import sqlglot  # noqa: F401  (import-if-present, design D1)
        return sqlglot
    except Exception:  # pragma: no cover - defensive
        return None


def resolve_engine(engine: str) -> Tuple[str, object]:
    """Resolve the requested engine to the (chosen_engine, sqlglot_or_None) pair.

    Returns ``("sqlglot", <module>)`` or ``("regex", None)``.

    Raises :class:`SqlglotUnavailableError` only when ``engine='sqlglot-sql'`` is
    REQUIRED and sqlglot is absent (fail-loud handoff, never an LLM call). For
    ``engine='auto'`` an absent sqlglot silently degrades to regex (the caller
    records the diagnostic). ``engine='regex'`` forces regex even if sqlglot is
    present."""
    if engine not in ENGINE_CHOICES:
        raise ValueError(f"engine must be one of {ENGINE_CHOICES!r}, got {engine!r}")
    if engine == ENGINE_REGEX:
        return (ENGINE_REGEX, None)
    sg = _try_import_sqlglot()
    if engine == ENGINE_SQLGLOT:
        if sg is None:
            raise SqlglotUnavailableError(SQLGLOT_HANDOFF)
        return ("sqlglot", sg)
    # auto
    if sg is not None:
        return ("sqlglot", sg)
    return (ENGINE_REGEX, None)


# ------------------------------------------------------------------------------
# Parsed-statement IR (engine-neutral) — both engines emit this shape
# ------------------------------------------------------------------------------
# Statement verb -> read/write direction relative to the program job node.
#   read  : the table FEEDS the program (table -> program)
#   write : the program FEEDS the table (program -> table)
_READ_VERBS = frozenset({"SELECT"})
_WRITE_VERBS = frozenset({"INSERT", "UPDATE", "DELETE", "MERGE"})

# Dynamic-SQL markers (non-goal: explicit diagnostic, never a guessed table).
_DYNAMIC_RE = re.compile(r"\b(EXECUTE\s+IMMEDIATE|PREPARE|EXECUTE)\b", re.IGNORECASE)


@dataclass
class TableRef:
    """One static table reference inside a statement.

    ``direction`` is "read" or "write" relative to the program job node.
    ``raw`` is the verbatim token as it appeared (for provenance)."""

    schema: Optional[str]   # None when not qualified in the SQL and none supplied
    table: str              # always present (the literal token, upper-cased)
    direction: str          # "read" | "write"
    raw: str                # verbatim source token


@dataclass
class ColumnRef:
    """One host-variable → column binding (``:host-var`` bound to a column).

    ``table`` is the best-effort owning table (the statement's primary table when
    unambiguous, else ``None``). ``column`` is the column name when statically
    derivable (e.g. ``SET COL = :HV`` / ``INSERT (COL) VALUES (:HV)`` /
    ``WHERE COL = :HV``), else ``None`` (a bare host-var with no column)."""

    host_var: str           # the :name token (without the leading colon)
    table: Optional[str]
    column: Optional[str]
    raw: str                # verbatim source token


@dataclass
class ParsedStatement:
    """The engine-neutral parse of one EXEC SQL block.

    Both the sqlglot and the regex engines fill this shape; the IR-emission code
    below is engine-agnostic and only reads :class:`ParsedStatement`."""

    tables: List[TableRef] = field(default_factory=list)
    columns: List[ColumnRef] = field(default_factory=list)
    is_dynamic: bool = False
    verb: Optional[str] = None        # the leading verb (SELECT/INSERT/...)
    raw_text: str = ""                # the SQL body (markers excluded)


# ------------------------------------------------------------------------------
# The stdlib REGEX engine (the live path — sqlglot is absent at plan time)
# ------------------------------------------------------------------------------
# An SQL identifier: optionally schema-qualified, allowing the DB2 _, $, # chars.
_IDENT = r"[A-Za-z_#@$][A-Za-z0-9_#@$]*"
_QUAL_IDENT = rf"(?:{_IDENT}\.)?{_IDENT}"

# A host-variable name is a COBOL data-name, NOT a SQL identifier: it permits the
# COBOL hyphen (e.g. ``:WS-EMPNO``). Keeping this separate from _IDENT means a SQL
# column token never absorbs a hyphen and a host-var never loses its hyphenated
# tail (the ``raw_host_var: 'WS'`` truncation bug guard).
_HOSTVAR_IDENT = r"[A-Za-z_#@$][A-Za-z0-9_#@$-]*"

_FROM_RE = re.compile(rf"\bFROM\s+({_QUAL_IDENT})", re.IGNORECASE)
_JOIN_RE = re.compile(rf"\bJOIN\s+({_QUAL_IDENT})", re.IGNORECASE)
_INSERT_RE = re.compile(rf"\bINSERT\s+INTO\s+({_QUAL_IDENT})", re.IGNORECASE)
_UPDATE_RE = re.compile(rf"\bUPDATE\s+({_QUAL_IDENT})", re.IGNORECASE)
_DELETE_RE = re.compile(rf"\bDELETE\s+FROM\s+({_QUAL_IDENT})", re.IGNORECASE)
_MERGE_RE = re.compile(rf"\bMERGE\s+INTO\s+({_QUAL_IDENT})", re.IGNORECASE)

# host-variable token: ``:name`` (DB2 allows ``:struct.field`` and indicator
# ``:hv:ind`` forms; we capture the primary host-var name, hyphens included).
_HOSTVAR_RE = re.compile(rf":({_HOSTVAR_IDENT}(?:\.{_HOSTVAR_IDENT})?)")

# Column = :host-var bindings (WHERE / SET / ON predicates). The LHS is a SQL
# column identifier (no hyphen); the RHS host-var keeps its COBOL hyphens.
_COL_EQ_HV_RE = re.compile(
    rf"({_IDENT})\s*=\s*:({_HOSTVAR_IDENT}(?:\.{_HOSTVAR_IDENT})?)", re.IGNORECASE
)

_LEADING_VERB_RE = re.compile(r"^\s*([A-Za-z]+)", re.IGNORECASE)


def _split_qualified(token: str) -> Tuple[Optional[str], str]:
    """Split ``schema.table`` -> (schema, table); ``table`` -> (None, table).

    Case-folds to UPPER per naming-contract §6 (DB2 identifiers are case-insensitive
    when unquoted; we canonicalise to upper for stable ids)."""
    parts = token.split(".")
    if len(parts) == 2:
        return (parts[0].upper(), parts[1].upper())
    return (None, parts[0].upper())


def parse_statement_regex(sql: str) -> ParsedStatement:
    """Parse one SQL statement body with the stdlib regex engine.

    Extracts FROM/JOIN/INSERT/UPDATE/DELETE/MERGE table refs (with read/write
    direction) and ``Column = :host-var`` column bindings. Dynamic SQL is flagged
    (never guessed). Deterministic, pure stdlib."""
    stmt = ParsedStatement(raw_text=sql)

    m = _LEADING_VERB_RE.match(sql)
    if m:
        stmt.verb = m.group(1).upper()

    if _DYNAMIC_RE.search(sql):
        stmt.is_dynamic = True
        # Do NOT extract tables from a dynamic statement (the text is a host-var
        # string, not the real SQL) — emit the diagnostic only.
        return stmt

    seen: set = set()

    def _add(token: str, direction: str) -> None:
        schema, table = _split_qualified(token)
        key = (schema, table, direction)
        if key in seen:
            return
        seen.add(key)
        stmt.tables.append(TableRef(schema=schema, table=table, direction=direction, raw=token))

    for rx, direction in (
        (_FROM_RE, "read"),
        (_JOIN_RE, "read"),
        (_INSERT_RE, "write"),
        (_UPDATE_RE, "write"),
        (_DELETE_RE, "write"),
        (_MERGE_RE, "write"),
    ):
        for mt in rx.finditer(sql):
            _add(mt.group(1), direction)

    # Column bindings: ``COL = :HV`` (covers WHERE / SET / ON predicates).
    primary_table = stmt.tables[0].table if stmt.tables else None
    col_seen: set = set()
    for cm in _COL_EQ_HV_RE.finditer(sql):
        col = cm.group(1).upper()
        hv = cm.group(2)
        # Skip a spurious match where the LHS is itself a host-var fragment.
        key = (hv, col)
        if key in col_seen:
            continue
        col_seen.add(key)
        stmt.columns.append(ColumnRef(host_var=hv, table=primary_table, column=col, raw=f":{hv}"))

    return stmt


# ------------------------------------------------------------------------------
# The OPTIONAL sqlglot engine (exercised only when sqlglot is installed)
# ------------------------------------------------------------------------------
def parse_statement_sqlglot(sql: str, sqlglot_mod) -> ParsedStatement:  # pragma: no cover - sqlglot absent at plan time
    """Parse one SQL statement with sqlglot (the higher-precision optional engine).

    Falls back to the regex engine's column heuristic for ``:host-var`` column
    bindings (sqlglot does not model EXEC SQL host-vars natively). Table refs come
    from the sqlglot AST for higher precision. Guarded by an importorskip in the
    tests so the suite is green whether or not sqlglot is installed."""
    stmt = ParsedStatement(raw_text=sql)
    exp = sqlglot_mod.expressions
    try:
        tree = sqlglot_mod.parse_one(sql, dialect="db2")
    except Exception:
        # A statement sqlglot cannot parse (e.g. an EXEC-SQL-only construct) ->
        # degrade to the regex engine for THIS statement (never an LLM call).
        return parse_statement_regex(sql)

    if tree is None:
        return parse_statement_regex(sql)

    stmt.verb = type(tree).__name__.upper()

    # Determine read vs write from the root statement type.
    write_types = (exp.Insert, exp.Update, exp.Delete, exp.Merge)
    is_write_root = isinstance(tree, write_types)

    seen: set = set()
    for tbl in tree.find_all(exp.Table):
        table = (tbl.name or "").upper()
        if not table:
            continue
        schema = (tbl.db or "").upper() or None
        # The target table of a write statement is a write; FROM/JOIN are reads.
        # A heuristic: the statement-root target table is the write target; all
        # others (subselect sources) are reads.
        direction = "write" if (is_write_root and tbl is tree.this) else "read"
        key = (schema, table, direction)
        if key in seen:
            continue
        seen.add(key)
        stmt.tables.append(TableRef(schema=schema, table=table, direction=direction, raw=tbl.sql()))

    # Host-var column bindings — reuse the regex heuristic (sqlglot does not model
    # EXEC SQL host-vars). This keeps column precision identical across engines.
    regex_parse = parse_statement_regex(sql)
    stmt.columns = regex_parse.columns
    return stmt


# ------------------------------------------------------------------------------
# IR emission (engine-agnostic — reads only ParsedStatement)
# ------------------------------------------------------------------------------
@dataclass
class SqlExtractResult:
    """The full result of extracting one set of EXEC SQL blocks.

    ``ir`` is the emitted IR (edges + gaps). ``chosen_engine`` is the engine that
    actually ran ("sqlglot" | "regex"). ``diagnostics`` are typed non-goal /
    degradation notes (dynamic SQL, auto-degrade-to-regex) — never silent."""

    ir: "object"            # an ir.IR instance
    chosen_engine: str
    diagnostics: List[str] = field(default_factory=list)


def _db2_table_node(schema: Optional[str], table: str, *, host=None, port=None, db=None):
    """Build the DB2 table dataset node ``db2://<host>:<port>/<db>`` /
    ``<schema>.<table>`` (naming-contract §1).

    An unresolved schema is emitted as the placeholder ``<schema>`` VERBATIM
    (never invented)."""
    ns = db2_namespace(host, port, db)
    sch = schema if schema else DB2_SCHEMA_PLACEHOLDER
    name = f"{sch}.{table}"
    facets = {"raw_table": table}
    if schema:
        facets["schema"] = schema
    return ir.make_node(ns, name, node_type="dataset", facets=facets)


def _db2_column_node(table_node, column: str):
    """Build a DB2 column node as a child dataset of the table node.

    Name is ``<schema>.<table>.<column>`` so the column edge target is the precise
    catalog column when resolved, and the placeholder-schema form when not."""
    ns = table_node.namespace
    name = f"{table_node.name}.{column.upper()}"
    return ir.make_node(ns, name, node_type="dataset",
                        facets={"raw_column": column, "of_table": table_node.name})


def emit_ir_from_statements(
    statements: Sequence[ParsedStatement],
    *,
    program_id: str,
    chosen_engine: str,
    spans: Optional[Sequence] = None,
    schema_default: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[str] = None,
    db: Optional[str] = None,
    has_catalog: bool = False,
    on_violation: str = "coerce",
) -> SqlExtractResult:
    """Emit the IR for a parsed set of statements (engine-agnostic).

    Parameters mirror the naming-contract §1 resolution inputs:
      * ``schema_default`` — from ``--schema``; applied when the SQL did not
        qualify the table. Absence keeps the ``<schema>`` placeholder.
      * ``host`` / ``port`` / ``db`` — from ``--db2-catalog`` connection metadata;
        absence keeps the verbatim placeholders.
      * ``has_catalog`` — True when ``--db2-catalog``/``--schema`` give enough to
        resolve a column to a real catalog column. When False, every column edge
        is forced ``speculative`` + a ``catalog_less_column`` gap (§1/§5, #158
        advisory-until-gold).

    ``spans`` (optional) is a per-statement list of (file, start_line, end_line)
    parallel to ``statements`` for source-span provenance.
    """
    out = ir.IR()
    diagnostics: List[str] = []
    pgm_node = ir.make_node(program_namespace(program_id), program_id, node_type="job")

    def _span_for(idx: int):
        if spans is not None and idx < len(spans):
            f, s, e = spans[idx]
            return ir.SourceSpan(f, s, e if e != s else None)
        return None

    for idx, stmt in enumerate(statements):
        span = _span_for(idx)
        span_list = [span] if span is not None else []

        if stmt.is_dynamic:
            # Non-goal: dynamic SQL. Explicit typed diagnostic — NEVER a guessed
            # table (C2/C3). Not a contract gap (the §5 set is closed in v1).
            diag = f"sql.dynamic_sql: statement '{(stmt.verb or 'DYNAMIC')}' is dynamic SQL (non-goal, no tables claimed)"
            diagnostics.append(diag)
            continue

        # (1) Table-level read/write edges (program job <-> DB2 table).
        for tref in stmt.tables:
            schema = tref.schema or schema_default
            table_node = _db2_table_node(schema, tref.table, host=host, port=port, db=db)
            # A statically-named table is a direct literal edge -> grounded. (The
            # table NAME is literal; the connection identity may still be a
            # placeholder, but that does not lower the table-edge confidence —
            # the placeholder is honest namespace, not a guessed binding.)
            prov = ir.Provenance(
                parser="sql",
                engine=chosen_engine,
                rule_id=f"sql.table.{tref.direction}",
                source_spans=list(span_list),
                dialect="db2-sql",
                raw_tokens={"raw_table": tref.raw, "verb": stmt.verb or ""},
            )
            if tref.direction == "read":
                edge = ir.make_edge(
                    table_node, pgm_node,
                    kind="direct", confidence="grounded", literal=True,
                    provenance=prov, on_violation=on_violation,
                )
            else:  # write
                edge = ir.make_edge(
                    pgm_node, table_node,
                    kind="direct", confidence="grounded", literal=True,
                    provenance=prov, on_violation=on_violation,
                )
            out.add_edge(edge)

        # (2) Host-var -> column edges (advisory-until-gold, #158).
        for cref in stmt.columns:
            schema = (cref.table and _schema_for_table(stmt, cref.table, schema_default)) or schema_default
            # Build the owning table node (best-effort) for the column's parent.
            table_name = cref.table or (stmt.tables[0].table if stmt.tables else None)
            if table_name is None or cref.column is None:
                # A bare host-var with no resolvable column -> not an edge; record
                # nothing as an invented edge (C3). (Still visible via the table
                # edges above.)
                continue
            table_node = _db2_table_node(schema, table_name, host=host, port=port, db=db)
            col_node = _db2_column_node(table_node, cref.column)
            prov = ir.Provenance(
                parser="sql",
                engine=chosen_engine,
                rule_id="sql.hostvar.column",
                source_spans=list(span_list),
                dialect="db2-sql",
                raw_tokens={"raw_host_var": cref.host_var, "raw_column": cref.column},
            )
            if has_catalog:
                # Catalog supplied -> the column resolves to a real catalog column.
                # Still an inferred-kind edge (we infer the host-var<->column
                # binding from the predicate; it is not a literal lineage token).
                edge = ir.make_edge(
                    col_node, pgm_node,
                    kind="inferred", confidence="inferred",
                    provenance=prov, on_violation=on_violation,
                )
                out.add_edge(edge)
            else:
                # Catalog-less column (naming-contract §1/§5): forced speculative +
                # a catalog_less_column gap. Advisory-until-gold (#158) — NEVER
                # feeds a gate.
                prov.notes.append("catalog-less column: forced speculative (advisory-until-gold #158)")
                edge = ir.make_edge(
                    col_node, pgm_node,
                    kind="unresolved", confidence="speculative",
                    provenance=prov, on_violation=on_violation,
                )
                out.add_edge(edge)
                out.add_gap(ir.gap_catalog_less_column(cref.host_var, source_span=span))

    if chosen_engine == ENGINE_REGEX:
        # Record the degradation note ONCE if any statement carried real SQL (so a
        # diff shows the engine tier honestly). The caller decides whether this is
        # an auto-degrade or an explicit --engine regex.
        pass  # the engine facet on every edge already carries this; no extra note.

    res = SqlExtractResult(ir=out, chosen_engine=chosen_engine, diagnostics=diagnostics)
    _canonical_sort_dedupe(out)
    return res


def _schema_for_table(stmt: ParsedStatement, table: str, schema_default: Optional[str]) -> Optional[str]:
    """Return the schema qualifying ``table`` in this statement, if the SQL
    qualified it; else None (the caller applies ``schema_default``)."""
    for tref in stmt.tables:
        if tref.table == table and tref.schema:
            return tref.schema
    return None


# ------------------------------------------------------------------------------
# Canonical sort + dedupe (mirrors the WP-5/WP-6 _canonical_sort_dedupe shape)
# ------------------------------------------------------------------------------
def _canonical_sort_dedupe(out) -> None:
    """In-place canonical sort + dedupe of the IR's edges by canonical edge key
    (naming-contract §6 rule 2-4); gap nodes deduped + sorted; both deterministic.

    Duplicate edges (same canonical key) collapse to one with merged provenance.
    The WP-8 assembler re-applies the GLOBAL sort across all extractors; this keeps
    the extractor's own slice deterministic in isolation (and testable). Mirrors
    the WP-5/WP-6 ``_canonical_sort_dedupe`` shape exactly."""
    by_key: Dict[Tuple[str, str, str], object] = {}
    for e in out.edges:
        k = e.canonical_key
        if k in by_key:
            by_key[k].provenance.merge_from(e.provenance)
        else:
            by_key[k] = e
    out.edges = [by_key[k] for k in sorted(by_key)]

    def _gap_key(g) -> Tuple[str, str]:
        raw = g.facets.get("raw_copy_member") or g.facets.get("raw_dsn") \
            or g.facets.get("raw_host_var") or ""
        return (g.gap_type, raw)

    seen_gaps: Dict[Tuple[str, str], object] = {}
    for g in out.gaps:
        seen_gaps.setdefault(_gap_key(g), g)
    out.gaps = [seen_gaps[k] for k in sorted(seen_gaps)]


# ------------------------------------------------------------------------------
# Public entry points
# ------------------------------------------------------------------------------
def extract_sql_blocks(
    sql_blocks: Sequence,
    *,
    program_id: str,
    engine: str = ENGINE_AUTO,
    schema: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[str] = None,
    db: Optional[str] = None,
    db2_catalog: Optional[str] = None,
    on_violation: str = "coerce",
) -> SqlExtractResult:
    """Extract IR from a list of preprocess ``SqlBlock`` objects (the primary API).

    ``sql_blocks`` is the ``PreprocessResult.sql_blocks`` list (each has
    ``.text``, ``.file``, ``.start_line``, ``.end_line``). The engine is resolved
    per :func:`resolve_engine` (NO LLM ever, C2); ``engine='sqlglot-sql'`` with
    sqlglot absent raises :class:`SqlglotUnavailableError`.

    A column resolves to a real catalog column ONLY when a catalog/schema is
    supplied (``db2_catalog`` or ``schema``); otherwise every column edge is
    forced ``speculative`` + ``catalog_less_column`` gap (naming-contract §1/§5,
    #158)."""
    chosen_engine, sg = resolve_engine(engine)
    has_catalog = bool(db2_catalog) or bool(schema)

    statements: List[ParsedStatement] = []
    spans: List[Tuple[str, int, int]] = []
    for blk in sql_blocks:
        if chosen_engine == "sqlglot":
            statements.append(parse_statement_sqlglot(blk.text, sg))
        else:
            statements.append(parse_statement_regex(blk.text))
        spans.append((blk.file, blk.start_line, blk.end_line))

    result = emit_ir_from_statements(
        statements,
        program_id=program_id,
        chosen_engine=chosen_engine,
        spans=spans,
        schema_default=schema.upper() if schema else None,
        host=host,
        port=port,
        db=db,
        has_catalog=has_catalog,
        on_violation=on_violation,
    )
    if engine == ENGINE_AUTO and chosen_engine == ENGINE_REGEX and statements:
        result.diagnostics.insert(
            0,
            "sql.engine_degraded: sqlglot not importable; degraded to the stdlib "
            "regex engine (lower SQL precision). For the LLM-as-parser path use "
            "lineage-extract-static. No model was invoked (C2).",
        )
    return result


def extract_sql_text(
    cobol_text: str,
    *,
    program_id: str = "UNKNOWN-PROGRAM",
    file_label: str = "<memory>",
    engine: str = ENGINE_AUTO,
    schema: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[str] = None,
    db: Optional[str] = None,
    db2_catalog: Optional[str] = None,
    on_violation: str = "coerce",
) -> SqlExtractResult:
    """Convenience: preprocess raw COBOL text (extracting its EXEC SQL blocks) and
    extract the SQL IR in one call. Composes WP-2 ``preprocess_source``."""
    pp = _import_preprocess()
    pre = pp.preprocess_source(cobol_text, file_label=file_label)
    return extract_sql_blocks(
        pre.sql_blocks,
        program_id=program_id,
        engine=engine,
        schema=schema,
        host=host,
        port=port,
        db=db,
        db2_catalog=db2_catalog,
        on_violation=on_violation,
    )


def extract_sql_file(
    path,
    *,
    program_id: Optional[str] = None,
    engine: str = ENGINE_AUTO,
    schema: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[str] = None,
    db: Optional[str] = None,
    db2_catalog: Optional[str] = None,
    on_violation: str = "coerce",
) -> SqlExtractResult:
    """Convenience: read a COBOL file, preprocess it, and extract the SQL IR.

    ``program_id`` defaults to the file stem (upper-cased) when not given; the
    caller (run_lineage WP-10) supplies the real PROGRAM-ID from the COBOL
    extractor so the SQL edges share the program job node."""
    p = Path(path)
    pid = program_id or p.stem.upper()
    text = p.read_text(encoding="utf-8", errors="replace")
    return extract_sql_text(
        text,
        program_id=pid,
        file_label=str(p),
        engine=engine,
        schema=schema,
        host=host,
        port=port,
        db=db,
        db2_catalog=db2_catalog,
        on_violation=on_violation,
    )


# ------------------------------------------------------------------------------
# CLI (non-interactive; ALL inputs as flags — WP-10 wires the full chain)
# ------------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="sql_extract",
        description=(
            "Extract DB2 embedded-EXEC-SQL lineage IR from a COBOL source file. "
            "Deterministic; sqlglot-optional with a regex fallback; NEVER invokes "
            "an LLM (C2)."
        ),
    )
    ap.add_argument("source", help="path to a COBOL source file containing EXEC SQL")
    ap.add_argument("--program-id", default=None,
                    help="the PROGRAM-ID for the job node (default: file stem)")
    ap.add_argument("--engine", choices=ENGINE_CHOICES, default=ENGINE_AUTO,
                    help="SQL engine: auto (sqlglot if present else regex), regex, or sqlglot-sql (require sqlglot)")
    ap.add_argument("--schema", default=None, help="default DB2 schema (--schema PAYROLL)")
    ap.add_argument("--db2-catalog", default=None,
                    help="path/handle to DB2 catalog metadata enabling real column resolution")
    ap.add_argument("--host", default=None, help="DB2 host (else <host> placeholder)")
    ap.add_argument("--port", default=None, help="DB2 port (else <port> placeholder)")
    ap.add_argument("--db", default=None, help="DB2 database (else <db> placeholder)")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = _build_arg_parser()
    args = ap.parse_args(argv)
    try:
        res = extract_sql_file(
            args.source,
            program_id=args.program_id,
            engine=args.engine,
            schema=args.schema,
            host=args.host,
            port=args.port,
            db=args.db,
            db2_catalog=args.db2_catalog,
        )
    except SqlglotUnavailableError as e:
        # Fail-loud handoff (NEVER an LLM call, C2).
        print(str(e), file=sys.stderr)
        return 2
    print(f"engine: {res.chosen_engine}")
    print(f"edges: {len(res.ir.edges)}  gaps: {len(res.ir.gaps)}")
    for e in res.ir.edges:
        print(f"  [{e.kind}/{e.confidence}] {e.source.node_id} -> {e.target.node_id}")
    for g in res.ir.gaps:
        print(f"  GAP {g.gap_type}: {g.facets}")
    for d in res.diagnostics:
        print(f"  DIAG {d}")
    return 0


__all__ = [
    # engine constants / selection
    "ENGINE_AUTO",
    "ENGINE_REGEX",
    "ENGINE_SQLGLOT",
    "ENGINE_CHOICES",
    "SQLGLOT_HANDOFF",
    "SqlglotUnavailableError",
    "resolve_engine",
    # namespaces / placeholders
    "DB2_HOST_PLACEHOLDER",
    "DB2_PORT_PLACEHOLDER",
    "DB2_DB_PLACEHOLDER",
    "DB2_SCHEMA_PLACEHOLDER",
    "db2_namespace",
    "program_namespace",
    # parse model
    "TableRef",
    "ColumnRef",
    "ParsedStatement",
    "parse_statement_regex",
    "parse_statement_sqlglot",
    # emission
    "SqlExtractResult",
    "emit_ir_from_statements",
    # public entry points
    "extract_sql_blocks",
    "extract_sql_text",
    "extract_sql_file",
    # cli
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
