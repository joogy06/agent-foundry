"""SchemaDatasetFacet emission (2026-07-01 schema-facet uplift).

Asserts the producer side of the DLP OL-import rendering fix: a rollup carrying
``dataset_schemas`` yields DatasetEvents with ``facets.schema.fields`` (named-in-
source columns only, ``type`` only when stated), fail-open attachment, and
byte-identical re-emission. Runs against the real merge_into_ol + validate_ol
with the vendored OL 2.0.2 schema.
"""
from __future__ import annotations

import json
from pathlib import Path

from accumulate import merge_dataset_schemas
from merge_into_ol import merge_into_ol


def _edge(edge_kind, ds_name):
    return {
        "edge_kind": edge_kind,
        "source_dataset": {
            "namespace": "postgres://dwh:5432/analytics",
            "name": ds_name,
            "kind": "table",
        },
        "target_job": {
            "namespace": "repo://etl",
            "name": "load.py:main",
            "kind": "script",
        },
        "evidence_line_start": 3,
        "evidence_line_end": 3,
        "evidence_snippet": "SELECT ...",
        "confidence": "grounded",
        "confidence_reason": "literal table name",
        "source_file": "load.py",
    }


def _rollup(dataset_schemas=None):
    rollup = {
        "schema_version": "1.0.0",
        "extractor_id": "lineage-extract-static",
        "scope": "project_aggregate",
        "edges": [_edge("reads_from", "public.users"),
                  _edge("writes_to", "public.user_stats")],
        "gaps": [],
    }
    if dataset_schemas is not None:
        rollup["dataset_schemas"] = dataset_schemas
    return rollup


def _emit(tmp_path, rollup):
    summary = merge_into_ol(
        rollup,
        run_id="r1",
        workspace_tree_hash="tree1",
        scan_started_at="2026-07-01T09:00:00Z",
        output_dir=tmp_path,
    )
    events = [json.loads(line) for line in
              (tmp_path / "openlineage.ndjson").read_text().splitlines() if line]
    return summary, events


def _dataset_events(events):
    return {e["dataset"]["name"]: e for e in events
            if e["eventType"] == "DATASET_EVENT"}


def test_dataset_schemas_attach_schema_facets(tmp_path):
    schemas = [{
        "namespace": "postgres://dwh:5432/analytics",
        "name": "public.users",
        "fields": [{"name": "id", "type": "bigint"}, {"name": "email"}],
    }]
    summary, events = _emit(tmp_path, _rollup(schemas))
    ds = _dataset_events(events)
    facet = ds["public.users"]["dataset"]["facets"]["schema"]
    # named-in-source only; type ONLY when stated (never "unknown"-padded).
    assert facet["fields"] == [{"name": "id", "type": "bigint"}, {"name": "email"}]
    assert facet["_schemaURL"].endswith("SchemaDatasetFacet.json")
    # the dataset WITHOUT a dataset_schemas entry stays facet-less.
    assert "schema" not in ds["public.user_stats"]["dataset"]["facets"]
    assert summary["schema_facets_attached"] == 1
    assert summary["schema_facet_gaps"] == []


def test_no_dataset_schemas_emits_no_schema_facets(tmp_path):
    summary, events = _emit(tmp_path, _rollup())
    for e in _dataset_events(events).values():
        assert "schema" not in e["dataset"]["facets"]
    assert summary["schema_facets_attached"] == 0


def test_empty_fields_entry_is_skipped(tmp_path):
    schemas = [{"namespace": "postgres://dwh:5432/analytics",
                "name": "public.users", "fields": []}]
    summary, events = _emit(tmp_path, _rollup(schemas))
    assert "schema" not in _dataset_events(events)["public.users"]["dataset"]["facets"]
    assert summary["schema_facets_attached"] == 0


def test_schema_facet_reemission_is_byte_identical(tmp_path):
    schemas = [{
        "namespace": "postgres://dwh:5432/analytics",
        "name": "public.users",
        "fields": [{"name": "id", "type": "bigint"}, {"name": "email"}],
    }]
    d1, d2 = tmp_path / "a", tmp_path / "b"
    _emit(d1.mkdir() or d1, _rollup(schemas))
    _emit(d2.mkdir() or d2, _rollup(schemas))
    assert (d1 / "openlineage.ndjson").read_bytes() == \
        (d2 / "openlineage.ndjson").read_bytes()


def test_merge_dataset_schemas_union_is_deterministic():
    chunk1 = [{"namespace": "n", "name": "b", "fields": [{"name": "x"}]},
              {"namespace": "n", "name": "a",
               "fields": [{"name": "c1"}, {"name": "c2", "type": "int"}]}]
    chunk2 = [{"namespace": "n", "name": "a",
               "fields": [{"name": "c1", "type": "text"},   # fills missing type
                          {"name": "c2", "type": "bigint"},  # never overwrites
                          {"name": "c3"}]}]
    out = merge_dataset_schemas([chunk1, chunk2])
    assert [e["name"] for e in out] == ["a", "b"]           # sorted by (ns, name)
    assert out[0]["fields"] == [
        {"name": "c1", "type": "text"},
        {"name": "c2", "type": "int"},
        {"name": "c3"},
    ]
