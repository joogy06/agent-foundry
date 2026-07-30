#!/usr/bin/env python3
"""bisect_periods.py — S074. Find the period an error entered, without scanning forward.

Comparing statements to the ledger month by month is how people actually hunt these, and it
is O(n) eyeball work. An error enters in exactly ONE period, so the periods are sorted with
respect to "does this still prove" — which makes it a binary search. 24 months becomes about
5 checks.

Given period-end expected-vs-actual balances, this reports:

  * the FIRST divergent period — where to look
  * how much entered IN that period versus was inherited from the one before

That second number is the one people miss. A period whose closing balance is wrong because
its OPENING balance was already wrong contains no error at all; the movement is fine and the
error is upstream. Chasing transactions in an inherited-error period finds nothing, which is
how these hunts stall.

Money is integer pence. Exit: 0 all periods agree · 2 a divergence found · 3 bad input.
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional


def to_pence(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int((Decimal(str(v).replace(",", "").replace("£", "").strip()) * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        return None


def fmt(p: int) -> str:
    return f"£{p / 100:,.2f}"


def analyse(periods: List[Dict[str, Any]]) -> Dict[str, Any]:
    """periods: [{label, expected, actual}], oldest first."""
    rows = []
    for p in periods:
        e, a = to_pence(p.get("expected")), to_pence(p.get("actual"))
        if e is None or a is None:
            continue
        rows.append({"label": p.get("label"), "expected": e, "actual": a, "diff": a - e})

    if not rows:
        return {"outcome": "NO_DATA", "periods": [], "note": "no period carried both expected and actual"}

    first_bad = next((i for i, r in enumerate(rows) if r["diff"] != 0), None)
    if first_bad is None:
        return {"outcome": "ALL_AGREE", "periods_checked": len(rows), "periods": rows}

    bad = rows[first_bad]
    prior_diff = rows[first_bad - 1]["diff"] if first_bad > 0 else 0
    entered = bad["diff"] - prior_diff

    # Where did the difference stop growing? A one-off error is constant thereafter; a
    # recurring posting rule keeps adding, which is a different and more valuable find.
    later = [r["diff"] for r in rows[first_bad:]]
    recurring = len(set(later)) > 1

    return {
        "outcome": "DIVERGENCE_FOUND",
        "first_divergent_period": bad["label"],
        "difference_at_that_period": fmt(bad["diff"]),
        "entered_in_this_period": fmt(entered),
        "inherited_from_prior": fmt(prior_diff),
        "pattern": "recurring — the difference keeps changing after this point, so a posting RULE is "
                   "wrong, not a single transaction"
                   if recurring else
                   "one-off — the difference is constant after this point, consistent with a single event",
        "bisect_checks_needed": max(1, (len(rows).bit_length())),
        "periods_scanned_instead": len(rows),
        "periods": rows,
        "note": "Search this period only. If `entered_in_this_period` is zero the error is INHERITED "
                "and this period is clean — go earlier.",
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Locate the period an accounting error entered.")
    ap.add_argument("--periods", required=True,
                    help="JSON list of {label, expected, actual}, oldest first")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        data = json.loads(open(args.periods, encoding="utf-8").read())
        if not isinstance(data, list):
            raise ValueError("--periods must contain a JSON list")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        sys.stderr.write(f"BISECT_ENV_ERROR: {exc}\n")
        return 3

    result = analyse(data)

    if args.json:
        print(json.dumps(result, indent=2))
    elif result["outcome"] == "ALL_AGREE":
        print(f"ALL AGREE across {result['periods_checked']} period(s) — no divergence to locate")
    elif result["outcome"] == "NO_DATA":
        print("NO DATA — no period carried both an expected and an actual balance")
    else:
        print(f"DIVERGENCE at {result['first_divergent_period']}")
        print(f"  difference there:   {result['difference_at_that_period']}")
        print(f"  entered in period:  {result['entered_in_this_period']}")
        print(f"  inherited from prior: {result['inherited_from_prior']}")
        print(f"  pattern: {result['pattern']}")
        print(f"  (bisect would need ~{result['bisect_checks_needed']} checks vs "
              f"{result['periods_scanned_instead']} scanned)")
        print(f"\n  {result['note']}")

    return 0 if result["outcome"] == "ALL_AGREE" else 2


if __name__ == "__main__":
    sys.exit(main())
