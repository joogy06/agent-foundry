#!/usr/bin/env python3
"""make_fixture_snapshot.py — generate a deterministic fixture snapshot for tests.

Writes `.wiring/latest.json` under the given fixture dir with a small,
hand-designed set of edges spanning 4 components so both impact() and
subgraph_for_llm() have interesting behaviour to exercise.

The fixture graph (edges drawn logically):

  auth-service.validateToken -->calls--> auth-service.lookupSession
  auth-service.validateToken -->calls--> user-service.getUser
  user-service.getUser       -->reads_from--> db.users.select
  auth-service.lookupSession -->reads_from--> db.sessions.select
  audit-log.append           -->persists_to--> db.audit.insert
  auth-service.validateToken -->emits--> audit-log.append             (agent_asserted only, blocking_eligible=false)
  auth-service.deprecatedFn  -->calls--> user-service.legacyGet        (status=stale)
  ghost-service.x            -->calls--> ghost-service.y               (status=orphan, excluded)

Plus one suppressed edge for completeness.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent  # wiring-query skill root
SNAP_WRITER_DIR = ROOT.parent / "wiring-reconcile" / "scripts"
sys.path.insert(0, str(SNAP_WRITER_DIR))

from edge_identity import compute_edge_id  # type: ignore  # noqa: E402
from snapshot_writer import canonical_json, write_snapshot_atomic  # type: ignore  # noqa: E402


def _edge(src_c, src_s, dst_c, dst_s, kind, status="live",
           evidence_kinds=("static_extract",), extractor_id="fastapi",
           extractor_version="1.0.0"):
    eid = compute_edge_id(src_c, src_s, dst_c, dst_s, kind)
    evidence = []
    for ev_src in evidence_kinds:
        evidence.append({
            "evidence_source": ev_src,
            "extractor_id": extractor_id,
            "extractor_version": extractor_version,
            "last_seen_at": "2026-04-15T02:00:00Z",
            "workspace_tree_hash": "a" * 40,
        })
    blocking = any(e == "static_extract" for e in evidence_kinds)
    return {
        "edge_id": eid,
        "src_component": src_c,
        "src_symbol": src_s,
        "dst_component": dst_c,
        "dst_symbol": dst_s,
        "edge_kind": kind,
        "status": status,
        "blocking_eligible": blocking,
        "evidence": evidence,
    }


def build_snapshot(snapshot_generation: int = 1):
    edges = [
        _edge("auth-service", "auth-service.validateToken",
              "auth-service", "auth-service.lookupSession", "calls"),
        _edge("auth-service", "auth-service.validateToken",
              "user-service", "user-service.getUser", "calls"),
        _edge("user-service", "user-service.getUser",
              "db", "db.users.select", "reads_from",
              extractor_id="generic-treesitter"),
        _edge("auth-service", "auth-service.lookupSession",
              "db", "db.sessions.select", "reads_from",
              extractor_id="generic-treesitter"),
        _edge("audit-log", "audit-log.append",
              "db", "db.audit.insert", "persists_to",
              extractor_id="generic-treesitter"),
        _edge("auth-service", "auth-service.validateToken",
              "audit-log", "audit-log.append", "emits",
              evidence_kinds=("agent_asserted",),
              extractor_id="bob-assertion"),
        _edge("auth-service", "auth-service.deprecatedFn",
              "user-service", "user-service.legacyGet", "calls",
              status="stale"),
        _edge("ghost-service", "ghost-service.x",
              "ghost-service", "ghost-service.y", "calls",
              status="orphan"),
        _edge("suppressed-comp", "suppressed-comp.skip",
              "db", "db.writes", "persists_to",
              status="suppressed"),
    ]
    edges.sort(key=lambda e: e["edge_id"])

    # Compute snapshot_id
    snapshot_id_source = [
        {k: e[k] for k in sorted(e.keys())} for e in edges
    ]
    sid = hashlib.sha256(
        canonical_json(snapshot_id_source).encode("utf-8")
    ).hexdigest()[:16]

    return {
        "schema_version": "1.0.0",
        "snapshot_id": sid,
        "snapshot_generation": snapshot_generation,
        "run_id": "00000000-0000-0000-0000-000000000001",
        "workspace_tree_hash": "b" * 40,
        "contract_map_hash": "c" * 64,
        "contract_map_revision": 1,
        "generated_at": "2026-04-15T02:00:00Z",
        "generated_by": "wiring-reconcile@1.0.0",
        "source_statuses": {
            "wiring-extract-static.fastapi": {
                "status": "succeeded",
                "edge_count": 3,
                "last_seen_at": "2026-04-15T02:00:00Z",
            }
        },
        "edges": edges,
    }


def write_fixture(target_dir: Path, snapshot_generation: int = 1) -> Path:
    target_dir = Path(target_dir)
    wiring = target_dir / ".wiring"
    wiring.mkdir(parents=True, exist_ok=True)
    snap = build_snapshot(snapshot_generation)
    latest = wiring / "latest.json"
    write_snapshot_atomic(latest, snap)
    return latest


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else str(SCRIPT_DIR / "fixture-project")
    path = write_fixture(Path(out))
    print(f"fixture written: {path}")
