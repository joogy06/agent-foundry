"""columnLineage 1-2-0 + description emission (2026-07-02 column-level uplift).

Asserts the producer side of the DLP column-level views cycle: a rollup carrying
``column_lineage`` yields OUTPUT DatasetEvents with a ``columnLineage`` facet in
the exact byte-shape ``project_views.build_graph`` reads (and the DLP importer
consumes); the §9 SELECT-* dual rule (single-input known-parent passthrough
expands 1:1; multi-input or unknown-parent yields NOTHING); descriptions ride
the schema facet fields and the ``documentation`` facet; deterministic
re-emission. Runs against the real merge_into_ol + validate_ol with the
vendored OL 2.0.2 schema.
"""
from __future__ import annotations

import json

from accumulate import (
    merge_column_lineage,
    merge_dataset_descriptions,
    merge_dataset_schemas,
)
from merge_into_ol import expand_column_lineage, merge_into_ol
from project_views import build_graph

NS = "postgres://dwh:5432/analytics"


def _edge(edge_kind, ds_name, job_name="load.py:main"):
    return {
        "edge_kind": edge_kind,
        "source_dataset": {"namespace": NS, "name": ds_name, "kind": "table"},
        "target_job": {"namespace": "repo://etl", "name": job_name, "kind": "script"},
        "evidence_line_start": 3,
        "evidence_line_end": 3,
        "evidence_snippet": "SELECT ...",
        "confidence": "grounded",
        "confidence_reason": "literal table name",
        "source_file": "load.py",
    }


def _rollup(edges, **extra):
    rollup = {
        "schema_version": "1.0.0",
        "extractor_id": "lineage-extract-static",
        "scope": "project_aggregate",
        "edges": edges,
        "gaps": [],
    }
    rollup.update(extra)
    return rollup


def _emit(tmp_path, rollup):
    summary = merge_into_ol(
        rollup,
        run_id="r1",
        workspace_tree_hash="tree1",
        scan_started_at="2026-07-02T09:00:00Z",
        output_dir=tmp_path,
    )
    events = [json.loads(line) for line in
              (tmp_path / "openlineage.ndjson").read_text().splitlines() if line]
    return summary, events


def _dataset_events(events):
    return {e["dataset"]["name"]: e for e in events
            if e["eventType"] == "DATASET_EVENT"}


_STG_FIELDS = {
    "order_id": {"inputFields": [
        {"namespace": NS, "name": "public.raw_orders", "field": "id"}]},
    "ordered_at": {"inputFields": [
        {"namespace": NS, "name": "public.raw_orders", "field": "ordered_at"}]},
}


def _stg_rollup(**extra):
    edges = [_edge("reads_from", "public.raw_orders"),
             _edge("writes_to", "public.stg_orders")]
    return _rollup(edges, **extra)


def test_explicit_column_lineage_round_trips_through_project_views(tmp_path):
    cl = [{"namespace": NS, "name": "public.stg_orders", "fields": _STG_FIELDS}]
    summary, events = _emit(tmp_path, _stg_rollup(column_lineage=cl))
    ds = _dataset_events(events)
    facet = ds["public.stg_orders"]["dataset"]["facets"]["columnLineage"]
    assert facet["fields"] == _STG_FIELDS
    assert facet["_schemaURL"].endswith("1-2-0/ColumnLineageDatasetFacet.json")
    # NO confidence key rides on the facet (spec-review note).
    assert set(facet.keys()) == {"_producer", "_schemaURL", "fields"}
    # the INPUT dataset never gets the facet.
    assert "columnLineage" not in ds["public.raw_orders"]["dataset"]["facets"]
    assert summary["column_lineage_facets_attached"] == 1
    assert summary["column_lineage_gaps"] == []
    # byte-shape check: project_views.build_graph reads it back verbatim.
    graph = build_graph(events)
    assert graph["column_lineage"][(NS, "public.stg_orders")] == _STG_FIELDS


def test_select_star_passthrough_single_known_parent_expands_identity(tmp_path):
    schemas = [{"namespace": NS, "name": "public.stg_orders",
                "fields": [{"name": "order_id"}, {"name": "ordered_at"}]}]
    cl = [{"namespace": NS, "name": "public.orders_copy",
           "passthrough_from": {"namespace": NS, "name": "public.stg_orders"}}]
    edges = [_edge("reads_from", "public.stg_orders", "copy.sql:orders_copy"),
             _edge("writes_to", "public.orders_copy", "copy.sql:orders_copy")]
    summary, events = _emit(
        tmp_path, _rollup(edges, dataset_schemas=schemas, column_lineage=cl))
    facet = _dataset_events(events)["public.orders_copy"]["dataset"]["facets"]["columnLineage"]
    assert facet["fields"] == {
        "order_id": {"inputFields": [
            {"namespace": NS, "name": "public.stg_orders", "field": "order_id"}]},
        "ordered_at": {"inputFields": [
            {"namespace": NS, "name": "public.stg_orders", "field": "ordered_at"}]},
    }
    assert summary["column_lineage_facets_attached"] == 1
    assert summary["column_lineage_gaps"] == []


def test_select_star_passthrough_unknown_parent_yields_nothing(tmp_path):
    cl = [{"namespace": NS, "name": "public.orders_copy",
           "passthrough_from": {"namespace": NS, "name": "public.stg_orders"}}]
    edges = [_edge("reads_from", "public.stg_orders", "copy.sql:orders_copy"),
             _edge("writes_to", "public.orders_copy", "copy.sql:orders_copy")]
    summary, events = _emit(tmp_path, _rollup(edges, column_lineage=cl))
    for e in _dataset_events(events).values():
        assert "columnLineage" not in e["dataset"]["facets"]
    assert summary["column_lineage_facets_attached"] == 0
    assert any("no named column set" in g for g in summary["column_lineage_gaps"])


def test_select_star_passthrough_multi_input_producer_yields_nothing(tmp_path):
    schemas = [{"namespace": NS, "name": "public.stg_orders",
                "fields": [{"name": "order_id"}]}]
    cl = [{"namespace": NS, "name": "public.orders_copy",
           "passthrough_from": {"namespace": NS, "name": "public.stg_orders"}}]
    edges = [_edge("reads_from", "public.stg_orders", "copy.sql:orders_copy"),
             _edge("reads_from", "public.stg_payments", "copy.sql:orders_copy"),
             _edge("writes_to", "public.orders_copy", "copy.sql:orders_copy")]
    summary, events = _emit(
        tmp_path, _rollup(edges, dataset_schemas=schemas, column_lineage=cl))
    assert "columnLineage" not in \
        _dataset_events(events)["public.orders_copy"]["dataset"]["facets"]
    assert summary["column_lineage_facets_attached"] == 0
    assert any("single input" in g for g in summary["column_lineage_gaps"])


def test_column_lineage_for_non_output_dataset_is_gapped(tmp_path):
    # entry names a dataset no job writes -> facet not attached, honest gap.
    cl = [{"namespace": NS, "name": "public.raw_orders", "fields": _STG_FIELDS}]
    summary, events = _emit(tmp_path, _stg_rollup(column_lineage=cl))
    assert "columnLineage" not in \
        _dataset_events(events)["public.raw_orders"]["dataset"]["facets"]
    assert summary["column_lineage_facets_attached"] == 0
    assert any("no job writes" in g for g in summary["column_lineage_gaps"])


def test_field_descriptions_ride_the_schema_facet(tmp_path):
    schemas = [{"namespace": NS, "name": "public.stg_orders",
                "fields": [{"name": "order_id", "type": "bigint",
                            "description": "Primary key"},
                           {"name": "ordered_at"}]}]
    _summary, events = _emit(tmp_path, _stg_rollup(dataset_schemas=schemas))
    facet = _dataset_events(events)["public.stg_orders"]["dataset"]["facets"]["schema"]
    assert facet["fields"] == [
        {"name": "order_id", "type": "bigint", "description": "Primary key"},
        {"name": "ordered_at"},
    ]


def test_dataset_descriptions_attach_documentation_facet(tmp_path):
    descs = [{"namespace": NS, "name": "public.stg_orders",
              "description": "One row per order."}]
    summary, events = _emit(tmp_path, _stg_rollup(dataset_descriptions=descs))
    ds = _dataset_events(events)
    doc = ds["public.stg_orders"]["dataset"]["facets"]["documentation"]
    # exact byte-shape the DLP importer's _facet_description reads.
    assert doc["description"] == "One row per order."
    assert doc["_schemaURL"].endswith("DocumentationDatasetFacet.json")
    assert "documentation" not in ds["public.raw_orders"]["dataset"]["facets"]
    assert summary["documentation_facets_attached"] == 1


def test_reemission_is_byte_identical(tmp_path):
    schemas = [{"namespace": NS, "name": "public.stg_orders",
                "fields": [{"name": "order_id", "description": "PK"}]}]
    cl = [{"namespace": NS, "name": "public.stg_orders", "fields": _STG_FIELDS}]
    descs = [{"namespace": NS, "name": "public.stg_orders",
              "description": "One row per order."}]
    rollup = _stg_rollup(dataset_schemas=schemas, column_lineage=cl,
                         dataset_descriptions=descs)
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir(), d2.mkdir()
    _emit(d1, rollup)
    _emit(d2, rollup)
    assert (d1 / "openlineage.ndjson").read_bytes() == \
        (d2 / "openlineage.ndjson").read_bytes()


def test_expand_column_lineage_explicit_beats_passthrough():
    rollup = _stg_rollup(
        dataset_schemas=[{"namespace": NS, "name": "public.raw_orders",
                          "fields": [{"name": "id"}]}],
        column_lineage=[
            {"namespace": NS, "name": "public.stg_orders",
             "passthrough_from": {"namespace": NS, "name": "public.raw_orders"}},
            {"namespace": NS, "name": "public.stg_orders", "fields": _STG_FIELDS},
        ])
    cl_by_ds, gaps, propagated = expand_column_lineage(rollup)
    assert cl_by_ds[(NS, "public.stg_orders")] == _STG_FIELDS
    assert gaps == []
    # explicit fields won → no passthrough expansion → nothing propagated.
    assert propagated == {}


# --- §9 corollary (a) — SELECT-* column-set propagation (2026-07-02) --------


def test_passthrough_propagates_parent_schema_as_own(tmp_path):
    # The passthrough output has NO own dataset_schemas entry; the parent's
    # NAMED set (name + stated type only) propagates, so the OUTPUT gets a
    # schema facet the importer can materialize columns from.
    schemas = [{"namespace": NS, "name": "public.stg_orders",
                "fields": [{"name": "order_id", "type": "bigint"},
                           {"name": "ordered_at"}]}]
    cl = [{"namespace": NS, "name": "public.orders_copy",
           "passthrough_from": {"namespace": NS, "name": "public.stg_orders"}}]
    edges = [_edge("reads_from", "public.stg_orders", "copy.sql:orders_copy"),
             _edge("writes_to", "public.orders_copy", "copy.sql:orders_copy")]
    summary, events = _emit(
        tmp_path, _rollup(edges, dataset_schemas=schemas, column_lineage=cl))
    facet = _dataset_events(events)["public.orders_copy"]["dataset"]["facets"]["schema"]
    assert facet["fields"] == [{"name": "order_id", "type": "bigint"},
                               {"name": "ordered_at"}]
    assert summary["schemas_propagated"] == 1
    assert summary["schema_facets_attached"] == 2   # parent + propagated child
    assert summary["column_lineage_facets_attached"] == 1


def test_propagation_never_overwrites_own_schema(tmp_path):
    # The output declares its OWN column set — propagation must not clobber it.
    schemas = [
        {"namespace": NS, "name": "public.stg_orders",
         "fields": [{"name": "order_id"}, {"name": "ordered_at"}]},
        {"namespace": NS, "name": "public.orders_copy",
         "fields": [{"name": "own_col"}]},
    ]
    cl = [{"namespace": NS, "name": "public.orders_copy",
           "passthrough_from": {"namespace": NS, "name": "public.stg_orders"}}]
    edges = [_edge("reads_from", "public.stg_orders", "copy.sql:orders_copy"),
             _edge("writes_to", "public.orders_copy", "copy.sql:orders_copy")]
    summary, events = _emit(
        tmp_path, _rollup(edges, dataset_schemas=schemas, column_lineage=cl))
    facet = _dataset_events(events)["public.orders_copy"]["dataset"]["facets"]["schema"]
    assert facet["fields"] == [{"name": "own_col"}]
    assert summary["schemas_propagated"] == 0


def test_propagation_negatives_mirror_the_dual_rule(tmp_path):
    # unknown parent → no propagation, no schema facet on the output.
    cl = [{"namespace": NS, "name": "public.orders_copy",
           "passthrough_from": {"namespace": NS, "name": "public.stg_orders"}}]
    edges = [_edge("reads_from", "public.stg_orders", "copy.sql:orders_copy"),
             _edge("writes_to", "public.orders_copy", "copy.sql:orders_copy")]
    summary, events = _emit(tmp_path, _rollup(edges, column_lineage=cl))
    assert "schema" not in \
        _dataset_events(events)["public.orders_copy"]["dataset"]["facets"]
    assert summary["schemas_propagated"] == 0
    # multi-input producer → no propagation either.
    schemas = [{"namespace": NS, "name": "public.stg_orders",
                "fields": [{"name": "order_id"}]}]
    edges2 = [_edge("reads_from", "public.stg_orders", "copy.sql:orders_copy"),
              _edge("reads_from", "public.stg_payments", "copy.sql:orders_copy"),
              _edge("writes_to", "public.orders_copy", "copy.sql:orders_copy")]
    d2 = tmp_path / "multi"
    d2.mkdir()
    summary2, events2 = _emit(
        d2, _rollup(edges2, dataset_schemas=schemas, column_lineage=cl))
    assert "schema" not in \
        _dataset_events(events2)["public.orders_copy"]["dataset"]["facets"]
    assert summary2["schemas_propagated"] == 0


def test_merge_column_lineage_union_rules():
    chunk1 = [{"namespace": NS, "name": "b",
               "fields": {"x": {"inputFields": [
                   {"namespace": NS, "name": "a", "field": "x0"}]},
                          "y": {"inputFields": []}}}]
    chunk2 = [{"namespace": NS, "name": "b",
               "fields": {"x": {"inputFields": [
                   {"namespace": NS, "name": "a", "field": "OVERWRITE"}]},
                          "y": {"inputFields": [
                              {"namespace": NS, "name": "a", "field": "y0"}]},
                          "z": {"inputFields": [
                              {"namespace": NS, "name": "a", "field": "z0"}]}}},
              {"namespace": NS, "name": "a",
               "passthrough_from": {"namespace": NS, "name": "raw"}}]
    out = merge_column_lineage([chunk1, chunk2])
    assert [e["name"] for e in out] == ["a", "b"]  # sorted by (ns, name)
    assert out[0]["passthrough_from"] == {"namespace": NS, "name": "raw"}
    fields = out[1]["fields"]
    # first-seen inputFields never overwritten...
    assert fields["x"]["inputFields"][0]["field"] == "x0"
    # ...but an EMPTY inputFields may be filled, and new fields are added.
    assert fields["y"]["inputFields"][0]["field"] == "y0"
    assert fields["z"]["inputFields"][0]["field"] == "z0"


def test_merge_column_lineage_explicit_displaces_marker():
    chunk1 = [{"namespace": NS, "name": "b",
               "passthrough_from": {"namespace": NS, "name": "raw"}}]
    chunk2 = [{"namespace": NS, "name": "b", "fields": _STG_FIELDS}]
    out = merge_column_lineage([chunk1, chunk2])
    assert len(out) == 1
    assert "passthrough_from" not in out[0]
    assert out[0]["fields"] == _STG_FIELDS


def test_merge_dataset_schemas_fills_missing_description():
    chunk1 = [{"namespace": NS, "name": "a",
               "fields": [{"name": "c1", "description": "first"},
                          {"name": "c2"}]}]
    chunk2 = [{"namespace": NS, "name": "a",
               "fields": [{"name": "c1", "description": "never overwrites"},
                          {"name": "c2", "description": "fills missing"}]}]
    out = merge_dataset_schemas([chunk1, chunk2])
    assert out[0]["fields"] == [
        {"name": "c1", "description": "first"},
        {"name": "c2", "description": "fills missing"},
    ]


def test_merge_dataset_descriptions_first_wins():
    out = merge_dataset_descriptions([
        [{"namespace": NS, "name": "b", "description": "first"}],
        [{"namespace": NS, "name": "b", "description": "second"},
         {"namespace": NS, "name": "a", "description": "other"}],
    ])
    assert out == [{"namespace": NS, "name": "a", "description": "other"},
                   {"namespace": NS, "name": "b", "description": "first"}]
