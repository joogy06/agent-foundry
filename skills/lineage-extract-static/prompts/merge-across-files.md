# Merge Across Files

You are combining per-file lineage rollups (from `prompts/merge-chunks-within-file.md` + `scripts/accumulate.py`) into a single project-level aggregate ready for OpenLineage emission. This is the LAST step before identity resolution + redaction + OL emission.

## Your task

1. Concatenate `edges[]` from all per-file rollups into a project-level `edges[]` array.
2. Concatenate `gaps[]`.
3. Compute project-level aggregate counters (`by_confidence`, `by_kind`, `boundary_issues_count`).
4. Surface a per-file index so downstream rendering can attribute edges to their source files.
5. Union `dataset_schemas[]` from all per-file rollups (2026-07-01 schema-facet uplift) — keyed on `(namespace, name)`, field lists unioned by field name preserving source order (a later duplicate may only fill a missing `type` or `description`), output sorted by `(namespace, name)`.
6. Union `column_lineage[]` from all per-file rollups (2026-07-02 column-level uplift) — keyed on the OUTPUT `(namespace, name)`; explicit `fields` entries merge field-map-wise (a later duplicate may only add new output fields or fill empty `inputFields`, never overwrite); a `passthrough_from` marker survives only when no explicit-fields entry exists for the same output; output sorted by `(namespace, name)`.
7. Union `dataset_descriptions[]` (2026-07-02 uplift) — keyed on `(namespace, name)`, first-seen description wins, output sorted by `(namespace, name)`.
8. Emit one JSON object conforming to a project-aggregate shape (NOT lineage-finding.v1 — see the structure below).

## Input you will receive

A list of per-file rollup JSON objects, each conforming to `lineage-finding.v1` at file level:

```json
[
  {"file_path": "etl/load_users.py", "file_sha256": "abc...", "chunk_id": 0, "edges": [...], "gaps": [...], "by_confidence": {...}, "by_kind": {...}, "boundary_issues_count": 0},
  {"file_path": "sql/create_tables.sql", "file_sha256": "def...", "chunk_id": 0, "edges": [...], "gaps": [...], ...},
  ...
]
```

Also: `run_id`, `extractor_version`, `workspace_tree_hash`.

## What you emit (one JSON object only)

```json
{
  "schema_version": "1.0.0",
  "extractor_id": "lineage-extract-static",
  "extractor_version": "<from input>",
  "run_id": "<from input>",
  "workspace_tree_hash": "<from input>",
  "scope": "project_aggregate",
  "files": [
    {"file_path": "etl/load_users.py", "file_sha256": "abc...", "edge_count": <int>, "gap_count": <int>}
  ],
  "edges": [
    /* Each edge from the per-file rollups, with an added "source_file" field
       to attribute the edge to its origin file. */
    {
      "edge_kind": "reads_from",
      "source_dataset": {...},
      "target_job": {...},
      "evidence_line_start": 412,
      "evidence_line_end": 412,
      "evidence_snippet": "...",
      "confidence": "grounded",
      "confidence_reason": "...",
      "source_file": "etl/load_users.py",
      "source_file_sha256": "abc..."
    }
  ],
  "gaps": [
    /* concatenated gaps with source_file attribution */
    {
      "kind": "dynamic_path",
      "line": 124,
      "description": "...",
      "source_file": "etl/load_users.py"
    }
  ],
  "by_confidence": {
    "grounded": <project total>,
    "inferred": <project total>,
    "speculative": <project total>
  },
  "by_kind": {
    "reads_from": <project total>,
    "writes_to": <project total>,
    "schedules": <project total>,
    "depends_on": <project total>
  },
  "boundary_issues_count": <project total>,
  "total_edges": <len(edges)>,
  "total_gaps": <len(gaps)>,
  "dataset_schemas": [
    /* OPTIONAL — project-level union of per-file dataset_schemas entries
       (task step 5). merge_into_ol.py joins each entry to its DatasetEvent on
       (namespace, name) — AFTER identity resolution these must use the SAME
       canonical namespace/name as the edges — and attaches facets.schema. Omit
       the key when no file carried one. */
    {"namespace": "postgres://dwh:5432/analytics", "name": "public.users",
     "fields": [{"name": "id", "type": "bigint"},
                {"name": "email", "description": "Customer email"}]}
  ],
  "column_lineage": [
    /* OPTIONAL — project-level union of per-file column_lineage entries
       (task step 6). merge_into_ol.py attaches each resolved entry as a
       columnLineage 1-2-0 facet on the matching OUTPUT DatasetEvent; the
       passthrough_from marker form expands against the parent's
       dataset_schemas entry. Omit the key when no file carried one. */
    {"namespace": "postgres://dwh:5432/analytics", "name": "public.stg_orders",
     "fields": {"order_id": {"inputFields": [
       {"namespace": "postgres://dwh:5432/analytics",
        "name": "public.raw_orders", "field": "id"}]}}},
    {"namespace": "postgres://dwh:5432/analytics", "name": "public.orders_copy",
     "passthrough_from": {"namespace": "postgres://dwh:5432/analytics",
                          "name": "public.stg_orders"}}
  ],
  "dataset_descriptions": [
    /* OPTIONAL — project-level union of per-file dataset_descriptions entries
       (task step 7). merge_into_ol.py attaches each as a documentation facet
       on the matching DatasetEvent. Omit the key when no file carried one. */
    {"namespace": "postgres://dwh:5432/analytics", "name": "public.users",
     "description": "One row per registered customer."}
  ]
}
```

## Important — do NOT canonicalize datasets here

You are NOT performing the 3-step identity waterfall. That's the job of `prompts/resolve-identity.md`, which runs AFTER this aggregation. Here, you preserve the `source_dataset.namespace` and `name` values exactly as emitted by `analyze-file.md`. The downstream identity resolution will collapse equivalent datasets.

## Important — do NOT deduplicate edges here

Two files might both legitimately reference the same dataset. Preserve both edges; deduplication (if any) happens in the OL emission stage.

## Format requirements

- Emit ONE JSON object only.
- Preserve every edge from every input file.
- Add `source_file` + `source_file_sha256` to every edge for downstream attribution.
- Sort `files[]` by `file_path` (lexicographic) for deterministic output ordering.
- Sort `edges[]` by `(source_file, evidence_line_start, edge_kind, source_dataset.namespace, source_dataset.name)` for deterministic output ordering.

## You will now receive the per-file rollup list. Emit one valid project-aggregate JSON object.
