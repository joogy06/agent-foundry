#!/usr/bin/env python3
"""g4_fixture.py — build a synthetic project_dir for G4 tests.

Produces:
  <tmpdir>/
    progress/contract-map.yaml   (minimal, with 2 components: auth, user)
    progress/integration-ledger.md
    .forge/session.key, session-id
    .wiring/latest.json          (signed via promote pattern)
    .wiring/.promote.lock
    (optionally) .ledger/config.yaml

Snapshot edges are parametric so individual rule tests can inject the shape they need.

Drift canary: ALDEBARAN-7.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Reuse bob #3's canonical_json + edge_id
SCRIPT_DIR = Path(__file__).resolve().parent
RECONCILE_SCRIPTS = SCRIPT_DIR.parent.parent / "wiring-reconcile" / "scripts"
sys.path.insert(0, str(RECONCILE_SCRIPTS))
from edge_identity import compute_edge_id  # type: ignore  # noqa: E402
from snapshot_writer import canonical_json, write_snapshot_atomic  # type: ignore  # noqa: E402


SIGNED_FIELDS = [
    "contract_map_hash",
    "contract_map_revision",
    "forge_session_id",
    "snapshot_id",
    "snapshot_generation",
    "signed_at",
]


def make_edge(src_c, src_s, dst_c, dst_s, kind="calls", status="live",
              evidence_kinds=("static_extract",),
              extractor_id="fastapi", extractor_version="1.0.0"):
    eid = compute_edge_id(src_c, src_s, dst_c, dst_s, kind)
    tree_hash = "a" * 40
    evidence = [
        {
            "evidence_source": ev,
            "extractor_id": extractor_id,
            "extractor_version": extractor_version,
            "last_seen_at": "2026-04-15T02:00:00Z",
            "workspace_tree_hash": tree_hash,
        }
        for ev in evidence_kinds
    ]
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


def _git_init(path: Path):
    env = {"GIT_AUTHOR_NAME": "g4", "GIT_AUTHOR_EMAIL": "g4@test",
           "GIT_COMMITTER_NAME": "g4", "GIT_COMMITTER_EMAIL": "g4@test",
           "HOME": str(path), "PATH": __import__("os").environ.get("PATH", "")}
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "g4@test"],
                   check=True, env=env)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "g4"],
                   check=True, env=env)


def build_project(tmpdir: Path, edges=None, snapshot_tree_hash=None,
                   generated_at=None, sign=True, bad_signature=False,
                   components=("auth-service", "user-service"),
                   config_stale_file_budget=None,
                   include_ledger=True):
    tmpdir = Path(tmpdir)
    (tmpdir / "progress").mkdir(parents=True, exist_ok=True)
    (tmpdir / ".forge").mkdir(parents=True, exist_ok=True)
    (tmpdir / ".wiring").mkdir(parents=True, exist_ok=True)

    # Minimal contract map with N components matching `components` arg
    comps = [
        {"id": c, "source_paths": [f"src/{c}/"]}
        for c in components
    ]
    map_yaml = {
        "schema_version": "1.0.0",
        "revision": 1,
        "components": comps,
    }
    # YAML dump minimal — use json (valid yaml) to keep deterministic
    map_bytes = json.dumps(map_yaml, sort_keys=True).encode("utf-8")
    (tmpdir / "progress" / "contract-map.yaml").write_bytes(map_bytes)

    # Session key + id
    session_key = b"g4-test-key-" + b"\x00" * 20
    (tmpdir / ".forge" / "session.key").write_bytes(session_key)
    (tmpdir / ".forge" / "session.key").chmod(0o600)
    session_id = "g4-session-00000000-0000-0000-0000-000000000042"
    (tmpdir / ".forge" / "session-id").write_text(session_id)

    # Ledger
    if include_ledger:
        map_hash = hashlib.sha256(map_bytes).hexdigest()
        ledger = (
            "---\n"
            "schema_version: 1\n"
            f"contract_map_hash: {map_hash}\n"
            "contract_map_revision: 1\n"
            f"forge_session_id: {session_id}\n"
            "frozen_at: 2026-04-15T00:00:00Z\n"
            "writer: bob\n"
            "drift_canary: ALDEBARAN-7\n"
            "pause_epoch: 0\n"
            "---\n"
            "# Ledger\n"
        )
        (tmpdir / "progress" / "integration-ledger.md").write_text(ledger)

    # Git init so write-tree works
    _git_init(tmpdir)
    # Add + commit the current state so write-tree produces a stable hash.
    subprocess.run(["git", "-C", str(tmpdir), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(tmpdir), "commit", "-q", "-m", "init"],
        check=True,
    )
    cur_tree = subprocess.run(
        ["git", "-C", str(tmpdir), "write-tree"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    # Build snapshot
    if edges is None:
        edges = [
            make_edge("auth-service", "auth-service.x",
                      "user-service", "user-service.y", "calls"),
        ]
    edges = sorted(edges, key=lambda e: e["edge_id"])
    snap_tree = snapshot_tree_hash or cur_tree
    generated_at = generated_at or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    snapshot_id_src = [{k: e[k] for k in sorted(e.keys())} for e in edges]
    sid = hashlib.sha256(
        canonical_json(snapshot_id_src).encode("utf-8")
    ).hexdigest()[:16]
    snap = {
        "schema_version": "1.0.0",
        "snapshot_id": sid,
        "snapshot_generation": 1,
        "run_id": "00000000-0000-0000-0000-000000000001",
        "workspace_tree_hash": snap_tree,
        "contract_map_hash": hashlib.sha256(map_bytes).hexdigest(),
        "contract_map_revision": 1,
        "generated_at": generated_at,
        "generated_by": "wiring-reconcile@1.0.0",
        "source_statuses": {},
        "edges": edges,
    }
    if sign:
        signed_at = generated_at
        payload = {
            "contract_map_hash": snap["contract_map_hash"],
            "contract_map_revision": 1,
            "forge_session_id": session_id,
            "snapshot_id": snap["snapshot_id"],
            "snapshot_generation": 1,
            "signed_at": signed_at,
        }
        if bad_signature:
            digest = "f" * 64
        else:
            digest = hmac.new(
                session_key, canonical_json(payload).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        snap["signature"] = {
            "algorithm": "HMAC-SHA256",
            "key_id": f"forge-session-{session_id}",
            "signed_at": signed_at,
            "signed_fields": list(SIGNED_FIELDS),
            "digest": digest,
        }
    write_snapshot_atomic(tmpdir / ".wiring" / "latest.json", snap)

    if config_stale_file_budget is not None:
        (tmpdir / ".ledger").mkdir(parents=True, exist_ok=True)
        (tmpdir / ".ledger" / "config.yaml").write_text(
            f"g4:\n  stale_file_budget: {config_stale_file_budget}\n"
        )

    return {"project_dir": tmpdir, "session_key": session_key,
            "session_id": session_id, "cur_tree": cur_tree,
            "snap_tree": snap_tree}
