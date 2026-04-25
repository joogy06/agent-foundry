#!/usr/bin/env python3
"""test_state_machine.py — tester-split design §5.4 verification.

Covers the verification-request state machine implemented by
`claims.mark_verification_request_status`:

  open -> consumed     OK
  open -> superseded   OK
  open -> stale        OK
  open -> abandoned    OK

  open -> open         ValueError (not a terminal state)
  terminal -> anything RuntimeError (one-shot transitions only)
  missing -> anything  RuntimeError (escalates)

Also verifies that the closed_at / closed_status / reason fields are
populated correctly on transition.

Run:
    python -m pytest skills/_meta/tests/test_state_machine.py -v
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


class StateMachineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vr-state-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _open(self, **overrides):
        return claims.open_verification_request(self.tmp, **_full_tuple(**overrides))

    # ---- valid open -> terminal transitions ----

    def test_open_to_consumed(self):
        rec = self._open(attempt_id="t1")
        out = claims.mark_verification_request_status(
            self.tmp, rec["request_id"], claims.VR_STATUS_CONSUMED,
        )
        self.assertEqual(out["status"], claims.VR_STATUS_CONSUMED)
        self.assertEqual(out["closed_status"], claims.VR_STATUS_CONSUMED)
        self.assertIn("closed_at", out)

    def test_open_to_superseded(self):
        rec = self._open(attempt_id="t2")
        out = claims.mark_verification_request_status(
            self.tmp, rec["request_id"], claims.VR_STATUS_SUPERSEDED,
            reason="newer bundle obsoletes this",
        )
        self.assertEqual(out["status"], claims.VR_STATUS_SUPERSEDED)
        self.assertEqual(out["reason"], "newer bundle obsoletes this")

    def test_open_to_stale(self):
        rec = self._open(attempt_id="t3")
        out = claims.mark_verification_request_status(
            self.tmp, rec["request_id"], claims.VR_STATUS_STALE,
            reason="tuple mismatch",
        )
        self.assertEqual(out["status"], claims.VR_STATUS_STALE)

    def test_open_to_abandoned(self):
        rec = self._open(attempt_id="t4")
        out = claims.mark_verification_request_status(
            self.tmp, rec["request_id"], claims.VR_STATUS_ABANDONED,
            reason="freshness window blew past",
        )
        self.assertEqual(out["status"], claims.VR_STATUS_ABANDONED)

    # ---- invalid transitions ----

    def test_open_to_open_is_value_error(self):
        rec = self._open(attempt_id="t5")
        with self.assertRaises(ValueError):
            claims.mark_verification_request_status(
                self.tmp, rec["request_id"], claims.VR_STATUS_OPEN,
            )

    def test_terminal_to_anything_raises(self):
        rec = self._open(attempt_id="t6")
        claims.mark_verification_request_status(
            self.tmp, rec["request_id"], claims.VR_STATUS_CONSUMED,
        )
        # Now any further transition must raise RuntimeError.
        for target in (
            claims.VR_STATUS_CONSUMED,
            claims.VR_STATUS_SUPERSEDED,
            claims.VR_STATUS_STALE,
            claims.VR_STATUS_ABANDONED,
        ):
            with self.subTest(target=target):
                with self.assertRaises(RuntimeError):
                    claims.mark_verification_request_status(
                        self.tmp, rec["request_id"], target,
                    )

    def test_missing_record_raises_runtime_error(self):
        with self.assertRaises(RuntimeError):
            claims.mark_verification_request_status(
                self.tmp, "deadbeef" * 4, claims.VR_STATUS_CONSUMED,
            )

    def test_unknown_status_raises_value_error(self):
        rec = self._open(attempt_id="t7")
        with self.assertRaises(ValueError):
            claims.mark_verification_request_status(
                self.tmp, rec["request_id"], "rejected",  # not a real state
            )


class StateMachineConstantsCase(unittest.TestCase):
    """Sanity: the exported state constants match the design vocabulary."""

    def test_terminal_states_exact_set(self):
        self.assertEqual(
            claims.VR_TERMINAL_STATES,
            frozenset({"consumed", "superseded", "stale", "abandoned"}),
        )

    def test_open_is_not_terminal(self):
        self.assertNotIn(claims.VR_STATUS_OPEN, claims.VR_TERMINAL_STATES)

    def test_verdict_tuple_fields_count_eight(self):
        self.assertEqual(len(claims.VERDICT_TUPLE_FIELDS), 8)


if __name__ == "__main__":
    unittest.main()
