#!/usr/bin/env python3
"""ux_review.py — S074. The wrapper that OWNS the UX-review sequence.

`G_UX_EVIDENCE` can validate an artifact but cannot cause a review to happen, and a bare
standalone invocation has no enforcement edge on this host (`settings.json` carries
SessionStart hooks only — no Stop, no PostToolUse). This module closes that lane the only
honest way available: by becoming the supported entry point, so that **evidence is a
byproduct of doing the work rather than a claim made afterwards**.

    plan -> measure each cell -> evaluate -> assemble evidence -> validate -> verdict

The model's job is to explain the artifact. It never produces the verdict: the terminal
outcome is whatever `ux_evidence.validate()` computes, printed verbatim.

WHAT THIS DELIBERATELY WILL NOT DO
----------------------------------
It will not invent a cell. Every failure mode lands as an explicit non-passing status:

  * transport missing / crashed        -> status "error",       errors[] carries why
  * geometry never stabilised          -> status "inconclusive" (an intermediate layout
                                          is a clean reading of a page nobody sees)
  * fixture state not reachable        -> status "unmeasured"   (see URL resolution below)
  * required capability not declared   -> capabilities_missing  (the incident: a dev box
                                          with no payment gateway returned a clean pass on
                                          a surface that did not exist there)

`--capability` is opt-IN for exactly that reason. A plan that declares
`required_capabilities` and a run that declares none yields INCONCLUSIVE, not PASS. Failing
toward "cannot conclude" is the whole point; the reviewed environment must assert what it
can actually render.

URL RESOLUTION (a fixture measured in the wrong state is worse than one not measured)
------------------------------------------------------------------------------------
  1. `--fixture-url <surface>:<fixture>=<url>` override, when supplied
  2. `setup.ref`, when `setup.kind == "url"`
  3. `surface.url`, ONLY when the fixture declares no `setup` at all (the default state)

Anything else — `script`, `api`, `manual` — is NOT automatable here, so the cell is
`unmeasured` with the reason recorded. Navigating to `surface.url` and hoping the fixture
happened to materialise would produce a confident measurement of the wrong page.

Stdlib only. Exit codes follow the house convention and mirror ux_evidence.py:
    0 — outcome PASS
    2 — outcome FAIL / INCONCLUSIVE / UNMEASURED
    3 — environment failure (unreadable plan, transport absent, node missing)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
MEASURE_SCRIPT = HERE / "geometry_measure.mjs"

sys.path.insert(0, str(HERE))
import geometry_rules  # noqa: E402
import ux_evidence  # noqa: E402

COLLECTION_SPEC_ID = "ux-review-collection"


# ---------------------------------------------------------------------------
# environment
# ---------------------------------------------------------------------------


def env_error(message: str) -> int:
    sys.stderr.write(f"UX_REVIEW_ENV_ERROR: {message}\n")
    return 3


def _node_bin() -> Optional[str]:
    return shutil.which("node")


# ---------------------------------------------------------------------------
# per-cell measurement
# ---------------------------------------------------------------------------


def resolve_cell_url(
    surface: Dict[str, Any],
    fixture: Dict[str, Any],
    overrides: Dict[Tuple[str, str], str],
) -> Tuple[Optional[str], Optional[str]]:
    """Return (url, refusal_reason). Exactly one is None."""
    key = (surface["id"], fixture["id"])
    if key in overrides:
        return overrides[key], None

    setup = fixture.get("setup") or {}
    if not setup:
        return surface["url"], None

    kind = setup.get("kind")
    if kind == "url" and setup.get("ref"):
        return setup["ref"], None

    return None, (
        f"fixture setup kind {kind!r} cannot be established by this wrapper; supply "
        f"--fixture-url {surface['id']}:{fixture['id']}=<url> or measure it by another "
        f"transport. Measuring the surface default would report a confident result for "
        f"the wrong page state."
    )


def build_measure_config(
    url: str,
    viewport: Dict[str, Any],
    fixture: Dict[str, Any],
    chrome_path: Optional[str],
    allow_no_sandbox: bool,
) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "product_url": url,
        "breakpoints": {
            viewport["id"]: {
                "width": viewport["width"],
                "height": viewport["height"],
                **({"dpr": viewport["device_pixel_ratio"]} if viewport.get("device_pixel_ratio") else {}),
            }
        },
    }
    selector = fixture.get("collection_selector")
    if selector:
        # The selector's match count IS the observed cardinality. Declaring it as a spec is
        # what lets the driver COUNT rather than assert.
        cfg["specs"] = [{"id": COLLECTION_SPEC_ID, "selector": selector, "cardinality": "many"}]

    # Tier A discovery is rooted at the DOCUMENT, never at collection_selector.
    # Rooting discovery at the collection selector searches INSIDE each item and so never
    # sees the items as siblings of one another — which silently loses the entire
    # repeated-structure defect class. Caught in S074 by a smoke run that returned a clean
    # PASS on the incident fixture, the one page in the tree guaranteed to be defective.
    # The two settings answer different questions: `specs` counts, `discover` finds shape.
    cfg["discover"] = {"root": fixture.get("discover_root") or "body", "min_members": 2}
    if chrome_path:
        cfg["chrome_path"] = chrome_path
    if allow_no_sandbox:
        cfg["allow_no_sandbox"] = True
    return cfg


def run_measure(config: Dict[str, Any], timeout: int = 180) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    node = _node_bin()
    if not node:
        return None, "node not on PATH"
    if not MEASURE_SCRIPT.exists():
        return None, f"measurement transport missing at {MEASURE_SCRIPT}"
    try:
        proc = subprocess.run(
            [node, str(MEASURE_SCRIPT)],
            input=json.dumps(config),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, f"measurement timed out after {timeout}s"
    if not proc.stdout.strip():
        return None, f"transport produced no output (exit {proc.returncode}): {(proc.stderr or '')[:200]}"
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as exc:
        # A truncated payload is the documented 64KB-pipe failure; surface it as an error
        # rather than letting a half-parsed measurement through.
        return None, f"transport output was not valid JSON ({exc}); {len(proc.stdout)} bytes received"


def observed_cardinality(measurement: Dict[str, Any], viewport_id: str, selector: Optional[str]) -> Optional[int]:
    """Count what the page actually rendered. None when the plan gave nothing to count."""
    if not selector:
        return None
    bp = (measurement.get("measurements") or {}).get(viewport_id) or {}
    found = [
        el for el in bp.get("elements", [])
        if el.get("spec_id") == COLLECTION_SPEC_ID and el.get("kind") == "found"
    ]
    return len(found)


def build_cell(
    surface: Dict[str, Any],
    fixture: Dict[str, Any],
    viewport: Dict[str, Any],
    declared_capabilities: set,
    overrides: Dict[Tuple[str, str], str],
    chrome_path: Optional[str],
    allow_no_sandbox: bool,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Return (cell, raw_measurement). The raw measurement carries probe attribution.

    Findings are collected WITHOUT applying a severity floor. The floor belongs to the
    validator: an artifact that silently dropped sub-floor findings could not be
    re-validated at a stricter floor later, which would make the evidence a function of
    the settings it was collected under.
    """
    cell: Dict[str, Any] = {
        "surface_id": surface["id"],
        "fixture_id": fixture["id"],
        "viewport_id": viewport["id"],
        "expected_cardinality": fixture.get("expected_cardinality"),
    }

    # Capability check first: an unrenderable surface must never reach measurement and
    # come back clean. This is the incident, mechanised.
    required = set(surface.get("required_capabilities") or [])
    missing = sorted(required - declared_capabilities)
    if missing:
        cell.update({
            "status": "inconclusive",
            "capabilities_missing": missing,
            "observed_cardinality": None,
            "findings": [],
            "errors": [],
        })
        return cell, None

    url, refusal = resolve_cell_url(surface, fixture, overrides)
    if refusal:
        cell.update({"status": "unmeasured", "observed_cardinality": None, "findings": [], "errors": [refusal]})
        return cell, None

    config = build_measure_config(url, viewport, fixture, chrome_path, allow_no_sandbox)
    measurement, err = run_measure(config)
    if err:
        cell.update({"status": "error", "observed_cardinality": None, "findings": [], "errors": [err]})
        return cell, None

    bp = (measurement.get("measurements") or {}).get(viewport["id"]) or {}
    errors = list(measurement.get("errors") or []) + list(bp.get("errors") or [])
    if not bp:
        cell.update({
            "status": "error",
            "observed_cardinality": None,
            "findings": [],
            "errors": errors or [f"transport returned no measurement for viewport {viewport['id']}"],
        })
        return cell, measurement

    # Tier B relations are declared per SURFACE in the plan and are optional: a plan with
    # none gets Tier A alone, which is the zero-configuration default and carries the
    # incident-catching value by itself.
    rules_config = {"relations": surface.get("relations") or []}
    findings = geometry_rules.evaluate(measurement, rules_config).get("findings", [])

    cell.update({
        "status": "measured" if not errors else "error",
        "observed_cardinality": observed_cardinality(measurement, viewport["id"], fixture.get("collection_selector")),
        "readiness": "stable" if bp.get("stable") else "unstable",
        "findings": findings,
        "errors": errors,
    })
    return cell, measurement


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def run_review(
    plan: Dict[str, Any],
    *,
    enforcement: str = "wrapper",
    run_id: str,
    product_hash: Optional[str] = None,
    declared_capabilities: Optional[set] = None,
    overrides: Optional[Dict[Tuple[str, str], str]] = None,
    chrome_path: Optional[str] = None,
    allow_no_sandbox: bool = False,
) -> Dict[str, Any]:
    """Drive every planned cell and assemble the evidence artifact.

    The artifact carries `observed_cells` as a plain count of what was driven. It is NOT a
    coverage claim: `ux_evidence.validate()` recomputes coverage from the plan and ignores
    whatever this number says.
    """
    declared_capabilities = declared_capabilities or set()
    overrides = overrides or {}
    # NOTE: no severity floor here on purpose. Findings are collected unfiltered and the
    # floor is applied by the validator, so the same artifact can be re-validated at a
    # stricter floor later. Filtering at collection would make the evidence a function of
    # the settings it happened to be gathered under.

    viewports = {v["id"]: v for v in plan.get("viewports", [])}
    cells: List[Dict[str, Any]] = []
    probe_sample: Optional[Dict[str, Any]] = None

    for surface in plan.get("surfaces", []):
        vp_ids = surface.get("viewport_ids") or list(viewports)
        for fixture in surface.get("fixtures", []):
            for vp_id in vp_ids:
                viewport = viewports.get(vp_id)
                if viewport is None:
                    cells.append({
                        "surface_id": surface["id"], "fixture_id": fixture["id"], "viewport_id": vp_id,
                        "status": "error", "findings": [], "errors": [f"viewport {vp_id!r} is not declared in the plan"],
                    })
                    continue
                cell, measurement = build_cell(
                    surface, fixture, viewport, declared_capabilities, overrides,
                    chrome_path, allow_no_sandbox,
                )
                cells.append(cell)
                if probe_sample is None and measurement:
                    probe_sample = measurement

    evidence: Dict[str, Any] = {
        "schema_version": ux_evidence.EVIDENCE_SCHEMA_VERSION,
        "run_id": run_id,
        "plan_id": plan.get("plan_id"),
        "plan_hash": f"sha256:{ux_evidence.canonical_hash(plan)}",
        "product_hash": product_hash,
        "transport": "puppeteer",
        "enforcement": enforcement,
        "expected_cells": len(ux_evidence.expected_cells(plan)),
        "observed_cells": len([c for c in cells if c.get("status") != "unmeasured"]),
        "cells": cells,
        "unmeasured_by_design": [
            "paint bounds (shadows, outlines, pseudo-elements, glyph overflow) are not "
            "measurable from DOM geometry and are reported unmeasured, never passed",
        ],
    }
    # Probe attribution comes from a REAL measurement or not at all. A missing probe_hash
    # is a structural failure in the validator — which is the correct outcome for a run
    # where nothing was actually measured, rather than a plausible-looking default.
    attach_probe_attribution(evidence, probe_sample)
    return evidence


def attach_probe_attribution(evidence: Dict[str, Any], sample: Optional[Dict[str, Any]]) -> None:
    if not sample:
        return
    if sample.get("probe_version"):
        evidence["probe_version"] = sample["probe_version"]
    if sample.get("probe_hash"):
        evidence["probe_hash"] = sample["probe_hash"]
    if sample.get("sandbox_disabled") is not None:
        evidence["sandbox_disabled"] = bool(sample["sandbox_disabled"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_override(raw: str) -> Tuple[Tuple[str, str], str]:
    ref, _, url = raw.partition("=")
    surface, _, fixture = ref.partition(":")
    if not (surface and fixture and url):
        raise argparse.ArgumentTypeError(
            f"--fixture-url expects <surface>:<fixture>=<url>, got {raw!r}"
        )
    return (surface, fixture), url


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Drive a measured UX review and emit validated evidence.")
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--out", type=Path, help="where to write the evidence artifact")
    ap.add_argument("--run-id", required=True, help="caller-supplied; this module never invents one")
    ap.add_argument("--product-hash", help="build identity of what was reviewed")
    ap.add_argument("--enforcement", choices=["wrapper", "ci", "gate"], default="wrapper")
    ap.add_argument("--capability", action="append", default=[],
                    help="declare a capability PRESENT in this environment; repeatable")
    ap.add_argument("--fixture-url", action="append", default=[],
                    help="<surface>:<fixture>=<url> override for non-URL fixture setups")
    ap.add_argument("--chrome-path")
    ap.add_argument("--allow-no-sandbox", action="store_true",
                    help="weakens Chrome against an untrusted page; stamped into the evidence")
    ap.add_argument("--severity-floor", choices=list(ux_evidence.SEVERITY_ORDER))
    ap.add_argument("--json", action="store_true", help="print the verdict as JSON")
    args = ap.parse_args(argv)

    try:
        plan = ux_evidence.load_plan(args.plan)
    except Exception as exc:
        return env_error(f"plan unreadable: {exc}")

    if not _node_bin():
        return env_error("node not on PATH — the measurement transport cannot run")

    try:
        overrides = dict(_parse_override(o) for o in args.fixture_url)
    except argparse.ArgumentTypeError as exc:
        return env_error(str(exc))

    evidence = run_review(
        plan,
        enforcement=args.enforcement,
        run_id=args.run_id,
        product_hash=args.product_hash,
        declared_capabilities=set(args.capability),
        overrides=overrides,
        chrome_path=args.chrome_path,
        allow_no_sandbox=args.allow_no_sandbox,
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")

    verdict = ux_evidence.validate(evidence, plan, severity_floor=args.severity_floor)

    if args.json:
        print(json.dumps(verdict, indent=2, sort_keys=True))
    else:
        print(f"UX_REVIEW {verdict['outcome']}: {verdict['observed_cells']}/{verdict['expected_cells']} "
              f"cells, {verdict['finding_count']} finding(s), "
              f"{verdict['findings_at_floor']} at floor '{verdict['severity_floor']}' "
              f"[enforcement: {verdict['enforcement']}]")
        for reason in verdict["outcome_reasons"]:
            print(f"  - {reason}")

    return 0 if verdict["outcome"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
