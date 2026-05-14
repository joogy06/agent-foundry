"""Unit tests for schema_validate.py — runtime validation of intent-extract output."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import schema_validate  # noqa: E402


_VALID_INTENT = {
    "schema_version": "1.0.0",
    "component_id": "auth-service",
    "workspace_tree_hash": "a" * 40,
    "content_hash": "b" * 64,
    "extractor_id": "intent-extract",
    "extractor_version": "1.0.0",
    "model_id": "claude-opus-4-7",
    "sampled_at": "2026-05-13T14:00:00Z",
    "template_hash": "c" * 64,
    "function_class": "auth",
    "entry_points": [{
        "kind": "http_route",
        "detail": "GET /healthz",
        "handler_symbol": "src/health.py:healthz",
        "evidence_edges": ["e1"],
    }],
    "inputs": [],
    "outputs": [],
    "side_effects": [],
    "flows_participated": [],
    "intent": {"one_line": "Health check endpoint.", "confidence_level": "interpretive"},
    "error_paths": [],
    "test_seeds": [],
    "unknowns": [],
    "determinism_class": "fresh_interpretive",
}


def test_schema_loads(tmp_path: Path) -> None:
    """load_schema finds the v1 schema in at least one candidate path."""
    schema = schema_validate.load_schema()
    assert schema["$id"].endswith("functional-intent.v1.json")


def test_validate_payload_passes_on_valid() -> None:
    ok, msg = schema_validate.validate_payload(_VALID_INTENT)
    assert ok, msg


def test_validate_payload_rejects_missing_required() -> None:
    bad = dict(_VALID_INTENT)
    del bad["function_class"]
    ok, msg = schema_validate.validate_payload(bad)
    assert ok is False
    assert "function_class" in msg


def test_validate_payload_rejects_wrong_enum() -> None:
    bad = dict(_VALID_INTENT)
    bad["function_class"] = "exotic"
    ok, msg = schema_validate.validate_payload(bad)
    assert ok is False


def test_validate_payload_rejects_extra_field() -> None:
    bad = dict(_VALID_INTENT)
    bad["sneaky"] = "yes"
    ok, msg = schema_validate.validate_payload(bad)
    assert ok is False


def test_validate_file_passes(tmp_path: Path) -> None:
    f = tmp_path / "intent.yaml"
    f.write_text(yaml.safe_dump(_VALID_INTENT))
    ok, msg = schema_validate.validate_file(f)
    assert ok, msg


def test_validate_file_missing_returns_error(tmp_path: Path) -> None:
    f = tmp_path / "nope.yaml"
    ok, msg = schema_validate.validate_file(f)
    assert ok is False
    assert "not found" in msg


def test_validate_file_malformed_yaml(tmp_path: Path) -> None:
    f = tmp_path / "bad.yaml"
    f.write_text(":\n:\n[")
    ok, msg = schema_validate.validate_file(f)
    assert ok is False


def test_validate_file_non_mapping_top_level(tmp_path: Path) -> None:
    f = tmp_path / "list.yaml"
    f.write_text("- a\n- b\n")
    ok, msg = schema_validate.validate_file(f)
    assert ok is False
    assert "mapping" in msg
