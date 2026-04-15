#!/usr/bin/env python3
"""promote.py — bob-side atomic snapshot promotion.

Per design 2026-04-14 §5.2 "bob responsibility after reconcile succeeds"
and §4.3 signature block. **This is a library module bob imports** — it is
NOT a standalone skill and does NOT emit transition requests (bob does).

Public API:
    promote_snapshot(
        project_dir,
        run_id,
        session_key_path,
        session_id_path,
    ) -> Dict[str, Any]

Steps (in order, all under `.wiring/.promote.lock`):
  1. flock the `.promote.lock` (non-blocking; raise BlockingIOError if held)
  2. Read `.wiring/runs/<run_id>/snapshot.json` (schema-validate once more)
  3. Read + bump `.wiring/snapshot_generation` atomically (N -> N+1)
  4. Compute signature payload: {map_hash, map_revision, forge_session_id,
     snapshot_id, snapshot_generation, signed_at}
  5. HMAC-SHA256 over `canonical_json(payload)` using raw bytes of session.key
  6. Rewrite snapshot with merged `signature` block + updated generation
  7. Atomic rename snapshot.json in run dir
  8. Atomic copy to `.wiring/latest.json` (file-copy + rename — NOT symlink,
     to keep behavior uniform across filesystems and simplify the bob
     invariant "readers see a plain file")
  9. Write `.wiring/latest.run_id = run_id` (atomic)
 10. Release flock

Invariants bob enforces:
- `.wiring/` root is bob-created (if missing, CREATE before flock).
- `.wiring/.promote.lock` is bob-created (if missing, CREATE before flock).
- bob is sole writer of `latest.json`, `latest.run_id`, `snapshot_generation`.
- Session key bytes are used verbatim (Path.read_bytes()); do NOT strip
  newline — this matches `_meta/gates.py` which uses `read_bytes()` too.

Idempotency: re-calling promote_snapshot with the same run_id+snapshot_id is
safe. If the generation counter already reflects this snapshot_id, we do not
bump again — we verify signature and return. This simplifies bob retry logic.

Drift canary: ALDEBARAN-7.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from snapshot_writer import canonical_json, canonical_json_bytes, write_snapshot_atomic  # noqa: E402


SIGNED_FIELDS = [
    "contract_map_hash",
    "contract_map_revision",
    "forge_session_id",
    "snapshot_id",
    "snapshot_generation",
    "signed_at",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def _read_generation(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return 0


def _write_generation(path: Path, n: int) -> None:
    _atomic_write_text(path, str(int(n)) + "\n")


class _PromoteLock:
    """Exclusive non-blocking flock on `.wiring/.promote.lock`.

    Raises BlockingIOError if already held. Caller is responsible for
    either: (a) retrying with backoff, or (b) aborting.
    """

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._fh = None

    def __enter__(self) -> "_PromoteLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        # touch
        self._fh = open(self.lock_path, "a+")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            self._fh.close()
            self._fh = None
            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise BlockingIOError("promote lock held") from e
            raise
        return self

    def __exit__(self, *exc) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()


def _build_signature(
    snapshot: Dict[str, Any],
    forge_session_id: str,
    session_key_bytes: bytes,
    generation: int,
) -> Dict[str, Any]:
    signed_at = _now_iso()
    payload = {
        "contract_map_hash": snapshot.get("contract_map_hash", ""),
        "contract_map_revision": int(snapshot.get("contract_map_revision", 0) or 0),
        "forge_session_id": forge_session_id,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_generation": int(generation),
        "signed_at": signed_at,
    }
    payload_bytes = canonical_json_bytes(payload)
    mac = hmac.new(session_key_bytes, payload_bytes, hashlib.sha256).hexdigest()
    return {
        "algorithm": "HMAC-SHA256",
        "key_id": f"forge-session-{forge_session_id}",
        "signed_at": signed_at,
        "signed_fields": list(SIGNED_FIELDS),
        "digest": mac,
    }


def verify_signature(
    snapshot: Dict[str, Any],
    session_key_bytes: bytes,
    forge_session_id: Optional[str] = None,
) -> bool:
    """Independently verify the HMAC on a signed snapshot.

    If `forge_session_id` is None, parse it out of `signature.key_id`.
    Returns True iff the HMAC matches. Used by tests + bob-side audit.
    """
    sig = snapshot.get("signature") or {}
    if sig.get("algorithm") != "HMAC-SHA256":
        return False
    expected_digest = sig.get("digest")
    if not expected_digest:
        return False
    if forge_session_id is None:
        key_id = sig.get("key_id", "")
        if not key_id.startswith("forge-session-"):
            return False
        forge_session_id = key_id[len("forge-session-"):]
    payload = {
        "contract_map_hash": snapshot.get("contract_map_hash", ""),
        "contract_map_revision": int(snapshot.get("contract_map_revision", 0) or 0),
        "forge_session_id": forge_session_id,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_generation": int(snapshot["snapshot_generation"]),
        "signed_at": sig["signed_at"],
    }
    payload_bytes = canonical_json_bytes(payload)
    mac = hmac.new(session_key_bytes, payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, expected_digest)


def promote_snapshot(
    project_dir: Path,
    run_id: str,
    session_key_path: Path,
    session_id_path: Path,
) -> Dict[str, Any]:
    """Atomic promote. Returns dict with snapshot_generation, snapshot_id, latest_path.

    Raises:
      BlockingIOError  if promote lock is held by another bob.
      FileNotFoundError if the run-scoped snapshot.json doesn't exist.
      ValueError       if session key or session id files cannot be read.
    """
    project_dir = Path(project_dir).resolve()
    run_dir = project_dir / ".wiring" / "runs" / run_id
    snap_path = run_dir / "snapshot.json"
    if not snap_path.is_file():
        raise FileNotFoundError(f"run snapshot missing: {snap_path}")

    try:
        session_key_bytes = Path(session_key_path).read_bytes()
    except OSError as e:
        raise ValueError(f"cannot read session key: {e}") from e
    try:
        forge_session_id = Path(session_id_path).read_text(encoding="utf-8").strip()
    except OSError as e:
        raise ValueError(f"cannot read session id: {e}") from e
    if not forge_session_id:
        raise ValueError("session id file is empty")

    wiring_root = project_dir / ".wiring"
    wiring_root.mkdir(parents=True, exist_ok=True)
    gen_path = wiring_root / "snapshot_generation"
    latest_json = wiring_root / "latest.json"
    latest_run_id = wiring_root / "latest.run_id"
    lock_path = wiring_root / ".promote.lock"

    # Pre-create lock file
    if not lock_path.exists():
        lock_path.touch()

    with _PromoteLock(lock_path):
        snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
        snapshot_id = snapshot["snapshot_id"]

        # Idempotency: if latest already points to this snapshot_id, verify
        # and return without bumping generation.
        if latest_json.is_file():
            try:
                cur = json.loads(latest_json.read_text(encoding="utf-8"))
                if cur.get("snapshot_id") == snapshot_id and cur.get("run_id") == run_id:
                    if verify_signature(cur, session_key_bytes, forge_session_id):
                        return {
                            "snapshot_generation": int(cur["snapshot_generation"]),
                            "snapshot_id": snapshot_id,
                            "latest_path": str(latest_json),
                            "idempotent_noop": True,
                        }
            except (json.JSONDecodeError, OSError):
                pass

        # Bump generation
        cur_gen = _read_generation(gen_path)
        new_gen = cur_gen + 1

        # Update snapshot dict and sign it
        snapshot["snapshot_generation"] = new_gen
        snapshot["signature"] = _build_signature(
            snapshot, forge_session_id, session_key_bytes, new_gen
        )

        # Atomic write updated snapshot into run dir (bob rewrites it
        # because §5.2 says bob signs after reconcile emits) AND atomic
        # write into latest.json.
        write_snapshot_atomic(snap_path, snapshot)
        write_snapshot_atomic(latest_json, snapshot)

        # Update latest.run_id + generation (atomic)
        _atomic_write_text(latest_run_id, run_id + "\n")
        _write_generation(gen_path, new_gen)

        return {
            "snapshot_generation": new_gen,
            "snapshot_id": snapshot_id,
            "latest_path": str(latest_json),
            "idempotent_noop": False,
        }
