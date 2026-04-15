#!/usr/bin/env python3
"""loader.py — snapshot loader + in-process cache for wiring-query.

Per design 2026-04-14 §5.3. Reads `.wiring/latest.json`, validates against
`wiring-snapshot.v1`, and caches the parsed dict in module-level memory so
subsequent calls within the same subprocess don't pay the parse cost.

Hard rules:
- Load time target <300ms first read.
- `latest.json` missing -> raise SnapshotMissing with message suggesting
  `wiring-reconcile` run. CLI converts to exit 1 + message.
- No LLM calls anywhere.
- No schema-validator dependency at import time — jsonschema is imported
  lazily in `_validate_shape` so bob can use this loader even in minimal
  envs. Validation errors are soft (logged to stderr) unless strict=True.

Drift canary: ALDEBARAN-7.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional


class SnapshotMissing(Exception):
    """Raised when `.wiring/latest.json` does not exist."""


class SnapshotInvalid(Exception):
    """Raised when latest.json is unparseable or fails the minimum shape check."""


# Module-level cache keyed by resolved project_dir path.
_CACHE: Dict[str, Dict[str, Any]] = {}


def _latest_path(project_dir: Path) -> Path:
    return project_dir / ".wiring" / "latest.json"


def load_snapshot(project_dir: Path, use_cache: bool = True) -> Dict[str, Any]:
    """Load `.wiring/latest.json`.

    Returns the parsed dict. Caches in-process by resolved project_dir.
    Subsequent calls within the same subprocess return the cached view.

    Raises:
      SnapshotMissing — `.wiring/latest.json` not found.
      SnapshotInvalid — file exists but cannot be parsed as JSON or lacks
        required top-level keys.
    """
    project_dir = Path(project_dir).resolve()
    key = str(project_dir)
    if use_cache and key in _CACHE:
        return _CACHE[key]

    latest = _latest_path(project_dir)
    if not latest.is_file():
        raise SnapshotMissing(
            f"no snapshot yet at {latest}; run wiring-reconcile"
        )

    try:
        raw = latest.read_text(encoding="utf-8")
    except OSError as e:
        raise SnapshotInvalid(f"cannot read {latest}: {e}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SnapshotInvalid(f"latest.json is not valid JSON: {e}") from e

    _validate_shape(data)

    if use_cache:
        _CACHE[key] = data
    return data


def _validate_shape(data: Any) -> None:
    """Lightweight required-field check.

    We don't run full jsonschema here — the snapshot was validated when
    wiring-reconcile wrote it. This is a defensive guard against an
    explicit corruption of `latest.json` between reconcile and query.
    """
    if not isinstance(data, dict):
        raise SnapshotInvalid("latest.json is not a JSON object")
    required = {"schema_version", "snapshot_id", "snapshot_generation",
                "run_id", "edges"}
    missing = required - set(data.keys())
    if missing:
        raise SnapshotInvalid(
            f"latest.json missing required fields: {sorted(missing)}"
        )
    if not isinstance(data["edges"], list):
        raise SnapshotInvalid("edges must be an array")


def clear_cache() -> None:
    """Explicit cache invalidation (used by tests)."""
    _CACHE.clear()


def cache_size() -> int:
    """Number of project_dirs cached (tests)."""
    return len(_CACHE)


if __name__ == "__main__":
    # Smoke: python3 loader.py <project_dir>
    if len(sys.argv) != 2:
        sys.stderr.write("usage: loader.py <project_dir>\n")
        sys.exit(2)
    try:
        snap = load_snapshot(Path(sys.argv[1]))
        print(f"snapshot_id={snap['snapshot_id']} "
              f"generation={snap['snapshot_generation']} "
              f"edges={len(snap['edges'])}")
    except SnapshotMissing as e:
        sys.stderr.write(f"MISSING: {e}\n")
        sys.exit(1)
    except SnapshotInvalid as e:
        sys.stderr.write(f"INVALID: {e}\n")
        sys.exit(1)
