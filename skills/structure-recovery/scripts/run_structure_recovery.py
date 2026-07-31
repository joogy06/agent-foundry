#!/usr/bin/env python3
"""structure-recovery — end-to-end pipeline driver (WP-11).

Wires the whole pipeline the SKILL.md documents:

    discover files
      -> [per file] boundary-hint pre-pass (boundary_hints.safe_break_lines)
      -> chunk (chunk_file.chunk_file, with preferred_break_lines)
      -> [per chunk] LLM extraction (the in-session AI CLI, via the prompts/)
         -> validate (validate_finding.validate_finding_or_abort)
      -> accumulate (accumulate_structure.accumulate_structure: merge partials,
         dedup, DETERMINISTIC offset compute via cobol_offset_calc)
      -> [resumable] run-state checkpoint + content-addressed skip ladder
         (run_state.py: probe HIT -> 0 LLM calls; partial -> first missing chunk)
    [cross-file]
      -> build the structure-index.v1 catalog (fold per-file summaries)
      -> resolve relationships + K2 honesty caps (relationships.resolve_relationships)
    render
      -> HTML + CSV + inferred DDL          (render_structure.render_all)
      -> Excel                              (render_structure.render_excel)
      -> wiki pages                         (render_structure.render_wiki)
      -> OpenLineage SchemaDatasetFacet     (render_structure.render_ol_schema_facets)

This is a THIN orchestration glue layer. It owns ZERO new structure logic: every
step composes a script delivered by an earlier WP (loaded by path so the skill
stays import-flat and layout-stable; the sibling chunk_file lives in
lineage-extract-static). It is CB4-safe — it writes ONLY under the run cache
(0700, NOT /tmp) and the caller-chosen output dir; it never touches `.ledger/`,
`progress/`, or any ledger artifact.

LLM-AS-PARSER seam (decision N2). The per-chunk extraction is the ONE step the
Python cannot do: a model-neutral prompt (prompts/analyze-<format>.md) instructs
the in-session AI CLI to emit ONE structure-finding.v1 JSON object per chunk.
In normal operation the AI CLI runs that loop and writes each
``chunk_NNNN.jsonl`` finding into the run cache before this driver's accumulate
pass. The driver exposes an ``analyzer`` hook so:

  * the in-session AI CLI (or a wrapper) supplies the real per-chunk analysis;
  * tests supply a deterministic stand-in (no live model needed) to exercise the
    full discover->chunk->validate->accumulate->cross-file->render flow end to end.

When no analyzer is supplied AND a chunk has no pre-written finding, the chunk is
left as a placeholder; accumulate_structure already turns that into an HONEST
catalog gap ("chunk N not yet analyzed by the AI CLI's LLM") rather than a
fabricated entity. Resumability then means: re-running with the findings present
(or the store warm) resumes at the first missing chunk.

Pure stdlib. Deterministic given a fixed analyzer + SOURCE_DATE_EPOCH.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# Locate sibling/own scripts and import them by PATH (layout-stable, import-flat).
# The structure-recovery scripts live alongside this file; chunk_file lives in
# the lineage-extract-static sibling skill.
# --------------------------------------------------------------------------- #
_THIS = Path(__file__).resolve()
_SR_SCRIPTS = _THIS.parent                                   # .../structure-recovery/scripts
_SR_ROOT = _SR_SCRIPTS.parent                                # .../structure-recovery
_SR_SCHEMAS = _SR_ROOT / "schemas"
_SKILLS_ROOT = _SR_ROOT.parent                               # .../skills
_LINEAGE_SCRIPTS = _SKILLS_ROOT / "lineage-extract-static" / "scripts"

EXTRACTOR_ID = "structure-recovery"
EXTRACTOR_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"

# Structure formats this skill understands (drives discovery + which prompt to use).
# The chunker's detect_language_hint maps extensions; this is the discovery filter.
STRUCTURE_EXTENSIONS = {
    ".sql": "sql",
    ".ddl": "sql",
    ".dsx": "dsx",
    ".cbl": "cobol",
    ".cob": "cobol",
    ".cobol": "cobol",
    ".cpy": "copybook",
    ".fd": "flat-file-layout",
    ".layout": "flat-file-layout",
    ".txt": "flat-file-layout",  # positional/delimited layouts often ship as .txt
}


def _load(name: str, path: Path):
    """Import a script module by path, registering it in ``sys.modules`` BEFORE
    exec so ``from __future__ import annotations`` string annotations resolve
    (the WP-2/WP-5/WP-6 test idiom)."""
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:  # pragma: no cover - defensive
        raise ImportError(f"cannot load module spec from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Lazily-bound module handles (bound on first use so a partial install or a
# missing optional dep degrades the AFFECTED step, not the whole import).
_MODS: Dict[str, object] = {}


def _mod(name: str):
    if name in _MODS:
        return _MODS[name]
    if name == "chunk_file":
        mod = _load("sr_chunk_file", _LINEAGE_SCRIPTS / "chunk_file.py")
    elif name == "boundary_hints":
        mod = _load("sr_boundary_hints", _SR_SCRIPTS / "boundary_hints.py")
    elif name == "validate_finding":
        mod = _load("sr_validate_finding", _SR_SCRIPTS / "validate_finding.py")
    elif name == "accumulate_structure":
        mod = _load("sr_accumulate_structure", _SR_SCRIPTS / "accumulate_structure.py")
    elif name == "relationships":
        mod = _load("sr_relationships", _SR_SCRIPTS / "relationships.py")
    elif name == "render_structure":
        mod = _load("sr_render_structure", _SR_SCRIPTS / "render_structure.py")
    elif name == "run_state":
        mod = _load("sr_run_state", _SR_SCRIPTS / "run_state.py")
    else:  # pragma: no cover - defensive
        raise KeyError(name)
    _MODS[name] = mod
    return mod


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def discover_files(root: Path, *, follow_symlinks: bool = False) -> List[Path]:
    """Return the sorted list of structure-bearing files under ``root``.

    Deterministic (sorted by relative POSIX path). A single file path is returned
    as-is when it carries a structure extension. Hidden dirs (``.git`` etc.) and
    the run/cache dirs are skipped.
    """
    root = root.resolve()
    if root.is_file():
        return [root] if root.suffix.lower() in STRUCTURE_EXTENSIONS else []

    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        # Prune hidden + obvious noise dirs in-place for determinism + speed.
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".") and d not in {"__pycache__", "node_modules"}
        )
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if p.suffix.lower() in STRUCTURE_EXTENSIONS:
                out.append(p)
    out.sort(key=lambda p: p.resolve().relative_to(root).as_posix())
    return out


# Prompts that drive the LLM-as-parser extraction; their content folds into the
# job fingerprint so a prompt edit invalidates a warm cache (design §3.5).
_PROMPT_FILES = (
    "analyze-sql.md", "analyze-dsx.md", "analyze-cobol.md", "analyze-flatfile.md",
    "merge.md", "redact.md",
)


def prompt_template_hash() -> str:
    """sha256 over the analysis prompt bodies (sorted, NUL-separated).

    Folded into ``run_state.job_fingerprint`` so editing a prompt (which changes
    how the LLM parses) produces a NEW job fingerprint -> no stale cache served.
    If a prompt file is missing the byte ``b"<missing>"`` is folded so the hash
    is still stable and total.
    """
    h = hashlib.sha256()
    for name in sorted(_PROMPT_FILES):
        h.update(name.encode("utf-8"))
        h.update(b"\x00")
        p = _SR_ROOT / "prompts" / name
        try:
            h.update(p.read_bytes())
        except OSError:
            h.update(b"<missing>")
        h.update(b"\x00")
    return h.hexdigest()


def default_model_id() -> str:
    """Stable identifier for the model that ran the LLM-as-parser step.

    The in-session AI CLI is the parser (N2), so there is no single API model id
    to read; we fold a host-neutral, override-able tag (``STRUCT_MODEL_ID`` env)
    into the fingerprint so a deliberate model swap invalidates the cache while a
    re-run on the same host resumes. Default mirrors the family convention.
    """
    return os.environ.get("STRUCT_MODEL_ID", "in-session-ai-cli")


def format_for_file(path: Path) -> str:
    """Map a file to its analysis format (which prompt to use)."""
    fmt = STRUCTURE_EXTENSIONS.get(path.suffix.lower())
    if fmt in (None, "copybook"):
        # copybook is analysed with the COBOL prompt.
        return "cobol"
    if fmt == "flat-file-layout":
        return "flatfile"
    return fmt


# --------------------------------------------------------------------------- #
# Analyzer hook — the LLM-as-parser seam (N2).
# --------------------------------------------------------------------------- #
# An analyzer is: (chunk_text, format_name, chunk_meta) -> structure-finding.v1 dict
# It returns the per-chunk finding the in-session AI CLI would emit per the
# prompts/analyze-<format>.md instructions. The driver validates whatever the
# analyzer returns and writes it as chunk_NNNN.jsonl.
Analyzer = Callable[[str, str, dict], Optional[dict]]


def _read_chunk_text(file_path: Path, start_byte: int, end_byte: int) -> str:
    """Read a chunk's raw text by byte span (mirrors the placeholder span)."""
    with file_path.open("rb") as f:
        f.seek(start_byte)
        raw = f.read(max(0, end_byte - start_byte))
    return raw.decode("utf-8", errors="replace")


def _placeholder_meta(artifact_dir: Path, chunk_index: int) -> Optional[dict]:
    """Read the chunk placeholder JSON (start/end byte/line, language hint)."""
    ph = artifact_dir / f"chunk_{chunk_index:04d}.jsonl.placeholder"
    if not ph.exists():
        return None
    try:
        with ph.open("r", encoding="utf-8") as f:
            return json.loads(f.readline())
    except (OSError, ValueError):  # pragma: no cover - defensive
        return None


def _write_finding(artifact_dir: Path, chunk_index: int, finding: dict) -> Path:
    """Atomically write a validated finding as chunk_NNNN.jsonl (one JSON line)."""
    rs = _mod("run_state")  # reuse the atomic-json helper family for parity
    out = artifact_dir / f"chunk_{chunk_index:04d}.jsonl"
    # accumulate_structure.read_chunk_findings reads the FIRST json line; write
    # a single canonical line atomically (tmp + os.replace) under the 0700 dir.
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix=out.name + ".tmp.", suffix=f".{os.getpid()}", dir=str(artifact_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(finding, ensure_ascii=False, sort_keys=True))
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, out)
    except Exception:  # pragma: no cover - defensive
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return out


# --------------------------------------------------------------------------- #
# Per-file processing (chunk -> analyze -> validate -> accumulate), resumable.
# --------------------------------------------------------------------------- #
def process_file(
    file_path: Path,
    run_dir: Path,
    *,
    analyzer: Optional[Analyzer] = None,
    chunk_size_lines: Optional[int] = None,
    overlap_lines: Optional[int] = None,
) -> dict:
    """Chunk + (analyze) + accumulate ONE file. Returns its summary.json dict.

    Resumable at the chunk granularity: a chunk that already has a
    ``chunk_NNNN.jsonl`` finding on disk is NOT re-analyzed (filesystem = truth).
    An un-analyzed chunk with no analyzer becomes an honest gap downstream.
    """
    cf = _mod("chunk_file")
    bh = _mod("boundary_hints")
    vf = _mod("validate_finding")
    acc = _mod("accumulate_structure")

    csz = chunk_size_lines if chunk_size_lines is not None else cf.STRUCT_CHUNK_LINES
    ovl = overlap_lines if overlap_lines is not None else cf.STRUCT_OVERLAP_LINES

    fmt = format_for_file(file_path)
    text = file_path.read_text(encoding="utf-8", errors="replace")

    # 1) boundary-hint pre-pass (pure, no LLM, no XML parser — N2).
    breaks = bh.safe_break_lines(text, fmt)

    # 2) chunk into the run cache (0700, NOT /tmp), record-aware.
    cache_root = run_dir / "files-cache"
    manifest = cf.chunk_file(
        file_path,
        run_id="structure",
        chunk_size_lines=csz,
        overlap_lines=ovl,
        cache_root=cache_root,
        preferred_break_lines=breaks or None,
    )
    file_sha = manifest["sha256"]
    artifact_dir = cache_root / "structure" / "files" / file_sha
    chunk_count = manifest.get("chunk_count", 0)

    # 3) per-chunk LLM extraction (the analyzer seam) — skip chunks already done.
    if analyzer is not None and chunk_count:
        for i in range(1, chunk_count + 1):
            done = artifact_dir / f"chunk_{i:04d}.jsonl"
            if done.exists():
                continue  # filesystem = truth: resume, do not re-analyze
            meta = _placeholder_meta(artifact_dir, i)
            if meta is None:
                continue
            chunk_text = _read_chunk_text(file_path, meta["start_byte"], meta["end_byte"])
            finding = analyzer(chunk_text, fmt, meta)
            if finding is None:
                continue  # analyzer abstained -> honest gap downstream
            # Validate BEFORE persisting — the offset-rejection rule (WP-1) and
            # enum/structural checks. A bad finding aborts loudly (fail-closed).
            vf.validate_finding_or_abort(finding, _SR_SCHEMAS / "structure-finding.v1.json")
            _write_finding(artifact_dir, i, finding)

    # 4) accumulate -> per-file summary.json (merge, dedup, COBOL offsets).
    summary = acc.accumulate_structure(artifact_dir, run_id="structure", file_sha256=file_sha, overlap_lines=ovl)
    return summary


# --------------------------------------------------------------------------- #
# Cross-file pass — fold per-file summaries into a structure-index.v1 catalog.
# --------------------------------------------------------------------------- #
def build_catalog(summaries: Sequence[dict], *, job_fingerprint: str, infer_relationships: bool) -> dict:
    """Fold per-file summaries into the cross-file structure-index.v1 catalog,
    then resolve relationships with the K2 honesty caps.

    Identity canonicalization is by (object_kind, qualified_name): the same entity
    seen in multiple files unions its fields (later files fill nulls; lower
    confidence wins, mirroring the in-file accumulate idiom). Relationships from
    every file are pooled, then ``relationships.resolve_relationships`` applies the
    declared/convention/JOIN/COBOL caps (advisory-only; never feeds a gate).
    """
    acc = _mod("accumulate_structure")
    rel = _mod("relationships")

    # --- union entities by identity ---------------------------------------- #
    by_key: Dict[Tuple[str, str], dict] = {}
    order: List[Tuple[str, str]] = []
    for summ in summaries:
        for ent in summ.get("entities", []):
            key = (ent.get("object_kind", ""), ent.get("qualified_name", ""))
            if key not in by_key:
                by_key[key] = json.loads(json.dumps(ent))  # deep copy
                order.append(key)
            else:
                _merge_entity_into(by_key[key], ent, acc)

    entities = [by_key[k] for k in order]

    # --- pool raw relationships + catalog gaps ----------------------------- #
    raw_rels: List[dict] = []
    gaps: List[dict] = []
    for summ in summaries:
        raw_rels.extend(summ.get("relationships", []))
        gaps.extend(summ.get("gaps", []))

    catalog = {
        "schema_version": SCHEMA_VERSION,
        "extractor_id": EXTRACTOR_ID,
        "extractor_version": EXTRACTOR_VERSION,
        "generated_with": {
            "job_fingerprint": job_fingerprint,
            "infer_relationships": bool(infer_relationships),
        },
        "entities": _sort_entities(entities),
        "relationships": [],          # filled by resolve_relationships
        "gaps": _dedup_gaps(gaps),
    }
    # Seed the raw relationships so resolve_relationships sees declared edges, then
    # replace with the resolved + capped set.
    catalog["relationships"] = raw_rels
    catalog["relationships"] = rel.resolve_relationships(catalog, infer_relationships=infer_relationships)
    return catalog


def _merge_entity_into(dst: dict, src: dict, acc) -> None:
    """Union ``src`` entity fields into ``dst`` (cross-file same-identity merge).

    Reuses the in-file merge semantics: dedup by (name, ordinal), fill null
    declared facts, lower-confidence-wins. Group/gap lists are unioned + deduped.
    """
    dst_fields = {(_f.get("name"), _f.get("ordinal")): _f for _f in dst.get("fields", [])}
    for f in src.get("fields", []):
        k = (f.get("name"), f.get("ordinal"))
        if k not in dst_fields:
            dst.setdefault("fields", []).append(json.loads(json.dumps(f)))
            dst_fields[k] = dst["fields"][-1]
        else:
            existing = dst_fields[k]
            # lower-confidence-wins on the merged field
            ec = existing.get("confidence")
            sc = f.get("confidence")
            if ec and sc:
                existing["confidence"] = acc._min_conf(ec, sc)
            # fill null declared facts from src
            for fk, fv in f.items():
                if existing.get(fk) in (None, "") and fv not in (None, ""):
                    existing[fk] = fv
    # entity confidence: lower wins
    if dst.get("confidence") and src.get("confidence"):
        dst["confidence"] = acc._min_conf(dst["confidence"], src["confidence"])
    # union gaps
    dst_gaps = dst.setdefault("gaps", [])
    for g in src.get("gaps", []):
        if g not in dst_gaps:
            dst_gaps.append(g)


def _sort_entities(entities: List[dict]) -> List[dict]:
    return sorted(entities, key=lambda e: (e.get("object_kind", ""), e.get("qualified_name", "")))


def _dedup_gaps(gaps: List[dict]) -> List[dict]:
    seen = set()
    out: List[dict] = []
    for g in gaps:
        key = (g.get("kind"), g.get("file_path"), g.get("line"), g.get("description"))
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    return out


# --------------------------------------------------------------------------- #
# Rendering — compose every emitter on the frozen catalog.
# --------------------------------------------------------------------------- #
def render_catalog(
    catalog: dict,
    output_dir: Path,
    *,
    project_name: str = "project",
    no_vendor: bool = False,
    source_date_epoch: Optional[int] = None,
    emit_excel: bool = True,
    emit_wiki: bool = True,
    emit_ol: bool = True,
    wiki_role: str = "specific",
    allow_shared_write: bool = False,
) -> Dict[str, object]:
    """Render ALL outputs (HTML + CSV + DDL + catalog.json + Excel + wiki + OL).

    Returns a dict of produced paths (Excel/OL may be ``None`` when their optional
    composition dep — openpyxl / the OL sibling — is absent: a sanctioned skip,
    not a failure; the rest of the catalog is intact).
    """
    rs = _mod("render_structure")
    output_dir.mkdir(parents=True, exist_ok=True)

    produced: Dict[str, object] = {}

    # Persist the queryable catalog itself (structure-index.v1).
    catalog_path = output_dir / "structure-index.json"
    rs.atomic_write_text(catalog_path, json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    produced["catalog"] = catalog_path

    # HTML + CSV + DDL.
    produced.update(rs.render_all(
        catalog, output_dir,
        no_vendor=no_vendor, project_name=project_name, source_date_epoch=source_date_epoch,
    ))

    if emit_excel:
        produced["excel"] = rs.render_excel(catalog, output_dir)
    if emit_wiki:
        produced["wiki"] = rs.render_wiki(
            catalog, output_dir,
            project_name=project_name, wiki_role=wiki_role,
            allow_shared_write=allow_shared_write, source_date_epoch=source_date_epoch,
        )
    if emit_ol:
        produced["ol_schema_facets"] = rs.render_ol_schema_facets(catalog, output_dir)

    return produced


# --------------------------------------------------------------------------- #
# Top-level orchestration.
# --------------------------------------------------------------------------- #
def run(
    target: Path,
    output_dir: Path,
    *,
    analyzer: Optional[Analyzer] = None,
    infer_relationships: bool = False,
    project_name: Optional[str] = None,
    no_vendor: bool = False,
    source_date_epoch: Optional[int] = None,
    chunk_size_lines: Optional[int] = None,
    overlap_lines: Optional[int] = None,
    emit_excel: bool = True,
    emit_wiki: bool = True,
    emit_ol: bool = True,
    wiki_role: str = "specific",
    allow_shared_write: bool = False,
    run_dir: Optional[Path] = None,
) -> Dict[str, object]:
    """Run the full pipeline over ``target`` (a file or a directory tree).

    Returns ``{"catalog": catalog_dict, "files": [relpaths], "outputs": {...},
    "job_fingerprint": str, "status": "complete"|"partial"}``.

    Resumability: a content-addressed run dir under ``output_dir/.run`` (0700).
    Re-running with findings already on disk resumes (no re-analysis); the
    self-healing reconcile in run_state rebuilds chunks_done from the filesystem.
    """
    target = target.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rd = (run_dir or (output_dir / ".run")).resolve()
    rd.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(rd, 0o700)
    except OSError:  # pragma: no cover - best effort
        pass

    if project_name is None:
        project_name = target.name or "project"

    files = discover_files(target)

    # Job fingerprint over the selected file set + options (run_state, wraps —
    # never widens — legacy-code-intel pipeline_fingerprint; §9 note 2).
    rs_state = _mod("run_state")
    root_for_fp = target if target.is_dir() else target.parent
    job_fp = rs_state.job_fingerprint(
        project_root=root_for_fp,
        files=files,
        prompt_hash=prompt_template_hash(),
        model_id=default_model_id(),
        infer_relationships=infer_relationships,
        options={"infer_relationships": infer_relationships},
    )

    # Per-file: chunk -> analyze -> accumulate (resumable at chunk granularity).
    summaries: List[dict] = []
    files_done: List[str] = []
    for fp in files:
        summ = process_file(
            fp, rd,
            analyzer=analyzer,
            chunk_size_lines=chunk_size_lines,
            overlap_lines=overlap_lines,
        )
        summaries.append(summ)
        files_done.append(fp.resolve().as_posix())

    # Cross-file -> catalog (+ K2-capped relationships).
    catalog = build_catalog(summaries, job_fingerprint=job_fp, infer_relationships=infer_relationships)

    # Honest status: if any entity/gap reports an un-analyzed chunk, this is PARTIAL.
    status = "complete"
    for summ in summaries:
        for g in summ.get("gaps", []):
            if "not yet analyzed" in (g.get("description") or ""):
                status = "partial"
                break

    outputs = render_catalog(
        catalog, output_dir,
        project_name=project_name, no_vendor=no_vendor, source_date_epoch=source_date_epoch,
        emit_excel=emit_excel, emit_wiki=emit_wiki, emit_ol=emit_ol,
        wiki_role=wiki_role, allow_shared_write=allow_shared_write,
    )

    return {
        "catalog": catalog,
        "files": files_done,
        "outputs": outputs,
        "job_fingerprint": job_fp,
        "status": status,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "structure-recovery pipeline driver. Discovers structure-bearing "
            "files (SQL/DSX/COBOL+copybook/flat-file), chunks them, accumulates "
            "the per-chunk LLM findings the in-session AI CLI emits per "
            "prompts/analyze-*.md, resolves K2-capped relationships, and renders "
            "HTML/CSV/DDL/Excel/wiki/OpenLineage. The per-chunk LLM extraction is "
            "performed by the in-session AI CLI (LLM-as-parser, N2); this CLI "
            "orchestrates everything around it and is resumable."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("target", type=Path, help="File or directory tree to analyze")
    parser.add_argument("--output-dir", type=Path, required=True, help="Where to write outputs")
    parser.add_argument("--infer-relationships", action="store_true",
                        help="Opt-in COBOL cross-record FK inference (decision O2; capped speculative, commented DDL only)")
    parser.add_argument("--project-name", default=None)
    parser.add_argument("--no-vendor", action="store_true", help="Skip vendored Cytoscape; CDN/Mermaid fallback")
    parser.add_argument("--source-date-epoch", type=int, default=None, help="Pin output timestamps for determinism")
    parser.add_argument("--chunk-size-lines", type=int, default=None)
    parser.add_argument("--overlap-lines", type=int, default=None)
    parser.add_argument("--no-excel", action="store_true")
    parser.add_argument("--no-wiki", action="store_true")
    parser.add_argument("--no-ol", action="store_true")
    parser.add_argument("--list-only", action="store_true",
                        help="Only discover + print the structure files (no analysis)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.list_only:
        for fp in discover_files(args.target.resolve()):
            print(fp)
        return 0

    # No analyzer is wired from the CLI: in real operation the in-session AI CLI
    # writes the per-chunk findings (per the prompts) BETWEEN chunking and this
    # accumulate pass. Running the CLI directly (no pre-written findings, no
    # analyzer) yields an HONEST partial catalog of gaps — never fabricated
    # entities. The flow, resumability, and rendering all still exercise.
    result = run(
        args.target,
        args.output_dir,
        analyzer=None,
        infer_relationships=args.infer_relationships,
        project_name=args.project_name,
        no_vendor=args.no_vendor,
        source_date_epoch=args.source_date_epoch,
        chunk_size_lines=args.chunk_size_lines,
        overlap_lines=args.overlap_lines,
        emit_excel=not args.no_excel,
        emit_wiki=not args.no_wiki,
        emit_ol=not args.no_ol,
    )
    summary = {
        "status": result["status"],
        "job_fingerprint": result["job_fingerprint"],
        "files": len(result["files"]),
        "entities": len(result["catalog"].get("entities", [])),
        "relationships": len(result["catalog"].get("relationships", [])),
        "outputs": {k: (str(v) if v is not None else None) for k, v in result["outputs"].items()},
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
