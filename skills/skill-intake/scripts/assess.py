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

Exit: 0 nothing blocking · 2 findings that need a decision (also: a custom key set twice
with different values — the message is on stderr, no report) · 3 bad input.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# The security rules are not kept here: they are the in-house rule set of the intake-scan
# skill (`harness_rules`), the same rules `intake.py scan`, the commit hook and the installer
# run. The file is looked for in the tree this script sits in (the repo when run from a
# checkout), then in the installed library. Each caution rule carries its fix, because a
# finding without a remedy just becomes an exemption request.
HARNESS_RULES_GAP = "harness-rules-missing"
_HARNESS_RULES_MODULE = "_skill_intake_harness_rules"
_BLOCK_RULE_FIX = ("a block rule: adoption stops here; run intake.py scan on the whole skill, "
                   "then fix it or record an exception with a reason")


def _harness_rules_candidates() -> List[Path]:
    rel = Path("intake-scan") / "scripts" / "harness_rules.py"
    return [Path(__file__).resolve().parents[2] / rel, Path.home() / ".claude" / "skills" / rel]


def load_harness_rules(candidates: Optional[List[Path]] = None) -> Any:
    """The shared rule set, or None when no copy of it can be loaded."""
    for path in (_harness_rules_candidates() if candidates is None else candidates):
        if not path.is_file():
            continue
        # Loaded under a name of its own, so a copy another module already imported as
        # `harness_rules` is neither reused from elsewhere nor replaced.
        try:
            spec = importlib.util.spec_from_file_location(_HARNESS_RULES_MODULE, str(path))
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[_HARNESS_RULES_MODULE] = module
            spec.loader.exec_module(module)
            return module
        except Exception:  # noqa: BLE001 - an unloadable copy is the same gap as an absent one
            sys.modules.pop(_HARNESS_RULES_MODULE, None)
    return None


def security_scan(text: str, name: str, rules: Any) -> List[Dict[str, Any]]:
    """Security findings on one file from the shared rule set, in the shape this tool has
    always printed: line, issue, match, fix. One finding per rule is enough to act on.

    With no rule set there is nothing to report as clean: the list carries one entry that
    names the gap, so `needs_decision` is set and nobody reads an empty list as a pass.
    """
    if rules is None:
        return [{"line": 0, "issue": f"gap {HARNESS_RULES_GAP}: the security rules did not run",
                 "match": "", "fix": "install the intake-scan skill, then run intake.py scan on the skill"}]
    record = rules.FileRecord("f001", name, 0o644, text.encode("utf-8", "replace"))
    lines = text.split("\n")
    found, seen = [], set()
    for finding in rules.scan([record]):
        if finding.rule_id in seen:
            continue
        seen.add(finding.rule_id)
        rule = rules.RULES[finding.rule_id]
        shown = lines[finding.line - 1].strip() if 0 < finding.line <= len(lines) else ""
        found.append({"line": finding.line, "issue": rule.description, "match": shown[:60],
                      "fix": rule.fix or _BLOCK_RULE_FIX})
    return found


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

# Custom keys may sit at the top level or under `metadata:` (#344). The shared reader lives
# beside this skill in `_meta`; run from a copy that has no `_meta`, only the top level is read.
sys.path.append(str(Path(__file__).resolve().parents[2] / "_meta"))
try:
    import skill_frontmatter  # noqa: E402
except ImportError:
    skill_frontmatter = None


def custom_value(text: str, fm: Dict[str, Any], key: str, path: Path) -> Optional[str]:
    """A custom key's value from either layout; None when absent.

    Raises skill_frontmatter.FrontmatterConflict when the two layouts disagree. A form the
    reader will not guess at falls back to what the top level says.
    """
    if skill_frontmatter is None:
        return fm.get(key)
    fm_text = skill_frontmatter.frontmatter_of(text)
    if fm_text is None:
        return fm.get(key)
    try:
        return skill_frontmatter.value(fm_text, key, path=path)
    except skill_frontmatter.FrontmatterUnsupported:
        return fm.get(key)


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
        if not custom_value(text, fm, f, path):
            structural.append({"issue": f"no `{f}` — needed once a near neighbour exists",
                               "severity": "advisory"})
    if fm.get("name") and fm["name"] != path.parent.name:
        structural.append({"issue": f"name {fm['name']!r} != directory {path.parent.name!r}",
                           "severity": "blocking"})
    if ":" in fm.get("description", "") and not fm["description"].startswith(("'", '"')):
        structural.append({"issue": "unquoted colon in description — breaks stricter YAML parsers",
                           "severity": "blocking"})

    security = security_scan(text, path.name, load_harness_rules())
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

    try:
        r = assess(args.skill, args.skills_root)
    except ValueError as exc:
        # A custom key set at the top level AND under `metadata:` with different values
        # (skill_frontmatter.FrontmatterConflict): a decision for a person, not a traceback.
        if skill_frontmatter is None or not isinstance(exc, skill_frontmatter.FrontmatterConflict):
            raise
        sys.stderr.write(f"skill-intake assess: {exc}\n")
        return 2

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
