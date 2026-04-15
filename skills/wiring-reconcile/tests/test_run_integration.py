#!/usr/bin/env python3
"""Integration test: run.py end-to-end against a fabricated run dir.

Builds a fake project with:
- progress/contract-map.yaml (stub, for component id resolution)
- .wiring/runs/<run_id>/manifest.json
- .wiring/runs/<run_id>/static.jsonl
- .wiring/runs/<run_id>/asserted/agent-1.jsonl

Invokes run.py (--skip-heartbeat --skip-claim-check) and asserts:
- exit code 0
- snapshot.json exists
- validates against wiring-snapshot.v1
- transition request emitted
- edges come from both static AND asserted inputs
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from edge_identity import compute_edge_id  # noqa: E402

from jsonschema import Draft202012Validator

SKILL_ROOT = Path(__file__).resolve().parent.parent
SNAP_SCHEMA = json.loads(
    (SKILL_ROOT / "schemas" / "wiring-snapshot.v1.json").read_text(encoding="utf-8")
)
SNAP_VALIDATOR = Draft202012Validator(SNAP_SCHEMA)


def _make_edge(
    src="auth-service", src_sym="auth-service.go",
    dst="db", dst_sym="db.User.read",
    kind="calls",
    source="static_extract",
    extractor="fastapi",
    tree="e" * 40,
):
    return {
        "schema_version": "1.0.0",
        "edge_id": compute_edge_id(src, src_sym, dst, dst_sym, kind),
        "src_component": src,
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


def _build_project(td: Path, run_id: str):
    # contract-map.yaml stub
    (td / "progress").mkdir(parents=True)
    cm = (
        'schema_version: "1.0.0"\n'
        "revision: 1\n"
        "components:\n"
        "  - id: auth-service\n"
        "    source_paths: [src/auth/]\n"
        "  - id: db\n"
        "    source_paths: [src/db/]\n"
    )
    (td / "progress" / "contract-map.yaml").write_text(cm)

    run_dir = td / ".wiring" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "asserted").mkdir()

    manifest = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "workspace_tree_hash": "e" * 40,
        "project_dir": str(td),
        "started_at": "2026-04-14T12:00:00Z",
        "completed_at": "2026-04-14T12:01:00Z",
        "sources": [
            {
                "source_id": "wiring-extract-static.fastapi",
                "evidence_source": "static_extract",
                "status": "succeeded",
                "output_path": "static.jsonl",
                "edge_count": 2,
                "completed_at": "2026-04-14T12:01:00Z",
            },
        ],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))

    static_edges = [
        _make_edge(src_sym="auth-service.login"),
        _make_edge(src_sym="auth-service.logout"),
    ]
    (run_dir / "static.jsonl").write_text(
        "\n".join(json.dumps(e) for e in static_edges) + "\n"
    )

    asserted_edges = [
        _make_edge(
            src_sym="auth-service.validateToken",
            source="agent_asserted", extractor="bob-asserter",
        ),
    ]
    (run_dir / "asserted" / "bob-asserter.jsonl").write_text(
        "\n".join(json.dumps(e) for e in asserted_edges) + "\n"
    )
    return run_dir


class TestRunIntegration(unittest.TestCase):

    def test_end_to_end_run_produces_valid_snapshot(self):
        import run  # noqa: E402  — run.py as module (import after sys.path insert)

        with tempfile.TemporaryDirectory() as tdstr:
            td = Path(tdstr)
            run_id = "deadbeef-dead-beef-dead-beefdeadbeef"
            run_dir = _build_project(td, run_id)

            rc = run.main([
                "--project-dir", str(td),
                "--run-id", run_id,
                "--claim-uuid", "dummy-claim-uuid",
                "--skip-heartbeat",
                "--skip-claim-check",
                "--log-level", "WARNING",
            ])
            self.assertEqual(rc, 0, "run.py should exit 0")

            snap_path = run_dir / "snapshot.json"
            self.assertTrue(snap_path.is_file(), "snapshot.json not written")
            snap = json.loads(snap_path.read_text())
            errs = sorted(SNAP_VALIDATOR.iter_errors(snap), key=lambda e: list(e.path))
            if errs:
                msgs = "; ".join(f"{list(e.path)}: {e.message}" for e in errs[:3])
                self.fail(f"snapshot schema errors: {msgs}")

            self.assertEqual(snap["run_id"], run_id)
            self.assertGreaterEqual(len(snap["edges"]), 3)  # 2 static + 1 asserted
            sources_seen = set()
            for e in snap["edges"]:
                for ev in e["evidence"]:
                    sources_seen.add(ev["evidence_source"])
            self.assertIn("static_extract", sources_seen)
            self.assertIn("agent_asserted", sources_seen)

            # Transition request emitted
            req_path = td / ".ledger" / "requests" / "dummy-claim-uuid.request.yaml"
            self.assertTrue(req_path.is_file(), "transition request not emitted")


if __name__ == "__main__":
    unittest.main()
