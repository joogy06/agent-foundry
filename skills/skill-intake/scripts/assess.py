#!/usr/bin/env python3
"""assess.py — S074. Mechanical assessment of an incoming skill.

Reports what CAN be measured about a skill arriving from outside: how much its description
overlaps existing ones, which patterns will trip an enterprise security scanner, what
portability assumptions it makes, and whether it conforms structurally.

WHAT THIS DELIBERATELY CANNOT DO

It cannot tell you whether the skill is any good. Value is the BEHAVIOUR CHANGE a skill
causes, and that is not extractable from text — it needs the empirical check in SKILL.md
§3: run a task the skill claims to improve, with and without it loaded, and see whether the
answer differs. A tool that scored "value" from wordcount and heading structure would be
confidently wrong and would be trusted anyway, so it does not offer a score.

What it does is remove the mechanical work so the human judgement has somewhere to start.

Exit: 0 nothing blocking · 2 findings that need a decision · 3 bad input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Patterns that cause enterprise scanner blocks. Each carries the fix, because a finding
# without a remedy just becomes an exemption request.
SECURITY_PATTERNS = [
    (r"\bcurl\b[^\n|]*\|\s*(ba)?sh", "curl piped into a shell",
     "name the URL as a reference; let a human fetch and review it"),
    (r"\b(curl|wget)\s+https?://(?!example\.|localhost)", "network fetch to a live host",
     "move the fact into a version-stamped reference file with a REVIEW_BY date"),
    (r"\beval\s*\(", "dynamic evaluation", "replace with an explicit dispatch"),
    (r"\bbase64\s+-d\b|\bbase64\.b64decode", "base64 decode of embedded data",
     "inline the content readably, or reference a file"),
    (r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*[\"'][A-Za-z0-9/+=_-]{16,}[\"']",
     "credential-shaped literal", "use an obvious placeholder such as <API_KEY>"),
    (r"/(home|Users)/[a-z][a-z0-9_-]{2,}/", "absolute path to a developer machine",
     "use a relative path or an environment variable"),
    (r"(?i)\b(disable|bypass|skip|turn off)\s+(the\s+)?(security|scanner|check|gate|verification)\b",
     "instruction to disable a safety control", "remove it; a workaround here is a permanent hole"),
    (r"(?i)\bchmod\s+777\b", "world-writable permissions", "use the narrowest mode that works"),
]

PORTABILITY_PATTERNS = [
    (r"(?i)\bmcp__[a-z0-9_]+", "harness-specific MCP tool name",
     "state the capability and name the tool as one option"),
    (r"(?i)\b(claude code|claude-code)\b", "assumes a specific CLI",
     "describe the capability so other harnesses can map it"),
    (r"~/\.claude/", "assumes this library's install location",
     "acceptable inside this library; must be parameterised if the skill is shared out"),
    (r"(?i)\bapt-get\b|\byum\b|\bbrew\b", "assumes a package manager",
     "state the dependency; do not assume how it is installed"),
]

REQUIRED_FIELDS = ("name", "description")
RECOMMENDED_FIELDS = ("disambiguation",)


def parse_frontmatter(text: str) -> Dict[str, Any]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    out: Dict[str, Any] = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([a-zA-Z_-]+):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def tokens(text: str) -> set:
    stop = {"use", "when", "the", "a", "an", "and", "or", "to", "for", "of", "in", "on",
            "with", "is", "are", "this", "that", "it", "as", "by", "from", "any", "all"}
    return {w for w in re.findall(r"[a-z][a-z-]{2,}", text.lower()) if w not in stop}


def overlap_scan(desc: str, skills_root: Path) -> List[Dict[str, Any]]:
    """Jaccard against every existing description. Crude on purpose — it points, it does not rank."""
    incoming = tokens(desc)
    if not incoming:
        return []
    out = []
    for md in sorted(skills_root.glob("*/SKILL.md")):
        fm = parse_frontmatter(md.read_text(errors="ignore")[:8000])
        other = tokens(fm.get("description", ""))
        if not other:
            continue
        j = len(incoming & other) / max(1, len(incoming | other))
        if j >= 0.15:
            out.append({"skill": md.parent.name, "similarity": round(j, 3)})
    return sorted(out, key=lambda x: -x["similarity"])[:8]


def scan(body: str, patterns) -> List[Dict[str, str]]:
    found = []
    for pat, label, fix in patterns:
        for m in re.finditer(pat, body):
            line = body[:m.start()].count("\n") + 1
            found.append({"line": line, "issue": label, "match": m.group(0)[:60], "fix": fix})
            break  # one per pattern is enough to act on
    return found


def assess(path: Path, skills_root: Path) -> Dict[str, Any]:
    text = path.read_text(errors="ignore")
    fm = parse_frontmatter(text)

    structural = []
    for f in REQUIRED_FIELDS:
        if not fm.get(f):
            structural.append({"issue": f"missing required frontmatter `{f}`", "severity": "blocking"})
    for f in RECOMMENDED_FIELDS:
        if not fm.get(f):
            structural.append({"issue": f"no `{f}` — needed once a near neighbour exists",
                               "severity": "advisory"})
    if fm.get("name") and fm["name"] != path.parent.name:
        structural.append({"issue": f"name {fm['name']!r} != directory {path.parent.name!r}",
                           "severity": "blocking"})
    if ":" in fm.get("description", "") and not fm["description"].startswith(("'", '"')):
        structural.append({"issue": "unquoted colon in description — breaks stricter YAML parsers",
                           "severity": "blocking"})

    security = scan(text, SECURITY_PATTERNS)
    portability = scan(text, PORTABILITY_PATTERNS)
    near = overlap_scan(fm.get("description", ""), skills_root) if skills_root.is_dir() else []

    blocking = [s for s in structural if s["severity"] == "blocking"]
    return {
        "skill": path.parent.name,
        "declared_name": fm.get("name"),
        "lines": text.count("\n") + 1,
        "structural": structural,
        "security": security,
        "portability": portability,
        "nearest_existing": near,
        "needs_decision": bool(blocking or security or near),
        "value_note": (
            "This tool measures shape, overlap and risk. It CANNOT judge whether the skill adds "
            "capability — that is the behavioural test in SKILL.md §3: run a task the skill claims "
            "to improve with and without it loaded. If deleting it would change nothing, it is "
            "documentation, not a skill."
        ),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Assess an incoming skill before adoption.")
    ap.add_argument("--skill", type=Path, required=True, help="path to the incoming SKILL.md")
    ap.add_argument("--skills-root", type=Path, default=Path.home() / ".claude" / "skills")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not args.skill.is_file():
        sys.stderr.write(f"INTAKE_ENV_ERROR: no such file: {args.skill}\n")
        return 3

    r = assess(args.skill, args.skills_root)

    if args.json:
        print(json.dumps(r, indent=2))
    else:
        print(f"SKILL INTAKE: {r['skill']} ({r['lines']} lines)\n")
        if r["structural"]:
            print("  STRUCTURE")
            for s in r["structural"]:
                print(f"    [{s['severity']:<9}] {s['issue']}")
        if r["security"]:
            print("\n  SECURITY — these trip enterprise scanners")
            for s in r["security"]:
                print(f"    line {s['line']}: {s['issue']}\n        found: {s['match']}\n        fix: {s['fix']}")
        if r["portability"]:
            print("\n  PORTABILITY — assumptions that may not hold elsewhere")
            for s in r["portability"]:
                print(f"    line {s['line']}: {s['issue']}\n        fix: {s['fix']}")
        if r["nearest_existing"]:
            print("\n  NEAREST EXISTING — high similarity means MERGE, not ADOPT")
            for n in r["nearest_existing"]:
                print(f"    {n['similarity']:.2f}  {n['skill']}")
        if not any((r["structural"], r["security"], r["portability"], r["nearest_existing"])):
            print("  no structural, security, portability or overlap findings")
        print(f"\n  {r['value_note']}")

    return 2 if r["needs_decision"] else 0


if __name__ == "__main__":
    sys.exit(main())
