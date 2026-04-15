#!/usr/bin/env python3
"""
forge_reminder_hook.py — SessionStart hook that always injects a forge routing reminder.

Prevents the recurring problem where Claude skips forge and goes straight to coding.
This hook fires on EVERY session start, not just when hard-rule mismatches are found.

Usage:
    forge_reminder_hook.py --hook    # emit SessionStart hook JSON on stdout
"""

from __future__ import annotations

import json
import sys


REMINDER = """\
## Forge Routing Reminder (auto-injected every session)

**Autonomy**: Already configured globally (acceptEdits + Bash(*) + git push ask). Do NOT ask the user about autonomy mode.

**Forge routing**: Always-on per CLAUDE.md. Route tasks automatically:
- TRIVIAL (typo, config) → handle directly
- SIMPLE (single-file, clear output) → domain skill directly
- MEDIUM (2-3 files, some decisions) → forge (simple complexity)
- COMPLEX (architecture, cross-layer) → full forge cycle (design team + challengers + bob)

**Critical**: Do NOT skip forge for MEDIUM/COMPLEX tasks. Do NOT write implementation code yourself for MEDIUM/COMPLEX — forge spawns bob for that. If you catch yourself about to write code for a multi-file task without having run forge, STOP and invoke forge first.
"""


def main() -> int:
    # Drain stdin if piped (hook protocol).
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:
        pass

    if "--hook" not in sys.argv:
        sys.stdout.write(REMINDER)
        return 0

    out = {
        "continue": True,
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": REMINDER,
        },
    }
    sys.stdout.write(json.dumps(out))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
