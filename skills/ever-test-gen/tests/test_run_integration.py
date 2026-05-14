"""Integration tests for run.py — full ever-test-gen pipeline."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import run  # noqa: E402


def _seed_project(tmp_path: Path) -> dict:
    """Create minimal project with intent-map, plan, api_delta, drift-report."""
    intent_map = {
        "components": [
            {
                "component_id": "auth",
                "function_class": "auth",
                "test_seeds": [
                    {"seed_id": "S-001", "scenario": "valid",
                     "given": "g", "when": "POST", "then": "200"},
                ],
            },
        ],
    }
    (tmp_path / "intent.yaml").write_text(yaml.safe_dump(intent_map))
    (tmp_path / "plan.yaml").write_text(yaml.safe_dump({
        "work_packages": [{"id": "WP-1", "component": "auth"}],
    }))
    (tmp_path / "api-delta.json").write_text(json.dumps({
        "package": "pandas",
        "old_version": "1.5.3",
        "new_version": "2.2.3",
        "breaking_lines": ["Series.append removed"],
        "affected_components": [{"name": "auth", "call_sites": 3}],
    }))
    (tmp_path / "drift-report.yaml").write_text(yaml.safe_dump({
        "findings": [
            {"kind": "cve", "cve_id": "CVE-2026-1111", "package": "pillow",
             "fix_category": "direct-fix-available",
             "fix_path": "bump >= 12.1.4"},
        ],
    }))
    return {
        "intent": tmp_path / "intent.yaml",
        "plan": tmp_path / "plan.yaml",
        "api_delta": tmp_path / "api-delta.json",
        "drift": tmp_path / "drift-report.yaml",
    }


def test_run_version_upgrade_emits_regression_and_migration(tmp_path: Path) -> None:
    paths = _seed_project(tmp_path)
    argv = [
        "--project-root", str(tmp_path),
        "--run-id", "run-1",
        "--claim-uuid", "00000000-0000-0000-0000-000000000001",
        "--plan-path", str(paths["plan"]),
        "--intent-map-path", str(paths["intent"]),
        "--api-delta-path", str(paths["api_delta"]),
        "--mode", "version-upgrade",
        "--language-target", "python",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    assert rc == 0
    tests = list((tmp_path / "tests").glob("*.py"))
    # 1 regression + 1 migration
    assert len(tests) == 2
    names = {p.name for p in tests}
    assert any("regression" in n for n in names)
    assert any("migration" in n for n in names)


def test_run_cve_fix_emits_regression_and_cve_proof(tmp_path: Path) -> None:
    paths = _seed_project(tmp_path)
    argv = [
        "--project-root", str(tmp_path),
        "--run-id", "run-1",
        "--claim-uuid", "00000000-0000-0000-0000-000000000001",
        "--plan-path", str(paths["plan"]),
        "--intent-map-path", str(paths["intent"]),
        "--drift-report-path", str(paths["drift"]),
        "--mode", "cve-fix",
        "--language-target", "python",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    assert rc == 0
    tests = list((tmp_path / "tests").glob("*.py"))
    # 1 regression + 1 CVE proof
    assert len(tests) == 2
    names = {p.name for p in tests}
    assert any("regression" in n for n in names)
    assert any("cve_2026_1111__proof" in n for n in names)


def test_run_emits_transition_request(tmp_path: Path) -> None:
    paths = _seed_project(tmp_path)
    argv = [
        "--project-root", str(tmp_path),
        "--run-id", "run-1",
        "--claim-uuid", "ABC-claim",
        "--plan-path", str(paths["plan"]),
        "--intent-map-path", str(paths["intent"]),
        "--mode", "version-upgrade",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    assert rc == 0
    reqs = list((tmp_path / ".ledger" / "requests").glob("*.request.yaml"))
    assert len(reqs) == 1
    req = yaml.safe_load(reqs[0].read_text())
    assert req["produced_by"] == "ever-test-gen"
    assert req["target_stage"] == "TESTED"
    assert req["claim_uuid"] == "ABC-claim"


def test_run_collision_with_user_test_refused(tmp_path: Path) -> None:
    """If a non-evo test exists at the proposed filename, refuse with exit 2."""
    paths = _seed_project(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    # Pre-existing user test at the EXACT filename evo would produce
    (tests_dir / "test_evo_version-upgrade_auth__s_001__regression.py").write_text(
        "# user-written test, no evo header\ndef test_x(): pass\n"
    )
    argv = [
        "--project-root", str(tmp_path),
        "--run-id", "run-1",
        "--claim-uuid", "x",
        "--plan-path", str(paths["plan"]),
        "--intent-map-path", str(paths["intent"]),
        "--mode", "version-upgrade",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    assert rc == 2


def test_run_evo_owned_file_overwritten(tmp_path: Path) -> None:
    """Existing evo-generated file (regen scenario) is overwritten, not refused."""
    paths = _seed_project(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    # Pre-existing test with evo header (e.g. previous run)
    pre = ('"""\nEVO-generated test — CONFIDENCE: characterization-aid\n'
           'Requires user review before being relied on.\n"""\n'
           'def test_old(): pass\n')
    (tests_dir / "test_evo_version-upgrade_auth__s_001__regression.py").write_text(pre)
    argv = [
        "--project-root", str(tmp_path),
        "--run-id", "run-1",
        "--claim-uuid", "x",
        "--plan-path", str(paths["plan"]),
        "--intent-map-path", str(paths["intent"]),
        "--mode", "version-upgrade",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    assert rc == 0


def test_run_missing_project_root_returns_3(tmp_path: Path) -> None:
    paths = _seed_project(tmp_path)
    argv = [
        "--project-root", "/no/such/dir",
        "--run-id", "x",
        "--claim-uuid", "x",
        "--plan-path", str(paths["plan"]),
        "--intent-map-path", str(paths["intent"]),
        "--mode", "version-upgrade",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    assert rc == 3


def test_run_missing_intent_map_returns_3(tmp_path: Path) -> None:
    (tmp_path / "plan.yaml").write_text("x: y\n")
    argv = [
        "--project-root", str(tmp_path),
        "--run-id", "x",
        "--claim-uuid", "x",
        "--plan-path", str(tmp_path / "plan.yaml"),
        "--intent-map-path", str(tmp_path / "missing.yaml"),
        "--mode", "version-upgrade",
        "--no-heartbeat",
    ]
    rc = run.main(argv)
    assert rc == 3
