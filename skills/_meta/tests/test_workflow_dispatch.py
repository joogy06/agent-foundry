#!/usr/bin/env python3
"""test_workflow_dispatch.py — WP-7 (S055 §4.3 / R11).

Covers: atomic claim exactly-once under concurrent callers; double-claim of
(plan_hash, revision) refused; resume-after-revision mechanically detected;
main-loop sole-writer record shape conforms to workflow-run-record.v1.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
import tempfile
import unittest
from pathlib import Path

_META_DIR = Path(__file__).resolve().parent.parent
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

import workflow_dispatch as wd  # noqa: E402

# Schema for record-shape validation (best-effort — skip if jsonschema absent).
try:
    import jsonschema  # noqa: E402
    _SCHEMA = json.loads((_META_DIR / "schemas" / "workflow-run-record.v1.json").read_text())
except Exception:  # pragma: no cover
    jsonschema = None
    _SCHEMA = None


PH = "sha256:" + "a" * 64


def _claim_worker(project_root_str, idx, q):
    pr = Path(project_root_str)
    res = wd.claim(pr, "bob-serial-exec", PH, 1, f"run-{idx}")
    q.put(res["status"])


class WorkflowDispatch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_emit_then_claim(self):
        wd.emit(self.tmp, "bob-serial-exec", PH, 1, "run-A", at="2026-06-11T00:00:00Z")
        res = wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A", at="2026-06-11T00:00:01Z")
        self.assertEqual(res["status"], "claimed")
        self.assertTrue(res["claim_token"])

    def test_double_claim_refused(self):
        r1 = wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A")
        self.assertEqual(r1["status"], "claimed")
        r2 = wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-B")
        self.assertEqual(r2["status"], "refused")
        self.assertIn("holder", r2)

    def test_claim_after_finish_allowed(self):
        wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A")
        wd.finish(self.tmp, "bob-serial-exec", PH, 1, "run-A", "complete")
        # After terminal, the same (plan_hash, revision) is no longer "live" —
        # a re-claim is allowed (e.g. a fresh attempt).
        r2 = wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-C")
        self.assertEqual(r2["status"], "claimed")

    def test_different_revision_not_blocked(self):
        wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A")
        # A higher revision (the post-amendment plan) is a different key.
        r2 = wd.claim(self.tmp, "bob-serial-exec", PH, 2, "run-A")
        self.assertEqual(r2["status"], "claimed")

    def test_concurrent_claimers_exactly_one_wins(self):
        ctx = mp.get_context("spawn")
        q = ctx.Queue()
        procs = [ctx.Process(target=_claim_worker, args=(str(self.tmp), i, q)) for i in range(8)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
        results = [q.get() for _ in range(8)]
        self.assertEqual(results.count("claimed"), 1, f"expected exactly one winner, got {results}")
        self.assertEqual(results.count("refused"), 7)

    def test_resume_after_revision_detected(self):
        # Simulate: claim+execute at rev1, then a higher rev2 appears (amendment),
        # then a STALE resume fires at rev1 again -> mechanically detectable.
        wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A")
        wd.executing(self.tmp, "bob-serial-exec", PH, 1, "run-A", run_id="rid-1")
        wd.emit(self.tmp, "bob-serial-exec", PH, 2, "run-A")  # amendment -> rev 2
        # stale resume back at rev 1
        wd.executing(self.tmp, "bob-serial-exec", PH, 1, "run-A", run_id="rid-1b", resumed_from="tok")
        offenders = wd.audit_resume_across_revision(self.tmp)
        self.assertEqual(len(offenders), 1)
        self.assertEqual(offenders[0]["plan_revision"], 1)
        self.assertEqual(offenders[0]["resumed_from"], "tok")

    def test_clean_resume_not_flagged(self):
        wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A")
        wd.executing(self.tmp, "bob-serial-exec", PH, 1, "run-A", run_id="rid-1")
        # a legit resume at the SAME revision is fine
        wd.executing(self.tmp, "bob-serial-exec", PH, 1, "run-A", run_id="rid-1", resumed_from="tok")
        self.assertEqual(wd.audit_resume_across_revision(self.tmp), [])

    @unittest.skipIf(jsonschema is None, "jsonschema not available")
    def test_records_conform_to_schema(self):
        wd.emit(self.tmp, "bob-serial-exec", PH, 1, "run-A", at="2026-06-11T00:00:00Z")
        wd.claim(self.tmp, "bob-serial-exec", PH, 1, "run-A", at="2026-06-11T00:00:01Z")
        wd.executing(self.tmp, "bob-serial-exec", PH, 1, "run-A", run_id="rid", at="2026-06-11T00:00:02Z")
        wd.finish(self.tmp, "bob-serial-exec", PH, 1, "run-A", "complete", at="2026-06-11T00:00:03Z")
        for rec in wd._read_records(self.tmp):
            jsonschema.validate(instance=rec, schema=_SCHEMA)


if __name__ == "__main__":
    unittest.main()
