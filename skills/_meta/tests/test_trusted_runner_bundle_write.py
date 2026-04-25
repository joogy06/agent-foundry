#!/usr/bin/env python3
"""test_trusted_runner_bundle_write.py — ecosystem-keystone §5.5 + §7.5 R9.

Covers `trusted_runner.bundle_write` and `trusted_runner.recover_orphan_rollback`
per contract-map `trusted-runner-keystone` test scenarios TS-TR-01..03:

    TS-TR-01 happy-path two-file commit: both files end at expected bytes, no
             orphan rollback dirs left.
    TS-TR-02 simulated second-file rename failure: first file rolled back to
             its pre-image content; the raised BundleWriteError carries a
             `rolled_back_paths` list including the first target.
    TS-TR-03 pkill-between-renames simulation: orphan rollback dir (with
             manifest + pre-image + partially-committed target) is left on
             disk, then `recover_orphan_rollback(project_root)` restores
             every pre-image and returns the txn_id.

Run:
    python -m pytest skills/_meta/tests/test_trusted_runner_bundle_write.py -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import trusted_runner  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _BundleWriteTestBase(unittest.TestCase):
    """Sets up an isolated project_root + rollback_dir per test."""

    def setUp(self):
        self.project_root = Path(tempfile.mkdtemp(prefix="bundle-write-proj-"))
        self.rollback_dir = self.project_root / ".tmp" / "rollback"

    def tearDown(self):
        shutil.rmtree(self.project_root, ignore_errors=True)

    def _count_orphan_txn_dirs(self) -> int:
        if not self.rollback_dir.is_dir():
            return 0
        return sum(1 for p in self.rollback_dir.iterdir() if p.is_dir())


# ---------------------------------------------------------------------------
# TS-TR-01 — happy-path two-file commit
# ---------------------------------------------------------------------------


class TSTR01HappyPathCommitCase(_BundleWriteTestBase):
    """TS-TR-01: two files commit atomically; no residual rollback state."""

    def test_two_file_commit_places_both_bytes(self):
        skeleton = self.project_root / ".design-ledger" / "skeletons" / "home.yaml"
        contract_map = self.project_root / "progress" / "contract-map.yaml"
        writes = [
            (skeleton, b"screen: home\nversion: 2\n"),
            (contract_map, b"components:\n  - id: home\n    version: 2\n"),
        ]
        txn_id = trusted_runner.bundle_write(
            writes, rollback_dir=self.rollback_dir,
        )
        self.assertTrue(isinstance(txn_id, str) and len(txn_id) > 0)
        self.assertTrue(skeleton.is_file())
        self.assertTrue(contract_map.is_file())
        self.assertEqual(skeleton.read_bytes(), b"screen: home\nversion: 2\n")
        self.assertEqual(
            contract_map.read_bytes(),
            b"components:\n  - id: home\n    version: 2\n",
        )

    def test_no_orphan_rollback_dir_after_success(self):
        writes = [
            (self.project_root / "a.yaml", b"x:1"),
            (self.project_root / "b.yaml", b"y:2"),
        ]
        trusted_runner.bundle_write(writes, rollback_dir=self.rollback_dir)
        self.assertEqual(
            self._count_orphan_txn_dirs(), 0,
            "successful bundle_write must not leave rollback scratch behind",
        )

    def test_custom_txn_id_returned_unchanged(self):
        writes = [(self.project_root / "f.yaml", b"v")]
        returned = trusted_runner.bundle_write(
            writes, rollback_dir=self.rollback_dir, txn_id="my-custom-txn",
        )
        self.assertEqual(returned, "my-custom-txn")

    def test_commit_order_is_preserved(self):
        # The write order equals the order given in `writes`.
        out_paths = [
            self.project_root / "first.yaml",
            self.project_root / "second.yaml",
            self.project_root / "third.yaml",
        ]
        writes = list(zip(out_paths, [b"1", b"2", b"3"]))
        trusted_runner.bundle_write(writes, rollback_dir=self.rollback_dir)
        for p, expected in zip(out_paths, (b"1", b"2", b"3")):
            self.assertEqual(p.read_bytes(), expected)

    def test_empty_writes_raises_value_error(self):
        with self.assertRaises(ValueError):
            trusted_runner.bundle_write([], rollback_dir=self.rollback_dir)

    def test_overwrites_existing_file_and_pre_image_not_needed_after_success(self):
        target = self.project_root / "pre.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"OLD")
        trusted_runner.bundle_write(
            [(target, b"NEW")], rollback_dir=self.rollback_dir,
        )
        self.assertEqual(target.read_bytes(), b"NEW")
        self.assertEqual(self._count_orphan_txn_dirs(), 0)


# ---------------------------------------------------------------------------
# TS-TR-02 — second-file rename failure rolls back first file
# ---------------------------------------------------------------------------


class TSTR02RollbackOnSecondRenameFailureCase(_BundleWriteTestBase):
    """TS-TR-02: simulated EIO on 2nd rename → 1st file reverted to pre-image."""

    def test_second_rename_failure_restores_first_file(self):
        first = self.project_root / "first.yaml"
        second = self.project_root / "second.yaml"
        first.parent.mkdir(parents=True, exist_ok=True)
        # Pre-existing content on the first file; its pre-image must be
        # restored when the second commit fails.
        first.write_bytes(b"FIRST-OLD")
        # second does NOT pre-exist.

        writes = [
            (first, b"FIRST-NEW"),
            (second, b"SECOND-NEW"),
        ]

        # Simulate EIO on the SECOND os.replace call only. `atomic_write_bytes`
        # delegates the rename to os.replace (see §5.7 atomic write). We count
        # calls and explode on call #2.
        real_replace = trusted_runner.os.replace
        call_counter = {"n": 0}

        def flaky_replace(src, dst):
            call_counter["n"] += 1
            # The bundle_write internal pre-image write also uses
            # atomic_write_bytes which calls os.replace — those go through
            # the rollback-dir path, NOT under the project's target files.
            # We only want to fail the SECOND target commit. Distinguish by
            # inspecting dst: the pre-image writes land under
            # self.rollback_dir, the target commits land elsewhere.
            if Path(dst).resolve().is_relative_to(self.rollback_dir.resolve()):
                return real_replace(src, dst)
            call_counter["target_n"] = call_counter.get("target_n", 0) + 1
            if call_counter["target_n"] == 2:
                raise OSError(5, "simulated EIO on second rename")
            return real_replace(src, dst)

        with mock.patch.object(
            trusted_runner.os, "replace", side_effect=flaky_replace
        ):
            with self.assertRaises(trusted_runner.BundleWriteError) as ctx:
                trusted_runner.bundle_write(
                    writes, rollback_dir=self.rollback_dir,
                )

        err = ctx.exception
        # Rollback: first file must read back as its pre-image bytes.
        self.assertEqual(first.read_bytes(), b"FIRST-OLD")
        # second file was never successfully committed, must not exist.
        self.assertFalse(second.exists())
        # BundleWriteError metadata must be populated.
        self.assertEqual(err.failed_path, str(second))
        self.assertEqual(err.rolled_back_paths, [str(first)])
        self.assertIsNotNone(err.txn_id)
        # cause chain captures the EIO.
        self.assertIsInstance(err.cause, OSError)
        self.assertEqual(err.cause.errno, 5)

    def test_rollback_preserves_rollback_dir_for_recovery(self):
        """After a failed commit, the rollback dir may remain for the next
        recovery sweep to verify. We tolerate either "deleted" or "left with
        pre-image" — the invariant is that recovery running a second time
        is idempotent.
        """
        first = self.project_root / "a.yaml"
        second = self.project_root / "b.yaml"
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_bytes(b"AOLD")

        real_replace = trusted_runner.os.replace
        call_counter = {"target_n": 0}

        def flaky_replace(src, dst):
            if Path(dst).resolve().is_relative_to(self.rollback_dir.resolve()):
                return real_replace(src, dst)
            call_counter["target_n"] += 1
            if call_counter["target_n"] == 2:
                raise OSError(5, "EIO")
            return real_replace(src, dst)

        with mock.patch.object(
            trusted_runner.os, "replace", side_effect=flaky_replace
        ):
            with self.assertRaises(trusted_runner.BundleWriteError):
                trusted_runner.bundle_write(
                    [(first, b"ANEW"), (second, b"BNEW")],
                    rollback_dir=self.rollback_dir,
                )

        # First file back to its pre-image — this is the load-bearing check.
        self.assertEqual(first.read_bytes(), b"AOLD")
        # Recovery is idempotent even if orphan dir remains.
        restored = trusted_runner.recover_orphan_rollback(self.project_root)
        # Whether or not a restore happened, the final state MUST still be
        # first=AOLD, second missing.
        self.assertEqual(first.read_bytes(), b"AOLD")
        self.assertFalse(second.exists())
        # restored may be empty (nothing orphan) or contain the txn id —
        # both are acceptable depending on where bundle_write chose to
        # cleanup. The load-bearing post-condition is that recovery did
        # not corrupt state.
        self.assertIsInstance(restored, list)


# ---------------------------------------------------------------------------
# TS-TR-03 — pkill-between-renames recovery
# ---------------------------------------------------------------------------


class TSTR03RecoverOrphanRollbackCase(_BundleWriteTestBase):
    """TS-TR-03: orphan rollback dir left by a crashed transaction is
    recovered by `recover_orphan_rollback`, restoring every pre-image."""

    def _build_orphan_transaction(
        self,
        targets: "list[tuple[Path, bytes, bytes | None]]",
        txn_id: str = "orphan-txn-0001",
    ) -> Path:
        """Manually construct an orphan rollback dir as if a previous
        transaction had been SIGKILL'd after writing pre-images + manifest
        and partially committing targets.

        Each entry in `targets` is (target_path, committed_new_bytes,
        original_pre_image_bytes_or_None). If pre_image is None the target
        did not exist pre-transaction; committed_new_bytes represents what
        the crash left on disk (the partial commit).
        """
        txn_dir = self.rollback_dir / txn_id
        txn_dir.mkdir(parents=True, exist_ok=True)
        entries: "list[dict]" = []
        for idx, (target, new_bytes, pre_image_bytes) in enumerate(targets):
            target.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "target": str(target),
                "pre_image": None,
                "existed": False,
            }
            if pre_image_bytes is not None:
                pre_image_name = f"preimage.{idx:04d}.bin"
                (txn_dir / pre_image_name).write_bytes(pre_image_bytes)
                entry["pre_image"] = pre_image_name
                entry["existed"] = True
            entries.append(entry)
            # Simulate partial commit: target holds the new (uncommitted) bytes.
            target.write_bytes(new_bytes)
        manifest = {
            "txn_id": txn_id,
            "created_at": "2026-04-23T00:00:00Z",
            "entries": entries,
        }
        (txn_dir / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True), encoding="utf-8",
        )
        return txn_dir

    def test_manual_orphan_with_existing_pre_images_restored(self):
        first = self.project_root / "skel.yaml"
        second = self.project_root / "cmap.yaml"
        # Both had pre-existing content; the crashed commit overwrote them.
        self._build_orphan_transaction(
            [
                (first, b"SKEL-NEW", b"SKEL-OLD"),
                (second, b"CMAP-NEW", b"CMAP-OLD"),
            ],
            txn_id="orphan-with-pre-images",
        )
        restored = trusted_runner.recover_orphan_rollback(self.project_root)
        self.assertEqual(restored, ["orphan-with-pre-images"])
        # Both files must now hold their PRE-IMAGE bytes (rewound).
        self.assertEqual(first.read_bytes(), b"SKEL-OLD")
        self.assertEqual(second.read_bytes(), b"CMAP-OLD")
        # The orphan dir must be cleaned up.
        self.assertEqual(self._count_orphan_txn_dirs(), 0)

    def test_manual_orphan_with_absent_pre_image_unlinks_target(self):
        # Target did not exist pre-transaction. The crashed commit created
        # it. Recovery must unlink it so state rewinds to "absent".
        created = self.project_root / "new-only.yaml"
        self._build_orphan_transaction(
            [(created, b"PARTIAL", None)],
            txn_id="orphan-absent-preimage",
        )
        self.assertTrue(created.is_file())
        restored = trusted_runner.recover_orphan_rollback(self.project_root)
        self.assertEqual(restored, ["orphan-absent-preimage"])
        self.assertFalse(created.exists(),
                         "recovery must unlink partially-committed absent pre-image")

    def test_recovery_is_idempotent(self):
        target = self.project_root / "idem.yaml"
        self._build_orphan_transaction(
            [(target, b"PARTIAL", b"ORIG")],
            txn_id="idempotent-txn",
        )
        r1 = trusted_runner.recover_orphan_rollback(self.project_root)
        r2 = trusted_runner.recover_orphan_rollback(self.project_root)
        self.assertEqual(r1, ["idempotent-txn"])
        self.assertEqual(r2, [])  # nothing left the second time
        self.assertEqual(target.read_bytes(), b"ORIG")

    def test_recovery_no_rollback_dir_returns_empty(self):
        # Fresh project with no .tmp/rollback/ → no-op, empty list.
        self.assertFalse(self.rollback_dir.exists())
        self.assertEqual(
            trusted_runner.recover_orphan_rollback(self.project_root), [],
        )

    def test_recovery_skips_dir_without_manifest(self):
        # A rollback dir without manifest.json is an in-progress transaction
        # (or garbage) — recovery must leave it alone.
        half = self.rollback_dir / "incomplete-txn"
        half.mkdir(parents=True, exist_ok=True)
        (half / "preimage.0000.bin").write_bytes(b"orphan-bytes")
        restored = trusted_runner.recover_orphan_rollback(self.project_root)
        self.assertEqual(restored, [])
        # The half dir must still exist (we didn't touch it).
        self.assertTrue(half.is_dir())

    def test_recovery_skips_corrupt_manifest(self):
        bad = self.rollback_dir / "bad-txn"
        bad.mkdir(parents=True, exist_ok=True)
        (bad / "manifest.json").write_text("{not valid json", encoding="utf-8")
        # Must not raise; must not claim to have restored it.
        restored = trusted_runner.recover_orphan_rollback(self.project_root)
        self.assertEqual(restored, [])

    def test_subprocess_pkill_simulation_recovers_via_os_exit(self):
        """Spawn a Python subprocess that starts a bundle_write transaction,
        writes its manifest + first target, and then calls os._exit(137)
        BEFORE the second target commits. We verify:

            1. The subprocess leaves an orphan rollback dir on disk.
            2. Calling `recover_orphan_rollback` in THIS process restores
               the first target from its pre-image.

        This exercises the "SIGKILL-mid-transaction" path end-to-end (§5.10).
        """
        # Pre-populate the first target so we have a pre-image to restore to.
        first = self.project_root / "survivor.yaml"
        second = self.project_root / "never-committed.yaml"
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_bytes(b"ORIGINAL")

        # Child-side script. The child imports trusted_runner, monkey-patches
        # os.replace to exit the process right AFTER the first target commit
        # succeeds (i.e., between renames 1 and 2), simulating SIGKILL.
        child_script = textwrap.dedent(f"""
            import os, sys
            sys.path.insert(0, {str(SCRIPT_DIR)!r})
            import trusted_runner

            first  = {str(first)!r}
            second = {str(second)!r}
            rollback_dir = {str(self.rollback_dir)!r}

            real_replace = trusted_runner.os.replace
            counter = {{"target_n": 0}}
            from pathlib import Path as _P
            def kill_between(src, dst):
                # Pre-image writes go into rollback_dir; allow those.
                if _P(dst).resolve().is_relative_to(_P(rollback_dir).resolve()):
                    return real_replace(src, dst)
                counter["target_n"] += 1
                if counter["target_n"] == 1:
                    # Complete the 1st rename normally, THEN kill ourselves
                    # before returning control — the equivalent of a SIGKILL
                    # landing between the first and second rename.
                    result = real_replace(src, dst)
                    os._exit(137)
                return real_replace(src, dst)

            trusted_runner.os.replace = kill_between
            trusted_runner.bundle_write(
                [(_P(first), b"FIRST-COMMITTED"),
                 (_P(second), b"SECOND-NEVER")],
                rollback_dir=_P(rollback_dir),
                txn_id="pkill-sim-txn",
            )
        """).lstrip()

        child_path = self.project_root / "_child.py"
        child_path.write_text(child_script, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(child_path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        # The child MUST have exited non-zero (we os._exit(137)'d it).
        self.assertNotEqual(
            proc.returncode, 0,
            f"expected non-zero exit, got {proc.returncode}; "
            f"stderr={proc.stderr!r}",
        )

        # Post-crash state: first target holds the crashed-in bytes (the
        # commit succeeded before the kill). Second target never existed.
        self.assertEqual(first.read_bytes(), b"FIRST-COMMITTED")
        self.assertFalse(second.exists())

        # Orphan rollback dir MUST be present with a valid manifest.
        orphan_txn_dir = self.rollback_dir / "pkill-sim-txn"
        self.assertTrue(orphan_txn_dir.is_dir())
        self.assertTrue((orphan_txn_dir / "manifest.json").is_file())

        # Now run recovery from this process and verify state rewinds.
        restored = trusted_runner.recover_orphan_rollback(self.project_root)
        self.assertEqual(restored, ["pkill-sim-txn"])
        self.assertEqual(first.read_bytes(), b"ORIGINAL",
                         "recovery must restore first target to pre-image bytes")
        self.assertFalse(second.exists(),
                         "second target never existed; still must not exist")
        # Orphan dir cleaned up.
        self.assertEqual(self._count_orphan_txn_dirs(), 0)


if __name__ == "__main__":
    unittest.main()
