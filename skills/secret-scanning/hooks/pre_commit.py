#!/usr/bin/env python3
"""pre-commit hook, in Python (#250) -- refuse a commit that stages a problem.

Three arms, in the order a blocker should stop you, unchanged from the bash hook
this replaces:

  1. SKILL.md frontmatter (#237)     -- E blocks, W advises
  2. portability lint (#249/#251)    -- E blocks, W advises
  3. secrets scan, --staged          -- any finding blocks

WHY IT IS PYTHON NOW
--------------------
Keeping bash solely for the security hooks preserves exactly the dependency class
#261 exists to remove. The Windows laptop had no gate at all (#250): `.git/hooks`
held only samples, so every commit and push there was unscanned -- and a bash hook
that Git-for-Windows may or may not run is not the shape to fix that with.

WHAT IS DELIBERATELY IDENTICAL
------------------------------
The observable contract, pinned per-scenario in tests/hooks/. Exit codes and the
BLOCKED/WARN decisions were frozen as golden fixtures BEFORE this file was written
(#262), and the suite runs every scenario against BOTH implementations. That is
what makes "the same hook" a measured claim rather than a hopeful one.

Two behaviours are load-bearing and easy to lose in a port:

  * MISSING SCANNER FAILS CLOSED. An enforcement hook that silently skips is worse
    than no hook: it advertises protection that is not there. `--no-verify` remains
    the deliberate escape hatch.
  * WARNINGS DO NOT BLOCK. A check that fires on ~600 pre-existing sites you did
    not touch is how people learn to reach for `--no-verify`, which costs more than
    the warnings buy.

STREAM HARDENING IS NOT OPTIONAL HERE
-------------------------------------
This hook PRINTS the output of the linters, and that output contains em-dashes. On
a cp1252 Windows console an unhardened write raises UnicodeEncodeError -- and #251's
signature failure was exit 0 with NO output, which is indistinguishable from a clean
run. A secrets hook that silently prints nothing and exits 0 is the worst possible
failure mode, so the streams are hardened before anything is written.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

MARKER = "# managed-by: foundry-lab/skills/secret-scanning/hooks/pre_commit.py"

# Frontmatter lint indents its findings; portability lint does not. Both are
# compiled with the MULTILINE FLAG rather than passed as a positional argument --
# `Pattern.search(string, re.MULTILINE)` passes 8 as POS and silently disables the
# anchor, which is precisely how a CRITICAL secrets rule sat inert (#272).
FRONTMATTER_ERROR = re.compile(r"^  E[0-9]", re.MULTILINE)
FRONTMATTER_WARN = re.compile(r"^  W[0-9]", re.MULTILINE)
PORTABILITY_ERROR = re.compile(r"^E[0-9]", re.MULTILINE)
PORTABILITY_WARN = re.compile(r"^W[0-9]", re.MULTILINE)


def _harden_streams() -> None:
    """UTF-8 with backslashreplace, before a single byte is written.

    `backslashreplace`, never `replace`: both survive the encode, but `replace`
    yields '?' and destroys the evidence needed to find the offending site.
    Uses portable_cli when it resolves, and degrades to the same call inline when
    it does not -- a hook must not depend on the harness being installed.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass  # a stream without reconfigure (pytest capture, a pipe) is fine


def _err(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def repo_root() -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(out) if out else None


def resolve_helper(root: Path, repo_rel: str, home_rel: str) -> Path | None:
    """Repo copy first, then the installed harness copy.

    Repo-first matters: a repo that vendors its own scanner must be gated by THAT
    one, not by whatever happens to be in the developer's home tree.
    """
    candidate = root / repo_rel
    if candidate.is_file():
        return candidate
    home = Path(os.path.expanduser("~")) / ".claude" / home_rel
    return home if home.is_file() else None


def staged_paths(root: Path, suffix: str = "", name: str = "") -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--name-only",
             "--diff-filter=ACM"],
            capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    hits = []
    for line in (l.strip() for l in out.splitlines() if l.strip()):
        if name and Path(line).name != name:
            continue
        if suffix and not line.endswith(suffix):
            continue
        hits.append(line)
    return hits


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        return 127, f"could not execute {cmd[0]}: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_lint_arm(root: Path, *, repo_rel: str, home_rel: str, paths: list[str],
                 error_re: re.Pattern, warn_re: re.Pattern,
                 blocked_message: list[str]) -> int:
    """One lint arm. Returns 1 to block, 0 to continue.

    A missing linter is NOT a block. Unlike the scanner, these arms are quality
    gates rather than the security gate, and refusing every commit in a repo that
    does not vendor them would make the hook unusable where it is most needed.
    """
    if not paths:
        return 0
    linter = resolve_helper(root, repo_rel, home_rel)
    if linter is None:
        return 0
    _rc, out = _run([sys.executable, str(linter), "check", *paths])
    if error_re.search(out):
        _err(out)
        _err("")
        for line in blocked_message:
            _err(line)
        return 1
    if warn_re.search(out):
        _err(out)
    return 0


def main() -> int:
    _harden_streams()

    root = repo_root()
    if root is None:
        return 0  # not a git repo: nothing to gate, and never wedge the caller

    # --- Arm 1: SKILL.md frontmatter (#237) ---------------------------------
    # Claude Code's loader tolerates YAML that yaml.safe_load and Codex reject, so
    # a broken skill is invisible here and MISSING there. Landed twice before.
    rc = run_lint_arm(
        root,
        repo_rel="skills/_meta/frontmatter_lint.py",
        home_rel="skills/_meta/frontmatter_lint.py",
        paths=staged_paths(root, name="SKILL.md"),
        error_re=FRONTMATTER_ERROR, warn_re=FRONTMATTER_WARN,
        blocked_message=[
            "pre-commit: BLOCKED - a staged SKILL.md has invalid frontmatter.",
            "  Commonest cause: an unquoted ': ' inside a value. Quote the value.",
            "  Bypass deliberately with: git commit --no-verify",
        ])
    if rc:
        return rc

    # --- Arm 2: portability lint (#249/#251) --------------------------------
    # Staged files ONLY, deliberately. A tree-wide gate would block every commit
    # on pre-existing findings, and a check that fires on work you did not do is
    # how people learn to reach for --no-verify.
    rc = run_lint_arm(
        root,
        repo_rel="skills/_meta/portability_lint.py",
        home_rel="skills/_meta/portability_lint.py",
        paths=staged_paths(root, suffix=".py"),
        error_re=PORTABILITY_ERROR, warn_re=PORTABILITY_WARN,
        blocked_message=[
            "pre-commit: BLOCKED - a staged .py breaks on another platform.",
            "  E001: guard the import (try/except ImportError), defer it into the",
            "  function, or branch on sys.platform. An unguarded platform-only import",
            "  fails at IMPORT, so it takes down every caller, not just the code path.",
            "  Bypass deliberately with: git commit --no-verify",
        ])
    if rc:
        return rc

    # --- Arm 3: secrets scan (the security gate) ----------------------------
    scanner = resolve_helper(
        root,
        "scripts/secrets-scan.py",
        "skills/secret-scanning/scripts/secrets-scan.py")
    if scanner is None:
        # FAIL CLOSED. The installer refuses to install without a scanner, so
        # reaching here means it was REMOVED afterwards.
        _err("pre-commit: BLOCKED - secrets scanner missing.")
        _err("  expected: $repo/scripts/secrets-scan.py or "
             "~/.claude/skills/secret-scanning/scripts/secrets-scan.py")
        _err("  Restore it, or bypass deliberately with: git commit --no-verify")
        return 1

    status, out = _run([sys.executable, str(scanner), str(root), "--staged"])
    if out.strip():
        _err(out.rstrip())
    if status != 0:
        _err("")
        _err("pre-commit: BLOCKED - staged content matches a secret pattern.")
        _err("  Move the value to ~/.secrets/<project>.env (0600) and load it at runtime.")
        _err("  See: skills/secret-scanning/references/storage-standard.md")
        _err("  If the credential was ever committed, ROTATE it - scrubbing is not rotation.")
    return status


if __name__ == "__main__":
    sys.exit(main())
