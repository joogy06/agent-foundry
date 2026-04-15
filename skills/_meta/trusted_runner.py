#!/usr/bin/env python3
"""
trusted_runner.py — Bob's trusted test execution runner.

Implements run_trusted_test_suite per spec section 11.2. The CB3 fix lives here:
skills GENERATE test files, bob's trusted runner EXECUTES them in an isolated
subprocess with sanitized environment, parses the structured JSON report, and
produces a sanitized audit bundle tagged `produced_by: bob-trusted-runner`.

The metacognitive audit (audit_spawn.py) consumes ONLY bob-produced bundles —
never raw skill output. This closes the prompt-injection-via-stdout hole.

Public API:
    run_trusted_test_suite(component_id, test_paths, runner='pytest') -> dict

CLI:
    python -m trusted_runner <component_id> <test_path> [<test_path> ...] [--runner pytest|jest]
    Output: bundle JSON to stdout. Exit 0 if all tests pass, 2 otherwise.

Provenance: spec section 11.2. Critical invariants enforced: CB3.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT_SECONDS = 300
SANITIZED_ENV_KEYS = (
    "PATH", "HOME", "LANG", "LC_ALL", "USER", "SHELL", "TMPDIR", "TERM",
    "PYTHONPATH", "VIRTUAL_ENV", "NODE_PATH", "PYTEST_CURRENT_TEST",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitized_env() -> Dict[str, str]:
    """Return a minimal env preserving only the keys needed for test runners."""
    return {k: os.environ[k] for k in SANITIZED_ENV_KEYS if k in os.environ}


def runner_info(runner: str) -> Dict[str, str]:
    """Capture the runner version for audit bundle provenance."""
    info = {"runner": runner}
    try:
        if runner == "pytest":
            result = subprocess.run(
                ["pytest", "--version"], capture_output=True, text=True, timeout=10, check=False
            )
            info["version"] = (result.stdout or result.stderr).strip().split("\n")[0]
        elif runner == "jest":
            result = subprocess.run(
                ["jest", "--version"], capture_output=True, text=True, timeout=10, check=False
            )
            info["version"] = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        info["version"] = "unknown"
    return info


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# pytest runner
# ---------------------------------------------------------------------------


def _run_pytest(
    test_path: Path, timeout: int
) -> Dict[str, Any]:
    """Run a single pytest target and return a sanitized result.

    The CB3 fix: we discard raw stdout/stderr after parsing the JSON report.
    The auditor never sees free-form text that could carry prompt injection.
    """
    cmd = [
        "pytest",
        "--tb=short",
        "-q",
        "--disable-warnings",
        # JSON report goes to stdout via --json-report-file=- if pytest-json-report
        # is installed; otherwise we fall back to parsing the exit code.
        str(test_path),
    ]
    # Try with the JSON reporter first; fall back if not installed
    json_cmd = cmd[:1] + ["--json-report", "--json-report-file=/dev/stdout"] + cmd[1:]
    try:
        result = subprocess.run(
            json_cmd,
            env=sanitized_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        # Try to parse JSON report from stdout.
        # pytest-json-report writes its JSON to /dev/stdout, which lands on the
        # same line as pytest's progress bar (e.g. "..... [100%]{...json...}").
        # Strategy: scan the full stdout for the first "{", then find a balanced
        # top-level object via brace counting (skipping braces inside strings).
        report: Dict[str, Any] = {}
        stdout_text = result.stdout or ""
        first_brace = stdout_text.find("{")
        if first_brace >= 0:
            depth = 0
            in_str = False
            esc = False
            end_idx = -1
            for i in range(first_brace, len(stdout_text)):
                ch = stdout_text[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end_idx = i
                        break
            if end_idx > first_brace:
                candidate = stdout_text[first_brace : end_idx + 1]
                try:
                    report = json.loads(candidate)
                except json.JSONDecodeError:
                    report = {}
        if not report:
            # Fallback: run plain pytest, infer from returncode
            plain = subprocess.run(
                cmd, env=sanitized_env(), capture_output=True, text=True,
                timeout=timeout, check=False,
            )
            return _result_from_returncode(test_path, plain.returncode)
        summary = report.get("summary") or {}
        tests = report.get("tests") or []
        # RT1 fix: emit per-test granularity from pytest-json-report's tests[]
        # instead of discarding it. Auditors need nodeid/outcome/duration to
        # tie specific passing tests to specific success_criteria. CB3 compliance
        # preserved — no raw stdout/stderr/tracebacks, only structured fields.
        per_test: List[Dict[str, Any]] = []
        for t in tests:
            # Best-effort duration: pytest-json-report records per-phase
            # durations under t["call"]["duration"] (+ setup/teardown). Sum
            # the three phases if present; fall back to top-level "duration".
            duration_s = 0.0
            for phase in ("setup", "call", "teardown"):
                phase_obj = t.get(phase)
                if isinstance(phase_obj, dict):
                    try:
                        duration_s += float(phase_obj.get("duration", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        pass
            if duration_s == 0.0:
                try:
                    duration_s = float(t.get("duration", 0.0) or 0.0)
                except (TypeError, ValueError):
                    duration_s = 0.0
            keywords = t.get("keywords") or []
            # keywords may be a dict (older plugin versions) — coerce to list of keys
            if isinstance(keywords, dict):
                keywords = sorted(keywords.keys())
            per_test.append({
                "nodeid": t.get("nodeid", "?"),
                "outcome": t.get("outcome", "?"),
                "duration_s": round(duration_s, 6),
                "keywords": list(keywords),
            })
        # Backward-compat: keep failed_tests[] exactly as before.
        failed_tests = [
            {"nodeid": t.get("nodeid", "?"), "outcome": t.get("outcome", "?")}
            for t in tests
            if t.get("outcome") in ("failed", "error")
        ]
        return {
            "path": str(test_path),
            "returncode": result.returncode,
            "summary": {
                "total": int(summary.get("total", 0)),
                "passed": int(summary.get("passed", 0)),
                "failed": int(summary.get("failed", 0)),
                "skipped": int(summary.get("skipped", 0)),
                "error": int(summary.get("error", 0)),
                "duration_s": float(report.get("duration", 0.0)),
            },
            "tests": per_test,
            "failed_tests": failed_tests,
        }
    except subprocess.TimeoutExpired:
        return {
            "path": str(test_path),
            "returncode": -1,
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 1, "duration_s": float(timeout)},
            "failed_tests": [{"nodeid": str(test_path), "outcome": "timeout"}],
        }
    except FileNotFoundError:
        return {
            "path": str(test_path),
            "returncode": -2,
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 1, "duration_s": 0.0},
            "failed_tests": [{"nodeid": str(test_path), "outcome": "runner_not_found"}],
        }


def _result_from_returncode(test_path: Path, rc: int) -> Dict[str, Any]:
    """Coarse fallback when JSON report is unavailable."""
    return {
        "path": str(test_path),
        "returncode": rc,
        "summary": {
            "total": 1 if rc == 0 else 1,
            "passed": 1 if rc == 0 else 0,
            "failed": 0 if rc == 0 else 1,
            "skipped": 0,
            "error": 0,
            "duration_s": 0.0,
        },
        "failed_tests": [] if rc == 0 else [{"nodeid": str(test_path), "outcome": "failed"}],
    }


# ---------------------------------------------------------------------------
# jest runner
# ---------------------------------------------------------------------------


def _run_jest(test_path: Path, timeout: int) -> Dict[str, Any]:
    cmd = ["jest", "--json", "--silent", str(test_path)]
    try:
        result = subprocess.run(
            cmd,
            env=sanitized_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            report = {}
        num_total = report.get("numTotalTests", 0)
        num_passed = report.get("numPassedTests", 0)
        num_failed = report.get("numFailedTests", 0)
        num_skipped = report.get("numPendingTests", 0)
        failed_tests: List[Dict[str, str]] = []
        for tr in report.get("testResults") or []:
            for assertion in tr.get("assertionResults") or []:
                if assertion.get("status") == "failed":
                    failed_tests.append({
                        "nodeid": assertion.get("fullName", "?"),
                        "outcome": "failed",
                    })
        return {
            "path": str(test_path),
            "returncode": result.returncode,
            "summary": {
                "total": int(num_total),
                "passed": int(num_passed),
                "failed": int(num_failed),
                "skipped": int(num_skipped),
                "error": 0,
                "duration_s": 0.0,
            },
            "failed_tests": failed_tests,
        }
    except subprocess.TimeoutExpired:
        return {
            "path": str(test_path),
            "returncode": -1,
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 1, "duration_s": float(timeout)},
            "failed_tests": [{"nodeid": str(test_path), "outcome": "timeout"}],
        }
    except FileNotFoundError:
        return {
            "path": str(test_path),
            "returncode": -2,
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 1, "duration_s": 0.0},
            "failed_tests": [{"nodeid": str(test_path), "outcome": "runner_not_found"}],
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_trusted_test_suite(
    component_id: str,
    test_paths: List[Path],
    runner: str = "pytest",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Bob runs the test runner directly. Skills NEVER call this.

    Returns a sanitized audit bundle tagged `produced_by: bob-trusted-runner`.
    The bundle is what audit_spawn.py consumes — never raw skill stdout.
    """
    bundle: Dict[str, Any] = {
        "component_id": component_id,
        "produced_by": "bob-trusted-runner",
        "runner_info": runner_info(runner),
        "run_at": now_iso(),
        "test_paths": [str(p) for p in test_paths],
        "results": [],
    }
    for test_path in test_paths:
        if runner == "pytest":
            res = _run_pytest(Path(test_path), timeout=timeout)
        elif runner == "jest":
            res = _run_jest(Path(test_path), timeout=timeout)
        else:
            res = {
                "path": str(test_path),
                "returncode": -3,
                "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 1, "duration_s": 0.0},
                "failed_tests": [{"nodeid": "?", "outcome": f"unknown_runner:{runner}"}],
            }
        bundle["results"].append(res)
    bundle["bundle_hash"] = sha256_hex(canonical_json(bundle))
    return bundle


def all_passed(bundle: Dict[str, Any]) -> bool:
    """Convenience: True iff every result has 0 failed and 0 error and returncode 0."""
    for r in bundle.get("results", []):
        if r.get("returncode", -1) != 0:
            return False
        s = r.get("summary") or {}
        if s.get("failed", 0) != 0 or s.get("error", 0) != 0:
            return False
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv
    if len(argv) < 3:
        sys.stderr.write("usage: trusted_runner.py <component_id> <test_path> [<test_path> ...] [--runner pytest|jest]\n")
        sys.exit(3)
    component_id = argv[1]
    runner = "pytest"
    test_paths: List[str] = []
    i = 2
    while i < len(argv):
        if argv[i] == "--runner":
            runner = argv[i + 1]
            i += 2
        else:
            test_paths.append(argv[i])
            i += 1
    bundle = run_trusted_test_suite(component_id, [Path(p) for p in test_paths], runner=runner)
    sys.stdout.write(json.dumps(bundle, indent=2) + "\n")
    sys.exit(0 if all_passed(bundle) else 2)


if __name__ == "__main__":
    main()
