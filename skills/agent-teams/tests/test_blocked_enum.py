"""WP-4 (agent-teams-scope-routing) pytest wrapper for the structural .sh test.

Spawn-5b: contract-map declares this path as `test_paths.unit` for component
`agent-teams-scope-routing`, but the actual structural assertions live in a
bash script at /path/to/project/tests/contract-scope/test_agent_teams_enum.sh
(WP-4 / spawn-2 deliverable). The shell script does seven grep-based checks
against ~/.claude/skills/agent-teams/SKILL.md to confirm the BLOCKED-enum
extension + Step-6 routing prose + CB4 invariant.

This wrapper delegates to the .sh ground-truth and surfaces a single pytest
node so the trusted_runner / arbiter pipeline can produce a deterministic
bundle for the VERIFIED batch (HARD-RULE 5 dual-verdict).
"""
from __future__ import annotations

import subprocess

SH_TEST = "/path/to/project/tests/contract-scope/test_agent_teams_enum.sh"


def test_agent_teams_blocked_enum_structural() -> None:
    """Delegate to the .sh ground-truth and assert clean exit (CONTRACT-B3)."""
    result = subprocess.run(
        ["bash", SH_TEST],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        "shell structural test failed:\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
