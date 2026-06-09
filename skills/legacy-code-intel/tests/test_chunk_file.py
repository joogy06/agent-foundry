"""test_chunk_file — pure-I/O chunker (forked from lineage). 0700 cache, format hint,
DoS caps, atomic writes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import chunk_file as cf  # noqa: E402


def test_cobol_fixture_single_chunk(payroll_path, store_base):
    cache = store_base / "cache"
    manifest = cf.chunk_file(payroll_path, "run-1", cache_root=cache)
    assert manifest["format_hint"] == "cobol"
    assert manifest["chunked"] is False
    assert manifest["chunk_count"] == 1
    assert manifest["line_count"] > 30


def test_cache_dir_is_0700(payroll_path, store_base):
    import os
    cache = store_base / "cache"
    manifest = cf.chunk_file(payroll_path, "run-2", cache_root=cache)
    sha = manifest["sha256"]
    d = cache / "run-2" / "files" / sha
    mode = os.stat(d).st_mode & 0o777
    assert mode == 0o700


def test_format_hint_detection(tmp_path):
    cases = {"x.cbl": "cobol", "x.cpy": "cobol", "x.dsx": "dsx", "x.sh": "etl",
             "x.sql": "etl", "x.py": "etl", "x.txt": "unknown"}
    for name, expected in cases.items():
        assert cf.detect_format_hint(Path(name)) == expected


def test_oversized_skip(tmp_path, store_base):
    big = tmp_path / "big.cbl"
    big.write_text("X\n" * 10, encoding="utf-8")
    cache = store_base / "cache"
    # force a 0 MB hard limit so even the tiny file is "oversized"
    manifest = cf.chunk_file(big, "run-3", hard_limit_mb=0, cache_root=cache)
    assert any(g["kind"] == "oversized_file" for g in manifest["gaps"])
    assert manifest["chunk_count"] == 0


def test_large_file_chunks_with_overlap(tmp_path, store_base):
    f = tmp_path / "large.cbl"
    f.write_text("\n".join(f"LINE-{i}" for i in range(5000)) + "\n", encoding="utf-8")
    cache = store_base / "cache"
    manifest = cf.chunk_file(f, "run-4", inline_limit_lines=1000, chunk_size_lines=2000,
                             overlap_lines=50, cache_root=cache)
    assert manifest["chunked"] is True
    assert manifest["chunk_count"] >= 3
