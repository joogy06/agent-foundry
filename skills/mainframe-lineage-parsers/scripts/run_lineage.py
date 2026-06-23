#!/usr/bin/env python3
"""run_lineage.py — the NON-INTERACTIVE autonomous CLI (mainframe-lineage-parsers WP-10).

The autonomous core (design §11). Wires the WHOLE deterministic chain:

    preprocess (WP-2)
      -> copybook_resolver (WP-3)
        -> { jcl_extract (WP-5), cobol_extract (WP-6), sql_extract (WP-7) }
          -> graph_assemble (WP-8)
            -> openlineage_emit (WP-9)  -> OpenLineage 2.0.2 ndjson

CONTRACT (design §11, autonomy_requirement):

  * ALL inputs are FLAGS. ZERO interactive prompts — this module NEVER reads
    stdin and NEVER asks a question. Gather inputs + permissions ONCE (the caller
    front-loads the allows); then run to completion non-interactively.

  * Gaps become DIAGNOSTICS / speculative edges, NEVER a blocking question:
      - unresolved COPY        -> `unresolved_copy` gap (and a non-zero exit ONLY
                                  under --copybook-missing=fail)
      - free-format COBOL      -> `free_format_unsupported` gap + partial output
      - symbolic / catalog-less-> `symbolic_dsn` / `catalog_less_column` gap,
                                  edge forced `speculative`
    The deterministic engine has NO LLM in the loop, EVER (C2).

  * Non-zero exit ONLY on fatal/unusable input:
      0  success (even with gaps — gaps are normal output)
      1  fatal: no usable input, fatal emit/validation failure, unreadable --src
      2  fail-LOUD handoff: --engine=sqlglot-sql requested but sqlglot is absent;
         the documented "use lineage-extract-static for the LLM path" pointer is
         printed (a model is NEVER auto-invoked, C2)
      3  --copybook-missing=fail AND an unresolved COPY remained

  * Deterministic + scriptable: re-running with the same inputs produces a
    byte-identical ndjson (the emitter sorts keys + uses a fixed default
    eventTime; set SOURCE_DATE_EPOCH for a reproducible non-default eventTime).

  * Front-loaded allows: READ --src / --copybook-path / --jcl-proc-path;
    WRITE --out. NO network/egress, NO shell beyond python3, NO dep install.

Headless usage (see SKILL.md WP-13):
    python3 run_lineage.py \
        --src PAYCALC.cbl --src PAYJOB.jcl \
        --copybook-path copybooks/ \
        --jcl-proc-path proclib/ \
        --out lineage.ndjson \
        --engine auto

Pure stdlib + OPTIONAL sqlglot (import-if-present, regex fallback) +
OPTIONAL networkx (graceful). No new MANDATORY pip deps; no runtime pip install (D1).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

# --- path-import the sibling skill scripts (own dir + the OL sibling) ----------
# Mirror the openlineage_emit.py runtime convention: add THIS scripts dir and the
# lineage-extract-static scripts dir to sys.path so the whole chain + the reused
# OL emit/validate machinery import cleanly whether run as a script or imported.
_THIS = Path(__file__).resolve()
_SKILL_SCRIPTS = _THIS.parent
_SKILLS_ROOT = _THIS.parents[2]  # .../skills
_SIBLING_SCRIPTS = _SKILLS_ROOT / "lineage-extract-static" / "scripts"

for _p in (str(_SKILL_SCRIPTS), str(_SIBLING_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import preprocess as _pre  # noqa: E402
import jcl_extract as _jcl  # noqa: E402
import cobol_extract as _cob  # noqa: E402
import sql_extract as _sql  # noqa: E402
import controlm_extract as _ctm  # noqa: E402
import graph_assemble as _ga  # noqa: E402
import openlineage_emit as _emit  # noqa: E402

# IMPORTANT (module identity): every chain module registers the IR module under
# the SHARED ``sys.modules`` name ``mlp_ir`` (see graph_assemble._import_ir,
# cobol/jcl/sql_extract). A plain ``import ir`` would register a DISTINCT module
# object whose ``ir.IR`` class is NOT the one the assembler's ``isinstance``
# check expects — so any IR we construct here (the preprocess-gap slice) would be
# rejected by ``graph_assemble._coerce_to_ir``. Reuse the assembler's already
# loaded, canonical ``mlp_ir`` module so every IR/gap node we build is the EXACT
# class the rest of the chain uses.
_ir = _ga.ir  # the shared mlp_ir module


# The documented LLM-handoff pointer (model-neutral; surfaced fail-LOUD, never
# auto-invoked — C2). sql_extract carries the same text in SQLGLOT_HANDOFF.
LLM_HANDOFF = (
    "For the LLM-as-parser path (free-format COBOL, non-DB2 dialects, dynamic SQL, "
    "or a richer SQL parse than the stdlib regex engine) use the sibling skill "
    "`lineage-extract-static`. This deterministic engine has NO LLM in the loop "
    "and will NOT auto-invoke a model."
)

# COBOL / JCL source classification.
_JCL_SUFFIXES = {".jcl", ".jct", ".job", ".proc", ".prc"}
_COBOL_SUFFIXES = {".cbl", ".cob", ".cobol", ".cpy", ".ccp", ".pco"}


# ==============================================================================
# Source discovery + classification (no prompts; deterministic order)
# ==============================================================================
def _expand_sources(src_args: Sequence[str]) -> List[Path]:
    """Expand --src args (files, directories, or globs) into a sorted file list.

    Deterministic: the result is sorted by resolved path so a re-run is stable.
    A directory expands to its COBOL+JCL files (recursively). A glob expands via
    pathlib. Plain file paths pass through. Missing paths are NOT silently
    dropped — they surface in the returned `missing` list for a fatal report.
    """
    found: List[Path] = []
    missing: List[str] = []
    for raw in src_args:
        p = Path(raw)
        if p.is_file():
            found.append(p.resolve())
            continue
        if p.is_dir():
            for child in p.rglob("*"):
                if child.is_file() and child.suffix.lower() in (
                    _JCL_SUFFIXES | _COBOL_SUFFIXES
                ):
                    found.append(child.resolve())
            continue
        # treat as a glob. pathlib rejects non-relative glob patterns on 3.12,
        # so split an absolute pattern into an anchor + a relative tail and glob
        # from the anchor; a relative pattern globs from CWD.
        try:
            if p.is_absolute():
                anchor = Path(p.anchor)
                rel = str(p.relative_to(anchor))
                matches = [m.resolve() for m in sorted(anchor.glob(rel)) if m.is_file()]
            else:
                matches = [m.resolve() for m in sorted(Path().glob(raw)) if m.is_file()]
        except (NotImplementedError, ValueError):
            matches = []
        if matches:
            found.extend(matches)
        else:
            missing.append(raw)
    # de-dup + sort (stable, byte-identical re-run)
    uniq = sorted(set(found), key=lambda x: str(x))
    return uniq, missing  # type: ignore[return-value]


def _classify(path: Path) -> str:
    """Return 'jcl', 'cobol', or 'controlm' for a source file.

    Suffix-first (fast, deterministic); falls back to a content sniff for
    suffix-less files (a leading `//... JOB` / `//... EXEC` marks JCL).

    CONVENIENCE Control-M sniff (design §3): a `.json` head carrying a
    `"Type": "Job:"` leaf is tagged 'controlm' AHEAD of the COBOL fallback (a
    Control-M `.json` is neither a JCL nor a COBOL suffix and would otherwise fall
    through to the COBOL content sniff). The `--controlm` flag remains the
    documented, authoritative invocation; this is a best-effort convenience only.
    """
    suf = path.suffix.lower()
    if suf in _JCL_SUFFIXES:
        return "jcl"
    if suf in _COBOL_SUFFIXES:
        return "cobol"
    # content sniff (read a small head; no full parse here)
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return "cobol"
    # Control-M convenience sniff: a JSON head with a "Type": "Job:" leaf.
    if suf == ".json" and '"Type"' in head and '"Job:' in head:
        return "controlm"
    for line in head.splitlines():
        s = line.rstrip()
        if s.startswith("//") and (" JOB " in s or s.endswith(" JOB") or " EXEC " in s):
            return "jcl"
        if s.startswith("//*"):
            continue
    return "cobol"


def _parse_controlm_profiles(arg: str) -> dict:
    """Parse the --controlm-connection-profiles argument into a profile map.

    Accepts either an inline JSON object string or a path to a JSON file. The
    parsed value MUST be a JSON object (profile_name -> {host,port,db,schema});
    anything else raises ValueError. Deterministic, no network, read-only."""
    candidate = Path(arg)
    if candidate.is_file():
        raw = candidate.read_text(encoding="utf-8")
    else:
        raw = arg
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("connection-profiles must be a JSON object")
    return obj


# ==============================================================================
# Preprocess-gap -> IR gap-node slice (C3: gaps are NEVER silently dropped)
# ==============================================================================
def _preprocess_gaps_to_ir(pre: "_pre.PreprocessResult") -> "_ir.IR":
    """Carry preprocess-level gaps (free-format, etc.) into an IR gap slice.

    The COBOL extractor only forwards COPY-resolver gaps; a free-format source
    produces zero clean lines (so zero edges/gaps from the extractor). To honour
    C3 we lift every preprocess gap into a typed IR gap node here so it is
    surfaced in the OpenLineage stream as a visible gap DatasetEvent.
    """
    out = _ir.IR()
    for g in pre.gaps:
        span = _ir.SourceSpan(
            file=(g.ref.file if getattr(g, "ref", None) else (pre.file or "")),
            start_line=(g.ref.line if getattr(g, "ref", None) else 1),
        )
        if g.type == _ir.GAP_FREE_FORMAT_UNSUPPORTED:
            out.gaps.append(_ir.gap_free_format_unsupported(source_span=span))
        else:
            # Any other preprocess gap type maps through make_gap_node verbatim;
            # the gap_type is already a frozen-vocab member (preprocess uses the
            # same closed set), so this never invents a node.
            out.gaps.append(
                _ir.make_gap_node(g.type, facets={"detail": g.detail or ""},
                                  source_span=span)
            )
    return out


def _count_unresolved_copy(ir_obj: "_ir.IR") -> int:
    """Count `unresolved_copy` gaps in an IR (for --copybook-missing=fail)."""
    return sum(1 for g in ir_obj.gaps if g.gap_type == _ir.GAP_UNRESOLVED_COPY)


# ==============================================================================
# Per-source extraction (the chain, wired)
# ==============================================================================
def _extract_one(
    path: Path,
    kind: str,
    *,
    copybook_paths: Sequence[Path],
    proc_paths: Sequence[Path],
    engine: str,
    schema: Optional[str],
    db2_catalog: Optional[str],
    diagnostics: List[str],
    controlm_profiles: Optional[dict] = None,
) -> List["object"]:
    """Extract the IR slice(s) for one source file.

    Returns a list of slices (ir.IR and/or SqlExtractResult) ready for assemble.
    Raises sql_extract.SqlglotUnavailableError on the fail-LOUD sqlglot path so
    the CLI can map it to exit 2 (the handoff). All other gaps are surfaced as IR
    gap nodes, never raised.
    """
    slices: List["object"] = []

    if kind == "controlm":
        # Control-M Automation-API jobs-as-code JSON (WP-2/WP-3). Explicit-flag-
        # authoritative: --controlm forces this kind, bypassing _classify.
        cir = _ctm.extract_controlm_file(
            str(path), connection_profiles=controlm_profiles or {},
        )
        slices.append(cir)
        return slices

    if kind == "jcl":
        jir = _jcl.extract_jcl_file(path, proc_paths=[str(p) for p in proc_paths])
        slices.append(jir)
        return slices

    # --- COBOL: preprocess (capture format/preprocess gaps) -------------------
    pre = _pre.preprocess_file(path)
    pre_slice = _preprocess_gaps_to_ir(pre)
    if pre_slice.gaps:
        slices.append(pre_slice)
        for g in pre.gaps:
            diagnostics.append(
                f"preprocess.{g.type}: {path} — {g.detail or ''}".rstrip(" —")
            )

    # Free-format -> the extractor yields nothing usable; the gap above is the
    # honest output. Still continue (partial output) — do NOT prompt, do NOT fail.
    if pre.source_format != "fixed":
        diagnostics.append(
            f"cobol.partial: {path} is {pre.source_format}-format; emitted the "
            f"free_format_unsupported gap only. {LLM_HANDOFF}"
        )
        return slices

    # --- COBOL IR (preprocess + COPY-resolve + extract) -----------------------
    cir = _cob.extract_cobol_file(path, copybook_paths=[str(p) for p in copybook_paths])
    slices.append(cir)

    # Real PROGRAM-ID so the SQL edges share the program job node (not the stem).
    pid = _program_id_for(path, copybook_paths) or path.stem.upper()

    # --- SQL IR (EXEC SQL split + parse; engine resolved here, fail-LOUD) -----
    sres = _sql.extract_sql_file(
        path,
        program_id=pid,
        engine=engine,
        schema=schema,
        db2_catalog=db2_catalog,
    )
    slices.append(sres)
    for d in sres.diagnostics:
        diagnostics.append(f"{path}: {d}")
    return slices


def _program_id_for(path: Path, copybook_paths: Sequence[Path]) -> Optional[str]:
    """Resolve the COBOL PROGRAM-ID via the WP-3/WP-6 resolve path.

    Reuses cobol_extract.extract_program_id over the COPY-expanded clean stream
    so a PROGRAM-ID that lives in a copybook is still found. Returns None when no
    PROGRAM-ID is declared (caller falls back to the file stem)."""
    try:
        cr = _cob._import_copybook_resolver()  # the same resolver the extractor uses
        rr = cr.resolve_file(path, [Path(p) for p in copybook_paths])
        lines = _cob._lines_from_resolve_result(rr)
        return _cob.extract_program_id(lines)
    except Exception:
        return None


# ==============================================================================
# event_time (deterministic; honours SOURCE_DATE_EPOCH for a reproducible run)
# ==============================================================================
def _resolve_event_time() -> str:
    """Return the OL eventTime.

    Default is the emitter's fixed deterministic time (byte-identical re-run).
    If SOURCE_DATE_EPOCH is set (reproducible-build convention), use it so a real
    run carries a meaningful — yet still deterministic — timestamp."""
    sde = os.environ.get("SOURCE_DATE_EPOCH")
    if sde:
        try:
            import datetime as _dt

            ts = int(sde)
            return (
                _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ")
            )
        except (ValueError, OverflowError, OSError):
            pass
    return _emit.DEFAULT_EVENT_TIME


# ==============================================================================
# CLI
# ==============================================================================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_lineage.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--src", action="append", default=[], metavar="PATH",
        help="A COBOL/JCL source file, a directory (recursed), or a glob "
             "(repeatable). At least one of --src / --controlm is required.",
    )
    p.add_argument(
        "--controlm", action="append", default=[], metavar="PATH",
        help="A Control-M Automation-API jobs-as-code JSON file (repeatable). "
             "EXPLICIT-FLAG-AUTHORITATIVE: files passed here are forced "
             "kind='controlm' (bypassing the COBOL/JCL classifier) — the "
             "canonical, documented Control-M invocation.",
    )
    p.add_argument(
        "--controlm-connection-profiles", default=None, metavar="JSON",
        help="Optional Control-M connection-profile map (a JSON object or a path "
             "to a JSON file): profile_name -> {host,port,db,schema}. The "
             "Control-M analogue of --db2-catalog. A Job:Database edge resolves "
             "to a real DB2 table node only when its ConnectionProfile is present "
             "here AND the SQL is literal; else it is forced speculative + a gap.",
    )
    p.add_argument(
        "--copybook-path", action="append", default=[], metavar="DIR",
        help="Copybook search directory for COPY resolution (repeatable).",
    )
    p.add_argument(
        "--jcl-proc-path", action="append", default=[], metavar="DIR",
        help="JCL PROC/INCLUDE library directory (repeatable).",
    )
    p.add_argument(
        "--out", type=Path, required=True, metavar="PATH",
        help="OpenLineage 2.0.2 ndjson output path.",
    )
    p.add_argument(
        "--engine", choices=["auto", "regex", "sqlglot-sql"], default="auto",
        help="SQL engine: auto (sqlglot if present else regex), regex (force "
             "stdlib regex), or sqlglot-sql (REQUIRE sqlglot — fail-LOUD if "
             "absent). Default: auto. NEVER an LLM (C2).",
    )
    p.add_argument(
        "--source-format", choices=["fixed"], default="fixed",
        help="COBOL source format. v1 supports fixed only; free-format sources "
             "emit a free_format_unsupported gap (not a failure). Default: fixed.",
    )
    p.add_argument(
        "--db2-catalog", default=None, metavar="PATH_OR_DSN",
        help="Optional DB2 catalog reference. Absent -> column edges are forced "
             "speculative + a catalog_less_column gap (#158).",
    )
    p.add_argument(
        "--schema", default=None, metavar="SCHEMA",
        help="Optional default DB2 schema. Absent -> the verbatim <schema> "
             "naming-contract placeholder + catalog_less_column gaps.",
    )
    p.add_argument(
        "--copybook-missing", choices=["gap", "fail"], default="gap",
        help="On an unresolved COPY: gap (emit an unresolved_copy gap and "
             "continue — default) or fail (exit non-zero).",
    )
    p.add_argument(
        "--check-deps", action="store_true",
        help="Print the dependency doctor (active interpreter, present/missing "
             "OPTIONAL enhancers, what degrades, and a PEP-668-safe install recipe) "
             "and exit. Does NOT need --src/--out. The core is pure stdlib and the "
             "skill never pip-installs at runtime.",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    # --check-deps is a standalone doctor: short-circuit BEFORE the --out/--src
    # requirements so a user can probe their environment without a real run.
    _av = list(sys.argv[1:] if argv is None else argv)
    if "--check-deps" in _av:
        # Load THIS skill's check_deps.py by explicit path — a bare `import
        # check_deps` is ambiguous because lineage-extract-static/scripts (which
        # also ships a check_deps.py) is on sys.path for the shared OL validator.
        import importlib.util as _ilu
        _cd_path = Path(__file__).resolve().parent / "check_deps.py"
        _spec = _ilu.spec_from_file_location("_mlp_check_deps", _cd_path)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod.report()

    parser = build_parser()
    args = parser.parse_args(argv)

    # --- at least one input required ------------------------------------------
    if not args.src and not args.controlm:
        print("ERROR: at least one of --src / --controlm is required.",
              file=sys.stderr)
        return 1

    # --- discover + classify --src sources (no prompts) -----------------------
    sources, missing = _expand_sources(args.src) if args.src else ([], [])
    if missing:
        print(
            "ERROR: no files matched these --src arguments: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    # --- Control-M sources are explicit-flag-authoritative (forced kind) ------
    controlm_sources: List[Path] = []
    controlm_missing: List[str] = []
    for raw in args.controlm:
        p = Path(raw)
        if p.is_file():
            controlm_sources.append(p.resolve())
        else:
            controlm_missing.append(raw)
    if controlm_missing:
        print(
            "ERROR: no files matched these --controlm arguments: "
            + ", ".join(controlm_missing),
            file=sys.stderr,
        )
        return 1
    controlm_sources = sorted(set(controlm_sources), key=lambda x: str(x))

    if not sources and not controlm_sources:
        print("ERROR: no usable COBOL/JCL/Control-M files were matched.",
              file=sys.stderr)
        return 1

    # --- parse the Control-M connection-profile map (object or file) ----------
    controlm_profiles: dict = {}
    if args.controlm_connection_profiles:
        try:
            controlm_profiles = _parse_controlm_profiles(args.controlm_connection_profiles)
        except (ValueError, OSError) as e:
            print(f"ERROR: --controlm-connection-profiles is not valid JSON: {e}",
                  file=sys.stderr)
            return 1

    copybook_paths = [Path(p) for p in args.copybook_path]
    proc_paths = [Path(p) for p in args.jcl_proc_path]
    diagnostics: List[str] = []
    slices: List["object"] = []

    # --- build the (path, kind) extraction list -------------------------------
    # Control-M files carry a forced kind that BYPASSES _classify entirely.
    work: List[Tuple[Path, str]] = [(src, _classify(src)) for src in sources]
    work.extend((cm_src, "controlm") for cm_src in controlm_sources)

    # --- extract every source (chain) -----------------------------------------
    for src, kind in work:
        try:
            slices.extend(
                _extract_one(
                    src, kind,
                    copybook_paths=copybook_paths,
                    proc_paths=proc_paths,
                    engine=args.engine,
                    schema=args.schema,
                    db2_catalog=args.db2_catalog,
                    diagnostics=diagnostics,
                    controlm_profiles=controlm_profiles,
                )
            )
        except _sql.SqlglotUnavailableError as e:
            # fail-LOUD handoff (exit 2) — NEVER auto-invoke an LLM (C2).
            print(f"FAIL-LOUD: --engine=sqlglot-sql but sqlglot is not "
                  f"importable.\n{e}\n{LLM_HANDOFF}", file=sys.stderr)
            return 2
        except OSError as e:
            print(f"ERROR: cannot read source {src}: {e}", file=sys.stderr)
            return 1

    if not slices:
        print("ERROR: no IR was produced from any source (unusable input).",
              file=sys.stderr)
        return 1

    # --- assemble (canonical sort + dedupe + DDNAME stitch) -------------------
    assembled = _ga.assemble(slices)

    # --- --copybook-missing=fail gate -----------------------------------------
    n_unresolved = _count_unresolved_copy(assembled.ir)
    if args.copybook_missing == "fail" and n_unresolved:
        print(
            f"ERROR: --copybook-missing=fail and {n_unresolved} unresolved COPY "
            f"member(s) remain. Provide --copybook-path or use "
            f"--copybook-missing=gap to continue.",
            file=sys.stderr,
        )
        return 3

    # --- emit (fail-CLOSED OL 2.0.2; deterministic) ---------------------------
    event_time = _resolve_event_time()
    engine_for_facet = _chosen_engine(slices)
    try:
        summary = _emit.emit_openlineage(
            assembled.ir, args.out, engine=engine_for_facet, event_time=event_time
        )
    except ValueError as e:
        print(f"FAIL-CLOSED: an event failed OL 2.0.2 validation; nothing "
              f"written.\n{e}", file=sys.stderr)
        return 1
    except (FileNotFoundError, OSError) as e:
        print(f"ERROR: cannot write --out {args.out}: {e}", file=sys.stderr)
        return 1

    # --- report (machine-readable on stdout; diagnostics on stderr) -----------
    summary["sources"] = len(work)
    summary["unresolved_copy"] = n_unresolved
    summary["diagnostics"] = diagnostics
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    for d in diagnostics:
        print(f"DIAGNOSTIC: {d}", file=sys.stderr)
    return 0


def _chosen_engine(slices: Sequence["object"]) -> str:
    """The engine that actually ran for the SQL facet.

    Prefer the SqlExtractResult.chosen_engine ('sqlglot'|'regex'); if there was
    no SQL at all, stamp 'stdlib' (the COBOL/JCL extractors are pure stdlib)."""
    for s in slices:
        ce = getattr(s, "chosen_engine", None)
        if ce:
            return ce
    return "stdlib"


if __name__ == "__main__":
    raise SystemExit(main())
