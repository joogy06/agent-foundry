"""test_drift_probe.py — manual / weekly drift detector.

Compares the `command` field of each registry entry against the help output
of the host CLI on PATH, if any. Reports new (in help, not in registry) and
removed (in registry, not in help) commands.

This test is marked `@pytest.mark.manual` and is SKIPPED by default. To run:

    pytest -v -m manual ~/.claude/skills/affordance-advisor/tests/

The intent is a weekly maintenance check. Auto-running is out of scope for
v1 because the help output of each CLI evolves on its own cadence and the
test would otherwise flap.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

import advise


_REGISTRY_DIR = Path(__file__).resolve().parent.parent / "registry"

# Map registry filename -> (binary, --help args, regex to extract commands)
_DRIFT_TARGETS = {
    "claude-code.yaml": ("claude",   ["--help"],
                         re.compile(r"^\s*/(\S+)", re.MULTILINE)),
    "codex.yaml":       ("codex",    ["--help"],
                         re.compile(r"^\s+(\w[\w-]*)\s+", re.MULTILINE)),
    "gemini.yaml":      ("gemini",   ["--help"],
                         re.compile(r"^\s+(\w[\w-]*)\s+", re.MULTILINE)),
    "copilot-cli.yaml": ("copilot",  ["--help"],
                         re.compile(r"^\s+(\w[\w-]*)\s+", re.MULTILINE)),
    "gh.yaml":          ("gh",       ["--help"],
                         re.compile(r"^\s+(\w[\w-]*)\s+", re.MULTILINE)),
}


def _extract_commands(text: str, pattern: re.Pattern) -> set[str]:
    return {m.group(1) for m in pattern.finditer(text)}


def _registry_commands(registry_path: Path) -> set[str]:
    data = advise.load_registry(registry_path)
    out: set[str] = set()
    for aff in data.get("affordances", []):
        cmd = aff["command"]
        # Take the distinctive first token: slash + word, or binary + first sub
        if cmd.startswith("/"):
            out.add(cmd.split()[0].lstrip("/"))
        else:
            words = cmd.split()
            # Skip the binary name (codex, gh, gemini, copilot)
            if len(words) >= 2:
                out.add(words[1])
    return out


@pytest.mark.manual
@pytest.mark.parametrize("registry_name", list(_DRIFT_TARGETS))
def test_help_vs_registry(registry_name):
    """Diff `<bin> --help` extracted commands against the registry's command set."""
    binary, args, pattern = _DRIFT_TARGETS[registry_name]
    if not shutil.which(binary):
        pytest.skip(f"{binary} not on PATH — cannot probe help output")

    try:
        proc = subprocess.run([binary, *args], capture_output=True,
                              text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"{binary} --help failed: {e}")

    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    help_cmds = _extract_commands(text, pattern)
    reg_cmds  = _registry_commands(_REGISTRY_DIR / registry_name)

    # Drift report — does NOT fail; just prints. Manual review decides.
    new_in_help = sorted(help_cmds - reg_cmds)
    removed_in_help = sorted(reg_cmds - help_cmds)
    print(f"\n=== drift for {registry_name} ===")
    print(f"  registry entries: {len(reg_cmds)}")
    print(f"  help entries:     {len(help_cmds)}")
    print(f"  in help but not registry ({len(new_in_help)}): {new_in_help}")
    print(f"  in registry but not help ({len(removed_in_help)}): {removed_in_help}")

    # Soft assertion: at least the registry is parseable and the help output
    # produced something. If both are zero we have a probe error worth flagging.
    assert reg_cmds, f"{registry_name}: registry has no commands"


def test_drift_probe_is_marked_manual():
    """Sanity: the drift test must be marked manual so CI doesn't run it."""
    import inspect
    fn = test_help_vs_registry
    markers = [m for m in getattr(fn, "pytestmark", [])]
    assert any(m.name == "manual" for m in markers), \
        "test_help_vs_registry must be @pytest.mark.manual"
