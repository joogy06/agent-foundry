# wiring-query operations — v1.1 reference

Four operations — `impact` + `subgraph_for_llm` (v1) and `intent_of` + `flow_intent` (v1.1, S032 WP-4). Deterministic. No LLM calls. Snapshot read from `.wiring/latest.json`.

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

## `intent_of` (v1.1)

Returns the per-component `intent` block from a v1.1 snapshot (merged in by `wiring-reconcile@1.1` `intent_merge.py` from `intent-extract` output). Pure dictionary lookup — no graph traversal.

### Args

- `--component <id>` (required) — component id as named in the snapshot's `components[]` (i.e., contract-map component id).

### Output shape

```json
{
  "component_id": "auth-service",
  "found": true,
  "intent_present": true,
  "intent": {
    "function_class": "orchestration",
    "one_line": "Validates tokens and brokers session lookups",
    "confidence_level": "interpretive",
    "cache_key": "<content-hash>",
    "intent_path": "/path/to/.wiring/runs/<run_id>/intent/auth-service.yaml",
    "test_seed_count": 3,
    "error_path_count": 2,
    "evidence_edge_count": 9,
    "extract_run_id": "<run_id>"
  },
  "edge_counts": {"inbound": 4, "outbound": 7}
}
```

### Missing cases (never raise, exit code stays 0)

- Component not in snapshot → `found: false`, `intent_present: false`, `intent: null`, zero edge counts.
- Component present but no intent block (v1.0 snapshot, or `intent-extract` skipped it) → `found: true`, `intent_present: false`, `intent: null`.

### Who calls it

- **evo** (DRIFT_SURFACED phase) — feeds `intent-map-render` D1 sequence and D4 coverage-heatmap diagrams; also a cheap pre-check for whether INTENT_MAPPED already covered a component (via `cache_key`) before re-extracting.
- **bob** — cheap component-intent context when scoping a WP that touches a mapped component, without paying for a full `subgraph_for_llm` slice.

### Example

```bash
python3 run.py --project-dir ./ intent_of --component auth-service
```

## `flow_intent` (v1.1)

Aggregates intent across every component on a named contract-map flow. Reads `flows[]` from `progress/contract-map.yaml` under `--project-dir` (matches `flows[].id == flow_id`, walks `flows[].path`), then looks each path component up in the snapshot.

### Args

- `--flow-id <id>` (required) — flow id as declared in `progress/contract-map.yaml` `flows[]`.

### Output shape

```json
{
  "flow_id": "user-signup",
  "flow_found": true,
  "components": [
    {"component_id": "gateway", "intent_present": true, "intent": {"...": "..."}},
    {"component_id": "auth-service", "intent_present": false, "intent": null}
  ],
  "summary": {
    "components_total": 2,
    "components_with_intent": 1,
    "function_class_distribution": {"orchestration": 1}
  }
}
```

Components on the path but absent from the snapshot appear with `intent_present: false`, `intent: null` (they still count in `components_total`). `function_class_distribution` buckets each present intent's `function_class` (`"unknown"` when the block lacks one).

### Missing cases (never raise, exit code stays 0)

- contract-map missing/malformed, or flow id unknown → `flow_found: false`, empty `components`, zeroed summary.
- v1.0 snapshot (no intent anywhere) → `flow_found: true` with `components_with_intent: 0`.

### Who calls it

- **evo** (DRIFT_SURFACED phase) — flow-level intent coverage for `intent-map-render` (which flows are fully mapped vs. have intent gaps) and for drift-report narrative.
- **bob** — when planning flow-level integration tests (companion to `integration-flow-testing@1.1`), `flow_intent` shows which legs of a declared flow have verified intent (and test seeds) before generating flow tests.

### Example

```bash
python3 run.py --project-dir ./ flow_intent --flow-id user-signup
```

## Out of scope for v1/v1.1

- `drift_report` — compares last two snapshots; needs history tracking (v2).
- `coverage_gaps` — lists edges with evidence gap patterns (v2, requires richer snapshot).
- `whole_snapshot_pack` — emits the full snapshot normalized for LLM context (v2; may overlap with `subgraph_for_llm` with a "whole graph" mode).
- `integration_test_inputs` — produces per-flow inputs ready for pytest parametrize (v2).
- `shortest_path` — point-to-point routing (v2).

These are intentionally blocked from v1/v1.1 to keep the surface narrow per Codex's cap. The only v1.1 additions are the two intent ops above (S032 design §4.4 / WP-4).
