#!/usr/bin/env python3
"""edge_identity.py — deterministic edge_id derivation.

Per design 2026-04-14 §4.1.1:
    edge_id = first 16 hex of sha256(canonical_json(five_tuple))

Five-tuple: (src_component, src_symbol, dst_component, dst_symbol, edge_kind).

This module is the single source of truth for edge identity. It is imported by
wiring-extract-static (extractors + test harnesses) AND wiring-reconcile. No
other file computes edge_ids — this guarantees same-logical-edge-same-edge_id.
"""
from __future__ import annotations

import hashlib
import json


def canonical_json(obj) -> str:
    """Sort keys, no whitespace — bit-identical across all callers."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_edge_id(
    src_component: str,
    src_symbol: str,
    dst_component: str,
    dst_symbol: str,
    edge_kind: str,
) -> str:
    """Return the 16-hex-char edge_id for this five-tuple."""
    payload = {
        "src_component": src_component,
        "src_symbol": src_symbol,
        "dst_component": dst_component,
        "dst_symbol": dst_symbol,
        "edge_kind": edge_kind,
    }
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return digest[:16]


def edge_id_for(edge: dict) -> str:
    """Compute edge_id from an edge dict (tolerates extra keys)."""
    return compute_edge_id(
        edge["src_component"],
        edge["src_symbol"],
        edge["dst_component"],
        edge["dst_symbol"],
        edge["edge_kind"],
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 6:
        sys.stderr.write("usage: edge_identity.py src_component src_symbol dst_component dst_symbol edge_kind\n")
        sys.exit(2)
    print(compute_edge_id(*sys.argv[1:6]))
