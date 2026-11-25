#!/usr/bin/env python3
"""test_verification_arbiter_spawn.py — Phase 2A-1 coverage.

Verifies the verification_arbiter_spawn.py contract:

    - Happy path: valid verdict JSON from subprocess -> exit 0, stdout = verdict.
    - Tuple echo-back correctness (all 8 fields must match bob's inputs).
    - Schema rejection (missing field / bad verdict enum) -> exit 4 with
      AUDIT_UNAVAILABLE and schema_error field populated.
    - Subprocess crash (non-zero rc) -> exit 4 AUDIT_UNAVAILABLE.
    - Subprocess emits non-JSON garbage -> exit 4 AUDIT_UNAVAILABLE.
    - Argv validation (wrong arg count) -> exit 3 with ENV_ERROR.

Run:
    pytest /path/to/project/skills/_meta/tests/test_verification_arbiter_spawn.py -v

We monkeypatch subprocess.run in the arbiter module so tests do not require
a real `claude` binary to be present.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:  # POSIX only (P001): the #282 G2 private-group tests skip where os.getgid is absent.
    import grp as _grp
except ImportError:  # pragma: no cover - Windows has no grp module
    _grp = None

# Add skills/_meta to path
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import seat_model  # noqa: E402
import model_roster  # noqa: E402
import verification_arbiter_spawn as vas  # noqa: E402

#: The arbiter Claude seat's pinned effort, read from the one authority (seat_model.ROLE_TABLE).
ARBITER_EFFORT = vas.seat_model.ROLE_TABLE["arbiter"]["claude"].effort

#: #291: the arbiter's Claude model (the code_reviewer row) is ROSTER DATA. Where a test below means
#: "the pinned model" it asserts MAIN, read from model_roster (the data), never from the resolver
#: under test. A stub invoked by hand stays literal.
MAIN = model_roster.CLAUDE_MAIN
SUPPORT = model_roster.CLAUDE_SUPPORT
#: Synthetic full served ids, one explicit LITERAL per vendor alias (the id a stub envelope reports
#: for that alias). A test picks the requested alias's id for "no mismatch" and another tier's for
#: "mismatch"; the strings stay literal, the choice follows the roster.
SERVED_ID = {"fable": "claude-fable-5-1", "opus": "claude-opus-5", "sonnet": "claude-sonnet-5",
             "haiku": "claude-haiku-4-5"}
from trusted_runner import bundle_hash_hex  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


HEX32 = "a" * 32
HEX64_A = "b" * 64  # placeholder; overridden per-test to real bundle hash
HEX64_PLAN = "c" * 64
HEX64_INV = "d" * 64

RUNNER_VERSION = "trusted_runner/1.0.0"
RUBRIC_VERSION = "rubric/1.0.0"


# ---------------------------------------------------------------------------
# Telemetry isolation (S081 WP-R01, design §4.11 / L6)
# ---------------------------------------------------------------------------
#
# vas.main() records every spawn run with project_root_override=None, i.e. into
# whichever project the CWD sits in. Run from the repository root, the
# in-process main() tests below appended 11 fixture rows (component_id comp-x,
# request_id aaaa..., model fable) to the TRACKED
# .process-observations/spawn-runs.jsonl on every run. So the whole module runs
# inside a throwaway project root. Its `.process-observations/` marker is what
# stops discovery, so the tmp dir's ancestors do not matter. Production code is
# unchanged: the fix lives here, not in a "skip under pytest" branch.
# TestTelemetryIsolation proves both halves: the cwd is the sandbox, and the
# recorder really writes a row there.

_TELEMETRY_SANDBOX = {}

# #282 R3: every arbiter launch resolves its fixed reviewer cwd from XDG_RUNTIME_DIR, so the
# module also points that at a throwaway runtime dir (a SIBLING of the sandbox, never inside
# the cwd) for in-process calls and every child that copies os.environ — no test creates or
# runs a stub in the host's real /run/user/<uid>/foundry-reviewer-cwd.
_UNSET = object()


def setUpModule():
    tmp = tempfile.TemporaryDirectory(prefix="vas-telemetry-")
    root = Path(tmp.name).resolve() / "telemetry-sandbox"
    (root / ".process-observations").mkdir(parents=True)
    runtime = Path(tmp.name).resolve() / "xdg-runtime"
    runtime.mkdir(mode=0o700)
    _TELEMETRY_SANDBOX.update(tmp=tmp, root=root, prev_cwd=os.getcwd(), runtime=runtime,
                              prev_xdg=os.environ.get("XDG_RUNTIME_DIR", _UNSET))
    os.environ["XDG_RUNTIME_DIR"] = str(runtime)
    os.chdir(root)


def tearDownModule():
    try:
        os.chdir(_TELEMETRY_SANDBOX.pop("prev_cwd"))
    finally:
        prev_xdg = _TELEMETRY_SANDBOX.pop("prev_xdg", _UNSET)
        if prev_xdg is _UNSET:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        else:
            os.environ["XDG_RUNTIME_DIR"] = prev_xdg
        _TELEMETRY_SANDBOX.pop("root", None)
        _TELEMETRY_SANDBOX.pop("runtime", None)
        _TELEMETRY_SANDBOX.pop("tmp").cleanup()


def make_sample_bundle(component_id: str = "comp-x"):
    """Build a bundle and its canonical hash (content-addressed)."""
    bundle = {
        "component_id": component_id,
        "produced_by": "bob-trusted-runner",
        "run_at": "2026-04-21T00:00:00Z",
        "runner_info": {"runner": "pytest", "version": "8.0"},
        "test_paths": ["tests/unit/test_x.py"],
        "results": [
            {
                "path": "tests/unit/test_x.py",
                "returncode": 0,
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0, "error": 0, "duration_s": 0.1},
                "tests": [{"nodeid": "tests/unit/test_x.py::test_a", "outcome": "passed", "duration_s": 0.1, "keywords": []}],
                "failed_tests": [],
            }
        ],
    }
    h = bundle_hash_hex(bundle)
    return bundle, h


def make_sample_plan():
    return {
        "plan_version": "v1",
        "requirements": [
            {"id": "REQ-001", "tier": 0},
        ],
        "skips": [],
    }


def valid_verdict_for(bundle_hash: str, request_id: str = HEX32, attempt_id: str = "att-1",
                     prior_state_version: str = "sv-1",
                     plan_hash: str = HEX64_PLAN,
                     inventory_hash: str = HEX64_INV,
                     runner_version: str = RUNNER_VERSION,
                     rubric_version: str = RUBRIC_VERSION):
    return {
        "verdict": "VERIFIED",
        "request_id": request_id,
        "attempt_id": attempt_id,
        "prior_state_version": prior_state_version,
        "bundle_hash": bundle_hash,
        "plan_hash": plan_hash,
        "inventory_hash": inventory_hash,
        "runner_version": runner_version,
        "rubric_version": rubric_version,
        "coverage": {
            "requirements_total": 1,
            "requirements_covered": 1,
            "uncovered": [],
            "skipped_with_reason": [],
        },
        "concerns": [],
        "self_hash_check": {
            "bundle_recomputed_hash": bundle_hash,
            "matches_input": True,
        },
        # S048 / #116 R-B2: evidence_map is now a REQUIRED top-level key.
        "evidence_map": {"REQ-1": ["tests/test_x.py::test_a"]},
    }


def write_bundle_and_plan(tmpdir: Path):
    bundle, bhash = make_sample_bundle()
    plan = make_sample_plan()
    bundle_path = tmpdir / "bundle.json"
    plan_path = tmpdir / "plan.json"
    bundle_path.write_text(json.dumps(bundle))
    plan_bytes = json.dumps(plan).encode("utf-8")
    plan_path.write_bytes(plan_bytes)
    phash = hashlib.sha256(plan_bytes).hexdigest()
    return bundle_path, bhash, plan_path, phash


def fake_completed_process(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


def run_main_capture(argv, stdout_buf, stderr_buf):
    """Run vas.main(argv) and capture SystemExit code + stdout/stderr."""
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = stdout_buf
    sys.stderr = stderr_buf
    try:
        try:
            vas.main(argv)
            return None  # should not reach — main always SystemExits
        except SystemExit as e:
            return int(e.code) if e.code is not None else 0
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestArgvValidation(unittest.TestCase):
    def test_too_few_args_exits_3(self):
        import io
        out, err = io.StringIO(), io.StringIO()
        code = run_main_capture(["prog", "only-one-arg"], out, err)
        self.assertEqual(code, 3)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["verdict"], "AUDIT_UNAVAILABLE")
        self.assertTrue(payload["reason"].startswith("ENV_ERROR"))

    def test_too_many_args_exits_3(self):
        import io
        out, err = io.StringIO(), io.StringIO()
        code = run_main_capture(["prog"] + ["x"] * 15, out, err)
        self.assertEqual(code, 3)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["verdict"], "AUDIT_UNAVAILABLE")

    def test_bad_bundle_hash_format_exits_3(self):
        import io, tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, _bhash, plan_path, plan_hash = write_bundle_and_plan(tmp)
            argv = [
                "prog",
                str(bundle_path),
                "NOT-HEX",           # bundle_hash invalid
                HEX32,
                "att",
                "sv",
                str(plan_path),
                plan_hash,
                HEX64_INV,
                RUNNER_VERSION,
                RUBRIC_VERSION,
            ]
            out, err = io.StringIO(), io.StringIO()
            code = run_main_capture(argv, out, err)
            self.assertEqual(code, 3)


class TestHappyPath(unittest.TestCase):
    def test_valid_verdict_returns_exit_0(self):
        import io, tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)
            verdict_body = valid_verdict_for(bhash, plan_hash=phash)

            def fake_run(cmd, **kwargs):
                # claude -p --output-format json — return raw JSON (shape c: raw verdict)
                return fake_completed_process(stdout=json.dumps(verdict_body), returncode=0)

            argv = [
                "prog",
                str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION,
            ]
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(vas.subprocess, "run", side_effect=fake_run):
                code = run_main_capture(argv, out, err)
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["verdict"], "VERIFIED")
            # All 8 tuple fields echoed verbatim
            self.assertEqual(payload["request_id"], HEX32)
            self.assertEqual(payload["bundle_hash"], bhash)
            self.assertEqual(payload["plan_hash"], phash)
            self.assertEqual(payload["inventory_hash"], HEX64_INV)
            self.assertEqual(payload["runner_version"], RUNNER_VERSION)
            self.assertEqual(payload["rubric_version"], RUBRIC_VERSION)

    def test_tuple_echo_mismatch_yields_audit_unavailable(self):
        import io, tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)
            # Subprocess returns a valid-schema verdict BUT with a different attempt_id
            tampered = valid_verdict_for(bhash, plan_hash=phash, attempt_id="DIFFERENT")

            def fake_run(cmd, **kwargs):
                return fake_completed_process(stdout=json.dumps(tampered), returncode=0)

            argv = [
                "prog",
                str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION,
            ]
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(vas.subprocess, "run", side_effect=fake_run):
                code = run_main_capture(argv, out, err)
            self.assertEqual(code, 4)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["verdict"], "AUDIT_UNAVAILABLE")
            self.assertIn("attempt_id", payload.get("tuple_echo_error", ""))


class TestSchemaValidation(unittest.TestCase):
    def test_missing_required_field_exits_4(self):
        import io, tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)
            incomplete = valid_verdict_for(bhash, plan_hash=phash)
            del incomplete["coverage"]  # remove required field

            def fake_run(cmd, **kwargs):
                return fake_completed_process(stdout=json.dumps(incomplete), returncode=0)

            argv = [
                "prog",
                str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION,
            ]
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(vas.subprocess, "run", side_effect=fake_run):
                code = run_main_capture(argv, out, err)
            self.assertEqual(code, 4)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["verdict"], "AUDIT_UNAVAILABLE")
            self.assertIn("schema_error", payload)
            self.assertIn("coverage", payload["schema_error"])

    def test_model_returns_audit_unavailable_is_rejected(self):
        """The model is never allowed to produce AUDIT_UNAVAILABLE — only the script."""
        import io, tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)
            forbidden = valid_verdict_for(bhash, plan_hash=phash)
            forbidden["verdict"] = "AUDIT_UNAVAILABLE"

            def fake_run(cmd, **kwargs):
                return fake_completed_process(stdout=json.dumps(forbidden), returncode=0)

            argv = [
                "prog",
                str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION,
            ]
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(vas.subprocess, "run", side_effect=fake_run):
                code = run_main_capture(argv, out, err)
            self.assertEqual(code, 4)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["verdict"], "AUDIT_UNAVAILABLE")
            self.assertIn("schema_error", payload)


class TestEvidenceMapContract(unittest.TestCase):
    """S048 / #116 R-B2 — the LOAD-BEARING proof: the arbiter must ACCEPT its
    OWN evidence_map output (else validate_verdict rejects every verdict -> bob
    halts). Also: a post-cutover verdict missing evidence_map is rejected, and a
    malformed evidence_map is rejected."""

    def test_validate_verdict_accepts_its_own_evidence_map(self):
        # The exact shape the bumped prompt asks the model to emit.
        v = valid_verdict_for("b" * 64)
        v["evidence_map"] = {"REQ-1": ["tests/test_x.py::test_a",
                                       "tests/test_x.py::test_b"]}
        validated, err = vas.validate_verdict(v)
        self.assertIsNone(err, f"arbiter rejected its own evidence_map: {err}")
        self.assertIsNotNone(validated)
        self.assertIn("evidence_map", validated)

    def test_evidence_map_in_required_top_keys(self):
        self.assertIn("evidence_map", vas.REQUIRED_TOP_KEYS)

    def test_verdict_without_evidence_map_rejected(self):
        v = valid_verdict_for("b" * 64)
        del v["evidence_map"]
        validated, err = vas.validate_verdict(v)
        self.assertIsNone(validated)
        self.assertIn("evidence_map", err)

    def test_empty_evidence_map_is_valid(self):
        # A degraded/jest bundle legitimately yields {} -> still valid shape.
        v = valid_verdict_for("b" * 64)
        v["evidence_map"] = {}
        validated, err = vas.validate_verdict(v)
        self.assertIsNone(err, err)
        self.assertIsNotNone(validated)

    def test_malformed_evidence_map_value_rejected(self):
        v = valid_verdict_for("b" * 64)
        v["evidence_map"] = {"REQ-1": "not-a-list"}
        validated, err = vas.validate_verdict(v)
        self.assertIsNone(validated)
        self.assertIn("evidence_map", err)

    def test_evidence_map_nonstring_nodeid_rejected(self):
        v = valid_verdict_for("b" * 64)
        v["evidence_map"] = {"REQ-1": [123]}
        validated, err = vas.validate_verdict(v)
        self.assertIsNone(validated)
        self.assertIn("evidence_map", err)


class TestSubprocessFailures(unittest.TestCase):
    def test_nonzero_returncode_exits_4(self):
        import io, tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)

            def fake_run(cmd, **kwargs):
                return fake_completed_process(stdout="", returncode=2, stderr="boom")

            argv = [
                "prog",
                str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION,
            ]
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(vas.subprocess, "run", side_effect=fake_run):
                code = run_main_capture(argv, out, err)
            self.assertEqual(code, 4)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["verdict"], "AUDIT_UNAVAILABLE")
            self.assertIn("subprocess_error", payload)
            self.assertIn("exited 2", payload["subprocess_error"])

    def test_garbage_stdout_exits_4(self):
        import io, tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)

            def fake_run(cmd, **kwargs):
                return fake_completed_process(stdout="this is not json at all", returncode=0)

            argv = [
                "prog",
                str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION,
            ]
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(vas.subprocess, "run", side_effect=fake_run):
                code = run_main_capture(argv, out, err)
            self.assertEqual(code, 4)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["verdict"], "AUDIT_UNAVAILABLE")

    def test_binary_not_found_exits_4(self):
        import io, tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)

            def fake_run(cmd, **kwargs):
                raise FileNotFoundError("no claude here")

            argv = [
                "prog",
                str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION,
            ]
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(vas.subprocess, "run", side_effect=fake_run):
                code = run_main_capture(argv, out, err)
            self.assertEqual(code, 4)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["verdict"], "AUDIT_UNAVAILABLE")
            self.assertIn("claude binary not found", payload.get("subprocess_error", ""))

    def test_timeout_exits_4(self):
        import io, tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)

            def fake_run(cmd, **kwargs):
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=180)

            argv = [
                "prog",
                str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION,
            ]
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(vas.subprocess, "run", side_effect=fake_run):
                code = run_main_capture(argv, out, err)
            self.assertEqual(code, 4)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["verdict"], "AUDIT_UNAVAILABLE")
            self.assertIn("timed out", payload.get("subprocess_error", ""))


class TestStreamArrayEnvelope(unittest.TestCase):
    """Confirm the claude stream-array envelope (shape a) is correctly parsed."""

    def test_stream_array_envelope_happy_path(self):
        import io, tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)
            verdict_body = valid_verdict_for(bhash, plan_hash=phash)
            # Shape (a): list of stream messages with final {type:result,result:"..."}
            envelope = [
                {"type": "system", "subtype": "init"},
                {"type": "assistant", "message": {"content": [
                    {"type": "text", "text": json.dumps(verdict_body)}
                ]}},
                {"type": "result", "subtype": "success", "result": json.dumps(verdict_body)},
            ]

            def fake_run(cmd, **kwargs):
                return fake_completed_process(stdout=json.dumps(envelope), returncode=0)

            argv = [
                "prog",
                str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION,
            ]
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(vas.subprocess, "run", side_effect=fake_run):
                code = run_main_capture(argv, out, err)
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["verdict"], "VERIFIED")


class TestTimeoutFlag(unittest.TestCase):
    """S030 follow-up #59: --timeout knob mirrors audit_spawn.py."""

    def _argv_with(self, bundle_path, bhash, plan_path, phash, *extra):
        return [
            "prog",
            str(bundle_path), bhash, HEX32, "att-1", "sv-1",
            str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION,
            *extra,
        ]

    def test_default_timeout_600s(self):
        """S081 stream 1 (L3): 180 -> 600. Renamed from test_default_timeout_180s
        with BOTH assertions carried forward at the new value — the default is
        applied, and the default is 600. Real opus arbiter rows timed out at
        180-240s (5 of 21) and the arm now runs fable, whose latency is unmeasured."""
        import io, tempfile
        captured = {}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)
            verdict_body = valid_verdict_for(bhash, plan_hash=phash)

            def fake_runner(prompt, timeout_s, usage_out=None):
                captured["timeout_s"] = timeout_s
                return verdict_body, None

            argv = self._argv_with(bundle_path, bhash, plan_path, phash)
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(vas, "run_claude_arbiter", side_effect=fake_runner):
                code = run_main_capture(argv, out, err)
            self.assertEqual(code, 0)
            self.assertEqual(captured["timeout_s"], vas.DEFAULT_TIMEOUT_S)
            self.assertEqual(captured["timeout_s"], 600)
            # S081 WP-R06 (I1): the value is OWNED by the code_reviewer Claude row, not
            # by the `arbiter` row (1200, the avengers / ratification arbiter).
            self.assertEqual(vas.DEFAULT_TIMEOUT_S,
                             seat_model.ROLE_TABLE["code_reviewer"]["claude"].timeout)
            self.assertNotEqual(vas.DEFAULT_TIMEOUT_S,
                                seat_model.ROLE_TABLE["arbiter"]["claude"].timeout)

    def test_custom_timeout_300s(self):
        import io, tempfile
        captured = {}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)
            verdict_body = valid_verdict_for(bhash, plan_hash=phash)

            def fake_runner(prompt, timeout_s, usage_out=None):
                captured["timeout_s"] = timeout_s
                return verdict_body, None

            argv = self._argv_with(bundle_path, bhash, plan_path, phash, "--timeout", "300")
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(vas, "run_claude_arbiter", side_effect=fake_runner):
                code = run_main_capture(argv, out, err)
            self.assertEqual(code, 0)
            self.assertEqual(captured["timeout_s"], 300)

    def test_invalid_timeout_value_errors(self):
        import io, tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)
            argv = self._argv_with(bundle_path, bhash, plan_path, phash, "--timeout", "abc")
            out, err = io.StringIO(), io.StringIO()
            code = run_main_capture(argv, out, err)
            self.assertEqual(code, 3)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["verdict"], "AUDIT_UNAVAILABLE")
            self.assertTrue(payload["reason"].startswith("ENV_ERROR"))
            self.assertIn("--timeout", payload["reason"])

    def test_missing_timeout_value_errors(self):
        import io, tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)
            # `--timeout` as the LAST argv slot -> no value following
            argv = self._argv_with(bundle_path, bhash, plan_path, phash, "--timeout")
            out, err = io.StringIO(), io.StringIO()
            code = run_main_capture(argv, out, err)
            self.assertEqual(code, 3)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["verdict"], "AUDIT_UNAVAILABLE")
            self.assertIn("--timeout", payload["reason"])


# ---------------------------------------------------------------------------
# S081 stream 1 — P0 containment (design §4.1, WP-P01)
# ---------------------------------------------------------------------------
#
# Every guarantee is paired with a control. Child processes run with
# HOME=<tmp> (no live ~/.codex or ~/.claude state) and cwd outside any project.

_REVIEWER_ENV = (
    "AUDIT_CLAUDE_MODEL", "ARBITER_CLAUDE_MODEL", "AUDIT_CODEX_MODEL",
    "AUDIT_CLAUDE_BIN", "AUDIT_CODEX_BIN",
)
_RESOLVER = SCRIPT_DIR.parent / "smart-config" / "scripts" / "model_policy.py"
_POISON = "version: 1\ntiers:\n  complex:\n    claude-code: haiku\n"
_REFUSED_TAG = "ARBITER_ENV_OVERRIDE_REFUSED "
_BIN_TAG = "ARBITER_BIN_OVERRIDE "

_STUB = """#!{python}
import json, os, sys
with open(os.environ["STUB_ARGV_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({{"bin": os.path.basename(sys.argv[0]), "argv": sys.argv[1:]}}) + "\\n")
sys.stdout.write(os.environ["STUB_VERDICT_JSON"])
"""


def _fixture_home(tmp: Path) -> Path:
    """HOME with a COPY of smart-config's resolver at the exact `~/.claude/...`
    path the pre-S081 wiring invoked, so re-adding that call is poisoned again
    rather than silently falling back on a missing file."""
    home = tmp / "home"
    dst = home / ".claude" / "skills" / "smart-config" / "scripts"
    dst.mkdir(parents=True)
    shutil.copy2(_RESOLVER, dst / "model_policy.py")
    return home


def _poisoned_cwd(tmp: Path) -> Path:
    cwd = tmp / "poisoned-repo"
    (cwd / ".claude").mkdir(parents=True)
    (cwd / ".claude" / "model-policy.yaml").write_text(_POISON, encoding="utf-8")
    return cwd


def _child_env(home: Path, **overrides):
    env = {k: v for k, v in os.environ.items() if k not in _REVIEWER_ENV}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.update(overrides)
    return env


def _write_stub(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_STUB.format(python=sys.executable), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _tagged(stderr: str, tag: str):
    return [json.loads(line[len(tag):]) for line in stderr.splitlines() if line.startswith(tag)]


class TestReviewerModelContainment(unittest.TestCase):

    def test_poisoned_cwd_cannot_downgrade_the_arbiter(self):
        """L1 TRUST, with a POSITIVE CONTROL proving the fixture poisons smart-config."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = _fixture_home(tmp)
            cwd = _poisoned_cwd(tmp)
            env = _child_env(home)
            resolver = home / ".claude" / "skills" / "smart-config" / "scripts" / "model_policy.py"
            ctl = subprocess.run(
                [sys.executable, str(resolver), "resolve", "--tier", "complex",
                 "--surface", "headless", "--no-log"],
                cwd=str(cwd), env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=60, stdin=subprocess.DEVNULL,
            )
            self.assertEqual(ctl.returncode, 0, ctl.stderr)
            poisoned = json.loads(ctl.stdout.strip().splitlines()[-1])
            self.assertEqual((poisoned["model"], poisoned["source"]), ("haiku", "project"))

            probe = (
                "import json, sys; sys.path.insert(0, sys.argv[1]); "
                "import verification_arbiter_spawn as m; "
                "print(json.dumps([m.CLAUDE_MODEL, getattr(m, 'CLAUDE_MODEL_SOURCE', None)]))"
            )
            proc = subprocess.run(
                [sys.executable, "-c", probe, str(SCRIPT_DIR)],
                cwd=str(cwd), env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=60, stdin=subprocess.DEVNULL,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            model, source = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertEqual(model, MAIN)
            self.assertEqual(source, "harness_literal")

    def test_resolution_never_invokes_smart_config(self):
        """No call builds a model_policy.py path, and neither resolution function has
        a subprocess. NEGATIVE CONTROL: the pre-S081 shape is flagged.

        S081 WP-R06: `_resolve_arbiter_model` became `_resolve_arbiter_pin` (plus the
        env-candidate helper); the assertions carry forward to both, and the pin is
        proven to come from seat_model (the one resolver), not a literal."""
        def calls_mentioning(tree, needle):
            return [
                n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and any(isinstance(s, ast.Constant) and isinstance(s.value, str)
                        and needle in s.value for s in ast.walk(n))
            ]

        def uses_subprocess(func):
            return any(isinstance(n, ast.Name) and n.id == "subprocess" for n in ast.walk(func))

        def calls_seat_model_resolve(func):
            return any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "resolve" and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "seat_model"
                for n in ast.walk(func)
            )

        control = ast.parse(
            "def _resolve_arbiter_pin():\n"
            "    resolver = os.path.expanduser('~/.claude/skills/smart-config/scripts/model_policy.py')\n"
            "    proc = subprocess.run(['python3', resolver, 'resolve'])\n"
        )
        self.assertTrue(calls_mentioning(control, "model_policy"))
        self.assertTrue(uses_subprocess(control.body[0]))
        self.assertFalse(calls_seat_model_resolve(control.body[0]))

        tree = ast.parse(Path(vas.__file__).read_text(encoding="utf-8"))
        self.assertEqual(calls_mentioning(tree, "model_policy"), [])
        funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        self.assertFalse(uses_subprocess(funcs["_resolve_arbiter_pin"]))
        self.assertFalse(uses_subprocess(funcs["_arbiter_env_var"]))
        self.assertTrue(calls_seat_model_resolve(funcs["_resolve_arbiter_pin"]))
        self.assertFalse(hasattr(vas, "_resolve_arbiter_model"),
                         "stream 1's ad-hoc env gating must be replaced, not duplicated")

    def test_env_override_is_gated_to_the_pin(self):
        """L2: ARBITER_CLAUDE_MODEL > AUDIT_CLAUDE_MODEL, each honoured only when
        equal to the pin; the refusal names the variable that was actually read.

        Carried forward from stream 1 onto seat_model's provenance: the same six cases,
        and the refusal record is seat_model's {var, value, reason}."""
        clean = {k: v for k, v in os.environ.items() if k not in _REVIEWER_ENV}
        cases = [
            ({"ARBITER_CLAUDE_MODEL": "haiku"},
             (MAIN, "harness_literal", {"var": "ARBITER_CLAUDE_MODEL", "value": "haiku"})),
            ({"AUDIT_CLAUDE_MODEL": "haiku"},
             (MAIN, "harness_literal", {"var": "AUDIT_CLAUDE_MODEL", "value": "haiku"})),
            ({"ARBITER_CLAUDE_MODEL": "haiku", "AUDIT_CLAUDE_MODEL": MAIN},
             (MAIN, "harness_literal", {"var": "ARBITER_CLAUDE_MODEL", "value": "haiku"})),
            # A blank ARBITER_CLAUDE_MODEL is not a candidate; AUDIT_CLAUDE_MODEL is read.
            ({"ARBITER_CLAUDE_MODEL": "  ", "AUDIT_CLAUDE_MODEL": "haiku"},
             (MAIN, "harness_literal", {"var": "AUDIT_CLAUDE_MODEL", "value": "haiku"})),
            # CONTROLS: equal to the pin -> accepted with source env.
            ({"ARBITER_CLAUDE_MODEL": MAIN}, (MAIN, "env", None)),
            ({"AUDIT_CLAUDE_MODEL": MAIN}, (MAIN, "env", None)),
            ({}, (MAIN, "harness_literal", None)),
        ]
        for env, (model, source, refused) in cases:
            with self.subTest(env=env):
                with mock.patch.dict(os.environ, dict(clean, **env), clear=True):
                    pin = vas._resolve_arbiter_pin()
                prov = pin.provenance
                self.assertEqual((pin.model, prov["source"]), (model, source))
                got = prov.get("env_override_refused")
                if refused is None:
                    self.assertIsNone(got)
                else:
                    self.assertEqual({k: got[k] for k in ("var", "value")}, refused)
                    self.assertIn("protected", got["reason"])
        # L4: the declared fallback is the role row's alias, the Claude main tier (MAIN, from model_roster).
        with mock.patch.dict(os.environ, clean, clear=True):
            pin = vas._resolve_arbiter_pin()
        self.assertEqual(pin.provenance["resolved_model"], MAIN)
        self.assertEqual(pin.provenance["requested_selector"], MAIN)
        self.assertEqual(pin, seat_model.resolve("code_reviewer", "claude",
                                                 env_var="ARBITER_CLAUDE_MODEL", fail_open=True))
        self.assertEqual(vas.REVIEWER_ROLE, "code_reviewer")

    def _run_cli(self, tmp: Path, env):
        bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)
        verdict_body = valid_verdict_for(bhash, plan_hash=phash)
        argv_log = tmp / "argv.jsonl"
        env = dict(env, STUB_ARGV_LOG=str(argv_log), STUB_VERDICT_JSON=json.dumps(verdict_body))
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "verification_arbiter_spawn.py"),
             str(bundle_path), bhash, HEX32, "att-1", "sv-1",
             str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION],
            cwd=str(_poisoned_cwd(tmp)), env=env, capture_output=True, text=True,
            encoding="utf-8", timeout=120, stdin=subprocess.DEVNULL,
        )
        calls = [json.loads(l) for l in argv_log.read_text(encoding="utf-8").splitlines() if l]
        return proc, verdict_body, calls

    @unittest.skipIf(sys.platform.startswith("win"), "stub binaries use a POSIX shebang")
    def test_refusal_and_bin_override_are_structured_stderr_lines(self):
        """L2 + BIN end to end: ONE structured refusal line, the bin realpath on
        stderr, the pinned model on argv, and the closed verdict object unchanged (I2)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            stub = _write_stub(tmp / "bin" / "claude-stub")
            env = _child_env(_fixture_home(tmp), ARBITER_CLAUDE_MODEL="haiku",
                             AUDIT_CLAUDE_BIN=str(stub))
            proc, verdict_body, calls = self._run_cli(tmp, env)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout), verdict_body)
            refused = _tagged(proc.stderr, _REFUSED_TAG)
            self.assertEqual([{k: r[k] for k in ("var", "value")} for r in refused],
                             [{"var": "ARBITER_CLAUDE_MODEL", "value": "haiku"}])
            # WP-R06: the record is seat_model's, so it also says WHY it was refused.
            self.assertEqual(set(refused[0]), {"var", "value", "reason"})
            self.assertEqual(_tagged(proc.stderr, _BIN_TAG), [{
                "var": "AUDIT_CLAUDE_BIN", "value": str(stub),
                "realpath": os.path.realpath(str(stub)),
            }])
            argv = calls[0]["argv"]
            self.assertEqual(argv[argv.index("--model") + 1], MAIN)
            # Written at import: non-ASCII could raise on a cp1252 console (W003).
            self.assertTrue(proc.stderr.isascii())

    @unittest.skipIf(sys.platform.startswith("win"), "stub binaries use a POSIX shebang")
    def test_equal_override_and_unset_bin_emit_no_records(self):
        """CONTROL: the same stub reached via PATH, BIN unset, override equal to the pin."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bindir = tmp / "pathbin"
            _write_stub(bindir / "claude")
            env = _child_env(_fixture_home(tmp), ARBITER_CLAUDE_MODEL=MAIN)
            env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
            proc, verdict_body, calls = self._run_cli(tmp, env)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout), verdict_body)
            self.assertEqual(_tagged(proc.stderr, _REFUSED_TAG), [])
            self.assertEqual(_tagged(proc.stderr, _BIN_TAG), [])
            self.assertNotIn("WARNING", proc.stderr)
            self.assertEqual([c["bin"] for c in calls], ["claude"])
            argv = calls[0]["argv"]
            self.assertEqual(argv[argv.index("--model") + 1], MAIN)


class TestTelemetryIsolation(unittest.TestCase):
    """S081 WP-R01 (design §4.11, L6): this module never writes a tracked
    .process-observations/ — and the recorder still writes, into the sandbox."""

    @staticmethod
    def _sandbox_rows():
        p = _TELEMETRY_SANDBOX["root"] / ".process-observations" / "spawn-runs.jsonl"
        if not p.is_file():
            return []
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_module_runs_inside_its_own_telemetry_root(self):
        """ISOLATION: every in-process main() sees the sandbox as its cwd, and the
        sandbox carries the marker that stops discovery walking up to a real project."""
        self.assertIn("root", _TELEMETRY_SANDBOX, "setUpModule did not install the sandbox")
        root = _TELEMETRY_SANDBOX["root"]
        self.assertEqual(Path.cwd().resolve(), root)
        self.assertTrue((root / ".process-observations").is_dir())
        self.assertNotEqual(Path(_TELEMETRY_SANDBOX["prev_cwd"]).resolve(), root)

    def test_in_process_main_records_into_the_sandbox(self):
        """CONTROL: a happy-path main() appends exactly one row, with the expected
        keys, to the sandbox — isolation is not passing because nothing was written."""
        import io
        self.assertIn("root", _TELEMETRY_SANDBOX, "setUpModule did not install the sandbox")
        before = len(self._sandbox_rows())
        with tempfile.TemporaryDirectory() as td:
            bundle_path, bhash, plan_path, phash = write_bundle_and_plan(Path(td))
            verdict_body = valid_verdict_for(bhash, plan_hash=phash)
            argv = [
                "prog",
                str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION,
            ]
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(
                vas.subprocess, "run",
                side_effect=lambda cmd, **kw: fake_completed_process(stdout=json.dumps(verdict_body)),
            ):
                code = run_main_capture(argv, out, err)
        self.assertEqual(code, 0, err.getvalue())
        rows = self._sandbox_rows()
        self.assertEqual(len(rows) - before, 1)
        row = rows[-1]
        self.assertEqual(
            (row["tool"], row["status"], row["component_id"], row["request_id"], row["bundle_hash"]),
            ("verification_arbiter", "VERIFIED", "comp-x", HEX32, bhash),
        )
        self.assertEqual(row["model"], vas.CLAUDE_MODEL)
        # S081 WP-R06 (design §4.11): the provenance fields ride the row.
        self.assertEqual(
            (row["requested_model"], row["served_model"], row["role"]),
            (vas.CLAUDE_MODEL, "unknown", "code_reviewer"),
        )
        # Absent means "did not happen": a raw verdict has no usage, nothing was
        # refused, and Claude is not metered by codex_quota.
        for absent in ("tokens", "env_override_refused", "quota_before", "quota_after", "quota_source"):
            self.assertNotIn(absent, row)


# ---------------------------------------------------------------------------
# #282 R3 — the arbiter never loads the reviewed project's configuration
# ---------------------------------------------------------------------------
#
# Plan K3-K5. The arbiter subprocess runs from ONE fixed empty directory (resolved from the
# module's throwaway XDG_RUNTIME_DIR, see setUpModule) with `--setting-sources user`, never
# `--bare`, and the prompt on a piped stdin that EOFs (#290); its served model comes from the envelope's modelUsage. The
# resolver's full safety matrix and the parity with audit_spawn.py's copy are in
# test_audit_spawn_defaults.py; here each guarantee is proven on THIS launcher, with a control.

_R3_STUB = """#!{python}
import json, os, select, sys

def drain_stdin():
    # Read stdin until EOF or 1 s of silence: returns (bytes read, reached EOF).
    data = b""
    try:
        while True:
            ready, _, _ = select.select([0], [], [], 1.0)
            if not ready:
                return data, False
            chunk = os.read(0, 65536)
            if chunk == b"":
                return data, True
            data += chunk
    except OSError:
        return data, False

_stdin_data, _stdin_eof = drain_stdin()

with open(os.environ["STUB_ARGV_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({{"bin": os.path.basename(sys.argv[0]), "argv": sys.argv[1:], "cwd": os.getcwd(),
                         "settings_visible": os.path.exists(os.path.join(".claude", "settings.json")),
                         "dot_claude": os.path.lexists(".claude"), "stdin_eof": _stdin_eof,
                         "stdin_len": len(_stdin_data),
                         "stdin_head": _stdin_data[:64].decode("utf-8", "replace")}}) + "\\n")
sys.stdout.write(os.environ["STUB_VERDICT_JSON"])
"""

_R3_SETTINGS_POISON = {"model": "haiku", "env": {"X": "1"}}


def _r3_settings_poisoned_project(root: Path) -> Path:
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "settings.json").write_text(json.dumps(_R3_SETTINGS_POISON), encoding="utf-8")
    return root


def _r3_reviewer_dir() -> str:
    return os.path.realpath(os.path.join(os.environ["XDG_RUNTIME_DIR"], vas.REVIEWER_CWD_NAME))


def _mkdir_chain(path: Path, mode: int = 0o700) -> Path:
    """Create `path` and every missing parent AT `mode` (duplicated from
    test_audit_spawn_defaults.py, plan K2). #282 fix round 1 F4 / plan K38: an ancestor
    that is group- or world-writable without the sticky bit is refused, and a plain mkdir
    under the common umask 002 yields 0o775 — so every fixture chain that must be ACCEPTED
    is created explicitly. Path.mkdir(parents=True, mode=...) applies `mode` to the leaf
    only."""
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=mode)
    return path


@unittest.skipIf(sys.platform.startswith("win"), "stub binaries use a POSIX shebang")
class TestReviewerIsolationR3(unittest.TestCase):

    def _run(self, tmp: Path, caller_cwd: Path, *, envelope=None, stdin=subprocess.DEVNULL, extra_env=None):
        bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)
        verdict_body = valid_verdict_for(bhash, plan_hash=phash)
        stub = _write_stub(tmp / "bin" / "claude-stub")
        stub.write_text(_R3_STUB.format(python=sys.executable), encoding="utf-8")
        log = tmp / "r3-argv.jsonl"
        env = _child_env(_fixture_home(tmp), AUDIT_CLAUDE_BIN=str(stub), STUB_ARGV_LOG=str(log),
                         STUB_VERDICT_JSON=envelope if envelope is not None else json.dumps(verdict_body))
        env.update(extra_env or {})
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "verification_arbiter_spawn.py"),
             str(bundle_path), bhash, HEX32, "att-1", "sv-1",
             str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION],
            cwd=str(caller_cwd), env=env, stdin=stdin, capture_output=True, text=True,
            encoding="utf-8", timeout=120,
        )
        calls = ([json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l]
                 if log.is_file() else [])
        return proc, verdict_body, calls, stub

    def test_argv_cwd_and_stdin_in_process(self):
        """(a) + (b) + (d, mocked): the pinned model and (#311 F1) the pinned effort, then
        `--setting-sources user`, no --bare / --fallback-model, cwd = the resolved reviewer dir, and the prompt on stdin via
        `input=`, never in argv (#290: a >128 KiB argv string is E2BIG)."""
        captured = []

        def fake_run(cmd, **kwargs):
            captured.append((list(cmd), kwargs))
            return fake_completed_process(stdout=json.dumps({"verdict": "x"}))

        with mock.patch.object(vas.subprocess, "run", side_effect=fake_run):
            parsed, err = vas.run_claude_arbiter("the prompt", 60)
        self.assertIsNone(err)
        (cmd, kwargs), = captured
        self.assertEqual(cmd[1:], ["-p", "--model", vas.CLAUDE_MODEL, "--effort", ARBITER_EFFORT,
                                   "--setting-sources", "user", "--output-format", "json"])
        for forbidden in ("--bare", "--fallback-model"):
            self.assertFalse(any(str(t).startswith(forbidden) for t in cmd), forbidden)
        self.assertEqual(kwargs["cwd"], _r3_reviewer_dir())
        self.assertEqual(kwargs["input"], "the prompt")
        self.assertNotIn("stdin", kwargs)  # subprocess.run refuses stdin= together with input=
        self.assertFalse(os.path.lexists(os.path.join(_r3_reviewer_dir(), ".claude")))

    def test_311_f1_a_missing_effort_refuses_to_spawn(self):
        """#311 fix round 1 F1: the arbiter never launches without its pinned effort."""
        self.assertEqual(vas.CLAUDE_EFFORT, ARBITER_EFFORT)
        for bad in (None, "", "ludicrous"):
            captured = []
            with mock.patch.object(vas, "CLAUDE_EFFORT", bad), \
                    mock.patch.object(vas.subprocess, "run", side_effect=lambda cmd, **kw: captured.append(cmd)):
                parsed, err = vas.run_claude_arbiter("the prompt", 60)
            self.assertIsNone(parsed)
            self.assertIn("effort", err)
            self.assertEqual(captured, [], bad)

    def test_a_poisoned_caller_cwd_is_invisible_and_stdin_is_at_eof(self):
        """(b) + (c) + (d) through the REAL CLI, launched from a project whose `.claude/settings.json`
        sets a model and an env, with the CLI's OWN stdin an open pipe that never EOFs: the stub ran in
        the reviewer dir, saw no settings file and no `.claude/`, carried `--setting-sources user`, and
        its stdin carried the prompt and then reached EOF. CONTROLS: the same stub with the PRE-R3 argv and cwd sees the settings
        file; with an open pipe as its stdin it reports not-at-EOF (so the EOF above is the launcher's)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            project = _r3_settings_poisoned_project(tmp / "settings-poisoned")
            read_end, write_end = os.pipe()
            try:
                proc, verdict_body, calls, stub = self._run(tmp, project, stdin=read_end)
            finally:
                os.close(read_end)
                os.close(write_end)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout), verdict_body)
            (call,) = calls
            self.assertEqual(call["cwd"], _r3_reviewer_dir())
            self.assertIs(call["settings_visible"], False)
            self.assertIs(call["dot_claude"], False)
            self.assertIs(call["stdin_eof"], True)
            self.assertGreater(call["stdin_len"], 0)  # the prompt arrived on stdin (#290)
            self.assertEqual(call["argv"][:8], ["-p", "--model", MAIN, "--effort", ARBITER_EFFORT,   # #311 F1
                                                "--setting-sources", "user", "--output-format"])
            self.assertNotIn("--bare", call["argv"])

            log = tmp / "r3-argv.jsonl"
            env = dict(os.environ, STUB_ARGV_LOG=str(log), STUB_VERDICT_JSON="{}")
            subprocess.run([str(stub), "-p", "--model", "fable", "--output-format", "json", "p"],
                           cwd=str(project), env=env, stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=30, check=True)
            read_end, write_end = os.pipe()
            try:
                subprocess.run([str(stub), "-p"], cwd=str(tmp), env=env, stdin=read_end,
                               capture_output=True, timeout=30, check=True)
            finally:
                os.close(read_end)
                os.close(write_end)
            pre_r3, open_pipe = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()][1:]
            self.assertEqual(os.path.realpath(pre_r3["cwd"]), os.path.realpath(str(project)))
            self.assertIs(pre_r3["settings_visible"], True)
            self.assertIs(open_pipe["stdin_eof"], False)

    def test_290_a_prompt_over_max_arg_strlen_reaches_the_cli_on_stdin(self):
        """#290 regression: a prompt larger than Linux's MAX_ARG_STRLEN (131072 bytes per argv
        string) launches, arrives whole on stdin, and argv stays small. CONTROL: the same prompt
        as an argv string fails with E2BIG, so the size really is over the limit here."""
        big = "x" * 200_000
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            stub = tmp / "claude"
            stub.write_text(_R3_STUB.format(python=sys.executable), encoding="utf-8")
            stub.chmod(0o755)
            log = tmp / "argv.jsonl"
            env = {"STUB_ARGV_LOG": str(log), "STUB_VERDICT_JSON": json.dumps({"verdict": "ok"})}
            with mock.patch.dict(os.environ, env), \
                    mock.patch.object(vas, "_claude_launch_bin", return_value=str(stub)):
                parsed, err = vas.run_claude_arbiter(big, 60)
            self.assertIsNone(err, err)
            (call,) = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(call["stdin_len"], len(big))
            self.assertIs(call["stdin_eof"], True)
            self.assertLess(sum(len(a) for a in call["argv"]), 1000)
            with self.assertRaises(OSError) as ctx:
                subprocess.run([str(stub), "-p", big], env=dict(os.environ, **env),
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
            self.assertEqual(ctx.exception.errno, 7)  # E2BIG

    def test_a_refused_reviewer_dir_is_exit_4_and_the_stub_never_runs(self):
        """(e) XDG_RUNTIME_DIR planted under a tree whose ancestor holds `.claude/settings.json` -> exit 4
        AUDIT_UNAVAILABLE naming the refusal, and the claude stub was never invoked (the caller's cwd is
        not a fallback). CONTROL: a clean runtime dir -> exit 0 with the verdict."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            planted = _r3_settings_poisoned_project(tmp / "planted") / "run"
            planted.mkdir()
            caller = tmp / "caller"
            caller.mkdir()
            proc, _verdict, calls, _stub = self._run(tmp, caller, extra_env={"XDG_RUNTIME_DIR": str(planted)})
            self.assertEqual(proc.returncode, 4, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["verdict"], "AUDIT_UNAVAILABLE")
            self.assertTrue(payload["subprocess_error"].startswith("reviewer cwd unavailable:"))
            self.assertIn("settings.json", payload["subprocess_error"])
            self.assertEqual(calls, [])

            clean = _mkdir_chain(tmp / "clean-runtime")
            control_tmp = tmp / "control"
            control_tmp.mkdir()
            proc, verdict_body, calls, _stub = self._run(control_tmp, caller,
                                                         extra_env={"XDG_RUNTIME_DIR": str(clean)})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout), verdict_body)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["cwd"], os.path.realpath(str(clean / vas.REVIEWER_CWD_NAME)))

    def test_served_model_mismatch_is_recorded_and_warned_never_a_verdict_change(self):
        """(f) + K4 through the REAL CLI: the envelope names ANOTHER tier's full id for the pinned main-tier
        alias -> exit 0 and the closed verdict object byte-identical, one stderr WARNING, and the row
        carries that served_model, served_model_usage and served_model_mismatch true. CONTROL: the pinned
        alias's own full id -> the id is recorded, no mismatch key, no warning. (#291: before the roster
        swap these were claude-opus-5 for "fable" and claude-fable-5-1.)"""
        for served, mismatch in ((SERVED_ID[SUPPORT], True), (SERVED_ID[MAIN], False)):
            with self.subTest(served=served), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                project = tmp / "project"
                (project / ".process-observations").mkdir(parents=True)
                bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)
                body = valid_verdict_for(bhash, plan_hash=phash)
                envelope = json.dumps({"type": "result", "subtype": "success", "result": json.dumps(body),
                                       "modelUsage": {served: {"inputTokens": 5, "outputTokens": 77}}})
                proc, verdict_body, _calls, _stub = self._run(tmp, project, envelope=envelope)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout), verdict_body)
                rows = [json.loads(l) for l in (project / ".process-observations" / "spawn-runs.jsonl")
                        .read_text(encoding="utf-8").splitlines() if l.strip()]
                (row,) = rows
                self.assertEqual((row["served_model"], row["served_model_usage"]), (served, {served: 77}))
                warnings = [l for l in proc.stderr.splitlines() if "served_model_mismatch" in l]
                if mismatch:
                    self.assertIs(row["served_model_mismatch"], True)
                    self.assertEqual(len(warnings), 1)
                    self.assertIn(served, warnings[0])
                    self.assertTrue(warnings[0].isascii())
                else:
                    self.assertNotIn("served_model_mismatch", row)
                    self.assertEqual(warnings, [])


# ---------------------------------------------------------------------------
# S081 WP-R06 — seat_model provenance and token usage on the telemetry row
# ---------------------------------------------------------------------------


def _stream_envelope(inner: dict, usage=None) -> str:
    result = {"type": "result", "subtype": "success", "result": json.dumps(inner),
              "total_cost_usd": 0.01, "duration_ms": 1000, "num_turns": 1}
    if usage is not None:
        result["usage"] = usage
    return json.dumps([
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": json.dumps(inner)}]}},
        result,
    ])


class TestClaudeTokens(unittest.TestCase):
    """Plan I9: tokens come from the --output-format json envelope; unobservable -> None."""

    def test_stream_array_usage_keeps_integer_token_fields_only(self):
        usage = {"input_tokens": 12, "output_tokens": 34, "cache_read_input_tokens": 5,
                 "cache_creation_input_tokens": 0, "service_tier": "standard",
                 "server_tool_use": {"web_search_requests": 0}, "bogus_tokens": True,
                 "negative_tokens": -1, "float_tokens": 1.5}
        envelope = json.loads(_stream_envelope({"verdict": "x"}, usage))
        self.assertEqual(vas._claude_tokens(envelope), {
            "input_tokens": 12, "output_tokens": 34,
            "cache_read_input_tokens": 5, "cache_creation_input_tokens": 0,
        })
        # Legacy dict envelope.
        self.assertEqual(vas._claude_tokens({"result": "x", "usage": {"output_tokens": 3}}),
                         {"output_tokens": 3})

    def test_unobservable_usage_is_none_never_raises(self):
        for envelope in (None, "", "not json", [], {}, [{"type": "result"}],
                         [{"type": "result", "usage": "lots"}], {"usage": {"service_tier": "x"}},
                         object()):
            with self.subTest(envelope=envelope):
                self.assertIsNone(vas._claude_tokens(envelope))


class TestProvenanceReachesTheTelemetryRow(unittest.TestCase):

    @unittest.skipIf(sys.platform.startswith("win"), "stub binaries use a POSIX shebang")
    def test_refusal_and_tokens_reach_the_row_end_to_end(self):
        """Through the real CLI: a refused override and the envelope's token usage land
        on the spawn-runs row (plan I2, I9), while the closed verdict object on stdout
        stays byte-for-byte the model's verdict. CONTROL: the same run with the override
        equal to the pin records no refusal."""
        for override, expect_refused in (("haiku", True), (MAIN, False)):
            with self.subTest(override=override), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                project = tmp / "project"
                (project / ".process-observations").mkdir(parents=True)
                (project / ".claude").mkdir()
                (project / ".claude" / "model-policy.yaml").write_text(_POISON, encoding="utf-8")
                bundle_path, bhash, plan_path, phash = write_bundle_and_plan(tmp)
                verdict_body = valid_verdict_for(bhash, plan_hash=phash)
                stub = _write_stub(tmp / "bin" / "claude-stub")
                env = _child_env(
                    _fixture_home(tmp), ARBITER_CLAUDE_MODEL=override, AUDIT_CLAUDE_BIN=str(stub),
                    STUB_ARGV_LOG=str(tmp / "argv.jsonl"),
                    STUB_VERDICT_JSON=_stream_envelope(
                        verdict_body, {"input_tokens": 1200, "output_tokens": 80}),
                )
                proc = subprocess.run(
                    [sys.executable, str(SCRIPT_DIR / "verification_arbiter_spawn.py"),
                     str(bundle_path), bhash, HEX32, "att-1", "sv-1",
                     str(plan_path), phash, HEX64_INV, RUNNER_VERSION, RUBRIC_VERSION],
                    cwd=str(project), env=env, capture_output=True, text=True,
                    encoding="utf-8", timeout=120, stdin=subprocess.DEVNULL,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout), verdict_body)
                rows = [json.loads(l) for l in (project / ".process-observations" / "spawn-runs.jsonl")
                        .read_text(encoding="utf-8").splitlines() if l.strip()]
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual((row["model"], row["requested_model"], row["served_model"], row["role"]),
                                 (MAIN, MAIN, "unknown", "code_reviewer"))
                self.assertEqual(row["tokens"], {"input_tokens": 1200, "output_tokens": 80})
                if expect_refused:
                    self.assertEqual({k: row["env_override_refused"][k] for k in ("var", "value")},
                                     {"var": "ARBITER_CLAUDE_MODEL", "value": "haiku"})
                    self.assertEqual(row["env_override_refused"], _tagged(proc.stderr, _REFUSED_TAG)[0])
                else:
                    self.assertNotIn("env_override_refused", row)
                    self.assertEqual(_tagged(proc.stderr, _REFUSED_TAG), [])


class TestReviewerCwdAncestorRulesF2F4F8(unittest.TestCase):
    """#282 fix round 1 F2 / F4 / F8 on THIS launcher's copy of the resolver (plan K2: the
    two copies are duplicated, so each guarantee is proven on both). The full matrix and the
    parity comparison live in test_audit_spawn_defaults.py; here each rule gets one proof and
    one control against `vas.resolve_reviewer_cwd` itself."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vas-reviewer-cwd-")
        self.tmp = Path(self._tmp.name).resolve()
        self._env = dict(os.environ)
        self.addCleanup(self._restore)

    def _restore(self):
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def _reviewer_dir(self) -> str:
        return os.path.realpath(os.path.join(os.environ["XDG_RUNTIME_DIR"], vas.REVIEWER_CWD_NAME))

    def test_f2_home_is_exempt_from_the_settings_markers_but_not_from_claude_md(self):
        """F2 (plan K37): a runtime dir under HOME holding the user's own
        ~/.claude/settings.json is ACCEPTED; CONTROL: CLAUDE.md at HOME still refuses, and a
        `.claude` entry at an ancestor strictly BELOW home refuses."""
        home = _mkdir_chain(self.tmp / "home")
        (home / ".claude").mkdir()
        (home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        runtime = _mkdir_chain(home / "run")
        os.environ["HOME"] = str(home)
        os.environ["USERPROFILE"] = str(home)
        os.environ["XDG_RUNTIME_DIR"] = str(runtime)
        self.assertEqual(Path.home(), home)
        self.assertEqual(vas.resolve_reviewer_cwd(), self._reviewer_dir())

        (home / "CLAUDE.md").write_text("steer", encoding="utf-8")
        with self.assertRaises(vas.ReviewerCwdError) as ctx:
            vas.resolve_reviewer_cwd()
        self.assertIn("CLAUDE.md", str(ctx.exception))
        (home / "CLAUDE.md").unlink()

        (runtime / ".claude").mkdir()
        deeper = runtime / "deep"
        deeper.mkdir(mode=0o700)
        os.environ["XDG_RUNTIME_DIR"] = str(deeper)
        with self.assertRaises(vas.ReviewerCwdError) as ctx:
            vas.resolve_reviewer_cwd()
        self.assertIn(".claude", str(ctx.exception))

    @unittest.skipUnless(hasattr(os, "getuid"), "POSIX ancestor owner/mode rules")
    def test_f4_a_world_writable_ancestor_without_the_sticky_bit_is_refused(self):
        """F4 (plan K38): CONTROL 1777 (the /tmp shape) and 0700 are accepted."""
        parent = self.tmp / "parent"
        parent.mkdir(mode=0o700)
        runtime = parent / "runtime"
        runtime.mkdir(mode=0o700)
        os.environ["XDG_RUNTIME_DIR"] = str(runtime)
        expected = self._reviewer_dir()
        self.assertEqual(vas.resolve_reviewer_cwd(), expected)

        os.chmod(parent, 0o777)
        with self.assertRaises(vas.ReviewerCwdError) as ctx:
            vas.resolve_reviewer_cwd()
        self.assertIn("sticky", str(ctx.exception))
        self.assertIn(str(parent), str(ctx.exception))
        os.chmod(parent, 0o1777)
        self.assertEqual(vas.resolve_reviewer_cwd(), expected)
        os.chmod(parent, 0o700)
        self.assertEqual(vas.resolve_reviewer_cwd(), expected)

    @unittest.skipUnless(hasattr(os, "getuid"), "POSIX ancestor symlink rule")
    def test_f4_a_user_owned_symlinked_ancestor_is_refused(self):
        """F4 (plan K38 (c)): the realpath chain alone never sees it, so the abspath chain is
        walked too. The root-owned carve-out is covered in test_audit_spawn_defaults.py."""
        runtime = self.tmp / "runtime"
        runtime.mkdir(mode=0o700)
        link = self.tmp / "link-runtime"
        try:
            link.symlink_to(runtime, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        os.environ["XDG_RUNTIME_DIR"] = str(link)
        with self.assertRaises(vas.ReviewerCwdError) as ctx:
            vas.resolve_reviewer_cwd()
        self.assertIn("symlink", str(ctx.exception))
        self.assertIn(str(link), str(ctx.exception))

    # --- #282 fix round 2 G1 / G2 (plan K53 / K54), the arbiter's own copy ---
    #
    # G1: `tempfile.gettempdir()` keeps the Windows 8.3 SHORT form
    # (C:\Users\RUNNER~1\AppData\Local\Temp), which equals NEITHER form of HOME as a
    # STRING — so the F2 exemption missed while the marker `lexists` resolved straight
    # through the alias and every arbiter launch failed closed on the user's own
    # ~/.claude/settings.json. NO WINDOWS HOST IS AVAILABLE HERE: the alias is SIMULATED by
    # monkeypatching os.path.realpath, so the LOGIC is verified and the TRIGGER stays
    # INFERRED. G2: a 0775 ancestor with the user's own PRIVATE single-member group (the
    # umask-002 `$HOME/run` shape) is accepted; world-write, a shared group and any
    # unverifiable group are still refused.

    @unittest.skipUnless(hasattr(os, "getuid"), "POSIX ancestor owner/mode rules")
    def test_g1_a_short_path_alias_of_home_is_exempt_from_the_settings_markers(self):
        """G1 (plan K53): `at_home` is an IDENTITY question and must see through the 8.3
        alias. CONTROL: with realpath left alone the short directory is a DIFFERENT
        directory holding a settings file, and it is still refused."""
        users = _mkdir_chain(self.tmp / "Users")
        long_home = _mkdir_chain(users / "runnerlong")
        short_home = _mkdir_chain(users / "RUNNER~1")
        for home in (long_home, short_home):
            _mkdir_chain(home / ".claude")
            (home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            _mkdir_chain(home / "run")
        os.environ["HOME"] = str(long_home)
        os.environ["USERPROFILE"] = str(long_home)
        os.environ["XDG_RUNTIME_DIR"] = str(short_home / "run")
        expected = str(long_home / "run" / vas.REVIEWER_CWD_NAME)

        with self.assertRaises(vas.ReviewerCwdError) as ctx:  # CONTROL: no alias
            vas.resolve_reviewer_cwd()
        self.assertIn("settings.json", str(ctx.exception))
        self.assertIn(str(short_home), str(ctx.exception))

        real_realpath = os.path.realpath
        short_s, long_s = str(short_home), str(long_home)

        def fake_realpath(path, *args, **kwargs):
            try:
                text = os.fspath(path)
            except TypeError:  # a file descriptor: never the path we are aliasing
                return real_realpath(path, *args, **kwargs)
            if isinstance(text, str) and (text == short_s or text.startswith(short_s + os.sep)):
                return real_realpath(long_s + text[len(short_s):], *args, **kwargs)
            return real_realpath(path, *args, **kwargs)

        os.path.realpath = fake_realpath
        try:
            self.assertEqual(vas.resolve_reviewer_cwd(), expected)
            # CONTROL: the exemption covers the two settings markers only.
            (short_home / "CLAUDE.md").write_text("steer", encoding="utf-8")
            with self.assertRaises(vas.ReviewerCwdError) as ctx:
                vas.resolve_reviewer_cwd()
            self.assertIn("CLAUDE.md", str(ctx.exception))
            (short_home / "CLAUDE.md").unlink()
            # A `.claude` at an ancestor below home is still refused through the RESOLVED
            # form alone — resolving the alias must not blind the below-home rule.
            (short_home / "run" / ".claude").mkdir()
            with self.assertRaises(vas.ReviewerCwdError) as ctx:
                vas.resolve_reviewer_cwd()
            self.assertIn("below home", str(ctx.exception))
        finally:
            os.path.realpath = real_realpath

    @unittest.skipUnless(hasattr(os, "getuid") and hasattr(os, "getgid"),
                         "POSIX ownership: Windows has no uid/gid or permission bits")
    def test_g2_a_private_group_group_writable_ancestor_is_accepted(self):
        """G2 (plan K54): a user-created `$HOME/run` on a umask-002 host is 0775 with the
        user's own PRIVATE single-member group, and F4 rule (b) refused it. CONTROLS: a
        MULTI-MEMBER group, 0777 world-write and an unresolvable group are all refused, and
        the reviewer directory's OWN mode rule is untouched."""
        if _grp is None:
            self.skipTest("grp is POSIX-only")
        runtime = _mkdir_chain(self.tmp / "runtime")
        os.environ["XDG_RUNTIME_DIR"] = str(runtime)
        expected = self._reviewer_dir()
        real_getgrgid = _grp.getgrgid
        self.addCleanup(setattr, _grp, "getgrgid", real_getgrgid)

        def group_with(members):
            def fake(gid):
                if isinstance(members, BaseException):
                    raise members
                return _grp.struct_group(("fake", "x", gid, list(members)))
            _grp.getgrgid = fake

        group_with([])
        os.chmod(runtime, 0o775)
        self.assertEqual(vas.resolve_reviewer_cwd(), expected)

        group_with(["someone-else"])  # CONTROL: a shared group is still refused
        with self.assertRaises(vas.ReviewerCwdError) as ctx:
            vas.resolve_reviewer_cwd()
        self.assertIn("sticky", str(ctx.exception))

        group_with(KeyError("no such group"))  # CONTROL: unverifiable -> fail closed
        with self.assertRaises(vas.ReviewerCwdError):
            vas.resolve_reviewer_cwd()

        group_with([])
        os.chmod(runtime, 0o777)  # CONTROL: world-write is unconditional
        with self.assertRaises(vas.ReviewerCwdError) as ctx:
            vas.resolve_reviewer_cwd()
        self.assertIn("sticky", str(ctx.exception))

        os.chmod(runtime, 0o700)
        os.chmod(Path(expected), 0o770)  # CONTROL: the dir's OWN rule is unchanged
        with self.assertRaises(vas.ReviewerCwdError) as ctx:
            vas.resolve_reviewer_cwd()
        self.assertIn("group/world-writable", str(ctx.exception))
        os.chmod(Path(expected), 0o700)

    def test_f8_the_filesystem_root_is_never_a_containment_root(self):
        """F8 (plan K39): with the caller's cwd at "/" every candidate used to be "inside the
        caller's cwd". CONTROL: the candidate's real parent still refuses."""
        runtime = self.tmp / "runtime"
        runtime.mkdir(mode=0o700)
        os.environ["XDG_RUNTIME_DIR"] = str(runtime)
        expected = self._reviewer_dir()
        self.assertFalse(vas._same_or_under(expected, os.sep))
        self.assertTrue(vas._same_or_under(expected, str(runtime)))

        previous = os.getcwd()
        try:
            os.chdir(os.sep)
            self.assertEqual(vas.resolve_reviewer_cwd(), expected)
            os.chdir(str(runtime))
            with self.assertRaises(vas.ReviewerCwdError) as ctx:
                vas.resolve_reviewer_cwd()
            self.assertIn("caller's cwd", str(ctx.exception))
        finally:
            os.chdir(previous)


class TestReviewerMemoryQuarantineF3(unittest.TestCase):
    """#282 fix round 1 F3 on THIS launcher (plan K2: the two copies are duplicated, so each
    guarantee is proven on both; the parity comparison lives in test_audit_spawn_defaults.py).

    FIXTURE HOMES ONLY: HOME and XDG_RUNTIME_DIR both point into a throwaway tmp dir, so the
    slug is a tmp-path slug and the host's real
    ~/.claude/projects/-run-user-1000-foundry-reviewer-cwd/ is never named, read or written.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vas-reviewer-memory-")
        self.tmp = Path(self._tmp.name).resolve()
        self._env = dict(os.environ)
        self.addCleanup(self._restore)
        home = _mkdir_chain(self.tmp / "home")
        for var in ("HOME", "USERPROFILE"):
            os.environ[var] = str(home)
        runtime = _mkdir_chain(self.tmp / "xdg-runtime")
        os.environ["XDG_RUNTIME_DIR"] = str(runtime)
        # #282 fix round 2 G3 (plan K55) makes CLAUDE_CONFIG_DIR load-bearing for the
        # auto-memory directory, so it is unset here for the same reason HOME is redirected:
        # a developer who exports it would otherwise have these tests reach into their real
        # config dir. A test that wants the relocated root sets it itself.
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.home = home

    def _restore(self):
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def _memory_dir(self) -> Path:
        """K40's rule restated independently of the implementation, for the fixture HOME."""
        reviewer = os.path.realpath(
            os.path.join(os.environ["XDG_RUNTIME_DIR"], vas.REVIEWER_CWD_NAME))
        slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(reviewer))
        return self.home / ".claude" / "projects" / slug / "memory"

    def _launch(self):
        """One arbiter launch against a stubbed subprocess: (parsed, err, calls, stderr)."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(kwargs["cwd"])
            return fake_completed_process(stdout=json.dumps({"verdict": "x"}))

        stderr = io.StringIO()
        with mock.patch.object(vas.subprocess, "run", side_effect=fake_run), \
                contextlib.redirect_stderr(stderr):
            parsed, err = vas.run_claude_arbiter("the prompt", 60)
        return parsed, err, calls, stderr.getvalue()

    def test_f3_a_seeded_memory_dir_is_quarantined_and_recorded_on_stderr_only(self):
        """F3 (plan K40): the entries are MOVED to memory.quarantine/<UTC stamp>/ before the
        launch, the launch PROCEEDS, and this launcher records ONE ASCII stderr line and
        nothing else — its stdout verdict is closed (K5), so there is no provenance key."""
        memory = _mkdir_chain(self._memory_dir())
        (memory / "MEMORY.md").write_text("a previous reviewer's notes", encoding="utf-8")
        (memory / "sub").mkdir(mode=0o700)

        parsed, err, calls, stderr = self._launch()
        self.assertIsNone(err)
        self.assertEqual(parsed, {"verdict": "x"})
        self.assertEqual(calls, [os.path.realpath(
            os.path.join(os.environ["XDG_RUNTIME_DIR"], vas.REVIEWER_CWD_NAME))])

        stamps = sorted((memory.parent / "memory.quarantine").iterdir())
        self.assertEqual(len(stamps), 1, stamps)
        self.assertEqual(sorted(p.name for p in stamps[0].iterdir()), ["MEMORY.md", "sub"])
        self.assertEqual((stamps[0] / "MEMORY.md").read_text(encoding="utf-8"),
                         "a previous reviewer's notes")
        # The memory directory itself is kept, left empty; nothing was deleted.
        self.assertTrue(memory.is_dir())
        self.assertEqual(sorted(memory.iterdir()), [])
        self.assertIn("2", stderr)
        self.assertIn("quarantin", stderr.lower())
        self.assertTrue(stderr.isascii(), stderr)

    def test_f3_an_empty_or_absent_memory_dir_moves_nothing_and_writes_no_line(self):
        """CONTROL: nothing to move -> no quarantine directory and no stderr line, so a
        missing line always means "nothing was moved", never "not checked"."""
        memory = self._memory_dir()
        quarantine = memory.parent / "memory.quarantine"

        self.assertFalse(memory.exists())
        _parsed, err, calls, stderr = self._launch()
        self.assertIsNone(err)
        self.assertEqual(len(calls), 1)
        self.assertFalse(quarantine.exists())
        self.assertNotIn("quarantin", stderr.lower())

        _mkdir_chain(memory)
        _parsed, err, calls, stderr = self._launch()
        self.assertIsNone(err)
        self.assertEqual(len(calls), 1)
        self.assertFalse(quarantine.exists())
        self.assertNotIn("quarantin", stderr.lower())

    def test_f3_a_move_failure_fails_closed_and_never_launches(self):
        """FAIL CLOSED (plan K40): an OSError while quarantining takes the existing
        `reviewer cwd unavailable: <reason>` path — the arbiter's exit 4 — with NO launch.
        Nothing is deleted: the entry that could not be moved is still there."""
        memory = _mkdir_chain(self._memory_dir())
        (memory / "MEMORY.md").write_text("notes", encoding="utf-8")

        def boom(_src, _dst):
            raise OSError(13, "Permission denied")

        with mock.patch.object(os, "replace", side_effect=boom):
            parsed, err, calls, _stderr = self._launch()
        self.assertIsNone(parsed)
        self.assertTrue(err.startswith("reviewer cwd unavailable: "), err)
        self.assertIn("MEMORY.md", err)
        self.assertEqual(calls, [])
        self.assertEqual((memory / "MEMORY.md").read_text(encoding="utf-8"), "notes")

    def test_f3_a_memory_path_that_is_not_a_real_directory_fails_closed(self):
        """FAIL CLOSED (plan K40): a `memory` that exists and is not a real directory cannot
        be emptied, so the arbiter refuses instead of launching over it. A symlink counts
        even when it points at a real directory."""
        memory = self._memory_dir()
        _mkdir_chain(memory.parent)
        target = memory.parent / "elsewhere"
        target.mkdir(mode=0o700)
        try:
            memory.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")

        parsed, err, calls, _stderr = self._launch()
        self.assertIsNone(parsed)
        self.assertEqual(calls, [])
        self.assertIn("not a real directory", err)

    # -- #282 fix round 2 G3 / G4 on THIS launcher (plan K55 / K56, K2 duplication) --

    def test_g3_a_relocated_claude_config_dir_is_the_quarantine_root(self):
        """G3 (plan K55): CLAUDE_CONFIG_DIR names the `.claude` directory ITSELF, so the
        quarantine target is `<root>/projects/<slug>/memory`. The pre-fix helper built from
        Path.home() alone, so under a relocated root it named a directory that did not exist,
        _quarantine_reviewer_memory returned 0 and the arbiter launched over the memory claude
        would really read — a 0 that meant "not checked" rather than "nothing was moved"."""
        config = _mkdir_chain(self.tmp / "relocated-claude")
        os.environ["CLAUDE_CONFIG_DIR"] = str(config)
        reviewer = os.path.realpath(
            os.path.join(os.environ["XDG_RUNTIME_DIR"], vas.REVIEWER_CWD_NAME))
        slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(reviewer))
        relocated = config / "projects" / slug / "memory"
        self.assertEqual(vas._reviewer_memory_dir(reviewer), str(relocated))

        _mkdir_chain(relocated)
        (relocated / "MEMORY.md").write_text("a previous reviewer's notes", encoding="utf-8")
        home_path = self._memory_dir()
        _mkdir_chain(home_path)
        (home_path / "MEMORY.md").write_text("not the reviewer's memory", encoding="utf-8")

        parsed, err, calls, stderr = self._launch()
        self.assertIsNone(err)
        self.assertEqual(parsed, {"verdict": "x"})
        self.assertEqual(calls, [reviewer])
        stamps = sorted((relocated.parent / "memory.quarantine").iterdir())
        self.assertEqual(len(stamps), 1, stamps)
        self.assertEqual((stamps[0] / "MEMORY.md").read_text(encoding="utf-8"),
                         "a previous reviewer's notes")
        self.assertIn("quarantin", stderr.lower())
        # The ~/.claude path is left ALONE: the fix moves where the check looks, it does
        # not widen it to two places.
        self.assertEqual((home_path / "MEMORY.md").read_text(encoding="utf-8"),
                         "not the reviewer's memory")
        self.assertFalse((home_path.parent / "memory.quarantine").exists())

    def test_g3_control_unset_or_empty_keeps_the_home_path_and_no_home_still_fails(self):
        """CONTROL for G3: UNSET keeps today's `~/.claude/projects/<slug>/memory`, an EMPTY
        value is treated as unset rather than as the filesystem root, and an undeterminable
        home with the variable unset is still a quarantine FAILURE — K55 widens WHERE the
        directory is, never WHETHER the check happens."""
        reviewer = os.path.realpath(
            os.path.join(os.environ["XDG_RUNTIME_DIR"], vas.REVIEWER_CWD_NAME))
        expected = str(self._memory_dir())
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.assertEqual(vas._reviewer_memory_dir(reviewer), expected)
        os.environ["CLAUDE_CONFIG_DIR"] = ""
        self.assertEqual(vas._reviewer_memory_dir(reviewer), expected)

        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        with mock.patch.object(vas.Path, "home", side_effect=RuntimeError("no home")):
            with self.assertRaises(vas.ReviewerCwdError) as exc:
                vas._reviewer_memory_dir(reviewer)
        self.assertIn("home directory", str(exc.exception))

    def test_g4_the_arbiter_passes_no_variant_but_carries_the_signature(self):
        """G4 (plan K56, K2): the arbiter has NO substitute, so it never passes a variant and
        its resolved directory is unchanged — but it carries the identical keyword-only
        parameter, so the duplicated helpers stay byte-comparable and the parity test in
        test_audit_spawn_defaults.py stays meaningful. The variant directory it CAN resolve
        goes through the same body and gets its own slug and memory dir."""
        plain = vas.resolve_reviewer_cwd()
        self.assertEqual(plain, os.path.realpath(
            os.path.join(os.environ["XDG_RUNTIME_DIR"], vas.REVIEWER_CWD_NAME)))
        source = Path(vas.__file__).read_text(encoding="utf-8")
        self.assertNotIn('variant="substitute"', source)

        substitute = vas.resolve_reviewer_cwd(variant="substitute")
        self.assertNotEqual(substitute, plain)
        self.assertEqual(os.path.basename(substitute), vas.REVIEWER_CWD_NAME + "-substitute")
        self.assertNotEqual(vas._reviewer_memory_dir(substitute),
                            vas._reviewer_memory_dir(plain))
        # Not a bypass: the same safety rules refuse the variant directory.
        (Path(substitute) / "CLAUDE.md").write_text("project instructions", encoding="utf-8")
        with self.assertRaises(vas.ReviewerCwdError) as exc:
            vas.resolve_reviewer_cwd(variant="substitute")
        self.assertIn("CLAUDE.md", str(exc.exception))
        self.assertEqual(vas.resolve_reviewer_cwd(), plain)   # CONTROL: the arm is unaffected


class TestD24WatchdogAdoptionIsAuditSpawnOnly(unittest.TestCase):
    """S081 revision 4, WP-A03 — THE ASYMMETRY, WRITTEN DOWN AS A CHECK.

    The WP-A03 plan text says the D24 watchdog is adopted at "the codex arm of
    audit_spawn, the same block in verification_arbiter_spawn (byte-identical, K2)",
    and asks for a parity test proving both launchers carry the identical adoption.

    THAT PREMISE IS FALSE, AND THIS TEST IS WHY IT STAYS FALSE VISIBLY RATHER THAN
    BEING QUIETLY ASSUMED. `verification_arbiter_spawn` HAS NO CODEX ARM AT ALL: it
    is a single cold-context CLAUDE arbiter, and its only `subprocess.run` (the line
    the plan names) is that Claude call. There is therefore no codex call site here
    to adopt the watchdog at, and the honest parity statement is the NEGATIVE one.

    What IS shared between the launchers (the real K2 idiom) is the CLAUDE arm, and
    that arm is deliberately untouched by D24: the watchdog is a codex/agy mechanism
    (its `mode` admits no other), and the Claude pins' timeouts did not move.

    A future stage that adds a codex arm to this launcher will fail this test, which
    is the intent: at that moment the adoption must be carried across too.
    """

    _CODEX_CALL_MARKERS = ("codex exec", "CODEX_PIN", "CODEX_TIMEOUT_S", "_codex_attempt")

    def _source(self, module):
        return Path(module.__file__).read_text(encoding="utf-8")

    def test_the_arbiter_has_no_codex_call_site(self):
        source = self._source(vas)
        for marker in self._CODEX_CALL_MARKERS:
            self.assertNotIn(marker, source, marker)
        # POSITIVE CONTROL: every one of those markers is present in the launcher that
        # DOES have a codex arm -- so this test cannot pass by looking for nothing.
        audit_source = self._source(_audit_spawn_module())
        for marker in self._CODEX_CALL_MARKERS:
            self.assertIn(marker, audit_source, marker)

    def test_the_arbiter_does_not_import_the_watchdog(self):
        """Nothing to watch -> nothing imported. Stated as a check so that adding the
        import without a call site (or a call site without the import) is caught."""
        self.assertFalse(hasattr(vas, "codex_watch"))
        self.assertTrue(hasattr(_audit_spawn_module(), "codex_watch"))

    def test_the_shared_claude_arm_is_still_byte_identical(self):
        """K2 for the block the launchers REALLY duplicate. D24 left it alone, and this
        is what would catch an adoption accidentally applied to the Claude arm here."""
        # #291 fix round 1 (B, C): both arms now also carry the prompt on stdin as UTF-8, so
        # the shared block includes the encoding pair and the stdin transport.
        needle = ('        proc = subprocess.run(\n            cmd,\n'
                  '            capture_output=True,\n            text=True,\n')
        tail = ('            encoding="utf-8",\n            errors="replace",\n'
                '            timeout=timeout_s,')
        for mod in (vas, _audit_spawn_module()):
            src = self._source(mod)
            start = src.index(needle, src.index("def run_claude_"))
            block = src[start:src.index("\n        )\n", start)]
            self.assertIn(tail, block)
            self.assertIn("            input=prompt,", block)
            self.assertNotIn("stdin=", block)
        self.assertIn(needle, self._source(vas))
        self.assertIn(needle, self._source(_audit_spawn_module()))


def _audit_spawn_module():
    """audit_spawn imported for a SOURCE comparison only.

    Imported lazily and under a throwaway HOME: audit_spawn resolves both seat pins at
    import time, and this module must not make that read against the developer's real
    home just to compare two files.
    """
    if "audit_spawn" in sys.modules:
        return sys.modules["audit_spawn"]
    saved = {var: os.environ.get(var) for var in ("HOME", "USERPROFILE")}
    home = tempfile.mkdtemp(prefix="vas-audit-import-home-")
    try:
        for var in saved:
            os.environ[var] = home
        import audit_spawn  # noqa: E402
        return audit_spawn
    finally:
        for var, value in saved.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
