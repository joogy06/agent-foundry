# wiring-query operations — v1 reference

Two operations. Deterministic. No LLM calls. Snapshot read from `.wiring/latest.json`.

## `impact`

BFS over symbol adjacency in both directions (src and dst), up to `max_depth` hops. Outputs all reachable edges with status in `{live}` (and `stale` if `--include-stale` is passed); excludes `orphan` and `suppressed` always.

### Semantics

- Node identity: `src_symbol` / `dst_symbol` strings (not components).
- Edge identity: `edge_id` (16-hex from `compute_edge_id(src_component, src_symbol, dst_component, dst_symbol, edge_kind)`).
- Cycle detection: visited-set on nodes. Each edge enters the output at most once (dedup by `edge_id`, keeping the shortest hop).
- Deterministic output: edges sorted by `edge_id` ascending.

### Example

```bash
python3 run.py --project-dir ./ impact --symbol auth-service.validateToken --max-depth 2
```

Output (abridged):
```json
{
  "query": "impact",
  "anchor_found": true,
  "edges": [
    {"edge_id": "12ab...", "src_symbol": "auth-service.validateToken",
     "dst_symbol": "user-service.getUser", "edge_kind": "calls",
     "status": "live", "blocking_eligible": true, "hop": 1, ...}
  ],
  "hop_counts": {"1": 3, "2": 2},
  "provenance_breakdown": {"static_extract": 5, "agent_asserted": 0, "manual": 0}
}
```

### Anchor not found

```json
{
  "anchor_found": false,
  "suggestions": ["auth-service.validateToken", "auth-service.lookupSession"],
  "summary_md": "anchor `auth-service.validateTokn` not found ..."
}
```

## `subgraph_for_llm`

Returns a bounded subgraph suitable for dropping into an LLM prompt. Runs `impact` internally for each anchor, unions the results, then truncates to `min(max_edges, max_tokens // 160)`.

### Why 160 tokens/edge

Conservative upper bound based on the compact edge shape (two symbols + kind + status + hop + one evidence summary string). Deterministic, not adaptive to tokenizer quirks. Agents can hash the output; the token estimate is a budget, not a guarantee.

### Truncation

When `total_edges > hard_cap`, the first `hard_cap` edges by sorted `edge_id` are kept; `truncated: true` and `omitted_edge_count` report the rest. No prioritization — deterministic by identity alone.

### Example

```bash
python3 run.py --project-dir ./ subgraph_for_llm \
    --anchors "auth-service.validateToken,POST /api/users" \
    --max-edges 40 --max-tokens 50000 --max-depth 2
```

## Out of scope for v1

- `drift_report` — compares last two snapshots; needs history tracking (v2).
- `coverage_gaps` — lists edges with evidence gap patterns (v2, requires richer snapshot).
- `whole_snapshot_pack` — emits the full snapshot normalized for LLM context (v2; may overlap with `subgraph_for_llm` with a "whole graph" mode).
- `integration_test_inputs` — produces per-flow inputs ready for pytest parametrize (v2).
- `shortest_path` — point-to-point routing (v2).

These are intentionally blocked from v1 to keep the surface narrow per Codex's cap.
