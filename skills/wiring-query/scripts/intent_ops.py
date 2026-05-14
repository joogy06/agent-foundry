"""intent_ops.py — wiring-query v1.1 ops (S032 WP-4).

Two new operations consume the snapshot.v1.1 per-component intent block
(populated by intent-extract via wiring-reconcile@1.1):

  - intent_of(component) → returns the intent block + counts + cache_key
  - flow_intent(flow_id)  → returns aggregated intent for every component
                            in the named flow (read from contract-map)

Both ops are pure-Python, deterministic, no LLM calls. Loaded snapshot is
already cached by run.py — these ops piggyback on the same in-process cache.

Backward-compatible with v1.0 snapshots: if no intent blocks exist, ops
return empty / structured-missing responses, never raise.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


def _components(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Safe accessor for snapshot.components."""
    comps = snapshot.get("components", [])
    if not isinstance(comps, list):
        return []
    return [c for c in comps if isinstance(c, dict)]


def _component_by_name(
    snapshot: Dict[str, Any], component_id: str
) -> Optional[Dict[str, Any]]:
    for c in _components(snapshot):
        if c.get("name") == component_id:
            return c
    return None


def intent_of(snapshot: Dict[str, Any], component_id: str) -> Dict[str, Any]:
    """Return the intent block for one component.

    Output shape:
      {
        "component_id": str,
        "found": bool,
        "intent_present": bool,
        "intent": {function_class, one_line, ...} or null,
        "edge_counts": {inbound, outbound}
      }
    """
    comp = _component_by_name(snapshot, component_id)
    if comp is None:
        return {
            "component_id": component_id,
            "found": False,
            "intent_present": False,
            "intent": None,
            "edge_counts": {"inbound": 0, "outbound": 0},
        }

    intent_block = comp.get("intent")
    intent_present = isinstance(intent_block, dict)

    return {
        "component_id": component_id,
        "found": True,
        "intent_present": intent_present,
        "intent": intent_block if intent_present else None,
        "edge_counts": {
            "inbound": comp.get("inbound_edge_count", 0),
            "outbound": comp.get("outbound_edge_count", 0),
        },
    }


def _load_contract_map_flows(project_dir: Path) -> List[Dict[str, Any]]:
    """Read contract-map.yaml and return flows[] (or empty)."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return []
    cm_path = project_dir / "progress" / "contract-map.yaml"
    if not cm_path.is_file():
        return []
    try:
        data = yaml.safe_load(cm_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    flows = data.get("flows", [])
    if not isinstance(flows, list):
        return []
    return [f for f in flows if isinstance(f, dict)]


def flow_intent(
    snapshot: Dict[str, Any],
    flow_id: str,
    project_dir: Path,
) -> Dict[str, Any]:
    """Aggregate intent across every component in the named flow.

    Output shape:
      {
        "flow_id": str,
        "flow_found": bool,
        "components": [
          {"component_id": str, "intent_present": bool,
           "intent": {...} or null}
        ],
        "summary": {
          "components_total": int,
          "components_with_intent": int,
          "function_class_distribution": {fc: count, ...}
        }
      }
    """
    flows = _load_contract_map_flows(project_dir)
    flow = None
    for f in flows:
        if f.get("id") == flow_id:
            flow = f
            break
    if flow is None:
        return {
            "flow_id": flow_id,
            "flow_found": False,
            "components": [],
            "summary": {
                "components_total": 0,
                "components_with_intent": 0,
                "function_class_distribution": {},
            },
        }

    path: List[str] = flow.get("path", []) or []
    components_out: List[Dict[str, Any]] = []
    function_class_dist: Dict[str, int] = {}
    intent_count = 0

    for cid in path:
        comp = _component_by_name(snapshot, cid)
        if comp is None:
            components_out.append({
                "component_id": cid,
                "intent_present": False,
                "intent": None,
            })
            continue
        intent_block = comp.get("intent")
        intent_present = isinstance(intent_block, dict)
        if intent_present:
            intent_count += 1
            fc = intent_block.get("function_class", "unknown")
            function_class_dist[fc] = function_class_dist.get(fc, 0) + 1
        components_out.append({
            "component_id": cid,
            "intent_present": intent_present,
            "intent": intent_block if intent_present else None,
        })

    return {
        "flow_id": flow_id,
        "flow_found": True,
        "components": components_out,
        "summary": {
            "components_total": len(path),
            "components_with_intent": intent_count,
            "function_class_distribution": function_class_dist,
        },
    }
