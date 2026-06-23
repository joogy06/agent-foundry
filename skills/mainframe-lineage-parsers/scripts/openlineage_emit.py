#!/usr/bin/env python3
"""openlineage_emit.py — map the assembled mainframe IR -> OpenLineage 2.0.2 ndjson.

WP-9 of the mainframe-lineage-parsers skill (design §3 "the single IR -> OL
mapper"). This is the ONE serializer that turns the WP-8 assembled IR
(``graph_assemble.assemble(...).ir`` — canonical-sorted, deduped, stitched, with
gap nodes carried through) into spec-correct OpenLineage 2.0.2 ``JobEvent`` +
``DatasetEvent`` ndjson.

REUSE, DON'T REINVENT (design §3, reuse_anchors.ol_emit). This module imports the
sibling ``lineage-extract-static/scripts``:

  * ``merge_into_ol.make_dataset_event`` / ``make_job_event`` — the event shape
    (eventType / eventTime / producer / schemaURL / facets-self-description);
  * ``merge_into_ol.atomic_write_text`` — the .tmp + fsync + os.replace atomic
    writer (named anchor parity with the siblings);
  * ``validate_ol.validate_event_or_abort`` — FAIL-CLOSED validation against the
    vendored OL 2.0.2 schema on EVERY event BEFORE it is written.

There is NO second hand-rolled OL serializer (acceptance criterion).

What this skill adds on top of the sibling shape:

  * a DISTINCT ``extractor_id = "mainframe-lineage-parsers"`` (so a side-by-side
    diff vs the LLM ``lineage-extract-static`` flow is attributable);
  * an ``engine`` facet (``sqlglot`` | ``regex`` | ``stdlib``) on every JobEvent;
  * a custom ``mainframeLineage`` facet on each input/output dataset reference
    carrying the per-edge ``kind`` + ``confidence`` (the two independent IR
    facets) + the full provenance (parser / engine / rule_id / source spans /
    copybook-expansion stack / dialect / unresolved-deps / raw tokens);
  * gap nodes (the frozen v1 closed set: unresolved_copy / free_format_unsupported
    / symbolic_dsn / catalog_less_column) surfaced as DatasetEvents carrying a
    ``mainframeGap`` facet — so a gap is VISIBLE in the OL stream, never silently
    dropped (C3), and the raw evidence (raw_dsn / raw_host_var / raw_copy_member)
    travels with it.

FAIL-CLOSED on the custom facets (mirrors structure-recovery §9 note-3): the
vendored OL 2.0.2 ``Job.facets`` / ``DatasetRef.facets`` are open objects (each
facet self-describes via ``_producer`` / ``_schemaURL``), so the custom facets
ARE accepted — but every event is still validated before write, so if a facet
ever made an event invalid the run aborts rather than emit malformed output.

Determinism: events are emitted in canonical order (datasets sorted by
(namespace, name); jobs sorted by (namespace, name); the input/output lists per
job sorted by (namespace, name); ndjson lines use ``sort_keys=True``), so the
output is byte-identical on re-run. ``eventTime`` is supplied by the caller (the
WP-10 CLI passes a fixed ``SOURCE_DATE_EPOCH``-derived stamp for reproducibility);
it defaults to a fixed epoch here so a bare call is still deterministic.

Pure stdlib + the two sibling modules (themselves stdlib + jsonschema). NO LLM,
NO network, NO new mandatory pip dep (D1/C2).

CLI usage (diagnostic; the real wiring is WP-10 run_lineage.py):
    openlineage_emit.py --help

Python API:
    from openlineage_emit import emit_openlineage, build_events
    summary = emit_openlineage(assembled_ir, out_path, engine="regex")
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --- locate + import the sibling lineage-extract-static OL machinery -----------
# We path-import the sibling scripts dir (NOT a copy/fork) so the OL event shape
# + validator + atomic writer are the SAME ones the LLM flow uses.
_THIS = Path(__file__).resolve()
_SKILLS_ROOT = _THIS.parents[2]  # .../skills
_SIBLING_SCRIPTS = _SKILLS_ROOT / "lineage-extract-static" / "scripts"
_SIBLING_SCHEMA = (
    _SKILLS_ROOT / "lineage-extract-static" / "schemas" / "openlineage-2.0.2-vendored.json"
)

if str(_SIBLING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SIBLING_SCRIPTS))

import merge_into_ol as _ol  # noqa: E402  (sibling emit shape — REUSED, not forked)
from validate_ol import (  # noqa: E402
    DEFAULT_SCHEMA_PATH,
    validate_event,
    validate_event_or_abort,
    SchemaPinMismatch,
)

# --- import the local IR (sibling-to-this-skill) -------------------------------
if str(_THIS.parent) not in sys.path:
    sys.path.insert(0, str(_THIS.parent))
import ir as _ir  # noqa: E402

# --- this skill's identity (DISTINCT from lineage-extract-static) --------------
EXTRACTOR_ID = "mainframe-lineage-parsers"
EXTRACTOR_VERSION = "1.0.0"
PRODUCER_URI = "urn:lineage:mainframe-lineage-parsers"

# Custom-facet self-description URIs (each facet self-describes per the OL open
# facets convention; these are this skill's facet spec URIs).
MAINFRAME_LINEAGE_FACET_URI = (
    "https://skill-factory.local/openlineage/facets/MainframeLineageFacet/1-0-0.json"
)
MAINFRAME_GAP_FACET_URI = (
    "https://skill-factory.local/openlineage/facets/MainframeGapFacet/1-0-0.json"
)
ENGINE_FACET_URI = (
    "https://skill-factory.local/openlineage/facets/EngineFacet/1-0-0.json"
)

# WP-4 (a): the STANDARD OpenLineage columnLineage dataset facet (live-verified
# current at 1-2-0). Attached to the OUTPUT dataset for host-var->column edges.
# The custom mainframeLineage confidence facet STAYS alongside (the standard
# facet has no confidence slot).
COLUMN_LINEAGE_FACET_URI = (
    "https://openlineage.io/spec/facets/1-2-0/ColumnLineageDatasetFacet.json"
)

# WP-4 (b): the CUSTOM controlmDependencies JOB facet (NOT a Run facet). Field
# names deliberately mirror JobDependenciesRunFacet so a future Run-stream
# migration is a rename. Honest: it is static design-time scheduling deps.
CONTROLM_DEPS_FACET_URI = (
    "https://skill-factory.local/openlineage/facets/ControlmDependenciesJobFacet/1-0-0.json"
)

# WP-4 (d): the STANDARD OpenLineage sourceCodeLocation JOB facet, carrying the
# v1.1 join key ``contentSha256`` = sha256 of the RAW on-disk source bytes,
# PRE-copybook-expansion / pre-symbol-substitution, no encoding normalization
# (INV-6 — byte-identical definition to the lineage WP-9 facet).
SOURCE_CODE_LOCATION_FACET_URI = (
    "https://openlineage.io/spec/facets/1-0-1/SourceCodeLocationJobFacet.json"
)

# The Control-M scheduler namespace prefix — used to detect Control-M job nodes
# that carry the controlmDependencies facet.
_CONTROLM_NS_PREFIX = "controlm://"
# The Control-M DAG dependency rule ids (graph_assemble re-keys but preserves the
# rule_id on provenance) — used to find scheduling edges for the deps facet.
_CONTROLM_DAG_RULE = "controlm.dag.event_dependency"
_CONTROLM_PROGRAM_RULE = "controlm.command.program_bind"

# A fixed deterministic default event time (caller overrides for a real run).
DEFAULT_EVENT_TIME = "1970-01-01T00:00:00Z"

# Engine facet allowed values (the engine that actually ran).
_ENGINE_VALUES = ("sqlglot", "regex", "stdlib")

# OL spec: a JobEvent's job.kind facet (we map every mainframe job to "job").
JOB_KIND = "job"


# ==============================================================================
# Facet builders (this skill's custom facets, self-describing)
# ==============================================================================
def _engine_facet(engine: str) -> dict:
    """The per-job ``engine`` facet: which SQL/parse engine actually ran."""
    eng = engine if engine in _ENGINE_VALUES else "stdlib"
    return {
        "_producer": PRODUCER_URI,
        "_schemaURL": ENGINE_FACET_URI,
        "extractor_id": EXTRACTOR_ID,
        "extractor_version": EXTRACTOR_VERSION,
        "engine": eng,
        "mode": "static-extract",
        "runtime_observed": False,
    }


def _provenance_to_dict(prov: "_ir.Provenance") -> dict:
    """Serialize an ir.Provenance into a JSON-safe, deterministic dict.

    Lists are already deduped+sorted by the IR / assembler; we keep that order.
    Empty fields are OMITTED so the facet is minimal + stable."""
    out: Dict[str, object] = {}
    if prov.parser:
        out["parser"] = prov.parser
    if prov.engine:
        out["engine"] = prov.engine
    if prov.rule_id:
        out["rule_id"] = prov.rule_id
    if prov.dialect:
        out["dialect"] = prov.dialect
    if prov.source_spans:
        out["source_spans"] = [
            {"file": s.file, "start_line": s.start_line,
             "end_line": s.end_line if s.end_line is not None else s.start_line}
            for s in prov.source_spans
        ]
    if prov.copybook_expansion_stack:
        out["copybook_expansion_stack"] = list(prov.copybook_expansion_stack)
    if prov.unresolved_deps:
        out["unresolved_deps"] = list(prov.unresolved_deps)
    if prov.raw_tokens:
        # sort keys for determinism
        out["raw_tokens"] = {k: prov.raw_tokens[k] for k in sorted(prov.raw_tokens)}
    if prov.notes:
        out["notes"] = list(prov.notes)
    return out


def _mainframe_lineage_facet(edge: "_ir.Edge") -> dict:
    """The per-edge ``mainframeLineage`` facet: the two independent IR facets
    (kind + confidence) + the full provenance. Carried on the dataset reference
    that participates in the edge (input or output)."""
    return {
        "_producer": PRODUCER_URI,
        "_schemaURL": MAINFRAME_LINEAGE_FACET_URI,
        "kind": edge.kind,
        "confidence": edge.confidence,
        "provenance": _provenance_to_dict(edge.provenance),
    }


def _mainframe_gap_facet(gap: "_ir.GapNode") -> dict:
    """The ``mainframeGap`` facet for a gap node: type + confidence + raw evidence."""
    facets = {k: gap.facets[k] for k in sorted(gap.facets)} if gap.facets else {}
    out: Dict[str, object] = {
        "_producer": PRODUCER_URI,
        "_schemaURL": MAINFRAME_GAP_FACET_URI,
        "gap_type": gap.gap_type,
        "confidence": gap.confidence,
        "evidence": facets,
    }
    if gap.source_span is not None:
        s = gap.source_span
        out["source_span"] = {
            "file": s.file,
            "start_line": s.start_line,
            "end_line": s.end_line if s.end_line is not None else s.start_line,
        }
    return out


# ==============================================================================
# WP-4 (a): STANDARD columnLineage 1-2-0 facet builder
# ==============================================================================
def _is_column_edge(edge: "_ir.Edge") -> bool:
    """True for a host-var -> column edge (rule_id ``sql.hostvar.column``). The
    edge SOURCE is the column node (``...<table>.<COLUMN>`` with a ``raw_column``
    facet); the TARGET is the program job node."""
    return (
        edge.provenance.rule_id == "sql.hostvar.column"
        and "raw_column" in edge.source.facets
        and "of_table" in edge.source.facets
    )


def _column_lineage_facet(col_edges: List["_ir.Edge"]) -> Optional[dict]:
    """Build the STANDARD OpenLineage ``columnLineage`` (1-2-0) DATASET facet for a
    table's host-var->column edges (design §5a).

    For each column edge: output column = the column name (``field``); the
    ``inputFields`` carry the host-var source; the transformation is
    ``{type:INDIRECT, subtype:CONDITIONAL, description:'host-var bind',
    masking:false}`` (INDIRECT — predicate-inferred, not a literal copy).

    The custom mainframeLineage confidence facet is carried separately on the
    dataset ref; this standard facet has no confidence slot (design §5a). Returns
    ``None`` when there are no column edges (so the facet is omitted, not empty)."""
    if not col_edges:
        return None
    fields: Dict[str, dict] = {}
    for e in sorted(col_edges, key=lambda x: x.canonical_key):
        column = e.source.facets.get("raw_column", "")
        out_col = column.upper() if column else e.source.name.rsplit(".", 1)[-1]
        host_var = e.provenance.raw_tokens.get("raw_host_var", "")
        input_fields = [{
            "namespace": e.source.namespace,
            "name": e.source.facets.get("of_table", ""),
            "field": host_var or out_col,
            "transformations": [{
                "type": "INDIRECT",
                "subtype": "CONDITIONAL",
                "description": "host-var bind",
                "masking": False,
            }],
        }]
        # Deterministic merge: if the same output column appears twice, union the
        # input fields (sorted) so the facet is byte-identical on re-run.
        if out_col in fields:
            existing = fields[out_col]["inputFields"]
            existing.extend(input_fields)
            seen = {(f["namespace"], f["name"], f["field"]): f for f in existing}
            fields[out_col]["inputFields"] = [
                seen[k] for k in sorted(seen)
            ]
        else:
            fields[out_col] = {"inputFields": input_fields}
    return {
        "_producer": PRODUCER_URI,
        "_schemaURL": COLUMN_LINEAGE_FACET_URI,
        "fields": {k: fields[k] for k in sorted(fields)},
    }


# ==============================================================================
# WP-4 (b): CUSTOM controlmDependencies JOB facet
# ==============================================================================
def _controlm_dependencies_facet(
    ir_obj: "_ir.IR", job: "_ir.Node"
) -> Optional[dict]:
    """Build the custom ``controlmDependencies`` JOB facet (design §5b) for a
    Control-M scheduler job node, or ``None`` for a non-Control-M / dep-less job.

    Schema (field names mirror JobDependenciesRunFacet so a future Run-stream
    migration is a rename):
        {upstream:[{namespace,name,dependency_type,sequence_trigger_rule,
                    status_trigger_rule}], downstream:[..]}

    ``dependency_type`` is ``DIRECT_INVOCATION`` for a program-bind edge and
    ``IMPLICIT_DEPENDENCY`` for an event-DAG scheduling edge. This is honest
    STATIC design-time deps (says so via ``static_design_time: true``), NOT a
    runtime Run facet."""
    if not job.namespace.startswith(_CONTROLM_NS_PREFIX):
        return None
    job_id = job.node_id
    upstream: List[dict] = []
    downstream: List[dict] = []
    for e in sorted(ir_obj.edges, key=lambda x: x.canonical_key):
        rule = e.provenance.rule_id
        if rule not in (_CONTROLM_DAG_RULE, _CONTROLM_PROGRAM_RULE):
            continue
        dep_type = (
            "DIRECT_INVOCATION" if rule == _CONTROLM_PROGRAM_RULE
            else "IMPLICIT_DEPENDENCY"
        )
        if e.target.node_id == job_id and e.source.node_id != job_id:
            upstream.append({
                "namespace": e.source.namespace,
                "name": e.source.name,
                "dependency_type": dep_type,
                "sequence_trigger_rule": "ALL",
                "status_trigger_rule": "OK",
            })
        elif e.source.node_id == job_id and e.target.node_id != job_id:
            downstream.append({
                "namespace": e.target.namespace,
                "name": e.target.name,
                "dependency_type": dep_type,
                "sequence_trigger_rule": "ALL",
                "status_trigger_rule": "OK",
            })
    if not upstream and not downstream:
        return None

    def _dedupe_sorted(rows: List[dict]) -> List[dict]:
        seen = {(r["namespace"], r["name"], r["dependency_type"]): r for r in rows}
        return [seen[k] for k in sorted(seen)]

    return {
        "_producer": PRODUCER_URI,
        "_schemaURL": CONTROLM_DEPS_FACET_URI,
        "static_design_time": True,
        "upstream": _dedupe_sorted(upstream),
        "downstream": _dedupe_sorted(downstream),
    }


# ==============================================================================
# WP-4 (d): STANDARD sourceCodeLocation.contentSha256 JOB facet
# ==============================================================================
def _content_sha256_for_job(job: "_ir.Node", ir_obj: "_ir.IR") -> Optional[str]:
    """Return the ``contentSha256`` for ``job`` if any edge provenance carries one.

    Extractors stamp the raw-source content hash onto edge provenance
    (``raw_tokens['content_sha256']``) so the emitter can surface it on the
    JobEvent. The hash is the sha256 of the RAW on-disk source bytes,
    PRE-copybook-expansion / pre-symbol-substitution (INV-6); the emitter does NOT
    recompute it — it only surfaces what the extractor recorded."""
    job_id = job.node_id
    for e in sorted(ir_obj.edges, key=lambda x: x.canonical_key):
        if job.node_id not in (e.source.node_id, e.target.node_id):
            continue
        sha = e.provenance.raw_tokens.get("content_sha256")
        if sha:
            return sha
    # Also accept a hash stamped directly on the job node facets.
    return job.facets.get("content_sha256")


def _attach_dataset_facet_fail_closed(
    event: dict, facet_name: str, facet: dict, schema_path
) -> Tuple[dict, Optional[str]]:
    """Attach ``facet`` under ``dataset.facets.<facet_name>``, FAIL-CLOSED (the
    structure-recovery §9 note-3 pattern; mirrors merge_into_ol.attach_schema_
    facet_fail_closed). If the enriched event validates, returns
    ``(enriched, None)``; if the facet would make the event invalid the facet is
    NOT applied and ``(original, gap_reason)`` is returned — a malformed facet can
    NEVER abort the whole-event emit (no malformed output, no fail-closed crash)."""
    import copy as _copy

    if event.get("eventType") != "DATASET_EVENT":
        return (event, f"{facet_name} facet only applies to DATASET_EVENT")
    enriched = _copy.deepcopy(event)
    enriched.setdefault("dataset", {}).setdefault("facets", {})[facet_name] = facet
    is_valid, errors = validate_event(enriched, schema_path)
    if is_valid:
        return (enriched, None)
    return (event, f"{facet_name} facet rejected by vendored OL schema: "
                   + "; ".join(errors))


def _attach_job_facet_fail_closed(
    event: dict, facet_name: str, facet: dict, schema_path
) -> Tuple[dict, Optional[str]]:
    """Attach ``facet`` under ``job.facets.<facet_name>``, FAIL-CLOSED (JOB-facet
    twin of :func:`_attach_dataset_facet_fail_closed`)."""
    import copy as _copy

    if event.get("eventType") != "JOB_EVENT":
        return (event, f"{facet_name} facet only applies to JOB_EVENT")
    enriched = _copy.deepcopy(event)
    enriched.setdefault("job", {}).setdefault("facets", {})[facet_name] = facet
    is_valid, errors = validate_event(enriched, schema_path)
    if is_valid:
        return (enriched, None)
    return (event, f"{facet_name} facet rejected by vendored OL schema: "
                   + "; ".join(errors))


def _source_code_location_facet(content_sha256: str, source_file: str = "") -> dict:
    """The STANDARD sourceCodeLocation JOB facet carrying ``contentSha256`` (the
    v1.1 join key; design §5d). ``type`` is ``file`` (a local source artifact)."""
    facet: Dict[str, object] = {
        "_producer": PRODUCER_URI,
        "_schemaURL": SOURCE_CODE_LOCATION_FACET_URI,
        "type": "file",
        "contentSha256": content_sha256,
    }
    if source_file:
        facet["url"] = source_file
    return facet


# ==============================================================================
# Edge -> input/output dataset partitioning
# ==============================================================================
def _is_job(node: "_ir.Node") -> bool:
    return node.node_type == "job"


def _dataset_ref(node: "_ir.Node", facet: Optional[dict]) -> dict:
    """Build an OL input/output dataset reference. The custom mainframeLineage
    facet (if any) self-describes; OL ``InputDataset``/``OutputDataset`` facets are
    an open object, so the custom facet is accepted."""
    ref: Dict[str, object] = {"namespace": node.namespace, "name": node.name}
    if facet is not None:
        ref["facets"] = {"mainframeLineage": facet}
    return ref


def _collect_datasets(ir_obj: "_ir.IR") -> List["_ir.Node"]:
    """All UNIQUE dataset nodes referenced by any edge endpoint OR standalone,
    sorted canonically by (namespace, name)."""
    seen: Dict[Tuple[str, str], "_ir.Node"] = {}
    for e in ir_obj.edges:
        for n in (e.source, e.target):
            if not _is_job(n):
                seen.setdefault((n.namespace, n.name), n)
    for n in ir_obj.nodes:
        if not _is_job(n):
            seen.setdefault((n.namespace, n.name), n)
    return [seen[k] for k in sorted(seen)]


def _collect_jobs(ir_obj: "_ir.IR") -> List["_ir.Node"]:
    """All UNIQUE job nodes, sorted canonically by (namespace, name)."""
    seen: Dict[Tuple[str, str], "_ir.Node"] = {}
    for e in ir_obj.edges:
        for n in (e.source, e.target):
            if _is_job(n):
                seen.setdefault((n.namespace, n.name), n)
    for n in ir_obj.nodes:
        if _is_job(n):
            seen.setdefault((n.namespace, n.name), n)
    return [seen[k] for k in sorted(seen)]


def _job_io(ir_obj: "_ir.IR", job: "_ir.Node") -> Tuple[List[dict], List[dict]]:
    """Partition the edges touching ``job`` into OL inputs (dataset -> job, the job
    reads the dataset) and outputs (job -> dataset, the job writes the dataset).

    Each dataset reference carries the per-edge mainframeLineage facet. The lists
    are deduped by (namespace, name) keeping the first (canonical-sorted) edge's
    facet, and sorted by (namespace, name) for determinism.

    Dataset-to-dataset edges (e.g. MOVE field-flow inside the program scope, whose
    endpoints are program-scoped ``field`` datasets, not the job node) are NOT
    encoded as job inputs/outputs — they have no job endpoint. They still surface
    as DatasetEvents (every dataset node gets one) so nothing is lost; field-flow
    is a within-program relationship, not a job I/O.
    """
    job_id = job.node_id
    inputs: Dict[Tuple[str, str], dict] = {}
    outputs: Dict[Tuple[str, str], dict] = {}
    # iterate edges in canonical order so "first wins" is deterministic
    for e in sorted(ir_obj.edges, key=lambda x: x.canonical_key):
        facet = _mainframe_lineage_facet(e)
        if e.target.node_id == job_id and not _is_job(e.source):
            key = (e.source.namespace, e.source.name)
            inputs.setdefault(key, _dataset_ref(e.source, facet))
        elif e.source.node_id == job_id and not _is_job(e.target):
            key = (e.target.namespace, e.target.name)
            outputs.setdefault(key, _dataset_ref(e.target, facet))
    in_list = [inputs[k] for k in sorted(inputs)]
    out_list = [outputs[k] for k in sorted(outputs)]
    return in_list, out_list


# ==============================================================================
# Event construction
# ==============================================================================
def build_events(
    assembled_ir: "_ir.IR",
    *,
    engine: str = "stdlib",
    event_time: str = DEFAULT_EVENT_TIME,
    schema_path: Optional[Path] = None,
) -> List[dict]:
    """Build the full, validated, canonically-ordered list of OL events.

    Order (deterministic): DatasetEvents (datasets sorted), then gap DatasetEvents
    (gaps sorted), then JobEvents (jobs sorted). Every event is validated
    FAIL-CLOSED against the vendored OL 2.0.2 schema before it is returned; an
    invalid event raises ``ValueError`` (no malformed output, ever).
    """
    if schema_path is None:
        schema_path = DEFAULT_SCHEMA_PATH

    events: List[dict] = []

    # WP-4 (a): index host-var->column edges by their OUTPUT table dataset so the
    # standard columnLineage 1-2-0 facet can be attached to that table's
    # DatasetEvent. The output table is identified by (namespace, of_table-name).
    col_edges_by_table: Dict[Tuple[str, str], List["_ir.Edge"]] = {}
    for e in assembled_ir.edges:
        if _is_column_edge(e):
            table_key = (e.source.namespace, e.source.facets.get("of_table", ""))
            col_edges_by_table.setdefault(table_key, []).append(e)

    # 1. DatasetEvents — one per unique dataset node (reuse the sibling shape).
    for ds in _collect_datasets(assembled_ir):
        evt = _ol.make_dataset_event(
            {"namespace": ds.namespace, "name": ds.name,
             "kind": ds.facets.get("kind", "file")},
            event_time,
        )
        # Re-stamp producer/schemaURL to THIS extractor's identity so a diff is
        # attributable (the sibling stamps its own; we stamp ours).
        evt["producer"] = PRODUCER_URI
        # WP-4 (a): attach the standard columnLineage facet to the OUTPUT table
        # dataset (host-var->column edges), routed through the fail-closed pattern
        # (a malformed facet -> a gap reason + the facet-less event, never abort).
        col_edges = col_edges_by_table.get((ds.namespace, ds.name))
        if col_edges:
            cl_facet = _column_lineage_facet(col_edges)
            if cl_facet is not None:
                evt, gap_reason = _attach_dataset_facet_fail_closed(
                    evt, "columnLineage", cl_facet, schema_path
                )
                # gap_reason is recorded as a diagnostic-only note; the event is
                # still emitted (facet-less if the facet was rejected). C3 honesty.
        validate_event_or_abort(evt, schema_path)
        events.append(evt)

    # 2. Gap DatasetEvents — surface every gap node VISIBLY (C3, never dropped).
    #    A gap is rendered as a DatasetEvent in this skill's gap namespace so it
    #    appears in the OL stream and carries the raw evidence facet.
    for gap in _sorted_gaps(assembled_ir.gaps):
        gap_ns = "mainframe://gap"
        gap_name = _gap_node_name(gap)
        evt = _ol.make_dataset_event(
            {"namespace": gap_ns, "name": gap_name, "kind": "gap"},
            event_time,
        )
        evt["producer"] = PRODUCER_URI
        evt["dataset"].setdefault("facets", {})["mainframeGap"] = _mainframe_gap_facet(gap)
        validate_event_or_abort(evt, schema_path)
        events.append(evt)

    # 3. JobEvents — one per unique job, with the engine facet + per-edge
    #    mainframeLineage facets on the input/output dataset refs.
    eng_facet = _engine_facet(engine)
    for job in _collect_jobs(assembled_ir):
        inputs, outputs = _job_io(assembled_ir, job)
        evt = _ol.make_job_event(
            (job.namespace, job.name, JOB_KIND),
            inputs=inputs,
            outputs=outputs,
            scan_started_at=event_time,
            workspace_tree_hash="",  # static extract; no workspace hash in v1
        )
        # Replace the sibling's staticAnalysis facet with THIS extractor's engine
        # facet (distinct extractor_id) — the job.facets object is open.
        evt["producer"] = PRODUCER_URI
        evt["job"]["facets"].pop("staticAnalysis", None)
        evt["job"]["facets"]["engine"] = eng_facet

        # WP-4 (b): the custom controlmDependencies JOB facet on Control-M jobs.
        ctm_deps = _controlm_dependencies_facet(assembled_ir, job)
        if ctm_deps is not None:
            evt, _gap = _attach_job_facet_fail_closed(
                evt, "controlmDependencies", ctm_deps, schema_path
            )

        # WP-4 (d): the standard sourceCodeLocation.contentSha256 JOB facet (the
        # v1.1 join key). Only when an extractor stamped a content hash.
        sha = _content_sha256_for_job(job, assembled_ir)
        if sha:
            scl = _source_code_location_facet(sha, job.facets.get("source_file", ""))
            evt, _gap = _attach_job_facet_fail_closed(
                evt, "sourceCodeLocation", scl, schema_path
            )

        validate_event_or_abort(evt, schema_path)
        events.append(evt)

    return events


def _sorted_gaps(gaps) -> list:
    """Canonical, deterministic gap order: (gap_type, sorted facet items)."""
    return sorted(
        gaps,
        key=lambda g: (g.gap_type, g.confidence,
                       tuple(sorted((g.facets or {}).items()))),
    )


def _gap_node_name(gap: "_ir.GapNode") -> str:
    """A stable, human-readable gap dataset name derived ONLY from the gap type +
    its raw evidence (never an invented id)."""
    raw = ""
    if gap.facets:
        # pick the single raw_* evidence value deterministically
        for k in sorted(gap.facets):
            if k.startswith("raw_"):
                raw = gap.facets[k]
                break
        if not raw:
            raw = gap.facets[sorted(gap.facets)[0]]
    return f"{gap.gap_type}:{raw}" if raw else gap.gap_type


# ==============================================================================
# Top-level emit
# ==============================================================================
def emit_openlineage(
    assembled_ir: "_ir.IR",
    out_path: Path,
    *,
    engine: str = "stdlib",
    event_time: str = DEFAULT_EVENT_TIME,
    schema_path: Optional[Path] = None,
) -> dict:
    """Build + validate + atomically write the OL 2.0.2 ndjson stream.

    Returns a summary dict. Fail-closed: an invalid event raises ``ValueError``
    (caught by the CLI / WP-10) before anything is written.
    """
    events = build_events(
        assembled_ir, engine=engine, event_time=event_time, schema_path=schema_path
    )
    ndjson = "\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in events)
    if events:
        ndjson += "\n"
    _ol.atomic_write_text(out_path, ndjson)

    n_dataset = sum(1 for e in events if e["eventType"] == "DATASET_EVENT")
    n_job = sum(1 for e in events if e["eventType"] == "JOB_EVENT")
    return {
        "extractor_id": EXTRACTOR_ID,
        "engine": engine if engine in _ENGINE_VALUES else "stdlib",
        "events_emitted": len(events),
        "dataset_events": n_dataset,
        "job_events": n_job,
        "gaps": len(assembled_ir.gaps),
        "ndjson_path": str(out_path),
    }


# ==============================================================================
# Diagnostic CLI (the real wiring is WP-10 run_lineage.py)
# ==============================================================================
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--src-cobol", type=Path, default=None,
        help="A COBOL source file (diagnostic: runs preprocess->copybook->"
             "cobol+sql extract->assemble->emit on it).",
    )
    parser.add_argument(
        "--src-jcl", type=Path, default=None,
        help="A JCL file (diagnostic: extracted + stitched with the COBOL).",
    )
    parser.add_argument("--out", type=Path, required=True, help="OL ndjson output path")
    parser.add_argument(
        "--engine", choices=["auto", "regex", "sqlglot-sql"], default="auto",
        help="SQL engine selection (the chosen engine is stamped into the facet).",
    )
    parser.add_argument("--program-id", default=None, help="COBOL PROGRAM-ID override")
    parser.add_argument("--schema", default=None, help="DB2 schema (else placeholder)")
    args = parser.parse_args(argv)

    if not args.src_cobol and not args.src_jcl:
        print("ERROR: supply --src-cobol and/or --src-jcl", file=sys.stderr)
        return 1

    # diagnostic chain (the full autonomous wiring lives in WP-10 run_lineage.py)
    import cobol_extract as _cob  # noqa: E402
    import jcl_extract as _jcl  # noqa: E402
    import sql_extract as _sql  # noqa: E402
    import graph_assemble as _ga  # noqa: E402

    slices = []
    chosen_engine = "stdlib"
    if args.src_jcl and args.src_jcl.exists():
        slices.append(_jcl.extract_jcl(args.src_jcl.read_text(encoding="utf-8"),
                                       file=args.src_jcl.name))
    if args.src_cobol and args.src_cobol.exists():
        text = args.src_cobol.read_text(encoding="utf-8")
        pid = args.program_id or args.src_cobol.stem.upper()
        slices.append(_cob.extract_cobol_text(text, file=args.src_cobol.name))
        try:
            sres = _sql.extract_sql_text(text, program_id=pid, file_label=args.src_cobol.name,
                                         engine=args.engine, schema=args.schema)
            slices.append(sres)
            chosen_engine = sres.chosen_engine
        except _sql.SqlglotUnavailableError as e:
            print(f"FAIL-LOUD: {e}", file=sys.stderr)
            return 2

    ag = _ga.assemble(slices)
    try:
        summary = emit_openlineage(ag.ir, args.out, engine=chosen_engine)
    except ValueError as e:
        print(f"FAIL-CLOSED: {e}", file=sys.stderr)
        return 1
    except (SchemaPinMismatch, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


__all__ = [
    "EXTRACTOR_ID",
    "EXTRACTOR_VERSION",
    "PRODUCER_URI",
    "build_events",
    "emit_openlineage",
]


if __name__ == "__main__":
    sys.exit(main())
