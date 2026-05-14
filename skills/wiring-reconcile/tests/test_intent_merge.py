"""Unit tests for intent_merge.py — wiring-reconcile v1.1 extension (S032 WP-3)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import intent_merge  # noqa: E402


def _write_intent(path: Path, *, component_id: str = "auth-service",
                  function_class: str = "auth",
                  one_line: str = "Validates tokens",
                  confidence: str = "interpretive",
                  test_seeds: int = 2,
                  error_paths: int = 1,
                  evidence_edges: int = 3) -> None:
    """Write a functional-intent.v1 YAML to path."""
    data = {
        "schema_version": "1.0.0",
        "component_id": component_id,
        "workspace_tree_hash": "a" * 40,
        "content_hash": "b" * 64,
        "extractor_id": "intent-extract",
        "extractor_version": "1.0.0",
        "model_id": "claude-opus-4-7",
        "sampled_at": "2026-05-13T14:00:00Z",
        "template_hash": "c" * 64,
        "function_class": function_class,
        "entry_points": [{
            "kind": "http_route",
            "detail": "GET /x",
            "handler_symbol": "y:z",
            "evidence_edges": [f"e{i}" for i in range(evidence_edges)],
        }],
        "inputs": [],
        "outputs": [],
        "side_effects": [],
        "flows_participated": [],
        "intent": {
            "one_line": one_line,
            "confidence_level": confidence,
        },
        "error_paths": [
            {"condition": f"err {i}", "error_kind": "raises",
             "propagates_to": "caller", "evidence_edges": []}
            for i in range(error_paths)
        ],
        "test_seeds": [
            {"seed_id": f"S-{i:03d}", "scenario": "x", "given": "y",
             "when": "z", "then": "ok"}
            for i in range(test_seeds)
        ],
        "unknowns": [],
        "determinism_class": "fresh_interpretive",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))


def test_intent_dir_for_run_layout(tmp_path: Path) -> None:
    p = intent_merge.intent_dir_for_run(tmp_path, "run-1")
    assert p == tmp_path / ".wiring" / "runs" / "run-1" / "intent"


def test_discover_intent_files_empty(tmp_path: Path) -> None:
    files = intent_merge.discover_intent_files(tmp_path, "run-1")
    assert files == {}


def test_discover_intent_files_returns_components(tmp_path: Path) -> None:
    intent_dir = intent_merge.intent_dir_for_run(tmp_path, "run-1")
    _write_intent(intent_dir / "auth.yaml", component_id="auth")
    _write_intent(intent_dir / "rbac.yaml", component_id="rbac",
                  function_class="rbac")
    files = intent_merge.discover_intent_files(tmp_path, "run-1")
    assert set(files.keys()) == {"auth", "rbac"}


def test_load_intent_summary_basic(tmp_path: Path) -> None:
    f = tmp_path / "auth.yaml"
    _write_intent(f, component_id="auth", function_class="auth",
                  one_line="Validates JWTs", confidence="grounded",
                  test_seeds=3, error_paths=2, evidence_edges=5)
    s = intent_merge.load_intent_summary(f)
    assert s["function_class"] == "auth"
    assert s["one_line"] == "Validates JWTs"
    assert s["confidence_level"] == "grounded"
    assert s["test_seed_count"] == 3
    assert s["error_path_count"] == 2
    # 5 evidence edges in entry_points + 0 in error_paths
    assert s["evidence_edge_count"] == 5


def test_load_intent_summary_missing_file(tmp_path: Path) -> None:
    assert intent_merge.load_intent_summary(tmp_path / "nope.yaml") is None


def test_load_intent_summary_malformed_yaml(tmp_path: Path) -> None:
    f = tmp_path / "bad.yaml"
    f.write_text(":\n: ]\n[")
    assert intent_merge.load_intent_summary(f) is None


def test_load_intent_summary_missing_function_class(tmp_path: Path) -> None:
    f = tmp_path / "noclass.yaml"
    f.write_text(yaml.safe_dump({"intent": {"one_line": "x"}}))
    assert intent_merge.load_intent_summary(f) is None


def test_merge_into_snapshot_no_intent_files_passthrough(tmp_path: Path) -> None:
    """No intent files → snapshot unchanged."""
    snap = {
        "schema_version": "1.0.0",
        "components": [{"name": "auth", "inbound_edge_count": 5,
                        "outbound_edge_count": 3}],
    }
    out = intent_merge.merge_into_snapshot(snap, tmp_path, "run-x")
    assert out["schema_version"] == "1.0.0"  # not bumped
    assert "intent" not in out["components"][0]


def test_merge_into_snapshot_decorates_existing(tmp_path: Path) -> None:
    """Existing component gets intent block; schema_version bumps to 1.1.0."""
    intent_dir = intent_merge.intent_dir_for_run(tmp_path, "run-1")
    _write_intent(intent_dir / "auth.yaml", component_id="auth",
                  one_line="X")
    snap = {
        "schema_version": "1.0.0",
        "components": [{"name": "auth", "inbound_edge_count": 1,
                        "outbound_edge_count": 1}],
    }
    out = intent_merge.merge_into_snapshot(snap, tmp_path, "run-1")
    assert out["schema_version"] == "1.1.0"
    assert out["components"][0]["intent"]["one_line"] == "X"


def test_merge_adds_orphan_component(tmp_path: Path) -> None:
    """Intent file for a component not in edges → new entry added."""
    intent_dir = intent_merge.intent_dir_for_run(tmp_path, "run-1")
    _write_intent(intent_dir / "orphan.yaml", component_id="orphan")
    snap = {
        "schema_version": "1.0.0",
        "components": [{"name": "other", "inbound_edge_count": 1,
                        "outbound_edge_count": 1}],
    }
    out = intent_merge.merge_into_snapshot(snap, tmp_path, "run-1")
    names = [c["name"] for c in out["components"]]
    assert "orphan" in names
    orphan = next(c for c in out["components"] if c["name"] == "orphan")
    assert orphan["inbound_edge_count"] == 0
    assert orphan["outbound_edge_count"] == 0
    assert orphan["intent"]["function_class"] == "auth"


def test_merge_sorts_components_alphabetically(tmp_path: Path) -> None:
    """After merge, components are sorted by name."""
    intent_dir = intent_merge.intent_dir_for_run(tmp_path, "run-1")
    _write_intent(intent_dir / "zeta.yaml", component_id="zeta")
    _write_intent(intent_dir / "alpha.yaml", component_id="alpha")
    snap = {
        "schema_version": "1.0.0",
        "components": [],
    }
    out = intent_merge.merge_into_snapshot(snap, tmp_path, "run-1")
    names = [c["name"] for c in out["components"]]
    assert names == sorted(names)


def test_merge_preserves_edge_counts(tmp_path: Path) -> None:
    """Existing inbound/outbound counts are not clobbered."""
    intent_dir = intent_merge.intent_dir_for_run(tmp_path, "run-1")
    _write_intent(intent_dir / "auth.yaml", component_id="auth")
    snap = {
        "schema_version": "1.0.0",
        "components": [{"name": "auth", "inbound_edge_count": 42,
                        "outbound_edge_count": 17}],
    }
    out = intent_merge.merge_into_snapshot(snap, tmp_path, "run-1")
    auth = next(c for c in out["components"] if c["name"] == "auth")
    assert auth["inbound_edge_count"] == 42
    assert auth["outbound_edge_count"] == 17


def test_merge_partial_some_have_intent(tmp_path: Path) -> None:
    """Some components have intent, others don't → only matching ones get block."""
    intent_dir = intent_merge.intent_dir_for_run(tmp_path, "run-1")
    _write_intent(intent_dir / "auth.yaml", component_id="auth")
    snap = {
        "schema_version": "1.0.0",
        "components": [
            {"name": "auth", "inbound_edge_count": 1, "outbound_edge_count": 1},
            {"name": "rbac", "inbound_edge_count": 1, "outbound_edge_count": 1},
        ],
    }
    out = intent_merge.merge_into_snapshot(snap, tmp_path, "run-1")
    auth = next(c for c in out["components"] if c["name"] == "auth")
    rbac = next(c for c in out["components"] if c["name"] == "rbac")
    assert "intent" in auth
    assert "intent" not in rbac


def test_merge_v1_snapshot_backward_compat(tmp_path: Path) -> None:
    """Snapshot conforming to v1.0 (no intent block) validates against v1.1 schema."""
    schema_path = Path(__file__).resolve().parent.parent / "schemas" / "wiring-snapshot.v1.1.json"
    schema = json.loads(schema_path.read_text())
    v1_snap = {
        "schema_version": "1.0.0",
        "snapshot_id": "a" * 16,
        "snapshot_generation": 1,
        "run_id": "12345678-1234-1234-1234-123456789abc",
        "workspace_tree_hash": "b" * 40,
        "generated_at": "2026-05-13T14:00:00Z",
        "generated_by": "wiring-reconcile@1.0.0",
        "source_statuses": {},
        "edges": [],
        "components": [],
    }
    import jsonschema
    jsonschema.validate(v1_snap, schema)


def test_merge_intent_path_set(tmp_path: Path) -> None:
    """intent_path field is set to the source file path."""
    intent_dir = intent_merge.intent_dir_for_run(tmp_path, "run-1")
    intent_file = intent_dir / "auth.yaml"
    _write_intent(intent_file, component_id="auth")
    s = intent_merge.load_intent_summary(intent_file)
    assert "intent_path" in s
    assert "auth.yaml" in s["intent_path"]


def test_merge_extract_run_id_set(tmp_path: Path) -> None:
    """After merge, intent.extract_run_id matches the run id."""
    intent_dir = intent_merge.intent_dir_for_run(tmp_path, "evo-run-99")
    _write_intent(intent_dir / "auth.yaml", component_id="auth")
    snap = {"schema_version": "1.0.0",
            "components": [{"name": "auth", "inbound_edge_count": 0,
                            "outbound_edge_count": 0}]}
    out = intent_merge.merge_into_snapshot(snap, tmp_path, "evo-run-99")
    assert out["components"][0]["intent"]["extract_run_id"] == "evo-run-99"
