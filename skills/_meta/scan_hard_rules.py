#!/usr/bin/env python3
"""
scan_hard_rules.py — SessionStart hook + forge helper.

Scans CLAUDE.md (global + project-local) for hard-rule-style directives and
surfaces any that are NOT reflected in ~/.claude/skills/_meta/hard-rules-checklist.md.

Usage:
    scan_hard_rules.py            # plain markdown output (for forge, CLI)
    scan_hard_rules.py --hook     # emit SessionStart hook JSON on stdout
    scan_hard_rules.py --plain    # explicit plain (same as default)

Design notes:
- Fuzzy token-overlap comparison against the checklist (not exact match).
- Non-fatal: any failure returns a benign "continue" JSON so sessions never break.
- Fast: sub-100ms on a laptop; reads 2-3 small files.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HOME = Path.home()
GLOBAL_CLAUDE_MD = HOME / ".claude" / "CLAUDE.md"
CHECKLIST = HOME / ".claude" / "skills" / "_meta" / "hard-rules-checklist.md"

PROJECT_CLAUDE_MD_CANDIDATES = [
    Path("CLAUDE.md"),
    Path(".claude/CLAUDE.md"),
]

# Patterns that identify a "hard rule" line in a CLAUDE.md file.
HARD_RULE_PATTERNS = [
    re.compile(r"<HARD-RULE>|<HARD-GATE>|HARD RULE|Hard Rules|Hard-Rules"),
    re.compile(
        r"^##+ .*([Ss]ession [Ss]tart|[Hh]ard [Rr]ule|[Mm]andatory|"
        r"[Cc]heckpoint|[Rr]outing|[Aa]utonomy|[Ww]iki [Bb]inding)"
    ),
    re.compile(r"^- \*\*[^*]+\*\*"),
    re.compile(r"^\s*\d+\.\s+\*\*[^*]+\*\*"),
]

STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "into", "each",
    "have", "been", "read", "check", "will", "should", "must", "when",
    "what", "your", "global", "project", "local", "also", "then", "before",
    "after", "file", "files", "would", "could", "their", "them", "they",
    "which", "while", "about", "where", "there", "these", "those", "make",
    "made", "over", "under", "above", "below", "other", "same", "such",
}


def extract_rules(path: Path, label: str) -> list[str]:
    """Extract hard-rule-looking lines from a markdown file."""
    if not path or not path.exists() or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rules: list[str] = []
    for line in text.splitlines():
        for pat in HARD_RULE_PATTERNS:
            if pat.search(line):
                rules.append(f"[{label}] {line.rstrip()}")
                break
    return rules


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def significant_tokens(s: str) -> list[str]:
    return [t for t in normalize(s).split() if len(t) > 3 and t not in STOPWORDS]


def checklist_tokens() -> set[str]:
    if not CHECKLIST.exists():
        return set()
    try:
        text = CHECKLIST.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    tokens: set[str] = set()
    for line in text.splitlines():
        tokens.update(normalize(line).split())
    return tokens


def rule_reflected(rule: str, tokens: set[str]) -> bool:
    """Fuzzy: does the rule share >=50% of its significant tokens with checklist?"""
    sig = significant_tokens(rule)
    if len(sig) < 3:
        return True  # too little signal, assume covered
    hits = sum(1 for t in sig if t in tokens)
    return hits / len(sig) >= 0.5


def find_project_claude_md() -> Path | None:
    for cand in PROJECT_CLAUDE_MD_CANDIDATES:
        try:
            if cand.exists() and cand.is_file():
                return cand.resolve()
        except OSError:
            continue
    return None


def build_context(all_rules: list[str], missing: list[str]) -> str:
    header = (
        "## Hard Rule Scan (CLAUDE.md → hard-rules-checklist)\n\n"
        "Scanned CLAUDE.md (global + project-local) for hard-rule directives and "
        "compared against `~/.claude/skills/_meta/hard-rules-checklist.md`.\n\n"
    )

    if not all_rules:
        return header + "No hard-rule directives found. No action needed.\n"

    if not missing:
        return (
            header
            + f"All {len(all_rules)} extracted directive(s) appear to be reflected "
            "in the checklist. No action needed.\n"
        )

    return (
        header
        + f"Found **{len(all_rules)}** directive(s); **{len(missing)} may be missing** "
        "from the checklist.\n\n"
        "**Action** — at the first natural opportunity this session (or forge Step 1), "
        "surface these to the user and ask whether to: "
        "(a) add to `hard-rules-checklist.md`, "
        "(b) wire into a skill, or "
        "(c) apply ad-hoc this session.\n\n"
        "### Potentially missing directives\n\n"
        "```\n" + "\n".join(missing) + "\n```\n\n"
        f"### Checklist path\n`{CHECKLIST}`\n"
    )


def emit_hook_json(context: str) -> None:
    out = {
        "continue": True,
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        },
    }
    sys.stdout.write(json.dumps(out))
    sys.stdout.write("\n")


def emit_benign_hook_json() -> None:
    sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
    sys.stdout.write("\n")


def main() -> int:
    # Drain stdin if piped (hook protocol) so we don't block.
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:
        pass

    hook_mode = "--hook" in sys.argv

    try:
        global_rules = extract_rules(GLOBAL_CLAUDE_MD, "global")
        project_path = find_project_claude_md()
        project_label = f"project:{project_path}" if project_path else "project"
        project_rules = extract_rules(project_path, project_label) if project_path else []
        all_rules = global_rules + project_rules

        tokens = checklist_tokens()
        missing = [r for r in all_rules if not rule_reflected(r, tokens)]
        context = build_context(all_rules, missing)

        if hook_mode:
            # Only inject context if there's something actionable.
            if missing:
                emit_hook_json(context)
            else:
                emit_benign_hook_json()
        else:
            sys.stdout.write(context)
            if not context.endswith("\n"):
                sys.stdout.write("\n")
        return 0
    except Exception as exc:  # never break a session
        if hook_mode:
            emit_benign_hook_json()
        else:
            sys.stderr.write(f"scan_hard_rules: {exc}\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
