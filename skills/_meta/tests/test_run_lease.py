#!/usr/bin/env python3
"""test_run_lease.py — WP-6 (S055 §6.5 / R16) persistent run lease.

Covers: acquire / refuse-on-live-different-label / heartbeat /
validate-on-mutation / release / stale-takeover. The lease is the cross-stage
replacement for the nonfunctional cross-process flock (each Bash stage is a
fresh process — flock dies on exit).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_META_DIR = Path(__file__).resolve().parent.parent
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

import claims  # noqa: E402


def _iso_minus(seconds: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class RunLease(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lease-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _lease_file(self):
        return self.tmp / ".ledger" / "run-lease.json"

    # ── acquire ──────────────────────────────────────────────────────────
    def test_acquire_fresh(self):
        r = claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-A", plan_revision=1)
        self.assertEqual(r["status"], "acquired")
        self.assertTrue(r["token"])
        self.assertTrue(self._lease_file().is_file())
        on_disk = json.loads(self._lease_file().read_text())
        self.assertEqual(on_disk["run_label"], "run-A")
        self.assertEqual(on_disk["plan_hash"], "sha256:aaa")
        self.assertEqual(on_disk["plan_revision"], 1)

    def test_reacquire_same_label_idempotent(self):
        r1 = claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-A")
        r2 = claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-A")
        self.assertEqual(r2["status"], "acquired")
        self.assertEqual(r1["token"], r2["token"])  # same token refreshed

    # ── refuse on live different label ──────────────────────────────────
    def test_refuse_live_different_label(self):
        claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-A")
        r = claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-B")
        self.assertEqual(r["status"], "needs_user_decision")
        self.assertIn("holder", r)
        self.assertEqual(r["holder"]["run_label"], "run-A")
        # The original lease is untouched.
        on_disk = json.loads(self._lease_file().read_text())
        self.assertEqual(on_disk["run_label"], "run-A")

    # ── heartbeat ────────────────────────────────────────────────────────
    def test_heartbeat_refreshes(self):
        r = claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-A")
        token = r["token"]
        # Age the heartbeat artificially.
        lease = json.loads(self._lease_file().read_text())
        lease["heartbeat_at"] = _iso_minus(300)
        self._lease_file().write_text(json.dumps(lease))
        ok = claims.heartbeat_run_lease(self.tmp, token)
        self.assertTrue(ok)
        refreshed = json.loads(self._lease_file().read_text())
        # New heartbeat is recent (< 5s old).
        age = (datetime.now(timezone.utc) - claims.parse_iso(refreshed["heartbeat_at"])).total_seconds()
        self.assertLess(age, 5)

    def test_heartbeat_wrong_token_rejected(self):
        claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-A")
        self.assertFalse(claims.heartbeat_run_lease(self.tmp, "not-the-token"))

    # ── validate on mutation ────────────────────────────────────────────
    def test_validate_matches(self):
        r = claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-A")
        self.assertTrue(claims.validate_run_lease(self.tmp, "run-A"))
        self.assertTrue(claims.validate_run_lease(self.tmp, "run-A", plan_hash="sha256:aaa"))
        self.assertTrue(claims.validate_run_lease(self.tmp, "run-A", token=r["token"]))

    def test_validate_wrong_label_rejected(self):
        claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-A")
        self.assertFalse(claims.validate_run_lease(self.tmp, "run-B"))

    def test_validate_wrong_plan_hash_rejected(self):
        claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-A")
        self.assertFalse(claims.validate_run_lease(self.tmp, "run-A", plan_hash="sha256:bbb"))

    def test_validate_no_lease_rejected(self):
        self.assertFalse(claims.validate_run_lease(self.tmp, "run-A"))

    def test_validate_stale_rejected(self):
        claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-A")
        lease = json.loads(self._lease_file().read_text())
        lease["heartbeat_at"] = _iso_minus(claims.RUN_LEASE_EXPIRY_SECONDS + 60)
        self._lease_file().write_text(json.dumps(lease))
        self.assertFalse(claims.validate_run_lease(self.tmp, "run-A"))

    # ── release ──────────────────────────────────────────────────────────
    def test_release(self):
        r = claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-A")
        self.assertTrue(claims.release_run_lease(self.tmp, r["token"]))
        self.assertFalse(self._lease_file().is_file())

    def test_release_wrong_token_rejected(self):
        claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-A")
        self.assertFalse(claims.release_run_lease(self.tmp, "nope"))
        self.assertTrue(self._lease_file().is_file())

    # ── stale takeover ───────────────────────────────────────────────────
    def test_stale_takeover_records_event(self):
        r1 = claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-A")
        # Make run-A's lease stale.
        lease = json.loads(self._lease_file().read_text())
        lease["heartbeat_at"] = _iso_minus(claims.RUN_LEASE_EXPIRY_SECONDS + 120)
        self._lease_file().write_text(json.dumps(lease))
        # run-B takes over.
        r2 = claims.acquire_run_lease(self.tmp, "sha256:aaa", "run-B")
        self.assertEqual(r2["status"], "takeover")
        self.assertIn("previous", r2)
        self.assertEqual(r2["previous"]["run_label"], "run-A")
        self.assertNotEqual(r1["token"], r2["token"])
        on_disk = json.loads(self._lease_file().read_text())
        self.assertEqual(on_disk["run_label"], "run-B")
        self.assertIn("takeover_of", on_disk)


if __name__ == "__main__":
    unittest.main()
