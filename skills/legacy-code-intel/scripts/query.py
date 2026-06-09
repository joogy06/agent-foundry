#!/usr/bin/env python3
"""query.py — deterministic graph query layer over catalog/latest.json.

Anti-requirement #3: the discarded agy build reimplemented BFS ad-hoc, byte-sliced
markdown for its "token budget", and never sorted edges, so two runs produced
different bytes. This port adopts the SHAPE of wiring-query/scripts/graph_ops.py
PROPERLY:

  - The adjacency index is built ONCE per snapshot (build_symbol_index).
  - BFS visits in a deterministic order; collected edges are sorted by a STABLE
    edge key (rel, from_id, to_id) before emission.
  - The token/edge budget is REAL (min(max_edges, max_tokens // TOKENS_PER_EDGE)),
    NOT a byte-slice of rendered text.
  - Anchor-not-found yields anchor_found:false + top-3 difflib fuzzy matches.
  - stdout is canonical JSON (sort_keys, no wall-clock), so two runs over the same
    catalog produce byte-identical output (test_query_determinism).

Reads ONLY catalog/latest.json (never the objects/ store — the catalog is the
promoted projection). NO LLM calls. Pure stdlib.

Ops (design §5):
    find_symbol <query>        fuzzy/exact symbol lookup (difflib)
    defs <symbol|name>         definition occurrences (cross-artifact)
    refs <symbol|name>         reference occurrences (cross-artifact)
    impact <symbol|name>       hop-bounded BFS over calls/copies/reads/writes;
                               ADVISORY (speculative framing) until the format's
                               gold precision clears the threshold (design §8).
    list_artifacts            promoted artifacts
    subgraph_for_llm <anchors> token-bounded slice for downstream LLM consumption

Exit codes (mirror wiring-query): 0 ok, 1 not-found/empty, 2 usage/error.

CLI usage:
    query.py <op> [args] [--store PATH] [--max-depth N] [--max-edges N]
             [--max-tokens N] [--include-speculative]
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Relationship kinds that participate in impact() traversal (design §5).
_IMPACT_RELS = {"calls", "copies", "reads", "writes", "schedules", "references"}
_TOKENS_PER_EDGE = 160  # conservative deterministic per-edge token estimate


# ---------------- Snapshot loading ---------------- #

def resolve_store_root(store: Optional[str]) -> Path:
    import os
    if store:
        root = Path(store)
        if not root.is_absolute():
            root = Path.cwd() / root
    elif os.environ.get("LCI_STORE"):
        root = Path(os.environ["LCI_STORE"])
    else:
        root = Path.home() / ".codelib"
    return root.resolve()


def load_catalog(root: Path) -> Optional[dict]:
    cat = root / "catalog" / "latest.json"
    if not cat.is_file():
        return None
    try:
        return json.loads(cat.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------- Index building (once per snapshot) ---------------- #

def build_symbol_index(catalog: dict) -> Dict[str, Any]:
    """Build adjacency + lookup indexes ONCE. Mirrors graph_ops.build_symbol_index.

    Returns:
      out:        {symbol_id: [relationship, ...]}  edges where from_id == symbol
      in_:        {symbol_id: [relationship, ...]}  edges where to_id == symbol
      by_id:      {symbol_id: symbol}
      name_to_ids:{name: [symbol_id, ...]}          for name-based lookup
      all_ids:    sorted list of all symbol_ids
      all_names:  sorted list of all names (for fuzzy)
      defs:       {symbol_id: [occurrence, ...]}     role == definition
      refs:       {symbol_id: [occurrence, ...]}     role == reference
    """
    out_edges: Dict[str, List[dict]] = defaultdict(list)
    in_edges: Dict[str, List[dict]] = defaultdict(list)
    by_id: Dict[str, dict] = {}
    name_to_ids: Dict[str, List[str]] = defaultdict(list)
    defs: Dict[str, List[dict]] = defaultdict(list)
    refs: Dict[str, List[dict]] = defaultdict(list)

    for sym in catalog.get("symbols", []):
        sid = sym.get("symbol_id")
        if not sid:
            continue
        by_id[sid] = sym
        nm = sym.get("name")
        if nm:
            name_to_ids[nm].append(sid)

    for rel in catalog.get("relationships", []):
        f, t = rel.get("from_id"), rel.get("to_id")
        if f:
            out_edges[f].append(rel)
        if t:
            in_edges[t].append(rel)

    for occ in catalog.get("occurrences", []):
        sid = occ.get("symbol_id")
        if not sid:
            continue
        if occ.get("role") == "definition":
            defs[sid].append(occ)
        elif occ.get("role") == "reference":
            refs[sid].append(occ)

    return {
        "out": dict(out_edges),
        "in": dict(in_edges),
        "by_id": by_id,
        "name_to_ids": {k: sorted(v) for k, v in name_to_ids.items()},
        "all_ids": sorted(by_id.keys()),
        "all_names": sorted(name_to_ids.keys()),
        "defs": dict(defs),
        "refs": dict(refs),
    }


def resolve_anchor(query: str, index: Dict[str, Any]) -> Tuple[Optional[str], List[str]]:
    """Resolve a query string to a symbol_id. Accepts a full symbol_id, or a name.
    Returns (resolved_symbol_id_or_None, fuzzy_suggestions)."""
    if query in index["by_id"]:
        return query, []
    ids = index["name_to_ids"].get(query)
    if ids:
        # Deterministic: pick the lexicographically smallest id for a name with
        # multiple symbols (callers can disambiguate via the suggestions list).
        return ids[0], ids[1:] if len(ids) > 1 else []
    # Fuzzy over names first, then full ids.
    name_sugg = difflib.get_close_matches(query, index["all_names"], n=3, cutoff=0.5)
    if name_sugg:
        return None, name_sugg
    id_sugg = difflib.get_close_matches(query, index["all_ids"], n=3, cutoff=0.5)
    return None, id_sugg


# ---------------- Ops ---------------- #

def op_find_symbol(catalog: dict, index: Dict[str, Any], query: str) -> dict:
    exact_id = query if query in index["by_id"] else None
    name_ids = index["name_to_ids"].get(query, [])
    matches = []
    seen = set()
    for sid in ([exact_id] if exact_id else []) + name_ids:
        if sid and sid not in seen:
            seen.add(sid)
            matches.append(index["by_id"][sid])
    suggestions = []
    if not matches:
        suggestions = difflib.get_close_matches(query, index["all_names"], n=5, cutoff=0.4)
    return {
        "op": "find_symbol", "query": query,
        "matches": sorted(matches, key=lambda s: (s.get("symbol_id", ""))),
        "match_count": len(matches), "suggestions": suggestions,
    }


def op_defs(catalog: dict, index: Dict[str, Any], query: str) -> dict:
    sid, sugg = resolve_anchor(query, index)
    if sid is None:
        return {"op": "defs", "query": query, "anchor_found": False, "suggestions": sugg, "occurrences": []}
    occs = sorted(index["defs"].get(sid, []),
                  key=lambda o: (o["range"]["start_line"], o["range"]["end_line"], o.get("source_path", "")))
    return {"op": "defs", "query": query, "anchor_found": True, "symbol_id": sid,
            "occurrences": occs, "occurrence_count": len(occs)}


def op_refs(catalog: dict, index: Dict[str, Any], query: str) -> dict:
    sid, sugg = resolve_anchor(query, index)
    if sid is None:
        return {"op": "refs", "query": query, "anchor_found": False, "suggestions": sugg, "occurrences": []}
    occs = sorted(index["refs"].get(sid, []),
                  key=lambda o: (o["range"]["start_line"], o["range"]["end_line"], o.get("source_path", "")))
    return {"op": "refs", "query": query, "anchor_found": True, "symbol_id": sid,
            "occurrences": occs, "occurrence_count": len(occs)}


def op_list_artifacts(catalog: dict, index: Dict[str, Any]) -> dict:
    arts = sorted(catalog.get("artifacts", []), key=lambda a: (a.get("source_path", ""), a.get("content_sha256", "")))
    return {"op": "list_artifacts", "artifacts": arts, "artifact_count": len(arts)}


def _symbol_format(index: Dict[str, Any], sid: str) -> Optional[str]:
    sym = index["by_id"].get(sid)
    return sym.get("format") if sym else None


def _advisory_for_format(catalog: dict, fmt: Optional[str]) -> bool:
    """True => impact() must be presented as speculative for this format (design §8).
    Default advisory unless the format's gold precision cleared the threshold."""
    acc = catalog.get("accuracy", {})
    if fmt is None:
        return True
    by_fmt = acc.get("by_format", {}).get(fmt)
    if not by_fmt:
        return True  # no gold check => advisory
    return bool(by_fmt.get("advisory", True))


def op_impact(catalog: dict, index: Dict[str, Any], query: str,
              max_depth: int = 3, include_speculative: bool = True,
              max_edges: int = 200) -> dict:
    """Hop-bounded BFS over impact relationships. ADVISORY by default.

    Mirrors graph_ops.impact: BFS both directions, collect edges, sort by stable
    key, hop_counts. The advisory flag (design §8) is set from the catalog's gold
    accuracy for the anchor's format — below threshold => speculative framing."""
    sid, sugg = resolve_anchor(query, index)
    fmt = _symbol_format(index, sid) if sid else None
    advisory = _advisory_for_format(catalog, fmt)

    result: Dict[str, Any] = {
        "op": "impact", "query": query, "anchor_found": sid is not None,
        "symbol_id": sid, "format": fmt, "advisory": advisory,
        "advisory_note": (
            "impact() is ADVISORY (speculative) for this format: gold-file call-edge "
            "precision has not cleared the threshold. Do NOT treat as authoritative."
            if advisory else
            "impact() is authoritative for this format (gold precision cleared)."
        ),
        "max_depth": max_depth, "edges": [], "components_touched": [],
        "hop_counts": {}, "truncated": False, "omitted_edge_count": 0,
    }
    if sid is None:
        result["suggestions"] = sugg
        return result

    out_map, in_map = index["out"], index["in"]
    visited: Set[str] = {sid}
    hop_of: Dict[str, int] = {sid: 0}
    queue: deque = deque([sid])
    collected: Dict[Tuple[str, str, str], Tuple[dict, int]] = {}

    while queue:
        cur = queue.popleft()
        cur_hop = hop_of[cur]
        if cur_hop >= max_depth:
            continue
        for rel in out_map.get(cur, []):
            if rel.get("rel") not in _IMPACT_RELS:
                continue
            if not include_speculative and rel.get("confidence") == "speculative":
                continue
            _record(rel, cur_hop + 1, collected)
            nxt = rel.get("to_id")
            if nxt and nxt not in visited:
                visited.add(nxt)
                hop_of[nxt] = cur_hop + 1
                queue.append(nxt)
        for rel in in_map.get(cur, []):
            if rel.get("rel") not in _IMPACT_RELS:
                continue
            if not include_speculative and rel.get("confidence") == "speculative":
                continue
            _record(rel, cur_hop + 1, collected)
            prv = rel.get("from_id")
            if prv and prv not in visited:
                visited.add(prv)
                hop_of[prv] = cur_hop + 1
                queue.append(prv)

    sorted_keys = sorted(collected.keys())
    if len(sorted_keys) > max_edges:
        result["truncated"] = True
        result["omitted_edge_count"] = len(sorted_keys) - max_edges
        sorted_keys = sorted_keys[:max_edges]

    hop_counts: Dict[str, int] = defaultdict(int)
    components: Set[str] = set()
    edges_out: List[dict] = []
    for key in sorted_keys:
        rel, hop = collected[key]
        hop_counts[str(hop)] += 1
        for end_id in (rel.get("from_id"), rel.get("to_id")):
            f = _symbol_format(index, end_id)
            if f:
                components.add(f)
        edges_out.append({
            "rel": rel.get("rel"), "from_id": rel.get("from_id"), "to_id": rel.get("to_id"),
            "confidence": rel.get("confidence"), "hop": hop,
        })

    result["edges"] = edges_out
    result["edge_count"] = len(edges_out)
    result["components_touched"] = sorted(components)
    result["hop_counts"] = dict(hop_counts)
    return result


def _record(rel: dict, hop: int, store: Dict[Tuple[str, str, str], Tuple[dict, int]]) -> None:
    key = (rel.get("rel", ""), rel.get("from_id", ""), rel.get("to_id", ""))
    if key in store:
        if hop < store[key][1]:
            store[key] = (rel, hop)
    else:
        store[key] = (rel, hop)


def op_subgraph_for_llm(catalog: dict, index: Dict[str, Any], anchors: List[str],
                        max_depth: int = 2, max_edges: int = 40, max_tokens: int = 50000,
                        include_speculative: bool = True) -> dict:
    """Token-bounded subgraph union over anchors. REAL budget (min(max_edges,
    max_tokens // TOKENS_PER_EDGE)) — NOT a byte-slice. Mirrors
    graph_ops.subgraph_for_llm."""
    result: Dict[str, Any] = {
        "op": "subgraph_for_llm", "anchors": list(anchors),
        "max_depth": max_depth, "max_edges": max_edges, "max_tokens": max_tokens,
        "anchors_found": {}, "suggestions": {}, "edges": [],
        "components_touched": [], "truncated": False, "omitted_edge_count": 0,
    }
    union: Dict[Tuple[str, str, str], Tuple[dict, int]] = {}
    for anchor in anchors:
        sub = op_impact(catalog, index, anchor, max_depth=max_depth,
                        include_speculative=include_speculative, max_edges=10 ** 9)
        result["anchors_found"][anchor] = sub["anchor_found"]
        if not sub["anchor_found"]:
            result["suggestions"][anchor] = sub.get("suggestions", [])
            continue
        for e in sub["edges"]:
            key = (e["rel"], e["from_id"], e["to_id"])
            if key not in union or e["hop"] < union[key][1]:
                union[key] = (e, e["hop"])

    token_cap = max(1, max_tokens // _TOKENS_PER_EDGE)
    hard_cap = min(max_edges, token_cap)
    sorted_keys = sorted(union.keys())
    if len(sorted_keys) > hard_cap:
        result["truncated"] = True
        result["omitted_edge_count"] = len(sorted_keys) - hard_cap
        sorted_keys = sorted_keys[:hard_cap]

    components: Set[str] = set()
    edges_out: List[dict] = []
    for key in sorted_keys:
        e, _hop = union[key]
        for end_id in (e["from_id"], e["to_id"]):
            f = _symbol_format(index, end_id)
            if f:
                components.add(f)
        edges_out.append(e)

    result["edges"] = edges_out
    result["edge_count"] = len(edges_out)
    result["components_touched"] = sorted(components)
    result["estimated_tokens"] = len(edges_out) * _TOKENS_PER_EDGE
    return result


# ---------------- CLI ---------------- #

def _emit(obj: dict) -> None:
    """Canonical JSON stdout (byte-identical across runs: sort_keys, no wall-clock)."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")


def run_query(op: str, args, catalog: dict) -> Tuple[dict, int]:
    index = build_symbol_index(catalog)
    if op == "find_symbol":
        res = op_find_symbol(catalog, index, args.query)
        return res, (0 if res["match_count"] else 1)
    if op == "defs":
        res = op_defs(catalog, index, args.query)
        return res, (0 if res.get("anchor_found") and res.get("occurrence_count") else 1)
    if op == "refs":
        res = op_refs(catalog, index, args.query)
        return res, (0 if res.get("anchor_found") and res.get("occurrence_count") else 1)
    if op == "impact":
        res = op_impact(catalog, index, args.query, max_depth=args.max_depth,
                        include_speculative=args.include_speculative, max_edges=args.max_edges)
        return res, (0 if res.get("anchor_found") else 1)
    if op == "list_artifacts":
        res = op_list_artifacts(catalog, index)
        return res, (0 if res["artifact_count"] else 1)
    if op == "subgraph_for_llm":
        anchors = args.anchors
        res = op_subgraph_for_llm(catalog, index, anchors, max_depth=args.max_depth,
                                  max_edges=args.max_edges, max_tokens=args.max_tokens,
                                  include_speculative=args.include_speculative)
        return res, (0 if any(res["anchors_found"].values()) else 1)
    return {"error": f"unknown op {op}"}, 2


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("op", choices=["find_symbol", "defs", "refs", "impact", "list_artifacts", "subgraph_for_llm"])
    parser.add_argument("query", nargs="?", default=None)
    parser.add_argument("--anchors", nargs="+", default=None, help="for subgraph_for_llm")
    parser.add_argument("--store")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--max-edges", type=int, default=200)
    parser.add_argument("--max-tokens", type=int, default=50000)
    parser.add_argument("--include-speculative", action="store_true", default=True)
    parser.add_argument("--no-speculative", dest="include_speculative", action="store_false")
    args = parser.parse_args(argv)

    # normalize anchors for subgraph
    if args.op == "subgraph_for_llm":
        if not args.anchors:
            if args.query:
                args.anchors = [args.query]
            else:
                print("ERROR: subgraph_for_llm needs --anchors or a positional query", file=sys.stderr)
                return 2
    else:
        if args.op != "list_artifacts" and not args.query:
            print(f"ERROR: op {args.op} needs a query argument", file=sys.stderr)
            return 2

    root = resolve_store_root(args.store)
    catalog = load_catalog(root)
    if catalog is None:
        _emit({"error": "no promoted catalog", "store": str(root),
               "hint": "run `legacy-code-intel ingest` first"})
        return 1

    res, code = run_query(args.op, args, catalog)
    _emit(res)
    return code


if __name__ == "__main__":
    sys.exit(main())
