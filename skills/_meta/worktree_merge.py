#!/usr/bin/env python3
"""worktree_merge.py — S055 §6.6 / R17 controlled merge step.

A deterministic MAIN-LOOP step (Bash-invoked) that applies a worker stage's
worktree diff to the canonical tree and REJECTS any diff touching the
forbidden-path list (CB4 protection — filesystem-shaped, not prompt-only). A
rejected diff fails that worker's WP (`needs: user-decision`); it never silently
drops files. The merge is idempotent (re-applicable diffs).

Forbidden paths (a diff touching ANY of these is rejected outright):
  .ledger/**                       (bob-only ledger machinery, CB4)
  progress/integration-ledger.md   (bob-only, CB4)
  .bob-checkpoint.md               (bob's resume contract)
  progress/work-packages.yaml      (the frozen plan; bob-only)
  .forge/session.key               (signing key custody, W-KEY/D1)
  progress/workflow-runs.jsonl     (main-loop sole-writer dispatch log)

CLI:
  worktree_merge.py check  --diff <unified-diff-file>          # exit 0 clean / 2 forbidden
  worktree_merge.py apply  --worktree <dir> --canonical <dir>  # apply via `git -C apply`
                           [--diff <file>]                     # or supply a precomputed diff
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

FORBIDDEN_PATTERNS = [
    re.compile(r"^\.ledger/"),
    re.compile(r"^progress/integration-ledger\.md$"),
    re.compile(r"^\.bob-checkpoint\.md$"),
    re.compile(r"^progress/work-packages\.yaml$"),
    re.compile(r"^\.forge/session\.key$"),
    re.compile(r"^progress/workflow-runs\.jsonl$"),
]


def _is_forbidden(path: str) -> bool:
    # Normalize a leading "./" ONLY (do NOT lstrip("./") — that would also eat
    # the leading dot of ".ledger" / ".bob-checkpoint.md").
    p = path
    while p.startswith("./"):
        p = p[2:]
    return any(rx.search(p) for rx in FORBIDDEN_PATTERNS)


_DIFF_PATH_RE = re.compile(r"^\+\+\+ (?:b/)?(.+?)\s*$")
_DIFF_OLD_RE = re.compile(r"^--- (?:a/)?(.+?)\s*$")
_GIT_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)\s*$")


def paths_in_diff(diff_text: str) -> List[str]:
    """Extract every file path a unified/git diff touches (both +++ and ---
    sides, plus git-diff headers — so a forbidden path is caught even on
    delete/rename)."""
    out: List[str] = []
    for line in diff_text.splitlines():
        m = _GIT_DIFF_HEADER_RE.match(line)
        if m:
            out.extend([m.group(1), m.group(2)])
            continue
        m = _DIFF_PATH_RE.match(line)
        if m and m.group(1) != "/dev/null":
            out.append(m.group(1))
            continue
        m = _DIFF_OLD_RE.match(line)
        if m and m.group(1) != "/dev/null":
            out.append(m.group(1))
    return out


def check_diff(diff_text: str) -> Tuple[bool, List[str]]:
    """Return (clean, forbidden_hits). clean is True iff NO touched path is
    forbidden."""
    touched = paths_in_diff(diff_text)
    forbidden = sorted({p for p in touched if _is_forbidden(p)})
    return (len(forbidden) == 0, forbidden)


def compute_worktree_diff(worktree: Path, canonical: Path) -> str:
    """Compute the diff of a worktree against the canonical tree. Uses
    `git -C <worktree> diff` against HEAD if it is a git worktree; else falls
    back to a recursive `diff -ruN`. Deterministic ordering."""
    # Prefer git (handles renames/deletes cleanly).
    try:
        r = subprocess.run(
            ["git", "-C", str(worktree), "diff", "HEAD"],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    # Fallback: plain recursive diff.
    r = subprocess.run(
        ["diff", "-ruN", str(canonical), str(worktree)],
        capture_output=True, text=True, timeout=120,
    )
    return r.stdout


def apply_diff(canonical: Path, diff_text: str) -> Tuple[bool, str]:
    """Apply diff_text to the canonical tree via `git -C apply`. Returns
    (ok, message). Refuses (does not apply) if the diff is forbidden."""
    clean, forbidden = check_diff(diff_text)
    if not clean:
        return (False, f"REJECTED: diff touches forbidden paths: {forbidden}")
    proc = subprocess.run(
        ["git", "-C", str(canonical), "apply", "--3way", "-"],
        input=diff_text, capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        # Retry without 3way (e.g. canonical not a git repo) via patch.
        proc2 = subprocess.run(
            ["patch", "-p1", "-d", str(canonical)],
            input=diff_text, capture_output=True, text=True, timeout=120,
        )
        if proc2.returncode != 0:
            return (False, f"apply failed: {proc.stderr or proc2.stderr}")
    return (True, "applied")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="S055 controlled worktree merge (forbidden-path rejection).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check")
    pc.add_argument("--diff", required=True, help="unified/git diff file")

    pa = sub.add_parser("apply")
    pa.add_argument("--worktree", help="worktree dir (diff computed against --canonical)")
    pa.add_argument("--canonical", required=True, help="canonical tree to apply into")
    pa.add_argument("--diff", help="precomputed diff file (skips computation)")

    args = ap.parse_args(argv)

    if args.cmd == "check":
        diff_text = Path(args.diff).read_text()
        clean, forbidden = check_diff(diff_text)
        if clean:
            sys.stdout.write("clean\n")
            return 0
        sys.stdout.write(f"REJECTED: forbidden paths: {forbidden}\n")
        return 2

    if args.cmd == "apply":
        canonical = Path(args.canonical)
        if args.diff:
            diff_text = Path(args.diff).read_text()
        elif args.worktree:
            diff_text = compute_worktree_diff(Path(args.worktree), canonical)
        else:
            sys.stderr.write("apply requires --diff or --worktree\n")
            return 2
        ok, msg = apply_diff(canonical, diff_text)
        sys.stdout.write(msg + "\n")
        return 0 if ok else 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
