"""Integration tests for run.py — full per-component pipeline with FakeBackend."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import llm_call  # noqa: E402
import run  # noqa: E402


def _seed_project(tmp_path: Path) -> Path:
    """Lay down a minimal project with contract-map + source + static.jsonl."""
    project = tmp_path
    # contract-map
    (project / "progress").mkdir(parents=True, exist_ok=True)
    cm = {
        "schema_version": "1.0.0",
        "revision": 1,
        "components": [
            {
                "id": "auth-service",
                "purpose": "Validates auth tokens",
                "source_paths": ["src/auth/*.py"],
                "inputs": [],
                "outputs": [],
                "dependencies": [],
                "callers": [],
                "callees": [],
                "integration_points": [],
                "success_criteria": ["validates tokens"],
                "test_scenarios": [],
                "flow_entry_point": False,
                "flow_terminal": False,
            }
        ],
    }
    (project / "progress" / "contract-map.yaml").write_text(yaml.safe_dump(cm))

    # source files
    (project / "src" / "auth").mkdir(parents=True, exist_ok=True)
    (project / "src" / "auth" / "routes.py").write_text(
        "# routes.py\n"
        "def verify(token):\n"
        "    return jwt.decode(token)\n"
    )
    (project / "src" / "auth" / "jwt.py").write_text(
        "# jwt.py\n"
        "def decode(t): return {'user': 'demo'}\n"
    )

    # static.jsonl
    static_dir = project / ".wiring" / "runs" / "test-run-1"
    static_dir.mkdir(parents=True, exist_ok=True)
    edges = [
        {
            "edge_id": "e1", "src_component": "auth-service",
            "src_symbol": "verify", "dst_component": "auth-service",
            "dst_symbol": "decode", "edge_kind": "calls",
            "callsite_refs": [{"path": "src/auth/routes.py", "line": 3}],
        }
    ]
    static_jsonl = static_dir / "static.jsonl"
    with static_jsonl.open("w") as fh:
        for e in edges:
            fh.write(json.dumps(e) + "\n")
    return project


_FAKE_INTENT_YAML = """
schema_version: "1.0.0"
component_id: auth-service
workspace_tree_hash: "0000000000000000000000000000000000000000"
content_hash: "0000000000000000000000000000000000000000000000000000000000000000"
extractor_id: intent-extract
extractor_version: "1.0.0"
model_id: claude-opus-4-7
sampled_at: "2026-05-13T14:00:00Z"
template_hash: "0000000000000000000000000000000000000000000000000000000000000000"
function_class: auth
entry_points:
  - kind: lib_api
    detail: "verify(token)"
    handler_symbol: "src/auth/routes.py:verify"
    evidence_edges: ["e1"]
inputs: []
outputs: []
side_effects: []
flows_participated: []
intent:
  one_line: "Validates auth tokens via jwt.decode."
  confidence_level: interpretive
error_paths: []
test_seeds: []
unknowns:
  - "Whether token expiry is checked"
determinism_class: fresh_interpretive
"""


def test_run_with_fake_backend_writes_cache_and_manifest(tmp_path: Path, monkeypatch) -> None:
    project = _seed_project(tmp_path)

    # Run with FakeBackend (no real LLM)
    argv = [
        "--project-root", str(project),
        "--run-id", "test-run-1",
        "--claim-uuid", "00000000-0000-0000-0000-000000000001",
        "--workspace-tree-hash", "0" * 40,
        "--components", "auth-service",
        "--backend", "fake",
        "--fake-yaml", _FAKE_INTENT_YAML,
        "--two-arm", "skip",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    assert rc == 0

    # Manifest written
    manifest_path = project / ".wiring" / "runs" / "test-run-1" / "intent-manifest.json"
    assert manifest_path.is_file()
    m = json.loads(manifest_path.read_text())
    assert m["run_id"] == "test-run-1"
    assert m["summary"]["regenerated"] == 1
    assert m["summary"]["hit"] == 0

    # Per-run symlink/hardlink exists
    intent_file = project / ".wiring" / "runs" / "test-run-1" / "intent" / "auth-service.yaml"
    assert intent_file.exists()

    # Transition request written
    req_dir = project / ".ledger" / "requests"
    assert req_dir.is_dir()
    requests = list(req_dir.glob("*.request.yaml"))
    assert len(requests) == 1
    req = yaml.safe_load(requests[0].read_text())
    assert req["target_stage"] == "INTENT_MAPPED"
    assert req["claim_uuid"] == "00000000-0000-0000-0000-000000000001"


def test_run_second_invocation_is_cache_hit(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    base_argv = [
        "--project-root", str(project),
        "--run-id", "test-run-1",
        "--claim-uuid", "00000000-0000-0000-0000-000000000001",
        "--workspace-tree-hash", "0" * 40,
        "--components", "auth-service",
        "--backend", "fake",
        "--fake-yaml", _FAKE_INTENT_YAML,
        "--two-arm", "skip",
        "--no-heartbeat",
    ]
    rc1 = run.main(base_argv)
    assert rc1 == 0

    # Run again — should hit cache
    rc2 = run.main([*base_argv, "--no-transition-request"])
    assert rc2 == 0

    manifest_path = project / ".wiring" / "runs" / "test-run-1" / "intent-manifest.json"
    m = json.loads(manifest_path.read_text())
    # Last run's manifest replaces — should be hit:1
    assert m["summary"]["hit"] == 1
    assert m["summary"]["regenerated"] == 0


def test_run_with_missing_component_records_gap(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    argv = [
        "--project-root", str(project),
        "--run-id", "test-run-1",
        "--claim-uuid", "00000000-0000-0000-0000-000000000001",
        "--workspace-tree-hash", "0" * 40,
        "--components", "auth-service,nonexistent-component",
        "--backend", "fake",
        "--fake-yaml", _FAKE_INTENT_YAML,
        "--two-arm", "skip",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    assert rc == 0
    manifest_path = project / ".wiring" / "runs" / "test-run-1" / "intent-manifest.json"
    m = json.loads(manifest_path.read_text())
    assert m["summary"]["regenerated"] == 1
    assert m["summary"]["gap"] == 1


def test_run_emits_transition_request(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    argv = [
        "--project-root", str(project),
        "--run-id", "test-run-1",
        "--claim-uuid", "abcdef00-1111-2222-3333-444444444444",
        "--workspace-tree-hash", "0" * 40,
        "--components", "auth-service",
        "--backend", "fake",
        "--fake-yaml", _FAKE_INTENT_YAML,
        "--two-arm", "skip",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    assert rc == 0
    reqs = list((project / ".ledger" / "requests").glob("*.request.yaml"))
    assert len(reqs) == 1
    req = yaml.safe_load(reqs[0].read_text())
    assert req["produced_by"] == "intent-extract"
    assert req["target_stage"] == "INTENT_MAPPED"
    assert req["run_id"] == "test-run-1"


def test_run_no_transition_request_flag_skips(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    argv = [
        "--project-root", str(project),
        "--run-id", "test-run-1",
        "--claim-uuid", "00000000-0000-0000-0000-000000000001",
        "--workspace-tree-hash", "0" * 40,
        "--components", "auth-service",
        "--backend", "fake",
        "--fake-yaml", _FAKE_INTENT_YAML,
        "--two-arm", "skip",
        "--no-heartbeat",
        "--no-transition-request",
    ]
    rc = run.main(argv)
    assert rc == 0
    reqs = list((project / ".ledger" / "requests").glob("*.request.yaml")) if (project / ".ledger" / "requests").is_dir() else []
    assert reqs == []


def test_run_missing_project_root_returns_3(tmp_path: Path) -> None:
    argv = [
        "--project-root", "/this/path/does/not/exist",
        "--run-id", "x",
        "--claim-uuid", "00000000-0000-0000-0000-000000000001",
        "--workspace-tree-hash", "0" * 40,
        "--components", "a",
        "--backend", "fake",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    assert rc == 3


def test_run_missing_contract_map_returns_3(tmp_path: Path) -> None:
    argv = [
        "--project-root", str(tmp_path),
        "--run-id", "x",
        "--claim-uuid", "00000000-0000-0000-0000-000000000001",
        "--workspace-tree-hash", "0" * 40,
        "--components", "a",
        "--backend", "fake",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    assert rc == 3


def test_run_schema_invalid_fake_yaml_records_failed(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    # FakeBackend returns garbage (missing required fields)
    argv = [
        "--project-root", str(project),
        "--run-id", "test-run-1",
        "--claim-uuid", "00000000-0000-0000-0000-000000000001",
        "--workspace-tree-hash", "0" * 40,
        "--components", "auth-service",
        "--backend", "fake",
        "--fake-yaml", "schema_version: \"1.0.0\"\nfunction_class: auth\n",  # missing many fields
        "--two-arm", "skip",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    # run.py returns 0 even on per-component failure (manifest records the gap)
    assert rc == 0
    manifest_path = project / ".wiring" / "runs" / "test-run-1" / "intent-manifest.json"
    m = json.loads(manifest_path.read_text())
    assert m["summary"]["failed"] >= 1
