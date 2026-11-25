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
  5. S081 WP-R06 (design §4.11): the rows carry requested_model / served_model /
     tokens / role, the codex row the quota meter readings, and the audit's codex
     use is admitted into the cycle's astra budget in HOME — never refused, and a
     broken admission never changes the audit.
  6. S081 WP-F03 (plan J15): an ordinary run's rows carry NONE of the substitution
     keys; when astra is unavailable (here: no codex binary) the codex arm's row keeps
     tool "audit_codex" but names the Fable substitute, and the stdout key set is
     still unchanged. Whether a codex binary exists is PINNED per test
     (audit_spawn._codex_cli_missing): since WP-F03 a host without codex would
     otherwise substitute and these rows would silently describe a different run.

Subprocesses are mocked — no real claude/codex binary required. audit_spawn is
imported under an EMPTY throwaway HOME and every in-process main() runs with HOME
pointed at a tmp dir, so nothing reads the live ~/.codex or writes the live
~/.claude (seat-model-tops.json, astra-budget.jsonl).

Run:
    pytest skills/_meta/tests/test_spawn_telemetry_wiring.py -v
"""
from __future__ import annotations

import importlib
import io
import contextlib
import json
import os
import shutil
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

#: #291: synthetic full served ids, one explicit LITERAL per vendor alias — the id a stub envelope
#: reports when it served that alias. A test indexes it with the alias the spawner pins (a roster
#: tier), so the strings stay literal while the one a test needs follows the roster.
SERVED_ID = {"fable": "claude-fable-5-1", "opus": "claude-opus-5", "sonnet": "claude-sonnet-5",
             "haiku": "claude-haiku-4-5"}

_HOME_VARS = ("HOME", "USERPROFILE")


def _import_under_empty_home(name):
    """Import with HOME at an empty throwaway dir (nothing read, nothing written)."""
    if name in sys.modules:
        return sys.modules[name]
    saved = {var: os.environ.get(var) for var in _HOME_VARS}
    home = tempfile.mkdtemp(prefix="telemetry-import-home-")
    try:
        for var in _HOME_VARS:
            os.environ[var] = home
        return importlib.import_module(name)
    finally:
        for var, value in saved.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value
        shutil.rmtree(home, ignore_errors=True)


aud = _import_under_empty_home("audit_spawn")
import codex_quota  # noqa: E402
import verification_arbiter_spawn as vas  # noqa: E402
from trusted_runner import bundle_hash_hex  # noqa: E402

# #282 R3: both launchers resolve their fixed reviewer cwd from XDG_RUNTIME_DIR before every
# launch (even with subprocess.run mocked), so the module points it at a throwaway runtime
# dir — never the host's real /run/user/<uid>/foundry-reviewer-cwd.
_RUNTIME = {}
_UNSET = object()


def setUpModule():
    tmp = tempfile.TemporaryDirectory(prefix="telemetry-xdg-runtime-")
    _RUNTIME.update(tmp=tmp, prev=os.environ.get("XDG_RUNTIME_DIR", _UNSET))
    os.environ["XDG_RUNTIME_DIR"] = str(Path(tmp.name).resolve())


def tearDownModule():
    prev = _RUNTIME.pop("prev", _UNSET)
    if prev is _UNSET:
        os.environ.pop("XDG_RUNTIME_DIR", None)
    else:
        os.environ["XDG_RUNTIME_DIR"] = prev
    _RUNTIME.pop("tmp").cleanup()

#: S081 WP-F03 — the keys a substituted codex arm adds (row: J15; provenance: J14).
SUBSTITUTION_ROW_KEYS = ("substitute_for", "substitution_reason", "use")
SUBSTITUTION_PROVENANCE_KEYS = ("codex_arm_substituted_by", "substitution_reason", "substitute_timeout_s",
                                "provider_gap", "codex_attempts", "substitution_error",
                                "substitution_row_error")

HEX32 = "a" * 32
HEX64_PLAN = "c" * 64
HEX64_INV = "d" * 64
RUNNER_VERSION = "trusted_runner/1.0.0"
RUBRIC_VERSION = "rubric/1.0.0"


# ---------------------------------------------------------------------------
# Envelope builders
# ---------------------------------------------------------------------------

def claude_stream_envelope(inner_json: str, cost=0.0123, dur=4210, turns=2, usage=None,
                           model_usage=None) -> str:
    """A realistic claude 2.1.x stream-array envelope whose terminal result
    element carries the cost/latency fields wrapped around `inner_json`.
    `usage` (S081 WP-R06) adds the envelope's token usage object when given.
    `model_usage` (#282 R3) {model id: outputTokens} adds the modelUsage map."""
    result = {"type": "result", "subtype": "success", "result": inner_json,
              "total_cost_usd": cost, "duration_ms": dur, "num_turns": turns,
              "is_error": False}
    if usage is not None:
        result["usage"] = usage
    if model_usage is not None:
        result["modelUsage"] = {k: {"inputTokens": 1, "outputTokens": v} for k, v in model_usage.items()}
    return json.dumps([
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": inner_json}]}},
        result,
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
# D24: audit_spawn's codex arm spawn seam (S081 revision 4, WP-A03)
# ---------------------------------------------------------------------------
#
# The codex arm moved off `subprocess.run` onto codex_watch (Popen + activity
# polling, streams to files). `patch_codex_spawn` routes one legacy `fake_run`
# to BOTH seams so the fakes below stay exactly as they were: `subprocess.run`
# still carries the CLAUDE arm, codex_watch.watch now carries the codex arm.
# Only the plumbing changed; every assertion in this module is untouched.
def _watch_from_run(fake_run):
    def _watch(cmd, **kwargs):
        stdout_path = Path(kwargs["stdout_path"])
        stderr_path = Path(kwargs["stderr_path"])
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        proc = fake_run(cmd)
        stdout_path.write_text(str(getattr(proc, "stdout", "") or ""), encoding="utf-8")
        stderr_path.write_text(str(getattr(proc, "stderr", "") or ""), encoding="utf-8")
        return aud.codex_watch.WatchResult(
            stop_reason=aud.codex_watch.STOP_OK,
            exit_code=getattr(proc, "returncode", 0),
            child_exit_code=getattr(proc, "returncode", 0),
            elapsed_s=0.0, max_silence_s=0.0, mode=aud.codex_watch.MODE_CODEX,
            argv=tuple(str(c) for c in cmd), stdout_path=stdout_path, stderr_path=stderr_path,
            idle_timeout_s=float(kwargs.get("idle_timeout_s") or 0.0),
            hard_cap_s=float(kwargs.get("hard_cap_s") or 0.0),
        )
    return _watch


@contextlib.contextmanager
def patch_codex_spawn(fake_run):
    """Both of audit_spawn's spawn seams, driven by one legacy `fake_run`."""
    with mock.patch.object(aud.subprocess, "run", side_effect=fake_run), \
            mock.patch.object(aud.codex_watch, "watch", side_effect=_watch_from_run(fake_run)):
        yield


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
        with patch_codex_spawn(lambda c, **k: fake_proc(env, 0)):
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
        with patch_codex_spawn(lambda c, **k: fake_proc(json.dumps(audit_verdict()), 0)):
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
            # S081 WP-R06: provenance rides the row, never the closed verdict object.
            self.assertEqual((r["requested_model"], r["served_model"], r["role"]),
                             (vas.CLAUDE_MODEL, "unknown", "code_reviewer"))
            self.assertNotIn("tokens", r)  # this envelope carries no usage object
            for forbidden in ("requested_model", "served_model", "role", "tokens"):
                self.assertNotIn(forbidden, payload)
            # #282 R3: no modelUsage in this envelope -> served "unknown" (above) and neither new key.
            for absent in ("served_model_usage", "served_model_mismatch"):
                self.assertNotIn(absent, r)
                self.assertNotIn(absent, payload)
            # The evidence bundle bytes were never modified.
            self.assertEqual(bundle_path.read_bytes(), bundle_bytes)

    def test_served_model_from_model_usage_reaches_the_row(self):
        """#282 R3 (plan K5): the SAME happy path with a modelUsage map -> the row's served_model is the
        key with the most output tokens, served_model_usage keeps every key, no mismatch key (alias vs
        full id), and the closed verdict stdout is unchanged (no usage or served keys)."""
        with tempfile.TemporaryDirectory() as td:
            root, bundle_path, bhash, _bundle_bytes, plan_path, phash = \
                self._setup_project(Path(td))
            body = arbiter_verdict(bhash, phash)
            # #291: the served id is the full id OF the pinned alias (so no mismatch); which literal
            # that is follows the roster tier the arbiter pins (vas.CLAUDE_MODEL).
            full_id = SERVED_ID[vas.CLAUDE_MODEL]
            env = claude_stream_envelope(json.dumps(body),
                                         model_usage={"claude-haiku-x": 10, full_id: 1234})
            argv = ["prog", str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                    str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION]
            cwd = os.getcwd()
            try:
                os.chdir(root)
                with mock.patch.object(vas.subprocess, "run",
                                       side_effect=lambda c, **k: fake_proc(env, 0)):
                    code, out, err = run_main_capture(vas, argv)
            finally:
                os.chdir(cwd)
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out), body)
            (r,) = read_spawn_runs(root)
            self.assertEqual((r["requested_model"], r["served_model"]), (vas.CLAUDE_MODEL, full_id))
            self.assertEqual(r["served_model_usage"], {"claude-haiku-x": 10, full_id: 1234})
            self.assertNotIn("served_model_mismatch", r)
            self.assertNotIn("WARNING", err)

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
    CODEX_BANNER = ("OpenAI Codex v0.154.0\n--------\nmodel: served-by-banner\n"
                    "reasoning effort: xhigh\n--------\n")

    def _project(self, td: Path):
        root = td / "proj"
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
        home = td / "home"
        home.mkdir()
        return root, bundle_path, bhash, home

    def _run_main(self, root, bundle_path, home, cli_missing=False, model_usage=None, **patches):
        claude_env = claude_stream_envelope(json.dumps(audit_verdict()),
                                            cost=0.02, dur=3000, turns=1,
                                            usage={"input_tokens": 700, "output_tokens": 70},
                                            model_usage=model_usage)
        codex_out = json.dumps(audit_verdict())  # raw verdict, non-envelope

        def fake_run(cmd, **kwargs):
            # cmd[0] is the binary; route by which spawner arm called us.
            if cmd and "codex" in str(cmd[0]).lower():
                return fake_proc(codex_out, 0, stderr=self.CODEX_BANNER)
            return fake_proc(claude_env, 0)

        argv = ["prog", "comp-x", str(bundle_path), "--project-root", str(root)]
        home_env = {var: str(home) for var in _HOME_VARS}
        with mock.patch.dict(os.environ, home_env), \
                patch_codex_spawn(fake_run), \
                mock.patch.object(aud, "_codex_cli_missing", return_value=cli_missing):
            if patches:
                with mock.patch.multiple(aud.codex_quota, **patches):
                    return run_main_capture(aud, argv)
            return run_main_capture(aud, argv)

    def test_both_arms_recorded_stdout_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root, bundle_path, bhash, home = self._project(Path(td))
            code, out, _err = self._run_main(root, bundle_path, home)

            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["result"], "VERIFIED")
            # The audit result dict carries NO usage keys (observe-only sidecar).
            for forbidden in ("cost_usd", "duration_ms", "num_turns",
                              "wall_clock_s", "usage", "tokens", "quota_before"):
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

            # S081 WP-R06 (design §4.11) — the provenance fields.
            claude, codex = by_tool["audit_claude"], by_tool["audit_codex"]
            self.assertEqual((claude["requested_model"], claude["served_model"], claude["role"]),
                             (aud.CLAUDE_MODEL, "unknown", "code_reviewer"))
            # #282 R3: no modelUsage -> "unknown" (carried forward), neither new key on either row,
            # and the verdict provenance's Claude `reported` stays unknown too.
            for r in (claude, codex):
                for absent in ("served_model_usage", "served_model_mismatch"):
                    self.assertNotIn(absent, r)
            self.assertEqual((payload["model_provenance"]["claude"]["reported"],
                              payload["model_provenance"]["claude"]["reported_source"]), ("unknown", "unknown"))
            self.assertEqual(claude["tokens"], {"input_tokens": 700, "output_tokens": 70})
            for absent in ("quota_before", "quota_after", "quota_source"):
                self.assertNotIn(absent, claude)
            # REQUESTED and SERVED are different facts, recorded separately.
            self.assertEqual((codex["requested_model"], codex["served_model"], codex["role"]),
                             (aud.CODEX_MODEL, "served-by-banner", "code_reviewer"))
            self.assertEqual(codex["quota_source"], "codex_rollout_meter")
            for key in ("quota_before", "quota_after"):
                self.assertEqual(codex[key]["state"], "unknown")  # an empty HOME has no rollout
            self.assertNotIn("tokens", codex)  # no session id on the banner -> unobservable

            # The codex use was admitted into the cycle's budget in HOME (never refused).
            budget = home / ".claude" / "projects" / codex_quota.project_slug(root) / "astra-budget.jsonl"
            rows = [json.loads(l) for l in budget.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual([(r["use"], r["admitted"], r["reason"]) for r in rows],
                             [("audit", True, "audit_exempt")])

            # S081 WP-F03 (J15): nothing was substituted, so no row carries a substitution
            # key and the codex provenance names none (absent means "did not happen").
            for r in recs:
                for key in SUBSTITUTION_ROW_KEYS:
                    self.assertNotIn(key, r)
            for key in SUBSTITUTION_PROVENANCE_KEYS:
                self.assertNotIn(key, payload["model_provenance"]["codex"])

    def test_a_substituted_codex_arm_is_recorded_as_the_substitute(self):
        """CONTROL for the absence above: the SAME run with no codex binary. The codex arm's
        row keeps its tool tag but describes the Fable substitute that served it (J15), the
        stdout keys are unchanged (#124), and the budget store has the substitution row
        (and no audit admission — no TOP call happened)."""
        with tempfile.TemporaryDirectory() as td:
            root, bundle_path, bhash, home = self._project(Path(td))
            code, out, err = self._run_main(root, bundle_path, home, cli_missing=True)

            self.assertEqual(code, 0, err)
            payload = json.loads(out)
            self.assertEqual(payload["result"], "VERIFIED")
            self.assertEqual(set(payload), {"result", "component_id", "claude_verdict", "codex_verdict",
                                            "disagreements", "bundle_hash", "elapsed_s", "model_provenance"})
            for forbidden in ("substitute_for", "substitution_reason", "codex_arm_substituted_by"):
                self.assertNotIn(forbidden, payload)

            by_tool = {r["tool"]: r for r in read_spawn_runs(root)}
            self.assertEqual(sorted(by_tool), ["audit_claude", "audit_codex"])
            codex, claude = by_tool["audit_codex"], by_tool["audit_claude"]
            # RE-POINTED by #282 R3 (spec H1 R3 item 5, plan K5): served_model is what the
            # substitute's envelope modelUsage names — this envelope has none, so "unknown" (it
            # was the alias, the request echoed back); the alias stays on `model`. The
            # modelUsage case: test_served_model_from_model_usage_reaches_both_rows.
            self.assertEqual((codex["model"], codex["served_model"], codex["requested_model"]),
                             (aud.CLAUDE_MODEL, "unknown", aud.CODEX_MODEL))
            self.assertEqual((codex["substitute_for"], codex["substitution_reason"], codex["use"]),
                             ("codex", "cli_missing", "audit"))
            # cost / turns / tokens come from the substitute's claude envelope.
            self.assertEqual((codex["cost_usd"], codex["num_turns"]), (0.02, 1))
            self.assertEqual(codex["tokens"], {"input_tokens": 700, "output_tokens": 70})
            for absent in ("quota_before", "quota_after", "quota_source"):
                self.assertNotIn(absent, codex)  # no codex call to bracket
            for key in SUBSTITUTION_ROW_KEYS:
                self.assertNotIn(key, claude)
            self.assertEqual(codex["invocation_id"], claude["invocation_id"])
            self.assertEqual(payload["model_provenance"]["codex"]["codex_arm_substituted_by"],
                             aud.CLAUDE_MODEL)

            budget = home / ".claude" / "projects" / codex_quota.project_slug(root) / "astra-budget.jsonl"
            rows = [json.loads(l) for l in budget.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual([(r.get("kind"), r["use"], r["reason"]) for r in rows],
                             [("substitution", "audit", "cli_missing")])

    def test_served_model_from_model_usage_reaches_both_rows(self):
        """#282 R3 (plan K5): the same two runs as above with a modelUsage map on every claude envelope.
        Un-substituted: the audit_claude row records the most-output-tokens id + every key, and
        model_provenance.claude reports it with source claude_model_usage; the codex row is unchanged
        (its banner). Substituted (no codex binary): the audit_codex row's served_model is the
        substitute envelope's id — `model` keeps the alias — and codex_arm_substituted_by is unchanged.
        No run has a mismatch key (full id vs its own alias), and the stdout keys are unchanged.
        #291: the served id is the full id of the pinned alias (aud.CLAUDE_MODEL, a roster tier)."""
        full_id = SERVED_ID[aud.CLAUDE_MODEL]
        usage = {"claude-haiku-x": 50, full_id: 900}
        for cli_missing in (False, True):
            with self.subTest(cli_missing=cli_missing), tempfile.TemporaryDirectory() as td:
                root, bundle_path, _bhash, home = self._project(Path(td))
                code, out, err = self._run_main(root, bundle_path, home, cli_missing=cli_missing,
                                                model_usage=usage)
                self.assertEqual(code, 0, err)
                payload = json.loads(out)
                self.assertEqual(set(payload), {"result", "component_id", "claude_verdict", "codex_verdict",
                                                "disagreements", "bundle_hash", "elapsed_s", "model_provenance"})
                claude_block = payload["model_provenance"]["claude"]
                self.assertEqual((claude_block["reported"], claude_block["reported_source"]),
                                 (full_id, "claude_model_usage"))
                by_tool = {r["tool"]: r for r in read_spawn_runs(root)}
                claude, codex = by_tool["audit_claude"], by_tool["audit_codex"]
                self.assertEqual((claude["served_model"], claude["served_model_usage"]), (full_id, usage))
                if cli_missing:
                    self.assertEqual((codex["model"], codex["served_model"], codex["served_model_usage"]),
                                     (aud.CLAUDE_MODEL, full_id, usage))
                    self.assertEqual(payload["model_provenance"]["codex"]["codex_arm_substituted_by"],
                                     aud.CLAUDE_MODEL)
                else:
                    self.assertEqual(codex["served_model"], "served-by-banner")
                    self.assertNotIn("served_model_usage", codex)
                for r in (claude, codex):
                    self.assertNotIn("served_model_mismatch", r)
                self.assertNotIn("served_model_mismatch", err)

    def test_a_broken_admission_never_changes_the_audit(self):
        """CONTROL for the budget row above: admit raising (a caller bug) or a store that
        cannot be written leaves the verdict, the exit code and the rows unchanged."""
        failures = {
            "raises": mock.Mock(side_effect=ValueError("caller bug")),
            "unwritten": mock.Mock(return_value={"admitted": True, "row_written": False,
                                                 "error": "OSError: read-only"}),
        }
        for label, admit in failures.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as td:
                root, bundle_path, _bhash, home = self._project(Path(td))
                code, out, err = self._run_main(root, bundle_path, home, admit=admit)
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(out)["result"], "VERIFIED")
                self.assertEqual(admit.call_count, 1)
                self.assertEqual(admit.call_args.args[0], "audit")
                self.assertIn("codex quota admission not recorded", err)
                self.assertEqual(sorted(r["tool"] for r in read_spawn_runs(root)),
                                 ["audit_claude", "audit_codex"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
