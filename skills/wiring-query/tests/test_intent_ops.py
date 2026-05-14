"""Unit tests for intent_ops.py — wiring-query v1.1 ops (S032 WP-4)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import intent_ops  # noqa: E402


def _snapshot_with_intent(component_id: str = "auth",
                          function_class: str = "auth") -> dict:
    return {
        "schema_version": "1.1.0",
        "snapshot_id": "a" * 16,
        "components": [
            {
                "name": component_id,
                "inbound_edge_count": 5,
                "outbound_edge_count": 3,
                "intent": {
                    "function_class": function_class,
                    "one_line": "Validates auth tokens",
                    "confidence_level": "grounded",
                    "test_seed_count": 3,
                    "error_path_count": 2,
                    "evidence_edge_count": 8,
                },
            },
            {
                "name": "rbac",
                "inbound_edge_count": 1,
                "outbound_edge_count": 2,
                # No intent block — v1.0-shaped component in a v1.1 snapshot
            },
        ],
    }


def test_intent_of_found_with_intent() -> None:
    snap = _snapshot_with_intent("auth")
    r = intent_ops.intent_of(snap, "auth")
    assert r["component_id"] == "auth"
    assert r["found"] is True
    assert r["intent_present"] is True
    assert r["intent"]["function_class"] == "auth"
    assert r["edge_counts"]["inbound"] == 5
    assert r["edge_counts"]["outbound"] == 3


def test_intent_of_found_without_intent() -> None:
    snap = _snapshot_with_intent("auth")
    r = intent_ops.intent_of(snap, "rbac")
    assert r["found"] is True
    assert r["intent_present"] is False
    assert r["intent"] is None


def test_intent_of_not_found() -> None:
    snap = _snapshot_with_intent("auth")
    r = intent_ops.intent_of(snap, "nonexistent")
    assert r["found"] is False
    assert r["intent_present"] is False
    assert r["intent"] is None
    assert r["edge_counts"] == {"inbound": 0, "outbound": 0}


def test_intent_of_empty_snapshot() -> None:
    r = intent_ops.intent_of({}, "any")
    assert r["found"] is False
    assert r["intent_present"] is False


def test_intent_of_malformed_components_list() -> None:
    """Non-list components is treated as empty."""
    snap = {"components": "not a list"}
    r = intent_ops.intent_of(snap, "x")
    assert r["found"] is False


def _project_with_flows(tmp_path: Path, flows: list) -> Path:
    """Lay down a contract-map.yaml with the given flows."""
    (tmp_path / "progress").mkdir(parents=True, exist_ok=True)
    cm = {"schema_version": "1.0.0", "revision": 1, "flows": flows,
          "components": []}
    (tmp_path / "progress" / "contract-map.yaml").write_text(yaml.safe_dump(cm))
    return tmp_path


def test_flow_intent_happy_path(tmp_path: Path) -> None:
    project = _project_with_flows(tmp_path, [
        {"id": "FLOW-X", "path": ["auth", "rbac"]}
    ])
    snap = _snapshot_with_intent("auth")
    r = intent_ops.flow_intent(snap, "FLOW-X", project)
    assert r["flow_found"] is True
    assert len(r["components"]) == 2
    assert r["summary"]["components_total"] == 2
    assert r["summary"]["components_with_intent"] == 1
    assert r["summary"]["function_class_distribution"] == {"auth": 1}


def test_flow_intent_flow_missing(tmp_path: Path) -> None:
    project = _project_with_flows(tmp_path, [
        {"id": "FLOW-X", "path": ["a", "b"]}
    ])
    snap = _snapshot_with_intent("auth")
    r = intent_ops.flow_intent(snap, "FLOW-Z", project)
    assert r["flow_found"] is False
    assert r["components"] == []
    assert r["summary"]["components_total"] == 0


def test_flow_intent_all_components_have_intent(tmp_path: Path) -> None:
    project = _project_with_flows(tmp_path, [
        {"id": "FLOW-X", "path": ["auth", "rbac"]}
    ])
    snap = {
        "components": [
            {"name": "auth", "inbound_edge_count": 1, "outbound_edge_count": 1,
             "intent": {"function_class": "auth", "one_line": "x",
                        "confidence_level": "grounded"}},
            {"name": "rbac", "inbound_edge_count": 1, "outbound_edge_count": 1,
             "intent": {"function_class": "rbac", "one_line": "y",
                        "confidence_level": "grounded"}},
        ],
    }
    r = intent_ops.flow_intent(snap, "FLOW-X", project)
    assert r["summary"]["components_with_intent"] == 2
    assert r["summary"]["function_class_distribution"] == {"auth": 1, "rbac": 1}


def test_flow_intent_unknown_components_in_path(tmp_path: Path) -> None:
    project = _project_with_flows(tmp_path, [
        {"id": "FLOW-X", "path": ["auth", "ghost"]}
    ])
    snap = _snapshot_with_intent("auth")
    r = intent_ops.flow_intent(snap, "FLOW-X", project)
    assert len(r["components"]) == 2
    ghost_entry = next(c for c in r["components"] if c["component_id"] == "ghost")
    assert ghost_entry["intent_present"] is False


def test_flow_intent_no_contract_map(tmp_path: Path) -> None:
    """No contract-map.yaml → flow_found is False."""
    snap = _snapshot_with_intent("auth")
    r = intent_ops.flow_intent(snap, "FLOW-X", tmp_path)
    assert r["flow_found"] is False


def test_flow_intent_malformed_contract_map(tmp_path: Path) -> None:
    """Garbage contract-map → flow_found False, no crash."""
    (tmp_path / "progress").mkdir(parents=True)
    (tmp_path / "progress" / "contract-map.yaml").write_text(":\n[\n")
    snap = _snapshot_with_intent("auth")
    r = intent_ops.flow_intent(snap, "FLOW-X", tmp_path)
    assert r["flow_found"] is False


def test_flow_intent_empty_path(tmp_path: Path) -> None:
    project = _project_with_flows(tmp_path, [{"id": "FLOW-X", "path": []}])
    snap = _snapshot_with_intent("auth")
    r = intent_ops.flow_intent(snap, "FLOW-X", project)
    assert r["flow_found"] is True
    assert r["summary"]["components_total"] == 0
