#!/usr/bin/env python3
"""lessons.py — S076. The consumption half of the defect-to-skill loop.

This project already captures lessons well: `history.md` carries a "the lesson" bullet for
almost every session, and a sibling project once mailed a full capability audit under the
label `skill-feedback`. **Nothing consumed any of it.** 13 of 226 skills reference any
tracked incident, and those 13 are mostly the orchestration skills someone was editing
during the incident anyway. So the missing piece was never better capture -- it was
routing and follow-through.

THE TAXONOMY IS THE WHOLE MECHANISM, and getting it wrong makes things worse:

  capability_gap     No check existed. The skill genuinely lacks the knowledge.
                     -> route to a SKILL edit (or a new skill).

  execution_failure  The rule EXISTED IN PROSE and was not honoured.
                     -> route to a MECHANISM: a lint, a gate, a test. NOT more prose.

  one_off            Environment, luck, a genuine novelty. Record and stop.
                     -> route nowhere.

The distinction came from a sibling project's capability audit, which measured that ~half
of its defects were execution failures rather than gaps. A loop without it answers every incident by ADDING
RULES, which makes skills longer, which makes them less likely to be read, which causes
more execution failures. The loop would degrade the system it exists to improve.

`execution_failure -> mechanism` is the rule this very session demonstrates. "Pass
encoding=" was not missing knowledge; it was unenforced knowledge. The fix that worked was
`portability_lint.py`, not another paragraph telling people to remember.

    add       record a lesson
    list      what is open, and where each one is headed
    classify  set the taxonomy (and therefore the destination)
    route     name the target skill / mechanism
    close     applied, or rejected with a reason
    report    the routing backlog, grouped by destination

Stdlib only. Atomic writes, UTF-8 everywhere, no platform-exclusive imports -- this file is
dogfood for `writing-portable-python` and must lint clean under its own E/W codes.
Exit: 0 ok · 2 findings/backlog · 3 bad input.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

LEDGER = Path(".lessons") / "lessons.jsonl"

# destination is DERIVED from classification, never set by hand — that is what stops
# "add a rule" becoming the reflex answer to every incident.
CLASSIFICATIONS = {
    "capability_gap": "skill",
    "execution_failure": "mechanism",
    "one_off": "none",
}
STATUSES = ("open", "classified", "routed", "applied", "rejected")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _write(path: Path, records: list[dict]) -> None:
    """Atomic: temp file in the DESTINATION dir, flush, os.replace.

    Not ceremony — six SessionStart hooks fire together here, and on Windows
    `os.replace` fails outright if a reader still holds the destination open.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _next_id(records: list[dict]) -> str:
    n = 0
    for r in records:
        try:
            n = max(n, int(str(r.get("id", "L0"))[1:]))
        except (ValueError, IndexError):
            continue
    return f"L{n + 1:03d}"


def _find(records: list[dict], lesson_id: str) -> dict | None:
    for r in records:
        if r.get("id") == lesson_id:
            return r
    return None


def cmd_add(args) -> int:
    records = _read(args.ledger)
    rec = {
        "id": _next_id(records),
        "recorded_at": _now(),
        "session": args.session,
        "title": args.title,
        "what_happened": args.what or "",
        "found_by": args.found_by,
        "classification": None,
        "destination": None,
        "target": None,
        "status": "open",
        "rationale": "",
    }
    if args.classify:
        rec["classification"] = args.classify
        rec["destination"] = CLASSIFICATIONS[args.classify]
        rec["status"] = "classified"
    records.append(rec)
    _write(args.ledger, records)
    print(f"{rec['id']}  {rec['title']}")
    if rec["classification"] is None:
        print("  status: open — classify it, or it routes nowhere and this becomes "
              "another capture mechanism nothing consumes.")
    else:
        print(f"  {rec['classification']} → {rec['destination']}")
    return 0


def cmd_classify(args) -> int:
    records = _read(args.ledger)
    rec = _find(records, args.id)
    if rec is None:
        print(f"! no lesson {args.id}", file=sys.stderr)
        return 3
    rec["classification"] = args.as_
    rec["destination"] = CLASSIFICATIONS[args.as_]
    rec["status"] = "classified"
    if args.rationale:
        rec["rationale"] = args.rationale
    _write(args.ledger, records)
    print(f"{rec['id']}  {rec['classification']} → {rec['destination']}")
    if rec["destination"] == "mechanism":
        print("  The rule already existed and was not honoured, so MORE PROSE WILL NOT "
              "HELP. Route this to a lint, a gate, or a test.")
    return 0


def cmd_route(args) -> int:
    records = _read(args.ledger)
    rec = _find(records, args.id)
    if rec is None:
        print(f"! no lesson {args.id}", file=sys.stderr)
        return 3
    if rec.get("destination") in (None, "none"):
        print(f"! {args.id} is {rec.get('classification') or 'unclassified'} — "
              f"classify it to a routable class first", file=sys.stderr)
        return 3
    rec["target"] = args.target
    rec["status"] = "routed"
    _write(args.ledger, records)
    print(f"{rec['id']}  routed → {args.target}")
    return 0


def cmd_close(args) -> int:
    records = _read(args.ledger)
    rec = _find(records, args.id)
    if rec is None:
        print(f"! no lesson {args.id}", file=sys.stderr)
        return 3
    rec["status"] = "rejected" if args.reject else "applied"
    if args.rationale:
        rec["rationale"] = args.rationale
    elif args.reject:
        print("! --reject needs --rationale: a rejected lesson without a reason is "
              "indistinguishable from one nobody looked at", file=sys.stderr)
        return 3
    _write(args.ledger, records)
    print(f"{rec['id']}  {rec['status']}")
    return 0


def cmd_list(args) -> int:
    records = _read(args.ledger)
    if args.status:
        records = [r for r in records if r.get("status") == args.status]
    if not records:
        print("no lessons recorded")
        return 0
    for r in records:
        cls = r.get("classification") or "-"
        tgt = r.get("target") or "-"
        print(f"{r['id']}  {r.get('status',''):<10} {cls:<18} {tgt:<28} {r.get('title','')}")
    return 0


def cmd_report(args) -> int:
    """The backlog, grouped by destination — the view that makes follow-through visible."""
    records = _read(args.ledger)
    if not records:
        print("no lessons recorded")
        return 0

    pending = [r for r in records if r.get("status") in ("open", "classified", "routed")]
    print(f"[lessons] {len(records)} recorded · {len(pending)} not yet applied\n")

    unclassified = [r for r in records if r.get("status") == "open"]
    if unclassified:
        print(f"  UNCLASSIFIED ({len(unclassified)}) — these route nowhere until triaged:")
        for r in unclassified:
            print(f"    {r['id']}  {r.get('title','')}")
        print()

    for dest, header in (("skill", "→ SKILL edits (capability gaps: the knowledge is missing)"),
                         ("mechanism", "→ MECHANISMS (execution failures: the rule existed "
                                       "and was ignored — a lint/gate/test, NOT prose)"),
                         ("none", "→ recorded only (one-offs)")):
        group = [r for r in records if r.get("destination") == dest
                 and r.get("status") != "rejected"]
        if not group:
            continue
        print(f"  {header}")
        for r in group:
            mark = "done" if r.get("status") == "applied" else r.get("status", "")
            print(f"    {r['id']}  [{mark}]  {r.get('target') or '(unrouted)'}  "
                  f"— {r.get('title','')}")
        print()

    return 2 if pending else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Classified lesson ledger — the consumption half of the "
                    "defect-to-skill loop.")
    ap.add_argument("--ledger", type=Path, default=LEDGER,
                    help=f"ledger path (default {LEDGER})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="record a lesson")
    p.add_argument("title")
    p.add_argument("--what", help="what actually happened")
    p.add_argument("--session", default="", help="session id, e.g. S076")
    p.add_argument("--found-by", default="unknown",
                   choices=["user", "check", "accident", "review", "unknown"],
                   help="how it surfaced — 'user' repeatedly dominates here, which is "
                        "itself the signal worth tracking")
    p.add_argument("--classify", choices=sorted(CLASSIFICATIONS))
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("classify", help="set the taxonomy, and therefore the destination")
    p.add_argument("id")
    p.add_argument("--as", dest="as_", required=True, choices=sorted(CLASSIFICATIONS))
    p.add_argument("--rationale", default="")
    p.set_defaults(func=cmd_classify)

    p = sub.add_parser("route", help="name the target skill or mechanism")
    p.add_argument("id")
    p.add_argument("target")
    p.set_defaults(func=cmd_route)

    p = sub.add_parser("close", help="applied, or rejected with a reason")
    p.add_argument("id")
    p.add_argument("--reject", action="store_true")
    p.add_argument("--rationale", default="")
    p.set_defaults(func=cmd_close)

    p = sub.add_parser("list", help="one line per lesson")
    p.add_argument("--status", choices=STATUSES)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("report", help="the backlog, grouped by destination")
    p.set_defaults(func=cmd_report)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    from portable_cli import run_cli
    raise SystemExit(run_cli(main))
