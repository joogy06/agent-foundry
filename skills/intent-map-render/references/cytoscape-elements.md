# Cytoscape Elements Contract

D2 output conforms to the Cytoscape.js elements schema
(https://js.cytoscape.org/#notation/elements-json).

## Element shape

Each element is `{"data": {...}}` (no `position`, no `style` — those live
in the rendering layer's stylesheet at `visual-companion/templates/...`).

### Nodes

```json
{
  "data": {
    "id": "<unique component_id>",
    "label": "<short description>",
    "kind": "node",
    "function_class": "<closed enum value>"
  }
}
```

### Edges

```json
{
  "data": {
    "id": "<unique edge_id>",
    "source": "<id of source node>",
    "target": "<id of target node>",
    "kind": "edge",
    "edge_kind": "calls|imports|inherits|..."
  }
}
```

## Top-level fields

```json
{
  "elements": [...],
  "truncated": false,
  "max_edges": 200,
  "anchor_count": 3,
  "edge_count": 42
}
```

`truncated: true` indicates the edge cap was exceeded and the output is
incomplete. The HTML renderer surfaces this with a banner.

## Vendored cytoscape.js

`visual-companion/templates/vendor/cytoscape.min.js` is loaded via
relative `<script src="vendor/cytoscape.min.js">`. CDN fallback added
inline if the vendor file is missing (warns in the console).
