---
name: intent-map-render
description: Use during evo's DRIFT_SURFACED phase (per design §6 state machine) to render diagrams from a frozen intent-map + wiring snapshot + api_delta. Pure-Python deterministic — no LLM calls, no timestamps in payloads, byte-identical output on re-run. Emits 4 diagram types capped at HARD-RULE 5's "3 per consultation turn" — D1 Mermaid sequence (per-component runtime), D2 Cytoscape-JSON blast-radius subgraph, D3 Mermaid sankey for version delta, D4 markdown coverage heatmap. Function-level rendering rejected with explicit error.
---

# intent-map-render (v1)

Pure-Python diagram renderer for the EVO agent (S032).

**Status:** PRODUCTION (S032 WP-5 ship).
**Design document:** `/path/to/project/docs/plans/2026-05-13-evo-agent-design.md` §4.1 + §8.
**No LLM, no timestamps, no network** — output is byte-identical on re-run.

## Diagram inventory (HARD-RULE 5 cap)

| ID | Diagram | Tech | When | Output |
|---|---|---|---|---|
| D1 | Intent Sequence | Mermaid `sequenceDiagram` | Every run, per component | Mermaid markdown block |
| D2 | Blast-Radius Subgraph | Cytoscape-JSON | On-demand during consultation | JSON for visual-companion HTML |
| D3 | Version Delta Sankey | Mermaid `sankey-beta` | Mode-b when api_delta.breaking_lines non-empty | Mermaid markdown block |
| D4 | Coverage Heat-map | Markdown table | Every run | GFM table |

**Hard cap: 3 diagrams per consultation turn.** Caller passes
`diagram_types_requested` and the skill rejects requests for >3 distinct
diagram types in a single invocation.

## CLI

```bash
python3 ~/.claude/skills/intent-map-render/scripts/run.py \
  --intent-map <path-to-intent-map.yaml> \
  --wiring-snapshot <path-to-snapshot.json> \
  [--api-delta <path-to-api-delta.json>] \
  --emit D1,D4 \
  --output-dir <where-to-write>
```

## Hard rules

1. **No LLM calls.** Anywhere. This skill is deterministic-only by contract.
2. **No timestamps in payloads.** Re-runs produce byte-identical outputs.
3. **Hard cap of 3 diagrams per call.** The `--emit` flag accepts at most
   3 distinct values from `{D1, D2, D3, D4}`.
4. **C4 container + component level only.** Function-level diagrams are
   rejected with `EVO_HARD_RULE_5_VIOLATION` (exit 2). No "render every
   call site" support.
5. **Two-tier progressive disclosure on D1.** When component count > 20,
   D1 collapses lanes into `<details>` blocks (markdown-native, GitHub
   renders the chevron).
6. **Cytoscape vendor offline.** D2 uses `visual-companion/templates/vendor/cytoscape.min.js`
   when available; CDN fallback only if vendor file missing.

## What lives in `scripts/`

- `run.py` — CLI entry + dispatch
- `d1_sequence.py` — Mermaid sequenceDiagram emitter
- `d2_cytoscape.py` — Cytoscape-elements JSON emitter
- `d3_sankey.py` — Mermaid sankey-beta emitter
- `d4_heatmap.py` — Markdown table emitter (intent × test crosswalk)
- `loader.py` — read intent-map.yaml, wiring snapshot, api_delta JSON

## What lives in `references/`

- `diagram-conventions.md` — Mermaid syntax details + truncation rules
- `cytoscape-elements.md` — Element shape contract for D2

## Determinism guarantee

Given the same inputs, every diagram is **byte-identical** between runs.
Tested by `test_d1_byte_identical`, `test_d2_byte_identical`, etc.

## How to invoke

```bash
# Emit D1 + D4 for an evo intent-map (typical mode-a output)
python3 ~/.claude/skills/intent-map-render/scripts/run.py \
    --intent-map .ledger/evo/runs/<run_id>/intent-map.yaml \
    --wiring-snapshot .wiring/latest.json \
    --emit D1,D4 \
    --output-dir /tmp/evo-diagrams/

# Emit D3 Sankey when version-upgrade has api_delta
python3 ~/.claude/skills/intent-map-render/scripts/run.py \
    --intent-map .ledger/evo/runs/<run_id>/intent-map.yaml \
    --wiring-snapshot .wiring/latest.json \
    --api-delta .ledger/evo/runs/<run_id>/api-delta.json \
    --emit D3 \
    --output-dir /tmp/evo-diagrams/
```
