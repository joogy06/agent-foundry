#!/usr/bin/env python3
"""test_claims_keystone.py — ecosystem-keystone §5.5 + §5.2 + §2.8 coverage.

Covers contract-map `claims-keystone` test scenarios TS-CL-01..07:

    TS-CL-01  open_visual_verification_request idempotency — two calls with
              byte-identical tuples return same request_id; `created` flips
              True -> False on the second call.
    TS-CL-02  consume_visual_verdict accepted — 8-field tuple echo matches +
              persisted status=open -> outcome='accepted', record marked
              consumed.
    TS-CL-03  consume_visual_verdict rejected_tuple_mismatch — one tuple
              field differs -> outcome='rejected_tuple_mismatch', request
              file unchanged (no state change).
    TS-CL-04  file_challenge closed-set reasons — each of 4 closed-set
              reasons writes a challenge + auto-emits observation of the
              correct category; any 5th reason raises ValueError.
    TS-CL-05  resolve_challenge approve + contract_map_delta — skeleton +
              contract-map committed atomically via bundle_write; a simulated
              second-target write failure rolls back the first target to its
              pre-image.
    TS-CL-06  file_lifecycle_event renamed — history gets the event, both
              from_uri and to_uri are resolvable via uri.resolve() with an
              alias chain threaded through.
    TS-CL-07  file_lifecycle_event retired — entity marked retired in
              history; uri.resolve(old_uri) raises UriExpiredError unless
              allow_expired=True.

Run:
    pytest ~/.claude/skills/_meta/tests/test_claims_keystone.py -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest import mock

_META_DIR = Path(__file__).resolve().parent.parent
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

import yaml  # noqa: E402

import claims  # noqa: E402
import trusted_runner  # noqa: E402
import uri  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _visual_tuple(**overrides) -> Dict[str, Any]:
    """Return a baseline 9-kwarg dict for open_visual_verification_request."""
    base = dict(
        skeleton_hash="s" * 64,
        impl_hash="i" * 64,
        breakpoints=["mobile", "tablet", "desktop"],
        attempt_id="attempt-1",
        prior_state_version="ledger-rev-7",
        plan_hash="p" * 64,
        inventory_hash="c" * 64,
        runner_version="trusted_runner/1.0",
        rubric_version="rubric/1.0",
    )
    base.update(overrides)
    return base


def _verdict_from_record(record: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """Build a verdict dict that echoes all 8 visual tuple fields."""
    v = {f: record[f] for f in claims.VISUAL_VERDICT_TUPLE_FIELDS if f in record}
    v.update(overrides)
    return v


class _ClaimsKeystoneBase(unittest.TestCase):
    """Per-test temp project_root; clean teardown."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="claims-keystone-"))

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# TS-CL-01 — open_visual_verification_request idempotency
# ---------------------------------------------------------------------------


class TSCL01IdempotentOpenCase(_ClaimsKeystoneBase):
    def test_same_tuple_returns_same_request_id_and_created_flips(self) -> None:
        first = claims.open_visual_verification_request(self.tmp, **_visual_tuple())
        second = claims.open_visual_verification_request(self.tmp, **_visual_tuple())

        self.assertEqual(first["request_id"], second["request_id"])
        self.assertTrue(first["created"], "first call must report created=True")
        self.assertFalse(second["created"], "second call must report created=False")

        # Exactly one file on disk for this tuple.
        req_dir = self.tmp / claims.VISUAL_VERIFICATION_REQUESTS_SUBDIR
        files = list(req_dir.glob("*.yaml"))
        self.assertEqual(len(files), 1)

        # Status remained `open` on both calls (no mutation).
        self.assertEqual(first["status"], claims.VVR_STATUS_OPEN)
        self.assertEqual(second["status"], claims.VVR_STATUS_OPEN)

    def test_different_breakpoints_yield_different_request_id(self) -> None:
        a = claims.open_visual_verification_request(
            self.tmp, **_visual_tuple(breakpoints=["mobile"])
        )
        b = claims.open_visual_verification_request(
            self.tmp, **_visual_tuple(breakpoints=["desktop"])
        )
        self.assertNotEqual(a["request_id"], b["request_id"])


# ---------------------------------------------------------------------------
# TS-CL-02 — consume_visual_verdict accepted
# ---------------------------------------------------------------------------


class TSCL02ConsumeAcceptedCase(_ClaimsKeystoneBase):
    def test_full_tuple_match_transitions_open_to_consumed(self) -> None:
        record = claims.open_visual_verification_request(self.tmp, **_visual_tuple())
        rid = record["request_id"]
        verdict = _verdict_from_record(record, verdict="pass", coverage={"ok": True})

        outcome, updated = claims.consume_visual_verdict(self.tmp, rid, verdict)

        self.assertEqual(outcome, "accepted")
        self.assertEqual(updated["status"], claims.VVR_STATUS_CONSUMED)
        self.assertEqual(updated["closed_status"], claims.VVR_STATUS_CONSUMED)
        self.assertIn("closed_at", updated)
        self.assertEqual(updated["verdict"]["verdict"], "pass")

        # File on disk reflects consumed state.
        path = self.tmp / claims.VISUAL_VERIFICATION_REQUESTS_SUBDIR / f"{rid}.yaml"
        persisted = yaml.safe_load(path.read_text())
        self.assertEqual(persisted["status"], claims.VVR_STATUS_CONSUMED)

    def test_second_consume_on_already_consumed_returns_not_open(self) -> None:
        record = claims.open_visual_verification_request(self.tmp, **_visual_tuple())
        rid = record["request_id"]
        verdict = _verdict_from_record(record)
        claims.consume_visual_verdict(self.tmp, rid, verdict)

        outcome, _ = claims.consume_visual_verdict(self.tmp, rid, verdict)
        self.assertEqual(outcome, "rejected_not_open")


# ---------------------------------------------------------------------------
# TS-CL-03 — consume_visual_verdict rejected_tuple_mismatch
# ---------------------------------------------------------------------------


class TSCL03ConsumeTupleMismatchCase(_ClaimsKeystoneBase):
    def test_single_field_mismatch_rejects_without_state_change(self) -> None:
        record = claims.open_visual_verification_request(self.tmp, **_visual_tuple())
        rid = record["request_id"]

        # Flip one tuple field in the verdict only.
        verdict = _verdict_from_record(record)
        verdict["inventory_hash"] = "x" * 64

        outcome, returned = claims.consume_visual_verdict(self.tmp, rid, verdict)
        self.assertEqual(outcome, "rejected_tuple_mismatch")
        self.assertEqual(returned["status"], claims.VVR_STATUS_OPEN,
                         "tuple mismatch MUST NOT change request status")

        # File on disk is still `open` — no state change was persisted.
        path = self.tmp / claims.VISUAL_VERIFICATION_REQUESTS_SUBDIR / f"{rid}.yaml"
        persisted = yaml.safe_load(path.read_text())
        self.assertEqual(persisted["status"], claims.VVR_STATUS_OPEN)
        self.assertNotIn("closed_at", persisted)
        self.assertNotIn("closed_status", persisted)

    def test_bad_request_id_in_verdict_is_also_mismatch(self) -> None:
        record = claims.open_visual_verification_request(self.tmp, **_visual_tuple())
        rid = record["request_id"]
        verdict = _verdict_from_record(record)
        verdict["request_id"] = "0" * 32  # wrong id echoed back

        outcome, _ = claims.consume_visual_verdict(self.tmp, rid, verdict)
        self.assertEqual(outcome, "rejected_tuple_mismatch")


# ---------------------------------------------------------------------------
# TS-CL-04 — file_challenge closed-set reasons + observation category
# ---------------------------------------------------------------------------


class TSCL04FileChallengeCase(_ClaimsKeystoneBase):
    def test_all_four_reasons_write_and_emit_expected_category(self) -> None:
        expected = {
            "implementation_blocked": "flow_gap",
            "functional_requirement_conflict": "schema_mismatch",
            "mockup_ambiguous": "skill_bug",
            "accessibility_violation": "skill_bug",
        }

        observed_categories: List[str] = []

        def _fake_observe(**kwargs: Any) -> None:
            observed_categories.append(kwargs.get("category"))

        with mock.patch.object(claims, "claude_observe", side_effect=_fake_observe):
            for reason, want_category in expected.items():
                record = claims.file_challenge(
                    self.tmp,
                    skeleton_ref=f"skeleton://journey.{reason}#elem",
                    reason=reason,
                    details={"note": f"details-for-{reason}"},
                    proposed_resolution={"note": "bump skeleton"},
                    filed_by="bob",
                )
                self.assertEqual(record["reason"], reason)
                self.assertEqual(record["schema"], "skeleton-challenge.v1")
                self.assertEqual(record["state"], "FILED")

                # File exists on disk.
                path = (
                    self.tmp / claims.CHALLENGES_SUBDIR
                    / f"{record['challenge_id']}.yaml"
                )
                self.assertTrue(path.is_file())

        self.assertEqual(len(observed_categories), 4)
        self.assertEqual(
            observed_categories,
            [expected[r] for r in expected.keys()],
        )

    def test_fifth_reason_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            claims.file_challenge(
                self.tmp,
                skeleton_ref="skeleton://home#x",
                reason="layout_drift",   # not in closed set
                details={},
            )

    def test_idempotent_by_digest(self) -> None:
        with mock.patch.object(claims, "claude_observe") as obs:
            r1 = claims.file_challenge(
                self.tmp,
                skeleton_ref="skeleton://home#x",
                reason="implementation_blocked",
                details={"k": "v"},
            )
            r2 = claims.file_challenge(
                self.tmp,
                skeleton_ref="skeleton://home#x",
                reason="implementation_blocked",
                details={"k": "v"},
            )
            self.assertEqual(r1["challenge_id"], r2["challenge_id"])
            # Only the first call should emit an observation.
            self.assertEqual(obs.call_count, 1)


# ---------------------------------------------------------------------------
# TS-CL-05 — resolve_challenge approve + contract_map_delta atomic bundle
# ---------------------------------------------------------------------------


class TSCL05ResolveChallengeBundleCase(_ClaimsKeystoneBase):
    def _pre_seed_challenge(self) -> str:
        rec = claims.file_challenge(
            self.tmp,
            skeleton_ref="skeleton://home#hero",
            reason="functional_requirement_conflict",
            details={"conflict": "auth-check vs layout"},
            proposed_resolution={"amend": "bump binds_to"},
        )
        return rec["challenge_id"]

    def test_happy_path_two_file_atomic_commit(self) -> None:
        cid = self._pre_seed_challenge()

        # Pre-seed the two targets with old content so we can assert replacement.
        skeleton_rel = ".design-ledger/skeletons/home.yaml"
        contract_rel = "progress/contract-map.yaml"
        skeleton_path = self.tmp / skeleton_rel
        contract_path = self.tmp / contract_rel
        skeleton_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        skeleton_path.write_bytes(b"old: skeleton\n")
        contract_path.write_bytes(b"old: contract\n")

        delta = {
            "skeleton_path": skeleton_rel,
            "contract_map_path": contract_rel,
            "skeleton_bytes": b"new: skeleton\n",
            "contract_map_bytes": b"new: contract\n",
        }
        updated = claims.resolve_challenge(
            self.tmp, cid,
            resolution_type="approve",
            new_skeleton_version="1.1",
            contract_map_delta=delta,
        )

        self.assertEqual(updated["state"], "RESOLVED_APPROVED")
        self.assertEqual(updated["resolution"]["resolution_type"], "approve")
        self.assertIn("txn_id", updated["resolution"])
        self.assertEqual(skeleton_path.read_bytes(), b"new: skeleton\n")
        self.assertEqual(contract_path.read_bytes(), b"new: contract\n")

        # No orphan rollback dir left.
        rollback_dir = self.tmp / ".tmp" / "rollback"
        if rollback_dir.is_dir():
            leftover = list(rollback_dir.iterdir())
            self.assertEqual(leftover, [], f"orphan rollback dirs: {leftover}")

    def test_simulated_second_write_failure_rolls_back_first(self) -> None:
        cid = self._pre_seed_challenge()
        skeleton_rel = ".design-ledger/skeletons/home.yaml"
        contract_rel = "progress/contract-map.yaml"
        skeleton_path = self.tmp / skeleton_rel
        contract_path = self.tmp / contract_rel
        skeleton_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        skeleton_pre = b"old: skeleton\n"
        contract_pre = b"old: contract\n"
        skeleton_path.write_bytes(skeleton_pre)
        contract_path.write_bytes(contract_pre)

        delta = {
            "skeleton_path": skeleton_rel,
            "contract_map_path": contract_rel,
            "skeleton_bytes": b"new: skeleton\n",
            "contract_map_bytes": b"new: contract\n",
        }

        # Patch atomic_write_bytes to fail when writing to the SECOND commit
        # target (contract-map). bundle_write also calls atomic_write_bytes
        # for pre-image snapshots and the rollback manifest, so matching by
        # count is brittle — matching by destination path is deterministic.
        # This is the spec's "second rename raises EIO" scenario.
        real_awb = trusted_runner.atomic_write_bytes

        def fail_on_contract_commit(path: Path, data: bytes) -> None:
            if Path(path) == contract_path:
                raise OSError(
                    "EIO: simulated disk failure on second commit"
                )
            return real_awb(path, data)

        with mock.patch.object(
            trusted_runner, "atomic_write_bytes",
            side_effect=fail_on_contract_commit,
        ):
            with self.assertRaises(trusted_runner.BundleWriteError) as ctx:
                claims.resolve_challenge(
                    self.tmp, cid,
                    resolution_type="approve",
                    new_skeleton_version="1.1",
                    contract_map_delta=delta,
                )
        err = ctx.exception
        self.assertIn(str(skeleton_path), err.rolled_back_paths)

        # Both targets are back at their pre-image content.
        self.assertEqual(skeleton_path.read_bytes(), skeleton_pre)
        self.assertEqual(contract_path.read_bytes(), contract_pre)

    def test_reject_path_makes_no_cross_ledger_writes(self) -> None:
        cid = self._pre_seed_challenge()
        skeleton_path = self.tmp / ".design-ledger/skeletons/home.yaml"
        contract_path = self.tmp / "progress/contract-map.yaml"
        self.assertFalse(skeleton_path.exists())
        self.assertFalse(contract_path.exists())
        updated = claims.resolve_challenge(
            self.tmp, cid, resolution_type="reject",
        )
        self.assertEqual(updated["state"], "RESOLVED_REJECTED")
        self.assertFalse(skeleton_path.exists())
        self.assertFalse(contract_path.exists())

    def test_accept_with_tradeoff_records_deviation(self) -> None:
        cid = self._pre_seed_challenge()
        updated = claims.resolve_challenge(
            self.tmp, cid,
            resolution_type="accept_with_tradeoff",
            new_skeleton_version="1.0-p1",
        )
        self.assertEqual(updated["state"], "RESOLVED_TRADEOFF")
        self.assertEqual(
            updated["accepted_deviation"]["new_skeleton_version"], "1.0-p1",
        )

    def test_bad_resolution_type_raises(self) -> None:
        cid = self._pre_seed_challenge()
        with self.assertRaises(ValueError):
            claims.resolve_challenge(
                self.tmp, cid, resolution_type="maybe",
            )


# ---------------------------------------------------------------------------
# TS-CL-06 — file_lifecycle_event renamed + uri.resolve alias chain
# ---------------------------------------------------------------------------


def _seed_capability_in_contract_map(
    project_root: Path, component_id: str, capability_id: str, uuid_str: str,
) -> None:
    """Write a minimal contract-map.yaml with one component + capability so
    that uri.resolve() can locate the active entity at `capability://...`.

    The contract-map schema uses `components: [{id, capabilities: {k: v}}]`
    (a list of component dicts, each with a keyed capabilities map). See
    _lookup_capability in _meta/uri.py.
    """
    contract_map = project_root / "progress" / "contract-map.yaml"
    contract_map.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "components": [
            {
                "id": component_id,
                "capabilities": {
                    capability_id: {
                        "entity_uuid": uuid_str,
                        "purpose": "seeded-for-test",
                    }
                },
            }
        ]
    }
    contract_map.write_text(yaml.safe_dump(doc, sort_keys=True))


class TSCL06LifecycleRenamedCase(_ClaimsKeystoneBase):
    def test_renamed_threads_through_alias_chain(self) -> None:
        entity_uuid = "e7a9f321-4c8b-11ef-a1b2-c3d4e5f6a7b8"
        from_uri = "capability://journey_controller.advance"
        to_uri = "capability://journey_controller.advance_step"

        # Step 1: record the created event so a baseline history exists.
        claims.file_lifecycle_event(
            self.tmp, entity_uuid, "created",
            {"initial_uri": from_uri, "by": "forge", "session_id": "fs_test"},
        )
        # Step 2: rename. History now threads from_uri -> to_uri.
        claims.file_lifecycle_event(
            self.tmp, entity_uuid, "renamed",
            {
                "from_uri": from_uri,
                "to_uri": to_uri,
                "by": "user",
                "reason": "clarity",
            },
        )

        # Seed the *new* URI as the active capability in contract-map so
        # uri.resolve() succeeds for the to_uri and follows the alias chain
        # for the from_uri.
        _seed_capability_in_contract_map(
            self.tmp, "journey_controller", "advance_step", entity_uuid,
        )

        # Resolving the current URI directly -> active hit (no chain).
        current = uri.resolve(to_uri, self.tmp)
        self.assertEqual(current.uri, to_uri)
        self.assertEqual(current.entity_uuid, entity_uuid)
        self.assertEqual(current.resolution_chain, ())

        # Resolving the from_uri must follow the alias chain to the to_uri.
        old = uri.resolve(from_uri, self.tmp)
        self.assertEqual(old.uri, to_uri,
                         "alias chain must land on the current URI")
        self.assertGreaterEqual(len(old.resolution_chain), 2)
        self.assertEqual(old.resolution_chain[0], from_uri)
        self.assertEqual(old.resolution_chain[-1], to_uri)

    def test_renamed_updates_current_final_uris(self) -> None:
        euuid = "e7a9f321-4c8b-11ef-a1b2-c3d4e5f6a7b9"
        claims.file_lifecycle_event(
            self.tmp, euuid, "created",
            {"initial_uri": "capability://m.a"},
        )
        history = claims.file_lifecycle_event(
            self.tmp, euuid, "renamed",
            {
                "from_uri": "capability://m.a",
                "to_uri": "capability://m.b",
            },
        )
        self.assertEqual(history["current"]["status"], "active")
        self.assertEqual(history["current"]["final_uris"], ["capability://m.b"])


# ---------------------------------------------------------------------------
# TS-CL-07 — file_lifecycle_event retired -> UriExpiredError
# ---------------------------------------------------------------------------


class TSCL07LifecycleRetiredCase(_ClaimsKeystoneBase):
    def test_retired_entity_raises_expired_unless_flag_set(self) -> None:
        entity_uuid = "a1b2c3d4-5e6f-7890-abcd-ef1234567890"
        the_uri = "capability://journey_controller.advance_step"

        # Register creation, then retirement with no successor.
        claims.file_lifecycle_event(
            self.tmp, entity_uuid, "created",
            {"initial_uri": the_uri, "by": "forge"},
        )
        history = claims.file_lifecycle_event(
            self.tmp, entity_uuid, "retired",
            {"final_uri": the_uri, "by": "user", "reason": "no longer needed"},
        )
        self.assertEqual(history["current"]["status"], "retired")
        self.assertEqual(history["current"]["final_uris"], [the_uri])

        # DELIBERATELY no contract-map entry for this capability — the
        # capability is retired, so no active ledger hit is present.
        # uri.resolve() must raise UriExpiredError.
        with self.assertRaises(uri.UriExpiredError):
            uri.resolve(the_uri, self.tmp)

        # With allow_expired=True the resolver returns a historical record.
        result = uri.resolve(the_uri, self.tmp, allow_expired=True)
        self.assertEqual(result.entity_uuid, entity_uuid)

    def test_split_affects_source_ledger_uses_bundle_write(self) -> None:
        entity_uuid = "d4e5f6a7-1234-5678-90ab-cdef12345678"
        history_path = (
            self.tmp / claims.ENTITY_LIFECYCLE_SUBDIR
            / f"{entity_uuid}.history.yaml"
        )
        source_rel = "progress/contract-map.yaml"
        source_path = self.tmp / source_rel
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"pre: source\n")

        # Count atomic_write_bytes calls to confirm bundle_write path was used
        # (two target commits + manifest = at least 3 calls).
        call_log: List[Path] = []
        real_awb = trusted_runner.atomic_write_bytes

        def spy_awb(path: Path, data: bytes) -> None:
            call_log.append(Path(path))
            return real_awb(path, data)

        with mock.patch.object(
            trusted_runner, "atomic_write_bytes", side_effect=spy_awb,
        ):
            history = claims.file_lifecycle_event(
                self.tmp, entity_uuid, "split",
                {
                    "from_uri": "capability://a.b",
                    "to_uris": ["capability://a.b_sync", "capability://a.b_async"],
                    "successor_uuids": ["u1", "u2"],
                    "affects_source_ledger": True,
                    "source_ledger_path": source_rel,
                    "source_ledger_bytes": b"post: source\n",
                },
            )
        self.assertEqual(history["current"]["status"], "retired")
        self.assertEqual(history["current"]["successors"], ["u1", "u2"])
        self.assertEqual(source_path.read_bytes(), b"post: source\n")
        self.assertTrue(history_path.is_file())

        # bundle_write -> pre-image manifest + 2 target commits = 3 writes.
        self.assertGreaterEqual(len(call_log), 3)

    def test_bad_event_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            claims.file_lifecycle_event(
                self.tmp, "u1", "deprecated", {},
            )


if __name__ == "__main__":
    unittest.main()
