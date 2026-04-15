#!/usr/bin/env python3
"""reconciler.py — pure merge algorithm producing a `wiring-snapshot.v1` dict.

Per design 2026-04-14 §5.2 lifecycle steps 3-7. Deterministic (sort by
edge_id before emitting; canonical JSON; round confidence to 2 decimals).

Public API:
    reconcile(
        static_edges,
        asserted_edges,
        manifest,
        contract_map_components,
        run_id,
        workspace_tree_hash,
        generated_at,
        snapshot_generation=None,        # provisional; bob re-writes on promote
        contract_map_hash=None,
        contract_map_revision=None,
        previous_snapshot=None,
        suppressed_edge_ids=None,
    ) -> dict

The returned dict conforms to `wiring-snapshot.v1`. Caller is responsible
for schema-validating before writing. `snapshot_id` is computed exactly as
the design specifies: first 16 hex of sha256(canonical_json(edges sorted by
edge_id, projected to the identity + evidence-shape keys)).

This module has ZERO file I/O. It takes in-memory edge dicts and returns a
dict. `run.py` orchestrates I/O.

Promotion rules (from spec):
- P1: static + agent -> evidence merged; confidence from static (≥0.9)
- P2: agent + trace  -> promoted; confidence = max(agent, trace)   [trace deferred to v2]
- P3: static + trace -> confidence 1.0                             [trace deferred to v2]
- P4: manual       -> acts like an assertion with confidence 0.8

For v1, `trace`-sourced evidence never enters this code path because
`wiring-extract-runtime` is deferred to v2. The `evidence_source` enum in
the schema permits only {static_extract, agent_asserted, manual}.

Drift canary: ALDEBARAN-7 (do not paraphrase; do not add v2 code paths
behind feature flags — code paths that cannot be tested are code paths
that rot).
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from edge_identity import compute_edge_id, edge_id_for
from snapshot_writer import canonical_json

# ---------------------------------------------------------------------------
# Default confidences per evidence_source per spec §5.2 P1/P4
# ---------------------------------------------------------------------------

DEFAULT_STATIC_CONFIDENCE = 0.9   # static_extract default if extractor did not supply one
DEFAULT_AGENT_CONFIDENCE = 0.6    # agent_asserted default
DEFAULT_MANUAL_CONFIDENCE = 0.8   # manual default (operates like a trusted assertion)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _round2(x: float) -> float:
    # stable 2-decimal rounding for determinism
    return float(f"{float(x):.2f}")


def _resolve_edge_id(edge: Dict[str, Any]) -> str:
    """Return edge_id from the edge, computing it if missing."""
    eid = edge.get("edge_id")
    if eid:
        return eid
    return edge_id_for(edge)


def _default_confidence(ev_source: str, supplied: Optional[float]) -> float:
    if supplied is not None:
        return _round2(supplied)
    if ev_source == "static_extract":
        return _round2(DEFAULT_STATIC_CONFIDENCE)
    if ev_source == "manual":
        return _round2(DEFAULT_MANUAL_CONFIDENCE)
    return _round2(DEFAULT_AGENT_CONFIDENCE)


def _evidence_entry(edge: Dict[str, Any]) -> Dict[str, Any]:
    """Project an input edge into one `evidence[]` entry."""
    entry: Dict[str, Any] = {
        "evidence_source": edge["evidence_source"],
        "extractor_id": edge["extractor_id"],
        "extractor_version": edge.get("extractor_version", "1.0.0"),
        "last_seen_at": edge["emitted_at"],
        "workspace_tree_hash": edge["workspace_tree_hash"],
    }
    entry["confidence"] = _default_confidence(
        edge["evidence_source"], edge.get("confidence")
    )
    return entry


def _callsite(edge: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cs = edge.get("callsite_ref")
    if not cs:
        return None
    # canonicalize: strip None keys
    return {k: v for k, v in cs.items() if v is not None}


def _callsites_key(cs: Dict[str, Any]) -> Tuple:
    return (cs.get("file"), cs.get("line"), cs.get("column"))


# ---------------------------------------------------------------------------
# Core reconcile
# ---------------------------------------------------------------------------


def reconcile(
    static_edges: Iterable[Dict[str, Any]],
    asserted_edges: Iterable[Dict[str, Any]],
    manifest: Dict[str, Any],
    contract_map_components: Iterable[str],
    run_id: str,
    workspace_tree_hash: str,
    generated_at: str,
    snapshot_generation: int = 1,
    contract_map_hash: Optional[str] = None,
    contract_map_revision: Optional[int] = None,
    previous_snapshot: Optional[Dict[str, Any]] = None,
    suppressed_edge_ids: Optional[Iterable[str]] = None,
    manual_edges: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Pure reconcile. Returns a dict shaped as `wiring-snapshot.v1`.

    `manifest` is the run manifest (wiring-source-manifest.v1 dict) — used to
    derive `source_statuses`.
    `contract_map_components` is an iterable of known component ids — used
    for the orphan check.
    `previous_snapshot` may be supplied for the staleness comparison; when
    None, staleness degrades to "evidence with older tree hash than current".
    """
    components_set: Set[str] = set(contract_map_components or [])
    suppressed: Set[str] = set(suppressed_edge_ids or [])
    prev_edges_by_id: Dict[str, Dict[str, Any]] = {}
    if previous_snapshot and isinstance(previous_snapshot.get("edges"), list):
        for e in previous_snapshot["edges"]:
            eid = e.get("edge_id")
            if eid:
                prev_edges_by_id[eid] = e

    # --- Group incoming edges by edge_id ---
    groups: Dict[str, List[Dict[str, Any]]] = {}

    def _ingest(edges_iter: Iterable[Dict[str, Any]]) -> None:
        for edge in edges_iter:
            if not isinstance(edge, dict):
                continue
            eid = _resolve_edge_id(edge)
            groups.setdefault(eid, []).append(edge)

    _ingest(static_edges)
    _ingest(asserted_edges)
    if manual_edges:
        _ingest(manual_edges)

    # --- source_statuses derived from manifest ---
    source_statuses: Dict[str, Dict[str, Any]] = {}
    static_status = "skipped"
    for src in manifest.get("sources", []) or []:
        sid = src.get("source_id")
        if not sid:
            continue
        source_statuses[sid] = {
            "status": src.get("status", "skipped"),
            "edge_count": int(src.get("edge_count", 0) or 0),
            "last_seen_at": src.get("completed_at")
            or src.get("started_at")
            or generated_at,
        }
        # Track overall static status (any source whose evidence_source is
        # static_extract counts; take the "best" — succeeded > partial > failed > skipped).
        if src.get("evidence_source") == "static_extract":
            rank = {"succeeded": 3, "partial": 2, "failed": 1, "skipped": 0}
            if rank.get(src.get("status", "skipped"), 0) > rank.get(static_status, 0):
                static_status = src.get("status", "skipped")

    # --- Build edges list ---
    out_edges: List[Dict[str, Any]] = []
    for eid, raws in groups.items():
        head = raws[0]

        # Merge evidence (dedupe by (evidence_source, extractor_id,
        # extractor_version, workspace_tree_hash) — same corroboration from
        # same extractor in same tree state should only count once).
        evidence: List[Dict[str, Any]] = []
        seen_ev = set()
        for raw in raws:
            ev = _evidence_entry(raw)
            key = (
                ev["evidence_source"],
                ev["extractor_id"],
                ev["extractor_version"],
                ev["workspace_tree_hash"],
            )
            if key in seen_ev:
                # Update to latest last_seen_at, keep max confidence
                for existing in evidence:
                    if (
                        existing["evidence_source"],
                        existing["extractor_id"],
                        existing["extractor_version"],
                        existing["workspace_tree_hash"],
                    ) == key:
                        if ev["last_seen_at"] > existing["last_seen_at"]:
                            existing["last_seen_at"] = ev["last_seen_at"]
                        if ev["confidence"] > existing["confidence"]:
                            existing["confidence"] = ev["confidence"]
                        break
                continue
            seen_ev.add(key)
            evidence.append(ev)

        # Sort evidence deterministically by (evidence_source, extractor_id, ...)
        evidence.sort(key=lambda e: (
            e["evidence_source"], e["extractor_id"],
            e["extractor_version"], e["workspace_tree_hash"],
        ))

        # Merge callsite_refs (dedupe by file/line/column)
        callsites: List[Dict[str, Any]] = []
        seen_cs: Set[Tuple] = set()
        for raw in raws:
            cs = _callsite(raw)
            if not cs:
                continue
            k = _callsites_key(cs)
            if k not in seen_cs:
                seen_cs.add(k)
                callsites.append(cs)
        callsites.sort(key=lambda c: (c.get("file") or "", c.get("line") or 0, c.get("column") or 0))

        # last_seen_by_source (for fast G4 queries)
        last_seen_by_source: Dict[str, str] = {}
        for ev in evidence:
            src = ev["evidence_source"]
            ts = ev["last_seen_at"]
            if src not in last_seen_by_source or ts > last_seen_by_source[src]:
                last_seen_by_source[src] = ts

        # blocking_eligible: >=1 static_extract evidence AND manifest static status in {succeeded, partial}
        has_static = any(ev["evidence_source"] == "static_extract" for ev in evidence)
        blocking_eligible = bool(has_static and static_status in ("succeeded", "partial"))

        # Status: live | stale | orphan | suppressed
        status = _determine_status(
            eid=eid,
            src_component=head["src_component"],
            dst_component=head["dst_component"],
            components_set=components_set,
            evidence=evidence,
            workspace_tree_hash=workspace_tree_hash,
            prev_edges_by_id=prev_edges_by_id,
            suppressed=suppressed,
        )

        edge_out: Dict[str, Any] = {
            "edge_id": eid,
            "src_component": head["src_component"],
            "src_symbol": head["src_symbol"],
            "dst_component": head["dst_component"],
            "dst_symbol": head["dst_symbol"],
            "edge_kind": head["edge_kind"],
            "status": status,
            "blocking_eligible": blocking_eligible,
            "evidence": evidence,
        }
        if callsites:
            edge_out["callsite_refs"] = callsites
        if last_seen_by_source:
            edge_out["last_seen_by_source"] = last_seen_by_source
        out_edges.append(edge_out)

    # Determinism: sort by edge_id.
    out_edges.sort(key=lambda e: e["edge_id"])

    # --- components[] aggregation ---
    comp_counts: Dict[str, Dict[str, int]] = {}
    for e in out_edges:
        for role, side in (("outbound", e["src_component"]), ("inbound", e["dst_component"])):
            slot = comp_counts.setdefault(side, {"inbound_edge_count": 0, "outbound_edge_count": 0})
            slot[f"{role}_edge_count"] += 1
    components_out = [
        {"name": name, **counts} for name, counts in sorted(comp_counts.items())
    ]

    # --- statistics ---
    total = len(out_edges)
    live = sum(1 for e in out_edges if e["status"] == "live")
    stale = sum(1 for e in out_edges if e["status"] == "stale")
    orphan = sum(1 for e in out_edges if e["status"] == "orphan")
    blocking = sum(1 for e in out_edges if e["blocking_eligible"])
    agent_only = sum(
        1 for e in out_edges
        if not any(ev["evidence_source"] == "static_extract" for ev in e["evidence"])
    )
    by_source: Dict[str, int] = {}
    for e in out_edges:
        for ev in e["evidence"]:
            by_source[ev["evidence_source"]] = by_source.get(ev["evidence_source"], 0) + 1
    stats = {
        "total_edges": total,
        "live_edges": live,
        "stale_edges": stale,
        "orphan_edges": orphan,
        "blocking_eligible_edges": blocking,
        "agent_only_edges": agent_only,
        "by_evidence_source": by_source,
    }

    # --- snapshot_id: sha256 over canonical edges list projected to identity + evidence shape ---
    projected = [
        {
            "edge_id": e["edge_id"],
            "src_component": e["src_component"],
            "src_symbol": e["src_symbol"],
            "dst_component": e["dst_component"],
            "dst_symbol": e["dst_symbol"],
            "edge_kind": e["edge_kind"],
            "status": e["status"],
            "blocking_eligible": e["blocking_eligible"],
            "evidence": e["evidence"],
        }
        for e in out_edges
    ]
    snapshot_id = hashlib.sha256(canonical_json(projected).encode("utf-8")).hexdigest()[:16]

    # --- Assemble final snapshot dict ---
    snapshot: Dict[str, Any] = {
        "schema_version": "1.0.0",
        "snapshot_id": snapshot_id,
        "snapshot_generation": int(snapshot_generation),
        "run_id": run_id,
        "workspace_tree_hash": workspace_tree_hash,
        "generated_at": generated_at,
        "generated_by": "wiring-reconcile@1.0.0",
        "source_statuses": source_statuses,
        "edges": out_edges,
        "components": components_out,
        "statistics": stats,
    }
    if contract_map_hash is not None:
        snapshot["contract_map_hash"] = contract_map_hash
    if contract_map_revision is not None:
        snapshot["contract_map_revision"] = int(contract_map_revision)
    return snapshot


def _determine_status(
    *,
    eid: str,
    src_component: str,
    dst_component: str,
    components_set: Set[str],
    evidence: List[Dict[str, Any]],
    workspace_tree_hash: str,
    prev_edges_by_id: Dict[str, Dict[str, Any]],
    suppressed: Set[str],
) -> str:
    """Status determination per spec §5.2 step 4."""
    if eid in suppressed:
        return "suppressed"
    # Orphan: one of the endpoints no longer maps to a known component.
    if components_set:
        if src_component not in components_set or dst_component not in components_set:
            return "orphan"
    # Current tree evidence = live; all old = stale
    any_current = any(
        ev.get("workspace_tree_hash") == workspace_tree_hash for ev in evidence
    )
    if any_current:
        return "live"
    # Comparison against previous snapshot: if we saw this edge before in a
    # different tree, mark stale. If we've never seen it at all, still stale
    # (no current corroboration).
    return "stale"
