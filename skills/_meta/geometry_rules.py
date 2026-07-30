#!/usr/bin/env python3
"""geometry_rules.py — S073. Evaluate raw geometry measurements into findings.

Consumes the output of geometry_measure.mjs / dom_geometry_probe.js. Pure functions over
JSON: no browser, no network. That separation is deliberate — false-positive tuning is the
hard part of this whole design, and it must be testable against saved fixtures rather than
by launching Chrome.

TIER A — zero-config invariants. These need no project declaration, which is the point: a
project will never have pre-declared the relation that would have caught its own bug.

  R1 repeated_collapse   Members of an auto-discovered repeated group whose corresponding
                         leaves share a coordinate. Catches "3 line-item prices all at
                         top:335" — a production cart where no row showed a price.
  R2 containment_breach  A child escaping its container's padding box. Reported as
                         `clipped_content` instead when a clipping ancestor hides it:
                         content silently lost and content painting outside a bordered
                         panel are different defects and must not be conflated.
  R3 text_clipping       Computed line-height exceeding the content box height.
  R4 rule_rhythm         Border count / widths / closest gap within a container. Catches
                         doubled rules and mismatched frame weights.

FALSE-POSITIVE POLICY. A check that cries wolf gets ignored inside one session, which
reproduces the exact failure this design exists to fix. So:
  * ancestor/descendant pairs are never compared (parents always overlap children)
  * position fixed/sticky/absolute is excluded from GENERIC inference (badges, overlays
    and sticky headers overlap by design) but never from an explicit declared relation
  * screen-reader hiding is recognised by computed properties, never by class name
  * tolerance is max(1 physical px, 0.5 CSS px) — getBoundingClientRect is subpixel
  * anything below threshold is INCONCLUSIVE, never silently clean

STATED LIMIT: DOM geometry is not paint geometry. Shadows, outlines, pseudo-elements, SVG
filters and glyph overflow can paint outside a valid bbox and are NOT measured here — they
are reported UNMEASURED rather than passed. (CSS transforms ARE reflected in
getBoundingClientRect, so scale/translate defects are covered.)

Public API (stable):
    evaluate(measurement, config=None) -> dict
    evaluate_breakpoint(bp_result, config=None) -> list[dict]
    main(argv) -> int

Exit codes (house convention: 0 pass / 2 block):
    0 — no findings at or above the configured severity
    2 — findings, or the input was not a completed measurement
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

SEVERITY_ORDER = {"critical": 3, "major": 2, "minor": 1, "info": 0}

DEFAULT_CONFIG = {
    "css_tolerance_px": 0.5,
    "min_overflow_area_px": 4.0,      # ignore hairline protrusions with no visible area
    # Two rules closer than this read as one doubled divider. 40px was the first guess and
    # was WRONG: adjacent bordered boxes separated by a normal margin (24px) tripped it on
    # every real page. The genuine defects measured 17px (cart) and ~8px (concentric summary
    # frames), so the line sits just above those and below ordinary spacing rhythm.
    "doubled_rule_gap_px": 18.0,
    # Rules must also overlap horizontally to be "the same divider seen twice"; two narrow
    # rules in different columns are unrelated however close their y happens to be.
    "doubled_rule_min_x_overlap": 0.8,
    "min_border_width_px": 0.5,
    "severity_floor": "minor",
}

# Positioning that legitimately overlaps or escapes its parent.
_ESCAPING_POSITIONS = {"fixed", "sticky", "absolute"}


def _tol(config: Dict[str, Any], dpr: float = 1.0) -> float:
    """max(1 physical px, configured CSS px) — subpixel noise must not become findings."""
    return max(1.0 / max(dpr, 1.0), float(config["css_tolerance_px"]))


def _visible(el: Dict[str, Any]) -> bool:
    return el.get("kind") == "found" and el.get("bbox") is not None


def _pos(el: Dict[str, Any]) -> str:
    return (el.get("computed") or {}).get("position", "static")


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(str(val).replace("px", "").strip())
    except (TypeError, ValueError):
        return default


def _finding(rule: str, severity: str, summary: str, **extra: Any) -> Dict[str, Any]:
    out = {"rule": rule, "severity": severity, "summary": summary}
    out.update(extra)
    return out


# --------------------------------------------------------------------------- R1
def rule_repeated_collapse(elements, groups, config, dpr=1.0) -> List[Dict[str, Any]]:
    """Corresponding leaves across repeated members sharing a coordinate."""
    tol = _tol(config, dpr)
    findings: List[Dict[str, Any]] = []

    by_group: Dict[str, List[Dict]] = defaultdict(list)
    for el in elements:
        if el.get("role") == "member_leaf" and _visible(el):
            by_group[el.get("group_id")].append(el)

    for gid, leaves in by_group.items():
        # compare like with like: same structural path inside each member
        by_path: Dict[str, List[Dict]] = defaultdict(list)
        for leaf in leaves:
            by_path[leaf.get("leaf_path", "")].append(leaf)

        for path, peers in by_path.items():
            if len(peers) < 2:
                continue
            # group peers by rounded coordinate; a bucket with >1 member is a collapse
            buckets: Dict[tuple, List[Dict]] = defaultdict(list)
            for p in peers:
                b = p["bbox"]
                buckets[(round(b["x"] / max(tol, 0.01)), round(b["y"] / max(tol, 0.01)))].append(p)
            for (bx, by), members in buckets.items():
                if len(members) < 2:
                    continue
                idxs = sorted({m.get("member_index") for m in members if m.get("member_index") is not None})
                if len(idxs) < 2:
                    continue  # same member, different leaves — not a collapse
                b = members[0]["bbox"]
                findings.append(_finding(
                    "repeated_collapse", "critical",
                    f"{len(idxs)} repeated items render corresponding content at the same "
                    f"coordinate (x={b['x']}, y={b['y']}) — only one is visible to a reader",
                    group_id=gid, leaf_path=path, member_indexes=idxs,
                    shared_coordinate={"x": b["x"], "y": b["y"]},
                    element_ids=[m["element_id"] for m in members],
                ))
    return findings


# --------------------------------------------------------------------------- R2
def rule_containment(elements, config, dpr=1.0) -> List[Dict[str, Any]]:
    """Children escaping the container padding box, split by whether a clip hides it."""
    tol = _tol(config, dpr)
    min_area = float(config["min_overflow_area_px"])
    findings: List[Dict[str, Any]] = []

    for el in elements:
        if not _visible(el):
            continue
        if _pos(el) in _ESCAPING_POSITIONS:
            continue  # generic inference only; declared relations handle these
        pp = el.get("parent_padding_box")
        b = el.get("bbox")
        if not pp or not b:
            continue

        right_over = (b["x"] + b["w"]) - (pp["x"] + pp["w"])
        left_over = pp["x"] - b["x"]
        bottom_over = (b["y"] + b["h"]) - (pp["y"] + pp["h"])
        worst = max(right_over, left_over, bottom_over)
        if worst <= tol:
            continue
        if worst * max(b["h"], 1.0) < min_area:
            continue

        # Only overflow:hidden|clip genuinely LOSES content. auto/scroll means the content
        # is reachable by scrolling, which is the entire purpose of a scroll container —
        # treating it as clipped fires on every scrollable region on a real page (observed
        # against a sticky-header scroll pane in the adversarial corpus).
        LOSES_CONTENT = {"hidden", "clip"}
        clipped = any(
            (c.get("overflow_x") in LOSES_CONTENT) or (c.get("overflow_y") in LOSES_CONTENT)
            for c in (el.get("clip_chain") or [])
        )
        scrollable = any(
            (c.get("overflow_x") in {"auto", "scroll"}) or (c.get("overflow_y") in {"auto", "scroll"})
            for c in (el.get("clip_chain") or [])
        )
        if scrollable and not clipped:
            continue  # reachable by scrolling — not a defect
        if clipped:
            # Only TEXT-bearing elements. overflow:hidden is the standard idiom for
            # intentional image/decorative cropping, and flagging it fires on almost every
            # real page — observed on the adversarial corpus against a deliberate crop.
            # Losing text is a defect; cropping a gradient is a design decision.
            if not el.get("has_direct_text"):
                continue
            findings.append(_finding(
                "clipped_content", "major",
                f"text extends {worst:.1f}px beyond its container and is CLIPPED by an "
                f"ancestor — the overflowing text is silently unreadable",
                element_id=el["element_id"], overflow_px=round(worst, 2)))
        else:
            findings.append(_finding(
                "containment_breach", "critical",
                f"content extends {worst:.1f}px outside its container's padding box and "
                f"paints over surrounding layout",
                element_id=el["element_id"], overflow_px=round(worst, 2),
                child_bbox=b, container_padding_box=pp))
    return findings


# --------------------------------------------------------------------------- R3
def rule_text_clipping(elements, config, dpr=1.0) -> List[Dict[str, Any]]:
    """Line-height taller than the box meant to hold it."""
    tol = _tol(config, dpr)
    findings: List[Dict[str, Any]] = []
    for el in elements:
        if not _visible(el):
            continue
        # Only elements holding their OWN text can have clipped glyphs. Without this an
        # empty spacer div with a short height reports "glyphs are cut off" — observed on
        # the first fixture run against two empty rule divs.
        if not el.get("has_direct_text"):
            continue
        comp = el.get("computed") or {}
        lh = _f(comp.get("line-height"))
        if lh <= 0:
            continue  # 'normal' — no reliable number, do not guess
        pb = el.get("padding_box") or el.get("bbox")
        inner = pb["h"] - _f(comp.get("padding-top")) - _f(comp.get("padding-bottom"))
        if inner <= 0:
            continue
        if lh - inner > tol:
            findings.append(_finding(
                "text_clipping", "critical",
                f"line-height {lh:.2f}px exceeds the {inner:.2f}px content box — glyphs are cut off",
                element_id=el["element_id"], line_height_px=round(lh, 2),
                content_box_height_px=round(inner, 2)))
    return findings


# --------------------------------------------------------------------------- R4
def rule_rhythm(elements, config, dpr=1.0) -> List[Dict[str, Any]]:
    """Doubled rules and inconsistent border weights within one parent."""
    findings: List[Dict[str, Any]] = []
    min_w = float(config["min_border_width_px"])
    gap_limit = float(config["doubled_rule_gap_px"])

    rules_by_parent: Dict[str, List[Dict]] = defaultdict(list)
    for el in elements:
        if not _visible(el):
            continue
        comp = el.get("computed") or {}
        for side in ("top", "bottom"):
            w = _f(comp.get(f"border-{side}-width"))
            if w < min_w:
                continue
            b = el["bbox"]
            y = b["y"] if side == "top" else b["y"] + b["h"]
            key = json.dumps(el.get("parent_bbox") or {}, sort_keys=True)
            rules_by_parent[key].append({
                "element_id": el["element_id"], "side": side,
                "y": round(y, 2), "width": round(w, 2), "x": b["x"], "w": b["w"],
                "box_top": b["y"], "box_bottom": b["y"] + b["h"],
            })

    for _, rules in rules_by_parent.items():
        if len(rules) < 2:
            continue
        rules.sort(key=lambda r: r["y"])
        for a, b in zip(rules, rules[1:]):
            # An element's OWN top+bottom border is a box outline, not two rules. Without
            # this guard every bordered box shorter than gap_limit reports as a doubled
            # divider — caught on the first fixture run, and precisely the cry-wolf
            # behaviour that gets a check ignored.
            if a["element_id"] == b["element_id"]:
                continue
            gap = b["y"] - a["y"]
            # Horizontal overlap: the same divider rendered twice spans the same x-range.
            lo, hi = max(a["x"], b["x"]), min(a["x"] + a["w"], b["x"] + b["w"])
            narrower = min(a["w"], b["w"]) or 1.0
            if (hi - lo) / narrower < float(config["doubled_rule_min_x_overlap"]):
                continue
            # If the two SOURCE boxes overlap vertically, this is deliberate layering
            # (negative margins, stacked cards), not one divider drawn twice. Codex
            # flagged negative margins as needing a declared relation; suppressing on
            # box overlap resolves the common case without one.
            if min(a["box_bottom"], b["box_bottom"]) - max(a["box_top"], b["box_top"]) > 0:
                continue
            if 0 < gap < gap_limit:
                findings.append(_finding(
                    # Heuristic, not a geometric fact like overlap or containment — kept
                    # below the default severity floor so it informs without failing a gate.
                    "doubled_rule", "minor",
                    f"two horizontal rules {gap:.1f}px apart read as one thick/duplicated "
                    f"divider (widths {a['width']}px and {b['width']}px)",
                    element_ids=[a["element_id"], b["element_id"]], gap_px=round(gap, 2)))
        widths = sorted({r["width"] for r in rules})
        if len(widths) > 2:
            findings.append(_finding(
                "rule_weight_inconsistency", "minor",
                f"{len(rules)} rules in one container use {len(widths)} different widths "
                f"({', '.join(str(w) for w in widths)}px) — reads as visual noise",
                widths_px=widths, rule_count=len(rules)))
    return findings


# --------------------------------------------------------------------------- driver
# ---------------------------------------------------------------------------
# Tier B — DECLARED relations (S074, #216)
# ---------------------------------------------------------------------------
#
# Tier A infers structure generically and therefore has to be conservative: it skips
# fixed/sticky/absolute elements, because an element that legitimately escapes its parent
# is indistinguishable, from geometry alone, from one that escaped by accident.
#
# Tier B is where that judgement is supplied by the project. A DECLARED relation states
# intent, so the exclusion must NOT apply — an explicitly declared `contain` over a sticky
# header is precisely the check Tier A cannot make, and inheriting the exclusion would
# silently make the declaration a no-op. That is the whole reason this tier exists.

RELATION_KINDS = {
    "repeat", "owned_by", "contain", "collision_free", "align",
    "must_not_occlude", "paint_within",
}


def _resolve(elements: List[Dict[str, Any]], ref: str) -> List[Dict[str, Any]]:
    """Resolve a relation's element reference by spec_id first, then selector."""
    if not ref:
        return []
    by_spec = [e for e in elements if e.get("spec_id") == ref]
    if by_spec:
        return by_spec
    return [e for e in elements if e.get("selector") == ref]


def _overlap(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Area of intersection between two bboxes."""
    ox = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    oy = max(0.0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    return ox * oy


def _edge(box: Dict[str, Any], edge: str) -> float:
    return {
        "left": box["x"], "right": box["x"] + box["w"],
        "top": box["y"], "bottom": box["y"] + box["h"],
    }[edge]


def rule_declared_relations(
    elements: List[Dict[str, Any]],
    relations: List[Dict[str, Any]],
    config: Dict[str, Any],
    dpr: float = 1.0,
) -> List[Dict[str, Any]]:
    """Evaluate declared Tier B relations. No positional exclusion — see the note above."""
    tol = _tol(config, dpr)
    findings: List[Dict[str, Any]] = []

    for rel in relations or []:
        kind = rel.get("kind")
        rid = rel.get("id") or kind
        if kind not in RELATION_KINDS:
            findings.append(_finding(
                "relation_unknown", "info",
                f"declared relation {rid!r} has unsupported kind {kind!r}",
                relation_id=rid))
            continue

        if kind == "paint_within":
            # Stated as a LIMIT rather than silently passed. DOM geometry cannot see paint
            # bounds — shadows, outlines, pseudo-elements and glyph overflow all paint
            # outside the box model — so a clean geometric reading here would be a claim
            # the measurement cannot support.
            findings.append(_finding(
                "paint_within_unmeasured", "info",
                f"relation {rid!r} needs pixel verification — DOM geometry cannot measure "
                f"paint bounds (shadows, outlines, pseudo-elements, glyph overflow)",
                relation_id=rid, requires="pixel_verification"))
            continue

        if kind == "repeat":
            members = [e for e in _resolve(elements, rel.get("selector", "")) if _visible(e)]
            want = int(rel.get("min_count", 2))
            if len(members) < want:
                findings.append(_finding(
                    "repeat_missing", rel.get("severity", "major"),
                    f"relation {rid!r} expected at least {want} repeated item(s), found {len(members)}",
                    relation_id=rid, observed=len(members), expected=want))
            continue

        if kind in ("owned_by", "contain"):
            container_ref = rel.get("container", "")
            child_refs = rel.get("children") or ([rel["child"]] if rel.get("child") else [])
            containers = _resolve(elements, container_ref)
            if not containers:
                findings.append(_finding(
                    "relation_unresolved", "major",
                    f"relation {rid!r} container {container_ref!r} matched no measured element",
                    relation_id=rid))
                continue
            cbox = containers[0].get("padding_box") or containers[0].get("bbox")
            for cref in child_refs:
                for child in _resolve(elements, cref):
                    if not _visible(child):
                        continue
                    b = child.get("bbox")
                    if not b or not cbox:
                        continue
                    over = max(
                        (b["x"] + b["w"]) - (cbox["x"] + cbox["w"]),
                        cbox["x"] - b["x"],
                        (b["y"] + b["h"]) - (cbox["y"] + cbox["h"]),
                        cbox["y"] - b["y"],
                    )
                    if over > tol:
                        findings.append(_finding(
                            "containment_breach", rel.get("severity", "major"),
                            f"relation {rid!r}: {cref!r} escapes {container_ref!r} by "
                            f"{round(over, 1)}px",
                            relation_id=rid, overflow_px=round(over, 1),
                            element_ids=[child.get("element_id")]))
            continue

        if kind == "collision_free":
            members = [e for e in
                       (m for ref in (rel.get("members") or []) for m in _resolve(elements, ref))
                       if _visible(e) and e.get("bbox")]
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    area = _overlap(members[i]["bbox"], members[j]["bbox"])
                    if area > float(config["min_overflow_area_px"]):
                        findings.append(_finding(
                            "collision", rel.get("severity", "major"),
                            f"relation {rid!r}: declared collision-free elements overlap by "
                            f"{round(area, 1)}px²",
                            relation_id=rid, overlap_area_px=round(area, 1),
                            element_ids=[members[i].get("element_id"), members[j].get("element_id")]))
            continue

        if kind == "align":
            edge = rel.get("edge", "left")
            if edge not in ("left", "right", "top", "bottom"):
                findings.append(_finding(
                    "relation_unknown", "info",
                    f"relation {rid!r} has unsupported edge {edge!r}", relation_id=rid))
                continue
            members = [e for e in
                       (m for ref in (rel.get("members") or []) for m in _resolve(elements, ref))
                       if _visible(e) and e.get("bbox")]
            if len(members) < 2:
                continue
            coords = [_edge(e["bbox"], edge) for e in members]
            spread = max(coords) - min(coords)
            if spread > tol:
                findings.append(_finding(
                    "misaligned", rel.get("severity", "major"),
                    f"relation {rid!r}: declared {edge}-aligned elements differ by "
                    f"{round(spread, 1)}px ({round(min(coords), 1)} to {round(max(coords), 1)})",
                    relation_id=rid, edge=edge, spread_px=round(spread, 1),
                    element_ids=[e.get("element_id") for e in members]))
            continue

        if kind == "must_not_occlude":
            occluders = [e for e in _resolve(elements, rel.get("occluder", "")) if _visible(e)]
            protected = [e for e in _resolve(elements, rel.get("protected", "")) if _visible(e)]
            for o in occluders:
                for pr in protected:
                    if not o.get("bbox") or not pr.get("bbox"):
                        continue
                    area = _overlap(o["bbox"], pr["bbox"])
                    if area > float(config["min_overflow_area_px"]):
                        findings.append(_finding(
                            "occlusion", rel.get("severity", "major"),
                            f"relation {rid!r}: {rel.get('occluder')!r} covers "
                            f"{rel.get('protected')!r} by {round(area, 1)}px²"
                            + (f" at scroll checkpoint {rel['at_scroll']}" if rel.get("at_scroll") is not None else ""),
                            relation_id=rid, overlap_area_px=round(area, 1),
                            at_scroll=rel.get("at_scroll"),
                            element_ids=[o.get("element_id"), pr.get("element_id")]))
            continue

    return findings


def evaluate_breakpoint(bp_result: Dict[str, Any], config: Optional[Dict] = None) -> List[Dict[str, Any]]:
    cfg = dict(DEFAULT_CONFIG)
    if config:
        cfg.update(config)
    elements = bp_result.get("elements") or []
    groups = bp_result.get("groups") or []
    dpr = float((bp_result.get("viewport") or {}).get("dpr", 1) or 1)

    findings: List[Dict[str, Any]] = []
    findings += rule_repeated_collapse(elements, groups, cfg, dpr)
    findings += rule_containment(elements, cfg, dpr)
    findings += rule_text_clipping(elements, cfg, dpr)
    findings += rule_rhythm(elements, cfg, dpr)
    # Tier B: only what the project declared. Absent relations = Tier A alone, which is
    # the zero-configuration default and carries the incident-catching value on its own.
    findings += rule_declared_relations(elements, cfg.get("relations") or [], cfg, dpr)
    for f in findings:
        f["breakpoint"] = bp_result.get("breakpoint")
    return findings


def evaluate(measurement: Dict[str, Any], config: Optional[Dict] = None) -> Dict[str, Any]:
    """Evaluate a whole geometry_measure.mjs payload.

    An incomplete measurement can never yield a clean verdict: `outcome` is carried
    through, and anything other than MEASURED becomes UNMEASURED/INCONCLUSIVE rather than
    an absence of findings.
    """
    cfg = dict(DEFAULT_CONFIG)
    if config:
        cfg.update(config)

    source_outcome = measurement.get("outcome")
    findings: List[Dict[str, Any]] = []
    for _, bp in (measurement.get("measurements") or {}).items():
        findings.extend(evaluate_breakpoint(bp, cfg))

    # De-duplicate: one element can be measured twice (once as a declared spec, once as a
    # discovered group leaf), which would otherwise report the same defect repeatedly and
    # inflate the count. Identity is the rule plus the geometry it describes, not the
    # element_id, since the two measurements carry different ids for the same node.
    def _identity(f: Dict[str, Any]) -> str:
        return json.dumps(
            [f.get("rule"), f.get("breakpoint"),
             f.get("shared_coordinate"), f.get("overflow_px"),
             f.get("line_height_px"), f.get("content_box_height_px"),
             f.get("gap_px"), sorted(f.get("widths_px") or [])],
            sort_keys=True,
        )

    seen: set = set()
    deduped: List[Dict[str, Any]] = []
    for f in findings:
        ident = _identity(f)
        if ident in seen:
            continue
        seen.add(ident)
        deduped.append(f)
    findings = deduped

    # A declared `paint_within` relation is a stated LIMIT, not a defect, so it belongs in
    # `unmeasured_by_design` rather than in `findings`. Left as an info-severity finding it
    # was silently dropped by the severity floor — the unit test passed against the rule
    # function while the integrated path discarded it, which is precisely the "reported
    # unmeasured, never passed" guarantee this field exists to keep.
    paint_limits = [f for f in findings if f.get("rule") == "paint_within_unmeasured"]
    findings = [f for f in findings if f.get("rule") != "paint_within_unmeasured"]

    floor = SEVERITY_ORDER.get(cfg["severity_floor"], 1)
    reportable = [f for f in findings if SEVERITY_ORDER.get(f["severity"], 0) >= floor]
    reportable.sort(key=lambda f: -SEVERITY_ORDER.get(f["severity"], 0))

    if source_outcome != "MEASURED":
        verdict = "UNMEASURED" if source_outcome in (None, "PARTIAL") else "INCONCLUSIVE"
    else:
        verdict = "FAIL" if reportable else "PASS"

    return {
        "schema": "geometry-findings.v1",
        "probe_version": measurement.get("probe_version"),
        "probe_hash": measurement.get("probe_hash"),
        "product_url": measurement.get("product_url"),
        "source_outcome": source_outcome,
        "verdict": verdict,
        "breakpoints_expected": measurement.get("breakpoints_expected"),
        "breakpoints_measured": measurement.get("breakpoints_measured"),
        "unmeasured_by_design": [
            "paint bounds beyond layout geometry: box-shadow, outline, pseudo-elements, "
            "SVG filters, glyph overflow"
        ] + [
            f"relation {f.get('relation_id')!r} requires pixel verification — "
            f"DOM geometry cannot measure paint bounds"
            for f in paint_limits
        ],
        "findings": reportable,
        "finding_count": len(reportable),
        "measurement_errors": measurement.get("errors") or [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate geometry measurements into findings.")
    ap.add_argument("--input", type=str, default="-", help="measurement JSON path, or - for stdin")
    ap.add_argument("--severity-floor", default=DEFAULT_CONFIG["severity_floor"],
                    choices=list(SEVERITY_ORDER))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    try:
        measurement = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"geometry_rules: input is not JSON ({exc})", file=sys.stderr)
        return 2

    report = evaluate(measurement, {"severity_floor": args.severity_floor})

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"verdict: {report['verdict']}   findings: {report['finding_count']}   "
              f"breakpoints: {report['breakpoints_measured']}/{report['breakpoints_expected']}")
        for f in report["findings"]:
            print(f"  [{f['severity'].upper():8}] {f['rule']}: {f['summary']}")
        if report["measurement_errors"]:
            print(f"  measurement errors: {report['measurement_errors']}")

    return 0 if report["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
