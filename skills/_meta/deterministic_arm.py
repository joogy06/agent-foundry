#!/usr/bin/env python3
"""deterministic_arm.py — the non-LLM verification arm (S048 / #116).

The dual-verdict (audit_spawn Claude+Codex + verification_arbiter Claude) couples
two LLM arms at INTEGRATED -> VERIFIED, but #118's R6 reads ONLY the LLM verdict
strings — it NEVER reads the actual on-disk test evidence. A correlated-LLM-error
(both arms wrongly approve a failing/empty/mismatched bundle) can therefore reach
VERIFIED. This module is the deterministic (non-LLM) arm R6 derives DIRECTLY from
the hash-addressed evidence bundle:

  - `classify_bundle_evidence(component_id, bundle_hash, project_root)` loads the
    bundle at `.ledger/evidence/<component_id>/<bundle_hash>.bundle.json`,
    recomputes `trusted_runner.bundle_hash_hex` (== the lookup key, else
    INDETERMINATE), asserts `produced_by == "bob-trusted-runner"` + component
    match, and classifies the suite into GREEN / RED / INDETERMINATE.
  - `corroborate_citations(bundle, evidence_map)` walks
    `bundle["results"][*]["tests"][*]` and verifies every cited nodeid EXISTS
    AND has `outcome == "passed"` (R-I3).

DESIGN NOTES (binding §9 supersedes §2-§4):

  R-B1  sanctioned-tier-skip: GREEN = no failed/error/timeout AND (>=1 passed OR
        every non-passed test is a `sanctioned_tier_skip`). The trusted runner
        STAMPS the tier decision into the bundle (bundle-level `tier_decision`
        + per-test `sanctioned_tier_skip: true` when `required_tier >
        inventory_tier`, reproducible from the inventory hash). This module READS
        it from the bundle (stays bundle-only — no test-plan dependency at
        transition time). "Should-have-run-but-didn't" (all-skipped with NO
        sanction stamp) -> INDETERMINATE.

  R-I1  degraded-GREEN: a fallback bundle (no pytest-json-report -> returncode-
        only; trusted_runner `_result_from_returncode`) has NO per-test `tests[]`
        list. returncode == 0 ⟺ no failures (sound) -> GREEN with
        `evidence_quality: degraded` (citation-corroboration UNAVAILABLE on it,
        recorded, no veto). returncode != 0 -> RED.

  R-I3  citation algorithm walks `results[].tests[]` (NOT a top-level tests[]).
        pytest-scoped; gated on rubric_version + per-test presence. Jest bundles
        (no passed tests[]) -> citation UNAVAILABLE (recorded, no veto).

HONEST SCOPE: this arm catches the *red-evidence-contradiction* + *invented-
evidence* class (a VERIFIED that contradicts failing/empty/mismatched evidence,
or cites non-existent tests). It does NOT close the *semantic-test-adequacy*
residual (tests that pass but encode the wrong oracle) — deferred to #151
(changed-line mutation pilot). R6 DERIVES this verdict from the bundle itself;
it NEVER trusts a producer-written boolean and NEVER reads gate-runs.jsonl
(fail-open telemetry with no component/bundle/state binding).

CB invariants preserved: this module READS the bundle; it NEVER writes it (the
#124 load-bearing invariant — bundle_hash untouched). It is a PURE VETO: it can
only subtract VERIFIEDs (no new pass-path), so it cannot add a false-pass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The hash-addressed evidence directory (mirrors bob.md Step 4.5 §5a:
#   .ledger/evidence/<component_id>/<bundle_hash>.bundle.json).
EVIDENCE_SUBDIR = ".ledger/evidence"

# CB3 provenance: the ONLY producer R6 trusts for a bundle.
PRODUCED_BY = "bob-trusted-runner"

# 3-state classification result.
GREEN = "GREEN"
RED = "RED"
INDETERMINATE = "INDETERMINATE"

# Per-test outcomes that constitute a real defect signal (RED).
_FAIL_OUTCOMES = frozenset({"failed", "error"})

# The deterministic-INDETERMINATE returncode sentinels emitted by the trusted
# runner (timeout / runner_not_found / unknown_runner). These are infra gaps,
# NOT defect signals — they route to the bounded-rerun-then-escalate path
# (R-I2), distinct from RED.
RC_TIMEOUT = -1
RC_RUNNER_NOT_FOUND = -2
RC_UNKNOWN_RUNNER = -3
_INDETERMINATE_RETURNCODES = frozenset({RC_TIMEOUT, RC_RUNNER_NOT_FOUND, RC_UNKNOWN_RUNNER})

# Evidence-quality tags (R-I1).
QUALITY_FULL = "full"          # pytest-json-report present -> per-test tests[]
QUALITY_DEGRADED = "degraded"  # returncode-only fallback -> no per-test detail

# Citation-corroboration availability (R-I3).
CIT_OK = "ok"
CIT_UNAVAILABLE = "unavailable"  # Jest / degraded / no per-test records
CIT_VETO = "veto"                # cited nodeid absent or non-passing


# ---------------------------------------------------------------------------
# trusted_runner import (for the canonical bundle_hash recompute)
# ---------------------------------------------------------------------------

def _import_trusted_runner():
    """Import trusted_runner.bundle_hash_hex. Lazy + path-safe so importing this
    module never perturbs gates.py / claims.py module-load (mirrors the existing
    `_load_classify_module` pattern)."""
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    import trusted_runner  # type: ignore
    return trusted_runner


# ---------------------------------------------------------------------------
# Bundle loading (hash-addressed)
# ---------------------------------------------------------------------------

def bundle_path_for(component_id: str, bundle_hash: str, project_root: Path) -> Path:
    """Return the hash-addressed bundle path
    `.ledger/evidence/<component_id>/<bundle_hash>.bundle.json`."""
    return (
        Path(project_root).resolve()
        / EVIDENCE_SUBDIR
        / str(component_id)
        / f"{bundle_hash}.bundle.json"
    )


def _read_bundle(path: Path) -> Optional[Dict[str, Any]]:
    """Read + JSON-parse the bundle. Returns None on missing/unreadable/non-dict
    (every such case -> INDETERMINATE, never RED — an unreadable bundle is an
    evidence gap, not a defect signal)."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


# ---------------------------------------------------------------------------
# 3-state classification
# ---------------------------------------------------------------------------

def _result_state(result: Dict[str, Any]) -> str:
    """Classify ONE per-path result into GREEN/RED/INDETERMINATE.

    Order matters:
      1. RED   — any failed/error outcome OR returncode not in the known set.
      2. INDETERMINATE — a deterministic-INDETERMINATE returncode (timeout /
         runner_not_found / unknown_runner), OR all-skipped with NO sanction
         stamp ("should-have-run-but-didn't").
      3. GREEN — returncode 0 AND (>=1 passed OR every non-passed test is a
         sanctioned_tier_skip) AND not-all-skipped-without-sanction.

    R-I1: a degraded (returncode-only) result has no `tests[]`. rc==0 -> GREEN
    (the returncode floor is sound: plain pytest rc==0 ⟺ no failures); rc!=0
    -> RED.
    """
    summary = result.get("summary") or {}
    try:
        rc = int(result.get("returncode", -99))
    except (TypeError, ValueError):
        rc = -99

    # (1) hard defect signals from the summary counters.
    failed = int(summary.get("failed", 0) or 0)
    error = int(summary.get("error", 0) or 0)
    passed = int(summary.get("passed", 0) or 0)
    skipped = int(summary.get("skipped", 0) or 0)

    # Per-test records (present only on the full pytest path, R-I3 / R-I1).
    tests = result.get("tests")
    has_per_test = isinstance(tests, list)

    # (0) deterministic-INDETERMINATE returncodes FIRST (timeout / runner gaps).
    # These sentinels carry a SYNTHETIC `error: 1` in the summary and a synthetic
    # failed_tests entry (outcome "timeout"/"runner_not_found"/"unknown_runner",
    # none in _FAIL_OUTCOMES, and no real per-test `tests[]` list) — those are
    # infra markers, NOT a defect signal. Classifying them here (before the
    # failed/error counter check) keeps them on the rerun-then-escalate path
    # (R-I2), distinct from RED. A genuine pytest run never returns these codes.
    if rc in _INDETERMINATE_RETURNCODES:
        return INDETERMINATE

    # (1a) any per-test failure/error -> RED (regardless of returncode).
    if has_per_test:
        for t in tests:
            if isinstance(t, dict) and t.get("outcome") in _FAIL_OUTCOMES:
                return RED
    if failed > 0 or error > 0:
        return RED

    # (1b) any other non-zero returncode is a defect signal -> RED. On the
    # degraded fallback (no per-test list) this IS the sole signal (R-I1).
    if rc != 0:
        return RED

    # rc == 0 from here. R-I1 degraded path: no per-test list + rc==0 -> GREEN
    # (returncode floor holds; citation-corroboration unavailable downstream).
    if not has_per_test:
        return GREEN

    # rc == 0 WITH per-test records. Apply R-B1 sanctioned-tier-skip carve-out.
    # GREEN requires: >=1 passed OR every non-passed test is a sanctioned skip.
    non_passed = [t for t in tests if isinstance(t, dict) and t.get("outcome") != "passed"]
    if passed >= 1:
        # At least one real passing test — but a non-passed test that is NOT a
        # sanctioned skip and NOT a benign skip is still suspect. We only RED on
        # failed/error (handled above); a plain skipped test alongside passes is
        # acceptable. So: GREEN.
        return GREEN

    # passed == 0 here. The ONLY way to GREEN is every non-passed test being a
    # sanctioned_tier_skip (R-B1). An empty suite (no tests) or all-skipped
    # WITHOUT a sanction stamp -> INDETERMINATE ("should-have-run-but-didn't").
    if not tests:
        return INDETERMINATE
    if non_passed and all(bool(t.get("sanctioned_tier_skip")) for t in non_passed):
        return GREEN
    # all-skipped (or mixed skip) with NO sanction on at least one -> veto.
    return INDETERMINATE


def classify_bundle_evidence(
    component_id: str,
    bundle_hash: str,
    project_root: Path,
) -> Dict[str, Any]:
    """The deterministic arm's verdict over the hash-addressed bundle.

    Returns a dict:
      {
        "state": GREEN | RED | INDETERMINATE,
        "reason": str,
        "evidence_quality": "full" | "degraded" | None,
        "bundle_path": str,
        "tests": {"total": int, "passed": int, "failed": int, "error": int,
                  "skipped": int, "sanctioned_skips": int},
      }

    R6 calls this and REQUIRES state == GREEN as a 4th necessary conjunct.
    The verdict is DERIVED here from the bundle — never from a producer-written
    boolean, never from gate-runs.jsonl.
    """
    project_root = Path(project_root).resolve()
    path = bundle_path_for(component_id, bundle_hash, project_root)

    base: Dict[str, Any] = {
        "state": INDETERMINATE,
        "reason": "",
        "evidence_quality": None,
        "bundle_path": str(path),
        "tests": {
            "total": 0, "passed": 0, "failed": 0,
            "error": 0, "skipped": 0, "sanctioned_skips": 0,
        },
    }

    bundle = _read_bundle(path)
    if bundle is None:
        base["reason"] = (
            f"bundle missing/unreadable/non-dict at {path} -> INDETERMINATE "
            f"(evidence gap; bounded clean rerun then escalate, do NOT VERIFY)"
        )
        return base

    # (1) provenance — refuse a skill-forged bundle (CB3).
    produced_by = bundle.get("produced_by")
    if produced_by != PRODUCED_BY:
        base["reason"] = (
            f"bundle produced_by={produced_by!r} != {PRODUCED_BY!r} "
            f"(CB3 provenance refused) -> INDETERMINATE"
        )
        return base

    # (2) component match.
    bundle_component = bundle.get("component_id")
    if str(bundle_component) != str(component_id):
        base["reason"] = (
            f"bundle component_id={bundle_component!r} != requested "
            f"{component_id!r} (cross-component mismatch) -> INDETERMINATE"
        )
        return base

    # (3) recompute the canonical bundle_hash and compare to the lookup key.
    # This is the self-hash check the arbiter is ASKED to do in prose — here
    # enforced in Python, non-spoofable. Mismatch -> INDETERMINATE.
    try:
        tr = _import_trusted_runner()
        recomputed = tr.bundle_hash_hex(bundle)
    except Exception as e:  # pragma: no cover - import/compute failure is env
        base["reason"] = (
            f"could not recompute bundle_hash ({type(e).__name__}: {e}) "
            f"-> INDETERMINATE"
        )
        return base
    if recomputed != str(bundle_hash):
        base["reason"] = (
            f"recomputed bundle_hash {recomputed!r} != lookup key "
            f"{bundle_hash!r} (content tampered / wrong file) -> INDETERMINATE"
        )
        return base

    results = bundle.get("results")
    if not isinstance(results, list) or not results:
        base["reason"] = (
            "bundle has no results[] (empty suite) -> INDETERMINATE "
            "(not a vacuous pass; bounded rerun then escalate)"
        )
        return base

    # Aggregate counters + per-result classification.
    totals = {"total": 0, "passed": 0, "failed": 0, "error": 0, "skipped": 0, "sanctioned_skips": 0}
    any_degraded = False
    any_full = False
    states: List[str] = []
    for res in results:
        if not isinstance(res, dict):
            states.append(INDETERMINATE)
            continue
        summary = res.get("summary") or {}
        totals["total"] += int(summary.get("total", 0) or 0)
        totals["passed"] += int(summary.get("passed", 0) or 0)
        totals["failed"] += int(summary.get("failed", 0) or 0)
        totals["error"] += int(summary.get("error", 0) or 0)
        totals["skipped"] += int(summary.get("skipped", 0) or 0)
        tlist = res.get("tests")
        if isinstance(tlist, list):
            any_full = True
            totals["sanctioned_skips"] += sum(
                1 for t in tlist if isinstance(t, dict) and t.get("sanctioned_tier_skip")
            )
        else:
            any_degraded = True
        states.append(_result_state(res))

    base["tests"] = totals
    base["evidence_quality"] = QUALITY_DEGRADED if (any_degraded and not any_full) else (
        QUALITY_FULL if any_full and not any_degraded else
        # mixed: at least one degraded result present -> degraded (the weaker
        # guarantee dominates; citation-corroboration is unavailable per-result
        # on the degraded ones).
        (QUALITY_DEGRADED if any_degraded else QUALITY_FULL)
    )

    # Combine per-result states. ANY RED -> RED (a real defect anywhere vetoes).
    # Else ANY INDETERMINATE -> INDETERMINATE (evidence gap). Else GREEN.
    if RED in states:
        base["state"] = RED
        base["reason"] = (
            f"deterministic RED — a failed/error/non-zero-rc result exists "
            f"(failed={totals['failed']}, error={totals['error']}); a VERIFIED "
            f"contradicting failing evidence is impossible -> veto"
        )
        return base
    if INDETERMINATE in states:
        base["state"] = INDETERMINATE
        base["reason"] = (
            f"deterministic INDETERMINATE — empty / all-skipped-without-sanction "
            f"/ timeout / runner gap (passed={totals['passed']}, "
            f"skipped={totals['skipped']}, sanctioned_skips="
            f"{totals['sanctioned_skips']}); bounded clean rerun then escalate, "
            f"do NOT VERIFY this bundle"
        )
        return base

    base["state"] = GREEN
    base["reason"] = (
        f"deterministic GREEN — passed={totals['passed']}, "
        f"sanctioned_skips={totals['sanctioned_skips']}, zero failed/error/"
        f"timeout (evidence_quality={base['evidence_quality']})"
    )
    return base


# ---------------------------------------------------------------------------
# Citation corroboration (R-I3)
# ---------------------------------------------------------------------------

def _passing_nodeids(bundle: Dict[str, Any]) -> Optional[set]:
    """Return the set of nodeids with outcome == "passed" across
    `bundle["results"][*]["tests"][*]`, or None if NO per-test records exist
    anywhere (degraded / Jest -> citation corroboration UNAVAILABLE)."""
    results = bundle.get("results")
    if not isinstance(results, list):
        return None
    found_any_list = False
    passing: set = set()
    for res in results:
        if not isinstance(res, dict):
            continue
        tlist = res.get("tests")
        if not isinstance(tlist, list):
            continue
        found_any_list = True
        for t in tlist:
            if isinstance(t, dict) and t.get("outcome") == "passed":
                nid = t.get("nodeid")
                if isinstance(nid, str) and nid:
                    passing.add(nid)
    if not found_any_list:
        return None
    return passing


def corroborate_citations(
    bundle: Dict[str, Any],
    evidence_map: Any,
) -> Dict[str, Any]:
    """Verify every nodeid cited in `evidence_map` EXISTS in the bundle's
    `results[].tests[]` AND has outcome == "passed" (R-I3).

    `evidence_map` shape: {<success_criterion_id>: [<nodeid>, ...], ...}

    Returns:
      {
        "status": "ok" | "unavailable" | "veto",
        "invalid": [{"criterion": str, "nodeid": str, "why": str}, ...],
        "checked": int,   # total cited nodeids examined
        "reason": str,
      }

    "unavailable" (no per-test records: degraded bundle / Jest) does NOT veto —
    you cannot corroborate what isn't there; the returncode floor still holds.
    A cited nodeid that's absent or non-passing -> "veto" (the arbiter
    invented/misattributed evidence — a correlated-hallucination tell). HONEST
    residual: catches *invented* evidence, NOT *irrelevant-but-real* citations.
    """
    out: Dict[str, Any] = {
        "status": CIT_UNAVAILABLE,
        "invalid": [],
        "checked": 0,
        "reason": "",
    }

    passing = _passing_nodeids(bundle)
    if passing is None:
        out["reason"] = (
            "no per-test records in bundle (degraded fallback or jest) -> "
            "citation corroboration unavailable (no veto)"
        )
        return out

    if not isinstance(evidence_map, dict):
        # Per-test records exist but no evidence_map supplied. With per-test
        # records available and the new rubric, a missing/malformed evidence_map
        # is treated as nothing-to-corroborate (the caller — R6 — decides
        # whether the rubric REQUIRES an evidence_map; this function only checks
        # what it is given). Report unavailable.
        out["reason"] = (
            f"evidence_map is not an object (got {type(evidence_map).__name__}) "
            f"-> nothing to corroborate"
        )
        return out

    invalid: List[Dict[str, str]] = []
    checked = 0
    for criterion, nodeids in evidence_map.items():
        if not isinstance(nodeids, list):
            invalid.append({
                "criterion": str(criterion),
                "nodeid": "",
                "why": f"value is not a list (got {type(nodeids).__name__})",
            })
            continue
        for nid in nodeids:
            checked += 1
            if not isinstance(nid, str) or not nid:
                invalid.append({
                    "criterion": str(criterion),
                    "nodeid": repr(nid),
                    "why": "nodeid is not a non-empty string",
                })
                continue
            if nid not in passing:
                invalid.append({
                    "criterion": str(criterion),
                    "nodeid": nid,
                    "why": "cited nodeid absent OR not outcome==passed in bundle",
                })

    out["checked"] = checked
    out["invalid"] = invalid
    if invalid:
        out["status"] = CIT_VETO
        out["reason"] = (
            f"{len(invalid)} cited nodeid(s) invalid (invented / misattributed / "
            f"non-passing) across {checked} citation(s) -> veto"
        )
    else:
        out["status"] = CIT_OK
        out["reason"] = f"all {checked} cited nodeid(s) exist and passed"
    return out


# ---------------------------------------------------------------------------
# CLI (bob pre-flight + tests)
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """CLI: deterministic_arm.py <component_id> <bundle_hash> <project_root>
              [--evidence-map <json-file>]

    Prints the combined deterministic verdict JSON to stdout. Exit codes:
      0 = GREEN (and, if an evidence_map is supplied with per-test records,
          citations corroborate or are unavailable)
      2 = veto (RED, INDETERMINATE, or citation veto)
      3 = usage / env error
    """
    if argv is None:
        argv = sys.argv
    rest: List[str] = []
    evidence_map_file: Optional[str] = None
    i = 1
    while i < len(argv):
        if argv[i] == "--evidence-map":
            if i + 1 >= len(argv):
                sys.stderr.write("--evidence-map requires a value\n")
                return 3
            evidence_map_file = argv[i + 1]
            i += 2
            continue
        rest.append(argv[i])
        i += 1

    if len(rest) != 3:
        sys.stderr.write(
            "usage: deterministic_arm.py <component_id> <bundle_hash> "
            "<project_root> [--evidence-map <json-file>]\n"
        )
        return 3

    component_id, bundle_hash, project_root = rest
    verdict = classify_bundle_evidence(component_id, bundle_hash, Path(project_root))

    citation: Optional[Dict[str, Any]] = None
    if evidence_map_file:
        try:
            evidence_map = json.loads(Path(evidence_map_file).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            sys.stderr.write(f"could not read --evidence-map: {e}\n")
            return 3
        bundle = _read_bundle(bundle_path_for(component_id, bundle_hash, Path(project_root)))
        if bundle is not None:
            citation = corroborate_citations(bundle, evidence_map)

    combined = {"deterministic": verdict, "citation": citation}
    sys.stdout.write(json.dumps(combined, indent=2, sort_keys=True) + "\n")

    if verdict["state"] != GREEN:
        return 2
    if citation is not None and citation["status"] == CIT_VETO:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
