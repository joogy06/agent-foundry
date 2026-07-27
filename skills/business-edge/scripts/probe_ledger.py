#!/usr/bin/env python3
"""probe_ledger.py — append-only probe ledger for business-edge scans.

Enforces the one rule that matters: only SEARCHED_NOT_FOUND supports a claim of
absence. Everything else is missing data, and `coverage` reports it as such.

Deterministic, stdlib-only, no network. Usage:

    probe_ledger.py add    --entity X --surface reddit --query "..." --status BLOCKED [--tool browser] [--note "..."]
    probe_ledger.py list   --entity X [--surface reddit]
    probe_ledger.py coverage --entity X          # per-surface verdict + absence-claim safety
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ("FOUND", "SEARCHED_NOT_FOUND", "BLOCKED", "CAPTCHA", "FAILED", "NOT_PROBED")
#: The ONLY status from which absence may be inferred.
ABSENCE_SAFE = "SEARCHED_NOT_FOUND"
#: Statuses meaning "the probe did not actually complete" — missing data, not evidence.
INCONCLUSIVE = ("BLOCKED", "CAPTCHA", "FAILED", "NOT_PROBED")


def ledger_path(root: str | None, entity: str) -> Path:
    base = Path(root) if root else Path.cwd() / ".business-edge"
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in entity.lower())[:64]
    return base / "probes" / f"{safe}.jsonl"


def cmd_add(a: argparse.Namespace) -> int:
    if a.status not in STATUSES:
        print(f"error: status must be one of {', '.join(STATUSES)}", file=sys.stderr)
        return 2
    path = ledger_path(a.root, a.entity)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entity": a.entity,
        "surface": a.surface,
        "query": a.query,
        "status": a.status,
        "tool": a.tool,
        "note": a.note,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{a.status:19s} {a.surface:22s} {a.query}")
    return 0


def _load(a: argparse.Namespace) -> list[dict]:
    path = ledger_path(a.root, a.entity)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a corrupt row must not hide the rest of the ledger
    return rows


def cmd_list(a: argparse.Namespace) -> int:
    rows = [r for r in _load(a) if not a.surface or r.get("surface") == a.surface]
    if not rows:
        print("no probes recorded — coverage is UNKNOWN, not empty")
        return 0
    for r in rows:
        print(f"{r['ts']}  {r['status']:19s} {r.get('surface',''):22s} {r.get('query','')}")
    return 0


def cmd_coverage(a: argparse.Namespace) -> int:
    rows = _load(a)
    if not rows:
        print("no probes recorded — coverage is UNKNOWN, not empty")
        return 0

    surfaces: dict[str, list[str]] = {}
    for r in rows:
        surfaces.setdefault(r.get("surface", "?"), []).append(r.get("status", "?"))

    print(f"{'SURFACE':24s} {'VERDICT':16s} DETAIL")
    print("-" * 78)
    unsafe = []
    for surface in sorted(surfaces):
        sts = surfaces[surface]
        if "FOUND" in sts:
            verdict = "PRESENT"
        elif ABSENCE_SAFE in sts:
            verdict = "ABSENT"
        else:
            verdict = "UNKNOWN"
            unsafe.append(surface)
        counts = ", ".join(f"{s}x{sts.count(s)}" for s in sorted(set(sts)))
        print(f"{surface:24s} {verdict:16s} {counts}")

    print()
    if unsafe:
        print("WARNING — absence MUST NOT be claimed for these surfaces:")
        for s in unsafe:
            print(f"  - {s}: probed but never completed ({', '.join(INCONCLUSIVE)})")
        print("\nReport them as UNKNOWN. A failed probe is missing data, not evidence of absence.")
        return 1
    print("All probed surfaces reached a conclusive state. Absence claims are supported.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="business-edge probe ledger")
    p.add_argument("--root", help="ledger root (default ./.business-edge)")
    sub = p.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="record one probe")
    add.add_argument("--entity", required=True)
    add.add_argument("--surface", required=True)
    add.add_argument("--query", required=True)
    add.add_argument("--status", required=True, help=f"one of: {', '.join(STATUSES)}")
    add.add_argument("--tool", default="")
    add.add_argument("--note", default="")
    add.set_defaults(func=cmd_add)

    lst = sub.add_parser("list", help="list recorded probes")
    lst.add_argument("--entity", required=True)
    lst.add_argument("--surface")
    lst.set_defaults(func=cmd_list)

    cov = sub.add_parser("coverage", help="per-surface verdict + absence-claim safety")
    cov.add_argument("--entity", required=True)
    cov.set_defaults(func=cmd_coverage)

    a = p.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
