# Merge Chunks Within File

You are merging multiple per-chunk lineage findings into one per-file rollup. Chunks were emitted in order by `scripts/chunk_file.py` and analysed individually using `prompts/analyze-file.md`. Your task is to:

1. Concatenate all `edges[]` arrays into a single file-level `edges[]` array.
2. Identify and pair adjacent partial-boundary edges (where chunk N ended with `partial_end` and chunk N+1 begins with `partial_start` referring to the same statement).
3. Concatenate all `gaps[]` arrays.
4. Surface file-level aggregate counters (by_confidence, by_kind, boundary_issues_count).

## Important — boundary pairing is NOT your judgment call

The boundary-matching predicate runs **deterministically** in `scripts/accumulate.py`:

```
pair two partials iff ALL of:
  same(edge.edge_kind)
  same(edge.source_dataset.namespace, edge.source_dataset.name)
  same(edge.target_job.namespace, edge.target_job.name)
  chunk_N+1.start_line - chunk_N.end_line <= LINEAGE_OVERLAP_LINES (default 50)
```

If two candidate pairs exist for the same `partial_end`, the deterministic helper takes the smaller line-distance. If still tied, BOTH edges are downgraded to `speculative` + `boundary_issue: true`.

**You do NOT pair partials.** You produce the input to `accumulate.py` — a single file-level array of all chunk-level edges with the original `boundary_status` markers preserved. The script's deterministic pairing is what guarantees byte-identical output on re-run.

## Input you will receive

A list of per-chunk JSON objects, each conforming to `lineage-finding.v1` with chunk-level granularity:

```json
[
  {"chunk_id": 1, "start_line": 1, "end_line": 2000, "boundary_status": "partial_end", "edges": [...], "gaps": [...]},
  {"chunk_id": 2, "start_line": 1951, "end_line": 3950, "boundary_status": "partial_both", "edges": [...], "gaps": [...]},
  {"chunk_id": 3, "start_line": 3901, "end_line": 5000, "boundary_status": "partial_start", "edges": [...], "gaps": [...]},
  ...
]
```

Also: `file_path`, `file_sha256`, `extractor_version`.

## What you emit (one JSON object only)

```json
{
  "schema_version": "1.0.0",
  "extractor_id": "lineage-extract-static",
  "extractor_version": "<from input>",
  "file_path": "<from input>",
  "file_sha256": "<from input>",
  "chunk_id": 0,
  "start_line": 1,
  "end_line": <last chunk end_line>,
  "start_byte": 0,
  "end_byte": <last chunk end_byte>,
  "boundary_status": "complete",
  "edges": [
    /* concatenated edges from all chunks; pass through original boundary_issue / confidence values
       — DO NOT pair partials; DO NOT modify confidence here. accumulate.py handles that deterministically. */
  ],
  "gaps": [
    /* concatenated gaps from all chunks */
  ],
  "by_confidence": {
    "grounded": <count>,
    "inferred": <count>,
    "speculative": <count>
  },
  "by_kind": {
    "reads_from": <count>,
    "writes_to": <count>,
    "schedules": <count>,
    "depends_on": <count>
  },
  "boundary_issues_count": <count of edges with boundary_issue: true (initially 0 at this stage)>,
  "dataset_schemas": [
    /* OPTIONAL — union of chunk-level dataset_schemas entries keyed on
       (namespace, name); field lists union by field name preserving source
       order (a later duplicate may only fill a missing "type"). Omit the key
       when no chunk carried one. accumulate.py applies the same deterministic
       union (merge_dataset_schemas). */
  ]
}
```

Key points:
- `chunk_id: 0` is the convention for file-level rollups (chunks are 1-indexed).
- `boundary_status` at the file level is ALWAYS `complete` (the chunks have boundaries within the file; the file as a whole has complete boundaries).
- The `boundary_issues_count` is initially `0` because YOU don't compute pairings. `accumulate.py` populates this after running the deterministic predicate.

## Format requirements

- Emit ONE JSON object only.
- Preserve every chunk-level `boundary_status` marker by keeping the chunk-level objects as inputs to `accumulate.py`. Your output is the simple concatenation + counters.
- Do not modify `confidence` values; chunks classified by `analyze-file.md` are authoritative.
- Do not modify `evidence_snippet` content; `redact.py` runs after this step.

## You will now receive the per-chunk JSON list. Emit one valid file-level JSON object.
