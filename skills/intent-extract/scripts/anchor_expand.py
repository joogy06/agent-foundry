"""anchor_expand.py — Anchor-and-expand a contract-map component to its 1-hop call neighbourhood.

Reads `.wiring/runs/<run_id>/static.jsonl` (single-line edges per
wiring-source-edge.v1) and `.wiring/runs/<run_id>/manifest.json`. For a given
`component_id`, returns:

  - direct edges originating from or terminating at any symbol in the component
  - the 1-hop expansion: edges of edges, no further
  - file paths participating in the neighbourhood

NEVER expands beyond 1-hop. Auto-traversal of the call graph is an anti-pattern
(per design §13 HARD-RULE 7 — declared flows only, no graph walks).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


class AnchorExpansion:
    """Result of anchor-and-expand for one component."""

    def __init__(
        self,
        component_id: str,
        direct_edges: List[Dict],
        neighbour_edges: List[Dict],
        participating_files: List[str],
        evidence_edge_ids: List[str],
    ) -> None:
        self.component_id = component_id
        self.direct_edges = direct_edges
        self.neighbour_edges = neighbour_edges
        self.participating_files = participating_files
        self.evidence_edge_ids = evidence_edge_ids


def _read_jsonl(path: Path) -> List[Dict]:
    if not path.is_file():
        return []
    out: List[Dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _belongs_to_component(edge: Dict, component_id: str) -> bool:
    return (
        edge.get("src_component") == component_id
        or edge.get("dst_component") == component_id
    )


def anchor_and_expand(
    static_jsonl_path: Path,
    component_id: str,
    *,
    max_neighbour_edges: int = 200,
) -> AnchorExpansion:
    """Find direct + 1-hop edges for `component_id`.

    Args:
        static_jsonl_path: path to .wiring/runs/<run_id>/static.jsonl
        component_id: target component id (must match wiring-source-edge.v1.src_component
                      or dst_component on at least one edge)
        max_neighbour_edges: cap on the 1-hop expansion (token budget guard)

    Returns:
        AnchorExpansion with direct edges, neighbour edges, file list, evidence ids.
    """
    edges = _read_jsonl(static_jsonl_path)
    direct: List[Dict] = []
    direct_symbols: Set[Tuple[str, str]] = set()  # (component, symbol) pairs
    evidence_ids: List[str] = []

    for e in edges:
        if _belongs_to_component(e, component_id):
            direct.append(e)
            eid = e.get("edge_id")
            if eid:
                evidence_ids.append(eid)
            for side in ("src", "dst"):
                comp = e.get(f"{side}_component")
                sym = e.get(f"{side}_symbol")
                if comp and sym:
                    direct_symbols.add((comp, sym))

    # 1-hop: edges that touch any direct_symbol but NOT the original component
    neighbours: List[Dict] = []
    for e in edges:
        if _belongs_to_component(e, component_id):
            continue
        src_key = (e.get("src_component"), e.get("src_symbol"))
        dst_key = (e.get("dst_component"), e.get("dst_symbol"))
        if src_key in direct_symbols or dst_key in direct_symbols:
            neighbours.append(e)
            if len(neighbours) >= max_neighbour_edges:
                break

    # Files: harvest callsite_refs and src/dst paths
    files: Set[str] = set()
    for e in direct + neighbours:
        for ref in e.get("callsite_refs", []) or []:
            p = ref.get("path")
            if p:
                files.add(p)

    return AnchorExpansion(
        component_id=component_id,
        direct_edges=direct,
        neighbour_edges=neighbours,
        participating_files=sorted(files),
        evidence_edge_ids=sorted(set(evidence_ids)),
    )


def load_component_source_paths(
    contract_map: Dict,
    component_id: str,
    project_root: Path,
) -> List[Path]:
    """Resolve contract-map components[<id>].source_paths into absolute paths.

    Expands `**` globs and `~` references. Returns only paths that exist.
    """
    component = None
    for c in contract_map.get("components", []):
        if c.get("id") == component_id:
            component = c
            break
    if component is None:
        return []

    source_globs = component.get("source_paths", [])
    resolved: List[Path] = []
    for g in source_globs:
        # Strip ~/ and absolute markers; resolve relative to project_root
        raw = g
        if raw.startswith("~/"):
            raw = str(Path.home() / raw[2:])
        if raw.startswith("/"):
            search_base = Path(raw).parent
            pattern = Path(raw).name
            try:
                matches = list(search_base.glob(pattern))
            except OSError:
                matches = []
        else:
            try:
                matches = list(project_root.glob(raw))
            except OSError:
                matches = []
        for m in matches:
            if m.is_file():
                resolved.append(m)
    # Dedup + sort
    return sorted(set(resolved), key=str)


def evidence_edge_ids_for(
    static_jsonl_path: Path,
    component_id: str,
) -> List[str]:
    """Convenience: just the evidence edge ids for a component (sorted)."""
    return anchor_and_expand(static_jsonl_path, component_id).evidence_edge_ids
