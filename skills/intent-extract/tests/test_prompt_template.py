"""Unit tests for prompt_template.py — locked template + hash + render."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import prompt_template  # noqa: E402


def test_template_file_exists() -> None:
    """templates/prompt-base.txt is on-disk."""
    assert prompt_template.template_path().is_file()


def test_template_hash_is_sha256_of_bytes() -> None:
    """template_hash() returns sha256 of file bytes."""
    expected = hashlib.sha256(prompt_template.template_path().read_bytes()).hexdigest()
    assert prompt_template.template_hash() == expected


def test_template_hash_64_hex() -> None:
    """sha256 hex digest is 64 chars."""
    h = prompt_template.template_hash()
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_render_substitutes_placeholders() -> None:
    """All four placeholders get replaced."""
    rendered = prompt_template.render(
        component_id="auth-service",
        source_paths_count=5,
        files_visible_count=3,
        static_edges_visible_count=12,
    )
    assert "auth-service" in rendered
    assert "5" in rendered
    assert "3" in rendered
    assert "12" in rendered
    # No remaining placeholders
    assert "{{" not in rendered


def test_render_idempotent() -> None:
    """Same inputs → same output."""
    r1 = prompt_template.render("x", 1, 1, 1)
    r2 = prompt_template.render("x", 1, 1, 1)
    assert r1 == r2


def test_build_context_payload_truncates_files() -> None:
    """file_contents capped at max_files."""
    contents = {f"file_{i}.py": f"content {i}" for i in range(50)}
    ctx = prompt_template.build_context_payload(
        "x", {"id": "x"}, ["a.py"], contents, [], max_files=10,
    )
    assert ctx["files_visible_count"] == 10
    assert len(ctx["file_contents"]) == 10


def test_build_context_payload_deterministic_sort() -> None:
    """Truncation is deterministic — alphabetical."""
    contents = {f"file_{i:02d}.py": f"c{i}" for i in range(30)}
    ctx = prompt_template.build_context_payload(
        "x", {"id": "x"}, [], contents, [], max_files=5,
    )
    keys = list(ctx["file_contents"].keys())
    assert keys == sorted(keys)
    assert keys == ["file_00.py", "file_01.py", "file_02.py", "file_03.py", "file_04.py"]


def test_build_context_payload_no_truncation_below_cap() -> None:
    """Few files → no truncation."""
    contents = {"a.py": "x", "b.py": "y"}
    ctx = prompt_template.build_context_payload(
        "x", {"id": "x"}, [], contents, [], max_files=30,
    )
    assert ctx["files_visible_count"] == 2


def test_build_context_payload_source_paths_sorted() -> None:
    """source_paths sorted in output."""
    ctx = prompt_template.build_context_payload(
        "x", {"id": "x"}, ["z.py", "a.py", "m.py"], {}, [],
    )
    assert ctx["source_paths"] == ["a.py", "m.py", "z.py"]


def test_template_mentions_required_enums() -> None:
    """Template body mentions all 4 closed enums (sanity check)."""
    text = prompt_template.template_path().read_text()
    assert "function_class" in text
    assert "entry_points" in text and ".kind" in text
    assert "side_effects" in text
    assert "error_paths" in text


def test_template_mentions_hard_rules() -> None:
    """Template includes the explicit must-have guards."""
    text = prompt_template.template_path().read_text()
    assert "evidence_edges" in text
    assert "interpretive" in text or "grounded" in text
    assert "unknowns" in text
