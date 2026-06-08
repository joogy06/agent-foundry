#!/usr/bin/env python3
"""Tests for drift_extract.py command extraction (Evergreening v1, S041; task #139).

#139 root cause: the original regex `^\\s+(\\w[\\w-]*)\\s+` could only match tokens that
START with a word character, so flag tokens (`-p`, `--add-dir`, `-c`) in agy/codex
`--help` were NEVER extracted — making every registered flag look "removed" (false
CONFIRMED removals), while wrapped description prose was over-captured (noisy additions).
The real invariant in both help layouts is two-column: `<token><>=2 spaces><description>`.

These are pure-fixture tests (no live --help calls) → run in CI, not manual.
  python3 -m pytest ~/.claude/skills/affordance-advisor/tests/test_drift_extract.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import drift_extract  # noqa: E402

# Real-shape agy 1.0.5 --help (two-column; flags start with '-').
AGY_HELP = """\
Usage of agy:
  --add-dir                       Add a directory to the workspace (repeatable) (default [])
  -c                              Short alias for --continue
  --continue                      Continue the most recent conversation
  --dangerously-skip-permissions  Auto-approve all tool permission requests without prompting
  -i                              Short alias for --prompt-interactive
  --model                         Model for the current CLI session
  -p                              Short alias for --print
  --print                         Run a single prompt non-interactively and print the response
  --print-timeout                 Timeout for print mode wait (default 5m0s)
  --sandbox                       Run in a sandbox with terminal restrictions enabled

Available subcommands:
  changelog       Show changelog and release notes
  install         Configure environment paths and shell settings
  models          List available models
  plugin          Manage plugins (install, uninstall, list, enable, disable)
  update          Update CLI
"""

# Real-shape codex --help (Commands section + wrapped description lines).
CODEX_HELP = """\
Codex CLI

Usage: codex [OPTIONS] [PROMPT]

Commands:
  exec            Run Codex non-interactively [aliases: e]
  review          Run a code review non-interactively
  login           Manage login
  app-server      [experimental] Run the app server or related tooling
  remote-control  [experimental] Manage the app-server daemon with remote control enabled
  cloud           [EXPERIMENTAL] Browse tasks from Codex Cloud and apply changes locally
  exec-server     [EXPERIMENTAL] Run the standalone exec-server service
  features        Inspect feature flags
  apply           Apply the latest diff produced by Codex agent as a `git apply` to your local
                  working tree [aliases: a]
  update          Update Codex to the latest version

Arguments:
  [PROMPT]
          Optional user prompt to start the session
"""


def _agy_extract():
    _, _, pattern = drift_extract.DRIFT_TARGETS["antigravity-cli.yaml"]
    return drift_extract.extract_commands(AGY_HELP, pattern)


def _codex_extract():
    _, _, pattern = drift_extract.DRIFT_TARGETS["codex.yaml"]
    return drift_extract.extract_commands(CODEX_HELP, pattern)


def test_agy_flags_are_extracted():
    """#139: the bedrock flags MUST be captured (they were the false-removal set)."""
    got = _agy_extract()
    for flag in ("-p", "--add-dir", "--sandbox", "-c", "-i", "--model"):
        assert flag in got, f"{flag} missing from agy extraction (the #139 bug)"


def test_agy_subcommands_are_extracted():
    got = _agy_extract()
    for sub in ("changelog", "models", "install", "update"):
        assert sub in got, f"{sub} missing from agy extraction"


def test_agy_prose_and_headers_not_extracted():
    """Section headers + description prose must NOT appear as commands."""
    got = _agy_extract()
    for noise in ("Usage", "Available", "Show", "Run", "Add", "Timeout", "Model"):
        assert noise not in got, f"prose token {noise!r} wrongly extracted from agy help"


def test_codex_subcommands_are_extracted():
    got = _codex_extract()
    for sub in ("exec", "review", "login", "cloud", "exec-server",
                "remote-control", "app-server", "features", "update"):
        assert sub in got, f"{sub} missing from codex extraction"


def test_codex_wrapped_prose_not_extracted():
    """Wrapped description lines (deep indent) must not be captured as commands."""
    got = _codex_extract()
    for noise in ("working", "Optional", "Run", "Manage", "Codex", "the", "to", "your"):
        assert noise not in got, f"prose token {noise!r} wrongly extracted from codex help"


def test_known_floors_present_and_subset_of_extraction():
    """#139 fix (c): each floored CLI's bedrock set must exist AND be satisfied by a
    healthy extraction — otherwise removals can't be trusted."""
    assert hasattr(drift_extract, "KNOWN_FLOORS"), "KNOWN_FLOORS public surface missing"
    floors = drift_extract.KNOWN_FLOORS
    assert floors.get("antigravity-cli.yaml"), "agy floor must be defined"
    assert floors.get("codex.yaml"), "codex floor must be defined"
    assert set(floors["antigravity-cli.yaml"]) <= _agy_extract()
    assert set(floors["codex.yaml"]) <= _codex_extract()


def test_real_flags_not_falsely_removed_end_to_end():
    """The live #139 symptom: registry flags appear 'removed' because extraction
    misses them. With the fix, agy's registered flags are present in extraction, so
    the removed-set (registry - help) does NOT contain them."""
    reg_path = drift_extract.registry_dir() / "antigravity-cli.yaml"
    reg_cmds = drift_extract.registry_commands(reg_path)
    help_cmds = _agy_extract()
    removed = reg_cmds - help_cmds
    for flag in ("-p", "--add-dir", "--sandbox"):
        if flag in reg_cmds:
            assert flag not in removed, f"{flag} falsely reported removed (#139 regression)"
