"""WP-3 — tests for intent-extract --standalone + --contract-map-path (code-comprehension).

These assert the CB4-critical properties:
  - --standalone needs NO claim
  - --standalone writes NO .ledger/requests/ (transition emission unreachable)
  - --standalone constructs NO heartbeat thread
  - --contract-map-path none => clean run; fallback to progress/ is NOT taken
  - --contract-map-path <PATH> resolves an explicit (e.g. synthetic) map
  - the NORMAL path is unchanged (claim still required without --standalone)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(TESTS_DIR))

import run  # noqa: E402

# Reuse the integration test's fixtures.
from test_run_integration import _seed_project, _FAKE_INTENT_YAML  # noqa: E402


def _standalone_argv(project: Path, cmp_path: str) -> list:
    return [
        "--project-root", str(project),
        "--run-id", "test-run-1",
        "--workspace-tree-hash", "0" * 40,
        "--components", "auth-service",
        "--backend", "fake",
        "--fake-yaml", _FAKE_INTENT_YAML,
        "--two-arm", "skip",
        "--standalone",
        "--contract-map-path", cmp_path,
    ]


def test_standalone_runs_without_claim(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    cmp_path = str(project / "progress" / "contract-map.yaml")
    rc = run.main(_standalone_argv(project, cmp_path))
    assert rc == 0
    # intent file produced
    intent_file = project / ".wiring" / "runs" / "test-run-1" / "intent" / "auth-service.yaml"
    assert intent_file.exists()


def test_standalone_writes_no_ledger_request(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    cmp_path = str(project / "progress" / "contract-map.yaml")
    rc = run.main(_standalone_argv(project, cmp_path))
    assert rc == 0
    # CB4: no transition request anywhere under .ledger/
    req_dir = project / ".ledger" / "requests"
    assert not req_dir.exists(), ".ledger/requests/ must not be created in --standalone"
    # And nothing under .ledger/ at all
    assert not (project / ".ledger").exists()


def test_standalone_never_constructs_heartbeat(tmp_path: Path, monkeypatch) -> None:
    """If --standalone constructs a HeartbeatThread, this test fails loudly."""
    project = _seed_project(tmp_path)
    constructed = {"n": 0}
    real_init = run.HeartbeatThread.__init__

    def spy_init(self, *a, **k):  # noqa: ANN001
        constructed["n"] += 1
        return real_init(self, *a, **k)

    monkeypatch.setattr(run.HeartbeatThread, "__init__", spy_init)
    cmp_path = str(project / "progress" / "contract-map.yaml")
    rc = run.main(_standalone_argv(project, cmp_path))
    assert rc == 0
    assert constructed["n"] == 0, "HeartbeatThread must NEVER be constructed in --standalone"


def test_standalone_missing_claim_is_fine_but_normal_requires_claim(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    # normal mode without --claim-uuid → ENV_ERROR (rc 3)
    argv = [
        "--project-root", str(project),
        "--run-id", "test-run-1",
        "--workspace-tree-hash", "0" * 40,
        "--components", "auth-service",
        "--backend", "fake",
        "--fake-yaml", _FAKE_INTENT_YAML,
        "--two-arm", "skip",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    assert rc == 3, "normal mode must still require --claim-uuid"


def test_contract_map_path_none_does_not_read_progress(tmp_path: Path) -> None:
    """--contract-map-path none must NOT fall back to progress/contract-map.yaml."""
    project = _seed_project(tmp_path)
    # 'none' → empty component set → the requested component is a 'gap', NOT resolved
    # from progress/. rc still 0 (gap is recorded, not a crash).
    argv = _standalone_argv(project, "none")
    rc = run.main(argv)
    assert rc == 0
    manifest_path = project / ".wiring" / "runs" / "test-run-1" / "intent-manifest.json"
    m = json.loads(manifest_path.read_text())
    # auth-service is NOT in the 'none' map → recorded as a gap (proves no progress/ fallback)
    assert m["summary"].get("gap", 0) == 1
    assert m["summary"].get("regenerated", 0) == 0


def test_contract_map_path_explicit_synthetic(tmp_path: Path) -> None:
    """A synthetic map at an explicit path resolves components (the code-comprehension flow)."""
    project = _seed_project(tmp_path)
    # write a synthetic map elsewhere (NOT under progress/)
    synthetic = project / ".comprehension" / "synthetic-contract-map.yaml"
    synthetic.parent.mkdir(parents=True, exist_ok=True)
    synthetic.write_text(yaml.safe_dump({
        "schema_version": "1.0.0",
        "components": [
            {"id": "auth-service", "source_paths": ["src/auth/*.py"]}
        ],
    }))
    argv = _standalone_argv(project, str(synthetic))
    rc = run.main(argv)
    assert rc == 0
    m = json.loads((project / ".wiring" / "runs" / "test-run-1" / "intent-manifest.json").read_text())
    assert m["summary"].get("regenerated", 0) == 1
