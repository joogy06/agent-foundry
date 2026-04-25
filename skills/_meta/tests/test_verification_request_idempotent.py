#!/usr/bin/env python3
"""test_verification_request_idempotent.py — tester-split design §5.4 verification.

Covers the idempotency guarantee on `claims.open_verification_request`:
two calls with byte-identical 8-field tuples MUST return the same
request_id, MUST NOT create a duplicate file, and MUST NOT mutate the
existing record's opened_at / opened_by metadata.

Run:
    python -m pytest skills/_meta/tests/test_verification_request_idempotent.py -v
Or plain unittest:
    python -m unittest skills._meta.tests.test_verification_request_idempotent -v
"""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import claims  # noqa: E402


def _full_tuple(**overrides):
    """Return a baseline 8-field input dict; tests override individual keys."""
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


class IdempotentOpenCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vr-idem-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_same_tuple_returns_same_request_id(self):
        first = claims.open_verification_request(self.tmp, **_full_tuple())
        second = claims.open_verification_request(self.tmp, **_full_tuple())
        self.assertEqual(first["request_id"], second["request_id"])

    def test_no_duplicate_file_created(self):
        claims.open_verification_request(self.tmp, **_full_tuple())
        claims.open_verification_request(self.tmp, **_full_tuple())
        claims.open_verification_request(self.tmp, **_full_tuple())
        request_dir = self.tmp / claims.VERIFICATION_REQUESTS_SUBDIR
        files = list(request_dir.glob("*.request.yaml"))
        self.assertEqual(len(files), 1)

    def test_second_call_does_not_mutate_opened_at(self):
        first = claims.open_verification_request(self.tmp, **_full_tuple())
        time.sleep(1.05)  # ensure now_iso() second-precision differs
        second = claims.open_verification_request(self.tmp, **_full_tuple())
        self.assertEqual(first["opened_at"], second["opened_at"])
        self.assertEqual(first["opened_by"], second["opened_by"])

    def test_second_call_with_different_opened_by_does_not_overwrite(self):
        first = claims.open_verification_request(
            self.tmp, opened_by="bob", **_full_tuple()
        )
        second = claims.open_verification_request(
            self.tmp, opened_by="impostor", **_full_tuple()
        )
        self.assertEqual(first["opened_by"], "bob")
        self.assertEqual(second["opened_by"], "bob")  # existing record returned

    def test_different_tuple_yields_different_request_id(self):
        a = claims.open_verification_request(self.tmp, **_full_tuple())
        b = claims.open_verification_request(
            self.tmp, **_full_tuple(attempt_id="attempt-2")
        )
        self.assertNotEqual(a["request_id"], b["request_id"])

    def test_request_id_is_deterministic_across_processes(self):
        # Recompute the digest manually and assert it matches.
        import hashlib
        record = claims.open_verification_request(self.tmp, **_full_tuple())
        expected_canonical = claims._canonical_request_payload(_full_tuple())
        expected_digest = hashlib.sha256(
            expected_canonical.encode("utf-8")
        ).hexdigest()[:32]
        self.assertEqual(record["request_id"], expected_digest)

    def test_request_id_excludes_request_id_from_digest_input(self):
        # Sanity: the canonical payload helper must not require / include
        # request_id (it's derived from the digest, not an input).
        canonical = claims._canonical_request_payload(_full_tuple())
        self.assertNotIn("request_id", canonical)


if __name__ == "__main__":
    unittest.main()
