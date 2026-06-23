#!/usr/bin/env python3
"""merge_into_ol.py — emit OpenLineage 2.0.2 ndjson from project-aggregate rollup.

Component: merge-into-ol (WP-4 in S033 contract-map).

Reads the project-aggregate JSON produced by `prompts/redact-secrets.md` (or
its equivalent post-redaction artifact) and emits:

- openlineage.ndjson — canonical stream, one JobEvent or DatasetEvent per line.
- openlineage.json — derived bundle {"events": [...]}.
- lineage_edges.csv — single denormalized CSV (default output).

Canonical emission is JobEvent + DatasetEvent with NO Run wrapper per HARD-RULE 1.
RunEvent wrapping is opt-in via --with-static-run for downstream consumers that
require RunEvents. The synthetic runId is deterministic (uuid5 of workspace_tree_hash + scan_started_at)
for idempotency.

Every emitted event is validated by validate_ol.py BEFORE writing. Validation
failure aborts the entire run (fail-closed per HARD-RULE 1).

Atomic writes via .tmp.<pid> + os.replace().

CLI usage:
    merge_into_ol.py <rollup_path> <run_id> <workspace_tree_hash> <scan_started_at>
                     --output-dir <path>
                     [--with-static-run]
                     [--merge-by-basename]
                     [--aliases <path>]
                     [--schema-path <path>]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

# Reuse validator
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_ol import (  # noqa: E402
    PINNED_OL_SCHEMA_URL,
    DEFAULT_SCHEMA_PATH,
    validate_event,
    validate_event_or_abort,
    compile_validator,
    SchemaPinMismatch,
)

PINNED_OL_VERSION = "2.0.2"
STATIC_PRODUCER_URI = "urn:lineage:static-scan"
STATIC_ANALYSIS_FACET_URI = (
    "https://skill-factory.local/openlineage/facets/StaticAnalysisFacet/1-0-0.json"
)
# SchemaDatasetFacet (structure-recovery WP-9, M1). The facet name `schema`
# matches the upstream OpenLineage SchemaDatasetFacet convention; the vendored
# OL 2.0.2 schema accepts it because DatasetRef.facets is an open object keyed by
# facet name (each value self-describing via _producer / _schemaURL). We pin our
# own _schemaURL to the upstream facet spec URI used by structure-recovery.
SCHEMA_DATASET_FACET_URI = (
    "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json"
)
# sourceCodeLocation JOB facet (lineage multi-view + Control-M cycle, WP-9).
# Carries contentSha256 = sha256 of the RAW on-disk source file bytes (the
# already-computed file_sha256 from chunk_file.sha256_of_file — a streaming
# whole-file hash with NO encoding normalization). This is the v1.1 cross-engine
# join key; its byte definition MUST be IDENTICAL to the mainframe engine's
# sourceCodeLocation.contentSha256 (design §5d / INV-6) or cross-engine joins
# silently break.
SOURCE_CODE_LOCATION_FACET_URI = (
    "https://openlineage.io/spec/facets/1-0-0/SourceCodeLocationJobFacet.json"
)
EXTRACTOR_ID = "lineage-extract-static"
EXTRACTOR_VERSION = "1.0.0"


def atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically via .tmp.<pid> + os.replace + fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".tmp.",
        suffix=f".{os.getpid()}",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def deterministic_run_id(workspace_tree_hash: str, scan_started_at: str) -> str:
    """Compute a deterministic UUID5 for the synthetic run.

    Same workspace + same scan_started_at = same runId on re-emission.
    """
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid.NAMESPACE_OID
    seed = f"{workspace_tree_hash}:{scan_started_at}"
    return str(uuid.uuid5(namespace, seed))


def make_dataset_event(
    dataset: dict,
    scan_started_at: str,
    schema_facet: Optional[dict] = None,
) -> dict:
    """Emit a DatasetEvent for a unique (namespace, name) tuple.

    When ``schema_facet`` is provided (structure-recovery WP-9, M1) it is
    attached under ``dataset.facets.schema`` to enrich the dataset with its
    structural field/type schema. ``schema_facet=None`` (the default) yields a
    byte-identical event to the pre-WP-9 lineage emission — the existing lineage
    path is unchanged.
    """
    facets: dict = {
        "datasetKind": {
            "_producer": STATIC_PRODUCER_URI,
            "_schemaURL": "https://skill-factory.local/openlineage/facets/DatasetKindFacet/1-0-0.json",
            "kind": dataset.get("kind", "file"),
        },
    }
    if schema_facet is not None:
        facets["schema"] = schema_facet
    return {
        "$schema": PINNED_OL_SCHEMA_URL,
        "eventType": "DATASET_EVENT",
        "eventTime": scan_started_at,
        "producer": STATIC_PRODUCER_URI,
        "schemaURL": PINNED_OL_SCHEMA_URL,
        "dataset": {
            "namespace": dataset["namespace"],
            "name": dataset["name"],
            "facets": facets,
        },
    }


def make_schema_dataset_facet(fields: list[dict]) -> dict:
    """Build an OpenLineage SchemaDatasetFacet (structure-recovery WP-9, M1).

    ``fields`` is a list of ``{"name": str, "type": str, "description"?: str}``
    projected from a structure-index entity's columns/fields. The facet carries
    the ``_producer`` / ``_schemaURL`` self-description keys that every other
    facet in this emitter uses (parity with ``datasetKind`` / ``staticAnalysis``).

    The field list is normalized to the minimal OL field shape: each field is a
    dict with a string ``name`` and a string ``type`` (defaulting to ``""`` /
    ``"unknown"`` when the source declared none), plus an optional ``description``
    when present. Order is preserved as given by the caller (the caller sorts).
    """
    norm_fields: list[dict] = []
    for f in fields:
        fld = {
            "name": str(f.get("name", "")),
            "type": str(f.get("type") if f.get("type") is not None else "unknown"),
        }
        desc = f.get("description")
        if desc:
            fld["description"] = str(desc)
        norm_fields.append(fld)
    return {
        "_producer": STATIC_PRODUCER_URI,
        "_schemaURL": SCHEMA_DATASET_FACET_URI,
        "fields": norm_fields,
    }


def attach_schema_facet_fail_closed(
    event: dict,
    schema_facet: dict,
    schema_path: Optional[Path] = None,
) -> tuple[dict, Optional[str]]:
    """Attach ``schema_facet`` to a DatasetEvent, FAIL-CLOSED (WP-9 / §9 note 3).

    Mutates a copy of ``event`` to carry ``dataset.facets.schema``, then validates
    the ENRICHED event against the vendored OL schema. If the enriched event
    validates, returns ``(enriched_event, None)``. If the facet would make the
    event invalid, the facet is NOT applied: returns ``(event, gap_reason)`` with
    the original event untouched and a human-readable gap reason — so a malformed
    facet can NEVER abort the whole-event emit (no fail-closed crash, no malformed
    output). The caller records the gap and emits the structure-only / facet-less
    event.
    """
    import copy as _copy

    if event.get("eventType") != "DATASET_EVENT":
        return (event, "schema facet only applies to DATASET_EVENT")
    enriched = _copy.deepcopy(event)
    enriched.setdefault("dataset", {}).setdefault("facets", {})["schema"] = schema_facet
    is_valid, errors = validate_event(enriched, schema_path)
    if is_valid:
        return (enriched, None)
    reason = "schema facet rejected by vendored OL schema: " + "; ".join(errors)
    return (event, reason)


def make_source_code_location_facet(
    source_file: str,
    content_sha256: str,
) -> dict:
    """Build the sourceCodeLocation JOB facet carrying contentSha256 (WP-9).

    ``content_sha256`` MUST be the sha256 of the RAW on-disk source file bytes —
    the already-computed ``file_sha256`` from ``chunk_file.sha256_of_file`` (a
    streaming whole-file hash, NO encoding normalization, NO chunk scoping). This
    byte definition is shared verbatim with the mainframe engine's
    sourceCodeLocation.contentSha256 so the two streams join on the same key
    (design §5d / INV-6). The facet self-describes via ``_producer`` /
    ``_schemaURL`` like every other facet in this emitter.
    """
    return {
        "_producer": STATIC_PRODUCER_URI,
        "_schemaURL": SOURCE_CODE_LOCATION_FACET_URI,
        "type": "file",
        "path": source_file,
        "contentSha256": content_sha256,
    }


def make_job_event(
    job_id: tuple[str, str, str],
    inputs: list[dict],
    outputs: list[dict],
    scan_started_at: str,
    workspace_tree_hash: str,
    source_code_location: Optional[dict] = None,
) -> dict:
    """Emit a JobEvent for (namespace, name, kind) tuple. The custom
    staticAnalysis facet is attached per HARD-RULE 1.

    When ``source_code_location`` is provided (WP-9) it is attached under
    ``job.facets.sourceCodeLocation`` carrying the contentSha256 join key.
    ``source_code_location=None`` (the default) yields a byte-identical event to
    the pre-WP-9 emission — the existing path is unchanged.
    """
    job_ns, job_name, job_kind = job_id
    facets: dict = {
        "jobKind": {
            "_producer": STATIC_PRODUCER_URI,
            "_schemaURL": "https://skill-factory.local/openlineage/facets/JobKindFacet/1-0-0.json",
            "kind": job_kind,
        },
        "staticAnalysis": {
            "_producer": STATIC_PRODUCER_URI,
            "_schemaURL": STATIC_ANALYSIS_FACET_URI,
            "extractor_id": EXTRACTOR_ID,
            "extractor_version": EXTRACTOR_VERSION,
            "workspace_tree_hash": workspace_tree_hash,
            "mode": "static-extract",
            "runtime_observed": False,
        },
    }
    if source_code_location is not None:
        facets["sourceCodeLocation"] = source_code_location
    return {
        "$schema": PINNED_OL_SCHEMA_URL,
        "eventType": "JOB_EVENT",
        "eventTime": scan_started_at,
        "producer": STATIC_PRODUCER_URI,
        "schemaURL": PINNED_OL_SCHEMA_URL,
        "job": {
            "namespace": job_ns,
            "name": job_name,
            "facets": facets,
        },
        "inputs": inputs,
        "outputs": outputs,
    }


def make_run_event(
    run_id: str,
    job_event: dict,
    scan_started_at: str,
) -> dict:
    """Wrap a JobEvent in a synthetic RunEvent for compatibility export."""
    return {
        "$schema": PINNED_OL_SCHEMA_URL,
        "eventType": "COMPLETE",
        "eventTime": scan_started_at,
        "producer": STATIC_PRODUCER_URI,
        "schemaURL": PINNED_OL_SCHEMA_URL,
        "run": {
            "runId": run_id,
            "facets": {
                "staticAnalysis": {
                    "_producer": STATIC_PRODUCER_URI,
                    "_schemaURL": STATIC_ANALYSIS_FACET_URI,
                    "extractor_id": EXTRACTOR_ID,
                    "extractor_version": EXTRACTOR_VERSION,
                    "mode": "static-extract",
                    "runtime_observed": False,
                },
            },
        },
        "job": job_event["job"],
        "inputs": job_event.get("inputs", []),
        "outputs": job_event.get("outputs", []),
    }


def group_edges_by_job(edges: list[dict]) -> dict[tuple[str, str, str], dict[str, list[dict]]]:
    """Group edges by (target_job.namespace, target_job.name, target_job.kind).
    Returns {job_id: {"inputs": [...], "outputs": [...]}}.

    Inputs come from reads_from edges; outputs from writes_to. schedules and
    depends_on edges are not encoded as inputs/outputs — they may be encoded
    as separate JobEvents with job-to-job relationships via facets in v1.1.
    For v1 we only emit reads_from and writes_to into the OL inputs/outputs
    arrays; schedules and depends_on are surfaced in the CSV but not as OL events.
    """
    grouped: dict[tuple[str, str, str], dict[str, list[dict]]] = {}
    for edge in edges:
        target = edge.get("target_job", {})
        job_id = (
            target.get("namespace", "unknown"),
            target.get("name", "unknown"),
            target.get("kind", "script"),
        )
        if job_id not in grouped:
            grouped[job_id] = {"inputs": [], "outputs": []}
        src = edge.get("source_dataset", {})
        ds = {"namespace": src.get("namespace", ""), "name": src.get("name", "")}
        kind = edge.get("edge_kind", "")
        if kind == "reads_from":
            # dedupe by (namespace, name)
            if ds not in grouped[job_id]["inputs"]:
                grouped[job_id]["inputs"].append(ds)
        elif kind == "writes_to":
            if ds not in grouped[job_id]["outputs"]:
                grouped[job_id]["outputs"].append(ds)
    return grouped


def collect_job_sources(edges: list[dict]) -> dict[tuple[str, str, str], dict]:
    """Map each job to its defining source file + raw-file sha256 (WP-9).

    The project-aggregate edge carries ``source_file`` + ``source_file_sha256``
    (added by prompts/merge-across-files.md). A job is defined in a source file;
    we attribute the sha of that file as the job's contentSha256 join key. When a
    job's edges disagree on source file (multi-source job), we pick the
    lexicographically-smallest (source_file, sha) pair for determinism, so the
    facet is byte-identical across re-runs. Jobs whose edges carry no
    ``source_file_sha256`` get no facet (None) — the pre-WP-9 byte-identical path.
    """
    by_job: dict[tuple[str, str, str], set] = {}
    for edge in edges:
        tgt = edge.get("target_job", {})
        job_id = (
            tgt.get("namespace", "unknown"),
            tgt.get("name", "unknown"),
            tgt.get("kind", "script"),
        )
        sha = edge.get("source_file_sha256", "") or ""
        src = edge.get("source_file", "") or ""
        if sha:
            by_job.setdefault(job_id, set()).add((src, sha))
    out: dict[tuple[str, str, str], dict] = {}
    for job_id, pairs in by_job.items():
        src, sha = sorted(pairs)[0]
        out[job_id] = {"source_file": src, "content_sha256": sha}
    return out


def collect_unique_datasets(edges: list[dict]) -> list[dict]:
    """Collect unique datasets across all edges. Returns sorted list."""
    seen: dict[tuple[str, str], dict] = {}
    for edge in edges:
        src = edge.get("source_dataset", {})
        key = (src.get("namespace", ""), src.get("name", ""))
        if key not in seen:
            seen[key] = {
                "namespace": src.get("namespace", ""),
                "name": src.get("name", ""),
                "kind": src.get("kind", "file"),
            }
    return sorted(seen.values(), key=lambda d: (d["namespace"], d["name"]))


def write_csv_denormalized(edges: list[dict], output_path: Path) -> None:
    """Write the single denormalized lineage_edges.csv."""
    cols = [
        "src_dataset_namespace",
        "src_dataset_name",
        "src_kind",
        "target_job_namespace",
        "target_job_name",
        "target_job_kind",
        "edge_kind",
        "confidence",
        "evidence_file",
        "evidence_line",
        "extractor_id",
    ]

    def edge_to_row(edge: dict) -> dict:
        src = edge.get("source_dataset", {})
        tgt = edge.get("target_job", {})
        return {
            "src_dataset_namespace": src.get("namespace", ""),
            "src_dataset_name": src.get("name", ""),
            "src_kind": src.get("kind", ""),
            "target_job_namespace": tgt.get("namespace", ""),
            "target_job_name": tgt.get("name", ""),
            "target_job_kind": tgt.get("kind", ""),
            "edge_kind": edge.get("edge_kind", ""),
            "confidence": edge.get("confidence", ""),
            "evidence_file": edge.get("source_file", ""),
            "evidence_line": edge.get("evidence_line_start", ""),
            "extractor_id": EXTRACTOR_ID,
        }

    rows = sorted(
        (edge_to_row(e) for e in edges),
        key=lambda r: (
            r["target_job_namespace"],
            r["target_job_name"],
            r["edge_kind"],
            r["src_dataset_name"],
        ),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=output_path.name + ".tmp.",
        suffix=f".{os.getpid()}",
        dir=str(output_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols, quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def write_csv_ol_relational(
    edges: list[dict],
    datasets: list[dict],
    jobs_grouped: dict,
    output_dir: Path,
    with_static_run: bool,
    run_id: Optional[str],
) -> None:
    """Write the 4-CSV split (datasets, jobs, edges, runs[optional])."""
    # datasets.csv
    datasets_path = output_dir / "datasets.csv"
    fd, tmp = tempfile.mkstemp(prefix="datasets.csv.tmp.", suffix=f".{os.getpid()}", dir=str(output_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["namespace", "name", "kind"], quoting=csv.QUOTE_MINIMAL)
            w.writeheader()
            w.writerows(datasets)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, datasets_path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise

    # jobs.csv
    jobs_path = output_dir / "jobs.csv"
    fd, tmp = tempfile.mkstemp(prefix="jobs.csv.tmp.", suffix=f".{os.getpid()}", dir=str(output_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["namespace", "name", "kind"], quoting=csv.QUOTE_MINIMAL)
            w.writeheader()
            for (ns, name, kind) in sorted(jobs_grouped.keys()):
                w.writerow({"namespace": ns, "name": name, "kind": kind})
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, jobs_path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise

    # edges.csv (relational version: just the join keys, no denormalized dataset/job columns)
    edges_path = output_dir / "edges.csv"
    edge_rows = []
    for e in edges:
        src = e.get("source_dataset", {})
        tgt = e.get("target_job", {})
        edge_rows.append({
            "src_namespace": src.get("namespace", ""),
            "src_name": src.get("name", ""),
            "target_namespace": tgt.get("namespace", ""),
            "target_name": tgt.get("name", ""),
            "edge_kind": e.get("edge_kind", ""),
            "confidence": e.get("confidence", ""),
            "evidence_file": e.get("source_file", ""),
            "evidence_line": e.get("evidence_line_start", ""),
        })
    edge_rows.sort(key=lambda r: (r["target_namespace"], r["target_name"], r["edge_kind"], r["src_name"]))
    fd, tmp = tempfile.mkstemp(prefix="edges.csv.tmp.", suffix=f".{os.getpid()}", dir=str(output_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(edge_rows[0].keys()) if edge_rows else ["src_namespace", "src_name", "target_namespace", "target_name", "edge_kind", "confidence", "evidence_file", "evidence_line"], quoting=csv.QUOTE_MINIMAL)
            w.writeheader()
            w.writerows(edge_rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, edges_path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise

    # runs.csv (only when --with-static-run)
    if with_static_run and run_id:
        runs_path = output_dir / "runs.csv"
        fd, tmp = tempfile.mkstemp(prefix="runs.csv.tmp.", suffix=f".{os.getpid()}", dir=str(output_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["run_id", "producer"], quoting=csv.QUOTE_MINIMAL)
                w.writeheader()
                w.writerow({"run_id": run_id, "producer": STATIC_PRODUCER_URI})
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, runs_path)
        except Exception:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise


def merge_into_ol(
    rollup: dict,
    run_id: str,
    workspace_tree_hash: str,
    scan_started_at: str,
    output_dir: Path,
    with_static_run: bool = False,
    output_format: str = "default",
    schema_path: Optional[Path] = None,
) -> dict:
    """Emit OL events + CSV from the rollup. Returns summary dict.

    Fail-closed: any validation failure aborts via ValueError.
    """
    if schema_path is None:
        schema_path = DEFAULT_SCHEMA_PATH

    # Compile validators upfront (per-process cache)
    compile_validator(schema_path)

    edges = rollup.get("edges", [])

    # Collect unique datasets
    datasets = collect_unique_datasets(edges)

    # Group edges by job
    jobs_grouped = group_edges_by_job(edges)

    # Per-job source-file -> contentSha256 join key (WP-9). Empty when the rollup
    # carries no source_file_sha256 (pre-WP-9 byte-identical path).
    job_sources = collect_job_sources(edges)

    # Build events
    events: list[dict] = []

    # DatasetEvents (one per unique dataset)
    for ds in datasets:
        evt = make_dataset_event(ds, scan_started_at)
        validate_event_or_abort(evt, schema_path)  # fail-closed
        events.append(evt)

    # JobEvents (one per unique job)
    for job_id, io in sorted(jobs_grouped.items()):
        scl = None
        src_info = job_sources.get(job_id)
        if src_info and src_info.get("content_sha256"):
            scl = make_source_code_location_facet(
                src_info.get("source_file", ""),
                src_info["content_sha256"],
            )
        evt = make_job_event(
            job_id,
            inputs=io["inputs"],
            outputs=io["outputs"],
            scan_started_at=scan_started_at,
            workspace_tree_hash=workspace_tree_hash,
            source_code_location=scl,
        )
        validate_event_or_abort(evt, schema_path)
        events.append(evt)

    # RunEvents (only when opt-in)
    if with_static_run:
        synth_run_id = deterministic_run_id(workspace_tree_hash, scan_started_at)
        for evt in list(events):
            if evt["eventType"] == "JOB_EVENT":
                run_evt = make_run_event(synth_run_id, evt, scan_started_at)
                validate_event_or_abort(run_evt, schema_path)
                events.append(run_evt)
    else:
        synth_run_id = None

    # Emit ndjson + json bundle
    output_dir.mkdir(parents=True, exist_ok=True)
    ndjson_path = output_dir / "openlineage.ndjson"
    bundle_path = output_dir / "openlineage.json"

    ndjson_content = "\n".join(
        json.dumps(e, ensure_ascii=False, sort_keys=True) for e in events
    )
    if events:
        ndjson_content += "\n"
    atomic_write_text(ndjson_path, ndjson_content)

    bundle = {"events": events}
    atomic_write_text(
        bundle_path,
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )

    # CSV outputs
    if output_format == "ol-relational":
        write_csv_ol_relational(
            edges, datasets, jobs_grouped, output_dir, with_static_run, synth_run_id
        )
    else:
        # default: single denormalized lineage_edges.csv
        edges_csv = output_dir / "lineage_edges.csv"
        write_csv_denormalized(edges, edges_csv)

    return {
        "events_emitted": len(events),
        "datasets": len(datasets),
        "jobs": len(jobs_grouped),
        "ndjson_path": str(ndjson_path),
        "bundle_path": str(bundle_path),
        "synthetic_run_id": synth_run_id,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rollup_path", type=Path, help="Path to project-aggregate JSON (post-redaction)")
    parser.add_argument("run_id", help="Run identifier")
    parser.add_argument("workspace_tree_hash", help="Workspace tree sha256")
    parser.add_argument("scan_started_at", help="ISO 8601 timestamp")
    parser.add_argument("--output-dir", type=Path, required=True, help="Where to write OL outputs")
    parser.add_argument("--with-static-run", action="store_true", help="Opt-in RunEvent wrapping")
    parser.add_argument(
        "--output-format",
        choices=["default", "ol-relational"],
        default="default",
        help="CSV output mode (default = single denormalized lineage_edges.csv)",
    )
    parser.add_argument(
        "--schema-path",
        type=Path,
        default=DEFAULT_SCHEMA_PATH,
        help=f"Vendored OL schema path (default: {DEFAULT_SCHEMA_PATH})",
    )
    args = parser.parse_args(argv)

    if not args.rollup_path.exists():
        print(f"ERROR: Rollup not found: {args.rollup_path}", file=sys.stderr)
        return 1

    try:
        with args.rollup_path.open("r", encoding="utf-8") as f:
            rollup = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse rollup JSON: {e}", file=sys.stderr)
        return 1

    try:
        result = merge_into_ol(
            rollup,
            run_id=args.run_id,
            workspace_tree_hash=args.workspace_tree_hash,
            scan_started_at=args.scan_started_at,
            output_dir=args.output_dir,
            with_static_run=args.with_static_run,
            output_format=args.output_format,
            schema_path=args.schema_path,
        )
    except ValueError as e:
        # validate_event_or_abort raises ValueError on validation failure (HARD-RULE 1)
        print(f"FAIL-CLOSED: {e}", file=sys.stderr)
        return 1
    except (ImportError, SchemaPinMismatch, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
