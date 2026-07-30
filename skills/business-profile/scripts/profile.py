#!/usr/bin/env python3
"""profile.py — S074. The learned operational profile of a business.

Stops every session starting from zero. Learns how each counterparty actually appears and
behaves — the narratives they show up under, how often they bill, what they normally cost,
how they are treated for VAT and category — then flags when any of that CHANGES.

    learn   ingest transactions; build or update counterparty baselines
    match   given a narrative, identify the counterparty (or say it is unknown)
    check   drift vs baseline — the point of the whole thing
    note    record a human observation about a counterparty

WHY DRIFT IS THE VALUABLE PART

Most bookkeeping errors are not wrong numbers, they are CHANGES nobody noticed:

  * a supplier alters its bank narrative -> the bank rule silently stops matching
  * a monthly direct debit stops appearing -> cancelled, or a FEED GAP
  * an amount steps outside its usual range -> a price rise, or a keying error
  * a VAT treatment changes -> a mis-code that no control account will ever catch

A missed recurrence is the one worth having. Nothing else in the books can detect a
transaction that simply never arrived, because absence has nothing to appear as.

WHAT THIS DELIBERATELY WILL NOT DO

Every finding is a QUESTION, never a verdict. Vendors legitimately rename, prices rise,
billing moves annual, and a business changes what it buys. The tool reports what changed
and against what baseline; a human decides whether it is a problem. Auto-classifying
change as error would train people to dismiss it, which is worse than not flagging at all.

Confidence is reported honestly: a baseline built on two observations is not a baseline,
and the tool says so instead of asserting a range it cannot support.

Stdlib only. Money is integer pence. Exit: 0 no drift · 2 drift found · 3 bad input.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "business-profile.v1"
MIN_OBSERVATIONS_FOR_RANGE = 4     # below this, a "usual range" is noise
AMOUNT_TOLERANCE = 0.25            # 25% outside observed range before flagging


def to_pence(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int((Decimal(str(v).replace(",", "").replace("£", "").strip()) * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        return None


def fmt(p: Optional[int]) -> str:
    return "—" if p is None else f"£{p / 100:,.2f}"


def normalise(narrative: str) -> str:
    """Strip the volatile parts of a bank narrative so the stable stem remains.

    Bank descriptions carry dates, card suffixes, reference numbers and payment ids that
    differ every time. Matching on the raw string means every transaction looks new.
    """
    s = (narrative or "").upper()
    s = re.sub(r"\b\d{2}[/-]\d{2}([/-]\d{2,4})?\b", " ", s)      # dates
    s = re.sub(r"\bREF[:\s]*\S+", " ", s)                          # references
    s = re.sub(r"\b\d{6,}\b", " ", s)                              # long numbers
    s = re.sub(r"\bCARD\s*\d+\b", " ", s)
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return " ".join(s.split())


def stem(narrative: str, words: int = 3) -> str:
    """The first few stable words — enough to identify a counterparty in practice."""
    return " ".join(normalise(narrative).split()[:words])


# ---------------------------------------------------------------------------
# learn
# ---------------------------------------------------------------------------


def learn(profile: Dict[str, Any], txns: List[Dict[str, Any]]) -> Dict[str, Any]:
    parties: Dict[str, Dict[str, Any]] = {p["id"]: p for p in profile.get("counterparties", [])}
    added, updated = 0, 0

    for t in txns:
        narrative = t.get("description") or t.get("narrative") or ""
        amt = to_pence(t.get("amount"))
        when = t.get("date")
        if not narrative or amt is None:
            continue
        key = stem(narrative)
        if not key:
            continue

        p = parties.get(key)
        if p is None:
            p = {
                "id": key, "display_name": key or narrative.strip()[:60],
                "narratives": [], "amounts": [], "dates": [],
                "category": t.get("category"), "vat_treatment": t.get("vat_treatment"),
                "notes": [], "occurrences": 0,
            }
            parties[key] = p
            added += 1
        else:
            updated += 1

        norm = normalise(narrative)
        if norm not in p["narratives"]:
            p["narratives"].append(norm)
        p["amounts"].append(amt)
        if when:
            p["dates"].append(when)
        p["occurrences"] += 1
        for field in ("category", "vat_treatment"):
            if t.get(field) and not p.get(field):
                p[field] = t[field]

    for p in parties.values():
        p["dates"] = sorted(set(p["dates"]))
        p.update(_baseline(p))

    profile["schema_version"] = SCHEMA_VERSION
    profile["counterparties"] = sorted(parties.values(), key=lambda x: -x["occurrences"])
    profile.setdefault("history", []).append(
        {"action": "learn", "ingested": len(txns), "new_counterparties": added})
    return {"new": added, "seen": updated, "total": len(parties)}


def _baseline(p: Dict[str, Any]) -> Dict[str, Any]:
    """Derive what 'normal' looks like — and say when there is not enough to say."""
    amounts = p.get("amounts") or []
    out: Dict[str, Any] = {
        "first_seen": p["dates"][0] if p.get("dates") else None,
        "last_seen": p["dates"][-1] if p.get("dates") else None,
    }
    if len(amounts) < MIN_OBSERVATIONS_FOR_RANGE:
        out.update({"amount_min": None, "amount_max": None, "amount_median": None,
                    "baseline_confidence": "insufficient",
                    "baseline_note": f"{len(amounts)} observation(s) — too few to call a range"})
    else:
        out.update({"amount_min": min(amounts), "amount_max": max(amounts),
                    "amount_median": int(statistics.median(amounts)),
                    "baseline_confidence": "established"})

    # Cadence, inferred from gaps rather than asserted.
    ds = p.get("dates") or []
    if len(ds) >= 3:
        try:
            parsed = sorted(date.fromisoformat(d) for d in ds)
            gaps = [(b - a).days for a, b in zip(parsed, parsed[1:])]
            med = statistics.median(gaps)
            out["cadence_days"] = int(med)
            out["cadence"] = ("monthly" if 25 <= med <= 35 else
                              "weekly" if 5 <= med <= 9 else
                              "quarterly" if 80 <= med <= 100 else
                              "annual" if 350 <= med <= 380 else "irregular")
        except ValueError:
            out["cadence"] = "unknown"
    else:
        out["cadence"] = "unknown"
    return out


# ---------------------------------------------------------------------------
# match / check
# ---------------------------------------------------------------------------


def match(profile: Dict[str, Any], narrative: str) -> Dict[str, Any]:
    key, norm = stem(narrative), normalise(narrative)
    for p in profile.get("counterparties", []):
        if p["id"] == key:
            exact = norm in p.get("narratives", [])
            return {
                "matched": True, "counterparty": p["display_name"], "id": p["id"],
                "category": p.get("category"), "vat_treatment": p.get("vat_treatment"),
                "cadence": p.get("cadence"), "typical": fmt(p.get("amount_median")),
                "narrative_is_new": not exact,
                "note": ("KNOWN counterparty under a NEW narrative — a bank rule keyed on the old "
                         "text has silently stopped matching. Check the rule."
                         if not exact else "known narrative"),
                "notes": p.get("notes", []),
            }
    # A renamed supplier is the commonest "unknown", and reporting it as a stranger loses the
    # most useful fact about it. Overlapping significant words is a weak but cheap signal, and
    # it is offered as a QUESTION — "Ltd" becoming "Limited" and a genuine new vendor sharing a
    # word look identical from here.
    words = {w for w in norm.split() if len(w) > 3}
    resembles = []
    for p in profile.get("counterparties", []):
        known = {w for w in p["id"].split() if len(w) > 3}
        if known and len(words & known) >= max(1, min(len(known), 2)):
            resembles.append(p["display_name"])
    return {"matched": False, "narrative": narrative, "resembles": resembles[:3],
            "note": ("unknown narrative, but it RESEMBLES " + ", ".join(resembles[:3]) +
                     " — a renamed counterparty keeps its history only if you link it, and a bank "
                     "rule keyed on the old name has stopped matching"
                     if resembles else
                     "unknown counterparty — classify it once and it is known from then on")}


def check(profile: Dict[str, Any], today: date, txns: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []

    # (a) An expected recurrence that did not arrive. Nothing else can see this.
    for p in profile.get("counterparties", []):
        if p.get("cadence") not in ("monthly", "weekly", "quarterly"):
            continue
        last = p.get("last_seen")
        if not last:
            continue
        try:
            gap = (today - date.fromisoformat(last)).days
        except ValueError:
            continue
        expected = p.get("cadence_days") or 30
        if gap > expected * 2:
            findings.append({
                "kind": "missed_recurrence", "counterparty": p["display_name"],
                "detail": f"{p.get('cadence')} counterparty last seen {last} ({gap} days ago, "
                          f"expected roughly every {expected})",
                "question": "cancelled, renamed, or a FEED GAP? A bill that simply stopped arriving "
                            "is invisible to every other check in the books",
            })

    # (b) Drift in transactions supplied for review.
    for t in (txns or []):
        narrative = t.get("description") or t.get("narrative") or ""
        amt = to_pence(t.get("amount"))
        m = match(profile, narrative)
        if not m["matched"]:
            res = m.get("resembles") or []
            findings.append({
                "kind": "possible_rename" if res else "unknown_counterparty",
                "counterparty": narrative.strip()[:60],
                "detail": (f"not in the profile, but resembles {', '.join(res)}" if res
                           else "not in the profile"),
                "question": ("is this a RENAME of an existing counterparty? Link it to keep its "
                             "history, and fix the bank rule that stopped matching"
                             if res else "who is this, and how should it be treated?"),
            })
            continue
        p = next(x for x in profile["counterparties"] if x["id"] == m["id"])

        if m["narrative_is_new"]:
            findings.append({
                "kind": "narrative_changed", "counterparty": p["display_name"],
                "detail": f"new bank text: {normalise(narrative)[:60]}",
                "question": "a bank rule keyed on the old wording has stopped matching — check it",
            })

        lo, hi = p.get("amount_min"), p.get("amount_max")
        if amt is not None and lo is not None and hi is not None:
            span = max(hi - lo, 1)
            if amt < lo - span * AMOUNT_TOLERANCE or amt > hi + span * AMOUNT_TOLERANCE:
                findings.append({
                    "kind": "amount_outside_range", "counterparty": p["display_name"],
                    "detail": f"{fmt(amt)} against an observed {fmt(lo)}–{fmt(hi)}",
                    "question": "price change, a different service, or a keying error?",
                })

        for field, label in (("category", "category"), ("vat_treatment", "VAT treatment")):
            if t.get(field) and p.get(field) and t[field] != p[field]:
                findings.append({
                    "kind": f"{field}_changed", "counterparty": p["display_name"],
                    "detail": f"{label} {p[field]!r} -> {t[field]!r}",
                    "question": "deliberate reclassification, or a mis-code? A VAT change never fails "
                                "a control-account proof",
                })

    return {
        "as_of": today.isoformat(),
        "counterparties_known": len(profile.get("counterparties", [])),
        "findings": findings,
        "drift_found": bool(findings),
        "note": "Every finding is a QUESTION, not a verdict. Vendors rename, prices rise, billing "
                "changes. The tool reports what moved against what baseline; a human decides whether "
                "it matters.",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Learned operational profile of a business.")
    ap.add_argument("--profile", type=Path, required=True)
    ap.add_argument("--today")
    sub = ap.add_subparsers(dest="cmd", required=True)

    l = sub.add_parser("learn"); l.add_argument("--transactions", type=Path, required=True)
    m = sub.add_parser("match"); m.add_argument("--narrative", required=True)
    c = sub.add_parser("check"); c.add_argument("--transactions", type=Path)
    n = sub.add_parser("note"); n.add_argument("--id", required=True); n.add_argument("--text", required=True)
    for p in (l, m, c, n):
        p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else date.today()
    try:
        profile = _load(args.profile, {"schema_version": SCHEMA_VERSION, "counterparties": []})
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"PROFILE_ENV_ERROR: {exc}\n")
        return 3

    if args.cmd == "learn":
        try:
            txns = json.loads(args.transactions.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"PROFILE_ENV_ERROR: transactions unreadable: {exc}\n")
            return 3
        res = learn(profile, txns)
        args.profile.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        print(f"LEARNED: {res['new']} new counterparty(ies), {res['total']} known in total")
        return 0

    if args.cmd == "match":
        res = match(profile, args.narrative)
        print(json.dumps(res, indent=2) if args.json else
              (f"MATCH {res['counterparty']} — {res.get('category')} / {res.get('vat_treatment')} / "
               f"{res.get('cadence')} / typically {res.get('typical')}\n  {res['note']}"
               if res["matched"] else f"UNKNOWN: {res['note']}"))
        return 0 if res["matched"] else 2

    if args.cmd == "note":
        p = next((x for x in profile["counterparties"] if x["id"] == args.id), None)
        if p is None:
            sys.stderr.write(f"PROFILE_ENV_ERROR: no counterparty {args.id!r}\n")
            return 3
        p.setdefault("notes", []).append({"at": today.isoformat(), "text": args.text})
        args.profile.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        print(f"NOTED against {p['display_name']}: {args.text}")
        return 0

    txns = None
    if args.transactions:
        try:
            txns = json.loads(args.transactions.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"PROFILE_ENV_ERROR: {exc}\n")
            return 3
    res = check(profile, today, txns)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"PROFILE CHECK {res['as_of']} — {res['counterparties_known']} known, "
              f"{len(res['findings'])} finding(s)")
        for f in res["findings"]:
            print(f"\n  [{f['kind']}] {f['counterparty']}")
            print(f"    {f['detail']}")
            print(f"    -> {f['question']}")
        print(f"\n  {res['note']}")
    return 2 if res["drift_found"] else 0


if __name__ == "__main__":
    sys.exit(main())
