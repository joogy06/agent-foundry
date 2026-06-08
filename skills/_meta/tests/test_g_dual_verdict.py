#!/usr/bin/env python3
"""test_g_dual_verdict.py — S044 / #118 G_DUAL_VERDICT gate coverage.

Covers the read-only pre-flight gate over claims.assert_verified_preconditions
(design §10 final scope item 4 + A7):

    - both arms present + passing -> exit 0
    - missing/unversioned/REJECTED/AUDIT_UNAVAILABLE archive -> exit 2
      (gate_false_block observation, fingerprint 'dual-verdict-precondition')
    - missing --bundle-hash / missing project_root -> exit 3 (env)
    - telemetry byte-invariance: exit codes identical with vs without the
      S039 gate-run telemetry backend (GATES_TELEMETRY_FORCE_IMPORTERROR=1)

Run:
    pytest ~/.claude/skills/_meta/tests/test_g_dual_verdict.py -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

_META_DIR = Path(__file__).resolve().parent.parent
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

import yaml  # noqa: E402

_GATES = _META_DIR / "gates.py"


def _run_gate(
    project_root: Path,
    bundle_hash: Optional[str],
    *,
    force_no_telemetry: bool = False,
) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(_GATES), "G_DUAL_VERDICT", str(project_root)]
    if bundle_hash is not None:
        argv += ["--bundle-hash", bundle_hash]
    env = dict(os.environ)
    if force_no_telemetry:
        env["GATES_TELEMETRY_FORCE_IMPORTERROR"] = "1"
    else:
        env.pop("GATES_TELEMETRY_FORCE_IMPORTERROR", None)
    return subprocess.run(argv, capture_output=True, text=True, env=env)


def _write_archive(root: Path, bundle_hash: str, **overrides: Any) -> None:
    vdir = root / ".ledger" / "verdicts"
    vdir.mkdir(parents=True, exist_ok=True)
    arch: Dict[str, Any] = {
        "schema_version": "dual-verdict.v1",
        "component_id": "foo",
        "bundle_hash": bundle_hash,
        "verification_request_id": "vr-1",
        "prior_state_version": "sv-1",
        "generation": 0,
        "audit_arm": {"result": "VERIFIED"},
        "arbiter_arm": {"verdict": "VERIFIED"},
    }
    arch.update(overrides)
    (vdir / f"{bundle_hash}.verdict.yaml").write_text(yaml.safe_dump(arch))


def _bh(seed: str = "a") -> str:
    return (seed * 64)[:64]


# S048 / #116: G_DUAL_VERDICT delegates to R6, which now ALSO requires a GREEN
# deterministic bundle. The pass-path test must write a real hash-addressed
# GREEN bundle. Fail-path tests (missing archive / REJECTED / AUDIT_UNAVAILABLE /
# unversioned) fail at the LLM-arm checks before the deterministic step, so they
# keep using cheap _bh() fakes.
import json as _json  # noqa: E402

import trusted_runner as _tr  # noqa: E402
import deterministic_arm as _da  # noqa: E402


def _write_green_bundle(root: Path, component_id: str = "foo") -> str:
    bundle = {
        "component_id": component_id,
        "produced_by": "bob-trusted-runner",
        "runner_info": {"runner": "pytest", "version": "test"},
        "run_at": "2026-06-08T00:00:00Z",
        "test_paths": ["t.py"],
        "results": [{"path": "t.py", "returncode": 0,
                     "summary": {"total": 1, "passed": 1, "failed": 0,
                                 "error": 0, "skipped": 0, "duration_s": 0.0},
                     "failed_tests": [],
                     "tests": [{"nodeid": "t::a", "outcome": "passed",
                                "duration_s": 0.0, "keywords": []}]}],
    }
    bh = _tr.bundle_hash_hex(bundle)
    bundle["bundle_hash"] = bh
    p = _da.bundle_path_for(component_id, bh, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(bundle), encoding="utf-8")
    return bh


class TestGDualVerdictGate(unittest.TestCase):
    def test_both_pass_exit_zero(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="gdv-"))
        bh = _write_green_bundle(root, "foo")  # S048: GREEN bundle required
        _write_archive(root, bh)
        cp = _run_gate(root, bh)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("G_DUAL_VERDICT_PASS", cp.stdout)

    def test_missing_archive_exit_two(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="gdv-"))
        (root / ".ledger" / "verdicts").mkdir(parents=True)
        cp = _run_gate(root, _bh("z"))
        self.assertEqual(cp.returncode, 2, cp.stdout + cp.stderr)
        self.assertIn("G_DUAL_VERDICT_FAIL", cp.stderr)

    def test_audit_rejected_exit_two(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="gdv-"))
        bh = _bh("d")
        _write_archive(root, bh, audit_arm={"result": "REJECTED"})
        cp = _run_gate(root, bh)
        self.assertEqual(cp.returncode, 2, cp.stdout + cp.stderr)

    def test_audit_unavailable_exit_two(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="gdv-"))
        bh = _bh("c")
        _write_archive(root, bh, arbiter_arm={"verdict": "AUDIT_UNAVAILABLE"})
        cp = _run_gate(root, bh)
        self.assertEqual(cp.returncode, 2, cp.stdout + cp.stderr)

    def test_unversioned_exit_two(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="gdv-"))
        bh = _bh("e")
        _write_archive(root, bh)
        p = root / ".ledger" / "verdicts" / f"{bh}.verdict.yaml"
        d = yaml.safe_load(p.read_text())
        del d["schema_version"]
        p.write_text(yaml.safe_dump(d))
        cp = _run_gate(root, bh)
        self.assertEqual(cp.returncode, 2, cp.stdout + cp.stderr)

    def test_no_bundle_hash_exit_three(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="gdv-"))
        cp = _run_gate(root, None)
        self.assertEqual(cp.returncode, 3, cp.stdout + cp.stderr)
        self.assertIn("ENV_ERROR", cp.stderr)

    def test_red_bundle_with_passing_llms_is_correlated_error(self) -> None:
        """S048 / #116: a RED on-disk bundle + BOTH LLM arms VERIFIED -> exit 2,
        and the gate flags it as a CORRELATED-LLM-ERROR (the caught false-pass)."""
        root = Path(tempfile.mkdtemp(prefix="gdv-"))
        # Write a RED bundle (failing test) at a real hash.
        bundle = {
            "component_id": "foo", "produced_by": "bob-trusted-runner",
            "runner_info": {"runner": "pytest", "version": "t"},
            "run_at": "x", "test_paths": ["t.py"],
            "results": [{"path": "t.py", "returncode": 1,
                         "summary": {"total": 1, "passed": 0, "failed": 1,
                                     "error": 0, "skipped": 0, "duration_s": 0.0},
                         "failed_tests": [{"nodeid": "t::a", "outcome": "failed"}],
                         "tests": [{"nodeid": "t::a", "outcome": "failed",
                                    "duration_s": 0.0, "keywords": []}]}],
        }
        bh = _tr.bundle_hash_hex(bundle)
        bundle["bundle_hash"] = bh
        p = _da.bundle_path_for("foo", bh, root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_json.dumps(bundle), encoding="utf-8")
        _write_archive(root, bh)  # both LLM arms VERIFIED
        cp = _run_gate(root, bh)
        self.assertEqual(cp.returncode, 2, cp.stdout + cp.stderr)
        self.assertIn("CORRELATED-LLM-ERROR", cp.stderr)

    def test_telemetry_byte_invariance(self) -> None:
        """Exit codes MUST be byte-identical with vs without the S039 gate-run
        telemetry backend (the HARD ship-gate from design §6 / A8)."""
        root = Path(tempfile.mkdtemp(prefix="gdv-"))
        bh_pass = _write_green_bundle(root, "foo")  # S048: GREEN bundle required
        _write_archive(root, bh_pass)
        bh_fail = _bh("z")  # no archive

        scenarios: List[Optional[str]] = [bh_pass, bh_fail, None]
        for bh in scenarios:
            with self.subTest(bundle_hash=bh):
                on = _run_gate(root, bh, force_no_telemetry=False)
                off = _run_gate(root, bh, force_no_telemetry=True)
                self.assertEqual(
                    on.returncode, off.returncode,
                    f"exit code drift with vs without telemetry for "
                    f"bundle_hash={bh}: on={on.returncode} off={off.returncode}",
                )


if __name__ == "__main__":
    unittest.main()
