"""d4_heatmap.py — Markdown table emitter for intent × test coverage crosswalk.

Reads intent-map.components → for each component, summarises
test_seed_count, error_path_count, evidence_edge_count, confidence_level
in a GFM table.

Deterministic — sort by component_id ascending.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _component_summary(c: Dict[str, Any]) -> Tuple[str, str, str, int, int, int]:
    """Extract (component_id, function_class, confidence, seeds, errors, edges)."""
    cid = c.get("component_id") or c.get("name") or "unknown"

    # Two shapes supported:
    #   (a) functional-intent.v1 doc directly → fc/seeds/errs at top level
    #   (b) snapshot.v1.1 component → c["intent"] block
    if "function_class" in c:
        fc = c.get("function_class", "unknown")
        seeds = len(c.get("test_seeds", []) or [])
        errs = len(c.get("error_paths", []) or [])
        # Evidence edges accumulated across entry_points/side_effects/error_paths
        edges = 0
        for f in ("entry_points", "side_effects", "error_paths"):
            for item in c.get(f, []) or []:
                if isinstance(item, dict):
                    edges += len(item.get("evidence_edges", []) or [])
        intent = c.get("intent", {})
        confidence = intent.get("confidence_level", "interpretive") if isinstance(intent, dict) else "interpretive"
    else:
        intent = c.get("intent", {})
        if not isinstance(intent, dict):
            intent = {}
        fc = intent.get("function_class", "unknown")
        confidence = intent.get("confidence_level", "interpretive")
        seeds = int(intent.get("test_seed_count", 0))
        errs = int(intent.get("error_path_count", 0))
        edges = int(intent.get("evidence_edge_count", 0))

    return (cid, fc, confidence, seeds, errs, edges)


def render(intent_map: Dict[str, Any]) -> str:
    """Render D4 GFM table."""
    components = intent_map.get("components", []) or []
    if not components:
        return "## D4 — Coverage Heatmap\n\n_No components mapped._\n"

    rows = [_component_summary(c) for c in components]
    rows.sort(key=lambda r: r[0])

    out: List[str] = []
    out.append("## D4 — Coverage Heatmap")
    out.append("")
    out.append("| Component | function_class | confidence | test_seeds | error_paths | evidence_edges |")
    out.append("|---|---|---|---:|---:|---:|")
    for (cid, fc, conf, seeds, errs, edges) in rows:
        out.append(f"| {cid} | {fc} | {conf} | {seeds} | {errs} | {edges} |")
    out.append("")
    # Aggregate row
    total_seeds = sum(r[3] for r in rows)
    total_errs = sum(r[4] for r in rows)
    total_edges = sum(r[5] for r in rows)
    grounded = sum(1 for r in rows if r[2] == "grounded")
    out.append(f"_Totals — components: {len(rows)}, grounded: {grounded}, "
               f"test_seeds: {total_seeds}, error_paths: {total_errs}, "
               f"evidence_edges: {total_edges}_")
    out.append("")
    return "\n".join(out)
