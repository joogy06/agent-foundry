#!/usr/bin/env python3
"""settlement_reconcile.py — S074. Prove a processor payout decomposes before you post it.

    check      does sum(orders) - fees - refunds equal the net payout?
    postings   the clearing-account journal shape the reconciled payout implies

THE INVARIANT THIS ENFORCES

**A payout is not a sale.** One payout is many orders, minus fees, sometimes minus refunds
and chargebacks, and it usually straddles a period boundary. Posting the NET payout as
turnover understates turnover, understates costs, and understates output VAT — all three at
once, in a way no control account will ever catch, because the bank line reconciles
perfectly against a wrong entry.

The payout reconciles a CLEARING ACCOUNT. It is never the revenue entry.

WHY THIS EXISTS BEFORE ANY FEED IS BUILT

The feed build order (`references/data-feeds.md`) puts payment settlements at step 4 and
says "manual export first, API once the posting pattern is proven". This is what proving it
means. A feed that lands data nobody has reconciled is worse than no feed: it looks like
coverage.

PERIOD STRADDLE IS THE VAT TRAP

An order placed on 30 June and paid out on 2 July belongs to June for VAT — the tax point
is the supply, not the settlement. Reconciling on payout date silently moves revenue and
output VAT into the wrong return. Straddling orders are reported separately for that reason,
never folded into the total.

WHAT IT WILL NOT DO

It reports the difference and names candidates. **It does not decide what the difference
is.** A processor legitimately nets monthly account fees out of a single transaction, holds
a reserve, or reverses a chargeback weeks later — those look identical to an error until a
human looks. Auto-classifying them would train people to dismiss the output.

Stdlib only. Money is INTEGER PENCE — never float. Exit: 0 reconciles · 2 difference · 3 bad input.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

_MONEY = re.compile(r"^\(?-?\s*[£$€]?\s*[\d,]+(?:\.\d{1,2})?\s*\)?$")


def to_pence(raw: str | int | float, field: str = "amount") -> int:
    """Parse money to integer pence WITHOUT going through float.

    `float("0.07") * 100` is 7.000000000000001 and `int()` of it is 7 — but the same trick
    on other values truncates the wrong way, and the error is invisible until a reconciliation
    is out by a penny nobody can explain. String handling has no such failure mode.
    """
    if isinstance(raw, int):
        return raw * 100
    if isinstance(raw, float):
        raise TypeError(f"{field}: refusing a float ({raw!r}) — pass a string or integer pence")
    s = str(raw).strip()
    if not s:
        raise ValueError(f"{field}: empty")
    if not _MONEY.match(s):
        raise ValueError(f"{field}: not a money value: {raw!r}")
    neg = s.startswith("(") and s.endswith(")")           # accounting negatives
    s = s.strip("()").strip()
    s = re.sub(r"[£$€,\s]", "", s)
    if s.startswith("-"):
        neg, s = True, s[1:]
    whole, _, frac = s.partition(".")
    frac = (frac + "00")[:2]
    val = int(whole or "0") * 100 + int(frac)
    return -val if neg else val


def money(p: int) -> str:
    sign = "-" if p < 0 else ""
    return f"{sign}{abs(p) // 100}.{abs(p) % 100:02d}"


def _rows(path: Path) -> list[dict]:
    if not path.is_file():
        sys.exit(f"[input] no such file: {path}")
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text())
            return data if isinstance(data, list) else data.get("rows", [])
        with path.open(newline="") as fh:
            return list(csv.DictReader(fh))
    except (json.JSONDecodeError, csv.Error, UnicodeDecodeError) as e:
        sys.exit(f"[input] cannot read {path}: {e}")


def _pick(row: dict, *names: str) -> str | None:
    low = {k.strip().lower(): v for k, v in row.items() if k}
    for n in names:
        if n in low and str(low[n]).strip():
            return str(low[n]).strip()
    return None


def load_settlement(path: Path) -> dict:
    """One payout: net amount, fee total, refund total, and the order ids it covers."""
    rows = _rows(path)
    if not rows:
        sys.exit(f"[input] {path} has no rows")
    lines, fees, refunds = [], 0, 0
    for i, r in enumerate(rows, 1):
        kind = (_pick(r, "type", "kind", "entry_type") or "sale").lower()
        amt_raw = _pick(r, "amount", "gross", "value")
        if amt_raw is None:
            sys.exit(f"[input] {path} row {i}: no amount column "
                     f"(looked for amount/gross/value)")
        try:
            amt = to_pence(amt_raw, f"{path.name} row {i}")
            fee = to_pence(_pick(r, "fee", "fees", "charge") or "0", f"{path.name} row {i} fee")
        except (ValueError, TypeError) as e:
            sys.exit(f"[input] {e}")
        oid = _pick(r, "order_id", "order", "reference", "transaction_id", "id")
        d = _pick(r, "date", "settled_date", "created")
        if "fee" in kind or kind in {"charge", "monthly_fee"}:
            fees += abs(amt) if amt else abs(fee)
            lines.append({"kind": "fee", "order_id": oid, "amount": -abs(amt or fee), "date": d})
            continue
        if kind in {"refund", "chargeback", "reversal"}:
            refunds += abs(amt)
            lines.append({"kind": kind, "order_id": oid, "amount": -abs(amt), "date": d})
            continue
        fees += fee
        lines.append({"kind": "sale", "order_id": oid, "amount": amt, "fee": fee, "date": d})
    return {"lines": lines, "fees": fees, "refunds": refunds}


def load_orders(path: Path) -> dict[str, dict]:
    out = {}
    for i, r in enumerate(_rows(path), 1):
        oid = _pick(r, "order_id", "order", "id", "reference")
        amt_raw = _pick(r, "amount", "total", "gross", "value")
        if not oid or amt_raw is None:
            sys.exit(f"[input] {path} row {i}: needs an order id and an amount")
        try:
            out[oid] = {"amount": to_pence(amt_raw, f"order {oid}"),
                        "date": _pick(r, "date", "order_date", "created")}
        except (ValueError, TypeError) as e:
            sys.exit(f"[input] {e}")
    return out


def reconcile(settle: dict, orders: dict, payout_pence: int,
              period: tuple[str, str] | None) -> dict:
    sale_lines = [l for l in settle["lines"] if l["kind"] == "sale"]
    gross = sum(l["amount"] for l in sale_lines)
    expected = gross - settle["fees"] - settle["refunds"]

    settled_ids = {l["order_id"] for l in sale_lines if l["order_id"]}
    order_ids = set(orders)
    orphans = sorted(settled_ids - order_ids)          # in the payout, no order found
    unsettled = sorted(order_ids - settled_ids)        # order exists, not in this payout

    mismatched = []
    for l in sale_lines:
        oid = l["order_id"]
        if oid in orders and orders[oid]["amount"] != l["amount"]:
            mismatched.append({"order_id": oid, "order": orders[oid]["amount"],
                               "settlement": l["amount"],
                               "delta": l["amount"] - orders[oid]["amount"]})

    straddle = []
    if period:
        lo, hi = period
        for l in sale_lines:
            oid = l["order_id"]
            od = (orders.get(oid) or {}).get("date")
            if od and not (lo <= od <= hi):
                straddle.append({"order_id": oid, "order_date": od,
                                 "amount": l["amount"]})

    return {
        "gross": gross, "fees": settle["fees"], "refunds": settle["refunds"],
        "expected_net": expected, "payout": payout_pence,
        "difference": payout_pence - expected,
        "orders_in_payout": len(sale_lines),
        "orphans": orphans, "unsettled": unsettled,
        "mismatched": mismatched, "straddle": straddle,
        "effective_fee_bps": round(settle["fees"] * 10000 / gross) if gross else None,
    }


def cmd_check(args) -> int:
    settle = load_settlement(args.settlement)
    orders = load_orders(args.orders) if args.orders else {}
    try:
        payout = to_pence(args.payout, "--payout")
    except (ValueError, TypeError) as e:
        sys.exit(f"[input] {e}")
    period = (args.period_start, args.period_end) if args.period_start and args.period_end else None
    r = reconcile(settle, orders, payout, period)

    if args.json:
        print(json.dumps(r, indent=2))
        return 2 if r["difference"] or r["orphans"] or r["mismatched"] or r["straddle"] else 0

    print(f"SETTLEMENT RECONCILIATION — {args.settlement.name}\n")
    print(f"  gross sales      {money(r['gross']):>12}   ({r['orders_in_payout']} order lines)")
    print(f"  fees            -{money(r['fees']):>12}"
          + (f"   ({r['effective_fee_bps'] / 100:.2f}% of gross)" if r["effective_fee_bps"] else ""))
    print(f"  refunds         -{money(r['refunds']):>12}")
    print(f"  {'-' * 34}")
    print(f"  expected net     {money(r['expected_net']):>12}")
    print(f"  actual payout    {money(r['payout']):>12}")
    print(f"  DIFFERENCE       {money(r['difference']):>12}"
          + ("   <- reconciles exactly" if r["difference"] == 0 else "   <- unexplained"))
    print()

    if r["difference"]:
        print("  The difference is NOT yet an error. Candidates, in the order they usually are:")
        print("    · a monthly account fee netted out of one transaction rather than per-sale")
        print("    · a rolling reserve held back, or released from an earlier period")
        print("    · a chargeback or reversal from a prior payout landing in this one")
        print("    · an order refunded after the payout was calculated")
        print("    · a fee column the export labels differently from the ones parsed here")
        print("  Identify which before posting anything.\n")
    if r["mismatched"]:
        print(f"  {len(r['mismatched'])} order(s) where settlement and order value disagree:")
        for m in r["mismatched"][:10]:
            print(f"    {m['order_id']}: order {money(m['order'])} vs "
                  f"settlement {money(m['settlement'])} (delta {money(m['delta'])})")
        print()
    if r["orphans"]:
        print(f"  {len(r['orphans'])} settlement line(s) with no matching order — "
              f"the payout is paying for something the order data does not show:")
        print("    " + ", ".join(r["orphans"][:12]) + "\n")
    if r["unsettled"]:
        print(f"  {len(r['unsettled'])} order(s) not in this payout. Usually timing, not loss — "
              f"confirm they appear in the NEXT one:")
        print("    " + ", ".join(r["unsettled"][:12]) + "\n")
    if r["straddle"]:
        print(f"  PERIOD STRADDLE — {len(r['straddle'])} order(s) dated outside "
              f"{args.period_start}..{args.period_end}.")
        print("    The VAT tax point is the SUPPLY, not the settlement. These belong to the period")
        print("    they were sold in, not the one they were paid out in:")
        for s in r["straddle"][:10]:
            print(f"    {s['order_id']}  ordered {s['order_date']}  {money(s['amount'])}")
        print()

    print("  Reminder: the payout posts to the CLEARING account, never to revenue.")
    print("  `postings` shows the shape.")
    return 2 if (r["difference"] or r["orphans"] or r["mismatched"] or r["straddle"]) else 0


def cmd_postings(args) -> int:
    settle = load_settlement(args.settlement)
    gross = sum(l["amount"] for l in settle["lines"] if l["kind"] == "sale")
    net = gross - settle["fees"] - settle["refunds"]
    print("Journal shape for a processor payout. Amounts in the reporting currency.\n")
    print("1. When the SALE happens (tax point — this is the revenue entry):")
    print(f"     Dr  Processor clearing            {money(gross)}")
    print(f"       Cr  Sales                          (net of VAT)")
    print(f"       Cr  VAT control                    (output VAT)\n")
    print("2. Processor fees (an expense, NOT a reduction of turnover):")
    print(f"     Dr  Merchant fees                 {money(settle['fees'])}")
    print(f"       Cr  Processor clearing           {money(settle['fees'])}\n")
    if settle["refunds"]:
        print("3. Refunds and chargebacks (reverse the original supply, incl. its VAT):")
        print(f"     Dr  Sales / VAT control        {money(settle['refunds'])}")
        print(f"       Cr  Processor clearing         {money(settle['refunds'])}\n")
    print("4. When the PAYOUT hits the bank:")
    print(f"     Dr  Bank                          {money(net)}")
    print(f"       Cr  Processor clearing           {money(net)}\n")
    print("The clearing account should trend to zero. A balance that only grows means sales are")
    print("being recorded and payouts are not — or the reverse. Either way it is the first thing")
    print("to check, and it is why the payout must never be posted straight to turnover.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Prove a processor payout decomposes before posting it.")
    ap.add_argument("--settlement", type=Path, required=True,
                    help="settlement/transaction export (CSV or JSON)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check")
    p.add_argument("--orders", type=Path, help="order export, to match line by line")
    p.add_argument("--payout", required=True, help="the amount that actually hit the bank")
    p.add_argument("--period-start", help="YYYY-MM-DD — enables straddle detection")
    p.add_argument("--period-end", help="YYYY-MM-DD")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("postings"); p.set_defaults(fn=cmd_postings)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
