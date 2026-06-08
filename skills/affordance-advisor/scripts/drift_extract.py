#!/usr/bin/env python3
"""drift_extract.py — PUBLIC command-extraction helpers for drift detection.

Part of Ecosystem Evergreening v1 (S041). Spec-review Issue 2: the drift extraction
logic used to live as `_`-private symbols inside tests/test_drift_probe.py. Importing
private symbols from a *test* module across a skill boundary is fragile — a future test
refactor would silently break the production drift_runner. So the three helpers are
promoted HERE to a public import surface; BOTH tests/test_drift_probe.py AND
scripts/drift_runner.py import from this module, and a meta-test pins these names.

Public surface (do NOT rename without updating the meta-test):
  DRIFT_TARGETS            — registry-file -> (binary, --help args, command regex)
  extract_commands(text, pattern) -> set[str]
  registry_commands(registry_path) -> set[str]
  read_validated_against(registry_path) -> dict | None

Registry-count note (spec-review Issue 2b): `validated_against` is STAMPED on all 6
registry YAMLs, but the drift PROBE runs only over the 5 CLI-backed targets in
DRIFT_TARGETS — `copilot-chat.yaml` has no CLI binary to `--help` and is metadata-only.

stdlib + the sibling `advise` module only. No LLM calls. Deterministic.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Make the sibling advise module importable regardless of CWD.
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import advise  # noqa: E402  (sibling module: load_registry)


_REGISTRY_DIR = _SCRIPTS.parent / "registry"

# Two-column GNU-style --help extractor (#139 fix). The real invariant in codex/agy/
# copilot/gh `--help` is a two-column layout: `<token><>=2 spaces><description>`, where
# the FIRST-COLUMN token is a flag (`-p`, `--add-dir`) OR a subcommand (`exec`).
#   ^[ ]{1,8}      first-column indent (rejects col-0 section headers AND deep-indent
#                  wrapped description prose, which sits in the description column)
#   (--?[A-Za-z][\w-]*|[A-Za-z][\w-]*)   a flag token OR a word token (hyphens allowed)
#   (?:[ ]{2,}|[ ]*$)                    followed by the >=2-space column gap (or EOL)
# The OLD pattern `^\s+(\w[\w-]*)\s+` required a WORD-initial token, so it silently
# dropped every flag (`-p`, `--add-dir`) — making registered flags look "removed"
# (#139 false CONFIRMED removals) — while also over-capturing wrapped prose.
_GNU_HELP = re.compile(r"^[ ]{1,8}(--?[A-Za-z][\w-]*|[A-Za-z][\w-]*)(?:[ ]{2,}|[ ]*$)",
                       re.MULTILINE)
# Claude Code lists slash commands, not GNU flags — keep its own shape.
_SLASH_HELP = re.compile(r"^\s*/(\S+)", re.MULTILINE)

# Map registry filename -> (binary, --help args, regex to extract commands).
# These are the 5 CLI-backed drift targets. copilot-chat.yaml is intentionally
# EXCLUDED (no CLI binary).
DRIFT_TARGETS = {
    "claude-code.yaml":     ("claude", ["--help"], _SLASH_HELP),
    "codex.yaml":           ("codex", ["--help"], _GNU_HELP),
    "antigravity-cli.yaml": ("agy", ["--help"], _GNU_HELP),
    "copilot-cli.yaml":     ("copilot", ["--help"], _GNU_HELP),
    "gh.yaml":              ("gh", ["--help"], _GNU_HELP),
}

# Known-floor sentinels (#139 fix c): bedrock tokens that MUST appear in a healthy
# extraction. If a floored CLI's set is not a subset of what was extracted, the
# --help parse broke — classify `extractor_error` and SUPPRESS removals (never report
# a parse break as product drift). Only CLIs with stable, known bedrock get a floor;
# `.get(reg, frozenset())` => no floor => no check (conservative for claude/gh/copilot).
KNOWN_FLOORS = {
    "antigravity-cli.yaml": frozenset({"-p", "--add-dir"}),
    "codex.yaml":           frozenset({"exec", "review"}),
}

# All registries that must carry a `validated_against` header (6 — includes the
# non-CLI copilot-chat metadata registry).
ALL_REGISTRIES = sorted(DRIFT_TARGETS) + ["copilot-chat.yaml"]


def extract_commands(text: str, pattern: "re.Pattern") -> set:
    """Extract the distinctive command token set from `--help` text via `pattern`."""
    return {m.group(1) for m in pattern.finditer(text)}


def registry_commands(registry_path: Path) -> set:
    """Extract the NORMALIZED command-token set from a registry YAML.

    Normalized == the distinctive first token (slash + word, or binary + first sub).
    No descriptions, no order, no prose — a sorted set is the comparison unit."""
    data = advise.load_registry(registry_path)
    out: set = set()
    for aff in data.get("affordances", []):
        cmd = aff["command"]
        if cmd.startswith("/"):
            out.add(cmd.split()[0].lstrip("/"))
        else:
            words = cmd.split()
            if len(words) >= 2:
                out.add(words[1])  # skip the binary name (codex, gh, agy, copilot)
    return out


def read_validated_against(registry_path: Path) -> dict | None:
    """Return the registry's `validated_against: {cli_version, date}` header, or None."""
    try:
        data = advise.load_registry(registry_path)
    except Exception:  # noqa: BLE001
        return None
    va = data.get("validated_against")
    return va if isinstance(va, dict) else None


def registry_dir() -> Path:
    return _REGISTRY_DIR
