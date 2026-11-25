#!/usr/bin/env python3
"""surfaces.py - render and check the AI surface registry (data/surfaces.v1.json).

The registry is the single owner of surface facts: GB availability, how a merchant enters a
surface, its crawlers and where it is measured. Skills link rows instead of restating them.

    surfaces.py show [--gb live,beta,...] [--type checkout] [--channel paid] [--id ID] [--json]
    surfaces.py check [--today YYYY-MM-DD]

`check` exits 2 on an ERROR (the file's enums / required_fields missing, malformed or different
from the trusted copy hard-coded here; missing, mistyped or invalid field; a GB claim other than
'unknown' without evidence; review_after outside as_of..as_of+90d; a FORECAST row without
forecast_due) and 0 otherwise. WARNs are printed but do not fail: a stale row, a passed
forecast_due, and a live/beta GB claim resting on inferred evidence (rendered "live
(inferred)") all need a human to re-verify, not a red build.
Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent.parent / "data" / "surfaces.v1.json"
URL_PREFIX = ("https://", "http://")


def load(path: Path = REGISTRY) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _iso(value) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


MAX_AGE_CAP = 90   # days; a registry cannot widen its own freshness window past this

#: The trusted schema. The registry carries a copy for readers, but the validator never takes
#: its rules from the file it validates: deleting or widening the file's copy would let any
#: value through. A copy that is missing, malformed or different is itself an ERROR.
TRUSTED_ENUMS: dict[str, list[str]] = {
    "surface_type": ["index", "answer", "shopping", "checkout", "app"],
    "channel": ["organic", "paid"],
    "gb_availability": ["live", "beta", "us_only", "not_available", "unknown"],
    "status": ["SHIPPED", "BETA", "DEPRECATED", "FORECAST"],
    "evidence": ["V", "I"],
}
TRUSTED_REQUIRED: list[str] = [
    "id", "surface", "vendor", "surface_type", "channel", "status", "gb_availability",
    "gb_evidence_url", "evidence", "feed_or_protocol", "crawler_ua", "measurement", "as_of",
    "review_after", "source_url",
]


def _schema_copy_errors(doc: dict) -> list[str]:
    """Errors for the registry's own copy of the schema; it must equal the trusted one."""
    errors = []
    enums = doc.get("enums")
    if "enums" not in doc:
        errors.append("enums is missing (the registry must carry the trusted copy)")
    elif not isinstance(enums, dict) or not all(
            isinstance(v, list) and all(isinstance(x, str) for x in v) for v in enums.values()):
        errors.append("enums is malformed (expected an object of string lists)")
    elif enums != TRUSTED_ENUMS:
        errors.append(f"enums differs from the trusted copy in surfaces.py: {enums!r}")
    req = doc.get("required_fields")
    if "required_fields" not in doc:
        errors.append("required_fields is missing (the registry must carry the trusted copy)")
    elif not isinstance(req, list) or not all(isinstance(x, str) for x in req):
        errors.append("required_fields is malformed (expected a list of strings)")
    elif req != TRUSTED_REQUIRED:
        errors.append(f"required_fields differs from the trusted copy in surfaces.py: {req!r}")
    return errors


def gb_label(row: dict) -> str:
    """GB availability as shown to a reader: a live/beta claim on inferred evidence says so."""
    gb = row.get("gb_availability", "?")
    if gb in ("live", "beta") and row.get("evidence") == "I":
        return f"{gb} (inferred)"
    return str(gb)


def _check_row(row: dict, rid: str, required, enums, max_age: int, today: date,
               errors: list, warnings: list) -> None:
    for field in required:
        if field not in row:
            errors.append(f"{rid}: missing required field {field!r}")
    for field, allowed in enums.items():
        if field in row and row[field] not in allowed:
            errors.append(f"{rid}: {field}={row[field]!r} not in {allowed}")
    gb = row.get("gb_availability")
    gb_url = row.get("gb_evidence_url")
    if gb_url is None:
        # Only an honest 'unknown' may lack GB evidence; an I label excuses nothing.
        if gb != "unknown":
            errors.append(f"{rid}: gb_evidence_url is null but gb_availability is {gb!r} "
                          "(null is allowed only for 'unknown')")
    elif not isinstance(gb_url, str) or not gb_url.startswith(URL_PREFIX):
        errors.append(f"{rid}: gb_evidence_url is not a URL")
    if gb in ("live", "beta") and row.get("evidence") == "I":
        warnings.append(f"{rid}: GB {gb} rests on inferred evidence; shown as '{gb_label(row)}' "
                        "until a primary page confirms it")
    src = row.get("source_url")
    if src is None:
        notes = str(row.get("notes", "")).lower()
        if not (row.get("evidence") == "I" and "could not verify" in notes):
            errors.append(f"{rid}: source_url is null (allowed only for evidence I with notes "
                          "saying 'could not verify')")
    elif not isinstance(src, str) or not src.startswith(URL_PREFIX):
        errors.append(f"{rid}: source_url is not a URL")
    if not isinstance(row.get("crawler_ua"), list):
        errors.append(f"{rid}: crawler_ua must be a list")
    if not str(row.get("measurement", "")).startswith("ai-assistant-referrals"):
        errors.append(f"{rid}: measurement must point at ai-assistant-referrals")
    share = row.get("gb_share")
    if share is not None:
        if not isinstance(share, dict):
            errors.append(f"{rid}: gb_share must be an object")
        else:
            for field in ("value", "as_of", "source_url", "evidence"):
                if not share.get(field):
                    errors.append(f"{rid}: gb_share missing {field!r}")
    if row.get("status") == "FORECAST":
        due = _iso(row.get("forecast_due"))
        if due is None:
            errors.append(f"{rid}: FORECAST row needs an ISO forecast_due")
        elif due < today:
            warnings.append(f"{rid}: forecast_due {due} has passed; re-check whether it shipped")
    as_of, review = _iso(row.get("as_of")), _iso(row.get("review_after"))
    if as_of is None:
        errors.append(f"{rid}: as_of is not an ISO date")
    elif (today - as_of).days > max_age:
        warnings.append(f"{rid}: as_of {as_of} is {(today - as_of).days} days old "
                        f"(> {max_age}); re-verify against {row.get('source_url')}")
    if review is None:
        errors.append(f"{rid}: review_after is not an ISO date")
    else:
        if as_of is not None and not (as_of <= review <= as_of + timedelta(days=max_age)):
            errors.append(f"{rid}: review_after {review} must fall within as_of..as_of+{max_age}d")
        if review < today:
            warnings.append(f"{rid}: review_after {review} has passed")


def validate(doc: dict, today: date | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the whole registry. Never raises on bad shapes."""
    today = today or date.today()
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(doc, dict):
        return ["registry is not a JSON object"], warnings
    enums, required = TRUSTED_ENUMS, TRUSTED_REQUIRED
    errors.extend(_schema_copy_errors(doc))
    try:
        declared = int(doc.get("max_age_days", MAX_AGE_CAP))
    except (TypeError, ValueError):
        declared = MAX_AGE_CAP
        errors.append("max_age_days is not an integer")
    max_age = min(declared, MAX_AGE_CAP)
    if declared > MAX_AGE_CAP:
        warnings.append(f"max_age_days {declared} exceeds the {MAX_AGE_CAP}-day cap; using {MAX_AGE_CAP}")
    rows = doc.get("surfaces")
    if not isinstance(rows, list) or not rows:
        return errors + ["registry has no surfaces[]"], warnings
    seen: set[str] = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"#{i}: row is not an object")
            continue
        rid = str(row.get("id", f"#{i}"))
        if rid in seen:
            errors.append(f"{rid}: duplicate id")
        seen.add(rid)
        _check_row(row, rid, required, enums, max_age, today, errors, warnings)
    return errors, warnings


def _filter(rows, a):
    for row in rows:
        if a.gb and row.get("gb_availability") not in a.gb.split(","):
            continue
        if a.type and row.get("surface_type") != a.type:
            continue
        if a.channel and row.get("channel") != a.channel:
            continue
        if a.id and row.get("id") != a.id:
            continue
        yield row


def cmd_show(a) -> int:
    doc = load(Path(a.registry))
    rows = list(_filter([r for r in doc["surfaces"] if isinstance(r, dict)], a))
    if a.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    print(f"AI surface registry {doc.get('version')} (as_of {doc.get('as_of')}); "
          "GB 'unknown' = not listed for GB")
    print("| Surface | Type | Channel | GB | Evidence | Status | Enter via | Review after |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['surface']} | {r['surface_type']} | {r['channel']} | {gb_label(r)} | "
              f"{r['evidence']} | {r['status']} | {r['feed_or_protocol']} | {r['review_after']} |")
    return 0


def cmd_check(a) -> int:
    errors, warnings = validate(load(Path(a.registry)), a.today or date.today())
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"surfaces check: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 2 if errors else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="render and check the AI surface registry")
    p.add_argument("--registry", default=str(REGISTRY))
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("--gb", help="comma list of gb_availability values")
    s.add_argument("--type")
    s.add_argument("--channel")
    s.add_argument("--id")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_show)
    c = sub.add_parser("check")
    c.add_argument("--today", type=date.fromisoformat, help="YYYY-MM-DD")
    c.set_defaults(func=cmd_check)
    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
