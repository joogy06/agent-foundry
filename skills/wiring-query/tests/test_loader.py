#!/usr/bin/env python3
"""test_loader.py — coverage for wiring-query snapshot loader."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(FIXTURE_DIR))

from loader import load_snapshot, SnapshotMissing, SnapshotInvalid, clear_cache, cache_size  # noqa: E402
from make_fixture_snapshot import write_fixture  # noqa: E402


class LoaderCase(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp(prefix="wiring-query-loader-"))
        clear_cache()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_snapshot_raises(self):
        # `.wiring/latest.json` absent
        with self.assertRaises(SnapshotMissing):
            load_snapshot(self.tmpdir)

    def test_load_happy_path(self):
        write_fixture(self.tmpdir)
        snap = load_snapshot(self.tmpdir)
        self.assertEqual(snap["schema_version"], "1.0.0")
        self.assertGreater(len(snap["edges"]), 0)

    def test_invalid_json_raises(self):
        (self.tmpdir / ".wiring").mkdir()
        (self.tmpdir / ".wiring" / "latest.json").write_text("NOT JSON")
        with self.assertRaises(SnapshotInvalid):
            load_snapshot(self.tmpdir)

    def test_missing_required_keys_raises(self):
        (self.tmpdir / ".wiring").mkdir()
        (self.tmpdir / ".wiring" / "latest.json").write_text(json.dumps({"x": 1}))
        with self.assertRaises(SnapshotInvalid):
            load_snapshot(self.tmpdir)

    def test_caching_same_project_dir(self):
        write_fixture(self.tmpdir)
        clear_cache()
        _ = load_snapshot(self.tmpdir)
        self.assertEqual(cache_size(), 1)
        _ = load_snapshot(self.tmpdir)
        self.assertEqual(cache_size(), 1)

    def test_load_performance_under_300ms(self):
        """300ms cold-load target per design §5.3 perf budget."""
        import time
        write_fixture(self.tmpdir)
        clear_cache()
        t0 = time.perf_counter()
        load_snapshot(self.tmpdir)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 300.0,
                        f"cold load took {elapsed_ms:.2f}ms, budget 300ms")


if __name__ == "__main__":
    unittest.main()
