"""Unit tests for regression_replay, migration_confirm, cve_proof emitters."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import regression_replay  # noqa: E402
import migration_confirm  # noqa: E402
import cve_proof  # noqa: E402


def _sample_intent() -> dict:
    return {
        "component_id": "auth",
        "test_seeds": [
            {"seed_id": "S-001", "scenario": "valid token", "given": "g",
             "when": "POST /verify", "then": "200 + user_identity"},
            {"seed_id": "S-002", "scenario": "expired token", "given": "g2",
             "when": "POST /verify", "then": "401"},
        ],
    }


def _sample_api_delta() -> dict:
    return {
        "package": "pandas",
        "old_version": "1.5.3",
        "new_version": "2.2.3",
        "breaking_lines": ["Series.append removed", "rename ax kw"],
        "affected_components": [{"name": "auth", "call_sites": 4}],
    }


def _sample_cve_findings() -> list:
    return [
        {"kind": "cve", "cve_id": "CVE-2026-1111", "package": "pillow",
         "fix_category": "direct-fix-available", "fix_path": "bump ≥ 12.1.4"},
        {"kind": "cve", "cve_id": "CVE-2026-2222", "package": "x",
         "fix_category": "no-known-fix"},
        {"kind": "version_lag", "package": "y"},  # Wrong kind, should be skipped
    ]


# ---- regression_replay ----

def test_regression_pytest_emits_one_per_seed() -> None:
    out = regression_replay.emit_pytest("auth", _sample_intent())
    assert len(out) == 2
    assert all("regression" in e["filename"] for e in out)


def test_regression_pytest_filename_pattern() -> None:
    out = regression_replay.emit_pytest("auth", _sample_intent())
    assert out[0]["filename"] == "test_evo_version-upgrade_auth__s_001__regression.py"


def test_regression_pytest_has_evo_header() -> None:
    out = regression_replay.emit_pytest("auth", _sample_intent())
    assert "EVO-generated test" in out[0]["content"]
    assert "characterization-aid" in out[0]["content"]


def test_regression_pytest_empty_seeds() -> None:
    out = regression_replay.emit_pytest("auth", {"test_seeds": []})
    assert out == []


def test_regression_jest_emits_one_per_seed() -> None:
    out = regression_replay.emit_jest("auth", _sample_intent())
    assert len(out) == 2
    assert all(e["filename"].endswith(".test.js") for e in out)


def test_regression_jest_describe_block() -> None:
    out = regression_replay.emit_jest("auth", _sample_intent())
    assert 'describe("evo regression replay' in out[0]["content"]


def test_regression_test_type_set() -> None:
    out = regression_replay.emit_pytest("auth", _sample_intent())
    assert all(e["test_type"] == "regression" for e in out)


# ---- migration_confirm ----

def test_migration_pytest_emits_one_per_breaking_line() -> None:
    out = migration_confirm.emit_pytest("auth", _sample_api_delta())
    assert len(out) == 2


def test_migration_pytest_skipped_if_component_not_affected() -> None:
    delta = _sample_api_delta()
    delta["affected_components"] = []
    out = migration_confirm.emit_pytest("auth", delta)
    assert out == []


def test_migration_pytest_has_oracle_fixture() -> None:
    out = migration_confirm.emit_pytest("auth", _sample_api_delta())
    assert "legacy_oracle_" in out[0]["content"]
    assert "HARD-RULE 2" in out[0]["content"]


def test_migration_pytest_filename_pattern() -> None:
    out = migration_confirm.emit_pytest("auth", _sample_api_delta())
    assert out[0]["filename"] == "test_evo_version-upgrade_auth__bl000__migration.py"


def test_migration_jest_emits_one_per_breaking_line() -> None:
    out = migration_confirm.emit_jest("auth", _sample_api_delta())
    assert len(out) == 2
    assert all(e["filename"].endswith(".test.js") for e in out)


def test_migration_test_type() -> None:
    out = migration_confirm.emit_pytest("auth", _sample_api_delta())
    assert all(e["test_type"] == "migration" for e in out)


# ---- cve_proof ----

def test_cve_proof_emits_only_direct_fix_available() -> None:
    out = cve_proof.emit_pytest("auth", _sample_cve_findings(), mode="cve-fix")
    # Only CVE-2026-1111 has direct-fix-available; CVE-2026-2222 is no-known-fix
    assert len(out) == 1
    assert "cve_2026_1111" in out[0]["filename"]


def test_cve_proof_skips_version_lag() -> None:
    out = cve_proof.emit_pytest("auth", [{"kind": "version_lag", "package": "x"}],
                                mode="cve-fix")
    assert out == []


def test_cve_proof_has_cve_metadata() -> None:
    out = cve_proof.emit_pytest("auth", _sample_cve_findings(), mode="cve-fix")
    content = out[0]["content"]
    assert "CVE-2026-1111" in content
    assert "pillow" in content
    assert "direct-fix-available" in content
    assert "cve-proof-of-fix" in content


def test_cve_proof_jest_emits() -> None:
    out = cve_proof.emit_jest("auth", _sample_cve_findings(), mode="cve-fix")
    assert len(out) == 1
    assert out[0]["filename"].endswith(".test.js")


def test_cve_proof_test_type() -> None:
    out = cve_proof.emit_pytest("auth", _sample_cve_findings(), mode="cve-fix")
    assert out[0]["test_type"] == "cve_proof"


def test_cve_proof_byte_identical_on_rerun() -> None:
    a = cve_proof.emit_pytest("auth", _sample_cve_findings(), mode="cve-fix")
    b = cve_proof.emit_pytest("auth", _sample_cve_findings(), mode="cve-fix")
    assert a[0]["content"] == b[0]["content"]
