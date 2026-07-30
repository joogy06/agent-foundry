#!/usr/bin/env python3
"""validate_extraction.py — S074. Prove an extraction before it reaches the books.

Extracted financial data is untrusted until it passes these checks. An OCR or table-parse
error does not announce itself: a transposed digit, a dropped minus sign or a missed page
produces a clean-looking row that is simply false. Plausibility is not evidence.

The strongest check available is V1, running-balance continuity: where a statement carries
a running balance, arithmetic PROVES the extraction line by line. Nothing else comes close.
Where there is no running balance the tool says so, because a materially weaker result must
not read like a stronger one.

Input is JSON on --rows: a list of objects with
    date (ISO), description, amount (signed: negative = money out), balance (optional)
Money is parsed to integer PENCE — never float. 0.1 + 0.2 != 0.3 matters when the output
is a tax figure.

Exit codes (house convention):
    0 — every applicable check passed
    2 — at least one check failed (do NOT post)
    3 — input unreadable
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional


def to_pence(value: Any) -> Optional[int]:
    """Money as integer pence. Floats are never used for money."""
    if value is None or value == "":
        return None
    try:
        return int((Decimal(str(value).replace(",", "").replace("£", "").strip()) * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        return None


def fmt(p: Optional[int]) -> str:
    return "—" if p is None else f"£{p / 100:,.2f}"


def check_continuity(rows: List[Dict]) -> Dict[str, Any]:
    """V1 — each balance equals the previous balance plus the movement."""
    balances = [to_pence(r.get("balance")) for r in rows]
    if sum(b is not None for b in balances) < 2:
        return {
            "check": "V1_running_balance", "status": "NOT_APPLICABLE",
            "detail": ("no running balance in this extraction — the strongest available proof "
                       "could not be run, so confidence is materially lower and must be recorded as such"),
        }
    breaks = []
    for i in range(1, len(rows)):
        prev, cur, amt = balances[i - 1], balances[i], to_pence(rows[i].get("amount"))
        if prev is None or cur is None or amt is None:
            continue
        if prev + amt != cur:
            breaks.append({
                "row": i, "date": rows[i].get("date"),
                "expected": fmt(prev + amt), "found": fmt(cur),
                "discrepancy": fmt(cur - (prev + amt)),
            })
    return {
        "check": "V1_running_balance",
        "status": "PASS" if not breaks else "FAIL",
        "breaks": breaks[:20],
        "break_count": len(breaks),
    }


def check_endpoints(rows: List[Dict], opening: Optional[int], closing: Optional[int]) -> Dict[str, Any]:
    """V2 — the extraction reconciles to the statement's own header/footer figures.

    This is what catches a MISSED PAGE, which every per-line check passes happily.
    """
    if opening is None and closing is None:
        return {"check": "V2_endpoints", "status": "NOT_APPLICABLE",
                "detail": "no opening/closing balance supplied — a missed page cannot be excluded"}
    movement = sum(p for p in (to_pence(r.get("amount")) for r in rows) if p is not None)
    problems = []
    if opening is not None and closing is not None:
        if opening + movement != closing:
            problems.append({
                "expected_closing": fmt(opening + movement), "stated_closing": fmt(closing),
                "discrepancy": fmt(closing - (opening + movement)),
                "meaning": "extracted movement does not span opening to closing — suspect a missing page or dropped rows",
            })
    return {"check": "V2_endpoints", "status": "PASS" if not problems else "FAIL",
            "movement": fmt(movement), "problems": problems}


def check_invoice_arithmetic(rows: List[Dict]) -> Dict[str, Any]:
    """V6 — net + VAT = gross, on rows that carry invoice fields."""
    bad, checked = [], 0
    for i, r in enumerate(rows):
        net, vat, gross = to_pence(r.get("net")), to_pence(r.get("vat")), to_pence(r.get("gross"))
        if net is None or vat is None or gross is None:
            continue
        checked += 1
        if net + vat != gross:
            bad.append({"row": i, "ref": r.get("reference") or r.get("description"),
                        "net": fmt(net), "vat": fmt(vat), "gross": fmt(gross),
                        "expected_gross": fmt(net + vat)})
    if not checked:
        return {"check": "V6_invoice_arithmetic", "status": "NOT_APPLICABLE",
                "detail": "no rows carried net/vat/gross"}
    return {"check": "V6_invoice_arithmetic", "status": "PASS" if not bad else "FAIL",
            "rows_checked": checked, "failures": bad[:20]}


def check_duplicates(rows: List[Dict]) -> Dict[str, Any]:
    """V7 — consecutive statements repeat boundary transactions."""
    keys = Counter(
        (r.get("date"), to_pence(r.get("amount")), (r.get("description") or "").strip().lower()[:60])
        for r in rows
    )
    dups = [{"date": k[0], "amount": fmt(k[1]), "description": k[2], "occurrences": n}
            for k, n in keys.items() if n > 1]
    return {"check": "V7_duplicates",
            "status": "PASS" if not dups else "REVIEW",
            "detail": ("repeated date+amount+description. Legitimate for genuine repeat payments; "
                       "a period-boundary overlap is a double-post. Confirm each."),
            "candidates": dups[:20], "candidate_count": len(dups)}


def validate(rows: List[Dict], opening: Optional[int], closing: Optional[int]) -> Dict[str, Any]:
    checks = [check_continuity(rows), check_endpoints(rows, opening, closing),
              check_invoice_arithmetic(rows), check_duplicates(rows)]
    failed = [c for c in checks if c["status"] == "FAIL"]
    review = [c for c in checks if c["status"] == "REVIEW"]
    na = [c for c in checks if c["status"] == "NOT_APPLICABLE"]

    if failed:
        outcome = "REJECTED"
    elif review:
        outcome = "NEEDS_REVIEW"
    elif na and len(na) == len(checks):
        outcome = "UNVALIDATED"
    else:
        outcome = "ACCEPTED"

    return {
        "schema": "extraction-validation.v1",
        "row_count": len(rows),
        "outcome": outcome,
        "postable": outcome == "ACCEPTED",
        "checks": checks,
        "note": ("ACCEPTED means the arithmetic holds, not that the extraction is true to the "
                 "document. NOT_APPLICABLE checks are stated, never treated as passes."),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Validate extracted financial rows before posting.")
    ap.add_argument("--rows", type=Path, required=True, help="JSON list of extracted rows")
    ap.add_argument("--opening", help="opening balance per the statement")
    ap.add_argument("--closing", help="closing balance per the statement")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        rows = json.loads(args.rows.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("--rows must contain a JSON list")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        sys.stderr.write(f"EXTRACTION_ENV_ERROR: {exc}\n")
        return 3

    result = validate(rows, to_pence(args.opening), to_pence(args.closing))

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"EXTRACTION {result['outcome']}: {result['row_count']} row(s), "
              f"postable={result['postable']}")
        for c in result["checks"]:
            print(f"  {c['status']:<15} {c['check']}")
            if c.get("break_count"):
                print(f"      {c['break_count']} continuity break(s); first: {c['breaks'][0]}")
            for p in c.get("problems", [])[:2]:
                print(f"      {p}")
            if c.get("candidate_count"):
                print(f"      {c['candidate_count']} duplicate candidate(s)")
            if c["status"] == "NOT_APPLICABLE":
                print(f"      {c['detail']}")
    return 0 if result["outcome"] in ("ACCEPTED",) else 2


if __name__ == "__main__":
    sys.exit(main())
