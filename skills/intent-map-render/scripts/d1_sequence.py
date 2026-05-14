"""d1_sequence.py — Mermaid sequenceDiagram emitter.

For each component in the intent-map, generate a sequence showing entry_points
making 1-hop calls. Default C4 container+component level (no function-level
arrows by default — that's HARD-RULE 5).

Two-tier progressive disclosure: when component count > 20, wrap each
component's lane in a `<details>` block.
"""
from __future__ import annotations

from typing import Any, Dict, List

COLLAPSE_THRESHOLD = 20


def _sanitize(name: str) -> str:
    """Mermaid participant names — replace whitespace with underscores."""
    return name.replace(" ", "_").replace("-", "_")


def render_single_component(component: Dict[str, Any]) -> str:
    """Render one Mermaid sequenceDiagram for a single component."""
    comp_id = component.get("component_id", "unknown")
    entry_points: List[Dict[str, Any]] = component.get("entry_points", []) or []
    side_effects: List[Dict[str, Any]] = component.get("side_effects", []) or []
    error_paths: List[Dict[str, Any]] = component.get("error_paths", []) or []

    actor_name = _sanitize(comp_id)
    lines: List[str] = []
    lines.append("```mermaid")
    lines.append("sequenceDiagram")
    lines.append(f"    participant External")
    lines.append(f"    participant {actor_name}")

    # Render entry points as inbound arrows from External
    for ep in entry_points:
        kind = ep.get("kind", "lib_api")
        detail = ep.get("detail", "?")
        lines.append(f"    External->>+{actor_name}: {kind} {detail}")

    # Render side effects as outbound arrows to External targets
    for se in side_effects:
        kind = se.get("kind", "io")
        target = se.get("target", "external")
        target_actor = _sanitize(target.split("//")[-1].split("?")[0])
        if target_actor != actor_name:
            lines.append(f"    participant {target_actor}")
        lines.append(f"    {actor_name}->>{target_actor}: {kind}")

    # Render error paths
    for er in error_paths:
        cond = er.get("condition", "error")
        kind = er.get("error_kind", "raises")
        lines.append(f"    Note over {actor_name}: {kind} on {cond}")

    # Close active blocks
    if entry_points:
        lines.append(f"    {actor_name}-->>-External: response")

    lines.append("```")
    return "\n".join(lines)


def render(intent_map: Dict[str, Any]) -> str:
    """Render D1 for all components in intent-map.

    Returns a single markdown blob. When component_count > COLLAPSE_THRESHOLD,
    wraps each in `<details>` block.
    """
    components = intent_map.get("components", []) or []
    if not components:
        return "<!-- D1: no components found -->\n"

    collapse = len(components) > COLLAPSE_THRESHOLD
    out_parts: List[str] = []
    out_parts.append("## D1 — Intent Sequence Diagrams")
    out_parts.append("")
    out_parts.append(f"Components rendered: {len(components)}")
    out_parts.append("")

    # Sort for determinism
    sorted_components = sorted(components, key=lambda c: c.get("component_id", ""))

    for comp in sorted_components:
        comp_id = comp.get("component_id", "unknown")
        diagram = render_single_component(comp)
        if collapse:
            out_parts.append(f"<details><summary>{comp_id}</summary>")
            out_parts.append("")
            out_parts.append(diagram)
            out_parts.append("")
            out_parts.append("</details>")
        else:
            out_parts.append(f"### {comp_id}")
            out_parts.append("")
            out_parts.append(diagram)
        out_parts.append("")

    return "\n".join(out_parts).rstrip() + "\n"
