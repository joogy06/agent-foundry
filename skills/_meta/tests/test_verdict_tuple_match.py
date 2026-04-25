#!/usr/bin/env python3
"""test_verdict_tuple_match.py — tester-split design §5.3 verification.

Covers the 8-field verdict tuple match in `claims.consume_verdict`:

  - Full match across all 8 fields → 'accepted', request consumed.
  - Mismatch on ANY single field → 'rejected_mismatch', request stale,
    `reason` lists the mismatched field(s).
  - Consume on already-terminal request → 'rejected_not_open', no
    state change.
  - Consume on missing request → RuntimeError (escalates).

Run:
    python -m pytest skills/_meta/tests/test_verdict_tuple_match.py -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import claims  # noqa: E402


def _full_tuple(**overrides):
    base = dict(
        component_id="auth-service",
        attempt_id="attempt-1",
        prior_state_version="ledger-rev-7",
        bundle_hash="b" * 64,
        plan_hash="a" * 64,
        inventory_hash="c" * 64,
        runner_version="trusted_runner/1.0",
        rubric_version="rubric/1.0",
    )
    base.update(overrides)
    return base


def _verdict_for(record, **overrides):
    """Build a valid verdict that echoes the record's tuple, with optional overrides."""
    v = {
        "request_id": record["request_id"],
        "attempt_id": record["attempt_id"],
        "prior_state_version": record["prior_state_version"],
        "bundle_hash": record["bundle_hash"],
        "plan_hash": record["plan_hash"],
        "inventory_hash": record["inventory_hash"],
        "runner_version": record["runner_version"],
        "rubric_version": record["rubric_version"],
    }
    v.update(overrides)
    return v


class FullMatchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vr-match-"))
        self.record = claims.open_verification_request(self.tmp, **_full_tuple())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_eight_field_match_accepts(self):
        outcome, after = claims.consume_verdict(
            self.tmp, self.record["request_id"], _verdict_for(self.record)
        )
        self.assertEqual(outcome, "accepted")
        self.assertEqual(after["status"], claims.VR_STATUS_CONSUMED)
        self.assertEqual(after["closed_status"], claims.VR_STATUS_CONSUMED)
        self.assertIn("closed_at", after)


class PerFieldMismatchCase(unittest.TestCase):
    """Mismatch on EACH field individually must be detected."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vr-mismatch-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _check_mismatch_field(self, field_name, bad_value):
        # Fresh request per subtest because consume is single-shot.
        record = claims.open_verification_request(self.tmp, **_full_tuple(
            attempt_id=f"attempt-for-{field_name}",
        ))
        verdict = _verdict_for(record, **{field_name: bad_value})
        outcome, after = claims.consume_verdict(
            self.tmp, record["request_id"], verdict
        )
        self.assertEqual(
            outcome, "rejected_mismatch",
            f"field {field_name!r} mismatch was not detected",
        )
        self.assertEqual(after["status"], claims.VR_STATUS_STALE)
        self.assertIn(field_name, after.get("reason", ""))

    def test_mismatch_on_request_id(self):
        self._check_mismatch_field("request_id", "0" * 32)

    def test_mismatch_on_attempt_id(self):
        self._check_mismatch_field("attempt_id", "wrong-attempt")

    def test_mismatch_on_prior_state_version(self):
        self._check_mismatch_field("prior_state_version", "ledger-rev-99")

    def test_mismatch_on_bundle_hash(self):
        self._check_mismatch_field("bundle_hash", "0" * 64)

    def test_mismatch_on_plan_hash(self):
        self._check_mismatch_field("plan_hash", "f" * 64)

    def test_mismatch_on_inventory_hash(self):
        self._check_mismatch_field("inventory_hash", "1" * 64)

    def test_mismatch_on_runner_version(self):
        self._check_mismatch_field("runner_version", "trusted_runner/9.9")

    def test_mismatch_on_rubric_version(self):
        self._check_mismatch_field("rubric_version", "rubric/9.9")


class MultipleMismatchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vr-multi-"))
        self.record = claims.open_verification_request(self.tmp, **_full_tuple())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_multiple_mismatched_fields_all_listed(self):
        verdict = _verdict_for(
            self.record,
            bundle_hash="0" * 64,
            plan_hash="0" * 64,
            attempt_id="bogus",
        )
        outcome, after = claims.consume_verdict(
            self.tmp, self.record["request_id"], verdict
        )
        self.assertEqual(outcome, "rejected_mismatch")
        for f in ("attempt_id", "bundle_hash", "plan_hash"):
            self.assertIn(f, after["reason"])


class TerminalRequestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vr-terminal-"))
        self.record = claims.open_verification_request(self.tmp, **_full_tuple())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_consume_on_already_consumed_request(self):
        # First consume succeeds.
        claims.consume_verdict(
            self.tmp, self.record["request_id"], _verdict_for(self.record)
        )
        # Second consume must report not-open without raising.
        outcome, after = claims.consume_verdict(
            self.tmp, self.record["request_id"], _verdict_for(self.record)
        )
        self.assertEqual(outcome, "rejected_not_open")
        # Status is unchanged from the first consume.
        self.assertEqual(after["status"], claims.VR_STATUS_CONSUMED)

    def test_consume_on_superseded_request(self):
        claims.mark_verification_request_status(
            self.tmp, self.record["request_id"], claims.VR_STATUS_SUPERSEDED,
            reason="bundle replaced",
        )
        outcome, after = claims.consume_verdict(
            self.tmp, self.record["request_id"], _verdict_for(self.record)
        )
        self.assertEqual(outcome, "rejected_not_open")
        self.assertEqual(after["status"], claims.VR_STATUS_SUPERSEDED)


class MissingRequestCase(unittest.TestCase):
    def test_consume_on_unknown_request_raises(self):
        tmp = Path(tempfile.mkdtemp(prefix="vr-missing-"))
        try:
            with self.assertRaises(RuntimeError):
                claims.consume_verdict(tmp, "deadbeef" * 4, {"request_id": "x"})
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
