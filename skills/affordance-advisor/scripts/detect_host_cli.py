#!/usr/bin/env python3
"""detect_host_cli.py — env-var probe for the active host CLI.

Reads environment variables in a fixed precedence order and prints exactly one
of:
    claude-code | codex | antigravity-cli | copilot-cli | copilot-chat | unknown

The probe is deliberately simple — env vars are the only signal. We do NOT
walk the process tree or inspect PATH, because those signals leak across
nested CLIs (e.g. Codex CLI launched from inside a Claude Code session would
otherwise be misclassified as Claude). Env vars are set by the host on
session start and stay stable for the lifetime of that session.

Usage:
    detect_host_cli.py                  # print the host name, exit 0
    detect_host_cli.py --json           # print {"host_cli": "..."} on stdout
    detect_host_cli.py --verbose        # print which signal matched, on stderr

Exit code is always 0 unless an unrecognised flag is passed. The host name
itself is the signal — callers should branch on the printed token.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Tuple


# Precedence order (most specific signal first). Each tuple is
# (env_var_name, value_predicate, host_name, signal_description).
#
# value_predicate semantics:
#   None       -> just "is set and non-empty"
#   str        -> "equals this exact string"
#   "set"      -> alias for None (set and non-empty)
#
# The first matching signal wins. Order matters — e.g. Claude Code's
# CLAUDECODE=1 is checked before Codex's CODEX_VERSION because a nested
# Codex run inside a Claude session would still have CLAUDECODE set.
_DETECTION_RULES = [
    # Claude Code — official CLAUDECODE=1 marker, set by `claude` on session start
    ("CLAUDECODE",              "1",  "claude-code", "CLAUDECODE=1"),
    ("CLAUDE_CODE_ENTRYPOINT",  None, "claude-code", "CLAUDE_CODE_ENTRYPOINT set"),

    # Codex CLI — CODEX_VERSION populated by the codex binary on launch
    ("CODEX_VERSION",           None, "codex",       "CODEX_VERSION set"),

    # Antigravity CLI (agy) — replaces the retired Gemini CLI for orchestration.
    # TODO(agy): confirm agy host env var. The Antigravity CLI 1.0.4 `agy --help`
    # exposes no documented session/host marker env var, and the antigravity-cli
    # skill does not name one. The entry below is a placeholder name kept so the
    # detection structure is intact; replace "ANTIGRAVITY_CLI_SESSION_ID" with the
    # real marker once verified (check `agy` runtime env, e.g. `agy -p "env | sort"`).
    ("ANTIGRAVITY_CLI_SESSION_ID", None, "antigravity-cli", "ANTIGRAVITY_CLI_SESSION_ID set (TODO(agy): confirm)"),

    # Copilot CLI — set by `copilot` on launch (newer @github/copilot)
    ("COPILOT_CLI_VERSION",     None, "copilot-cli", "COPILOT_CLI_VERSION set"),
    ("GH_COPILOT_TOKEN",        None, "copilot-cli", "GH_COPILOT_TOKEN set"),
]


def detect_from_env(env=None) -> Tuple[str, str]:
    """Return (host_name, signal_description).

    Parameter `env` is an optional mapping to use instead of os.environ. Tests
    pass a synthetic dict; production callers pass nothing.
    """
    if env is None:
        env = os.environ

    for var, expected, host, signal in _DETECTION_RULES:
        val = env.get(var)
        if val is None or val == "":
            continue
        if expected is None or expected == "set":
            return host, signal
        if val == expected:
            return host, signal

    # Copilot Chat — VS Code panel with Copilot extension. This is harder to
    # probe via env alone; we check for VSCODE_PID + TERM_PROGRAM=vscode +
    # a Copilot-extension marker. If we ever see a clean signal we can move
    # this above the loop.
    if env.get("TERM_PROGRAM") == "vscode" and env.get("VSCODE_PID"):
        # Look for any of several Copilot-extension env vars
        copilot_markers = ("GITHUB_COPILOT_CHAT", "VSCODE_COPILOT_CHAT_SESSION")
        for marker in copilot_markers:
            if env.get(marker):
                return "copilot-chat", f"VS Code with Copilot Chat ({marker})"

    return "unknown", "no recognised host signal"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true",
                        help="print a JSON object instead of a bare token")
    parser.add_argument("--verbose", action="store_true",
                        help="print the matched signal to stderr")
    args = parser.parse_args()

    host, signal = detect_from_env()

    if args.verbose:
        sys.stderr.write(f"affordance-advisor: matched {signal} -> {host}\n")

    if args.json:
        sys.stdout.write(json.dumps({"host_cli": host, "signal": signal}) + "\n")
    else:
        sys.stdout.write(host + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
