#!/usr/bin/env python3
"""effort_rollup.py -- READ-ONLY pass@1 by (grade, effort) over the Claude dispatch rows (#311).

Design docs/plans/2026-09-24-adaptive-effort-design.md s3.5, the calibration MVP. Reads the
`tool: "claude_dispatch"` rows effort_policy.py appends to
`<project_root>/.process-observations/spawn-runs.jsonl`, joins each dispatch row to its outcome row
by `dispatch_id`, and prints, per (grade, effort_requested) cell, how many FIRST attempts
(`attempt == 1`) reached COMPLETE. A cell with fewer than MIN_N joined first attempts is reported
as `insufficient`: it shows its counts but no rate. It makes NO proposals in phase 1 -- turning
these numbers into a policy change is a later, human-approved edit (design s5).

#313: an outcome whose needs_kind is `clarification` is a QUESTION, not an attempt -- it is counted
apart (`clarifications`) and never enters a pass@1 cell. `d21_review` rows (effort_policy.py
record-d21-review / admit-fix-round) are summarised per review identity: rounds used, the last disposition, and whether the
loop converged or merely stopped.

Writes nothing. A line that is not JSON, or a row that is not a claude_dispatch row, is skipped
and counted. A dispatch with no outcome yet is `open` and stays out of the rate.

    effort_rollup.py [--project-root PATH] [--json]

Also exports `claude_spawn_counts(rows)` -- (graded, total) Claude dispatches -- which the
SessionStart digest (freshness_nudge.py) uses for its "graded N/M Claude spawns" ratio.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

TOOL = "claude_dispatch"
PHASE_DISPATCH, PHASE_OUTCOME = "dispatch", "outcome"
GRADED_SOURCES = frozenset({"grade", "promotion"})
MIN_N = 30
SPAWN_RUNS = Path(".process-observations") / "spawn-runs.jsonl"
UNGRADED = "-"


def read_rows(path: Path) -> Tuple[List[Dict[str, Any]], int]:
    """(rows, skipped): every JSON object line; skipped counts lines that are not one. A line that
    is not UTF-8 is skipped and counted, never read with errors=replace (#313 round 3 item 8)."""
    rows: List[Dict[str, Any]] = []
    skipped = 0
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return rows, skipped
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            skipped += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            skipped += 1
    return rows, skipped


OUTCOME_REFUSED = "REFUSED"
NEEDS_CLARIFICATION = "clarification"
D21_TOOL = "d21_review"


def claude_spawn_counts(rows: Iterable[Dict[str, Any]]) -> Tuple[int, int]:
    """(graded, total) over Claude DISPATCH rows: graded = effort chosen from a WP grade. A
    dispatch whose outcome is REFUSED never spawned, so it is in neither count (fix round 1 m2)."""
    rows = list(rows)
    refused = {r.get("dispatch_id") for r in rows
               if r.get("tool") == TOOL and r.get("phase") == PHASE_OUTCOME and r.get("status") == OUTCOME_REFUSED}
    graded = total = 0
    for r in rows:
        if r.get("tool") == TOOL and r.get("phase") == PHASE_DISPATCH and r.get("dispatch_id") not in refused:
            total += 1
            if r.get("effort_source") in GRADED_SOURCES:
                graded += 1
    return graded, total


def rollup(rows: Iterable[Dict[str, Any]], min_n: int = MIN_N) -> Dict[str, Any]:
    dispatches: Dict[str, Dict[str, Any]] = {}
    outcomes: Dict[str, Dict[str, Any]] = {}
    other = 0
    d21: Dict[str, List[Dict[str, Any]]] = {}
    rows = list(rows)
    # fix round 2 item 4: a fix-round dispatch whose admission no admit-fix-round issued.
    admissions = {r.get("admission_id") for r in rows if r.get("tool") == D21_TOOL and r.get("kind") == "admitted"}
    unbound = sorted({r.get("dispatch_id") for r in rows
                      if r.get("tool") == TOOL and r.get("phase") == PHASE_DISPATCH
                      and r.get("dispatch_kind") == "fix-round" and r.get("fix_admission_id") not in admissions})
    # #313 round 3 item 4: outcome rows must agree with their dispatch row, name only issued
    # admissions, and no admission may bind more than one dispatch.
    disp_rows = {r.get("dispatch_id"): r for r in rows if r.get("tool") == TOOL and r.get("phase") == PHASE_DISPATCH}
    outcomes_ = [r for r in rows if r.get("tool") == TOOL and r.get("phase") == PHASE_OUTCOME]
    mismatched = sorted({o.get("dispatch_id") for o in outcomes_ if o.get("dispatch_id") in disp_rows and
                         (o.get("dispatch_kind"), o.get("fix_admission_id")) !=
                         (disp_rows[o["dispatch_id"]].get("dispatch_kind"), disp_rows[o["dispatch_id"]].get("fix_admission_id"))})
    unissued = sorted({o.get("dispatch_id") for o in outcomes_
                       if o.get("fix_admission_id") is not None and o.get("fix_admission_id") not in admissions})
    bound_to: Dict[str, set] = {}
    for r in rows:
        if r.get("tool") == TOOL and r.get("phase") == PHASE_DISPATCH and r.get("fix_admission_id"):
            bound_to.setdefault(r["fix_admission_id"], set()).add(r.get("dispatch_id"))
    multiply = sorted(a for a, ds in bound_to.items() if len(ds) > 1)
    for r in rows:
        if r.get("tool") == D21_TOOL:
            rid = r.get("review_id")
            if isinstance(rid, str):                       # a legacy `<anchor>:<path>` id is the same loop
                d21.setdefault((rid.split(":", 1)[1] if ":" in rid else rid).lower(), []).append(r)
            continue
        if r.get("tool") != TOOL:
            other += 1
            continue
        did = r.get("dispatch_id")
        if not isinstance(did, str):
            continue
        if r.get("phase") == PHASE_DISPATCH:
            dispatches.setdefault(did, r)          # first write wins; a duplicate is ignored
        elif r.get("phase") == PHASE_OUTCOME:
            outcomes[did] = r                      # the latest outcome for a dispatch
    cells: Dict[Tuple[str, str], Dict[str, int]] = {}
    by_source: Dict[str, int] = {}
    open_ = retries = refused = mismatches = clarifications = 0
    for did, d in dispatches.items():
        by_source[str(d.get("effort_source"))] = by_source.get(str(d.get("effort_source")), 0) + 1
        o = outcomes.get(did)
        if o is not None and o.get("attempt") != d.get("attempt"):
            mismatches += 1        # m1: the two halves disagree on which attempt this was
            continue
        if o is not None and o.get("status") == OUTCOME_REFUSED:
            refused += 1           # m2: nothing ran; neither a pass nor a fail
            continue
        if o is not None and o.get("needs_kind") == NEEDS_CLARIFICATION:
            clarifications += 1    # #313: a question, never an execution attempt
            continue
        if d.get("attempt") != 1:
            retries += 1
            continue
        if o is None:
            open_ += 1
            continue
        key = (str(d.get("grade") or UNGRADED), str(d.get("effort_requested") or "inherit"))
        c = cells.setdefault(key, {"n": 0, "pass": 0})
        c["n"] += 1
        c["pass"] += 1 if o.get("status") == "COMPLETE" else 0
    out_cells = []
    for (grade, effort) in sorted(cells):
        c = cells[(grade, effort)]
        enough = c["n"] >= min_n
        out_cells.append({"grade": grade, "effort": effort, "n": c["n"], "pass": c["pass"],
                          "pass_at_1": round(c["pass"] / c["n"], 4) if enough else None,
                          "status": "ok" if enough else "insufficient"})
    return {"schema": "effort-rollup.v1", "min_n": min_n, "cells": out_cells,
            "dispatches": len(dispatches), "open": open_, "retries": retries, "refused": refused,
            "attempt_mismatches": mismatches, "clarifications": clarifications,
            "d21_reviews": _d21_summary(d21), "unbound_fix_dispatches": unbound,
            "outcome_binding_mismatches": mismatched, "unissued_outcome_admissions": unissued,
            "multiply_bound_admissions": multiply,
            "orphan_outcomes": sum(1 for did in outcomes if did not in dispatches),
            "by_effort_source": dict(sorted(by_source.items())), "other_rows": other,
            "proposals": []}


def _d21_summary(by_review: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Per review identity: reviews recorded, automatic and user fix rounds admitted, the last
    disposition, bound hit. `converged` only when the last review says so; a loop that merely
    stopped did not converge."""
    out = []
    for rid in sorted(by_review):
        rs = by_review[rid]
        reviews = [r for r in rs if r.get("kind") == "review"]
        admitted = [r for r in rs if r.get("kind") == "admitted"]
        user = [r for r in admitted if r.get("user_directed") is True]
        last = reviews[-1].get("disposition") if reviews else None
        out.append({"review_id": rid, "reviews": len(reviews), "fix_rounds": len(admitted) - len(user),
                    "user_rounds": len(user), "user_refs": [r.get("user_ref") for r in user],
                    "disposition": last,
                    "bound_hit": any(r.get("bound_hit") for r in reviews),
                    "converged": last == "converged"})
    return out


def render(doc: Dict[str, Any]) -> str:
    lines = [f"Claude dispatch pass@1 by (grade, effort) -- read-only; cells with n < {doc['min_n']} "
             f"are insufficient; no proposals (phase 1)"]
    if not doc["cells"]:
        lines.append("  no joined first attempts yet")
    for c in doc["cells"]:
        rate = f"{c['pass_at_1']:.2f}" if c["pass_at_1"] is not None else "insufficient"
        lines.append(f"  grade {c['grade']:<3} effort {c['effort']:<8} n={c['n']:<4} pass={c['pass']:<4} pass@1={rate}")
    lines.append(f"  dispatches={doc['dispatches']} open={doc['open']} retries={doc['retries']} "
                 f"refused={doc['refused']} attempt_mismatches={doc['attempt_mismatches']} "
                 f"orphan_outcomes={doc['orphan_outcomes']} clarifications={doc['clarifications']} "
                 f"sources={doc['by_effort_source']}")
    for key in ("outcome_binding_mismatches", "unissued_outcome_admissions", "multiply_bound_admissions"):
        if doc.get(key):
            lines.append(f"  {key}: {doc[key]}")
    if doc.get("unbound_fix_dispatches"):
        lines.append(f"  UNBOUND fix-round dispatches (no issued admission): {doc['unbound_fix_dispatches']}")
    for c in doc.get("d21_reviews", []):
        lines.append(f"  d21 {c['review_id']}: reviews={c['reviews']} fix_rounds={c['fix_rounds']} "
                     f"disposition={c['disposition']} bound_hit={c['bound_hit']}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="effort_rollup.py", description=__doc__.splitlines()[0])
    p.add_argument("--project-root", default=".")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    # fix round 2 item 7: ONE resolver -- the store effort_policy writes (the git toplevel).
    from effort_policy import store_path  # noqa: E402  (lazy: freshness_nudge imports this module)
    rows, skipped = read_rows(store_path(a.project_root))
    doc = rollup(rows)
    doc["skipped_lines"] = skipped
    text = render(doc)
    if skipped:
        text += f"\n  skipped_lines={skipped} (not JSON: corrupt or truncated; the admits refuse on them)"
    print(json.dumps(doc, sort_keys=True) if a.json else text)
    return 0


if __name__ == "__main__":
    from portable_cli import run_cli  # noqa: E402  (#251 stream hardening)

    sys.exit(run_cli(main))
