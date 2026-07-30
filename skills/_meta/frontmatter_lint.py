#!/usr/bin/env python3
"""frontmatter_lint.py — S074 (#237). Every SKILL.md must parse as YAML everywhere.

Claude Code's loader is forgiving. `yaml.safe_load` and Codex CLI's parser are not, and a
skill that loads fine here can be invisible in another harness — which is discovered by
whoever is using that harness, not by whoever wrote the file.

The recurring break is an UNQUOTED COLON-SPACE inside a value:

    disambiguation: The tactical layer: pre-wires, events, the ask.
                                      ^^ YAML now expects a mapping, and errors

This has landed at least twice — `llm-security`'s `Trigger on:` in S040, and
`career-advocacy`'s `disambiguation:` in S074. Both times the FILE was fixed and the CAUSE
was not, because nothing checked.

    lint     parse every skill's frontmatter; report every failure
    check    same, but only files given on argv (for the pre-commit hook)

Checks, in severity order:
  E1  frontmatter missing or not delimited by --- ... ---
  E2  YAML does not parse
  E3  no `name:`, or `name:` does not match the directory
  E4  no `description:`
  W1  description is very short (< 40 chars) — selection quality depends on it
  W2  a value contains ": " and is unquoted — parses today, fragile tomorrow

W2 is the pre-emptive one: it catches the pattern BEFORE a value happens to sit where the
parser chokes.

Stdlib only, and yaml is optional — without it the parse check degrades to a structural
check and SAYS SO rather than passing silently. Exit: 0 clean · 2 findings · 3 bad input.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
    HAVE_YAML = True
except ImportError:                                   # pragma: no cover - env dependent
    HAVE_YAML = False

DEFAULT_ROOT = Path.home() / ".claude" / "skills"
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")
MIN_DESC = 40


def split_frontmatter(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return text[3:end]


def unquoted_colon_values(fm: str) -> list[tuple[str, str]]:
    """Top-level `key: value` lines whose value holds ': ' and is not quoted.

    Block scalars (`>` / `|`) are exempt — the colon is safe inside them, which is exactly
    why several skills in this library use that form for long descriptions.
    """
    out = []
    for line in fm.splitlines():
        m = KEY_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if not val or val[0] in "\"'" or val[0] in ">|":
            continue
        if ": " in val:
            out.append((key, val))
    return out


def lint_file(path: Path) -> list[tuple[str, str]]:
    """Return [(code, message)] — empty means clean."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return [("E1", f"unreadable: {e}")]

    fm = split_frontmatter(text)
    if fm is None:
        return [("E1", "no YAML frontmatter delimited by --- ... ---")]

    findings: list[tuple[str, str]] = []
    data = None
    if HAVE_YAML:
        try:
            data = yaml.safe_load(fm)
        except Exception as e:                        # yaml raises several types
            first = str(e).splitlines()[0]
            return [("E2", f"YAML does not parse: {first}")]
        if not isinstance(data, dict):
            return [("E2", f"frontmatter is {type(data).__name__}, expected a mapping")]

    if data is not None:
        name = data.get("name")
        if not name:
            findings.append(("E3", "no `name:`"))
        elif name != path.parent.name:
            findings.append(("E3", f"`name: {name}` != directory `{path.parent.name}`"))
        desc = data.get("description")
        if not desc:
            findings.append(("E4", "no `description:`"))
        elif len(str(desc)) < MIN_DESC:
            findings.append(("W1", f"description is {len(str(desc))} chars — "
                                   f"selection quality depends on it"))

    for key, val in unquoted_colon_values(fm):
        findings.append(("W2", f"`{key}:` value contains ': ' unquoted — "
                               f"quote it or use a block scalar ({val[:48]}…)"))
    return findings


def report(results: dict[Path, list[tuple[str, str]]], root: Path | None) -> int:
    errors = {p: f for p, f in results.items() if any(c[0].startswith("E") for c in f)}
    warns = {p: f for p, f in results.items()
             if f and p not in errors}
    for p, fs in sorted(errors.items()):
        print(f"FAIL {p}")
        for code, msg in fs:
            print(f"  {code} {msg}")
    for p, fs in sorted(warns.items()):
        print(f"warn {p}")
        for code, msg in fs:
            print(f"  {code} {msg}")

    n = len(results)
    print(f"\nfrontmatter_lint: {n} file(s) · {len(errors)} failing · {len(warns)} with warnings")
    if not HAVE_YAML:
        print("  NOTE: pyyaml is absent, so the PARSE check did not run — structural checks only.")
        print("  This is a degraded result, not a pass.")
    return 2 if (errors or warns) else 0


def cmd_lint(args) -> int:
    root = args.root
    if not root.is_dir():
        sys.exit(f"[input] not a directory: {root}")
    files = sorted(root.glob("*/SKILL.md"))
    if not files:
        sys.exit(f"[input] no */SKILL.md under {root}")
    return report({p: lint_file(p) for p in files}, root)


def cmd_check(args) -> int:
    files = [Path(f) for f in args.files if Path(f).name == "SKILL.md"]
    if not files:
        return 0                                      # nothing relevant staged
    missing = [f for f in files if not f.is_file()]
    if missing:                                       # deleted in this commit
        files = [f for f in files if f.is_file()]
    if not files:
        return 0
    return report({p: lint_file(p) for p in files}, None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lint SKILL.md YAML frontmatter.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lint"); p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.set_defaults(fn=cmd_lint)
    p = sub.add_parser("check"); p.add_argument("files", nargs="*")
    p.set_defaults(fn=cmd_check)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
