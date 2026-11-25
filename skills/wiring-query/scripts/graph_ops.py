#!/usr/bin/env python3
"""graph_ops.py — deterministic BFS + subgraph slicing for wiring-query.

Two public operations, both pure Python, both deterministic.

Per design 2026-04-14 §5.3.

Hard rules:
- NO LLM calls.
- BFS <50ms on 10k edges at depth 3 (unit test enforces).
- Cycle detection via visited set.
- Anchor-not-found -> `anchor_found: false` + top-3 fuzzy matches via
  difflib.get_close_matches.
- Truncation by `max_edges` OR `max_tokens` yields `truncated: true` plus
  the number of omitted edges.
- Output ordering is fully deterministic: sort edges by `edge_id` ascending
  so the same snapshot+anchor produces bit-identical stdout.

Drift canary: ALDEBARAN-7.
"""
from __future__ import annotations

import difflib
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Index building (per-snapshot, cached by caller)
# ---------------------------------------------------------------------------

def build_symbol_index(snapshot: Dict[str, Any]) -> Dict[str, Dict[str, List[Dict]]]:
    """Build symbol->edges adjacency once per snapshot.

    Returns a dict:
      {
        "out":  {symbol: [edge_ref, ...]},   # edges where src_symbol == symbol
        "in":   {symbol: [edge_ref, ...]},   # edges where dst_symbol == symbol
        "all_symbols": sorted list of all symbols (for fuzzy match),
      }

    Each edge_ref is the raw edge dict from snapshot.edges (by reference).
    """
    out_edges: Dict[str, List[Dict]] = defaultdict(list)
    in_edges: Dict[str, List[Dict]] = defaultdict(list)
    all_symbols: Set[str] = set()
    for edge in snapshot.get("edges", []):
        s = edge["src_symbol"]
        d = edge["dst_symbol"]
        out_edges[s].append(edge)
        in_edges[d].append(edge)
        all_symbols.add(s)
        all_symbols.add(d)
    return {
        "out": dict(out_edges),
        "in": dict(in_edges),
        "all_symbols": sorted(all_symbols),
    }


def fuzzy_suggestions(anchor: str, all_symbols: List[str], n: int = 3) -> List[str]:
    """Top-N fuzzy matches for an anchor that wasn't found."""
    return difflib.get_close_matches(anchor, all_symbols, n=n, cutoff=0.5)


# ---------------------------------------------------------------------------
# Op 1: impact
# ---------------------------------------------------------------------------

def impact(
    snapshot: Dict[str, Any],
    symbol: str,
    max_depth: int = 3,
    include_stale: bool = False,
    index: Optional[Dict[str, Dict[str, List[Dict]]]] = None,
) -> Dict[str, Any]:
    """BFS outwards from `symbol` as either src OR dst, up to max_depth.

    Returns a dict shaped per design §5.3:
      {
        "query": "impact",
        "args": {"symbol": ..., "max_depth": ..., "include_stale": ...},
        "snapshot_generation": int,
        "anchor": symbol,
        "anchor_found": bool,
        "edges": [...compact edge entries...],
        "components_touched": [...],
        "hop_counts": {"1": int, "2": int, ...},
        "provenance_breakdown": {"static_extract": int, "agent_asserted": int, "manual": int},
        "truncated": false,
        "summary_md": "...",
        "suggestions": [...]  # only when anchor_found is false
      }
    """
    if index is None:
        index = build_symbol_index(snapshot)

    all_symbols = index["all_symbols"]
    out_map = index["out"]
    in_map = index["in"]

    result: Dict[str, Any] = {
        "query": "impact",
        "args": {
            "symbol": symbol,
            "max_depth": max_depth,
            "include_stale": include_stale,
        },
        "snapshot_generation": snapshot.get("snapshot_generation"),
        "anchor": symbol,
        "anchor_found": symbol in all_symbols,
        "edges": [],
        "components_touched": [],
        "hop_counts": {},
        "provenance_breakdown": {
            "static_extract": 0,
            "agent_asserted": 0,
            "manual": 0,
        },
        "truncated": False,
    }

    if not result["anchor_found"]:
        result["suggestions"] = fuzzy_suggestions(symbol, all_symbols, n=3)
        result["summary_md"] = (
            f"anchor `{symbol}` not found in snapshot generation "
            f"{result['snapshot_generation']}. "
            f"Top suggestions: {result['suggestions']}"
        )
        return result

    # BFS. Node identity = symbol. Edges traverse both directions
    # (caller asked for impact, which includes upstream AND downstream).
    visited: Set[str] = {symbol}
    hop_of: Dict[str, int] = {symbol: 0}
    queue: deque[str] = deque([symbol])
    collected_edges: Dict[str, Tuple[Dict, int]] = {}  # edge_id -> (edge, hop)

    while queue:
        cur = queue.popleft()
        cur_hop = hop_of[cur]
        if cur_hop >= max_depth:
            continue
        # Walk outgoing edges (cur as src)
        for edge in out_map.get(cur, []):
            _maybe_record(edge, cur_hop + 1, collected_edges, include_stale)
            nxt = edge["dst_symbol"]
            if nxt not in visited:
                visited.add(nxt)
                hop_of[nxt] = cur_hop + 1
                queue.append(nxt)
        # Walk incoming edges (cur as dst)
        for edge in in_map.get(cur, []):
            _maybe_record(edge, cur_hop + 1, collected_edges, include_stale)
            prv = edge["src_symbol"]
            if prv not in visited:
                visited.add(prv)
                hop_of[prv] = cur_hop + 1
                queue.append(prv)

    # Sort edges deterministically by edge_id
    sorted_edge_ids = sorted(collected_edges.keys())
    compact: List[Dict[str, Any]] = []
    hop_counts: Dict[str, int] = defaultdict(int)
    components: Set[str] = set()
    prov: Dict[str, int] = defaultdict(int)
    for eid in sorted_edge_ids:
        edge, hop = collected_edges[eid]
        components.add(edge["src_component"])
        components.add(edge["dst_component"])
        hop_counts[str(hop)] += 1
        ev_summary = _evidence_summary(edge.get("evidence", []))
        for e in edge.get("evidence", []):
            src = e.get("evidence_source")
            if src in prov:
                prov[src] += 1
            else:
                # Unknown source — count but do not seed keys outside the v1 set
                prov[src] = prov.get(src, 0) + 1
        compact.append({
            "edge_id": edge["edge_id"],
            "src_component": edge["src_component"],
            "src_symbol": edge["src_symbol"],
            "dst_component": edge["dst_component"],
            "dst_symbol": edge["dst_symbol"],
            "edge_kind": edge["edge_kind"],
            "status": edge.get("status"),
            "blocking_eligible": edge.get("blocking_eligible", False),
            "hop": hop,
            "evidence_summary": ev_summary,
        })

    result["edges"] = compact
    result["components_touched"] = sorted(components)
    result["hop_counts"] = dict(hop_counts)
    # Merge provenance counts ensuring v1 keys always present
    for k in ("static_extract", "agent_asserted", "manual"):
        result["provenance_breakdown"][k] = prov.get(k, 0)
    for k, v in prov.items():
        if k not in result["provenance_breakdown"]:
            result["provenance_breakdown"][k] = v

    result["summary_md"] = _impact_summary_md(symbol, compact, sorted(components))
    return result


def _maybe_record(edge: Dict, hop: int, store: Dict[str, Tuple[Dict, int]],
                  include_stale: bool) -> None:
    status = edge.get("status")
    if status in ("orphan", "suppressed"):
        return
    if status == "stale" and not include_stale:
        return
    eid = edge["edge_id"]
    if eid in store:
        # Keep shorter hop
        if hop < store[eid][1]:
            store[eid] = (edge, hop)
    else:
        store[eid] = (edge, hop)


def _evidence_summary(evidence: List[Dict]) -> List[str]:
    """Render each evidence entry as `source:extractor@version`, sorted."""
    parts = []
    for e in evidence:
        src = e.get("evidence_source", "?")
        ext = e.get("extractor_id", "?")
        ver = e.get("extractor_version", "?")
        parts.append(f"{src}:{ext}@{ver}")
    return sorted(parts)


def _impact_summary_md(symbol: str, edges: List[Dict], components: List[str]) -> str:
    if not edges:
        return f"`{symbol}` has 0 impacted edges. Anchor exists but no traversable edges found."
    blocking = sum(1 for e in edges if e.get("blocking_eligible"))
    return (
        f"`{symbol}` has {len(edges)} impacted edges across components: "
        f"{', '.join(components)}. "
        f"{blocking}/{len(edges)} blocking-eligible (static-corroborated)."
    )


# ---------------------------------------------------------------------------
# Op 2: subgraph_for_llm
# ---------------------------------------------------------------------------

# Heuristic: 1 edge compact entry ~= 160 tokens. We use a conservative
# per-edge token estimate for budget enforcement. This is deterministic.
_TOKENS_PER_EDGE = 160


def subgraph_for_llm(
    snapshot: Dict[str, Any],
    anchors: List[str],
    max_edges: int = 40,
    max_tokens: int = 50000,
    max_depth: int = 2,
    include_stale: bool = False,
    index: Optional[Dict[str, Dict[str, List[Dict]]]] = None,
) -> Dict[str, Any]:
    """Return a bounded subgraph covering one or more anchors.

    Strategy: BFS up to max_depth from each anchor; union the edge sets;
    truncate by min(max_edges, max_tokens / TOKENS_PER_EDGE).
    """
    if index is None:
        index = build_symbol_index(snapshot)

    result: Dict[str, Any] = {
        "query": "subgraph_for_llm",
        "args": {
            "anchors": list(anchors),
            "max_edges": max_edges,
            "max_tokens": max_tokens,
            "max_depth": max_depth,
            "include_stale": include_stale,
        },
        "snapshot_generation": snapshot.get("snapshot_generation"),
        "anchors_found": {},
        "edges": [],
        "components_touched": [],
        "provenance_breakdown": {
            "static_extract": 0,
            "agent_asserted": 0,
            "manual": 0,
        },
        "truncated": False,
        "omitted_edge_count": 0,
        "suggestions": {},
    }

    # Per-anchor impact reuse
    all_edges: Dict[str, Tuple[Dict, int]] = {}
    for anchor in anchors:
        sub = impact(snapshot, anchor, max_depth=max_depth,
                     include_stale=include_stale, index=index)
        result["anchors_found"][anchor] = sub["anchor_found"]
        if not sub["anchor_found"]:
            result["suggestions"][anchor] = sub.get("suggestions", [])
            continue
        # Merge edges; prefer lower hop
        for ce in sub["edges"]:
            eid = ce["edge_id"]
            if eid in all_edges:
                if ce["hop"] < all_edges[eid][1]:
                    all_edges[eid] = (ce, ce["hop"])
            else:
                all_edges[eid] = (ce, ce["hop"])

    # Compute token-based edge budget
    token_edge_cap = max(1, max_tokens // _TOKENS_PER_EDGE)
    hard_cap = min(max_edges, token_edge_cap)

    sorted_eids = sorted(all_edges.keys())
    total_eids = len(sorted_eids)
    if total_eids > hard_cap:
        truncated_eids = sorted_eids[:hard_cap]
        result["truncated"] = True
        result["omitted_edge_count"] = total_eids - hard_cap
    else:
        truncated_eids = sorted_eids

    # Build output
    components: Set[str] = set()
    prov: Dict[str, int] = defaultdict(int)
    out_edges: List[Dict] = []
    for eid in truncated_eids:
        ce, _hop = all_edges[eid]
        components.add(ce["src_component"])
        components.add(ce["dst_component"])
        for ev_str in ce.get("evidence_summary", []):
            src = ev_str.split(":", 1)[0] if ":" in ev_str else ev_str
            prov[src] += 1
        out_edges.append(ce)

    result["edges"] = out_edges
    result["components_touched"] = sorted(components)
    for k in ("static_extract", "agent_asserted", "manual"):
        result["provenance_breakdown"][k] = prov.get(k, 0)
    for k, v in prov.items():
        if k not in result["provenance_breakdown"]:
            result["provenance_breakdown"][k] = v

    result["estimated_tokens"] = len(out_edges) * _TOKENS_PER_EDGE
    result["summary_md"] = _subgraph_summary_md(
        anchors, out_edges, sorted(components), result["truncated"],
        result["omitted_edge_count"]
    )
    return result


def _subgraph_summary_md(anchors: List[str], edges: List[Dict],
                          components: List[str], truncated: bool,
                          omitted: int) -> str:
    header = f"Subgraph for anchors {anchors}: {len(edges)} edges across {len(components)} components"
    if truncated:
        header += f" (truncated; {omitted} edges omitted)"
    rows = ["", "| src | dst | kind | status | hop |",
            "|---|---|---|---|---|"]
    for e in edges[:50]:  # cap markdown table rendering
        rows.append(
            f"| `{e['src_symbol']}` | `{e['dst_symbol']}` | "
            f"{e['edge_kind']} | {e.get('status', '?')} | {e.get('hop', '?')} |"
        )
    return header + "\n" + "\n".join(rows)
