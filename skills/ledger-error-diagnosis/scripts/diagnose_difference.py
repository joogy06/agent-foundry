#!/usr/bin/env python3
"""diagnose_difference.py — S074. Read an unexplained difference and name the candidates.

The difference itself narrows the error class before you look at a single transaction.
This runs the classic arithmetic tests — divisible by 9, exactly twice a real amount,
equal to a real amount, sub-pound, suspiciously round, a VAT fraction — and returns the
candidate classes ranked, each with the check that would confirm or kill it.

It SUGGESTS. It never concludes, and it deliberately cannot correct anything. A candidate
is a hypothesis to test against a source document, and every one of these signatures has
innocent explanations: a genuine repeat payment looks exactly like a duplicate, and a
round number is sometimes just a round invoice.

Money is integer pence throughout. Using floats to diagnose rounding errors would be its
own joke.

Exit codes: 0 candidates found, OR a zero difference · 2 a real difference no signature
explains (still real — narrow it by hand per §2) · 3 bad input.
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


def diagnose(diff_p: int, amounts_p: Optional[List[int]] = None) -> Dict[str, Any]:
    amounts_p = amounts_p or []
    a = abs(diff_p)
    out: List[Dict[str, str]] = []

    if a == 0:
        return {"difference": fmt(diff_p), "candidates": [],
                "note": "no difference — nothing to diagnose"}

    # Transposition / digit slide. Any digit swap leaves a multiple of 9.
    if a % 9 == 0:
        out.append({
            "class": "transposition_or_digit_slide",
            "confidence": "high",
            "why": f"{fmt(a)} is divisible by 9 — the signature of swapped digits (54 keyed as 45) "
                   f"or a slid decimal (100 as 1,000)",
            "check": f"search for an entry near {fmt(a // 9 * 10)} whose digits could transpose; "
                     f"compare each posted amount against its source document",
        })

    # Wrong side: the entry is out by twice its value.
    if a % 2 == 0:
        half = a // 2
        hit = half in amounts_p
        out.append({
            "class": "wrong_side_or_sign",
            "confidence": "high" if hit else "medium",
            "why": f"{fmt(a)} is exactly twice {fmt(half)}"
                   + (" — and a transaction of that amount EXISTS in the supplied list" if hit
                      else " — a debit posted as a credit is out by twice its value"),
            "check": f"look for a {fmt(half)} entry posted to the wrong side, or a refund booked as a cost",
        })

    # Missing or duplicated: the difference IS a transaction.
    if a in amounts_p:
        out.append({
            "class": "missing_or_duplicated_transaction",
            "confidence": "high",
            "why": f"a transaction of exactly {fmt(a)} exists in the supplied list",
            "check": "confirm against the source document whether it was posted once, twice, or not "
                     "at all. Genuine repeat payments look identical to duplicates — check the document",
        })

    # Rounding / FX.
    if a < 100:
        out.append({
            "class": "rounding_or_fx",
            "confidence": "high",
            "why": f"{fmt(a)} is under £1 — accumulated rounding, recomputed VAT, or an FX rate difference",
            "check": "check whether VAT was recomputed from net instead of read from the invoice, and "
                     "whether any line is in a foreign currency",
        })

    # Suspiciously round.
    if a >= 10000 and a % 10000 == 0:
        out.append({
            "class": "missing_whole_transaction",
            "confidence": "medium",
            "why": f"{fmt(a)} is a round amount — real invoices rarely are, estimates and transfers are",
            "check": "look for an unposted transfer, a standing order, or a round-sum accrual",
        })

    # VAT fractions: gross treated as net (1/6 of gross at 20%), or the 20% itself.
    for div, label in ((6, "1/6 of a gross amount — the VAT fraction at 20%"),
                       (5, "1/5 of a net amount — VAT at 20% omitted or double-counted")):
        if a % div == 0:
            out.append({
                "class": "vat_treatment",
                "confidence": "low",
                "why": f"{fmt(a)} is divisible by {div} — {label}",
                "check": "check whether a gross amount was posted as net, or a standard-rated item "
                         "treated as zero-rated (weak signal on its own — confirm against the invoice)",
            })
            break

    rank = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda c: rank.get(c["confidence"], 3))
    return {
        "difference": fmt(diff_p),
        "difference_pence": diff_p,
        "candidates": out,
        "note": "Candidates are HYPOTHESES ranked by signature strength, not findings. Every one has "
                "innocent explanations; confirm each against a source document before correcting. "
                "This tool cannot and must not correct anything.",
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Suggest error classes from an unexplained difference.")
    ap.add_argument("--difference", required=True, help="the unexplained difference, e.g. 81.00")
    ap.add_argument("--amounts", help="optional JSON file: list of candidate transaction amounts")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    diff = to_pence(args.difference)
    if diff is None:
        sys.stderr.write(f"DIAGNOSE_ENV_ERROR: could not parse difference {args.difference!r}\n")
        return 3

    amounts: List[int] = []
    if args.amounts:
        try:
            raw = json.loads(open(args.amounts, encoding="utf-8").read())
            amounts = [p for p in (to_pence(x) for x in raw) if p is not None]
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            sys.stderr.write(f"DIAGNOSE_ENV_ERROR: amounts unreadable: {exc}\n")
            return 3

    result = diagnose(diff, amounts)
    # A zero difference is SUCCESS, not a failed match. Conflating "nothing is wrong" with
    # "I could not explain what is wrong" would make a clean reconciliation look like a
    # diagnostic dead end.
    if diff == 0:
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("DIFFERENCE £0.00 — nothing to diagnose")
        return 0

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"DIFFERENCE {result['difference']} — {len(result['candidates'])} candidate class(es)\n")
        for i, c in enumerate(result["candidates"], 1):
            print(f"  {i}. [{c['confidence'].upper():<6}] {c['class']}")
            print(f"       why:   {c['why']}")
            print(f"       check: {c['check']}\n")
        print(f"  {result['note']}")
    return 0 if result["candidates"] else 2


if __name__ == "__main__":
    sys.exit(main())
