---
name: wiring-query
description: Thin deterministic Python skill that reads `.wiring/latest.json` and returns narrow slices for agent consumption. Two v1 operations only — `impact(symbol)` and `subgraph_for_llm(anchors)`. No LLM calls anywhere. Snapshot is cached in-process for subsequent calls within a single subprocess. Deterministic BFS with cycle detection; anchor fuzzy-match suggestions when not found; token/edge-budget truncation. Invoked by bob, by integration-flow-testing@1.1, or directly from CLI.
---

# wiring-query (v1 thin)

**Design reference:** `/path/to/project/docs/plans/2026-04-14-wiring-skills-design.md` §5.3

## Purpose

Answer two narrow, deterministic questions over the signed wiring snapshot:

1. `impact(symbol, max_depth, include_stale)` — which edges are reachable within N hops of a symbol (caller or callee direction)?
2. `subgraph_for_llm(anchors, max_edges, max_tokens, max_depth)` — a token-bounded slice of the graph anchored on one or more symbols, safe to drop into an agent prompt.

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
```

Outputs are emitted as canonical JSON (sorted keys, compact separators) on stdout, suitable for hashing or piping to another agent.

## Programmatic use

```python
from wiring_query.scripts.loader import load_snapshot
from wiring_query.scripts.graph_ops import build_symbol_index, impact, subgraph_for_llm

snap = load_snapshot(project_dir)
idx = build_symbol_index(snap)
result = impact(snap, "auth-service.validateToken", max_depth=3, index=idx)
```

Used this way by `integration-flow-testing@1.1` to annotate flow tests with evidence provenance.

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

## Performance budgets (enforced by tests)

- First-read snapshot load: <300 ms.
- BFS depth-3 on 10k edges: <50 ms.
- Determinism: same snapshot + same args produce bit-identical stdout (edges sorted by `edge_id`).

## Hard rules (do not violate)

- No LLM subprocess invocations. The skill is pure Python.
- Exactly two operations in v1. `drift_report`, `coverage_gaps`, `whole_snapshot_pack`, `integration_test_inputs`, `shortest_path` are v2.
- `latest.json` missing -> exit 1 with a message pointing to `wiring-reconcile`.
- Stale-status edges are excluded by default. `--include-stale` opts in.
- `orphan` and `suppressed` edges are never emitted regardless of `--include-stale`.
- Anchor not found -> `anchor_found: false` + fuzzy suggestions (top-3). Do NOT fail the CLI.
- Output is canonical JSON (sort_keys, compact separators) for hashing.

## Files

```
wiring-query/
├── SKILL.md                        (this file)
├── scripts/
│   ├── run.py                      CLI dispatch
│   ├── loader.py                   snapshot load + in-process cache
│   └── graph_ops.py                build_symbol_index, impact, subgraph_for_llm
├── references/
│   └── operations.md               op-level detail + examples
├── fixtures/
│   └── make_fixture_snapshot.py    deterministic fixture builder
└── tests/
    ├── test_loader.py              6 tests
    ├── test_impact.py              6 tests
    └── test_subgraph.py            7 tests
```

## Drift canary

`ALDEBARAN-7` — load-bearing across the pipeline: any rearrangement of canonical JSON serialization breaks HMAC signatures downstream. wiring-query itself does not sign anything, but its determinism contract shares the same canonical_json convention.
