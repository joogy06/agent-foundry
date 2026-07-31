"""d2_cytoscape.py — Cytoscape-elements JSON emitter for D2 blast-radius subgraph.

Reads wiring snapshot.edges + intent-map.components → produces a
Cytoscape-compatible elements JSON describing the blast radius around a
set of anchor components.

Output shape:
  {
    "elements": [
      {"data": {"id": "<comp_id>", "label": "<one_line>", "kind": "node",
                "function_class": "<fc>"}},
      ...
      {"data": {"id": "<edge_id>", "source": "<src>", "target": "<dst>",
                "kind": "edge", "edge_kind": "calls"}},
      ...
    ],
    "truncated": <bool>,
    "max_edges": <int>
  }

Truncation: edges > max_edges (default 200) trips truncated:true; the first
max_edges are kept. Deterministic — sort by edge id before truncation.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Set

DEFAULT_MAX_EDGES = 200


def _component_label(intent_components: List[Dict[str, Any]], cid: str) -> Dict[str, Any]:
    """Lookup intent block by component_id; return {label, function_class}."""
    for c in intent_components:
        if c.get("component_id") == cid or c.get("name") == cid:
            intent = c.get("intent") if isinstance(c.get("intent"), dict) else None
            if intent:
                return {
                    "label": intent.get("one_line", cid),
                    "function_class": intent.get("function_class", "unknown"),
                }
            # functional-intent.v1 doc — intent is nested
            fc = c.get("function_class")
            i = c.get("intent")
            label = i.get("one_line") if isinstance(i, dict) else cid
            return {"label": label or cid, "function_class": fc or "unknown"}
    return {"label": cid, "function_class": "unknown"}


def render(
    intent_map: Dict[str, Any],
    wiring_snapshot: Dict[str, Any],
    *,
    anchors: Optional[Iterable[str]] = None,
    max_edges: int = DEFAULT_MAX_EDGES,
) -> Dict[str, Any]:
    """Render D2 Cytoscape JSON.

    Args:
        intent_map: dict with 'components' list
        wiring_snapshot: snapshot dict with 'edges' list
        anchors: optional component-id filter; if None, all components are anchors
        max_edges: cap on edges in output

    Returns:
        dict with 'elements', 'truncated', 'max_edges' keys
    """
    intent_components = intent_map.get("components", []) or []
    all_edges = wiring_snapshot.get("edges", []) or []

    # Determine which components participate
    anchor_set: Set[str] = set(anchors) if anchors else set()
    if not anchor_set:
        anchor_set = {
            c.get("component_id") or c.get("name") for c in intent_components
        }
        anchor_set.discard(None)

    # Edges that touch any anchor
    relevant_edges = []
    for e in all_edges:
        if e.get("src_component") in anchor_set or e.get("dst_component") in anchor_set:
            relevant_edges.append(e)

    # Sort deterministically and cap
    relevant_edges.sort(key=lambda e: e.get("edge_id", ""))
    truncated = len(relevant_edges) > max_edges
    relevant_edges = relevant_edges[:max_edges]

    # Build node set from the kept edges + anchors
    node_ids: Set[str] = set(anchor_set)
    for e in relevant_edges:
        node_ids.add(e.get("src_component", ""))
        node_ids.add(e.get("dst_component", ""))
    node_ids.discard("")

    elements: List[Dict[str, Any]] = []
    for nid in sorted(node_ids):
        label = _component_label(intent_components, nid)
        elements.append({
            "data": {
                "id": nid,
                "label": label["label"],
                "kind": "node",
                "function_class": label["function_class"],
            }
        })
    for e in relevant_edges:
        elements.append({
            "data": {
                "id": e.get("edge_id", ""),
                "source": e.get("src_component", ""),
                "target": e.get("dst_component", ""),
                "kind": "edge",
                "edge_kind": e.get("edge_kind", "calls"),
            }
        })

    return {
        "elements": elements,
        "truncated": truncated,
        "max_edges": max_edges,
        "anchor_count": len(anchor_set),
        "edge_count": len(relevant_edges),
    }


def render_string(intent_map: Dict[str, Any], wiring_snapshot: Dict[str, Any],
                  **kwargs) -> str:
    """Convenience: render + dump canonical JSON for byte-identical output."""
    payload = render(intent_map, wiring_snapshot, **kwargs)
    return json.dumps(payload, sort_keys=True, indent=2)
