#!/usr/bin/env python3
"""test_spawn_telemetry_wiring.py — S046 / #124 end-to-end instrumentation.

Proves BOTH spawners are instrumented for observe-only cost telemetry WITHOUT
changing their existing verdict-return API or output:

  1. A captured `claude -p --output-format json` envelope (carrying
     total_cost_usd / duration_ms / num_turns) -> those fields land in the
     spawn-runs.jsonl sidecar record, with all correlation fields.
  2. The arbiter's stdout verdict is UNCHANGED (no usage keys; still
     schema-valid additionalProperties:false) and the evidence bundle is never
     touched.
  3. The non-JSON / Codex path -> usage null, NOT an error (still records).
  4. The internal helpers keep their (verdict, err) / (parsed, err) API: calling
     them with the legacy 2-arg signature behaves exactly as before.

Subprocesses are mocked — no real claude/codex binary required.

Run:
    pytest skills/_meta/tests/test_spawn_telemetry_wiring.py -v
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_META = Path(__file__).resolve().parent.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import audit_spawn as aud  # noqa: E402
import verification_arbiter_spawn as vas  # noqa: E402
from trusted_runner import bundle_hash_hex  # noqa: E402

HEX32 = "a" * 32
HEX64_PLAN = "c" * 64
HEX64_INV = "d" * 64
RUNNER_VERSION = "trusted_runner/1.0.0"
RUBRIC_VERSION = "rubric/1.0.0"


# ---------------------------------------------------------------------------
# Envelope builders
# ---------------------------------------------------------------------------

def claude_stream_envelope(inner_json: str, cost=0.0123, dur=4210, turns=2) -> str:
    """A realistic claude 2.1.x stream-array envelope whose terminal result
    element carries the cost/latency fields wrapped around `inner_json`."""
    return json.dumps([
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": inner_json}]}},
        {"type": "result", "subtype": "success", "result": inner_json,
         "total_cost_usd": cost, "duration_ms": dur, "num_turns": turns,
         "is_error": False},
    ])


def fake_proc(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


def make_bundle(component_id="comp-x"):
    bundle = {
        "component_id": component_id,
        "produced_by": "bob-trusted-runner",
        "run_at": "2026-06-07T00:00:00Z",
        "runner_info": {"runner": "pytest", "version": "8.0"},
        "test_paths": ["tests/unit/test_x.py"],
        "results": [{
            "path": "tests/unit/test_x.py", "returncode": 0,
            "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0,
                        "error": 0, "duration_s": 0.1},
            "tests": [{"nodeid": "tests/unit/test_x.py::test_a",
                       "outcome": "passed", "duration_s": 0.1, "keywords": []}],
            "failed_tests": [],
        }],
    }
    # Real bundles carry their own bundle_hash field (the canonical hash over
    # the bundle EXCLUDING this field). audit_spawn reads bundle["bundle_hash"]
    # for correlation; the arbiter recomputes from on-disk bytes.
    h = bundle_hash_hex(bundle)
    bundle["bundle_hash"] = h
    return bundle, h


def arbiter_verdict(bundle_hash, plan_hash):
    return {
        "verdict": "VERIFIED", "request_id": HEX32, "attempt_id": "att-1",
        "prior_state_version": "sv-1", "bundle_hash": bundle_hash,
        "plan_hash": plan_hash, "inventory_hash": HEX64_INV,
        "runner_version": RUNNER_VERSION, "rubric_version": RUBRIC_VERSION,
        "coverage": {"requirements_total": 1, "requirements_covered": 1,
                     "uncovered": [], "skipped_with_reason": []},
        "concerns": [],
        "self_hash_check": {"bundle_recomputed_hash": bundle_hash,
                            "matches_input": True},
        # S048 / #116 R-B2: evidence_map is now a REQUIRED top-level key.
        "evidence_map": {"REQ-1": ["tests/test_x.py::test_a"]},
    }


def audit_verdict():
    return {
        "verdict": "pass",
        "structured_disagreements": [
            {"point": "thin fixtures", "severity": "minor", "location": "comp-x"},
            {"point": "no perf budget", "severity": "minor", "location": "comp-x"},
            {"point": "adversarial gap", "severity": "moderate", "location": "comp-x"},
        ],
        "evidence_verified": True,
        "reason": "ok",
    }


def read_spawn_runs(root: Path):
    p = root / ".process-observations" / "spawn-runs.jsonl"
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def run_main_capture(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    old_o, old_e = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        try:
            mod.main(argv)
            code = None
        except SystemExit as e:
            code = int(e.code) if e.code is not None else 0
    finally:
        sys.stdout, sys.stderr = old_o, old_e
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Internal-helper API preservation (called the legacy 2-arg way)
# ---------------------------------------------------------------------------

class TestVerdictReturnApiUnchanged(unittest.TestCase):
    def test_run_claude_auditor_two_arg_call(self):
        env = claude_stream_envelope(json.dumps(audit_verdict()))
        with mock.patch.object(aud.subprocess, "run",
                               side_effect=lambda c, **k: fake_proc(env, 0)):
            verdict, errmsg = aud.run_claude_auditor("prompt", 60)  # NO usage_out
        self.assertIsNone(errmsg)
        self.assertEqual(verdict["verdict"], "pass")

    def test_run_codex_auditor_two_arg_call(self):
        env = json.dumps(audit_verdict())  # codex returns raw verdict json
        with mock.patch.object(aud.subprocess, "run",
                               side_effect=lambda c, **k: fake_proc(env, 0)):
            verdict, errmsg = aud.run_codex_auditor("prompt", 60)  # NO usage_out
        self.assertIsNone(errmsg)
        self.assertEqual(verdict["verdict"], "pass")

    def test_run_claude_arbiter_two_arg_call(self):
        body = arbiter_verdict("b" * 64, HEX64_PLAN)
        env = claude_stream_envelope(json.dumps(body))
        with mock.patch.object(vas.subprocess, "run",
                               side_effect=lambda c, **k: fake_proc(env, 0)):
            parsed, errmsg = vas.run_claude_arbiter("prompt", 60)  # NO usage_out
        self.assertIsNone(errmsg)
        self.assertEqual(parsed["verdict"], "VERIFIED")

    def test_usage_out_filled_when_supplied(self):
        env = claude_stream_envelope(json.dumps(audit_verdict()),
                                     cost=0.5, dur=999, turns=3)
        sink = {}
        with mock.patch.object(aud.subprocess, "run",
                               side_effect=lambda c, **k: fake_proc(env, 0)):
            aud.run_claude_auditor("prompt", 60, sink)
        self.assertEqual(sink["cost_usd"], 0.5)
        self.assertEqual(sink["duration_ms"], 999)
        self.assertEqual(sink["num_turns"], 3)
        self.assertIn("wall_clock_s", sink)

    def test_usage_out_null_on_codex_nonjson(self):
        """Non-JSON path -> cost/duration/turns null, wall_clock present, no raise."""
        sink = {}
        with mock.patch.object(aud.subprocess, "run",
                               side_effect=lambda c, **k: fake_proc(
                                   json.dumps(audit_verdict()), 0)):
            # codex returns valid verdict json but it's NOT a claude envelope,
            # so extract_usage finds no result-element cost fields -> null.
            aud.run_codex_auditor("prompt", 60, sink)
        self.assertIsNone(sink["cost_usd"])
        self.assertIsNone(sink["duration_ms"])
        self.assertIsNone(sink["num_turns"])
        self.assertIn("wall_clock_s", sink)


# ---------------------------------------------------------------------------
# Arbiter main — sidecar emitted, verdict stdout unchanged, bundle untouched
# ---------------------------------------------------------------------------

class TestArbiterMainTelemetry(unittest.TestCase):
    def _setup_project(self, td: Path):
        root = td / "proj"
        (root / ".process-observations").mkdir(parents=True)
        bundle, bhash = make_bundle()
        plan = {"plan_version": "v1",
                "requirements": [{"id": "REQ-001", "tier": 0}], "skips": []}
        bundle_path = root / "bundle.json"
        plan_path = root / "plan.json"
        bundle_bytes = json.dumps(bundle).encode("utf-8")
        bundle_path.write_bytes(bundle_bytes)
        plan_bytes = json.dumps(plan).encode("utf-8")
        plan_path.write_bytes(plan_bytes)
        import hashlib
        phash = hashlib.sha256(plan_bytes).hexdigest()
        return root, bundle_path, bhash, bundle_bytes, plan_path, phash

    def test_happy_path_records_cost_and_keeps_verdict_clean(self):
        with tempfile.TemporaryDirectory() as td:
            root, bundle_path, bhash, bundle_bytes, plan_path, phash = \
                self._setup_project(Path(td))
            env = claude_stream_envelope(
                json.dumps(arbiter_verdict(bhash, phash)),
                cost=0.0789, dur=5120, turns=2)
            argv = ["prog", str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                    str(plan_path), phash, HEX64_INV, RUNNER_VERSION,
                    RUBRIC_VERSION]
            cwd = os.getcwd()
            try:
                os.chdir(root)
                with mock.patch.object(vas.subprocess, "run",
                                       side_effect=lambda c, **k: fake_proc(env, 0)):
                    code, out, _err = run_main_capture(vas, argv)
            finally:
                os.chdir(cwd)

            # Behavior unchanged: exit 0, verdict stdout = schema-valid verdict.
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["verdict"], "VERIFIED")
            # The verdict object carries NO usage keys (additionalProperties:false).
            for forbidden in ("cost_usd", "duration_ms", "num_turns",
                              "wall_clock_s", "usage"):
                self.assertNotIn(forbidden, payload)
            # The sidecar captured the cost/latency + correlation fields.
            recs = read_spawn_runs(root)
            self.assertEqual(len(recs), 1)
            r = recs[0]
            self.assertEqual(r["tool"], "verification_arbiter")
            self.assertEqual(r["status"], "VERIFIED")
            self.assertEqual(r["cost_usd"], 0.0789)
            self.assertEqual(r["duration_ms"], 5120)
            self.assertEqual(r["num_turns"], 2)
            self.assertEqual(r["bundle_hash"], bhash)
            self.assertEqual(r["request_id"], HEX32)
            self.assertEqual(r["component_id"], "comp-x")
            # The evidence bundle bytes were never modified.
            self.assertEqual(bundle_path.read_bytes(), bundle_bytes)

    def test_nonjson_garbage_records_null_cost_still_audit_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            root, bundle_path, bhash, bundle_bytes, plan_path, phash = \
                self._setup_project(Path(td))
            argv = ["prog", str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                    str(plan_path), phash, HEX64_INV, RUNNER_VERSION,
                    RUBRIC_VERSION]
            cwd = os.getcwd()
            try:
                os.chdir(root)
                with mock.patch.object(vas.subprocess, "run",
                                       side_effect=lambda c, **k: fake_proc(
                                           "this is not json at all", 0)):
                    code, out, _err = run_main_capture(vas, argv)
            finally:
                os.chdir(cwd)
            # Behavior unchanged: garbage -> exit 4 AUDIT_UNAVAILABLE.
            self.assertEqual(code, 4)
            payload = json.loads(out)
            self.assertEqual(payload["verdict"], "AUDIT_UNAVAILABLE")
            # But we STILL recorded a spawn run, with null cost (non-JSON path).
            recs = read_spawn_runs(root)
            self.assertEqual(len(recs), 1)
            self.assertIsNone(recs[0]["cost_usd"])
            self.assertIsNone(recs[0]["duration_ms"])
            self.assertTrue(recs[0]["status"].startswith("ERROR"))


# ---------------------------------------------------------------------------
# Audit_spawn main — two arms recorded (claude cost, codex null), stdout clean
# ---------------------------------------------------------------------------

class TestAuditSpawnMainTelemetry(unittest.TestCase):
    def test_both_arms_recorded_stdout_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"
            (root / ".process-observations").mkdir(parents=True)
            (root / "progress").mkdir(parents=True)
            bundle, bhash = make_bundle()
            bundle_path = root / "bundle.json"
            bundle_path.write_text(json.dumps(bundle))
            # Minimal contract map + ledger so load_component_entry / row work.
            (root / "progress" / "contract-map.yaml").write_text(
                "revision: 1\ncomponents:\n  - id: comp-x\n    "
                "success_criteria: []\n")
            (root / "progress" / "integration-ledger.md").write_text(
                "| WP | component | stage | generation | deps |\n"
                "|----|-----------|-------|------------|------|\n"
                "| WP-1 | comp-x | INTEGRATED | 0 | — |\n")

            claude_env = claude_stream_envelope(json.dumps(audit_verdict()),
                                                cost=0.02, dur=3000, turns=1)
            codex_out = json.dumps(audit_verdict())  # raw verdict, non-envelope

            def fake_run(cmd, **kwargs):
                # cmd[0] is the binary; route by which spawner arm called us.
                if cmd and "codex" in str(cmd[0]).lower():
                    return fake_proc(codex_out, 0)
                return fake_proc(claude_env, 0)

            argv = ["prog", "comp-x", str(bundle_path),
                    "--project-root", str(root)]
            with mock.patch.object(aud.subprocess, "run", side_effect=fake_run):
                code, out, _err = run_main_capture(aud, argv)

            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["result"], "VERIFIED")
            # The audit result dict carries NO usage keys (observe-only sidecar).
            for forbidden in ("cost_usd", "duration_ms", "num_turns",
                              "wall_clock_s", "usage"):
                self.assertNotIn(forbidden, payload)

            recs = read_spawn_runs(root)
            tools = sorted(r["tool"] for r in recs)
            self.assertEqual(tools, ["audit_claude", "audit_codex"])
            by_tool = {r["tool"]: r for r in recs}
            # Claude arm captured cost (JSON envelope); codex arm null (non-JSON).
            self.assertEqual(by_tool["audit_claude"]["cost_usd"], 0.02)
            self.assertEqual(by_tool["audit_claude"]["num_turns"], 1)
            self.assertIsNone(by_tool["audit_codex"]["cost_usd"])
            self.assertIsNone(by_tool["audit_codex"]["num_turns"])
            # Both share the same invocation_id (one audit call, two arms).
            self.assertEqual(by_tool["audit_claude"]["invocation_id"],
                             by_tool["audit_codex"]["invocation_id"])
            # Both carry the component + bundle hash correlation.
            for r in recs:
                self.assertEqual(r["component_id"], "comp-x")
                self.assertEqual(r["bundle_hash"], bhash)


if __name__ == "__main__":
    unittest.main(verbosity=2)
