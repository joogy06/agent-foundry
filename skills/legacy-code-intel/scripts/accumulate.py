#!/usr/bin/env python3
"""accumulate.py — per-artifact rollup with deterministic boundary handling.

Forked from lineage-extract-static/scripts/accumulate.py. Lineage pairs data-flow
EDGES across chunk boundaries; legacy-code-intel pairs the SCIP triad —
symbols (content-addressed, deduped by symbol_id), occurrences, and relationships.

The boundary problem for code: a COBOL `CALL 'SUBPGM'` or a copybook `COPY` can be
split across a 2000-line chunk boundary, producing a duplicate or half-resolved
relationship. The deterministic predicate (NO LLM judgment — HARD-RULE 3):

  - Symbols: union, deduped by symbol_id (content-addressed => identical IDs from
    overlapping chunks merge to one). Keep the richest record (with signature /
    container) when duplicates differ.
  - Occurrences: deduped by (symbol_id, role, start_line, end_line). Overlap
    regions between adjacent chunks naturally produce duplicate occurrences for
    the same line range — these collapse to one. The more conservative confidence
    wins on a collision.
  - Relationships: deduped by (rel, from_id, to_id). A relationship that appears
    in a chunk marked partial_end AND in the next chunk's partial_start within
    LCI_OVERLAP_LINES is the SAME relationship (paired -> single, keeping the
    lower confidence). A relationship that is partial at a boundary with NO
    matching half in the adjacent overlap is downgraded to speculative +
    boundary_issue (honest disclosure, never silently dropped).

Atomic writes via .tmp.<pid> + os.replace (HARD-RULE 3). Idempotent on re-run.

CLI usage:
    accumulate.py <chunk_dir_path> <run_id> <file_sha256> [--overlap-lines N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

DEFAULT_OVERLAP_LINES = int(os.environ.get("LCI_OVERLAP_LINES", "50"))

_CONF_RANK = {"grounded": 3, "inferred": 2, "speculative": 1}


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".tmp.", suffix=f".{os.getpid()}", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def read_chunk_finding(chunk_path: Path) -> Optional[dict]:
    """Read one chunk_NNNN.jsonl. Returns the code-finding.v1 dict (the LLM's
    emission — the LAST non-placeholder JSON line with symbols/occurrences keys)
    or None if not yet analyzed."""
    if not chunk_path.exists():
        return None
    last = None
    with chunk_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("status") == "awaiting_analysis":
                continue
            if "symbols" in obj and "occurrences" in obj and "relationships" in obj:
                last = obj
    return last


# ---------------- Deterministic merge helpers ---------------- #

def _symbol_richness(sym: dict) -> int:
    """Higher = more complete (prefer keeping the record with signature/container)."""
    score = 0
    if sym.get("signature"):
        score += 2
    if sym.get("container_symbol_id"):
        score += 1
    if sym.get("attributes"):
        score += 1
    return score


def merge_symbols(chunks: list) -> list:
    by_id: dict = {}
    for chunk in chunks:
        for sym in chunk.get("symbols", []):
            sid = sym.get("symbol_id")
            if not sid:
                continue
            if sid not in by_id or _symbol_richness(sym) > _symbol_richness(by_id[sid]):
                by_id[sid] = dict(sym)
    return sorted(by_id.values(), key=lambda s: (s.get("symbol_id", ""), s.get("kind", "")))


def _occ_key(occ: dict) -> tuple:
    r = occ.get("range", {})
    return (occ.get("symbol_id", ""), occ.get("role", ""), r.get("start_line", 0), r.get("end_line", 0))


def merge_occurrences(chunks: list) -> list:
    """Dedup occurrences by (symbol_id, role, start_line, end_line). On a
    collision (overlap region), keep the MORE conservative (lower) confidence."""
    by_key: dict = {}
    for chunk in chunks:
        for occ in chunk.get("occurrences", []):
            k = _occ_key(occ)
            existing = by_key.get(k)
            if existing is None:
                by_key[k] = dict(occ)
            else:
                if _CONF_RANK.get(occ.get("confidence"), 0) < _CONF_RANK.get(existing.get("confidence"), 0):
                    by_key[k] = dict(occ)

    def sort_key(o):
        r = o.get("range", {})
        return (r.get("start_line", 0), r.get("end_line", 0), o.get("symbol_id", ""), o.get("role", ""))

    return sorted(by_key.values(), key=sort_key)


def _rel_key(rel: dict) -> tuple:
    return (rel.get("rel", ""), rel.get("from_id", ""), rel.get("to_id", ""))


def merge_relationships(chunks: list, overlap_lines: int) -> tuple:
    """Dedup relationships by (rel, from_id, to_id). Boundary pairing:

    A relationship in a chunk whose boundary_status is partial_end/partial_both,
    whose evidence_line falls in the last `overlap_lines` of the chunk, is a
    boundary candidate. If the SAME key appears in the next chunk's overlap, they
    pair (single relationship, lower confidence kept). If a boundary candidate has
    NO matching half, it is downgraded to speculative + flagged via a returned gap
    (honest disclosure — never silently dropped).

    Returns (merged_relationships, boundary_gaps).
    """
    # Index by key; track which (chunk_idx, evidence_line) produced each.
    by_key: dict = {}
    boundary_gaps: list = []

    # First pass: collect chunk metadata for boundary detection.
    chunk_ends = [c.get("end_line", 0) for c in chunks]
    chunk_status = [c.get("boundary_status", "complete") for c in chunks]

    # occurrences of each key with their chunk index + evidence line
    key_sites: dict = {}
    for idx, chunk in enumerate(chunks):
        for rel in chunk.get("relationships", []):
            k = _rel_key(rel)
            key_sites.setdefault(k, []).append((idx, rel.get("evidence_line", 0), dict(rel)))

    for k, sites in key_sites.items():
        # Merge all sites for this key into one relationship; lowest confidence wins.
        best = None
        for _idx, _line, rel in sites:
            if best is None or _CONF_RANK.get(rel.get("confidence"), 0) < _CONF_RANK.get(best.get("confidence"), 0):
                best = dict(rel)

        # Boundary check: is this key represented ONLY by a partial-boundary site
        # with no adjacent-overlap corroboration?
        partial_sites = [
            (idx, line) for (idx, line, _r) in sites
            if chunk_status[idx] in ("partial_end", "partial_both")
            and line >= chunk_ends[idx] - overlap_lines
        ]
        if partial_sites and len(sites) == 1:
            # Single partial-boundary site, no corroborating half -> downgrade.
            best["confidence"] = "speculative"
            boundary_gaps.append({
                "kind": "boundary_issue", "line": partial_sites[0][1],
                "detail": f"relationship {k[0]} {k[1]}->{k[2]} partial at chunk boundary, no corroborating half within overlap",
            })
        by_key[k] = best

    merged = sorted(by_key.values(), key=lambda r: (r.get("rel", ""), r.get("from_id", ""), r.get("to_id", "")))
    return merged, boundary_gaps


def sort_gaps(gaps: list) -> list:
    return sorted(gaps, key=lambda g: (g.get("line", 0), g.get("kind", ""), g.get("detail", "")))


def accumulate(chunk_dir: Path, run_id: str, file_sha256: str, overlap_lines: int = DEFAULT_OVERLAP_LINES) -> dict:
    if not chunk_dir.exists():
        raise FileNotFoundError(f"Chunk directory not found: {chunk_dir}")
    manifest_path = chunk_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    file_path = manifest.get("path", "")
    chunk_count = manifest.get("chunk_count", 0)
    fmt = manifest.get("format_hint", "unknown")
    manifest_gaps = manifest.get("gaps", [])

    if chunk_count == 0:
        # binary / oversized skip
        summary = {
            "schema_version": "1.0.0", "extractor_id": "legacy-code-intel",
            "format": fmt if fmt in ("cobol", "dsx", "etl", "pick") else "etl",
            "file_path": file_path, "file_sha256": file_sha256, "chunk_id": 0,
            "start_line": 1, "end_line": 1, "boundary_status": "complete",
            "symbols": [], "occurrences": [], "relationships": [],
            "gaps": sort_gaps(manifest_gaps),
        }
        atomic_write_json(chunk_dir / "summary.json", summary)
        return summary

    chunks: list = []
    for i in range(1, chunk_count + 1):
        cj = chunk_dir / f"chunk_{i:04d}.jsonl"
        if not cj.exists():
            cj = chunk_dir / f"chunk_{i:04d}.jsonl.placeholder"
        finding = read_chunk_finding(cj) if cj.exists() else None
        if finding is None:
            chunks.append({
                "chunk_id": i, "start_line": 0, "end_line": 0, "boundary_status": "complete",
                "symbols": [], "occurrences": [], "relationships": [],
                "gaps": [{"kind": "unresolved_symbol", "line": 1, "detail": f"Chunk {i} not yet analyzed"}],
            })
        else:
            chunks.append(finding)

    symbols = merge_symbols(chunks)
    occurrences = merge_occurrences(chunks)
    relationships, boundary_gaps = merge_relationships(chunks, overlap_lines)

    all_gaps = list(manifest_gaps) + list(boundary_gaps)
    for chunk in chunks:
        all_gaps.extend(chunk.get("gaps", []))

    # Determine format from chunks if manifest hint was 'unknown'
    fmt_final = fmt if fmt in ("cobol", "dsx", "etl", "pick") else None
    if fmt_final is None:
        for chunk in chunks:
            cf = chunk.get("format")
            if cf in ("cobol", "dsx", "etl", "pick"):
                fmt_final = cf
                break
    if fmt_final is None:
        fmt_final = "etl"

    summary = {
        "schema_version": "1.0.0", "extractor_id": "legacy-code-intel",
        "format": fmt_final, "file_path": file_path, "file_sha256": file_sha256,
        "chunk_id": 0, "start_line": 1, "end_line": max(manifest.get("line_count", 1), 1),
        "boundary_status": "complete",
        "symbols": symbols, "occurrences": occurrences, "relationships": relationships,
        "gaps": sort_gaps(all_gaps),
    }
    atomic_write_json(chunk_dir / "summary.json", summary)
    return summary


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chunk_dir_path", type=Path)
    parser.add_argument("run_id")
    parser.add_argument("file_sha256")
    parser.add_argument("--overlap-lines", type=int, default=DEFAULT_OVERLAP_LINES)
    args = parser.parse_args(argv)

    try:
        summary = accumulate(args.chunk_dir_path, args.run_id, args.file_sha256, overlap_lines=args.overlap_lines)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
