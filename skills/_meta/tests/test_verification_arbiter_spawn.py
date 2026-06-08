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

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

# Add skills/_meta to path
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import verification_arbiter_spawn as vas  # noqa: E402
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

    def test_default_timeout_180s(self):
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
            self.assertEqual(captured["timeout_s"], 180)

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


if __name__ == "__main__":
    unittest.main()
