#!/usr/bin/env python3
"""Tests for deterministic_arm.py (S048 / #116 non-LLM verification arm).

Covers the §6 + §9 verification cases VERBATIM:
  - failed test -> RED veto
  - empty / all-skipped-NON-sanctioned -> INDETERMINATE veto
  - sanctioned-tier-skip all-skipped -> GREEN pass (R-B1 — the false-block fix)
  - degraded-fallback rc==0 -> GREEN (R-I1); rc!=0 -> RED
  - hash-mismatch / forged-provenance / wrong-component -> INDETERMINATE
  - invented-citation nodeid -> veto; all-real-passing citations -> ok
  - degraded / jest bundle -> citation UNAVAILABLE (no veto)
  - bundle file is hash-addressed; bundle_hash == bundle_hash_hex(bundle)
"""
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_META = _HERE.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import deterministic_arm as da  # type: ignore
import trusted_runner as tr  # type: ignore


# ---------------------------------------------------------------------------
# Helpers — write a correctly-hash-addressed bundle to disk.
# ---------------------------------------------------------------------------

def _write_bundle(project_root: Path, component_id: str, results, *, extra=None):
    """Build a bundle dict, compute its canonical bundle_hash, and write it to
    the hash-addressed path. Returns (bundle_hash, path)."""
    bundle = {
        "component_id": component_id,
        "produced_by": da.PRODUCED_BY,
        "runner_info": {"runner": "pytest", "version": "test"},
        "run_at": "2026-06-08T00:00:00Z",
        "test_paths": ["tests/test_x.py"],
        "results": results,
    }
    if extra:
        bundle.update(extra)
    bundle_hash = tr.bundle_hash_hex(bundle)
    bundle["bundle_hash"] = bundle_hash  # convenience field (excluded from hash)
    path = da.bundle_path_for(component_id, bundle_hash, project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return bundle_hash, path


def _result(rc=0, *, passed=0, failed=0, error=0, skipped=0, tests=None):
    res = {
        "path": "tests/test_x.py",
        "returncode": rc,
        "summary": {
            "total": passed + failed + error + skipped,
            "passed": passed, "failed": failed, "error": error,
            "skipped": skipped, "duration_s": 0.0,
        },
        "failed_tests": [],
    }
    if tests is not None:
        res["tests"] = tests
    return res


# ---------------------------------------------------------------------------
# RED — failing evidence vetoes (case 1 / §9 failed->RED)
# ---------------------------------------------------------------------------

def test_failed_test_is_red(tmp_path):
    bh, _ = _write_bundle(tmp_path, "comp", [_result(
        rc=1, passed=1, failed=1,
        tests=[
            {"nodeid": "t::a", "outcome": "passed", "duration_s": 0.0, "keywords": []},
            {"nodeid": "t::b", "outcome": "failed", "duration_s": 0.0, "keywords": []},
        ],
    )])
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.RED, v["reason"]


def test_error_outcome_is_red(tmp_path):
    bh, _ = _write_bundle(tmp_path, "comp", [_result(
        rc=1, error=1,
        tests=[{"nodeid": "t::a", "outcome": "error", "duration_s": 0.0, "keywords": []}],
    )])
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.RED


# ---------------------------------------------------------------------------
# INDETERMINATE — empty / all-skipped-non-sanctioned / timeout (case 2, 6)
# ---------------------------------------------------------------------------

def test_empty_results_is_indeterminate(tmp_path):
    bh, _ = _write_bundle(tmp_path, "comp", [])
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.INDETERMINATE
    assert "empty" in v["reason"].lower() or "no results" in v["reason"].lower()


def test_all_skipped_non_sanctioned_is_indeterminate(tmp_path):
    # all-skipped with NO sanction stamp -> should-have-run-but-didn't -> veto.
    bh, _ = _write_bundle(tmp_path, "comp", [_result(
        rc=0, skipped=2,
        tests=[
            {"nodeid": "t::a", "outcome": "skipped", "duration_s": 0.0, "keywords": []},
            {"nodeid": "t::b", "outcome": "skipped", "duration_s": 0.0, "keywords": []},
        ],
    )])
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.INDETERMINATE, v["reason"]


def test_timeout_returncode_is_indeterminate_not_red(tmp_path):
    # returncode -1 (timeout) is a rerun-class INDETERMINATE, distinct from RED.
    bh, _ = _write_bundle(tmp_path, "comp", [_result(rc=da.RC_TIMEOUT, error=1)])
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.INDETERMINATE


def test_runner_not_found_is_indeterminate(tmp_path):
    bh, _ = _write_bundle(tmp_path, "comp", [_result(rc=da.RC_RUNNER_NOT_FOUND, error=1)])
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.INDETERMINATE


# ---------------------------------------------------------------------------
# R-B1 — sanctioned-tier-skip all-skipped -> GREEN (THE false-block fix)
# ---------------------------------------------------------------------------

def test_sanctioned_tier_skip_all_skipped_is_green(tmp_path):
    bh, _ = _write_bundle(tmp_path, "comp", [_result(
        rc=0, skipped=2,
        tests=[
            {"nodeid": "t::a", "outcome": "skipped", "duration_s": 0.0,
             "keywords": [], "required_tier": 2, "sanctioned_tier_skip": True},
            {"nodeid": "t::b", "outcome": "skipped", "duration_s": 0.0,
             "keywords": [], "required_tier": 2, "sanctioned_tier_skip": True},
        ],
    )])
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.GREEN, v["reason"]
    assert v["tests"]["sanctioned_skips"] == 2


def test_mixed_sanctioned_and_unsanctioned_skip_is_indeterminate(tmp_path):
    # One sanctioned, one bare skip, zero passed -> veto (the bare skip should
    # have run for this tier).
    bh, _ = _write_bundle(tmp_path, "comp", [_result(
        rc=0, skipped=2,
        tests=[
            {"nodeid": "t::a", "outcome": "skipped", "duration_s": 0.0,
             "keywords": [], "sanctioned_tier_skip": True},
            {"nodeid": "t::b", "outcome": "skipped", "duration_s": 0.0,
             "keywords": []},
        ],
    )])
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.INDETERMINATE, v["reason"]


def test_passed_plus_sanctioned_skip_is_green(tmp_path):
    bh, _ = _write_bundle(tmp_path, "comp", [_result(
        rc=0, passed=1, skipped=1,
        tests=[
            {"nodeid": "t::a", "outcome": "passed", "duration_s": 0.0, "keywords": []},
            {"nodeid": "t::b", "outcome": "skipped", "duration_s": 0.0,
             "keywords": [], "sanctioned_tier_skip": True},
        ],
    )])
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.GREEN


# ---------------------------------------------------------------------------
# Plain GREEN
# ---------------------------------------------------------------------------

def test_passing_bundle_is_green(tmp_path):
    bh, _ = _write_bundle(tmp_path, "comp", [_result(
        rc=0, passed=3,
        tests=[
            {"nodeid": "t::a", "outcome": "passed", "duration_s": 0.0, "keywords": []},
            {"nodeid": "t::b", "outcome": "passed", "duration_s": 0.0, "keywords": []},
            {"nodeid": "t::c", "outcome": "passed", "duration_s": 0.0, "keywords": []},
        ],
    )])
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.GREEN
    assert v["evidence_quality"] == da.QUALITY_FULL


# ---------------------------------------------------------------------------
# R-I1 — degraded-GREEN on the returncode-only fallback
# ---------------------------------------------------------------------------

def test_degraded_fallback_rc0_is_green(tmp_path):
    # No `tests` key (returncode-only fallback). rc==0 -> GREEN degraded.
    bh, _ = _write_bundle(tmp_path, "comp", [_result(rc=0, passed=1)])  # no tests=
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.GREEN, v["reason"]
    assert v["evidence_quality"] == da.QUALITY_DEGRADED


def test_degraded_fallback_rc_nonzero_is_red(tmp_path):
    bh, _ = _write_bundle(tmp_path, "comp", [_result(rc=1, failed=1)])  # no tests=
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.RED


# ---------------------------------------------------------------------------
# Provenance / hash / component integrity -> INDETERMINATE
# ---------------------------------------------------------------------------

def test_missing_bundle_is_indeterminate(tmp_path):
    v = da.classify_bundle_evidence("comp", "0" * 64, tmp_path)
    assert v["state"] == da.INDETERMINATE
    assert "missing" in v["reason"].lower()


def test_forged_provenance_is_indeterminate(tmp_path):
    # produced_by != bob-trusted-runner. Build a bundle with a forged producer,
    # hash it, and write at its hash path.
    bundle = {
        "component_id": "comp",
        "produced_by": "evil-skill",
        "runner_info": {}, "run_at": "x", "test_paths": [],
        "results": [_result(rc=0, passed=1, tests=[
            {"nodeid": "t::a", "outcome": "passed", "duration_s": 0.0, "keywords": []}])],
    }
    bh = tr.bundle_hash_hex(bundle)
    bundle["bundle_hash"] = bh
    p = da.bundle_path_for("comp", bh, tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(bundle), encoding="utf-8")
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.INDETERMINATE
    assert "provenance" in v["reason"].lower()


def test_hash_mismatch_is_indeterminate(tmp_path):
    # Write a valid bundle, then mutate the file content so the recomputed hash
    # no longer matches the filename -> INDETERMINATE.
    bh, path = _write_bundle(tmp_path, "comp", [_result(rc=0, passed=1, tests=[
        {"nodeid": "t::a", "outcome": "passed", "duration_s": 0.0, "keywords": []}])])
    doc = json.loads(path.read_text())
    doc["results"][0]["summary"]["passed"] = 999  # tamper -> changes canonical bytes
    path.write_text(json.dumps(doc), encoding="utf-8")
    v = da.classify_bundle_evidence("comp", bh, tmp_path)
    assert v["state"] == da.INDETERMINATE
    assert "bundle_hash" in v["reason"]


def test_wrong_component_is_indeterminate(tmp_path):
    bh, _ = _write_bundle(tmp_path, "comp-A", [_result(rc=0, passed=1, tests=[
        {"nodeid": "t::a", "outcome": "passed", "duration_s": 0.0, "keywords": []}])])
    # Look it up under a DIFFERENT component_id (path won't even resolve, but
    # also the component check would fire). Use the correct path but wrong id by
    # writing under comp-A then asking for comp-B at the same hash dir.
    v = da.classify_bundle_evidence("comp-B", bh, tmp_path)
    assert v["state"] == da.INDETERMINATE  # missing at comp-B path


# ---------------------------------------------------------------------------
# Citation corroboration (R-I3)
# ---------------------------------------------------------------------------

def _bundle_with_tests(tmp_path, nodeids_outcomes):
    tests = [{"nodeid": n, "outcome": o, "duration_s": 0.0, "keywords": []}
             for (n, o) in nodeids_outcomes]
    passed = sum(1 for _, o in nodeids_outcomes if o == "passed")
    bh, path = _write_bundle(tmp_path, "comp", [_result(rc=0, passed=passed, tests=tests)])
    return json.loads(path.read_text())


def test_citation_all_real_passing_is_ok(tmp_path):
    bundle = _bundle_with_tests(tmp_path, [("t::a", "passed"), ("t::b", "passed")])
    c = da.corroborate_citations(bundle, {"REQ-1": ["t::a"], "REQ-2": ["t::b"]})
    assert c["status"] == da.CIT_OK
    assert c["checked"] == 2
    assert c["invalid"] == []


def test_citation_invented_nodeid_is_veto(tmp_path):
    bundle = _bundle_with_tests(tmp_path, [("t::a", "passed")])
    c = da.corroborate_citations(bundle, {"REQ-1": ["t::a"], "REQ-2": ["t::ghost"]})
    assert c["status"] == da.CIT_VETO
    assert any(inv["nodeid"] == "t::ghost" for inv in c["invalid"])


def test_citation_nonpassing_nodeid_is_veto(tmp_path):
    bundle = _bundle_with_tests(tmp_path, [("t::a", "passed"), ("t::b", "skipped")])
    # cite t::b which exists but did NOT pass.
    c = da.corroborate_citations(bundle, {"REQ-1": ["t::b"]})
    assert c["status"] == da.CIT_VETO


def test_citation_degraded_bundle_is_unavailable(tmp_path):
    # Bundle with no per-test records -> corroboration unavailable, no veto.
    bh, path = _write_bundle(tmp_path, "comp", [_result(rc=0, passed=1)])  # no tests
    bundle = json.loads(path.read_text())
    c = da.corroborate_citations(bundle, {"REQ-1": ["anything"]})
    assert c["status"] == da.CIT_UNAVAILABLE


def test_citation_jest_no_passed_tests_is_unavailable(tmp_path):
    # Jest-style: results carry no `tests[]` list -> unavailable.
    bh, path = _write_bundle(tmp_path, "comp", [{
        "path": "x.test.js", "returncode": 0,
        "summary": {"total": 1, "passed": 1, "failed": 0, "error": 0, "skipped": 0, "duration_s": 0.0},
        "failed_tests": [],
    }])
    bundle = json.loads(path.read_text())
    c = da.corroborate_citations(bundle, {"REQ-1": ["x"]})
    assert c["status"] == da.CIT_UNAVAILABLE


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_green_exit_0(tmp_path, capsys):
    bh, _ = _write_bundle(tmp_path, "comp", [_result(rc=0, passed=1, tests=[
        {"nodeid": "t::a", "outcome": "passed", "duration_s": 0.0, "keywords": []}])])
    rc = da.main(["deterministic_arm.py", "comp", bh, str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deterministic"]["state"] == da.GREEN


def test_cli_red_exit_2(tmp_path, capsys):
    bh, _ = _write_bundle(tmp_path, "comp", [_result(rc=1, failed=1, tests=[
        {"nodeid": "t::a", "outcome": "failed", "duration_s": 0.0, "keywords": []}])])
    rc = da.main(["deterministic_arm.py", "comp", bh, str(tmp_path)])
    assert rc == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
