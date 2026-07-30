#!/usr/bin/env python3
"""ux_evidence.py — S073. Validate a UX-review evidence artifact against its plan.

The central rule: **the reviewer never states its own coverage.** The expected fixture
matrix is derived from the PLAN (project-owned); the driver reports only what it
OBSERVED; this module computes `expected - observed` and the final outcome. A schema
alone does not make a self-attested claim trustworthy — the same agent that skips the
work will happily emit a well-formed block claiming it was done.

Outcome precedence (first match wins) — chosen so an incomplete run can never look clean:

  UNMEASURED     planned cells with no measurement at all, or cells marked unmeasured.
                 Absence of findings from a cell that never ran is not evidence.
  INCONCLUSIVE   the cell ran but cannot support a verdict: an error, unstable geometry
                 (an intermediate layout was measured), a cardinality mismatch (the
                 fixture did not materialise), or a missing required capability (the
                 surface was not rendered in this environment at all).
  FAIL           fully measured, with at least one finding at or above the severity floor.
  PASS           fully measured, everything matched, nothing at or above the floor.

Stdlib only; PyYAML used when available so plans can be YAML, with a JSON fallback.

Public API (stable):
    load_plan(path) -> dict
    canonical_hash(obj) -> str
    expected_cells(plan) -> list[tuple[str, str, str]]
    validate(evidence, plan, severity_floor=None) -> dict
    main(argv) -> int

Exit codes (house convention: 0 pass / 2 block / 3 environment):
    0 — outcome PASS
    2 — outcome FAIL / INCONCLUSIVE / UNMEASURED, or the artifact is invalid
    3 — plan or evidence unreadable
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SEVERITY_ORDER = {"critical": 3, "major": 2, "minor": 1, "info": 0}
DEFAULT_SEVERITY_FLOOR = "major"

EVIDENCE_SCHEMA_VERSION = "ux-evidence.v1"
PLAN_SCHEMA_VERSION = "ux-review-plan.v1"


def _load_structured(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(f"PyYAML needed to read {path.name}: {exc}") from exc
        return yaml.safe_load(text) or {}
    return json.loads(text)


def load_plan(path: Path) -> Dict[str, Any]:
    plan = _load_structured(path)
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ValueError(
            f"plan schema_version must be {PLAN_SCHEMA_VERSION}, got {plan.get('schema_version')!r}"
        )
    return plan


def canonical_hash(obj: Any) -> str:
    """sha256 of canonical JSON — stable across key ordering and formatting."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def expected_cells(plan: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """The full planned matrix: surface x fixture x viewport.

    Derived from the plan alone. This is the number the reviewer is measured against and
    has no way to influence.
    """
    all_viewports = [v["id"] for v in plan.get("viewports", [])]
    cells: List[Tuple[str, str, str]] = []
    for surface in plan.get("surfaces", []):
        vp_ids = surface.get("viewport_ids") or all_viewports
        for fixture in surface.get("fixtures", []):
            for vp in vp_ids:
                cells.append((surface["id"], fixture["id"], vp))
    return cells


def _fixture_index(plan: Dict[str, Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    idx: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for surface in plan.get("surfaces", []):
        for fixture in surface.get("fixtures", []):
            idx[(surface["id"], fixture["id"])] = fixture
    return idx


def validate(
    evidence: Dict[str, Any],
    plan: Dict[str, Any],
    severity_floor: Optional[str] = None,
) -> Dict[str, Any]:
    """Recompute coverage and outcome. Never trusts `outcome` from the input."""
    floor_name = severity_floor or plan.get("severity_floor") or DEFAULT_SEVERITY_FLOOR
    floor = SEVERITY_ORDER.get(floor_name, SEVERITY_ORDER[DEFAULT_SEVERITY_FLOOR])

    reasons: List[str] = []
    structural: List[str] = []

    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        structural.append(
            f"schema_version must be {EVIDENCE_SCHEMA_VERSION}, got {evidence.get('schema_version')!r}"
        )

    # Plan binding: evidence measured against a different plan proves nothing about this one.
    declared_plan_hash = (evidence.get("plan_hash") or "").replace("sha256:", "")
    actual_plan_hash = canonical_hash(plan)
    if declared_plan_hash and declared_plan_hash != actual_plan_hash:
        structural.append(
            "plan_hash does not match the supplied plan — evidence was produced against "
            "a different plan revision"
        )
    if not evidence.get("probe_hash"):
        structural.append("probe_hash missing — measurements cannot be attributed to a probe version")
    if not evidence.get("product_hash"):
        # Not fatal on its own, but it means the evidence is not pinned to a build.
        reasons.append(
            "product_hash absent: this evidence is not bound to a specific reviewed build"
        )

    planned = expected_cells(plan)
    planned_set = set(planned)
    fixtures = _fixture_index(plan)

    measured: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for cell in evidence.get("cells", []) or []:
        key = (cell.get("surface_id"), cell.get("fixture_id"), cell.get("viewport_id"))
        measured[key] = cell

    unexpected = [k for k in measured if k not in planned_set]
    missing = [k for k in planned if k not in measured]

    unmeasured_cells: List[Tuple[str, str, str]] = list(missing)
    inconclusive_cells: List[Tuple[str, str, str]] = []
    findings_at_floor: List[Dict[str, Any]] = []
    total_findings = 0

    for key in planned:
        cell = measured.get(key)
        if cell is None:
            continue
        status = cell.get("status")
        if status == "unmeasured":
            unmeasured_cells.append(key)
            continue
        if status in ("error", "inconclusive"):
            inconclusive_cells.append(key)
            # Carry the cell's own explanation up. A producer that has already classified a
            # cell as inconclusive still knows WHY, and dropping that here produced an
            # artifact saying only "cannot support a verdict" — true, unactionable, and
            # against this contract's own rule that a non-pass must explain itself.
            if cell.get("capabilities_missing"):
                reasons.append(
                    f"{key}: required capability absent ({', '.join(cell['capabilities_missing'])}) "
                    f"— the surface was not rendered in this environment"
                )
            for err in (cell.get("errors") or [])[:3]:
                reasons.append(f"{key}: {err}")
            continue

        if cell.get("errors"):
            inconclusive_cells.append(key)
            continue
        if cell.get("readiness") not in (None, "stable"):
            inconclusive_cells.append(key)
            reasons.append(f"{key}: geometry {cell.get('readiness')} — an intermediate layout was measured")
            continue
        if cell.get("capabilities_missing"):
            inconclusive_cells.append(key)
            reasons.append(
                f"{key}: required capability absent ({', '.join(cell['capabilities_missing'])}) "
                f"— the surface was not rendered in this environment"
            )
            continue

        fixture = fixtures.get((key[0], key[1])) or {}
        expected_card = fixture.get("expected_cardinality")
        observed_card = cell.get("observed_cardinality")
        if expected_card is not None:
            if observed_card is None:
                inconclusive_cells.append(key)
                reasons.append(f"{key}: cardinality unverified — no observed count reported")
                continue
            if observed_card != expected_card:
                inconclusive_cells.append(key)
                reasons.append(
                    f"{key}: fixture did not materialise — expected {expected_card} item(s), "
                    f"observed {observed_card}"
                )
                continue

        for finding in cell.get("findings", []) or []:
            total_findings += 1
            if SEVERITY_ORDER.get(finding.get("severity", "info"), 0) >= floor:
                findings_at_floor.append(finding)

    # ---- outcome, computed ----------------------------------------------------------
    if structural:
        outcome = "UNMEASURED"
        reasons = structural + reasons
    elif unmeasured_cells:
        outcome = "UNMEASURED"
        reasons.insert(0, f"{len(unmeasured_cells)} of {len(planned)} planned cell(s) were never measured")
    elif inconclusive_cells:
        outcome = "INCONCLUSIVE"
        reasons.insert(0, f"{len(inconclusive_cells)} cell(s) ran but cannot support a verdict")
    elif findings_at_floor:
        outcome = "FAIL"
        reasons.insert(0, f"{len(findings_at_floor)} finding(s) at or above severity '{floor_name}'")
    else:
        outcome = "PASS"
        reasons.insert(0, f"all {len(planned)} planned cell(s) measured, no finding at or above '{floor_name}'")

    if unexpected:
        reasons.append(f"{len(unexpected)} measured cell(s) are not in the plan and were ignored")

    return {
        "schema": "ux-evidence-verdict.v1",
        "plan_id": plan.get("plan_id"),
        "plan_hash": actual_plan_hash,
        "run_id": evidence.get("run_id"),
        "product_url": evidence.get("product_url"),
        "product_hash": evidence.get("product_hash"),
        "probe_version": evidence.get("probe_version"),
        "enforcement": evidence.get("enforcement") or "convention",
        "severity_floor": floor_name,
        "expected_cells": len(planned),
        "observed_cells": len([k for k in planned if k in measured]),
        "missing_cells": [{"surface_id": s, "fixture_id": f, "viewport_id": v} for s, f, v in missing],
        "unmeasured_count": len(unmeasured_cells),
        "inconclusive_count": len(inconclusive_cells),
        "finding_count": total_findings,
        "findings_at_floor": len(findings_at_floor),
        "outcome": outcome,
        "outcome_reasons": reasons,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Validate UX evidence against its plan.")
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--evidence", type=Path, required=True)
    ap.add_argument("--severity-floor", choices=list(SEVERITY_ORDER), default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        plan = load_plan(args.plan)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ux_evidence: plan unreadable: {exc}", file=sys.stderr)
        return 3
    try:
        evidence = _load_structured(args.evidence)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ux_evidence: evidence unreadable: {exc}", file=sys.stderr)
        return 3

    verdict = validate(evidence, plan, args.severity_floor)

    if args.json:
        print(json.dumps(verdict, indent=2))
    else:
        print(f"outcome: {verdict['outcome']}   "
              f"cells: {verdict['observed_cells']}/{verdict['expected_cells']}   "
              f"findings: {verdict['finding_count']} "
              f"({verdict['findings_at_floor']} at/above {verdict['severity_floor']})   "
              f"enforcement: {verdict['enforcement']}")
        for reason in verdict["outcome_reasons"]:
            print(f"  - {reason}")

    return 0 if verdict["outcome"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
