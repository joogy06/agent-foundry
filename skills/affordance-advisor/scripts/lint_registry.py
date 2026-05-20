#!/usr/bin/env python3
"""lint_registry.py — corpus-contamination guard.

Two passes:

  1. SCHEMA pass — every registry/*.yaml file parses and conforms to the
     closed schema in advise.py. (Validation re-uses the same loader.)

  2. PORTABILITY pass — scan every skill body in ~/.claude/skills/<name>/SKILL.md
     and ~/.codex/skills/<name>/SKILL.md, look for host-native command tokens
     listed in our own registry/*.yaml `command:` fields, and fail if any of
     those tokens appear in a non-registry file.

The portability pass is the real prize. It catches three mistakes:
  - someone copy-pastes a slash command into a portable skill body
  - someone refers to "the /verify command" in a non-registry skill
  - someone removes the no-codex-symlink sentinel and the registry leaks

The script is stdlib-only.

Exit codes:
   0 — both passes clean
   1 — at least one schema or portability violation
   2 — usage error / broken environment

Usage:
  lint_registry.py                              # run both passes, summary stdout
  lint_registry.py --schema-only                # skip portability pass
  lint_registry.py --portability-only           # skip schema pass
  lint_registry.py --skill-roots <dir1> [...]   # override the corpus locations
  lint_registry.py --json                       # machine-readable summary
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# Add the script's own directory to sys.path so we can import advise.py
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import advise  # type: ignore  # noqa: E402


# ─── schema pass ───────────────────────────────────────────────────────────────

def schema_pass(registry_dir: Path) -> Tuple[List[str], List[str]]:
    """Validate every registry/*.yaml file.

    Returns (passed_files, error_messages).
    """
    passed: List[str] = []
    errors: List[str] = []
    if not registry_dir.is_dir():
        errors.append(f"registry directory missing: {registry_dir}")
        return passed, errors
    for fp in sorted(registry_dir.glob("*.yaml")):
        try:
            advise.load_registry(fp)
        except advise.RegistryParseError as e:
            errors.append(f"{fp.name}: {e}")
        except Exception as e:
            errors.append(f"{fp.name}: unexpected error: {e}")
        else:
            passed.append(fp.name)
    return passed, errors


# ─── portability pass ──────────────────────────────────────────────────────────

# Tokens we never want to see in a portable skill body. The contamination
# vector we care about is the Claude-Code slash-command family: if a skill
# body says "run /verify next" and that skill is loaded into Codex (or Gemini),
# the foreign host either follows the suggestion literally (broken) or
# carries noisy text in its skill descriptions.
#
# Binary-prefixed commands like `codex review`, `gh pr create`, `gemini -w`
# are a weaker vector — they typically appear in skills that legitimately
# discuss those CLIs (e.g. codex-orchestration, gh-copilot-cli), and the
# command body is unambiguous in context. We intentionally do NOT flag them.
#
# The lint is a corpus-hygiene check, not a brand-mention check.

def _collect_tokens_from_registry(registry_dir: Path) -> List[str]:
    """Extract distinct slash-command tokens from every registry file.

    For commands starting with '/', the token is the full first word (e.g.
    '/run', '/verify', '/ultrareview', '/autofix-pr'). Binary-prefixed
    commands are deliberately not in this list — see module docstring.
    """
    tokens: set[str] = set()
    for fp in sorted(registry_dir.glob("*.yaml")):
        try:
            data = advise.load_registry(fp)
        except advise.RegistryParseError:
            continue
        for aff in data.get("affordances", []):
            cmd = aff.get("command", "")
            if not cmd or not cmd.startswith("/"):
                continue
            first_word = cmd.split()[0]
            tokens.add(first_word)
    return sorted(tokens)


# Tokens that are common English nouns / path fragments and would generate
# too many false positives. The advisor never has affordances for these.
# Keep this list small and grounded — anything we add here documents a real
# linguistic collision we accepted.
_FALSE_POSITIVE_GUARDS: dict[str, re.Pattern] = {
    # '/run' collides with /run tmpfs mounts in docker contexts. Only flag
    # when followed by a non-path / non-slash character, i.e. a real command.
    "/run": re.compile(r"(?<![\w/])/run(?![\w/-])"),
}


def _scan_body_for_tokens(text: str, tokens: Sequence[str]) -> List[Tuple[str, int]]:
    """Return a list of (token, line_number) hits in `text`.

    For slash-command tokens we require the token to appear at a word boundary
    that is NOT part of an absolute path (so '/var/run' or 'foo/run' won't
    match the '/run' token).

    A hit is suppressed if the surrounding line context shows the token is
    obviously a directory path or a docker mount target (e.g. inside
    ``--tmpfs /run:..``).
    """
    hits: List[Tuple[str, int]] = []
    if not text:
        return hits

    patterns: List[Tuple[re.Pattern, str]] = []
    for t in tokens:
        if t in _FALSE_POSITIVE_GUARDS:
            patterns.append((_FALSE_POSITIVE_GUARDS[t], t))
            continue
        # Default word-boundary regex for slash commands. The negative
        # lookbehind '(?<![\w/])' ensures we don't match inside a path
        # like '/usr/run'; the negative lookahead '(?![\w/-])' ensures we
        # don't match a longer token like '/runner' or '/run/foo'.
        pattern = re.compile(r"(?<![\w/])" + re.escape(t) + r"(?![\w/-])")
        patterns.append((pattern, t))

    # Windows CLIs that use forward-slash flags. When one of these binaries
    # appears on the same line as a slash-token, it's almost certainly a
    # Windows-flag false positive, not a Claude Code slash command.
    win_cli_marker = re.compile(
        r"\b(schtasks|sc|net|netsh|wmic|takeown|icacls|robocopy|xcopy|attrib|"
        r"reg|dism|sfc|fsutil|bcdedit|diskpart|tasklist|taskkill|where|"
        r"shutdown|rundll32|cmd|powershell|certutil)\b"
    )

    for lineno, line in enumerate(text.splitlines(), start=1):
        line_stripped = line.lstrip()
        # Context filter: docker / shell command examples often contain
        # '--tmpfs /run'. Suppress those.
        suppress_docker_mount = (
            "--tmpfs" in line or
            "--mount" in line or
            line_stripped.startswith("docker ") or
            line_stripped.startswith("podman ") or
            line_stripped.startswith("RUN ")
        )
        # Context filter: Windows CLI flags. When `schtasks /run /tn ...`
        # appears, /run is a schtasks flag, not a slash command.
        suppress_win_flag = bool(win_cli_marker.search(line))

        for pattern, token in patterns:
            m = pattern.search(line)
            if not m:
                continue
            if suppress_docker_mount and token in ("/run",):
                continue
            if suppress_win_flag:
                # Heuristic: any slash-token co-located with a Windows-CLI
                # binary is a Windows flag, not a Claude command. The cost
                # of this filter is that someone writing a portable skill
                # about Claude commands won't be able to also reference
                # `schtasks` on the same line — acceptable.
                continue
            hits.append((token, lineno))
    return hits


def portability_pass(
    registry_dir: Path,
    skill_roots: Sequence[Path],
    exclude_relpaths: Sequence[str] = (),
) -> Tuple[int, List[str]]:
    """Scan every skill body and flag tokens that leak host-native commands.

    Returns (skills_scanned, violations). A violation is a single string like
    "~/.claude/skills/foo/SKILL.md:42: '/verify' (claude-code)".
    """
    tokens = _collect_tokens_from_registry(registry_dir)
    if not tokens:
        return 0, []

    own_skill_dir = registry_dir.parent  # ~/.claude/skills/affordance-advisor
    own_skill_name = own_skill_dir.name

    violations: List[str] = []
    scanned = 0

    for root in skill_roots:
        if not root.is_dir():
            continue
        for skill_md in sorted(root.glob("*/SKILL.md")):
            skill_dir = skill_md.parent
            if skill_dir.name == own_skill_name:
                # The advisor's own SKILL.md is allowed to mention the advisor mechanism,
                # but we still scan it for slash-command tokens.
                # In fact we DO want to scan it — see the design's
                # contamination rule. Continue with scan.
                pass
            try:
                text = skill_md.read_text(encoding="utf-8")
            except OSError:
                continue
            scanned += 1
            hits = _scan_body_for_tokens(text, tokens)
            for token, lineno in hits:
                violations.append(f"{skill_md}:{lineno}: '{token}'")
    return scanned, violations


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    default_roots = [
        Path.home() / ".claude" / "skills",
        Path.home() / ".codex"  / "skills",
    ]

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--schema-only", action="store_true")
    parser.add_argument("--portability-only", action="store_true")
    parser.add_argument("--skill-roots", nargs="*", default=None,
                        help="override list of skill-corpus roots to scan")
    parser.add_argument("--registry-dir", default=None,
                        help="override registry directory (default: sibling of script)")
    parser.add_argument("--json", action="store_true",
                        help="emit a JSON summary instead of plain text")
    args = parser.parse_args()

    registry_dir = Path(args.registry_dir) if args.registry_dir else \
                   (Path(__file__).resolve().parent.parent / "registry")

    skill_roots = [Path(p) for p in args.skill_roots] if args.skill_roots else default_roots

    schema_passed: List[str] = []
    schema_errors: List[str] = []
    portability_scanned = 0
    portability_violations: List[str] = []

    if not args.portability_only:
        schema_passed, schema_errors = schema_pass(registry_dir)

    if not args.schema_only:
        portability_scanned, portability_violations = portability_pass(
            registry_dir, skill_roots
        )

    summary = {
        "schema": {
            "passed": schema_passed,
            "errors": schema_errors,
        },
        "portability": {
            "skills_scanned": portability_scanned,
            "violations": portability_violations,
        },
        "ok": (not schema_errors) and (not portability_violations),
    }

    if args.json:
        sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    else:
        sys.stdout.write("=== Schema pass ===\n")
        for f in schema_passed:
            sys.stdout.write(f"  OK    {f}\n")
        for e in schema_errors:
            sys.stdout.write(f"  FAIL  {e}\n")
        sys.stdout.write(f"\n=== Portability pass ({portability_scanned} skills scanned) ===\n")
        if not portability_violations:
            sys.stdout.write("  clean\n")
        else:
            for v in portability_violations:
                sys.stdout.write(f"  HIT   {v}\n")
        sys.stdout.write("\n")
        sys.stdout.write("OK\n" if summary["ok"] else "FAIL\n")

    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
