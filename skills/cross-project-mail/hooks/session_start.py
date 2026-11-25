#!/usr/bin/env python3
"""cross-project-mail SessionStart hook -- the one implementation (S075; cpmail watch, 2026-10-30).

`session-start.sh` execs this file, so both hook entries print identical lines.
The .sh stays because its command string is the dedup identity in settings.json.

One `cpmail _hook-counts` call returns the project, the count of new messages
(ack_state unread), the count read but not acked, and the project's watch
setting. Only the non-zero parts are printed:

  [mail] 2 new for P: read and handle them before other work (cpmail list --new)
  [mail] 13 read but not acked for P (cpmail list --unread)
  [mail] watch is on for P: start "cpmail watch-loop" as a background task (run_in_background), restart it after each wake

Budget: <100ms. ALWAYS EXITS 0. A session must never fail to start because the
mail count could not be produced; silence is the correct degradation.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def hook_counts(cpmail: str) -> tuple[str, int, int, bool] | None:
    """(project, new, read, watch_on) from the CLI, or None on any failure."""
    try:
        p = subprocess.run([cpmail, "_hook-counts"], capture_output=True,
                           text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    parts = (p.stdout or "").split()
    if len(parts) != 4:
        return None
    project, new, read, watch = parts
    try:
        return project, int(new), int(read), watch == "on"
    except ValueError:
        return None


def hook_lines(project: str, new: int, read: int, watch_on: bool) -> list[str]:
    lines = []
    if new > 0:
        lines.append(f"[mail] {new} new for {project}: read and handle them before other work "
                     f"(cpmail list --new)")
    if read > 0:
        lines.append(f"[mail] {read} read but not acked for {project} (cpmail list --unread)")
    if watch_on:
        lines.append(f'[mail] watch is on for {project}: start "cpmail watch-loop" as a background '
                     f"task (run_in_background), restart it after each wake")
    return lines


def main() -> int:
    cpmail = os.environ.get("CPMAIL_BIN", "cpmail")
    got = hook_counts(cpmail)
    if got is None:
        return 0
    for line in hook_lines(*got):
        print(line)
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
