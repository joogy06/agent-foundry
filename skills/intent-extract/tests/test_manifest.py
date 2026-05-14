"""Unit tests for manifest.py — per-run intent-manifest.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import manifest  # noqa: E402


def test_empty_manifest_shape() -> None:
    m = manifest.empty_manifest("run-1")
    assert m["schema_version"] == "1.0.0"
    assert m["run_id"] == "run-1"
    assert m["extractor_id"] == "intent-extract"
    assert m["components"] == []
    assert m["summary"]["total"] == 0


def test_record_component_hit() -> None:
    m = manifest.empty_manifest("run-1")
    manifest.record_component(m, "auth", "hit",
                              cache_key="abc", output_path="/path/x.yaml")
    assert m["summary"]["total"] == 1
    assert m["summary"]["hit"] == 1
    assert m["components"][0]["component_id"] == "auth"
    assert m["components"][0]["status"] == "hit"


def test_record_component_regenerated_counts_llm() -> None:
    m = manifest.empty_manifest("run-1")
    manifest.record_component(m, "auth", "regenerated",
                              tokens_in=1000, tokens_out=200)
    assert m["summary"]["llm_calls"] == 1
    assert m["summary"]["tokens_in"] == 1000
    assert m["summary"]["tokens_out"] == 200


def test_record_component_failed_with_error() -> None:
    m = manifest.empty_manifest("run-1")
    manifest.record_component(m, "auth", "failed", error="LLM transient")
    assert m["summary"]["failed"] == 1
    assert m["components"][0]["error"] == "LLM transient"


def test_record_component_gap() -> None:
    m = manifest.empty_manifest("run-1")
    manifest.record_component(m, "missing", "gap")
    assert m["summary"]["gap"] == 1


def test_record_component_invalid_status_raises() -> None:
    m = manifest.empty_manifest("run-1")
    with pytest.raises(ValueError):
        manifest.record_component(m, "x", "wibble")


def test_multiple_components_accumulate() -> None:
    m = manifest.empty_manifest("run-1")
    manifest.record_component(m, "a", "hit")
    manifest.record_component(m, "b", "regenerated", tokens_in=500, tokens_out=100)
    manifest.record_component(m, "c", "failed", error="boom")
    assert m["summary"]["total"] == 3
    assert m["summary"]["hit"] == 1
    assert m["summary"]["regenerated"] == 1
    assert m["summary"]["failed"] == 1


def test_write_and_read_manifest_roundtrip(tmp_path: Path) -> None:
    m = manifest.empty_manifest("run-1")
    manifest.record_component(m, "auth", "hit")
    written = manifest.write_manifest(tmp_path, "run-1", m)
    assert written.exists()
    read = manifest.read_manifest(tmp_path, "run-1")
    assert read["run_id"] == "run-1"
    assert read["summary"]["hit"] == 1


def test_read_manifest_missing_returns_none(tmp_path: Path) -> None:
    assert manifest.read_manifest(tmp_path, "nonexistent") is None


def test_write_manifest_creates_dir(tmp_path: Path) -> None:
    m = manifest.empty_manifest("run-1")
    written = manifest.write_manifest(tmp_path, "run-1", m)
    assert written.parent.is_dir()


def test_write_manifest_atomic_no_tmp_leftover(tmp_path: Path) -> None:
    m = manifest.empty_manifest("run-1")
    manifest.write_manifest(tmp_path, "run-1", m)
    tmps = list(manifest.manifest_path(tmp_path, "run-1").parent.glob("*.tmp.*"))
    assert tmps == []
