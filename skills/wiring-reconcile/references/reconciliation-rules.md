# Reconciliation Rules (v1)

Reference for `wiring-reconcile/scripts/reconciler.py` (pending implementation, WP-5).

## Edge grouping

Group input edges (from `static.jsonl` + all `asserted/<agent>.jsonl`) by `edge_id` (the 16-hex-char five-tuple hash from `edge_identity.py`). For each group:

1. Build `evidence[]` from all occurrences — preserve `evidence_source`, `extractor_id`, `extractor_version`, `last_seen_at`, `workspace_tree_hash`, optional `confidence`.
2. Determine `status`:
   - `live` — any `evidence[i].workspace_tree_hash == current_run_tree_hash`
   - `orphan` — `src_component` or `dst_component` no longer resolves to a component (via contract-map `source_paths` globs against current source tree)
   - `stale` — all evidence entries have `workspace_tree_hash` older than current tree (requires reading previous `latest.json` read-only)
   - `suppressed` — matches a suppress pattern in `.ledger/config.yaml:suppress[]`
3. Determine `blocking_eligible`:
   - TRUE iff >=1 `evidence[i].evidence_source == "static_extract"` AND `source_statuses.static.status in {succeeded, partial}`
   - FALSE otherwise (agent-only edges, runtime-only edges (v2+), failed-source edges)

## Determinism

- Sort `edges[]` by `edge_id` ascending.
- Canonical JSON: `json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)`.
- `snapshot_id = first 16 hex chars of sha256(canonical_json(edges_sorted))`.
- Timestamps (`generated_at`, `last_seen_at` for the *current run*) are the only non-deterministic fields; the determinism test stubs them.

## Failure handling

- Malformed line in jsonl: skip + write to stderr with `SKIP_MALFORMED: <run_id>/<file>:<lineno>`. Do not fail overall.
- Missing required field on an edge: reject + count in `statistics.rejected_edges`.
- Previous snapshot unreadable: treat as first run (no staleness comparison).
- Mid-write SIGKILL: atomic tmp+rename ensures `.wiring/runs/<run_id>/snapshot.json` is either absent (retry) or fully-formed (success).

## Source-status propagation

Reconcile reads `manifest.json` `sources[].status` per run and aggregates into `snapshot.source_statuses`:

```json
{
  "static": {"status": "succeeded|failed|partial|skipped", "edge_count": N, "last_seen_at": "..."},
  "agent_asserted": {"status": "...", "edge_count": N, "last_seen_at": "..."}
}
```

`blocking_eligible` reads `source_statuses.static.status` (NOT individual evidence) — this is the key "is static corroboration available" signal for G4 R1.

## Agent-asserted edges

Each agent writes its own file at `.wiring/runs/<run_id>/asserted/<agent_id>.jsonl`. Reconcile is sole reader of the asserted directory. If two agents assert the same `edge_id`, the snapshot's `evidence[]` has two entries — one per agent. The edge is still `blocking_eligible=false` unless a static source also covers it.

## What reconcile NEVER does

- Never writes `.wiring/latest.json` (bob-only, atomic promote under flock).
- Never writes to `.ledger/claims/` (bob-only).
- Never invokes an LLM.
- Never auto-traverses beyond the input JSONL files (no speculative edge creation).
- Never modifies input files.
