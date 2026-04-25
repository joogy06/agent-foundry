#!/usr/bin/env python3
"""test_atomic_write_crash.py — tester-split design §5.7 verification.

Covers `trusted_runner.atomic_write_bytes` / `atomic_write_bundle`:

  - Normal write places bytes at the destination path.
  - Temp file is created in the SAME directory as the destination (so the
    rename stays intra-filesystem and remains atomic).
  - Crash mid-write (monkey-patched os.replace) leaves NO partial file at
    the destination path; a parallel reader sees either the old file or
    no file at all — never a torn write.
  - atomic_write_bundle names the file `<bundle_hash>.bundle.json` and
    returns (path, hash) matching bundle_hash_hex(bundle).
  - Re-writing the same bundle is idempotent: same path, same hash,
    identical bytes on disk.

Run:
    python -m pytest skills/_meta/tests/test_atomic_write_crash.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import trusted_runner  # noqa: E402


class AtomicWriteBytesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="atomic-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_normal_write_places_bytes(self):
        target = self.tmp / "a" / "b" / "file.json"
        trusted_runner.atomic_write_bytes(target, b'{"k":1}')
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), b'{"k":1}')

    def test_no_temp_file_left_after_success(self):
        target = self.tmp / "file.json"
        trusted_runner.atomic_write_bytes(target, b"payload")
        leftovers = [
            p for p in self.tmp.iterdir()
            if p.name != "file.json"
        ]
        self.assertEqual(leftovers, [], f"unexpected tempfiles: {leftovers}")

    def test_temp_file_created_in_same_directory_as_destination(self):
        target = self.tmp / "deeper" / "dst.json"
        observed_dirs = []
        real_mkstemp = tempfile.mkstemp

        def spy_mkstemp(*args, **kwargs):
            observed_dirs.append(kwargs.get("dir"))
            return real_mkstemp(*args, **kwargs)

        with mock.patch.object(trusted_runner.tempfile, "mkstemp", side_effect=spy_mkstemp):
            trusted_runner.atomic_write_bytes(target, b"x")

        self.assertEqual(len(observed_dirs), 1)
        self.assertEqual(Path(observed_dirs[0]).resolve(), target.parent.resolve())

    def test_crash_mid_write_leaves_no_partial_target(self):
        """Simulate kill between fsync and rename: no target file visible."""
        target = self.tmp / "crash.json"

        # Pre-existing content that a parallel reader might be holding.
        # Write it via plain write so we know what "old" looks like.
        target.write_bytes(b'{"old":true}')

        def exploding_replace(src, dst):
            # Simulate kill -9 / OOM between fsync and rename.
            raise KeyboardInterrupt("simulated crash")

        with mock.patch.object(trusted_runner.os, "replace", side_effect=exploding_replace):
            with self.assertRaises(KeyboardInterrupt):
                trusted_runner.atomic_write_bytes(target, b'{"new":true}')

        # The old bytes are still there — no torn write.
        self.assertEqual(target.read_bytes(), b'{"old":true}')
        # The temp file must have been cleaned up by our except-clause.
        leftovers = [p for p in self.tmp.iterdir() if p.name != "crash.json"]
        self.assertEqual(leftovers, [], f"stray tempfiles: {leftovers}")

    def test_crash_after_write_before_rename_never_exposes_partial_at_target(self):
        """A reader watching the target path never sees partial bytes."""
        target = self.tmp / "watch.json"
        # target does NOT exist yet.
        self.assertFalse(target.exists())

        def exploding_replace(src, dst):
            # Target still absent at this point. Reader watching dst sees nothing.
            self.assertFalse(Path(dst).exists(),
                             f"target unexpectedly exists pre-rename: {dst}")
            raise RuntimeError("simulated crash")

        with mock.patch.object(trusted_runner.os, "replace", side_effect=exploding_replace):
            with self.assertRaises(RuntimeError):
                trusted_runner.atomic_write_bytes(target, b"partial-payload")

        # Target must still not exist.
        self.assertFalse(target.exists())


class AtomicWriteBundleCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bundle-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sample_bundle(self, **overrides):
        b = {
            "component_id": "auth",
            "produced_by": "bob-trusted-runner",
            "run_at": "2026-04-21T00:00:00Z",
            "results": [],
        }
        b.update(overrides)
        return b

    def test_returns_path_and_hash_matching_helper(self):
        bundle = self._sample_bundle()
        expected_hash = trusted_runner.bundle_hash_hex(bundle)
        path, got_hash = trusted_runner.atomic_write_bundle(bundle, self.tmp)
        self.assertEqual(got_hash, expected_hash)
        self.assertEqual(path.name, f"{expected_hash}.bundle.json")
        self.assertTrue(path.is_file())

    def test_persisted_bytes_round_trip_and_contain_hash(self):
        bundle = self._sample_bundle()
        path, h = trusted_runner.atomic_write_bundle(bundle, self.tmp)
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        # The persisted form includes bundle_hash for consumer convenience.
        self.assertEqual(on_disk["bundle_hash"], h)
        # Round-trip: recomputing the hash on the on-disk form (hash excluded
        # by canonical_bundle_bytes) matches the recorded hash.
        self.assertEqual(trusted_runner.bundle_hash_hex(on_disk), h)

    def test_idempotent_rewrite_same_bytes(self):
        bundle = self._sample_bundle()
        p1, h1 = trusted_runner.atomic_write_bundle(bundle, self.tmp)
        b1 = p1.read_bytes()
        p2, h2 = trusted_runner.atomic_write_bundle(bundle, self.tmp)
        self.assertEqual(p1, p2)
        self.assertEqual(h1, h2)
        self.assertEqual(b1, p2.read_bytes())

    def test_canonical_bundle_bytes_excludes_bundle_hash(self):
        a = self._sample_bundle()
        b = self._sample_bundle()
        b["bundle_hash"] = "deadbeef"
        self.assertEqual(
            trusted_runner.canonical_bundle_bytes(a),
            trusted_runner.canonical_bundle_bytes(b),
        )

    def test_different_content_different_hash(self):
        a = self._sample_bundle(component_id="a")
        b = self._sample_bundle(component_id="b")
        self.assertNotEqual(
            trusted_runner.bundle_hash_hex(a),
            trusted_runner.bundle_hash_hex(b),
        )


if __name__ == "__main__":
    unittest.main()
