# Merge Across Files

You are combining per-file lineage rollups (from `prompts/merge-chunks-within-file.md` + `scripts/accumulate.py`) into a single project-level aggregate ready for OpenLineage emission. This is the LAST step before identity resolution + redaction + OL emission.

## Your task

1. Concatenate `edges[]` from all per-file rollups into a project-level `edges[]` array.
2. Concatenate `gaps[]`.
3. Compute project-level aggregate counters (`by_confidence`, `by_kind`, `boundary_issues_count`).
4. Surface a per-file index so downstream rendering can attribute edges to their source files.
5. Emit one JSON object conforming to a project-aggregate shape (NOT lineage-finding.v1 — see the structure below).

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
  "total_gaps": <len(gaps)>
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
