"""Unit tests for cache.py — content-addressable caching of intent-extract output."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import cache  # noqa: E402


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return tmp_path


def test_content_hash_deterministic(tmp_path: Path) -> None:
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("hello\n")
    f2.write_text("world\n")
    h1 = cache.content_hash([f1, f2])
    h2 = cache.content_hash([f2, f1])  # different order
    assert h1 == h2, "content_hash must be order-independent"


def test_content_hash_changes_on_content_change(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("v1\n")
    h1 = cache.content_hash([f])
    f.write_text("v2\n")
    h2 = cache.content_hash([f])
    assert h1 != h2


def test_content_hash_skips_missing(tmp_path: Path) -> None:
    f = tmp_path / "exists.py"
    f.write_text("here\n")
    missing = tmp_path / "nope.py"
    # Should not raise; missing files silently dropped
    h = cache.content_hash([f, missing])
    h_only = cache.content_hash([f])
    assert h == h_only


def test_cache_key_components_change_invalidates(tmp_path: Path) -> None:
    base = cache.cache_key("auth", "hash1", "1.0.0", "claude-opus-4-7", "thash")
    diff_comp = cache.cache_key("rbac", "hash1", "1.0.0", "claude-opus-4-7", "thash")
    diff_hash = cache.cache_key("auth", "hashX", "1.0.0", "claude-opus-4-7", "thash")
    diff_ver = cache.cache_key("auth", "hash1", "1.0.1", "claude-opus-4-7", "thash")
    diff_model = cache.cache_key("auth", "hash1", "1.0.0", "claude-opus-4-8", "thash")
    diff_template = cache.cache_key("auth", "hash1", "1.0.0", "claude-opus-4-7", "tx")
    assert len({base, diff_comp, diff_hash, diff_ver, diff_model, diff_template}) == 6


def test_cache_path_layout(project_root: Path) -> None:
    p = cache.cache_path(project_root, "abc123")
    assert p == project_root / ".wiring" / "intent-cache" / "abc123.yaml"


def test_per_run_symlink_layout(project_root: Path) -> None:
    p = cache.per_run_symlink(project_root, "run-1", "auth-service")
    assert p == project_root / ".wiring" / "runs" / "run-1" / "intent" / "auth-service.yaml"


def test_read_cache_miss_returns_none(project_root: Path) -> None:
    assert cache.read_cache(project_root, "missing-key") is None


def test_write_then_read_cache_roundtrip(project_root: Path) -> None:
    content = "schema_version: \"1.0.0\"\ncomponent_id: x\n"
    written_to = cache.write_cache(project_root, "key-abc", content)
    assert written_to.exists()
    got = cache.read_cache(project_root, "key-abc")
    assert got == content


def test_write_cache_atomic_no_partial(project_root: Path) -> None:
    """Atomic rename — no .tmp files left behind on success."""
    cache.write_cache(project_root, "key-1", "data1\n")
    cdir = cache.cache_dir(project_root)
    tmps = list(cdir.glob("*.tmp.*"))
    assert tmps == [], f"unexpected tmp files: {tmps}"


def test_link_per_run_creates_link(project_root: Path) -> None:
    cf = cache.write_cache(project_root, "k", "content\n")
    link = cache.link_per_run(project_root, "run-1", "comp-a", cf)
    assert link.exists()
    assert link.read_text() == "content\n"


def test_link_per_run_replaces_existing(project_root: Path) -> None:
    cf1 = cache.write_cache(project_root, "k1", "old\n")
    cache.link_per_run(project_root, "run-1", "comp-a", cf1)
    cf2 = cache.write_cache(project_root, "k2", "new\n")
    link = cache.link_per_run(project_root, "run-1", "comp-a", cf2)
    assert link.read_text() == "new\n"


def test_cache_ttl_days_default() -> None:
    """When env unset, default is 30."""
    old = os.environ.pop("EVO_INTENT_CACHE_TTL_DAYS", None)
    try:
        assert cache.cache_ttl_days() == 30
    finally:
        if old is not None:
            os.environ["EVO_INTENT_CACHE_TTL_DAYS"] = old


def test_cache_ttl_days_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVO_INTENT_CACHE_TTL_DAYS", "7")
    assert cache.cache_ttl_days() == 7


def test_cache_ttl_days_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVO_INTENT_CACHE_TTL_DAYS", "not-a-number")
    assert cache.cache_ttl_days() == 30


def test_cache_ttl_days_negative_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVO_INTENT_CACHE_TTL_DAYS", "-1")
    assert cache.cache_ttl_days() == 30


def test_evict_stale_removes_old(project_root: Path) -> None:
    f1 = cache.write_cache(project_root, "fresh", "fresh\n")
    f2 = cache.write_cache(project_root, "stale", "stale\n")
    # Set f2 mtime to 60 days ago
    sixty_days_ago = time.time() - 60 * 86400
    os.utime(f2, (sixty_days_ago, sixty_days_ago))
    removed = cache.evict_stale(project_root)
    assert removed == 1
    assert f1.exists()
    assert not f2.exists()


def test_evict_stale_empty_dir_returns_zero(project_root: Path) -> None:
    assert cache.evict_stale(project_root) == 0


# --- §12 C10: never-evict entries referenced by a current partition.lock ---


def test_evict_stale_respects_protected_keys(project_root: Path) -> None:
    f_keep = cache.write_cache(project_root, "locked", "x\n")
    f_drop = cache.write_cache(project_root, "unlocked", "y\n")
    long_ago = time.time() - 90 * 86400
    os.utime(f_keep, (long_ago, long_ago))
    os.utime(f_drop, (long_ago, long_ago))
    # 'locked' is protected → only 'unlocked' is evicted despite both being stale
    removed = cache.evict_stale(project_root, protected_keys={"locked"})
    assert removed == 1
    assert f_keep.exists(), "a key referenced by partition.lock must NEVER be evicted"
    assert not f_drop.exists()


def test_protected_keys_from_lock_reads_cache_keys_list(tmp_path: Path) -> None:
    import json
    lock = tmp_path / "partition.lock"
    lock.write_text(json.dumps({
        "schema_version": "1.0.0",
        "cache_keys": ["aaa", "bbb"],
        "components": {"x": {"source_files": ["a.py"]}},
    }))
    keys = cache.protected_keys_from_lock(lock)
    assert keys == {"aaa", "bbb"}


def test_protected_keys_from_lock_absent_is_empty(tmp_path: Path) -> None:
    assert cache.protected_keys_from_lock(tmp_path / "nope.lock") == set()


def test_end_to_end_lock_protects_cache(project_root: Path) -> None:
    import json
    f_keep = cache.write_cache(project_root, "key-in-lock", "x\n")
    f_drop = cache.write_cache(project_root, "key-not-in-lock", "y\n")
    long_ago = time.time() - 90 * 86400
    os.utime(f_keep, (long_ago, long_ago))
    os.utime(f_drop, (long_ago, long_ago))
    lock = project_root / "partition.lock"
    lock.write_text(json.dumps({"cache_keys": ["key-in-lock"]}))
    protected = cache.protected_keys_from_lock(lock)
    removed = cache.evict_stale(project_root, protected_keys=protected)
    assert removed == 1
    assert f_keep.exists()
    assert not f_drop.exists()
