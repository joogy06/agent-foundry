#!/usr/bin/env python3
"""Tests for inventory_history.py — the Evergreening v1 change-record writer.

Covers the §9.1 delta-classification matrix (patch/minor/major/added/removed +
0.x semantics), plugin/mcp diffing, the no-change debounce, the first-probe
no-baseline rule, and the never-raise append boundary. Stdlib unittest only
(cross-model-portable, no pytest dependency).

Run: python3 -m unittest discover -s ~/.claude/skills/env-adoption/tests -v
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

# Load the module under test by path (it lives in ../scripts).
_MOD_PATH = Path(__file__).resolve().parent.parent / "scripts" / "inventory_history.py"
_spec = importlib.util.spec_from_file_location("inventory_history", _MOD_PATH)
ih = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ih)


class TestVersionSeverity(unittest.TestCase):
    """§9.1 delta classification matrix (semver, incl. 0.x convention)."""

    def test_patch_bump(self):
        self.assertEqual(ih.version_severity("2.1.96", "2.1.97"), "patch")

    def test_minor_bump(self):
        self.assertEqual(ih.version_severity("2.1.96", "2.2.0"), "minor")

    def test_major_bump(self):
        self.assertEqual(ih.version_severity("2.9.9", "3.0.0"), "major")

    def test_zerox_second_digit_is_minor(self):
        # 0.x convention: 0.136 -> 0.137 is a MINOR bump (the design's codex case).
        self.assertEqual(ih.version_severity("0.136.0", "0.137.0"), "minor")

    def test_zerox_third_digit_is_patch(self):
        self.assertEqual(ih.version_severity("0.137.0", "0.137.1"), "patch")

    def test_zerox_to_one_is_major(self):
        self.assertEqual(ih.version_severity("0.45.0", "1.0.0"), "major")

    def test_two_component_version(self):
        # Versions like "2.1" (no patch) parse with patch=0.
        self.assertEqual(ih.version_severity("2.1", "2.2"), "minor")

    def test_unparseable_differs_falls_back_to_minor(self):
        self.assertEqual(ih.version_severity("weird", "alsoweird"), "minor")


class TestDiffInventories(unittest.TestCase):
    def _inv(self, tools=None, plugins=None, mcp=None):
        d = {}
        if tools is not None:
            d["tools"] = tools
        if plugins is not None:
            d["plugins"] = plugins
        if mcp is not None:
            d["mcp_servers"] = mcp
        return d

    def test_no_baseline_emits_nothing(self):
        # First-ever probe (prev is None) -> no records (avoids phantom add storm).
        cur = self._inv(tools={"codex": {"installed": True, "version": "0.137.0"}})
        recs = ih.diff_inventories(None, cur, "pid")
        self.assertEqual(recs, [])

    def test_no_change_no_record(self):
        # The debounce primitive: identical snapshots produce zero records.
        t = {"codex": {"installed": True, "version": "0.137.0"}}
        recs = ih.diff_inventories(self._inv(tools=dict(t)), self._inv(tools=dict(t)), "pid")
        self.assertEqual(recs, [])

    def test_cli_version_change(self):
        prev = self._inv(tools={"codex": {"installed": True, "version": "0.136.0"}})
        cur = self._inv(tools={"codex": {"installed": True, "version": "0.137.0"}})
        recs = ih.diff_inventories(prev, cur, "pid")
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r["surface"], "cli")
        self.assertEqual(r["id"], "codex")
        self.assertEqual(r["field"], "version")
        self.assertEqual(r["before"], "0.136.0")
        self.assertEqual(r["after"], "0.137.0")
        self.assertEqual(r["severity"], "minor")
        self.assertEqual(r["schema_version"], "inventory-history.v1")
        self.assertEqual(r["probe_id"], "pid")

    def test_tool_surface_for_non_cli(self):
        prev = self._inv(tools={"docker": {"installed": True, "version": "29.5.2"}})
        cur = self._inv(tools={"docker": {"installed": True, "version": "29.5.3"}})
        recs = ih.diff_inventories(prev, cur, "pid")
        self.assertEqual(recs[0]["surface"], "tool")
        self.assertEqual(recs[0]["severity"], "patch")

    def test_tool_added(self):
        prev = self._inv(tools={"semgrep": {"installed": False, "version": None}})
        cur = self._inv(tools={"semgrep": {"installed": True, "version": "1.2.3"}})
        recs = ih.diff_inventories(prev, cur, "pid")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["field"], "presence")
        self.assertEqual(recs[0]["severity"], "added")
        self.assertEqual(recs[0]["after"], True)

    def test_tool_removed(self):
        prev = self._inv(tools={"semgrep": {"installed": True, "version": "1.2.3"}})
        cur = self._inv(tools={"semgrep": {"installed": False, "version": None}})
        recs = ih.diff_inventories(prev, cur, "pid")
        self.assertEqual(recs[0]["severity"], "removed")
        self.assertEqual(recs[0]["after"], False)

    def test_plugin_version_change(self):
        prev = self._inv(plugins={"superpowers@m": {"enabled": True, "version": "5.0.7"}})
        cur = self._inv(plugins={"superpowers@m": {"enabled": True, "version": "5.1.0"}})
        recs = ih.diff_inventories(prev, cur, "pid")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["surface"], "plugin")
        self.assertEqual(recs[0]["severity"], "minor")

    def test_plugin_added(self):
        prev = self._inv(plugins={"a@m": {"enabled": True, "version": "1.0.0"}})
        cur = self._inv(plugins={"a@m": {"enabled": True, "version": "1.0.0"},
                                 "b@m": {"enabled": True, "version": "2.0.0"}})
        recs = ih.diff_inventories(prev, cur, "pid")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["id"], "b@m")
        self.assertEqual(recs[0]["severity"], "added")

    def test_plugins_partial_coverage_no_churn(self):
        # If one side lacks a plugins map entirely (coverage: partial), do NOT emit
        # add/remove churn from the side that simply had no sensor.
        prev = self._inv(tools={"codex": {"installed": True, "version": "0.137.0"}})
        cur = self._inv(tools={"codex": {"installed": True, "version": "0.137.0"}},
                        plugins={"a@m": {"enabled": True, "version": "1.0.0"}})
        recs = ih.diff_inventories(prev, cur, "pid")
        self.assertEqual(recs, [])  # prev had no plugins map -> no plugin diff

    def test_mcp_added_and_removed(self):
        prev = self._inv(mcp=["pa-server"])
        cur = self._inv(mcp=["pa-server", "wordpress-mcp"])
        recs = ih.diff_inventories(prev, cur, "pid")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["surface"], "mcp")
        self.assertEqual(recs[0]["id"], "wordpress-mcp")
        self.assertEqual(recs[0]["severity"], "added")

        prev2 = self._inv(mcp=["pa-server", "old-mcp"])
        cur2 = self._inv(mcp=["pa-server"])
        recs2 = ih.diff_inventories(prev2, cur2, "pid")
        self.assertEqual(recs2[0]["severity"], "removed")
        self.assertEqual(recs2[0]["id"], "old-mcp")

    def test_multi_change_window(self):
        # Change-records survive a multi-change window (the change-record rationale).
        prev = self._inv(
            tools={"codex": {"installed": True, "version": "0.136.0"},
                   "agy": {"installed": True, "version": "1.0.4"}},
            mcp=["pa-server"])
        cur = self._inv(
            tools={"codex": {"installed": True, "version": "0.137.0"},
                   "agy": {"installed": True, "version": "1.0.5"}},
            mcp=["pa-server", "chrome-devtools"])
        recs = ih.diff_inventories(prev, cur, "pid")
        ids = sorted(r["id"] for r in recs)
        self.assertEqual(ids, ["agy", "chrome-devtools", "codex"])


class TestAppendNeverRaises(unittest.TestCase):
    def test_append_to_tmpdir(self):
        with tempfile.TemporaryDirectory() as td:
            orig = ih.HISTORY_FILE
            orig_state = ih.STATE_DIR
            try:
                ih.STATE_DIR = Path(td)
                ih.HISTORY_FILE = Path(td) / "inventory-history.jsonl"
                recs = [ih._rec("ts", "cli", "codex", "version", "0.1", "0.2", "minor", "p")]
                n = ih.append_records(recs)
                self.assertEqual(n, 1)
                lines = ih.HISTORY_FILE.read_text().strip().splitlines()
                self.assertEqual(len(lines), 1)
                parsed = json.loads(lines[0])
                self.assertEqual(parsed["id"], "codex")
            finally:
                ih.HISTORY_FILE = orig
                ih.STATE_DIR = orig_state

    def test_empty_records_returns_zero(self):
        self.assertEqual(ih.append_records([]), 0)

    def test_append_failure_never_raises(self):
        # Pointing at an un-writable path must NOT raise (best-effort boundary).
        orig = ih.HISTORY_FILE
        orig_state = ih.STATE_DIR
        try:
            ih.STATE_DIR = Path("/proc/nonexistent-dir-xyz")
            ih.HISTORY_FILE = Path("/proc/nonexistent-dir-xyz/h.jsonl")
            n = ih.append_records([ih._rec("t", "cli", "x", "version", "1", "2", "minor", "p")])
            self.assertEqual(n, 0)  # failed silently
        finally:
            ih.HISTORY_FILE = orig
            ih.STATE_DIR = orig_state


if __name__ == "__main__":
    unittest.main(verbosity=2)
