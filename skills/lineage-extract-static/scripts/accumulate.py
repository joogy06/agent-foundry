#!/usr/bin/env python3
"""accumulate.py — per-file lineage rollup with deterministic boundary pairing.

Reads chunk-level lineage findings (`chunk_NNNN.jsonl` files populated by the
agent's LLM via `prompts/analyze-file.md`) and produces a per-file summary at
`summary.json`. Performs DETERMINISTIC boundary-pairing per HARD-RULE 2 in
the design (no LLM judgment in pairing).

Component: accumulate (WP-3 in S033 contract-map).

Boundary-pairing predicate (per design §9):

    pair two partials iff ALL of:
      same(edge.edge_kind)
      same(edge.source_dataset.namespace, edge.source_dataset.name)
      same(edge.target_job.namespace, edge.target_job.name)
      chunk_N+1.start_line - chunk_N.end_line <= LINEAGE_OVERLAP_LINES (default 50)

    If two candidate pairs exist for the same partial_end, take the smaller
    line-distance. If still tied, downgrade BOTH to confidence: speculative +
    boundary_issue: true.

Atomic writes via .tmp.<pid> + os.replace(). Idempotent on re-run with same chunks.

CLI usage:
    accumulate.py <chunk_dir_path> <run_id> <file_sha256> [--overlap-lines N]

The chunk_dir_path is the per-file cache directory created by chunk_file.py
(at ~/.cache/lineage-extract-static/runs/<run_id>/files/<file_sha256>/).

Reads:
- manifest.json (must exist; produced by chunk_file.py)
- chunk_NNNN.jsonl files (one per chunk, each containing one or more JSON
  objects: the placeholder metadata on line 1, then the LLM's
  lineage-finding.v1 emission on line 2+)

Writes:
- summary.json — file-level rollup conforming to lineage-finding.v1 with
  chunk_id=0, edges merged, gaps merged, boundary pairings applied.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

DEFAULT_OVERLAP_LINES = int(os.environ.get("LINEAGE_OVERLAP_LINES", "50"))


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically via .tmp.<pid> + os.replace + fsync. HARD-RULE 5."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".tmp.",
        suffix=f".{os.getpid()}",
        dir=str(path.parent),
    )
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


def read_chunk_findings(chunk_path: Path) -> Optional[dict]:
    """Read one chunk_NNNN.jsonl file. Returns the lineage-finding.v1 dict
    (the agent's emission) or None if the chunk hasn't been analyzed yet.

    The chunk file structure is:
    line 1: placeholder metadata (from chunk_file.py)
    line 2+: agent's analyze-file.md output (one or more JSON objects)

    By convention, the agent's emission is the LAST non-empty JSON object
    in the file. Earlier lines are placeholders.
    """
    if not chunk_path.exists():
        return None
    last_finding = None
    with chunk_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Skip pure-placeholder lines (status="awaiting_analysis")
            if obj.get("status") == "awaiting_analysis":
                continue
            # Treat as agent emission iff it has edges/gaps arrays
            if "edges" in obj and "gaps" in obj:
                last_finding = obj
    return last_finding


def edge_key(edge: dict) -> tuple:
    """Canonical key for an edge — used for boundary pairing."""
    src = edge.get("source_dataset", {})
    tgt = edge.get("target_job", {})
    return (
        edge.get("edge_kind", ""),
        src.get("namespace", ""),
        src.get("name", ""),
        tgt.get("namespace", ""),
        tgt.get("name", ""),
    )


def pair_boundary_edges(
    chunks: list[dict],
    overlap_lines: int = DEFAULT_OVERLAP_LINES,
) -> tuple[list[dict], int]:
    """Apply the deterministic boundary-pairing predicate.

    Args:
        chunks: List of chunk-level findings, in chunk_id order.
        overlap_lines: Maximum line-distance for pairing.

    Returns:
        (merged_edges, boundary_issues_count)
        - merged_edges: List of edges with paired partials merged into single
          edges, and unpaired partials downgraded to speculative + boundary_issue.
        - boundary_issues_count: Number of unpaired partials (now boundary_issue=true).
    """
    # Collect every edge with its chunk index
    all_edges: list[tuple[int, dict]] = []
    for idx, chunk in enumerate(chunks):
        for edge in chunk.get("edges", []):
            all_edges.append((idx, dict(edge)))  # copy to avoid mutation

    # Group edges by chunk-boundary status. Edges in chunks with
    # boundary_status in {partial_end, partial_both} are "ends" candidates;
    # edges in chunks with boundary_status in {partial_start, partial_both}
    # are "starts" candidates.

    # We need to identify edges that are AT the chunk boundary specifically.
    # The LLM's analyze-file.md emits all edges in the chunk; we treat edges
    # whose evidence_line_end equals (or is close to) chunk.end_line as
    # boundary-end candidates, and edges whose evidence_line_start equals
    # (or is close to) chunk.start_line as boundary-start candidates.
    # In practice the LLM is told to set boundary_status at the chunk level;
    # edges within a partial_end chunk that touch the last lines are the
    # ones eligible for pairing.

    pair_end_edges: dict[tuple, list[tuple[int, int, dict]]] = {}  # key -> [(chunk_idx, edge_idx, edge)]
    pair_start_edges: dict[tuple, list[tuple[int, int, dict]]] = {}
    paired_indices: set[tuple[int, int]] = set()  # (chunk_idx, edge_idx)

    for chunk_idx, chunk in enumerate(chunks):
        status = chunk.get("boundary_status", "complete")
        chunk_end_line = chunk.get("end_line", 0)
        chunk_start_line = chunk.get("start_line", 0)
        for edge_idx, edge in enumerate(chunk.get("edges", [])):
            evidence_end = edge.get("evidence_line_end", 0)
            evidence_start = edge.get("evidence_line_start", 0)
            key = edge_key(edge)
            # boundary-end candidates: edges whose evidence touches chunk's last few lines
            # and chunk has partial_end / partial_both
            if status in ("partial_end", "partial_both") and (
                evidence_end >= chunk_end_line - overlap_lines
            ):
                pair_end_edges.setdefault(key, []).append((chunk_idx, edge_idx, edge))
            # boundary-start candidates
            if status in ("partial_start", "partial_both") and (
                evidence_start <= chunk_start_line + overlap_lines
            ):
                pair_start_edges.setdefault(key, []).append((chunk_idx, edge_idx, edge))

    # Pair: for each end-edge, find the closest start-edge with the same key
    # in the NEXT chunk (chunk_idx + 1) within overlap_lines of chunk boundary.
    merged_partials: list[dict] = []
    boundary_issues = 0

    for key, end_list in pair_end_edges.items():
        starts = pair_start_edges.get(key, [])
        for chunk_idx_end, edge_idx_end, edge_end in end_list:
            # Find all candidate starts in chunk_idx_end+1 (immediate next chunk only)
            candidates = [
                (c_idx, e_idx, e)
                for (c_idx, e_idx, e) in starts
                if c_idx == chunk_idx_end + 1
            ]
            # Already-paired starts excluded
            candidates = [
                (c_idx, e_idx, e)
                for (c_idx, e_idx, e) in candidates
                if (c_idx, e_idx) not in paired_indices
            ]
            if not candidates:
                # No pair found: keep the end-edge but downgrade to speculative + boundary_issue.
                # Add to merged_partials so the final loop emits it (vs filtering it out via paired_indices).
                orphan = dict(edge_end)
                orphan["confidence"] = "speculative"
                orphan["confidence_reason"] = "unpaired_partial_at_chunk_end"
                orphan["boundary_issue"] = True
                boundary_issues += 1
                paired_indices.add((chunk_idx_end, edge_idx_end))
                merged_partials.append(orphan)
                continue

            # Compute line distance for each candidate
            def line_dist(cand):
                c_idx, e_idx, e = cand
                chunk_end_line = chunks[chunk_idx_end].get("end_line", 0)
                evidence_start_next = e.get("evidence_line_start", chunk_end_line + 1)
                return abs(evidence_start_next - chunk_end_line)

            candidates_sorted = sorted(candidates, key=line_dist)
            best_dist = line_dist(candidates_sorted[0])
            tied = [c for c in candidates_sorted if line_dist(c) == best_dist]

            if len(tied) > 1:
                # Tie: downgrade BOTH/ALL to speculative + boundary_issue
                edge_end["confidence"] = "speculative"
                edge_end["confidence_reason"] = "ambiguous_partial_pair_at_chunk_boundary"
                edge_end["boundary_issue"] = True
                boundary_issues += 1
                paired_indices.add((chunk_idx_end, edge_idx_end))
                for c_idx, e_idx, e in tied:
                    e_marked = dict(e)
                    e_marked["confidence"] = "speculative"
                    e_marked["confidence_reason"] = "ambiguous_partial_pair_at_chunk_boundary"
                    e_marked["boundary_issue"] = True
                    boundary_issues += 1
                    paired_indices.add((c_idx, e_idx))
                continue

            # Single best candidate: merge
            c_idx_start, e_idx_start, edge_start = candidates_sorted[0]
            merged = dict(edge_end)
            # Combine line ranges
            merged_start = min(
                edge_end.get("evidence_line_start", 0),
                edge_start.get("evidence_line_start", 0),
            )
            merged_end = max(
                edge_end.get("evidence_line_end", 0),
                edge_start.get("evidence_line_end", 0),
            )
            merged["evidence_line_start"] = merged_start
            merged["evidence_line_end"] = merged_end
            # Preserve the more conservative confidence (lower confidence wins)
            conf_rank = {"grounded": 3, "inferred": 2, "speculative": 1}
            end_conf = edge_end.get("confidence", "speculative")
            start_conf = edge_start.get("confidence", "speculative")
            if conf_rank.get(end_conf, 0) <= conf_rank.get(start_conf, 0):
                merged["confidence"] = end_conf
                merged["confidence_reason"] = edge_end.get("confidence_reason", "")
            else:
                merged["confidence"] = start_conf
                merged["confidence_reason"] = edge_start.get("confidence_reason", "")
            merged_partials.append(merged)
            paired_indices.add((chunk_idx_end, edge_idx_end))
            paired_indices.add((c_idx_start, e_idx_start))

    # Handle start-edges with no end-pair (orphan start)
    for key, start_list in pair_start_edges.items():
        for c_idx, e_idx, e in start_list:
            if (c_idx, e_idx) in paired_indices:
                continue
            # Check if there's a matching end in the previous chunk we haven't seen
            prev_idx = c_idx - 1
            had_end_chunk = prev_idx >= 0 and chunks[prev_idx].get(
                "boundary_status", "complete"
            ) in ("partial_end", "partial_both")
            if not had_end_chunk:
                # No matching end-chunk; treat as ordinary edge (don't downgrade)
                continue
            # Had an end-chunk but couldn't pair: downgrade
            e_marked = dict(e)
            e_marked["confidence"] = "speculative"
            e_marked["confidence_reason"] = "unpaired_partial_at_chunk_start"
            e_marked["boundary_issue"] = True
            boundary_issues += 1
            # Replace in place by marking paired (the merged output collects from chunks below)
            paired_indices.add((c_idx, e_idx))
            # Track for inclusion in output
            merged_partials.append(e_marked)

    # Build final edges list: all non-paired edges from each chunk + merged_partials
    final_edges: list[dict] = []
    for chunk_idx, chunk in enumerate(chunks):
        for edge_idx, edge in enumerate(chunk.get("edges", [])):
            if (chunk_idx, edge_idx) in paired_indices:
                continue
            final_edges.append(dict(edge))
    final_edges.extend(merged_partials)

    return final_edges, boundary_issues


def sort_edges_deterministic(edges: list[dict]) -> list[dict]:
    """Stable sort: (evidence_line_start, evidence_line_end, edge_kind,
    source_dataset.namespace, source_dataset.name, target_job.namespace,
    target_job.name) for deterministic byte-identical output."""

    def key(e):
        src = e.get("source_dataset", {})
        tgt = e.get("target_job", {})
        return (
            e.get("evidence_line_start", 0),
            e.get("evidence_line_end", 0),
            e.get("edge_kind", ""),
            src.get("namespace", ""),
            src.get("name", ""),
            tgt.get("namespace", ""),
            tgt.get("name", ""),
        )

    return sorted(edges, key=key)


def sort_gaps_deterministic(gaps: list[dict]) -> list[dict]:
    """Sort gaps by (line, kind, description) for deterministic output."""

    def key(g):
        return (g.get("line", 0), g.get("kind", ""), g.get("description", ""))

    return sorted(gaps, key=key)


def accumulate(
    chunk_dir: Path,
    run_id: str,
    file_sha256: str,
    overlap_lines: int = DEFAULT_OVERLAP_LINES,
) -> dict:
    """Read chunks, apply boundary pairing, write summary.json. Returns the
    summary dict.

    Raises FileNotFoundError if chunk_dir or manifest.json missing.
    """
    if not chunk_dir.exists():
        raise FileNotFoundError(f"Chunk directory not found: {chunk_dir}")
    manifest_path = chunk_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    file_path = manifest.get("path", "")
    chunk_count = manifest.get("chunk_count", 0)
    binary = manifest.get("binary", False)
    manifest_gaps = manifest.get("gaps", [])

    # If file was skipped (binary or oversized), emit a degenerate rollup
    if chunk_count == 0:
        summary = {
            "schema_version": "1.0.0",
            "extractor_id": "lineage-extract-static",
            "extractor_version": "1.0.0",
            "file_path": file_path,
            "file_sha256": file_sha256,
            "chunk_id": 0,
            "start_line": 1,
            "end_line": 1,
            "start_byte": 0,
            "end_byte": 0,
            "boundary_status": "complete",
            "edges": [],
            "gaps": manifest_gaps,
            "by_confidence": {"grounded": 0, "inferred": 0, "speculative": 0},
            "by_kind": {"reads_from": 0, "writes_to": 0, "schedules": 0, "depends_on": 0},
            "boundary_issues_count": 0,
        }
        atomic_write_json(chunk_dir / "summary.json", summary)
        return summary

    # Read each chunk's analyzed findings (.jsonl, not .jsonl.placeholder)
    chunks: list[dict] = []
    for i in range(1, chunk_count + 1):
        # Prefer the populated .jsonl over the placeholder
        chunk_jsonl = chunk_dir / f"chunk_{i:04d}.jsonl"
        if not chunk_jsonl.exists():
            chunk_jsonl = chunk_dir / f"chunk_{i:04d}.jsonl.placeholder"
        finding = read_chunk_findings(chunk_jsonl) if chunk_jsonl.exists() else None
        if finding is None:
            # No analysis yet: treat as empty chunk
            chunks.append({
                "chunk_id": i,
                "start_line": 0,
                "end_line": 0,
                "boundary_status": "complete",
                "edges": [],
                "gaps": [{
                    "kind": "unresolved_symbol",
                    "line": 1,
                    "description": f"Chunk {i} not yet analyzed by the agent's LLM",
                }],
            })
        else:
            chunks.append(finding)

    # Apply boundary pairing
    merged_edges, boundary_issues = pair_boundary_edges(chunks, overlap_lines)

    # Concatenate gaps from all chunks + the manifest-level gaps
    all_gaps: list[dict] = list(manifest_gaps)
    for chunk in chunks:
        all_gaps.extend(chunk.get("gaps", []))

    # Sort for determinism
    final_edges = sort_edges_deterministic(merged_edges)
    final_gaps = sort_gaps_deterministic(all_gaps)

    # Aggregate counters
    by_confidence = {"grounded": 0, "inferred": 0, "speculative": 0}
    by_kind = {"reads_from": 0, "writes_to": 0, "schedules": 0, "depends_on": 0}
    for edge in final_edges:
        conf = edge.get("confidence", "speculative")
        if conf in by_confidence:
            by_confidence[conf] += 1
        kind = edge.get("edge_kind", "")
        if kind in by_kind:
            by_kind[kind] += 1

    # File-level start/end
    line_count = manifest.get("line_count", 1)
    size_bytes = manifest.get("size_bytes", 0)

    summary = {
        "schema_version": "1.0.0",
        "extractor_id": "lineage-extract-static",
        "extractor_version": "1.0.0",
        "file_path": file_path,
        "file_sha256": file_sha256,
        "chunk_id": 0,
        "start_line": 1,
        "end_line": max(line_count, 1),
        "start_byte": 0,
        "end_byte": size_bytes,
        "boundary_status": "complete",
        "edges": final_edges,
        "gaps": final_gaps,
        "by_confidence": by_confidence,
        "by_kind": by_kind,
        "boundary_issues_count": boundary_issues,
    }

    summary_path = chunk_dir / "summary.json"
    atomic_write_json(summary_path, summary)
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chunk_dir_path", type=Path, help="Per-file chunk directory")
    parser.add_argument("run_id", help="Run identifier")
    parser.add_argument("file_sha256", help="File sha256 (must match the chunk dir)")
    parser.add_argument("--overlap-lines", type=int, default=DEFAULT_OVERLAP_LINES)
    args = parser.parse_args(argv)

    try:
        summary = accumulate(
            args.chunk_dir_path,
            args.run_id,
            args.file_sha256,
            overlap_lines=args.overlap_lines,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # Print summary JSON to stdout (compact, for capture)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
