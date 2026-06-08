#!/usr/bin/env python3
"""Tests for freshness_nudge.py (Evergreening v1, S041).

Covers the §6.3 nudge policy table (each row -> digest/silence), the ack /
ack_until / max-2-per-14-days dedup, the quiet-session suppressOutput envelope
(§9.3), and the <500ms latency budget (§9.2) measured against a controlled state
tree (no subprocess — direct in-process timing of build_digest).

stdlib unittest. Run:
  python3 -m unittest discover -s ~/.claude/skills/_meta/tests -p 'test_freshness_nudge.py' -v
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import time
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

_META = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("freshness_nudge", _META / "freshness_nudge.py")
fn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fn)

_NOW = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 6, 5)


class _StateFixture:
    """Redirect the module's state paths into a temp dir and seed feed files."""

    def __init__(self, td: Path):
        self.td = td
        self.fresh = td / "freshness"
        self.fresh.mkdir(parents=True, exist_ok=True)
        self._orig = {}

    def __enter__(self):
        for name in ("STATE", "FRESH", "INVENTORY", "HISTORY", "ROT_REPORT",
                     "IDENTITY_REPORT", "INDEX", "ACK"):
            self._orig[name] = getattr(fn, name)
        fn.STATE = self.td
        fn.FRESH = self.fresh
        fn.INVENTORY = self.td / "inventory.json"
        fn.HISTORY = self.td / "inventory-history.jsonl"
        fn.ROT_REPORT = self.fresh / "rot-report.json"
        fn.IDENTITY_REPORT = self.fresh / "identity-report.json"
        fn.INDEX = self.fresh / "index.json"
        fn.ACK = self.fresh / "ack.json"
        return self

    def __exit__(self, *a):
        for k, v in self._orig.items():
            setattr(fn, k, v)

    def history(self, records):
        fn.HISTORY.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    def rot(self, red):
        fn.ROT_REPORT.write_text(json.dumps({"counts": {"RED": red}, "schema_version": "rot-report.v1"}))

    def identity(self, status, mismatch_count=0):
        fn.IDENTITY_REPORT.write_text(json.dumps({"status": status, "mismatch_count": mismatch_count}))

    def index(self, by_deadline):
        fn.INDEX.write_text(json.dumps({"by_deadline": by_deadline}))

    def inventory(self):
        fn.INVENTORY.write_text(json.dumps({"version": 1}))


def _rec(surface, _id, field, before, after, severity, ts="2026-06-05T11:00:00Z"):
    return {"schema_version": "inventory-history.v1", "ts": ts, "surface": surface,
            "id": _id, "field": field, "before": before, "after": after,
            "severity": severity, "probe_id": "p"}


class TestPolicyTable(unittest.TestCase):
    def test_minor_bump_yes(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.history([_rec("cli", "codex", "version", "0.136.0", "0.137.0", "minor")])
            digest, _ = fn.build_digest(_TODAY, _NOW)
            self.assertIsNotNone(digest)
            self.assertIn("codex 0.136.0→0.137.0 (minor)", digest)

    def test_major_bump_yes(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.history([_rec("plugin", "superpowers@m", "version", "5.1.0", "6.0.0", "major")])
            digest, _ = fn.build_digest(_TODAY, _NOW)
            self.assertIsNotNone(digest)
            self.assertIn("major", digest)

    def test_patch_bump_silent(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.history([_rec("cli", "claude", "version", "2.1.162", "2.1.163", "patch")])
            digest, _ = fn.build_digest(_TODAY, _NOW)
            self.assertIsNone(digest)  # patch -> SILENT

    def test_added_yes(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.history([_rec("mcp", "wordpress-mcp", "presence", False, True, "added")])
            digest, _ = fn.build_digest(_TODAY, _NOW)
            self.assertIsNotNone(digest)
            self.assertIn("wordpress-mcp added", digest)

    def test_removed_yes(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.history([_rec("plugin", "old@m", "presence", True, False, "removed")])
            digest, _ = fn.build_digest(_TODAY, _NOW)
            self.assertIsNotNone(digest)
            self.assertIn("removed", digest)

    def test_rot_red_yes(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.rot(4)
            digest, _ = fn.build_digest(_TODAY, _NOW)
            self.assertIsNotNone(digest)
            self.assertIn("4 rot RED", digest)

    def test_rot_zero_silent(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.rot(0)
            digest, _ = fn.build_digest(_TODAY, _NOW)
            self.assertIsNone(digest)

    def test_deadline_within_horizon_yes(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.index([{"target": "skills/gemini-cli/SKILL.md", "date": "2026-06-18",
                       "kind": "retirement", "volatility": "medium"}])
            digest, _ = fn.build_digest(_TODAY, _NOW)
            self.assertIsNotNone(digest)
            self.assertIn("deadline", digest)

    def test_identity_mismatch_critical_yes(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.identity("mismatch", mismatch_count=1)
            digest, _ = fn.build_digest(_TODAY, _NOW)
            self.assertIsNotNone(digest)
            self.assertIn("MISMATCH", digest)
            self.assertIn("CRITICAL", digest)

    def test_identity_match_silent(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.identity("match")
            digest, _ = fn.build_digest(_TODAY, _NOW)
            self.assertIsNone(digest)

    def test_everything_quiet_is_silent(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.history([_rec("cli", "claude", "version", "2.1.162", "2.1.163", "patch")])
            sf.rot(0)
            sf.identity("match")
            sf.index([])
            digest, _ = fn.build_digest(_TODAY, _NOW)
            self.assertIsNone(digest)

    def test_digest_ends_actionably(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.rot(4)
            digest, _ = fn.build_digest(_TODAY, _NOW)
            self.assertIn("run the version sweep", digest)
            self.assertIn("alf_sweep_launcher.sh version", digest)


class TestDedup(unittest.TestCase):
    def test_same_fingerprint_capped_at_2(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            rec = _rec("cli", "codex", "version", "0.136.0", "0.137.0", "minor")
            # 1st nudge
            sf.history([rec])
            d1, ack1 = fn.build_digest(_TODAY, _NOW)
            fn.save_ack(ack1)
            self.assertIsNotNone(d1)
            # reset watermark so the record is reconsidered, 2nd nudge
            ack1["watermark_ts"] = None
            fn.save_ack(ack1)
            d2, ack2 = fn.build_digest(_TODAY, _NOW)
            fn.save_ack(ack2)
            self.assertIsNotNone(d2)  # 2nd still fires
            # 3rd: capped
            ack2["watermark_ts"] = None
            fn.save_ack(ack2)
            d3, _ = fn.build_digest(_TODAY, _NOW)
            self.assertIsNone(d3)  # capped at 2 within 14d

    def test_deadline_never_suppressed_by_ack(self):
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.index([{"target": "skills/x/SKILL.md", "date": "2026-06-18",
                       "kind": "retirement", "volatility": "medium"}])
            # even after many runs, a deadline always fires (always-on class)
            for _ in range(5):
                d, ack = fn.build_digest(_TODAY, _NOW)
                fn.save_ack(ack)
                self.assertIsNotNone(d)


class TestEnvelope(unittest.TestCase):
    def test_quiet_envelope_zero_text(self):
        # §9.3: no-change state -> hook emits a suppressOutput envelope, zero text.
        import io
        import contextlib
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.rot(0)
            sf.identity("match")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                fn.emit_hook(None)
            out = json.loads(buf.getvalue())
            self.assertEqual(out, {"continue": True, "suppressOutput": True})
            self.assertNotIn("additionalContext", out.get("hookSpecificOutput", {}))

    def test_digest_envelope_has_context(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn.emit_hook("[evergreen] something")
        out = json.loads(buf.getvalue())
        self.assertTrue(out["continue"])
        self.assertTrue(out["suppressOutput"])
        self.assertEqual(out["hookSpecificOutput"]["additionalContext"], "[evergreen] something")


class TestLatency(unittest.TestCase):
    def test_build_digest_under_500ms(self):
        # §9.2 hard budget. Build a realistic-ish feed set and time build_digest
        # in-process (no subprocess overhead — the hook itself is python3 startup +
        # this call; the call must be the cheap part).
        with tempfile.TemporaryDirectory() as td, _StateFixture(Path(td)) as sf:
            sf.inventory()
            sf.history([_rec("cli", "codex", "version", "0.136.0", "0.137.0", "minor")] * 50)
            sf.rot(4)
            sf.identity("match")
            sf.index([{"target": f"skills/s{i}/SKILL.md", "date": "2026-06-18",
                       "kind": "retirement", "volatility": "medium"} for i in range(20)])
            # warm + measure best-of-3
            best = 1e9
            for _ in range(3):
                t = time.perf_counter()
                fn.build_digest(_TODAY, _NOW)
                best = min(best, (time.perf_counter() - t) * 1000)
            self.assertLess(best, 500.0, f"build_digest took {best:.1f}ms (budget 500ms)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
