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

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Import the extraction helpers from the PUBLIC drift_extract module (Evergreening v1,
# S041, spec-review Issue 2) rather than re-defining private symbols here. This test
# and scripts/drift_runner.py share ONE import surface, so a refactor can't silently
# break the production runner. The test keeps the same names (aliased) for continuity.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import advise  # noqa: E402,F401  (kept for back-compat with any external importer)
import drift_extract  # noqa: E402

_REGISTRY_DIR = drift_extract.registry_dir()
_DRIFT_TARGETS = drift_extract.DRIFT_TARGETS
_extract_commands = drift_extract.extract_commands
_registry_commands = drift_extract.registry_commands


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
    fn = test_help_vs_registry
    markers = [m for m in getattr(fn, "pytestmark", [])]
    assert any(m.name == "manual" for m in markers), \
        "test_help_vs_registry must be @pytest.mark.manual"


def test_drift_extract_public_surface_pinned():
    """Meta-test (Evergreening v1, S041, spec-review Issue 2): pin the PUBLIC names
    drift_runner.py depends on, so a refactor of drift_extract can't silently break
    the production runner."""
    assert hasattr(drift_extract, "DRIFT_TARGETS")
    assert hasattr(drift_extract, "extract_commands")
    assert hasattr(drift_extract, "registry_commands")
    assert hasattr(drift_extract, "read_validated_against")
    assert hasattr(drift_extract, "registry_dir")
    assert hasattr(drift_extract, "KNOWN_FLOORS")  # #139: floor-check public surface
    # The 5 CLI-backed targets are stable; copilot-chat is NOT a drift target.
    assert set(drift_extract.DRIFT_TARGETS) == {
        "claude-code.yaml", "codex.yaml", "antigravity-cli.yaml",
        "copilot-cli.yaml", "gh.yaml",
    }
    assert "copilot-chat.yaml" not in drift_extract.DRIFT_TARGETS
    # validated_against is stamped on all 6 (the 5 + copilot-chat metadata registry).
    assert "copilot-chat.yaml" in drift_extract.ALL_REGISTRIES
    assert len(drift_extract.ALL_REGISTRIES) == 6
