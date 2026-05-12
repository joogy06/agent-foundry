"""cache.py — split-TTL atomic-write cache for registry + vuln data.

Stdlib only. Layout: ~/.claude/state/dep-currency-cache/<class>/<ecosystem>/<package>.{json,etag}

Public API:
    Cache class (instantiate per CLI invocation)
        .get(class_, ecosystem, package) -> dict | None
        .put(class_, ecosystem, package, data)
        .etag_for(class_, ecosystem, package) -> str | None
        .set_etag(class_, ecosystem, package, etag)
        .invalidate(class_, ecosystem, package)

TTL split per references/cache-design.md:
    versions    -> 18h
    vulns       -> 2h
    deprecation -> 7d
    wrappers    -> 2h
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

CACHE_BASE = Path.home() / ".claude" / "state" / "dep-currency-cache"

# TTL in seconds
TTL = {
    "versions": 18 * 3600,
    "vulns": 2 * 3600,
    "deprecation": 7 * 24 * 3600,
    "wrappers": 2 * 3600,
}


def _sanitize(name: str) -> str:
    """Make a package name safe for use as a filename."""
    # Allow alnum, dash, underscore, dot. Replace others with single dash.
    out = []
    for ch in name:
        if ch.isalnum() or ch in "-_.":
            out.append(ch)
        else:
            out.append("-")
    s = "".join(out)
    return s[:200] or "unknown"


class Cache:
    """Stateful cache instance for a single CLI invocation."""

    def __init__(self, base: Optional[Path] = None, no_cache: bool = False,
                 ignore_ttl: bool = False) -> None:
        """
        Args:
            base: override the cache base dir (default ~/.claude/state/...)
            no_cache: if True, .get() always returns None (but .put() still writes)
            ignore_ttl: if True, .get() returns cached entries regardless of age
                        (used in offline/internal-only mode)
        """
        self.base = base or CACHE_BASE
        self.no_cache = no_cache
        self.ignore_ttl = ignore_ttl

    def _path(self, class_: str, ecosystem: str, package: str,
              suffix: str = "json") -> Path:
        return (self.base / class_ / ecosystem
                / f"{_sanitize(package)}.{suffix}")

    def get(self, class_: str, ecosystem: str, package: str) -> Optional[dict]:
        if self.no_cache:
            return None
        p = self._path(class_, ecosystem, package)
        if not p.is_file():
            return None
        try:
            age = time.time() - p.stat().st_mtime
        except OSError:
            return None
        ttl = TTL.get(class_, 3600)
        if not self.ignore_ttl and age > ttl:
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def put(self, class_: str, ecosystem: str, package: str,
            data: dict) -> None:
        p = self._path(class_, ecosystem, package)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + f".tmp.{os.getpid()}")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(str(tmp), str(p))
        except OSError:
            # Best-effort cache write; never raise to caller
            try:
                tmp.unlink()
            except OSError:
                pass

    def etag_for(self, class_: str, ecosystem: str,
                 package: str) -> Optional[str]:
        p = self._path(class_, ecosystem, package, suffix="etag")
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    def set_etag(self, class_: str, ecosystem: str, package: str,
                 etag: str) -> None:
        p = self._path(class_, ecosystem, package, suffix="etag")
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + f".tmp.{os.getpid()}")
        try:
            tmp.write_text(etag, encoding="utf-8")
            os.replace(str(tmp), str(p))
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass

    def invalidate(self, class_: str, ecosystem: str, package: str) -> None:
        for suffix in ("json", "etag"):
            p = self._path(class_, ecosystem, package, suffix=suffix)
            try:
                p.unlink()
            except OSError:
                pass

    def touch(self, class_: str, ecosystem: str, package: str) -> None:
        """Refresh mtime on 304 — keeps cache entry alive without re-downloading body."""
        p = self._path(class_, ecosystem, package)
        try:
            os.utime(str(p), None)
        except OSError:
            pass
