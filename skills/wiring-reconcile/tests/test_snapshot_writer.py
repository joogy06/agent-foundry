#!/usr/bin/env python3
"""Unit tests for snapshot_writer — canonical JSON + atomic write."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from snapshot_writer import (  # noqa: E402
    canonical_json,
    canonical_json_bytes,
    write_snapshot_atomic,
    read_snapshot,
)


class TestCanonicalJson(unittest.TestCase):

    def test_sort_keys(self):
        self.assertEqual(
            canonical_json({"b": 1, "a": 2}),
            '{"a":2,"b":1}',
        )

    def test_no_whitespace(self):
        out = canonical_json({"k": [1, 2, 3], "m": {"x": True}})
        self.assertNotIn(" ", out)
        self.assertNotIn("\n", out)

    def test_nested_order_stable(self):
        self.assertEqual(
            canonical_json({"outer": {"z": 1, "a": 2}}),
            '{"outer":{"a":2,"z":1}}',
        )

    def test_bytes_utf8(self):
        self.assertEqual(canonical_json_bytes({"x": "test"}), b'{"x":"test"}')

    def test_matches_meta_gates_canonical_json_behavior(self):
        """Must match `_meta/gates.py canonical_json` exactly.

        Load gates.py's canonical_json and compare on a known payload.
        """
        meta_path = Path.home() / ".claude" / "skills" / "_meta"
        sys.path.insert(0, str(meta_path))
        try:
            import gates as _gates  # type: ignore
        except ImportError:
            self.skipTest("_meta/gates.py not importable")
        payload = {"b": [3, 1, 2], "a": {"nested": True, "arr": [{"k": 1}]}, "z": "x"}
        self.assertEqual(canonical_json(payload), _gates.canonical_json(payload))


class TestAtomicWrite(unittest.TestCase):

    def test_write_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "snap.json"
            body = {"schema_version": "1.0.0", "edges": [{"edge_id": "a" * 16}]}
            write_snapshot_atomic(p, body)
            self.assertTrue(p.is_file())
            self.assertEqual(read_snapshot(p), body)

    def test_canonical_bytes_on_disk(self):
        """File contents must equal canonical_json_bytes output."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "snap.json"
            body = {"z": 1, "a": 2, "arr": [3, 1, 2]}
            write_snapshot_atomic(p, body)
            disk = p.read_bytes()
            self.assertEqual(disk, canonical_json_bytes(body))

    def test_no_partial_on_overwrite(self):
        """Overwrite must still produce a valid JSON file (atomic semantics)."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "snap.json"
            write_snapshot_atomic(p, {"k": 1})
            write_snapshot_atomic(p, {"k": 2})
            self.assertEqual(read_snapshot(p), {"k": 2})

    def test_tmp_files_cleaned_up(self):
        """No .tmp.* siblings should remain after a successful write."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "snap.json"
            write_snapshot_atomic(p, {"x": 1})
            leftovers = list(Path(td).glob("snap.json.tmp*"))
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
