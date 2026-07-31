#!/usr/bin/env python3
"""pre-push hook, in Python (#250) -- identity gate, then the secrets scan.

Two arms, in this order, unchanged from the /bin/sh hook this replaces:

  1. identity gate -- repo<->live `_meta` drift. Fail CLOSED on drift (exit 1).
  2. secrets scan over the WORKTREE. CRITICAL/HIGH block.

THE FAIL-OPEN, PRESERVED ON PURPOSE
-----------------------------------
A missing scanner lets the push through with a WARN, while the pre-commit hook
BLOCKS in the same situation. That asymmetry is real, it is almost certainly wrong,
and it is reproduced here EXACTLY.

Changing it during a port would be the worst way to fix it: the change would ride
in as an unreviewed side effect of "make it Python", and the person who later hit a
blocked push would have no way to tell whether it was intended. The current answer
is frozen as a golden fixture (`missing_scanner_FAILS_OPEN_today`) so the decision
is visible, and it is tracked as #260. Fix it as a decision, in its own commit.

WHICH SCANNER RUNS
------------------
`secrets-scan.py`, not `secrets-scan.sh`. The .sh arm is what made #239 possible in
the first place -- two catalogues gating two different moments, drifting apart in
ways no output comparison could show -- and #272 later found them disagreeing in the
opposite direction. Pointing push-time and commit-time at ONE scanner removes the
divergence class rather than testing for it. `install-pre-push-hook.py` already made
this choice; this hook keeps it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

MARKER = "# managed-by: foundry-lab/skills/secret-scanning/hooks/pre_push.py"


def _harden_streams() -> None:
    """See pre_commit._harden_streams -- #251. A hook whose output vanishes on a
    cp1252 console while it exits 0 looks exactly like a clean push."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


def _err(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def repo_root() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True).stdout.strip()
        if out:
            return Path(out)
    except (OSError, subprocess.CalledProcessError):
        pass
    return Path.cwd()


def resolve_helper(root: Path, repo_rel: str, home_rel: str) -> Path | None:
    candidate = root / repo_rel
    if candidate.is_file():
        return candidate
    home = Path(os.path.expanduser("~")) / ".claude" / home_rel
    return home if home.is_file() else None


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        return 127, f"could not execute {cmd[0]}: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def identity_arm(root: Path) -> int:
    """Returns 1 to block the push, 0 to continue.

    Only exit code 1 from the gate means DRIFT. Anything else is environmental --
    a gate that cannot verify must not wedge a push, because the failure mode of
    over-blocking here is that people stop using the hook at all.
    """
    # Repo-relative ONLY, deliberately. identity_gate.py is a repo-level tool and
    # install.py does not place it in ~/.claude, so a home fallback would be a
    # branch that can never be taken -- the kind of dead path that reads as
    # coverage. This also fixes a real defect in the hook it replaces: the
    # generated /bin/sh version bakes an ABSOLUTE path to foundry-lab's own
    # scripts/, so installing it in any other repo silently gates that repo on a
    # sibling checkout existing at exactly that location.
    gate = root / "scripts" / "identity_gate.py"
    if not gate.is_file():
        _err("[pre-push] WARN: identity gate not found - skipping identity check")
        return 0

    rc, out = _run([sys.executable, str(gate), "--repo-root", str(root)])
    if rc == 0:
        return 0
    if rc == 1:
        if out.strip():
            _err(out.rstrip())
        _err("[pre-push] BLOCKED by identity gate: repo<->live drift in a "
             "safety-critical _meta file.")
        _err("[pre-push] Reconcile or acknowledge the drift; bypass one push with: "
             "git push --no-verify")
        return 1
    _err(f"[pre-push] WARN: identity gate could not verify (exit {rc}) - "
         "continuing to secrets scan")
    return 0


def secrets_arm(root: Path) -> int:
    scanner = resolve_helper(root, "scripts/secrets-scan.py",
                             "skills/secret-scanning/scripts/secrets-scan.py")
    if scanner is None:
        # Fail OPEN -- see the module docstring. Not an oversight; a frozen
        # incumbent behaviour awaiting a deliberate decision (#260).
        _err("[pre-push] WARN: scanner not found - letting push through")
        return 0

    rc, out = _run([sys.executable, str(scanner), str(root)])
    if out.strip():
        _err(out.rstrip())
    return rc


def main() -> int:
    _harden_streams()
    # git writes "<local ref> <local sha> <remote ref> <remote sha>" per ref on
    # stdin. Neither arm needs it -- both scan the worktree -- but it is drained so
    # git never sees EPIPE on a hook that exits early.
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except (OSError, ValueError):
        pass

    root = repo_root()
    if identity_arm(root):
        return 1
    return secrets_arm(root)


if __name__ == "__main__":
    sys.exit(main())
