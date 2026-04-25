#!/usr/bin/env python3
"""test_recover_verification_requests.py — tester-split design §5.4, §9.5.

Covers `claims.recover_verification_requests`: the bob-owned sweeper that
marks stale (open but past freshness window) verification requests as
`abandoned` and leaves everything else alone.

Design references:
  §5.4 — state machine: stale open requests transition to `abandoned`
          and escalate.
  §9.5 — freshness window defaults to 1800 s, configurable via
          the `ARBITER_FRESHNESS_WINDOW_S` environment variable.

Run:
    python -m pytest skills/_meta/tests/test_recover_verification_requests.py -v
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import yaml  # noqa: E402

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


def _iso_minus(seconds: int) -> str:
    """Return an ISO-8601 'Z' timestamp that is `seconds` before now (UTC)."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _backdate_request(project_root: Path, request_id: str, seconds_ago: int) -> None:
    """Rewrite a persisted request's `opened_at` to `seconds_ago` before now.

    We go through the raw YAML rather than through `claims` helpers because
    `open_verification_request` stamps `opened_at = now_iso()` and is
    idempotent — rewriting on disk is the only way to simulate an old
    request without patching the clock globally.
    """
    path = (
        project_root
        / claims.VERIFICATION_REQUESTS_SUBDIR
        / f"{request_id}.request.yaml"
    )
    record = yaml.safe_load(path.read_text())
    record["opened_at"] = _iso_minus(seconds_ago)
    path.write_text(yaml.safe_dump(record, sort_keys=True, default_flow_style=False))


class RecoverVerificationRequestsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vr-recover-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- trivial / empty cases ----

    def test_missing_directory_returns_zero_zero(self):
        # No .ledger/requests/verification dir has been created yet.
        swept, skipped = claims.recover_verification_requests(self.tmp)
        self.assertEqual((swept, skipped), (0, 0))

    def test_empty_directory_returns_zero_zero(self):
        (self.tmp / claims.VERIFICATION_REQUESTS_SUBDIR).mkdir(parents=True)
        swept, skipped = claims.recover_verification_requests(self.tmp)
        self.assertEqual((swept, skipped), (0, 0))

    # ---- freshness-window classification ----

    def test_fresh_open_request_is_skipped(self):
        rec = claims.open_verification_request(self.tmp, **_full_tuple(attempt_id="t-fresh"))
        # Default window is 1800s; the record was just opened, so age ~= 0.
        swept, skipped = claims.recover_verification_requests(self.tmp)
        self.assertEqual(swept, 0)
        self.assertEqual(skipped, 1)
        # File is unchanged: status still open.
        path = (
            self.tmp
            / claims.VERIFICATION_REQUESTS_SUBDIR
            / f"{rec['request_id']}.request.yaml"
        )
        reread = yaml.safe_load(path.read_text())
        self.assertEqual(reread["status"], claims.VR_STATUS_OPEN)
        self.assertNotIn("closed_at", reread)

    def test_stale_open_request_is_abandoned(self):
        rec = claims.open_verification_request(self.tmp, **_full_tuple(attempt_id="t-stale"))
        # Backdate to 2 hours ago — well past the 1800s default.
        _backdate_request(self.tmp, rec["request_id"], seconds_ago=2 * 60 * 60)

        swept, skipped = claims.recover_verification_requests(self.tmp)
        self.assertEqual(swept, 1)
        self.assertEqual(skipped, 0)

        path = (
            self.tmp
            / claims.VERIFICATION_REQUESTS_SUBDIR
            / f"{rec['request_id']}.request.yaml"
        )
        reread = yaml.safe_load(path.read_text())
        self.assertEqual(reread["status"], claims.VR_STATUS_ABANDONED)
        self.assertEqual(reread["closed_status"], claims.VR_STATUS_ABANDONED)
        self.assertEqual(reread["reason"], "freshness_window_elapsed")
        self.assertIn("closed_at", reread)

    # ---- terminal states are left alone ----

    def test_terminal_states_are_not_touched(self):
        # Open four requests and move each into a distinct terminal state.
        for idx, target in enumerate(
            (
                claims.VR_STATUS_CONSUMED,
                claims.VR_STATUS_SUPERSEDED,
                claims.VR_STATUS_STALE,
                claims.VR_STATUS_ABANDONED,
            )
        ):
            rec = claims.open_verification_request(
                self.tmp, **_full_tuple(attempt_id=f"t-terminal-{idx}")
            )
            claims.mark_verification_request_status(
                self.tmp, rec["request_id"], target,
                reason=f"prestaged-{target}",
            )
            # Backdate even the terminal ones — sweeper must still ignore them
            # because it only considers status == open.
            _backdate_request(self.tmp, rec["request_id"], seconds_ago=2 * 60 * 60)

        swept, skipped = claims.recover_verification_requests(self.tmp)
        self.assertEqual((swept, skipped), (0, 0))

    # ---- env-var override ----

    def test_env_override_shrinks_window(self):
        import os

        rec = claims.open_verification_request(self.tmp, **_full_tuple(attempt_id="t-env"))
        # Opened 5 minutes ago — well within 1800s default, well past 60s.
        _backdate_request(self.tmp, rec["request_id"], seconds_ago=5 * 60)

        prev = os.environ.get("ARBITER_FRESHNESS_WINDOW_S")
        os.environ["ARBITER_FRESHNESS_WINDOW_S"] = "60"
        try:
            swept, skipped = claims.recover_verification_requests(self.tmp)
        finally:
            if prev is None:
                os.environ.pop("ARBITER_FRESHNESS_WINDOW_S", None)
            else:
                os.environ["ARBITER_FRESHNESS_WINDOW_S"] = prev

        self.assertEqual(swept, 1)
        self.assertEqual(skipped, 0)
        path = (
            self.tmp
            / claims.VERIFICATION_REQUESTS_SUBDIR
            / f"{rec['request_id']}.request.yaml"
        )
        reread = yaml.safe_load(path.read_text())
        self.assertEqual(reread["status"], claims.VR_STATUS_ABANDONED)

    # ---- robustness: malformed YAML ----

    def test_malformed_yaml_is_skipped(self):
        # One well-formed fresh request plus one malformed file in the
        # same directory. Sweeper should count the fresh one and not crash
        # on the malformed one.
        rec = claims.open_verification_request(self.tmp, **_full_tuple(attempt_id="t-good"))
        bad_path = (
            self.tmp
            / claims.VERIFICATION_REQUESTS_SUBDIR
            / "deadbeefdeadbeefdeadbeefdeadbeef.request.yaml"
        )
        bad_path.write_text("this is: : not valid yaml: [unterminated\n")

        swept, skipped = claims.recover_verification_requests(self.tmp)
        self.assertEqual(swept, 0)
        self.assertEqual(skipped, 1)  # only the good request is counted

        # Good request untouched.
        good_path = (
            self.tmp
            / claims.VERIFICATION_REQUESTS_SUBDIR
            / f"{rec['request_id']}.request.yaml"
        )
        reread = yaml.safe_load(good_path.read_text())
        self.assertEqual(reread["status"], claims.VR_STATUS_OPEN)


if __name__ == "__main__":
    unittest.main()
