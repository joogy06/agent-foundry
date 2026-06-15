#!/usr/bin/env python3
"""accumulate_structure.py — per-file structure rollup with deterministic
boundary pairing and downstream COBOL offset computation.

Part of the structure-recovery skill (lineage-family sibling of
lineage-extract-static / legacy-code-intel). This is the structure analogue of
``lineage-extract-static/scripts/accumulate.py``: it reads the per-chunk
``structure-finding.v1`` emissions the in-session AI CLI's LLM produced (one per
``chunk_NNNN.jsonl`` under the per-file cache dir created by ``chunk_file.py``)
and writes a per-file ``summary.json`` whose entities carry the
DETERMINISTICALLY-computed byte layout.

What it does (design §3.6 / §9):

1. Reads ``manifest.json`` + ``chunk_NNNN.jsonl`` findings (last JSON object with
   ``fields`` + ``gaps`` is the agent emission — same convention as the lineage
   accumulator).
2. Groups findings by the structure pairing key — ``same(object_kind)`` AND
   ``same(qualified_name)``. Adjacent overlapping chunks for the SAME object are
   unioned: their ``fields`` merge by ``ordinal`` and dedup ``(name, ordinal)``.
3. Lower-confidence-wins on a duplicated field — the EXACT ``conf_rank``
   ``{grounded:3, inferred:2, speculative:1}`` lower-wins idiom is REUSED verbatim
   from ``accumulate.py`` (lines 256-264) via :data:`_CONF_RANK`. A duplicate keeps
   the more conservative confidence.
4. Orphan / tie partials -> ``boundary_issue`` gap + a confidence downgrade to
   ``speculative`` (mirrors the ``accumulate.py`` tie idiom ~225-239).
5. After a COBOL record's declared field tree is merged, ``cobol_offset_calc``
   (WP-2) computes ``byte_offset`` / ``length`` / ranged + gaps. (COPY splicing is
   resolved FIRST in the cross-file pass — WP-10/WP-11 — before this is called;
   an unresolved COPY arrives as a finding-level ``unresolved_copybook`` gap and
   forces the affected subtree speculative inside the calculator.)
6. Flat-file findings with ``position_declared: true`` carry advisory declared
   offsets (``declared_start`` / ``declared_end``); they are cross-checked against
   the computed positional sequence. A mismatch downgrades the field and emits a
   ``position_mismatch`` gap.

Output ``summary.json`` is a per-FILE rollup conforming to the *entity fragment*
of ``structure-index.v1`` (``entities`` / ``relationships`` / ``gaps`` plus the
provenance ``schema_version`` / ``extractor_id`` / ``extractor_version`` /
``file_path`` / ``file_sha256``). The CROSS-FILE catalog (full
``structure-index.v1`` with ``generated_with``) is assembled later by the
cross-file pass; this module never claims to be the catalog.

Atomic writes via ``.tmp.<pid>`` + ``os.replace()`` + ``fsync`` (HARD-RULE 5,
reused shape). Idempotent: re-running over the same chunks yields byte-identical
``summary.json``.

Pure stdlib (no per-format parser deps, sibling parity). Python 3.12 target.

CLI usage::

    accumulate_structure.py <chunk_dir_path> <run_id> <file_sha256> \
        [--overlap-lines N] [--pointer-size 4|8]

The chunk_dir_path is the per-file cache directory created by chunk_file.py.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Default overlap (in lines) within which two adjacent chunks may pair the same
# object. The structure chunker (WP-3) defaults STRUCT_OVERLAP_LINES=200; we read
# that env so the accumulator's pairing window matches the chunker's overlap.
DEFAULT_OVERLAP_LINES = int(os.environ.get("STRUCT_OVERLAP_LINES", "200"))

EXTRACTOR_ID = "structure-recovery"
EXTRACTOR_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Confidence helpers — REUSE the lineage accumulate.py conf_rank lower-wins
# idiom verbatim (accumulate.py:256-264). Kept byte-identical so the structure
# accumulator and the lineage accumulator make the SAME conservative choice.
# ---------------------------------------------------------------------------

_CONF_RANK = {"grounded": 3, "inferred": 2, "speculative": 1}
_RANK_CONF = {3: "grounded", 2: "inferred", 1: "speculative"}


def _min_conf(a: str, b: str) -> str:
    """Lower-confidence-wins (mirrors accumulate.py conf_rank lower-wins)."""
    return _RANK_CONF[min(_CONF_RANK.get(a, 1), _CONF_RANK.get(b, 1))]


# ---------------------------------------------------------------------------
# Sibling-module import (cobol_offset_calc.py lives next to this file)
# ---------------------------------------------------------------------------

def _load_cobol_offset_calc():
    """Import cobol_offset_calc.py by path from the same scripts/ dir.

    The module name MUST be registered in sys.modules BEFORE exec_module so the
    dataclasses in cobol_offset_calc can resolve the string annotations produced
    by ``from __future__ import annotations`` (same pattern the WP-2 tests use).
    """
    calc_path = Path(__file__).resolve().parent / "cobol_offset_calc.py"
    spec = importlib.util.spec_from_file_location("sr_cobol_offset_calc", calc_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load cobol_offset_calc from {calc_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_CALC = _load_cobol_offset_calc()


# ---------------------------------------------------------------------------
# Chunk reading — structure variant of accumulate.read_chunk_findings
# ---------------------------------------------------------------------------

def read_chunk_findings(chunk_path: Path) -> Optional[dict]:
    """Read one ``chunk_NNNN.jsonl`` file. Returns the ``structure-finding.v1``
    dict (the agent's emission) or ``None`` if the chunk hasn't been analyzed.

    The chunk file structure mirrors the lineage convention:
        line 1: placeholder metadata (from chunk_file.py, status=awaiting_analysis)
        line 2+: the agent's analyze-<fmt>.md output (one or more JSON objects)

    By convention the agent's emission is the LAST non-empty JSON object that
    looks like a structure finding — i.e. has ``fields`` AND ``gaps`` arrays.
    Pure-placeholder lines (``status=awaiting_analysis``) are skipped.
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
            if not isinstance(obj, dict):
                continue
            # Skip pure-placeholder lines.
            if obj.get("status") == "awaiting_analysis":
                continue
            # Treat as agent emission iff it carries the structure-finding shape.
            if "fields" in obj and "gaps" in obj:
                last_finding = obj
    return last_finding


# ---------------------------------------------------------------------------
# Atomic write — REUSE the accumulate.py shape verbatim (HARD-RULE 5)
# ---------------------------------------------------------------------------

def atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically via .tmp.<pid> + os.replace + fsync. HARD-RULE 5.

    Byte-identical idiom to lineage-extract-static/scripts/accumulate.py so the
    structure summary is written with the same durability guarantees.
    """
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


# ---------------------------------------------------------------------------
# Object pairing key + field merge
# ---------------------------------------------------------------------------

def object_key(finding: dict) -> tuple:
    """Canonical pairing key for an object: (object_kind, qualified_name)."""
    return (finding.get("object_kind", ""), finding.get("qualified_name", ""))


def _chunk_span(finding: dict) -> tuple[int, int]:
    """(start_line, end_line) of the chunk the finding came from. Missing values
    default to 0 (which makes the adjacency test conservative)."""
    return (int(finding.get("start_line", 0) or 0),
            int(finding.get("end_line", 0) or 0))


def _adjacent_within_overlap(prev: dict, cur: dict, overlap_lines: int) -> bool:
    """True iff ``cur``'s chunk begins within ``overlap_lines`` of where ``prev``'s
    chunk ended (i.e. they are adjacent/overlapping chunks of the same file).

    Mirrors the lineage pairing distance test
    (``chunk_N+1.start_line - chunk_N.end_line <= OVERLAP``) but is lenient about
    direction so a true overlap (start <= prev_end) also pairs.
    """
    _, prev_end = _chunk_span(prev)
    cur_start, _ = _chunk_span(cur)
    if prev_end <= 0 or cur_start <= 0:
        # Insufficient line info — fall back to "adjacent" so same-object findings
        # in sequence still union (single-chunk inline artifacts hit this path).
        return True
    return (cur_start - prev_end) <= overlap_lines


def _field_merge_key(field: dict) -> tuple:
    """Dedup key for a field within an object: (name, ordinal)."""
    return (field.get("name", ""), field.get("ordinal", -1))


def merge_object_fields(
    findings: list[dict],
    overlap_lines: int,
) -> tuple[list[dict], list[dict], int]:
    """Union the fields of one object's findings (already grouped + chunk-ordered).

    Returns ``(merged_fields, gaps, boundary_issues)``.

    * Fields union by ``(name, ordinal)``. On a duplicate, lower-confidence-wins
      (the reused conf_rank idiom) — the kept field carries the more conservative
      ``confidence`` (and if either side was a boundary partial, it stays flagged).
    * A field that appears in a NON-adjacent later chunk for the same object (an
      orphan across a gap larger than the overlap) is kept but downgraded to
      ``speculative`` with a ``boundary_issue`` gap.
    """
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []  # preserve first-seen order for determinism
    gaps: list[dict] = []
    boundary_issues = 0
    prev_finding: Optional[dict] = None

    for finding in findings:
        adjacent = True
        if prev_finding is not None:
            adjacent = _adjacent_within_overlap(prev_finding, finding, overlap_lines)
        line_for_gap = _chunk_span(finding)[0] or 1

        for fld in finding.get("fields", []) or []:
            if not isinstance(fld, dict):
                continue
            key = _field_merge_key(fld)
            incoming = dict(fld)

            # An orphan across a too-large gap, or a field already flagged as a
            # boundary partial by the LLM, is forced speculative + boundary_issue.
            orphaned = (not adjacent) and (prev_finding is not None) and (key not in merged)
            if orphaned or incoming.get("boundary_issue"):
                if _CONF_RANK.get(incoming.get("confidence", "speculative"), 1) > 1:
                    incoming["confidence"] = "speculative"
                incoming["boundary_issue"] = True
                gaps.append({
                    "kind": "boundary_issue",
                    "line": line_for_gap,
                    "description": (
                        f"field {incoming.get('name', '?')!r} of "
                        f"{finding.get('qualified_name', '?')!r} paired across a "
                        f"chunk gap wider than the {overlap_lines}-line overlap — "
                        f"downgraded to speculative."
                    ),
                })
                boundary_issues += 1

            if key not in merged:
                merged[key] = incoming
                order.append(key)
            else:
                # Duplicate field across the overlap: lower-confidence-wins.
                existing = merged[key]
                kept_conf = _min_conf(
                    existing.get("confidence", "speculative"),
                    incoming.get("confidence", "speculative"),
                )
                # Prefer the existing field's declared facts but take the more
                # conservative confidence and propagate any boundary flag.
                existing["confidence"] = kept_conf
                if incoming.get("boundary_issue") or existing.get("boundary_issue"):
                    existing["boundary_issue"] = True
                # Fill any declared facts the first occurrence left null.
                for k, v in incoming.items():
                    if existing.get(k) is None and v is not None:
                        existing[k] = v

        prev_finding = finding

    merged_fields = [merged[k] for k in order]
    return merged_fields, gaps, boundary_issues


# ---------------------------------------------------------------------------
# COBOL offset computation + flat-file position cross-check
# ---------------------------------------------------------------------------

def _finding_evidence(finding: dict) -> dict:
    ev = finding.get("evidence")
    if isinstance(ev, dict) and ev.get("file_path") and isinstance(ev.get("line"), int):
        return {"file_path": ev["file_path"], "line": ev["line"]}
    return {"file_path": finding.get("file_path", "") or "<unknown>", "line": 1}


def _strip_finding_only_field_keys(field: dict) -> dict:
    """Project a (non-COBOL) merged finding-field into the structure-index.v1
    ``fields[]`` shape. COBOL records go through cobol_offset_calc instead; this
    handles SQL / DSX / flat-file fields where offsets stay null (or, for a
    cross-checked flat-file, are filled from declared positions)."""
    out = {
        "name": field.get("name", ""),
        "ordinal": int(field.get("ordinal", 0) or 0),
        "level": field.get("level"),
        "parent": None,
        "byte_offset": None,
        "length": None,
        "byte_offset_min": None,
        "byte_offset_max": None,
        "ranged": False,
        "variable_length": False,
        "pic_clause": field.get("pic_clause"),
        "usage": field.get("usage"),
        "declared_type": field.get("declared_type"),
        "normalized_type": field.get("normalized_type"),
        "nullable": field.get("nullable"),
        "occurs": field.get("occurs"),
        "occurs_max": field.get("occurs_max"),
        "occurs_depending_on": field.get("occurs_depending_on"),
        "redefines": field.get("redefines"),
        "renames": field.get("renames"),
        "is_group": field.get("is_group"),
        "is_filler": field.get("is_filler"),
        "offset_confidence": field.get("confidence", "grounded"),
        "confidence": field.get("confidence", "grounded"),
        "evidence_kind": field.get("evidence_kind", "declared_column"),
        "enforcement": field.get("enforcement", "unknown"),
        "evidence": field.get("evidence"),
    }
    return out


def _crosscheck_flatfile_positions(
    index_fields: list[dict],
    merged_fields: list[dict],
    qualified_name: str,
    file_path: str,
) -> list[dict]:
    """Cross-check declared flat-file positions against a computed positional
    sequence. The declared positions live on the ORIGINAL merged finding-fields
    (``position_declared`` / ``declared_start`` / ``declared_end``). When ALL
    fields declare positions we adopt them as the authoritative byte layout, but
    we verify they form a consistent non-overlapping forward sequence; any field
    whose declared span disagrees with the running computed sequence is downgraded
    and a ``position_mismatch`` gap is returned.

    ``index_fields`` is mutated in place (offsets filled / downgraded). Returns the
    list of gaps produced.
    """
    gaps: list[dict] = []
    by_ordinal = sorted(
        range(len(merged_fields)),
        key=lambda i: int(merged_fields[i].get("ordinal", i) or 0),
    )
    cursor = 0
    for i in by_ordinal:
        src = merged_fields[i]
        if not src.get("position_declared"):
            continue
        d_start = src.get("declared_start")
        d_end = src.get("declared_end")
        if not isinstance(d_start, int) or not isinstance(d_end, int):
            continue
        declared_len = max(d_end - d_start, 0)
        # The computed sequence expects the next field to start at `cursor`.
        mismatch = d_start != cursor
        idx_field = index_fields[i]
        idx_field["byte_offset"] = d_start
        idx_field["length"] = declared_len
        idx_field["byte_offset_min"] = d_start
        idx_field["byte_offset_max"] = d_start
        if mismatch:
            idx_field["ranged"] = True
            idx_field["offset_confidence"] = _min_conf(
                idx_field.get("offset_confidence", "grounded"), "speculative"
            )
            gaps.append({
                "kind": "position_mismatch",
                "file_path": file_path or None,
                "line": (src.get("evidence") or {}).get("line", 1)
                if isinstance(src.get("evidence"), dict) else 1,
                "description": (
                    f"{qualified_name}: field {src.get('name', '?')!r} declares "
                    f"start {d_start} but the computed sequence reached {cursor} "
                    f"— offset downgraded."
                ),
            })
        else:
            idx_field["offset_confidence"] = "grounded"
        cursor = max(cursor, d_end)
    return gaps


def build_entity(
    findings: list[dict],
    overlap_lines: int,
    pointer_size: int,
) -> dict:
    """Merge one object's findings into a structure-index.v1 *entity* dict.

    For ``cobol_record`` objects the merged field tree is handed to
    ``cobol_offset_calc.compute_offsets`` for deterministic byte layout. For
    other kinds the fields are projected with null offsets (flat-file declared
    positions are cross-checked and may fill offsets).
    """
    first = findings[0]
    object_kind = first.get("object_kind", "")
    qualified_name = first.get("qualified_name", "")
    file_path = first.get("file_path", "")

    merged_fields, merge_gaps, boundary_issues = merge_object_fields(
        findings, overlap_lines
    )

    # Concatenate any per-finding gaps (deduped later at file level).
    entity_gaps: list[dict] = list(merge_gaps)
    for finding in findings:
        for g in finding.get("gaps", []) or []:
            if isinstance(g, dict):
                entity_gaps.append({
                    "kind": g.get("kind", "language_unsupported"),
                    "file_path": file_path or None,
                    "line": g.get("line", 1),
                    "description": g.get("description", ""),
                })

    if object_kind == "cobol_record":
        # The COBOL record's declared level-tree drives the deterministic layout.
        # Any finding-level unresolved-COPY gap forces the subtree speculative
        # inside the calculator (it reads finding['gaps']).
        proxy_finding = {
            "object_kind": object_kind,
            "qualified_name": qualified_name,
            "file_path": file_path,
            "fields": merged_fields,
            "gaps": [g for f in findings for g in (f.get("gaps", []) or [])
                     if isinstance(g, dict)],
            "evidence": _finding_evidence(first),
        }
        result = _CALC.compute_finding_offsets(proxy_finding, pointer_size=pointer_size)
        index_fields = result.fields
        record_length = result.record_length
        record_length_min = result.record_length_min
        record_length_max = result.record_length_max
        variable_length = result.variable_length
        entity_conf = result.confidence
        # The calculator's gaps (sync/odo/unresolved-copy) join the entity gaps.
        for g in result.gaps:
            entity_gaps.append({
                "kind": g.get("kind", "language_unsupported"),
                "file_path": file_path or None,
                "line": g.get("line", 1),
                "description": g.get("description", ""),
            })
    else:
        index_fields = [_strip_finding_only_field_keys(f) for f in merged_fields]
        record_length = None
        record_length_min = None
        record_length_max = None
        variable_length = False
        # Flat-file declared-position cross-check (advisory -> authoritative).
        if object_kind == "flatfile_layout":
            pos_gaps = _crosscheck_flatfile_positions(
                index_fields, merged_fields, qualified_name, file_path
            )
            entity_gaps.extend(pos_gaps)
            if index_fields and all(
                f.get("position_declared") for f in merged_fields
            ):
                # All positions declared -> we can roll a record length up.
                ends = [
                    f.get("byte_offset_max") or 0
                    if f.get("byte_offset") is None
                    else (f.get("byte_offset") or 0) + (f.get("length") or 0)
                    for f in index_fields
                ]
                record_length = max(ends) if ends else 0
                record_length_min = record_length
                record_length_max = record_length
        # Entity declaration confidence = most conservative across fields.
        entity_conf = "grounded"
        for f in index_fields:
            entity_conf = _min_conf(entity_conf, f.get("confidence", "grounded"))

    # Object-level confidence floor: also fold in the finding-declared confidence.
    declared_obj_conf = first.get("confidence", "grounded")
    entity_conf = _min_conf(entity_conf, declared_obj_conf)
    if boundary_issues:
        entity_conf = _min_conf(entity_conf, "speculative")

    entity = {
        "object_kind": object_kind,
        "qualified_name": qualified_name,
        "record_length": record_length,
        "record_length_min": record_length_min,
        "record_length_max": record_length_max,
        "variable_length": bool(variable_length),
        "fields": index_fields,
        "confidence": entity_conf,
        "evidence": _finding_evidence(first),
        "gaps": _dedup_gaps(entity_gaps),
    }
    return entity


def _collect_relationships(findings: list[dict]) -> list[dict]:
    """Union the per-object relationships declared in the contributing chunks,
    projected into the structure-index.v1 relationship shape (adds ``from_object``).
    Deduped on the full tuple. Cross-file FK resolution (and the K2 caps) is a
    LATER pass (WP-10); this only carries the chunk-declared edges forward."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for finding in findings:
        from_object = finding.get("qualified_name", "")
        for rel in finding.get("relationships", []) or []:
            if not isinstance(rel, dict):
                continue
            row = {
                "kind": rel.get("kind", "join"),
                "from_object": from_object,
                "from_field": rel.get("from_field", ""),
                "to_object": rel.get("to_object"),
                "to_field": rel.get("to_field"),
                "evidence_kind": rel.get("evidence_kind", "observed_usage"),
                "enforcement": rel.get("enforcement", "unknown"),
                "confidence": rel.get("confidence", "inferred"),
            }
            key = (
                row["kind"], row["from_object"], row["from_field"],
                row["to_object"], row["to_field"],
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
    return out


def _dedup_gaps(gaps: list[dict]) -> list[dict]:
    """Dedup gaps on (kind, file_path, line, description) and sort deterministically."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for g in gaps:
        key = (g.get("kind", ""), g.get("file_path"), g.get("line"), g.get("description", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(g)

    def sort_key(g):
        return (
            str(g.get("kind", "")),
            str(g.get("file_path") or ""),
            g.get("line") if isinstance(g.get("line"), int) else 0,
            str(g.get("description", "")),
        )

    return sorted(out, key=sort_key)


def _sort_entities(entities: list[dict]) -> list[dict]:
    return sorted(entities, key=lambda e: (e.get("object_kind", ""), e.get("qualified_name", "")))


def _sort_relationships(rels: list[dict]) -> list[dict]:
    return sorted(
        rels,
        key=lambda r: (
            r.get("kind", ""), r.get("from_object", ""), r.get("from_field", ""),
            str(r.get("to_object") or ""), str(r.get("to_field") or ""),
        ),
    )


# ---------------------------------------------------------------------------
# The accumulator entry point
# ---------------------------------------------------------------------------

def accumulate_structure(
    chunk_dir: Path,
    run_id: str,
    file_sha256: str,
    overlap_lines: int = DEFAULT_OVERLAP_LINES,
    pointer_size: int = 4,
) -> dict:
    """Read chunks, pair + merge per object, compute COBOL offsets, write
    ``summary.json``. Returns the summary dict.

    Raises ``FileNotFoundError`` if ``chunk_dir`` or ``manifest.json`` is missing.
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
    manifest_gaps_raw = manifest.get("gaps", []) or []

    # Carry manifest-level gaps (binary/oversized/etc.) up to the catalog level.
    catalog_gaps: list[dict] = []
    for g in manifest_gaps_raw:
        if isinstance(g, dict):
            catalog_gaps.append({
                "kind": g.get("kind", "language_unsupported"),
                "file_path": file_path or None,
                "line": g.get("line", 1) if isinstance(g.get("line"), int) else None,
                "description": g.get("description", ""),
            })

    # Degenerate file (binary / oversized / not chunked): no entities.
    if chunk_count == 0:
        summary = _summary_envelope(
            file_path, file_sha256,
            entities=[], relationships=[], gaps=_dedup_gaps(catalog_gaps),
        )
        atomic_write_json(chunk_dir / "summary.json", summary)
        return summary

    # Read each chunk's analyzed finding (.jsonl, falling back to placeholder).
    findings: list[dict] = []
    for i in range(1, chunk_count + 1):
        chunk_jsonl = chunk_dir / f"chunk_{i:04d}.jsonl"
        if not chunk_jsonl.exists():
            chunk_jsonl = chunk_dir / f"chunk_{i:04d}.jsonl.placeholder"
        finding = read_chunk_findings(chunk_jsonl) if chunk_jsonl.exists() else None
        if finding is None:
            # Not analyzed yet -> honest catalog-level gap, no fabricated entity.
            catalog_gaps.append({
                "kind": "language_unsupported",
                "file_path": file_path or None,
                "line": None,
                "description": f"chunk {i} not yet analyzed by the AI CLI's LLM",
            })
            continue
        findings.append(finding)

    # Group by object pairing key in first-seen order (deterministic).
    groups: dict[tuple, list[dict]] = {}
    group_order: list[tuple] = []
    for finding in findings:
        key = object_key(finding)
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(finding)

    entities: list[dict] = []
    relationships: list[dict] = []
    for key in group_order:
        obj_findings = groups[key]
        # Chunk-order the findings so adjacency is correct.
        obj_findings_sorted = sorted(obj_findings, key=lambda f: _chunk_span(f)[0])
        entities.append(build_entity(obj_findings_sorted, overlap_lines, pointer_size))
        relationships.extend(_collect_relationships(obj_findings_sorted))

    # Dedup relationships across objects.
    rel_seen: set[tuple] = set()
    rels_deduped: list[dict] = []
    for r in relationships:
        rk = (r["kind"], r["from_object"], r["from_field"],
              r.get("to_object"), r.get("to_field"))
        if rk in rel_seen:
            continue
        rel_seen.add(rk)
        rels_deduped.append(r)

    summary = _summary_envelope(
        file_path, file_sha256,
        entities=_sort_entities(entities),
        relationships=_sort_relationships(rels_deduped),
        gaps=_dedup_gaps(catalog_gaps),
    )
    atomic_write_json(chunk_dir / "summary.json", summary)
    return summary


def _summary_envelope(
    file_path: str,
    file_sha256: str,
    *,
    entities: list[dict],
    relationships: list[dict],
    gaps: list[dict],
) -> dict:
    """Per-file summary envelope. This is the entity fragment of
    structure-index.v1 plus file provenance — the cross-file pass folds these
    into the full catalog (adding ``generated_with``)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "extractor_id": EXTRACTOR_ID,
        "extractor_version": EXTRACTOR_VERSION,
        "file_path": file_path,
        "file_sha256": file_sha256,
        "entities": entities,
        "relationships": relationships,
        "gaps": gaps,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("chunk_dir_path", type=Path, help="Per-file chunk directory")
    parser.add_argument("run_id", help="Run identifier")
    parser.add_argument("file_sha256", help="File sha256 (must match the chunk dir)")
    parser.add_argument("--overlap-lines", type=int, default=DEFAULT_OVERLAP_LINES)
    parser.add_argument(
        "--pointer-size", type=int, choices=(4, 8), default=4,
        help="Assumed POINTER/INDEX storage size in bytes (default 4).",
    )
    args = parser.parse_args(argv)

    try:
        summary = accumulate_structure(
            args.chunk_dir_path,
            args.run_id,
            args.file_sha256,
            overlap_lines=args.overlap_lines,
            pointer_size=args.pointer_size,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
