"""cache.py — Content-addressable cache for per-component intent extracts.

Cache key = sha256(component_id + sorted(file_content_hashes) + extractor_version + model_id + template_hash).
Cache file at .wiring/intent-cache/<key>.yaml.
Per-run symlink at .wiring/runs/<run_id>/intent/<component_id>.yaml.

Eviction TTL: EVO_INTENT_CACHE_TTL_DAYS env, default 30.
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Iterable, Optional


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def content_hash(file_paths: Iterable[Path]) -> str:
    """Canonical content-hash over a set of source files.

    Sorts by absolute path (string), concatenates sha256s with newline separator,
    returns sha256 of the joined string. Deterministic across runs.
    """
    file_paths = sorted(file_paths, key=lambda p: str(p))
    hashes = []
    for p in file_paths:
        if not p.is_file():
            continue
        hashes.append(_file_sha256(p))
    canonical = "\n".join(hashes)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cache_key(
    component_id: str,
    sources_content_hash: str,
    extractor_version: str,
    model_id: str,
    template_hash: str,
) -> str:
    """Derive a stable cache key from the 5-tuple."""
    parts = [
        component_id,
        sources_content_hash,
        extractor_version,
        model_id,
        template_hash,
    ]
    canonical = "\x00".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cache_dir(project_root: Path) -> Path:
    return project_root / ".wiring" / "intent-cache"


def cache_path(project_root: Path, key: str) -> Path:
    return cache_dir(project_root) / f"{key}.yaml"


def per_run_dir(project_root: Path, run_id: str) -> Path:
    return project_root / ".wiring" / "runs" / run_id / "intent"


def per_run_symlink(project_root: Path, run_id: str, component_id: str) -> Path:
    return per_run_dir(project_root, run_id) / f"{component_id}.yaml"


def read_cache(project_root: Path, key: str) -> Optional[str]:
    """Read a cached intent file's raw bytes (string). Returns None if absent."""
    p = cache_path(project_root, key)
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8")


def write_cache(project_root: Path, key: str, content: str) -> Path:
    """Write intent content into the cache atomically."""
    cdir = cache_dir(project_root)
    cdir.mkdir(parents=True, exist_ok=True)
    out = cache_path(project_root, key)
    tmp = out.with_suffix(out.suffix + f".tmp.{os.getpid()}.{int(time.time() * 1e6)}")
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(out))
    return out


def link_per_run(
    project_root: Path,
    run_id: str,
    component_id: str,
    cache_file: Path,
) -> Path:
    """Create the per-run symlink pointing into the cache (hard-link on Linux for stability)."""
    target_dir = per_run_dir(project_root, run_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    link = per_run_symlink(project_root, run_id, component_id)
    if link.exists() or link.is_symlink():
        link.unlink()
    try:
        os.link(str(cache_file), str(link))
    except OSError:
        # Cross-device or other constraint → symlink fallback
        os.symlink(str(cache_file.resolve()), str(link))
    return link


def cache_ttl_days() -> int:
    raw = os.environ.get("EVO_INTENT_CACHE_TTL_DAYS", "30")
    try:
        n = int(raw)
    except ValueError:
        return 30
    if n < 1:
        return 30
    return n


def protected_keys_from_lock(lock_path: Path) -> set:
    """Return the set of cache keys (sha) referenced by a partition.lock.

    S048/code-comprehension (§12 C10): a content-addressed cache entry referenced
    by a CURRENT partition.lock must NEVER be evicted — otherwise a delete-and-rebuild
    of the render would have to cold-LLM-regen, and cold regen is not byte-stable.

    The lock stores component → {source_files, entry_points}. The cache key is a
    function of (component_id, content_hash, extractor_version, model_id,
    template_hash), which the lock does NOT record directly. So instead of trying to
    reconstruct keys, the orchestrator records the live cache keys it just wrote into
    the lock's optional `cache_keys` list. We read that list. Absent => empty set
    (no protection, legacy behavior preserved).
    """
    if not lock_path.is_file():
        return set()
    try:
        import json as _json
        data = _json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    keys = data.get("cache_keys")
    if isinstance(keys, list):
        return {str(k) for k in keys}
    # Backward/forward-compat: also accept per-component cache_key under components[].
    comps = data.get("components")
    out = set()
    if isinstance(comps, dict):
        for v in comps.values():
            if isinstance(v, dict) and v.get("cache_key"):
                out.add(str(v["cache_key"]))
    return out


def evict_stale(
    project_root: Path,
    now_ts: Optional[float] = None,
    protected_keys: Optional[set] = None,
) -> int:
    """Remove cache entries older than TTL. Returns count removed.

    `protected_keys` (a set of cache-key shas) are NEVER evicted regardless of age
    (§12 C10 never-evict for entries referenced by a current partition.lock). When
    None, the caller may pass the partition.lock-derived set via
    `protected_keys_from_lock`. Absent => no protection (legacy behavior).
    """
    cdir = cache_dir(project_root)
    if not cdir.is_dir():
        return 0
    if now_ts is None:
        now_ts = time.time()
    protected = protected_keys or set()
    horizon = now_ts - cache_ttl_days() * 86400
    removed = 0
    for entry in cdir.glob("*.yaml"):
        key = entry.stem  # filename is <key>.yaml
        if key in protected:
            continue
        try:
            if entry.stat().st_mtime < horizon:
                entry.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    return removed
