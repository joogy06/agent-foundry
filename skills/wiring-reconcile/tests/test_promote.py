#!/usr/bin/env python3
"""Unit tests for promote.py."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from promote import (  # noqa: E402
    promote_snapshot,
    verify_signature,
)
from snapshot_writer import write_snapshot_atomic  # noqa: E402


def _stub_snapshot(run_id, snapshot_id="aaaabbbbccccdddd"):
    return {
        "schema_version": "1.0.0",
        "snapshot_id": snapshot_id,
        "snapshot_generation": 1,
        "run_id": run_id,
        "workspace_tree_hash": "f" * 40,
        "generated_at": "2026-04-14T12:00:00Z",
        "generated_by": "wiring-reconcile@1.0.0",
        "contract_map_hash": "deadbeef" * 8,
        "contract_map_revision": 1,
        "source_statuses": {},
        "edges": [],
    }


def _setup_project(td: Path, run_id: str, snapshot_id: str = "aaaabbbbccccdddd"):
    wiring = td / ".wiring" / "runs" / run_id
    wiring.mkdir(parents=True)
    snap = _stub_snapshot(run_id, snapshot_id)
    write_snapshot_atomic(wiring / "snapshot.json", snap)
    skey = td / "session.key"
    skey.write_bytes(b"secret-key-bytes\n")
    sid = td / "session-id"
    sid.write_text("77a80531-f542-4add-a138-1049c926ecd5\n")
    return skey, sid


class TestPromote(unittest.TestCase):

    def test_happy_path(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            run_id = "11111111-1111-1111-1111-111111111111"
            skey, sid = _setup_project(td, run_id)
            result = promote_snapshot(td, run_id, skey, sid)
            self.assertEqual(result["snapshot_generation"], 1)
            self.assertEqual(result["snapshot_id"], "aaaabbbbccccdddd")
            latest = td / ".wiring" / "latest.json"
            self.assertTrue(latest.is_file())
            # Signature verifies with session key bytes
            snap = json.loads(latest.read_text())
            self.assertIn("signature", snap)
            self.assertTrue(verify_signature(snap, skey.read_bytes()))

    def test_generation_monotonic(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            run1 = "aaaaaaaa-0000-0000-0000-000000000001"
            run2 = "aaaaaaaa-0000-0000-0000-000000000002"
            skey, sid = _setup_project(td, run1, "aaaa111122223333")
            r1 = promote_snapshot(td, run1, skey, sid)

            # Build second run
            wiring2 = td / ".wiring" / "runs" / run2
            wiring2.mkdir(parents=True)
            write_snapshot_atomic(
                wiring2 / "snapshot.json",
                _stub_snapshot(run2, snapshot_id="aaaa111122224444"),
            )
            r2 = promote_snapshot(td, run2, skey, sid)
            self.assertEqual(r1["snapshot_generation"], 1)
            self.assertEqual(r2["snapshot_generation"], 2)
            # Generation counter file matches
            gen = int((td / ".wiring" / "snapshot_generation").read_text().strip())
            self.assertEqual(gen, 2)

    def test_idempotent_same_snapshot(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            run_id = "bbbbbbbb-0000-0000-0000-000000000001"
            skey, sid = _setup_project(td, run_id)
            r1 = promote_snapshot(td, run_id, skey, sid)
            r2 = promote_snapshot(td, run_id, skey, sid)
            self.assertEqual(r1["snapshot_generation"], r2["snapshot_generation"])
            self.assertTrue(r2["idempotent_noop"])

    def test_latest_run_id_written(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            run_id = "cccccccc-0000-0000-0000-000000000001"
            skey, sid = _setup_project(td, run_id)
            promote_snapshot(td, run_id, skey, sid)
            lr = (td / ".wiring" / "latest.run_id").read_text().strip()
            self.assertEqual(lr, run_id)

    def test_signature_tampering_fails(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            run_id = "dddddddd-0000-0000-0000-000000000001"
            skey, sid = _setup_project(td, run_id)
            promote_snapshot(td, run_id, skey, sid)
            latest = td / ".wiring" / "latest.json"
            snap = json.loads(latest.read_text())
            # Tamper: change snapshot_id
            snap["snapshot_id"] = "0000000000000000"
            self.assertFalse(verify_signature(snap, skey.read_bytes()))

    def test_missing_snapshot_raises(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            skey = td / "session.key"
            skey.write_bytes(b"k")
            sid = td / "session-id"
            sid.write_text("s")
            with self.assertRaises(FileNotFoundError):
                promote_snapshot(td, "no-such-run", skey, sid)

    def test_session_key_read_as_bytes_including_newline(self):
        """Verify session key is read via Path.read_bytes() (with trailing newline).

        This is a load-bearing invariant — the HMAC is computed over the
        RAW bytes. If we strip the newline, the signature won't verify.
        """
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            run_id = "eeeeeeee-0000-0000-0000-000000000001"
            skey, sid = _setup_project(td, run_id)
            promote_snapshot(td, run_id, skey, sid)
            snap = json.loads((td / ".wiring" / "latest.json").read_text())
            # Signature verifies with full-bytes including trailing newline
            self.assertTrue(verify_signature(snap, skey.read_bytes()))
            # And FAILS if we strip newline (wrong key)
            self.assertFalse(verify_signature(snap, skey.read_bytes().rstrip()))


if __name__ == "__main__":
    unittest.main()
