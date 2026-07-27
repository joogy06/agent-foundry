#!/usr/bin/env python3
"""impact_scan.py — map and CLASSIFY the impact zone of a proposed removal.

A plain grep answers "where does this name appear". That is the wrong question:
most hits are usually things you MUST NOT delete. This classifies every hit so
the dangerous ones are separated from the ones that look identical to a grep:

    USAGE       actually invokes/depends on it        -> remove or rewrite
    POINTER     routes a reader to it                 -> repoint or delete
    PROHIBITION "do NOT use X"                        -> KEEP (guard rail)
    HISTORY     a dated record of what happened       -> KEEP (dated, not stale)
    LOOKALIKE   shares the name, different thing      -> KEEP (verify first)

Classification is a HEURISTIC and says so: `--strict` exits non-zero while any
USAGE remains, and every run prints the counts it is least sure about.

Deterministic, stdlib-only, no network.

    impact_scan.py --term <retired-thing> --root ~/.claude/skills
    impact_scan.py --term gemini --root ~/.claude/skills --lookalike "Vertex AI,~/.gemini,gemini-3"
    impact_scan.py --term X --root . --exempt legacy/vendored --strict
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

PROHIBITION_RE = re.compile(
    r"(?:do not|don'?t|never|no longer|must not|forbidden|prohibited|"
    r"do NOT reintroduce|avoid|deprecated|retired|removed|deleted)",
    re.IGNORECASE,
)
POINTER_RE = re.compile(
    r"(?:\bsee\b|\brefer to\b|→|->|\bcanonical\b|\bowner\b|\bcovered (?:in|by)\b)",
    re.IGNORECASE,
)
#: A dated line is a record of what happened, not a live instruction.
HISTORY_RE = re.compile(
    r"(?:\b20\d{2}-\d{2}-\d{2}\b|\bas of\b|\bhistoric|\bpreviously\b|"
    r"\bused to\b|\bformerly\b|\bchangelog\b|\bsession\b\s*S\d+)",
    re.IGNORECASE,
)
#: Shell/command/import shapes — the strongest USAGE signal.
USAGE_RE = re.compile(
    r"(?:^\s*[\$>]\s|\b(?:import|from|require|source|exec|run|invoke|call)\b|"
    r"`[^`]*\b{term}\b[^`]*\s+-{{1,2}}\w|--tool\s+{term}\b|\b{term}\s+-{{1,2}}\w)",
)

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache"}
#: Locations that are archival BY DEFINITION. Date-matching alone missed these —
#: an archived ledger entry has no date in the line, only in its path.
HISTORY_PATH_RE = re.compile(
    r"(?:^|/)(?:archive|archives|history|\.archive|changelog|CHANGELOG)(?:/|$|\.)",
    re.IGNORECASE,
)
TEXT_SUFFIXES = {".md", ".py", ".sh", ".yaml", ".yml", ".json", ".toml", ".js", ".ts", ".txt"}


def classify(line: str, term: str, lookalikes: list[str], rel: str = "") -> str:
    """Order matters: the KEEP classes must win over USAGE.

    A line reading "do not reintroduce `gemini -p`" matches a usage pattern but is
    the opposite of a usage. Removing it would delete the guard rail that stops the
    thing coming back.
    """
    for token in lookalikes:
        if token and token.lower() in line.lower():
            return "LOOKALIKE"
    if rel and HISTORY_PATH_RE.search(rel):
        return "HISTORY"
    if PROHIBITION_RE.search(line):
        return "PROHIBITION"
    if HISTORY_RE.search(line):
        return "HISTORY"
    if POINTER_RE.search(line):
        return "POINTER"
    usage = re.compile(USAGE_RE.pattern.format(term=re.escape(term)), re.IGNORECASE | re.MULTILINE)
    if usage.search(line):
        return "USAGE"
    return "USAGE"  # unclassified defaults to the ACTIONABLE class, never to "safe"


def scan(root: Path, term: str, lookalikes: list[str], exempt: set[str]):
    rows, exempted = [], []
    needle = term.lower()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = str(path.relative_to(root))
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if needle not in text.lower():
            continue
        is_exempt = any(e and (rel.startswith(e) or f"/{e}/" in f"/{rel}") for e in exempt)
        for i, line in enumerate(text.splitlines(), 1):
            if needle not in line.lower():
                continue
            entry = (rel, i, classify(line, term, lookalikes, rel), line.strip()[:150])
            (exempted if is_exempt else rows).append(entry)
    return rows, exempted


def main() -> int:
    p = argparse.ArgumentParser(description="map + classify a removal's impact zone")
    p.add_argument("--term", required=True, help="name being retired")
    p.add_argument("--root", action="append", default=[],
                   help="tree to scan (REPEATABLE — pass the repo, the live tree, the published "
                        "mirror and any symlink farm; clearing one tree while another still "
                        "carries it means the next install restores it)")
    p.add_argument("--lookalike", default="",
                   help="comma-separated tokens marking a DIFFERENT thing sharing the name")
    p.add_argument("--exempt", action="append", default=[],
                   help="path prefix deliberately excluded (repeatable) — reported separately, never actioned")
    p.add_argument("--show", default="USAGE,POINTER",
                   help="classes to list in full (default: the actionable ones)")
    p.add_argument("--strict", action="store_true", help="exit 2 while any USAGE remains")
    a = p.parse_args()

    roots = [Path(r).expanduser().resolve() for r in (a.root or ["."])]
    missing = [r for r in roots if not r.is_dir()]
    if missing:
        sys.stderr.write(f"error: root(s) not found: {', '.join(map(str, missing))}\n")
        return 3

    lookalikes = [s.strip() for s in a.lookalike.split(",") if s.strip()]
    rows, exempted, per_root = [], [], {}
    for root in roots:
        r_rows, r_exempt = scan(root, a.term, lookalikes, set(a.exempt))
        # Qualify paths so two trees carrying the same relative file stay distinguishable.
        r_rows = [(f"{root.name}/{rel}", i, c, l) for rel, i, c, l in r_rows]
        r_exempt = [(f"{root.name}/{rel}", i, c, l) for rel, i, c, l in r_exempt]
        per_root[str(root)] = len(r_rows)
        rows += r_rows
        exempted += r_exempt
    counts = Counter(c for _, _, c, _ in rows)

    print(f"IMPACT ZONE for '{a.term}'")
    for r, cnt in per_root.items():
        print(f"  {cnt:5d} lines  {r}")
    print(f"  files touched : {len({r[0] for r in rows})}")
    print(f"  lines matched : {len(rows)}")
    if len(roots) == 1:
        print("  NOTE: ONE tree scanned. Pass --root again for the repo / published mirror /")
        print("        symlink farm — a partial sweep gets undone by the next install or publish.")
    print()
    for cls in ("USAGE", "POINTER", "PROHIBITION", "HISTORY", "LOOKALIKE"):
        verdict = {
            "USAGE": "-> REMOVE or REWRITE",
            "POINTER": "-> REPOINT or DELETE",
            "PROHIBITION": "-> KEEP (guard rail)",
            "HISTORY": "-> KEEP (dated record)",
            "LOOKALIKE": "-> KEEP (different thing)",
        }[cls]
        print(f"  {cls:12s} {counts.get(cls, 0):4d}  {verdict}")

    if exempted:
        print(f"\n  EXEMPT       {len(exempted):4d}  -> NOT ACTIONED "
              f"({', '.join(sorted(a.exempt))}) — record the reason in the decommission record")

    show = {s.strip().upper() for s in a.show.split(",") if s.strip()}
    for cls in ("USAGE", "POINTER", "PROHIBITION", "HISTORY", "LOOKALIKE"):
        if cls not in show:
            continue
        listed = [r for r in rows if r[2] == cls]
        if not listed:
            continue
        print(f"\n{'=' * 74}\n{cls} ({len(listed)})\n{'=' * 74}")
        for rel, ln, _, line in listed:
            print(f"  {rel}:{ln}\n      {line}")

    print("\nClassification is a HEURISTIC. Read every USAGE and LOOKALIKE before acting —")
    print("unclassified lines default to USAGE so nothing dangerous is silently marked safe.")

    if a.strict and counts.get("USAGE"):
        print(f"\nSTRICT: {counts['USAGE']} USAGE reference(s) remain — retirement is INCOMPLETE.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
