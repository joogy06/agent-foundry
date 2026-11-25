#!/usr/bin/env python3
"""rot-report staleness alarm (2026-09-27): the digest names the report's age and alarms
past 14 days; the rot scan grades external_fact anchors and visits every skill.

stdlib unittest. Run:
  python3 -m unittest discover -s ~/.claude/skills/_meta/tests -p 'test_rot_staleness.py' -v
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_META = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_META))
import rot_staleness as rst  # noqa: E402

_spec = importlib.util.spec_from_file_location("rot_scan_for_staleness", _META / "rot_scan.py")
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)

_NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)


def _iso(days_ago: float) -> str:
    return (_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Segment(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "rot-report.json"   # absent: no mtime fallback

    def test_fresh_report_is_silent(self):
        self.assertIsNone(rst.segment({"generated_at": _iso(3), "last_success": True}, self.path, _NOW))

    def test_past_seven_days_is_a_note_with_the_age(self):
        self.assertEqual(rst.segment({"generated_at": _iso(9), "last_success": True}, self.path, _NOW), "rot scan stale (9 days old)")

    def test_past_fourteen_days_is_an_alarm_with_the_age_and_the_fix(self):
        seg = rst.segment({"generated_at": _iso(60), "last_success": True}, self.path, _NOW)
        self.assertIn("rot-report 60 days old", seg)
        self.assertIn("ALARM >14d", seg)
        self.assertIn("rot_scan.py --refresh", seg)

    def test_generated_at_beats_mtime(self):
        # A report copied or touched recently still says how old its SCAN is.
        self.path.write_text("{}", encoding="utf-8")
        self.assertIn("ALARM", rst.segment({"generated_at": _iso(30), "last_success": True}, self.path, _NOW))

    def test_mtime_is_the_fallback(self):
        self.path.write_text("{}", encoding="utf-8")
        old = (_NOW - timedelta(days=20)).timestamp()
        os.utime(self.path, (old, old))
        self.assertIn("ALARM", rst.segment({}, self.path, _NOW))


    def test_bad_timestamp_is_not_fresh_even_with_a_fresh_mtime(self):
        # Fix round 2 (finding 6): the mtime says when the file was written, not whether the
        # scan in it succeeded. A report with no parseable generated_at is invalid.
        self.path.write_text("{}", encoding="utf-8")
        os.utime(self.path, (_NOW.timestamp(), _NOW.timestamp()))
        self.assertIn("ALARM", rst.segment({"generated_at": "not a date", "last_success": True},
                                           self.path, _NOW))


class FixRound1(unittest.TestCase):
    """C4: a failed scan, a missing report and a fixture scan must not read as fresh."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "rot-report.json"
        self.history = self.dir / "rot-history.jsonl"

    def _history(self, *rows):
        self.history.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def test_failed_scan_is_not_fresh_and_falls_back_to_last_success(self):
        self._history({"generated_at": _iso(40), "last_success": True},
                      {"generated_at": _iso(1), "last_success": False})
        seg = rst.segment({"generated_at": _iso(1), "last_success": False}, self.path, _NOW)
        self.assertIsNotNone(seg)
        self.assertIn("40 days", seg)
        self.assertIn("ALARM", seg)

    def test_failed_scan_with_recent_success_in_history_still_names_the_failure(self):
        self._history({"generated_at": _iso(2), "last_success": True})
        seg = rst.segment({"generated_at": _iso(0.5), "last_success": False}, self.path, _NOW)
        self.assertIsNotNone(seg)
        self.assertIn("last rot scan failed", seg)

    def test_failed_scan_with_no_success_on_record_alarms(self):
        seg = rst.segment({"generated_at": _iso(0.5), "last_success": False}, self.path, _NOW)
        self.assertIn("ALARM", seg)
        self.assertIn("no successful", seg)

    def test_missing_report_emits_a_note(self):
        seg = rst.segment(None, self.path, _NOW)
        self.assertIsNotNone(seg)
        self.assertIn("missing", seg)

    def test_rot_scan_refuses_to_write_the_live_report_for_a_custom_root(self):
        called = []
        orig = rs.write_report
        rs.write_report = lambda report: called.append(report)
        try:
            with self.assertRaises(SystemExit) as cm:
                rs.main(["--root", str(self.dir)])
            self.assertEqual(cm.exception.code, 2)
            self.assertEqual(rs.main(["--root", str(self.dir), "--no-write"]), 0)
        finally:
            rs.write_report = orig
        self.assertEqual(called, [])


class FixRound2(unittest.TestCase):
    """Finding 6: overrides never write the live report; a corrupt fresh report is not fresh."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "rot-report.json"
        self.history = self.dir / "rot-history.jsonl"

    def _fresh_file(self, text: str):
        self.path.write_text(text, encoding="utf-8")
        os.utime(self.path, (_NOW.timestamp(), _NOW.timestamp()))

    def test_every_override_without_no_write_is_refused(self):
        called = []
        orig = rs.write_report
        rs.write_report = lambda report: called.append(report)
        try:
            for extra in (["--agents", str(self.dir)], ["--today", "2020-01-01"],
                          ["--inventory", str(self.dir / "inv.json")]):
                with self.assertRaises(SystemExit, msg=extra) as cm:
                    rs.main(extra)
                self.assertEqual(cm.exception.code, 2, extra)
            self.assertEqual(rs.main(["--today", "2020-01-01", "--agents", str(self.dir),
                                      "--root", str(self.dir), "--no-write"]), 0)
        finally:
            rs.write_report = orig
        self.assertEqual(called, [])

    def test_corrupt_reports_with_a_fresh_mtime_alarm_without_history(self):
        for text, parsed in (("not json", None), ("null", None), ("{}", {}), ("[]", []),
                             ('{"counts": {"RED": 0}}', {"counts": {"RED": 0}})):
            self._fresh_file(text)
            seg = rst.segment(parsed, self.path, _NOW, history=self.history)
            self.assertIsNotNone(seg, text)
            self.assertIn("ALARM", seg, text)
            self.assertIn("no successful", seg, text)

    def test_corrupt_report_falls_back_to_the_last_success_in_history(self):
        self.history.write_text(json.dumps({"generated_at": _iso(20), "last_success": True}) + "\n",
                                encoding="utf-8")
        self._fresh_file("[]")
        seg = rst.segment([], self.path, _NOW, history=self.history)
        self.assertIn("20 days", seg)
        self.assertIn("ALARM", seg)
        self.history.write_text(json.dumps({"generated_at": _iso(2), "last_success": True}) + "\n",
                                encoding="utf-8")
        seg = rst.segment([], self.path, _NOW, history=self.history)
        self.assertIsNotNone(seg)            # never silent: the report itself is unreadable
        self.assertIn("invalid", seg)

    def test_cli_reads_an_unparseable_report_as_invalid(self):
        self._fresh_file("{not json")
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rst.main(["--report", str(self.path)])
        self.assertIn("ALARM", buf.getvalue())


class Digest(unittest.TestCase):
    """The alarm reaches the SessionStart digest on its own (a standalone class)."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location("freshness_nudge_for_staleness", _META / "freshness_nudge.py")
        self.fn = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.fn)
        self.td = Path(tempfile.mkdtemp())
        fresh = self.td / "freshness"
        fresh.mkdir()
        for name, value in {
            "STATE": self.td, "FRESH": fresh, "INVENTORY": self.td / "inventory.json",
            "HISTORY": self.td / "inventory-history.jsonl", "ROT_REPORT": fresh / "rot-report.json",
            "IDENTITY_REPORT": fresh / "identity-report.json", "INDEX": fresh / "index.json",
            "ACK": fresh / "ack.json", "CODEX_ROSTER": self.td / "codex" / "models_cache.json",
            "CODEX_SESSIONS": self.td / "codex" / "sessions", "AGY_ROSTER": self.td / "agy.json",
            "SEAT_PINS": self.td / "pins.json", "SEAT_TOPS": self.td / "tops.json",
            "MODEL_POLICY": self.td / "model-policy.yaml", "CLAUDE_PROJECTS": self.td / "projects",
            "INSTALLED_ROSTER": self.td / "meta" / "model_roster.py", "SESSION_CWD": self.td / "cwd",
        }.items():
            setattr(self.fn, name, value)
        self.fn._seat_model_segments = lambda ack, now: ([], [])   # isolate from seat state

    def digest(self, generated_days_ago: float):
        self.fn.ROT_REPORT.write_text(json.dumps({"counts": {"RED": 0}, "generated_at": _iso(generated_days_ago),
                                                  "last_success": True}),
                                      encoding="utf-8")
        line, _ = self.fn.build_digest(_NOW.date(), _NOW)
        return line

    def test_stale_report_alarms_alone(self):
        line = self.digest(60)
        self.assertIsNotNone(line)
        self.assertIn("rot-report 60 days old", line)

    def test_fresh_report_stays_silent(self):
        self.assertIsNone(self.digest(2))


class RotScan(unittest.TestCase):
    def test_expired_external_fact_is_red(self):
        parsed = {"volatility": "high", "anchors": [{"kind": "external_fact", "subject": "x",
                                                      "source_url": "https://e.com", "review_by": "2026-09-01"}]}
        found = rs._grade_freshness("s/SKILL.md", parsed, {}, date(2026, 9, 27))
        self.assertEqual([f["verdict"] for f in found], ["RED"])
        self.assertEqual(found[0]["kind"], "external_fact")

    def test_future_external_fact_is_green(self):
        parsed = {"anchors": [{"kind": "external_fact", "review_by": "2027-06-01"}]}
        found = rs._grade_freshness("s/SKILL.md", parsed, {}, date(2026, 9, 27))
        self.assertEqual([f["verdict"] for f in found], ["GREEN"])

    def test_dated_anchor_without_a_parseable_review_by_is_vague(self):
        for kind in ("external_fact", "status_snapshot"):
            for review in (None, "someday"):
                anchor = {"kind": kind, "subject": "x"}
                if review:
                    anchor["review_by"] = review
                found = rs._grade_freshness("s/SKILL.md", {"anchors": [anchor]}, {}, date(2026, 9, 27))
                self.assertEqual([f["verdict"] for f in found], ["VAGUE"], (kind, review))

    def test_scan_visits_every_skill_including_new_ones(self):
        # The walker globs; no skill list to forget. markdown-for-agents was missed only
        # because the scan had not RUN since the skill was created.
        skills = _META.parent
        visited = {p.relative_to(skills).as_posix() for p in rs.iter_targets(skills, skills / "__none__")}
        for name in ("markdown-for-agents", "ai-assistant-referrals", "ai-search-optimizer"):
            self.assertIn(f"{name}/SKILL.md", visited)
        expected = {p.relative_to(skills).as_posix() for p in skills.glob("*/SKILL.md")}
        self.assertEqual(expected - visited, set())


if __name__ == "__main__":
    unittest.main()
