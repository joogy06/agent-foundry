#!/usr/bin/env python3
"""Every test fixture's reconcile output validates against wiring-snapshot.v1."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from reconciler import reconcile  # noqa: E402
from edge_identity import compute_edge_id  # noqa: E402


SCHEMA = json.loads((SKILL_ROOT / "schemas" / "wiring-snapshot.v1.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)


COMPONENTS = ["auth-service", "user-service", "db"]
TREE = "c" * 40


def _edge(src_sym="auth-service.f1", dst="db", dst_sym="db.User.get", kind="calls",
          source="static_extract", extractor="fastapi", tree=TREE):
    return {
        "schema_version": "1.0.0",
        "edge_id": compute_edge_id("auth-service", src_sym, dst, dst_sym, kind),
        "src_component": "auth-service",
        "src_symbol": src_sym,
        "dst_component": dst,
        "dst_symbol": dst_sym,
        "edge_kind": kind,
        "evidence_source": source,
        "extractor_id": extractor,
        "extractor_version": "1.0.0",
        "workspace_tree_hash": tree,
        "emitted_at": "2026-04-14T12:00:00Z",
    }


def _manifest(static_status="succeeded"):
    return {
        "schema_version": "1.0.0",
        "run_id": "00000000-0000-0000-0000-000000000000",
        "workspace_tree_hash": TREE,
        "project_dir": "/tmp",
        "started_at": "2026-04-14T12:00:00Z",
        "sources": [{
            "source_id": "wiring-extract-static.fastapi",
            "evidence_source": "static_extract",
            "status": static_status,
            "output_path": "static.jsonl",
            "edge_count": 2,
            "completed_at": "2026-04-14T12:01:00Z",
        }],
    }


def _reconcile(statics=(), asserteds=(), manuals=(), static_status="succeeded",
               components=COMPONENTS, tree=TREE):
    return reconcile(
        static_edges=list(statics),
        asserted_edges=list(asserteds),
        manual_edges=list(manuals),
        manifest=_manifest(static_status),
        contract_map_components=components,
        run_id="22222222-2222-2222-2222-222222222222",
        workspace_tree_hash=tree,
        generated_at="2026-04-14T12:02:00Z",
        snapshot_generation=1,
    )


def _assert_valid(snapshot):
    errs = sorted(VALIDATOR.iter_errors(snapshot), key=lambda e: list(e.path))
    if errs:
        raise AssertionError("; ".join(f"{list(e.path)}: {e.message}" for e in errs[:5]))


class TestSchemaConformance(unittest.TestCase):

    def test_empty(self):
        _assert_valid(_reconcile())

    def test_single_static(self):
        _assert_valid(_reconcile(statics=[_edge()]))

    def test_mixed_sources(self):
        s = _edge()
        a = _edge(source="agent_asserted", extractor="bob-challenger-1",
                  src_sym="auth-service.g2")
        m = _edge(source="manual", extractor="human",
                  src_sym="auth-service.g3")
        _assert_valid(_reconcile(statics=[s], asserteds=[a], manuals=[m]))

    def test_orphan_and_live(self):
        live = _edge(src_sym="auth-service.live")
        orphan = _edge(dst="ghost", dst_sym="ghost.x", src_sym="auth-service.o")
        _assert_valid(_reconcile(statics=[live, orphan]))

    def test_many_edges(self):
        es = [_edge(src_sym=f"auth-service.m{i}") for i in range(30)]
        _assert_valid(_reconcile(statics=es))


if __name__ == "__main__":
    unittest.main()
