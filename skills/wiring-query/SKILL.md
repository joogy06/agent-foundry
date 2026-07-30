---
name: wiring-query
description: Thin deterministic Python skill that reads `.wiring/latest.json` and returns narrow slices for agent consumption. Four operations — `impact(symbol)` and `subgraph_for_llm(anchors)` (v1), plus `intent_of(component)` and `flow_intent(flow_id)` (v1.1, S032). No LLM calls anywhere. Snapshot is cached in-process for subsequent calls within a single subprocess. Deterministic BFS with cycle detection; anchor fuzzy-match suggestions when not found; token/edge-budget truncation. Invoked by bob, by evo (DRIFT_SURFACED phase), by integration-flow-testing@1.1, or directly from CLI.
family: wiring
---

# wiring-query (v1.1 thin)

**Design references:**
- `/path/to/project/docs/plans/2026-04-14-wiring-skills-design.md` §5.3 (v1 ops)
- `/path/to/project/docs/plans/2026-05-13-evo-agent-design.md` §4.4 + WP-4 (v1.1 intent ops)

## Purpose

Answer four narrow, deterministic questions over the signed wiring snapshot:

1. `impact(symbol, max_depth, include_stale)` — which edges are reachable within N hops of a symbol (caller or callee direction)?
2. `subgraph_for_llm(anchors, max_edges, max_tokens, max_depth)` — a token-bounded slice of the graph anchored on one or more symbols, safe to drop into an agent prompt.
3. `intent_of(component)` — **v1.1** — the per-component `intent` block (function_class, one_line, confidence_level, counts) merged into the snapshot by `wiring-reconcile@1.1` from `intent-extract` output.
4. `flow_intent(flow_id)` — **v1.1** — aggregated intent for every component along a named flow from `progress/contract-map.yaml`, plus a function-class distribution summary.

## CLI

```bash
# impact
python3 ~/.claude/skills/wiring-query/scripts/run.py \
    --project-dir $PROJECT_DIR impact \
    --symbol "auth-service.validateToken" \
    --max-depth 3

# subgraph_for_llm
python3 ~/.claude/skills/wiring-query/scripts/run.py \
    --project-dir $PROJECT_DIR subgraph_for_llm \
    --anchors "auth-service.validateToken,audit-log.append" \
    --max-edges 40 --max-tokens 50000 --max-depth 2

# intent_of (v1.1)
python3 ~/.claude/skills/wiring-query/scripts/run.py \
    --project-dir $PROJECT_DIR intent_of \
    --component auth-service

# flow_intent (v1.1)
python3 ~/.claude/skills/wiring-query/scripts/run.py \
    --project-dir $PROJECT_DIR flow_intent \
    --flow-id user-signup
```

Outputs are emitted as canonical JSON (sorted keys, compact separators) on stdout, suitable for hashing or piping to another agent.

## Programmatic use

```python
from wiring_query.scripts.loader import load_snapshot
from wiring_query.scripts.graph_ops import build_symbol_index, impact, subgraph_for_llm
from wiring_query.scripts.intent_ops import intent_of, flow_intent

snap = load_snapshot(project_dir)
idx = build_symbol_index(snap)
result = impact(snap, "auth-service.validateToken", max_depth=3, index=idx)
intent = intent_of(snap, "auth-service")
flow = flow_intent(snap, "user-signup", project_dir)
```

Used this way by `integration-flow-testing@1.1` to annotate flow tests with evidence provenance, and by evo's `intent-map-render` pipeline at the DRIFT_SURFACED phase (D1/D4 diagrams consume `intent_of` / `flow_intent` output).

## Exit codes

- `0` — success
- `1` — `.wiring/latest.json` missing or malformed
- `2` — invalid CLI arguments

## Output contracts

### `impact`

```json
{
  "query": "impact",
  "args": {"symbol": "...", "max_depth": 3, "include_stale": false},
  "snapshot_generation": 42,
  "anchor": "...",
  "anchor_found": true,
  "edges": [
    {"edge_id": "...", "src_component": "...", "src_symbol": "...",
     "dst_component": "...", "dst_symbol": "...", "edge_kind": "calls",
     "status": "live", "blocking_eligible": true, "hop": 1,
     "evidence_summary": ["static_extract:fastapi@1.0.0"]}
  ],
  "components_touched": ["auth-service", "db"],
  "hop_counts": {"1": 3, "2": 2},
  "provenance_breakdown": {"static_extract": 5, "agent_asserted": 0, "manual": 0},
  "truncated": false,
  "summary_md": "..."
}
```

When `anchor_found: false`, the response includes `suggestions` (top-3 fuzzy matches via difflib) and a summary message.

### `subgraph_for_llm`

Same edge shape as `impact`; additional fields:
- `anchors_found: {anchor: bool}` — per-anchor found flags
- `suggestions: {anchor: [fuzzy_matches]}` — per-anchor suggestions when missing
- `estimated_tokens: int` — conservative upper bound (160 tokens/edge)
- `omitted_edge_count: int` — when truncated

Truncation fires at `min(max_edges, max_tokens // 160)`.

### `intent_of` (v1.1)

```json
{
  "component_id": "auth-service",
  "found": true,
  "intent_present": true,
  "intent": {"function_class": "...", "one_line": "...",
             "confidence_level": "interpretive", "cache_key": "...",
             "intent_path": "...", "test_seed_count": 3,
             "error_path_count": 2, "evidence_edge_count": 9,
             "extract_run_id": "..."},
  "edge_counts": {"inbound": 4, "outbound": 7}
}
```

`found: false` → component not in the snapshot. `intent_present: false` → component exists but no intent block was merged (v1.0 snapshot, or `intent-extract` not run for it). Never raises on v1.0 snapshots.

### `flow_intent` (v1.1)

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

The flow path is read from `progress/contract-map.yaml` `flows[].path` (matching `flows[].id == flow_id`). Missing contract-map or unknown flow id → `flow_found: false` with an empty components list (exit code stays 0).

## Performance budgets (enforced by tests)

- First-read snapshot load: <300 ms.
- BFS depth-3 on 10k edges: <50 ms.
- Determinism: same snapshot + same args produce bit-identical stdout (edges sorted by `edge_id`).

## Hard rules (do not violate)

- No LLM subprocess invocations. The skill is pure Python.
- Exactly four operations — `impact` + `subgraph_for_llm` (v1) and `intent_of` + `flow_intent` (v1.1). `drift_report`, `coverage_gaps`, `whole_snapshot_pack`, `integration_test_inputs`, `shortest_path` remain v2.
- `latest.json` missing -> exit 1 with a message pointing to `wiring-reconcile`.
- Stale-status edges are excluded by default. `--include-stale` opts in.
- `orphan` and `suppressed` edges are never emitted regardless of `--include-stale`.
- Anchor not found -> `anchor_found: false` + fuzzy suggestions (top-3). Do NOT fail the CLI. Same spirit for v1.1: unknown component/flow -> structured-missing response, never an exception.
- Output is canonical JSON (sort_keys, compact separators) for hashing.

## Files

```
wiring-query/
├── SKILL.md                        (this file)
├── scripts/
│   ├── run.py                      CLI dispatch (4 subparsers)
│   ├── loader.py                   snapshot load + in-process cache
│   ├── graph_ops.py                build_symbol_index, impact, subgraph_for_llm
│   └── intent_ops.py               intent_of, flow_intent (v1.1, S032 WP-4)
├── references/
│   └── operations.md               op-level detail + examples
├── fixtures/
│   └── make_fixture_snapshot.py    deterministic fixture builder
└── tests/
    ├── test_loader.py              6 tests
    ├── test_impact.py              6 tests
    ├── test_subgraph.py            7 tests
    └── test_intent_ops.py          v1.1 intent ops
```

## Drift canary

`ALDEBARAN-7` — load-bearing across the pipeline: any rearrangement of canonical JSON serialization breaks HMAC signatures downstream. wiring-query itself does not sign anything, but its determinism contract shares the same canonical_json convention.
