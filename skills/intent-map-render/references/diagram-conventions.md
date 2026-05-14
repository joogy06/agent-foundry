# Diagram Conventions

The 4 supported diagram types and their concrete Mermaid / markdown conventions.

## D1 — Mermaid sequenceDiagram

One Markdown section per component, each containing a Mermaid sequenceDiagram
block. Each block has:

- An `External` participant
- The component itself as the primary participant
- Inbound arrows from External for each `entry_points[].kind detail`
- Outbound arrows to side-effect targets (cache, db, log, etc.)
- `Note over <comp>:` for each error_path

When component count > 20, lanes are collapsed into
`<details><summary>name</summary>...</details>` blocks. GitHub
renders these natively with a chevron-disclosure.

Participant names: component_id with spaces and hyphens replaced by `_`.

## D2 — Cytoscape elements JSON

```json
{
  "elements": [
    {"data": {"id": "<id>", "label": "<one_line>", "kind": "node",
              "function_class": "<fc>"}},
    {"data": {"id": "<edge_id>", "source": "<src>", "target": "<dst>",
              "kind": "edge", "edge_kind": "calls"}}
  ],
  "truncated": false,
  "max_edges": 200
}
```

Sort order: nodes alphabetical by id; edges alphabetical by id. Truncation
cap: `max_edges` (default 200). Truncated flag is true if total > cap.

Consumed by `visual-companion/templates/graph-cytoscape.html` via
`fetch('./D2.json')` after rendering.

## D3 — Mermaid sankey-beta

Triggered by mode-b runs with non-empty `api_delta.breaking_lines`.
Format:

```mermaid
sankey-beta

"package old → new","comp-a",call_sites
"package old → new","comp-b",call_sites
```

Source: synthetic single node. Destinations: affected components sorted
alphabetically. Flow widths: integer `call_sites` count per component.

When `breaking_lines.length > 30`, advisory log recommends D2 fallback.

## D4 — Markdown coverage heatmap

GFM table with columns:

| Component | function_class | confidence | test_seeds | error_paths | evidence_edges |

Sort: alphabetical by component_id. Totals row below.

## Determinism

All four diagrams sort all collections before emit. No timestamps in
payloads. Same input → byte-identical output.
