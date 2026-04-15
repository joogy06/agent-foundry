#!/usr/bin/env python3
"""snapshot_writer.py — canonical JSON + atomic write for `snapshot.json`.

Per design 2026-04-14 §4.3 + §5.2 (determinism contract). Two concerns:

1. **Canonical JSON serialization.** The bytes of `snapshot.json` MUST match
   bit-for-bit the canonical JSON used elsewhere (notably `edge_identity.py`
   and `_meta/gates.py`) so that bob's HMAC over the signed fields stays
   reproducible. This is `json.dumps(obj, sort_keys=True,
   separators=(",", ":"), ensure_ascii=False)`.

2. **Atomic write.** Same pattern as `_meta/claims.py atomic_write`: write
   to a sibling tmp file, fsync, then `os.replace` onto the final path.
   Guarantees that readers never see a partial file.

This module has NO knowledge of schema validation — `run.py` validates
before calling write. It also has NO knowledge of promotion (`promote.py`
handles that). It is a narrow utility shared by:
- `reconciler.py` (serializes the in-memory snapshot)
- `promote.py` (re-writes the signed snapshot after HMAC)
- tests.

Drift canary: ALDEBARAN-7 (documented invariant: NEVER rearrange
canonical_json parameters; a single-byte diff breaks the signature).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def canonical_json(obj: Any) -> str:
    """Bit-identical canonical JSON.

    Must match `_meta/gates.py canonical_json()` and
    `wiring-reconcile/scripts/edge_identity.py canonical_json()`.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_json_bytes(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def write_snapshot_atomic(path: Path, snapshot_dict: Any) -> None:
    """Write snapshot_dict to path atomically, canonical JSON encoding.

    Pattern: tmp file in same dir + fsync + os.replace. Safe under concurrent
    readers. The caller is responsible for holding any required lock (for
    `snapshot.json` inside a run dir, no lock is needed because each run_id is
    private to one reconcile invocation).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json_bytes(snapshot_dict)
    tmp_path = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    # Write + fsync + replace. fsync the file; on POSIX replace is atomic for
    # same-filesystem swap.
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp_path), str(path))


def read_snapshot(path: Path) -> Any:
    """Read + parse. Convenience for tests and consumers."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
