#!/usr/bin/env python3
"""test_effort_rollup.py -- #311 phase 1: the read-only rollup and the digest ratio (design s3.5).

Also the fixture version of design s6 item 4: plan -> `effort_policy.py wp` -> `record-dispatch`
-> workflows/bob-stage.js (real bytes, stub agent, under node) -> `record-outcome` from the
workflow's dispatch block -> effort_rollup reads the joined rows. The live version of that chain
is a main-loop run and is not reproducible from a test.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_META = Path(__file__).resolve().parent.parent
_TESTS = Path(__file__).resolve().parent
for p in (_META, _TESTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import effort_policy as ep  # noqa: E402
import effort_rollup as er  # noqa: E402

_NODE = shutil.which("node")
_POLICY_CLI = _META / "effort_policy.py"
_ROLLUP_CLI = _META / "effort_rollup.py"


def _pair(did, grade, effort, status, attempt=1, source="grade"):
    d = ep.dispatch_row(dispatch_id=did, task_key="P:" + did, effort_source=source,
                        effort_requested=effort, grade=grade, attempt=attempt)
    o = ep.outcome_row(dispatch_id=did, task_key="P:" + did, status=status, attempt=attempt)
    return [d, o]


class Rollup(unittest.TestCase):
    def test_a_small_cell_is_insufficient_and_shows_no_rate(self):
        rows = _pair("a1", "S", "low", "COMPLETE") + _pair("a2", "S", "low", "FAILED")
        doc = er.rollup(rows)
        self.assertEqual(doc["cells"], [{"grade": "S", "effort": "low", "n": 2, "pass": 1,
                                         "pass_at_1": None, "status": "insufficient"}])
        self.assertEqual(doc["proposals"], [])

    def test_thirty_first_attempts_give_a_rate(self):
        rows = []
        for i in range(30):
            rows += _pair(f"m{i}", "M", "medium", "COMPLETE" if i < 24 else "PARTIAL")
        cell = er.rollup(rows)["cells"][0]
        self.assertEqual((cell["n"], cell["pass"], cell["pass_at_1"], cell["status"]), (30, 24, 0.8, "ok"))

    def test_only_joined_first_attempts_count(self):
        rows = _pair("x1", "L", "high", "COMPLETE")
        rows += _pair("x2", "L", "high", "FAILED", attempt=2)                       # a retry: not pass@1
        rows.append(ep.dispatch_row(dispatch_id="x3", task_key="P:x3", effort_source="grade",
                                    effort_requested="high", grade="L"))            # open: no outcome
        rows.append(ep.outcome_row(dispatch_id="ghost", task_key="P:g", status="COMPLETE"))
        rows.append({"tool": "codex_watch", "status": "ok"})
        doc = er.rollup(rows)
        self.assertEqual([(c["grade"], c["n"]) for c in doc["cells"]], [("L", 1)])
        self.assertEqual((doc["open"], doc["retries"], doc["orphan_outcomes"], doc["other_rows"]), (1, 1, 1, 1))

    def test_promotion_and_ungraded_cells_are_kept_apart(self):
        rows = _pair("p1", "S", "medium", "COMPLETE", source="promotion")
        rows += _pair("u1", None, "high", "COMPLETE", source="default-ungraded")
        doc = er.rollup(rows)
        self.assertEqual([(c["grade"], c["effort"]) for c in doc["cells"]], [("-", "high"), ("S", "medium")])
        self.assertEqual(doc["by_effort_source"], {"default-ungraded": 1, "promotion": 1})

    def test_claude_spawn_counts_ignore_every_other_writer(self):
        rows = _pair("g1", "S", "low", "COMPLETE") + _pair("g2", "M", "high", "COMPLETE", source="promotion")
        rows += _pair("u1", None, "high", "COMPLETE", source="default-ungraded")
        rows += [{"tool": "codex_watch"}] * 50 + [{"tool": "audit_claude"}]
        self.assertEqual(er.claude_spawn_counts(rows), (2, 3))

    def test_the_cli_reads_the_store_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for r in _pair("c1", "S", "low", "COMPLETE"):
                ep.record(root, r)
            with ep.store_path(root).open("a", encoding="utf-8") as fh:
                fh.write("not json\n")
            before = ep.store_path(root).read_bytes()
            proc = subprocess.run([sys.executable, str(_ROLLUP_CLI), "--project-root", td, "--json"],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            doc = json.loads(proc.stdout)
            self.assertEqual((doc["cells"][0]["n"], doc["skipped_lines"]), (1, 1))
            self.assertEqual(ep.store_path(root).read_bytes(), before)
            text = subprocess.run([sys.executable, str(_ROLLUP_CLI), "--project-root", td],
                                  capture_output=True, text=True, timeout=60).stdout
            self.assertIn("insufficient", text)


class DigestRatio(unittest.TestCase):
    def test_the_ratio_counts_graded_claude_spawns_over_claude_spawns(self):
        import freshness_nudge as fn
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cwd = os.getcwd()
            os.chdir(td)
            try:
                store = ep.store_path(root)
                store.parent.mkdir(parents=True)
                store.write_text("".join(json.dumps({"tool": "codex_watch"}) + "\n" for _ in range(40)),
                                 encoding="utf-8")
                self.assertIsNone(fn._spawn_vs_decisions(), "codex rows alone are not Claude spawns")
                for r in _pair("d1", "S", "low", "COMPLETE") + _pair("d2", None, "high", "COMPLETE",
                                                                    source="default-ungraded"):
                    ep.record(root, r)
                self.assertEqual(fn._spawn_vs_decisions(), "graded 1/2 Claude spawns")
            finally:
                os.chdir(cwd)


@unittest.skipIf(_NODE is None, "node not installed")
class FixtureRunThroughBobStage(unittest.TestCase):
    """s6 item 4, fixture form: every hop is the shipped code except the agent itself."""

    def _cli(self, *argv):
        proc = subprocess.run([sys.executable, str(_POLICY_CLI), *argv], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_plan_to_rollup(self):
        import test_bob_stage_workflow as tbs
        plan = {"plan_id": "P311", "work_packages": [
            {"id": "WP-1", "complexity": "S", "files": ["docs/a.md"]},
            {"id": "WP-2", "complexity": "M", "files": ["skills/_meta/gates.py"]},
            {"id": "WP-3", "complexity": "L", "files": ["docs/b.md"]}]}
        want = {"WP-1": ("low", "grade"), "WP-2": ("high", "promotion"), "WP-3": ("high", "grade")}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            for wp in ("WP-1", "WP-2", "WP-3"):
                d = self._cli("wp", "--plan", str(plan_path), "--wp", wp)
                self.assertEqual((d["effort"], d["effort_source"]), want[wp])
                self._cli("record-dispatch", "--dispatch-kind", "work-package", "--project-root", td, "--dispatch-id", d["dispatch_id"],
                          "--task-key", d["task_key"], "--effort-source", d["effort_source"],
                          "--effort-requested", d["effort"], "--grade", d["grade"],
                          "--policy-hash", d["policy_hash"], "--agent-type", "bob")
                args = tbs.stage_args(wp_id=wp, effort=d["effort"], effort_source=d["effort_source"],
                                      grade=d["grade"], policy_hash=d["policy_hash"],
                                      dispatch_id=d["dispatch_id"], task_key=d["task_key"])
                status = "PARTIAL" if wp == "WP-3" else "COMPLETE"
                out = tbs.run_wf([tbs.report(status, wp_id=wp)], args)
                self.assertEqual(out["calls"][0]["opts"]["effort"], d["effort"])
                blk = out["result"]["dispatch"]
                extra = ["--needs-kind", blk["needs_kind"]] if blk["needs_kind"] else []
                self._cli("record-outcome", "--dispatch-kind", "work-package", "--project-root", td, "--dispatch-id", blk["dispatch_id"],
                          "--task-key", blk["task_key"], "--status", blk["status"],
                          "--attempt", str(blk["attempt"]), *extra)
            rows, skipped = er.read_rows(ep.store_path(root))
            self.assertEqual(skipped, 0)
            self.assertEqual(len(rows), 6)
            for r in rows:                      # structural only: nothing a prompt could hide in
                self.assertFalse({"prompt", "detail", "reason", "goal"} & set(r))
            doc = er.rollup(rows)
            self.assertEqual([(c["grade"], c["effort"], c["n"], c["pass"]) for c in doc["cells"]],
                             [("L", "high", 1, 0), ("M", "high", 1, 1), ("S", "low", 1, 1)])
            self.assertEqual(er.claude_spawn_counts(rows), (3, 3))


if __name__ == "__main__":
    unittest.main()


class FixRound1(unittest.TestCase):
    def test_m1_a_redispatch_is_not_a_first_attempt_and_a_mismatch_is_flagged(self):
        rows = _pair("r1", "S", "low", "FAILED") + _pair("r2", "S", "low", "COMPLETE", attempt=2)
        d = ep.dispatch_row(dispatch_id="r3", task_key="P:r3", effort_source="grade", effort_requested="low", grade="S")
        o = ep.outcome_row(dispatch_id="r3", task_key="P:r3", status="COMPLETE", attempt=2)
        doc = er.rollup(rows + [d, o])
        self.assertEqual([(c["n"], c["pass"]) for c in doc["cells"]], [(1, 0)])
        self.assertEqual((doc["retries"], doc["attempt_mismatches"]), (1, 1))

    def test_m2_refused_dispatches_are_neither_cells_nor_graded(self):
        rows = _pair("f1", "S", "low", "REFUSED") + _pair("f2", "M", "medium", "COMPLETE")
        doc = er.rollup(rows)
        self.assertEqual([(c["grade"], c["n"]) for c in doc["cells"]], [("M", 1)])
        self.assertEqual(doc["refused"], 1)
        self.assertEqual(er.claude_spawn_counts(rows), (1, 1))
