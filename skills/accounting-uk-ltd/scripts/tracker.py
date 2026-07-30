#!/usr/bin/env python3
"""tracker.py — S074. The accounting engagement tracker for a UK small Ltd.

Turns a company profile into an obligation calendar, then keeps it current across sessions.
Four verbs:

    init       profile in  -> obligation calendar out (accounting-tracker.v1)
    status     recompute what is due, soon, or overdue AS OF TODAY
    update     record an obligation as in_progress / done / not_applicable, with evidence
    law-check  report which rules and rates need re-verifying, and where to look

THE RULE, and it is the same one the rest of this harness runs on: anything derivable is
COMPUTED, never accepted from input.

  * Due dates are computed from the profile plus the statutory rule, and each obligation
    carries the rule it came from, so a wrong date is traceable rather than mysterious.
  * `overdue` is NOT a stored field. It is derived from due_date and today's date every
    time status runs. A caller can record that something was DONE; nobody can assert that
    an obligation is not due. That asymmetry is the whole point — the failure mode this
    guards against is a tracker that has been talked out of its own deadlines.
  * `init` refuses to invent a profile. A missing accounting reference date is a question,
    not a default.

Law-watch is honest about its limits: this script cannot browse. It computes staleness and
emits the URLs that need checking; the AGENT does the verification and records the result.
Saying "checked" without fetching is the failure it is designed to make visible.

Stdlib only. Dates are ISO. Exit codes: 0 ok · 2 attention required · 3 bad input.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "accounting-tracker.v1"
DEFAULT_CHECK_INTERVAL_DAYS = 90

# Rules are named so a due date can be argued with. See accounting-uk-ltd §4.
RULES = {
    "vat_return": "VAT return + payment: 1 month + 7 days after the period end",
    "ct_payment": "Corporation tax PAYMENT: 9 months + 1 day after the period end",
    "ct_filing": "CT600 FILING: 12 months after the period end",
    "annual_accounts": "Companies House accounts: 9 months after the ARD (21 months from incorporation for a first period)",
    "confirmation_statement": "Confirmation statement: within 14 days of the review period end",
    "paye_payment": "PAYE/NIC: by the 22nd of the following month (electronic)",
    "p60": "P60 to employees: by 31 May",
    "p11d": "P11D/P11D(b): by 6 July",
    "class_1a_payment": "Class 1A NIC: by 22 July (electronic)",
}


def add_months(d: date, months: int) -> date:
    """Month arithmetic that clamps to month end — 31 Jan + 1 month is 28/29 Feb."""
    y, m = divmod((d.year * 12 + d.month - 1) + months, 12)
    m += 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last))


def _last_day(y: int, m: int) -> int:
    return [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]


def add_months_eom(d: date, months: int) -> date:
    """Month arithmetic that preserves END OF MONTH.

    Statutory deadlines run from the END of a period, so "one month after 30 September"
    means the end of October, not 30 October. Plain clamping got the VAT deadline for
    every 30-day quarter end one day early — a quarter ending 30 Sep computed as 6 Nov
    when the answer is 7 Nov. Caught by checking the arithmetic against HMRC's own
    worked pattern (period end 31 Mar -> 7 May, 30 Jun -> 7 Aug) rather than trusting it.
    """
    if d.day == _last_day(d.year, d.month):
        y, m = divmod((d.year * 12 + d.month - 1) + months, 12)
        m += 1
        return date(y, m, _last_day(y, m))
    return add_months(d, months)


def iso(d: date) -> str:
    return d.isoformat()


def env_error(msg: str) -> int:
    sys.stderr.write(f"TRACKER_ENV_ERROR: {msg}\n")
    return 3


# ---------------------------------------------------------------------------
# init — derive the calendar
# ---------------------------------------------------------------------------


def _year_end(ard: str, ref: date) -> date:
    """Next accounting year end on or after `ref`, from an MM-DD reference date."""
    mm, dd = (int(x) for x in ard.split("-"))
    cand = date(ref.year, mm, min(dd, 28) if mm == 2 else dd)
    return cand if cand >= ref else date(ref.year + 1, mm, cand.day)


def build_obligations(company: Dict[str, Any], horizon_months: int, today: date) -> List[Dict[str, Any]]:
    obs: List[Dict[str, Any]] = []
    horizon = add_months(today, horizon_months)

    def add(kind: str, due: date, label: str, period_end: Optional[date] = None) -> None:
        if due <= horizon:
            obs.append({
                "id": f"{kind}-{label}".replace(" ", "-").lower(),
                "kind": kind, "period_label": label,
                "period_end": iso(period_end) if period_end else None,
                "due_date": iso(due), "status": "pending",
                "completed_on": None, "evidence": None, "notes": None,
                "rule": RULES.get(kind),
            })

    ard = company.get("accounting_reference_date")
    ye = _year_end(ard, today) if ard else None

    # --- year-end driven -----------------------------------------------------
    if ye:
        label = iso(ye)
        # Companies House accounts. A FIRST period runs 21 months from incorporation.
        inc = company.get("incorporated_on")
        first_period = False
        if inc:
            try:
                inc_d = date.fromisoformat(inc)
                first_period = ye <= add_months(inc_d, 18)
            except ValueError:
                pass
        add("annual_accounts",
            add_months(date.fromisoformat(inc), 21) if (first_period and inc) else add_months_eom(ye, 9),
            label, ye)
        add("ct_payment", add_months_eom(ye, 9) + timedelta(days=1), label, ye)
        add("ct_filing", add_months_eom(ye, 12), label, ye)

    # --- VAT quarters --------------------------------------------------------
    if company.get("vat_registered"):
        stagger = company.get("vat_stagger_month")
        if stagger:
            # Walk quarter ends from the stagger month forward through the horizon.
            q_end = date(today.year, stagger, 1)
            q_end = add_months(q_end, 1) - timedelta(days=1)
            while q_end < today:
                q_end = add_months(q_end + timedelta(days=1), 3) - timedelta(days=1)
            for _ in range(8):
                add("vat_return", add_months_eom(q_end, 1) + timedelta(days=7),
                    f"quarter-ending-{iso(q_end)}", q_end)
                q_end = add_months(q_end + timedelta(days=1), 3) - timedelta(days=1)

    # --- confirmation statement ---------------------------------------------
    csr = company.get("confirmation_statement_review_date")
    if csr:
        try:
            r = date.fromisoformat(csr)
            while r < today:
                r = add_months(r, 12)
            add("confirmation_statement", r + timedelta(days=14), iso(r), r)
        except ValueError:
            pass

    # --- payroll -------------------------------------------------------------
    if company.get("has_employees") and company.get("payroll_frequency") == "monthly":
        m = date(today.year, today.month, 1)
        for _ in range(horizon_months + 1):
            pay_month_end = add_months(m, 1) - timedelta(days=1)
            add("paye_payment", date(add_months(m, 1).year, add_months(m, 1).month, 22),
                f"month-ending-{iso(pay_month_end)}", pay_month_end)
            m = add_months(m, 1)
        for yr in (today.year, today.year + 1):
            add("p60", date(yr, 5, 31), f"tax-year-{yr - 1}-{yr}")
            add("p11d", date(yr, 7, 6), f"tax-year-{yr - 1}-{yr}")
            add("class_1a_payment", date(yr, 7, 22), f"tax-year-{yr - 1}-{yr}")

    obs.sort(key=lambda o: o["due_date"])
    return obs


def cmd_init(args) -> int:
    try:
        company = json.loads(Path(args.company).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return env_error(f"company profile unreadable: {exc}")

    if not company.get("accounting_reference_date"):
        sys.stderr.write(
            "TRACKER_INCOMPLETE: accounting_reference_date is required and will not be guessed.\n"
            "  It drives the year end, the Companies House deadline and the corporation tax period.\n"
            "  Take it from the Companies House register — not from memory.\n")
        return 3

    today = date.fromisoformat(args.today) if args.today else date.today()
    tracker = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": iso(today),
        "company": company,
        "obligations": build_obligations(company, args.horizon_months, today),
        "law_watch": {
            "rates_review_by": args.rates_review_by,
            "last_checked": None,
            "check_interval_days": DEFAULT_CHECK_INTERVAL_DAYS,
            "watch_items": [
                {"topic": "CT600 gains 2 boxes for a 40% first-year allowance",
                 "effective_from": "2027-04-01",
                 "source_url": "https://www.gov.uk/guidance/changes-and-issues-affecting-the-corporation-tax-online-service",
                 "note": "affects the return form"},
                {"topic": "Companies House software-only filing; small companies must file a P&L; abridged abolished",
                 "effective_from": "2028-04-01",
                 "source_url": "https://changestoukcompanylaw.campaign.gov.uk/changes-to-accounts/",
                 "note": "ends the filleted-accounts P&L privacy this company may rely on"},
                {"topic": "Rates and thresholds for employers",
                 "effective_from": None,
                 "source_url": "https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027",
                 "note": "reset annually at fiscal events"},
                {"topic": "Corporation Tax rates and allowances",
                 "effective_from": None,
                 "source_url": "https://www.gov.uk/government/publications/rates-and-allowances-corporation-tax/rates-and-allowances-corporation-tax",
                 "note": "main/small rate, limits, marginal fraction"},
            ],
        },
        "history": [{"at": iso(today), "action": "init",
                     "detail": f"{len(build_obligations(company, args.horizon_months, today))} obligation(s) derived"}],
    }

    assumed = [k for k, v in (company.get("field_provenance") or {}).items() if v == "assumed"]
    Path(args.out).write_text(json.dumps(tracker, indent=2, sort_keys=False), encoding="utf-8")

    print(f"TRACKER INITIALISED: {len(tracker['obligations'])} obligation(s) -> {args.out}")
    if assumed:
        print(f"  ASSUMED fields ({len(assumed)}): {', '.join(assumed)}")
        print("  Every date derived from an assumed field inherits that assumption. Confirm them.")
    return 0


# ---------------------------------------------------------------------------
# status — derived, never stored
# ---------------------------------------------------------------------------


def compute_status(tracker: Dict[str, Any], today: date, soon_days: int = 30) -> Dict[str, Any]:
    overdue, due_soon, upcoming, done = [], [], [], []
    for o in tracker.get("obligations", []):
        if o.get("status") in ("done", "not_applicable"):
            done.append(o)
            continue
        try:
            due = date.fromisoformat(o["due_date"])
        except (ValueError, KeyError):
            continue
        days = (due - today).days
        entry = {**o, "days_remaining": days}
        (overdue if days < 0 else due_soon if days <= soon_days else upcoming).append(entry)

    law = tracker.get("law_watch") or {}
    law_flags = []
    rb = law.get("rates_review_by")
    if rb:
        try:
            if date.fromisoformat(rb) < today:
                law_flags.append(f"rates reference passed REVIEW_BY {rb} — figures are suspect until re-verified")
        except ValueError:
            pass
    lc, interval = law.get("last_checked"), law.get("check_interval_days", DEFAULT_CHECK_INTERVAL_DAYS)
    if not lc:
        law_flags.append("law-watch has never been run")
    else:
        try:
            age = (today - date.fromisoformat(lc)).days
            if age > interval:
                law_flags.append(f"law-watch last run {age} days ago (interval {interval})")
        except ValueError:
            pass
    for w in law.get("watch_items", []):
        ef = w.get("effective_from")
        if ef:
            try:
                d = (date.fromisoformat(ef) - today).days
                if 0 <= d <= 365:
                    law_flags.append(f"{w['topic']} takes effect in {d} days ({ef})")
            except ValueError:
                pass

    return {
        "as_of": iso(today),
        "overdue": overdue, "due_soon": due_soon, "upcoming": upcoming,
        "done_count": len(done), "law_flags": law_flags,
        "needs_attention": bool(overdue or due_soon or law_flags),
    }


def cmd_status(args) -> int:
    try:
        tracker = json.loads(Path(args.tracker).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return env_error(f"tracker unreadable: {exc}")
    today = date.fromisoformat(args.today) if args.today else date.today()
    st = compute_status(tracker, today, args.soon_days)

    if args.json:
        print(json.dumps(st, indent=2))
    else:
        print(f"ACCOUNTING STATUS as of {st['as_of']} — "
              f"{len(st['overdue'])} overdue, {len(st['due_soon'])} due soon, "
              f"{len(st['upcoming'])} upcoming, {st['done_count']} done")
        for o in st["overdue"]:
            print(f"  OVERDUE  {o['due_date']}  {o['kind']:<24} {o['period_label']}  ({-o['days_remaining']}d late)")
        for o in st["due_soon"]:
            print(f"  DUE SOON {o['due_date']}  {o['kind']:<24} {o['period_label']}  (in {o['days_remaining']}d)")
        for f in st["law_flags"]:
            print(f"  LAW      {f}")
    return 2 if st["needs_attention"] else 0


# ---------------------------------------------------------------------------
# update / law-check
# ---------------------------------------------------------------------------


def cmd_update(args) -> int:
    p = Path(args.tracker)
    try:
        tracker = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return env_error(f"tracker unreadable: {exc}")
    today = date.fromisoformat(args.today) if args.today else date.today()

    hit = next((o for o in tracker["obligations"] if o["id"] == args.id), None)
    if hit is None:
        sys.stderr.write(f"TRACKER_ENV_ERROR: no obligation with id {args.id!r}\n")
        return 3
    if args.status == "done" and not args.evidence:
        sys.stderr.write(
            "TRACKER_REFUSED: marking an obligation done requires --evidence.\n"
            "  A submission reference, receipt or filing id. 'Done' with nothing behind it is\n"
            "  indistinguishable from forgotten, which is the state this tracker exists to prevent.\n")
        return 2

    before = hit["status"]
    hit["status"] = args.status
    hit["completed_on"] = iso(today) if args.status == "done" else None
    if args.evidence:
        hit["evidence"] = args.evidence
    if args.notes:
        hit["notes"] = args.notes
    tracker.setdefault("history", []).append({
        "at": iso(today), "action": "update",
        "detail": f"{args.id}: {before} -> {args.status}" + (f" ({args.evidence})" if args.evidence else ""),
    })
    p.write_text(json.dumps(tracker, indent=2, sort_keys=False), encoding="utf-8")
    print(f"UPDATED {args.id}: {before} -> {args.status}")
    return 0


def cmd_law_check(args) -> int:
    p = Path(args.tracker)
    try:
        tracker = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return env_error(f"tracker unreadable: {exc}")
    today = date.fromisoformat(args.today) if args.today else date.today()
    law = tracker.setdefault("law_watch", {})

    if args.record_checked:
        law["last_checked"] = iso(today)
        tracker.setdefault("history", []).append(
            {"at": iso(today), "action": "law-check", "detail": args.record_checked})
        p.write_text(json.dumps(tracker, indent=2, sort_keys=False), encoding="utf-8")
        print(f"LAW-CHECK RECORDED {iso(today)}: {args.record_checked}")
        return 0

    st = compute_status(tracker, today)
    print("LAW-WATCH — this script cannot browse. Fetch each source, then record the result with")
    print("  --record-checked '<what changed, or: no change>'. Recording without fetching is the")
    print("  failure this is built to make visible.\n")
    for f in st["law_flags"]:
        print(f"  FLAG  {f}")
    print("\n  Sources to verify:")
    for w in law.get("watch_items", []):
        ef = f" [effective {w['effective_from']}]" if w.get("effective_from") else ""
        print(f"    - {w['topic']}{ef}\n      {w['source_url']}")
    return 2 if st["law_flags"] else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="UK small-company accounting engagement tracker.")
    ap.add_argument("--today", help="override today's date (ISO) for testing")
    sub = ap.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="derive the obligation calendar from a company profile")
    i.add_argument("--company", required=True); i.add_argument("--out", required=True)
    i.add_argument("--horizon-months", type=int, default=30,
               help="must exceed 24 or CT filing (12 months after a year end up to 12 months away) falls outside and silently vanishes")
    i.add_argument("--rates-review-by", default="2027-04-06")
    i.set_defaults(func=cmd_init)

    s = sub.add_parser("status", help="what is overdue, due soon, upcoming — computed as of today")
    s.add_argument("--tracker", required=True); s.add_argument("--soon-days", type=int, default=30)
    s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_status)

    u = sub.add_parser("update", help="record progress on one obligation")
    u.add_argument("--tracker", required=True); u.add_argument("--id", required=True)
    u.add_argument("--status", required=True, choices=["pending", "in_progress", "done", "not_applicable"])
    u.add_argument("--evidence"); u.add_argument("--notes"); u.set_defaults(func=cmd_update)

    l = sub.add_parser("law-check", help="what needs re-verifying, and where to look")
    l.add_argument("--tracker", required=True)
    l.add_argument("--record-checked", help="record that verification happened, with what changed")
    l.set_defaults(func=cmd_law_check)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
