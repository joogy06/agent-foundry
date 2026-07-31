#!/usr/bin/env python3
"""cross-project-mail SessionStart hook — portable twin of session-start.sh (S075).

Behaviourally identical to the bash version, in Python so it runs on Windows,
where neither `bash` nor `find` can be assumed. The .sh stays as the POSIX
default: it is already deployed and its command string is the dedup identity in
settings.json, so replacing it everywhere would duplicate hooks on every
existing install for no gain.

Budget: <100ms. A directory listing and a count — no parsing, no mailbox reads.

ALWAYS EXITS 0. A session must never fail to start because the mail count could
not be produced; silence is the correct degradation, and it is why every failure
path here returns quietly rather than reporting.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def detect_project(cpmail: str) -> str:
    """Ask the CLI, exactly as the bash hook does. Silent on any failure."""
    try:
        p = subprocess.run([cpmail, "_detect-project"], capture_output=True,
                           text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (p.stdout or "").strip() if p.returncode == 0 else ""


def unread_count(inbox: Path) -> int:
    """*.md directly under the inbox. Deliberately NOT recursive — .acked/ lives
    beneath it and those messages are, by definition, no longer unread."""
    try:
        return sum(1 for e in inbox.iterdir() if e.is_file() and e.suffix == ".md")
    except OSError:
        return 0


def main() -> int:
    mailbox = Path(os.environ.get("AI_MAILBOX", Path.home() / ".ai-mailbox"))
    cpmail = os.environ.get("CPMAIL_BIN", "cpmail")

    project = detect_project(cpmail)
    if not project:
        return 0

    inbox = mailbox / "inbox" / project
    if not inbox.is_dir():
        return 0

    n = unread_count(inbox)
    if n > 0:
        print(f"[mail] {n} unread for {project} (run: {cpmail} list --unread)")
    return 0


if __name__ == "__main__":
    # #251: harden stdout before main() prints. This hook lives outside _meta, so
    # portable_cli is reached by path rather than by import — and its absence is not
    # allowed to break session start any more than a mail failure is.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_meta"))
        from portable_cli import make_streams_utf8
        make_streams_utf8()
    except Exception:
        pass

    try:
        sys.exit(main())
    except Exception:
        # Never let a mail count break session start.
        sys.exit(0)
