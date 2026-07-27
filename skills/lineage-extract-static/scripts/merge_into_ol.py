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
    "https://foundry-lab.local/openlineage/facets/StaticAnalysisFacet/1-0-0.json"
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
# columnLineage 1-2-0 DATASET facet (2026-07-02 column-level uplift). The pin
# matches project_views.COLUMN_LINEAGE_SCHEMA_URL — build_graph reads
# facets.columnLineage.fields off output DatasetEvents; the DLP importer's
# PASS 2.5 consumes the same byte-shape. The facet carries NO confidence key
# (spec-review note: confidence lives in the skill's edge/report layer only).
COLUMN_LINEAGE_FACET_URI = (
    "https://openlineage.io/spec/facets/1-2-0/ColumnLineageDatasetFacet.json"
)
# documentation DATASET facet (2026-07-02 uplift): dataset_descriptions ->
# facets.documentation.description (the shape the DLP importer's
# _facet_description already reads).
DOCUMENTATION_FACET_URI = (
    "https://openlineage.io/spec/facets/1-0-1/DocumentationDatasetFacet.json"
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
            "_schemaURL": "https://foundry-lab.local/openlineage/facets/DatasetKindFacet/1-0-0.json",
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
    return _attach_dataset_facet_fail_open(event, "schema", schema_facet, schema_path)


def _attach_dataset_facet_fail_open(
    event: dict,
    facet_key: str,
    facet: dict,
    schema_path: Optional[Path] = None,
) -> tuple[dict, Optional[str]]:
    """Generalized fail-open dataset-facet attach (2026-07-02 uplift).

    Same contract as ``attach_schema_facet_fail_closed`` for any facet key
    (schema / columnLineage / documentation): validate the ENRICHED event; on
    rejection return the original event untouched plus a gap reason.
    """
    import copy as _copy

    if event.get("eventType") != "DATASET_EVENT":
        return (event, f"{facet_key} facet only applies to DATASET_EVENT")
    enriched = _copy.deepcopy(event)
    enriched.setdefault("dataset", {}).setdefault("facets", {})[facet_key] = facet
    is_valid, errors = validate_event(enriched, schema_path)
    if is_valid:
        return (enriched, None)
    reason = f"{facet_key} facet rejected by vendored OL schema: " + "; ".join(errors)
    return (event, reason)


def make_lineage_schema_facet(fields: list[dict]) -> dict:
    """Build a SchemaDatasetFacet from rollup ``dataset_schemas`` fields
    (2026-07-01 schema-facet uplift, lineage path).

    Unlike ``make_schema_dataset_facet`` (structure-recovery path, which
    normalizes a missing type to ``"unknown"``), the lineage path emits ``type``
    ONLY when it was stated in source — columns are never invented and neither
    are their types (confidence rule: named-in-source only). Same rule for
    ``description`` (2026-07-02 uplift): emitted only when stated in source
    (dbt schema.yml column description, copybook comment).
    """
    norm_fields: list[dict] = []
    for f in fields:
        name = f.get("name")
        if not name:
            continue
        fld: dict = {"name": str(name)}
        if f.get("type"):
            fld["type"] = str(f["type"])
        if f.get("description"):
            fld["description"] = str(f["description"])
        norm_fields.append(fld)
    return {
        "_producer": STATIC_PRODUCER_URI,
        "_schemaURL": SCHEMA_DATASET_FACET_URI,
        "fields": norm_fields,
    }


def make_column_lineage_facet(fields_map: dict) -> dict:
    """Build a columnLineage 1-2-0 facet (2026-07-02 column-level uplift).

    ``fields_map`` is ``{<output_field>: {"inputFields": [{namespace, name,
    field}]}}`` — the exact byte-shape ``project_views.build_graph`` reads and
    the DLP importer consumes. Input entries missing any of the three keys are
    dropped; output fields left with no inputFields are dropped (a mapping
    exists only when the source names both ends). NO confidence key ever rides
    on this facet (spec-review note).
    """
    norm: dict = {}
    for out_field, spec in (fields_map or {}).items():
        inputs = []
        for inf in (spec or {}).get("inputFields") or []:
            ns = inf.get("namespace", "")
            name = inf.get("name", "")
            field = inf.get("field", "")
            if ns and name and field:
                inputs.append({"namespace": str(ns), "name": str(name), "field": str(field)})
        if inputs:
            norm[str(out_field)] = {"inputFields": inputs}
    return {
        "_producer": STATIC_PRODUCER_URI,
        "_schemaURL": COLUMN_LINEAGE_FACET_URI,
        "fields": norm,
    }


def make_documentation_facet(description: str) -> dict:
    """Build a documentation DATASET facet (2026-07-02 uplift).

    Byte-shape matches what the DLP importer's ``_facet_description`` reads:
    ``facets.documentation.description``.
    """
    return {
        "_producer": STATIC_PRODUCER_URI,
        "_schemaURL": DOCUMENTATION_FACET_URI,
        "description": str(description),
    }


def expand_column_lineage(rollup: dict) -> tuple[dict, list[str], dict]:
    """Resolve rollup ``column_lineage`` entries to per-output field maps.

    Returns ``(cl_by_ds, gaps, propagated_schemas)`` where ``cl_by_ds`` maps
    ``(ns, name)`` of the OUTPUT dataset to a columnLineage 1-2-0 ``fields``
    map, ``gaps`` lists human-readable reasons for entries that were dropped
    (fail-open — a bad entry never aborts the emit), and
    ``propagated_schemas`` maps ``(ns, name)`` to a propagated field list per
    the corollary below.

    Explicit ``fields`` entries pass through (normalization happens in
    ``make_column_lineage_facet``). ``passthrough_from`` markers (§9 SELECT-*
    single-parent identity rule) expand deterministically iff BOTH hold:

    * the parent's column set is NAMED in ``rollup.dataset_schemas`` — the
      identity map propagates exactly that named set, 1:1;
    * some job in ``rollup.edges`` writes the output AND reads EXACTLY ONE
      distinct input dataset, which is the marked parent (the "exactly ONE
      input dataset" requirement, enforced deterministically here).

    Multi-input or unknown-parent SELECT-* yields NOTHING for that output
    (dual rule) — recorded as a gap, never guessed.

    **§9 corollary (a) — SELECT-* column-set propagation (user-approved
    2026-07-02):** a model that is exactly ``select * from <one parent>``
    whose parent has a NAMED-in-source column set gets that column set
    propagated as its OWN ``dataset_schemas`` entry — fields carry ``name``,
    plus ``type`` ONLY when the parent states it (never invented; the same
    deterministic-SQL argument as the identity mapping — the select-*
    statement itself is the evidence). Same constraints as the mapping rule:
    exactly one input, plain projection (the marker), known parent set —
    otherwise nothing. A dataset that already HAS its own dataset_schemas
    entry is never overwritten by propagation.
    """
    schemas_by_ds: dict[tuple[str, str], list[dict]] = {}
    for entry in rollup.get("dataset_schemas", []) or []:
        ns, name = entry.get("namespace", ""), entry.get("name", "")
        fields = entry.get("fields") or []
        if ns and name and fields:
            schemas_by_ds.setdefault((ns, name), fields)

    # (out_ns, out_name) -> set of distinct input (ns, name) per writing job.
    writers: dict[tuple[str, str], list[set]] = {}
    jobs_io: dict[tuple[str, str], dict[str, set]] = {}
    for edge in rollup.get("edges", []) or []:
        tgt = edge.get("target_job", {}) or {}
        job_key = (tgt.get("namespace", ""), tgt.get("name", ""))
        io = jobs_io.setdefault(job_key, {"inputs": set(), "outputs": set()})
        src = edge.get("source_dataset", {}) or {}
        ds_key = (src.get("namespace", ""), src.get("name", ""))
        kind = edge.get("edge_kind", "")
        if kind == "reads_from":
            io["inputs"].add(ds_key)
        elif kind == "writes_to":
            io["outputs"].add(ds_key)
    for io in jobs_io.values():
        for out_key in io["outputs"]:
            writers.setdefault(out_key, []).append(io["inputs"])

    entries = rollup.get("column_lineage", []) or []
    cl_by_ds: dict[tuple[str, str], dict] = {}
    gaps: list[str] = []
    propagated_schemas: dict[tuple[str, str], list[dict]] = {}
    # Phase 1 — explicit fields entries win unconditionally (order-independent).
    for entry in entries:
        ns, name = entry.get("namespace", ""), entry.get("name", "")
        fields = entry.get("fields")
        if ns and name and isinstance(fields, dict) and fields:
            cl_by_ds.setdefault((ns, name), fields)
    # Phase 2 — passthrough markers fill only outputs with no explicit entry.
    for entry in entries:
        ns, name = entry.get("namespace", ""), entry.get("name", "")
        if not ns or not name:
            continue
        key = (ns, name)
        label = f"{ns}/{name}"
        if isinstance(entry.get("fields"), dict) and entry.get("fields"):
            continue
        passthrough = entry.get("passthrough_from") or {}
        p_key = (passthrough.get("namespace", ""), passthrough.get("name", ""))
        if not p_key[0] or not p_key[1]:
            continue
        if key in cl_by_ds:
            continue  # explicit fields already won for this output
        parent_fields = schemas_by_ds.get(p_key)
        if not parent_fields:
            gaps.append(
                f"{label}: passthrough parent {p_key[0]}/{p_key[1]} has no "
                "named column set (dataset_schemas) — nothing emitted"
            )
            continue
        input_sets = writers.get(key, [])
        if not any(inputs == {p_key} for inputs in input_sets):
            gaps.append(
                f"{label}: no producing job reads EXACTLY the passthrough "
                f"parent {p_key[0]}/{p_key[1]} as its single input — nothing emitted"
            )
            continue
        identity: dict = {}
        for f in parent_fields:
            col = f.get("name")
            if col:
                identity[str(col)] = {
                    "inputFields": [
                        {"namespace": p_key[0], "name": p_key[1], "field": str(col)}
                    ]
                }
        if identity:
            cl_by_ds[key] = identity
            # §9 corollary (a) — propagate the parent's NAMED column set as
            # the passthrough output's own schema (name + parent-stated type
            # only; a dataset with its own dataset_schemas entry is never
            # overwritten — the caller checks before applying).
            if key not in schemas_by_ds:
                prop_fields: list[dict] = []
                for f in parent_fields:
                    col = f.get("name")
                    if not col:
                        continue
                    fld: dict = {"name": str(col)}
                    if f.get("type"):
                        fld["type"] = str(f["type"])
                    prop_fields.append(fld)
                if prop_fields:
                    propagated_schemas[key] = prop_fields
    return cl_by_ds, gaps, propagated_schemas


def make_business_static_analysis_facet(
    business: Optional[dict],
    dead_code: Optional[dict],
) -> dict:
    """Build the minimal dataset-side ``staticAnalysis`` facet (S59 business pass).

    Datasets carry no staticAnalysis facet on the pre-S59 path; when the
    business-analysis pass supplies ``business`` (``{purpose, domain}``) and/or
    ``dead_code`` (``{flag, evidence_file, evidence_line, reason}``) for a
    dataset, this facet carries them — same key shape as the job-side
    ``staticAnalysis.business`` / ``staticAnalysis.dead_code`` (design §3.1).
    Only emitted when at least one sub-object exists; datasets without business
    info stay byte-identical to the pre-S59 emission.
    """
    facet: dict = {
        "_producer": STATIC_PRODUCER_URI,
        "_schemaURL": STATIC_ANALYSIS_FACET_URI,
    }
    if business:
        facet["business"] = business
    if dead_code:
        facet["dead_code"] = dead_code
    return facet


def index_object_business(rollup: dict) -> tuple[dict, dict, list[str]]:
    """Index rollup ``object_business`` + ``dead_code`` entries (S59 WP-1).

    Returns ``(business_by_key, dead_by_key, gaps)`` where keys are
    ``(entity, namespace, name)`` with entity in {"dataset", "job"}.
    Business values are ``{purpose?, domain?}`` (at least one present);
    dead values are ``{flag: True, evidence_file, evidence_line, reason}``.

    Fail-open: entries with missing identity, neither purpose nor domain, or
    dead flags lacking ANY of the named-evidence fields (file + line + reason —
    the §3.1 "never inferred from absence alone" rule) are dropped with a gap
    note, never aborting the emit and never padded.
    """
    business_by_key: dict[tuple[str, str, str], dict] = {}
    dead_by_key: dict[tuple[str, str, str], dict] = {}
    gaps: list[str] = []
    for entry in rollup.get("object_business", []) or []:
        entity = entry.get("entity", "")
        ns, name = entry.get("namespace", ""), entry.get("name", "")
        if entity not in ("dataset", "job") or not ns or not name:
            gaps.append(f"object_business entry missing entity/namespace/name: {entry!r:.200}")
            continue
        biz: dict = {}
        if str(entry.get("purpose") or "").strip():
            biz["purpose"] = str(entry["purpose"]).strip()
        if str(entry.get("domain") or "").strip():
            biz["domain"] = str(entry["domain"]).strip()
        if not biz:
            gaps.append(f"object_business {ns}/{name}: neither purpose nor domain — dropped")
            continue
        business_by_key.setdefault((entity, ns, name), biz)
    for entry in rollup.get("dead_code", []) or []:
        entity = entry.get("entity", "")
        ns, name = entry.get("namespace", ""), entry.get("name", "")
        label = f"dead_code {ns}/{name}"
        if entity not in ("dataset", "job") or not ns or not name:
            gaps.append(f"dead_code entry missing entity/namespace/name: {entry!r:.200}")
            continue
        evidence_file = str(entry.get("evidence_file") or "").strip()
        evidence_line = entry.get("evidence_line")
        reason = str(entry.get("reason") or "").strip()
        if not evidence_file or not isinstance(evidence_line, int) or not reason:
            gaps.append(
                f"{label}: dead flag without NAMED evidence "
                "(evidence_file + evidence_line + reason all required) — dropped"
            )
            continue
        dead_by_key.setdefault(
            (entity, ns, name),
            {
                "flag": True,
                "evidence_file": evidence_file,
                "evidence_line": evidence_line,
                "reason": reason,
            },
        )
    return business_by_key, dead_by_key, gaps


REFERENCE_DATASET_KINDS = ("seed", "lookup")


def index_dataset_kinds(rollup: dict) -> tuple[dict, list[str]]:
    """Index rollup ``dataset_kinds`` reference-data tags (S59 §3.3 pin).

    Returns ``({(ns, name): kind}, gaps)`` with kind restricted to
    ``seed``/``lookup`` — the values the DLP importer lands in
    ``elements.subtype`` and the report builder's no-consumer exemption reads.
    Other kinds are dropped with a gap note (fail-open).
    """
    kinds: dict[tuple[str, str], str] = {}
    gaps: list[str] = []
    for entry in rollup.get("dataset_kinds", []) or []:
        ns, name = entry.get("namespace", ""), entry.get("name", "")
        kind = str(entry.get("kind") or "").strip()
        if not ns or not name:
            gaps.append(f"dataset_kinds entry missing namespace/name: {entry!r:.200}")
            continue
        if kind not in REFERENCE_DATASET_KINDS:
            gaps.append(
                f"dataset_kinds {ns}/{name}: kind {kind!r} not in "
                f"{REFERENCE_DATASET_KINDS} — dropped"
            )
            continue
        kinds.setdefault((ns, name), kind)
    return kinds, gaps


def assemble_manifest_business(
    rollup: dict,
    workspace_tree_hash: str,
    known_object_keys: set,
) -> tuple[Optional[dict], list[str]]:
    """Assemble the ``manifest.business`` block (design §3.1, S59 WP-1).

    Pure + fail-open: reads the rollup's project-level ``business`` block and
    returns ``(block_or_None, gaps)``. The caller (SKILL.md orchestration)
    drops the block into ``manifest.json`` verbatim.

    Rules enforced here:
    - sections OMITTED when the source gave nothing (empty string / list —
      never padded);
    - domains partition ONLY objects present in the bundle: members not in
      ``known_object_keys`` (the union of dataset and job ``(ns, name)`` keys)
      are dropped with a gap note;
    - single primary domain per member: a member already claimed by an earlier
      domain is dropped from later ones with a gap note;
    - a domain left with zero members is dropped with a gap note;
    - ``generated_by`` + ``tree_hash`` always stamped when a block is emitted.
    """
    raw = rollup.get("business")
    if not isinstance(raw, dict) or not raw:
        return None, []
    gaps: list[str] = []
    block: dict = {}
    for key in ("overview", "narrative", "flow_summary"):
        val = str(raw.get(key) or "").strip()
        if val:
            block[key] = val
    domains_out: list[dict] = []
    claimed: dict[tuple[str, str], str] = {}
    for dom in raw.get("domains", []) or []:
        dname = str(dom.get("name") or "").strip()
        if not dname:
            gaps.append("business domain without a name — dropped")
            continue
        members_out: list[dict] = []
        for m in dom.get("members", []) or []:
            ns, name = m.get("namespace", ""), m.get("name", "")
            if not ns or not name:
                gaps.append(f"domain {dname!r}: member missing namespace/name — dropped")
                continue
            if (ns, name) not in known_object_keys:
                gaps.append(
                    f"domain {dname!r}: member {ns}/{name} not present in the "
                    "bundle — dropped"
                )
                continue
            prior = claimed.get((ns, name))
            if prior is not None:
                if prior != dname:
                    gaps.append(
                        f"domain {dname!r}: member {ns}/{name} already claimed by "
                        f"domain {prior!r} (single primary domain per member) — dropped"
                    )
                continue
            claimed[(ns, name)] = dname
            members_out.append({"namespace": ns, "name": name})
        if not members_out:
            gaps.append(f"domain {dname!r}: no surviving members — dropped")
            continue
        dout: dict = {"name": dname, "members": members_out}
        for key in ("description", "flow"):
            val = str(dom.get(key) or "").strip()
            if val:
                dout[key] = val
        domains_out.append(dout)
    if domains_out:
        block["domains"] = domains_out
    if not block:
        return None, gaps
    block["generated_by"] = EXTRACTOR_ID
    block["tree_hash"] = workspace_tree_hash
    return block, gaps


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
    business: Optional[dict] = None,
    dead_code: Optional[dict] = None,
) -> dict:
    """Emit a JobEvent for (namespace, name, kind) tuple. The custom
    staticAnalysis facet is attached per HARD-RULE 1.

    When ``source_code_location`` is provided (WP-9) it is attached under
    ``job.facets.sourceCodeLocation`` carrying the contentSha256 join key.
    ``source_code_location=None`` (the default) yields a byte-identical event to
    the pre-WP-9 emission — the existing path is unchanged.

    ``business`` / ``dead_code`` (S59 business pass, design §3.1) ride INSIDE
    the existing staticAnalysis facet as ``staticAnalysis.business`` /
    ``staticAnalysis.dead_code``; ``None`` (the default) keeps the pre-S59
    byte-identical emission.
    """
    job_ns, job_name, job_kind = job_id
    facets: dict = {
        "jobKind": {
            "_producer": STATIC_PRODUCER_URI,
            "_schemaURL": "https://foundry-lab.local/openlineage/facets/JobKindFacet/1-0-0.json",
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
    if business:
        facets["staticAnalysis"]["business"] = business
    if dead_code:
        facets["staticAnalysis"]["dead_code"] = dead_code
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

    # Schema-facet uplift (2026-07-01): rollup dataset_schemas -> facets.schema
    # on the matching DatasetEvent. Keyed on the SAME (namespace, name) the edges
    # use; entries with no usable fields are skipped. Attachment is fail-open per
    # attach_schema_facet_fail_closed — a facet the vendored OL schema rejects is
    # dropped (event emitted facet-less) rather than aborting the run.
    schemas_by_ds: dict[tuple[str, str], list[dict]] = {}
    for entry in rollup.get("dataset_schemas", []) or []:
        ns, name = entry.get("namespace", ""), entry.get("name", "")
        fields = entry.get("fields") or []
        if ns and name and fields:
            schemas_by_ds.setdefault((ns, name), fields)
    schema_facets_attached = 0
    schema_facet_gaps: list[str] = []

    # Column-level uplift (2026-07-02): resolve column_lineage entries (explicit
    # fields + §9 passthrough markers) to per-OUTPUT field maps, and index
    # dataset_descriptions. Both attach fail-open like the schema facet.
    # §9 corollary (a) (user-approved 2026-07-02): passthrough outputs with no
    # own schema entry inherit the parent's NAMED column set so their columns
    # materialize downstream; never overwrites an explicit entry.
    cl_by_ds, column_lineage_gaps, propagated_schemas = expand_column_lineage(rollup)
    schemas_propagated = 0
    for _pkey, _pfields in propagated_schemas.items():
        if _pkey not in schemas_by_ds:
            schemas_by_ds[_pkey] = _pfields
            schemas_propagated += 1
    output_ds_keys: set[tuple[str, str]] = set()
    for io in jobs_grouped.values():
        for d in io["outputs"]:
            output_ds_keys.add((d.get("namespace", ""), d.get("name", "")))
    descriptions_by_ds: dict[tuple[str, str], str] = {}
    for entry in rollup.get("dataset_descriptions", []) or []:
        ns, name = entry.get("namespace", ""), entry.get("name", "")
        desc = entry.get("description", "")
        if ns and name and desc:
            descriptions_by_ds.setdefault((ns, name), str(desc))
    column_lineage_facets_attached = 0
    documentation_facets_attached = 0

    # Business pass (S59 WP-1): per-object business/dead_code facets, seed/
    # lookup datasetKind overrides, and the manifest.business assembly. All
    # fail-open — malformed entries become business_gaps, never an abort; a
    # rollup without the business keys stays byte-identical to pre-S59 output.
    business_by_key, dead_by_key, business_gaps = index_object_business(rollup)
    kind_overrides, kind_gaps = index_dataset_kinds(rollup)
    business_gaps.extend(kind_gaps)
    dataset_keys = {(d["namespace"], d["name"]) for d in datasets}
    job_ns_names = {(ns, name) for (ns, name, _kind) in jobs_grouped}
    known_object_keys = dataset_keys | job_ns_names
    for (entity, ns, name) in sorted(set(business_by_key) | set(dead_by_key)):
        present = (ns, name) in (dataset_keys if entity == "dataset" else job_ns_names)
        if not present:
            business_gaps.append(
                f"business/dead_code entry for unknown {entity} {ns}/{name} — not attached"
            )
    dataset_kinds_applied = 0
    for ds in datasets:
        override = kind_overrides.get((ds["namespace"], ds["name"]))
        if override:
            ds["kind"] = override
            dataset_kinds_applied += 1
    for key, kind in sorted(kind_overrides.items()):
        if key not in dataset_keys:
            business_gaps.append(
                f"dataset_kinds {key[0]}/{key[1]}: dataset not in bundle — not applied"
            )
    manifest_business, mb_gaps = assemble_manifest_business(
        rollup, workspace_tree_hash, known_object_keys
    )
    business_gaps.extend(mb_gaps)
    business_facets_attached = 0
    dead_code_facets_attached = 0

    # Build events
    events: list[dict] = []

    # DatasetEvents (one per unique dataset)
    for ds in datasets:
        evt = make_dataset_event(ds, scan_started_at)
        validate_event_or_abort(evt, schema_path)  # fail-closed
        ds_key = (ds["namespace"], ds["name"])
        fields = schemas_by_ds.get(ds_key)
        if fields:
            facet = make_lineage_schema_facet(fields)
            if facet["fields"]:
                evt, gap_reason = attach_schema_facet_fail_closed(
                    evt, facet, schema_path
                )
                if gap_reason is None:
                    schema_facets_attached += 1
                else:
                    schema_facet_gaps.append(
                        f"{ds['namespace']}/{ds['name']}: {gap_reason}"
                    )
        cl_fields = cl_by_ds.get(ds_key)
        if cl_fields and ds_key in output_ds_keys:
            facet = make_column_lineage_facet(cl_fields)
            if facet["fields"]:
                evt, gap_reason = _attach_dataset_facet_fail_open(
                    evt, "columnLineage", facet, schema_path
                )
                if gap_reason is None:
                    column_lineage_facets_attached += 1
                else:
                    column_lineage_gaps.append(
                        f"{ds['namespace']}/{ds['name']}: {gap_reason}"
                    )
        elif cl_fields:
            column_lineage_gaps.append(
                f"{ds['namespace']}/{ds['name']}: column_lineage entry for a "
                "dataset no job writes — facet not attached"
            )
        desc = descriptions_by_ds.get(ds_key)
        if desc:
            evt, gap_reason = _attach_dataset_facet_fail_open(
                evt, "documentation", make_documentation_facet(desc), schema_path
            )
            if gap_reason is None:
                documentation_facets_attached += 1
            else:
                column_lineage_gaps.append(
                    f"{ds['namespace']}/{ds['name']}: {gap_reason}"
                )
        ds_business = business_by_key.get(("dataset",) + ds_key)
        ds_dead = dead_by_key.get(("dataset",) + ds_key)
        if ds_business or ds_dead:
            facet = make_business_static_analysis_facet(ds_business, ds_dead)
            evt, gap_reason = _attach_dataset_facet_fail_open(
                evt, "staticAnalysis", facet, schema_path
            )
            if gap_reason is None:
                if ds_business:
                    business_facets_attached += 1
                if ds_dead:
                    dead_code_facets_attached += 1
            else:
                business_gaps.append(f"{ds['namespace']}/{ds['name']}: {gap_reason}")
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
        job_business = business_by_key.get(("job", job_id[0], job_id[1]))
        job_dead = dead_by_key.get(("job", job_id[0], job_id[1]))
        evt = make_job_event(
            job_id,
            inputs=io["inputs"],
            outputs=io["outputs"],
            scan_started_at=scan_started_at,
            workspace_tree_hash=workspace_tree_hash,
            source_code_location=scl,
            business=job_business,
            dead_code=job_dead,
        )
        validate_event_or_abort(evt, schema_path)
        if job_business:
            business_facets_attached += 1
        if job_dead:
            dead_code_facets_attached += 1
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
        "schema_facets_attached": schema_facets_attached,
        "schema_facet_gaps": schema_facet_gaps,
        "column_lineage_facets_attached": column_lineage_facets_attached,
        "column_lineage_gaps": column_lineage_gaps,
        "documentation_facets_attached": documentation_facets_attached,
        "schemas_propagated": schemas_propagated,
        "business_facets_attached": business_facets_attached,
        "dead_code_facets_attached": dead_code_facets_attached,
        "dataset_kinds_applied": dataset_kinds_applied,
        "business_gaps": business_gaps,
        "manifest_business": manifest_business,
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
