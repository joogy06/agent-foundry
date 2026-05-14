"""compose_iflow.py — Adapter for integration-flow-testing composition.

Per HARD-RULE 6 (design §13): ever-test-gen COMPOSES integration-flow-testing,
never extends or forks it. This adapter is the single entry point.

Currently the composition is a thin no-op stub — the v1 ship doesn't yet
chain integration-flow-testing output into the regression-replay flow.
Future S033+ work will:

  1. Call integration-flow-testing's flow-test generator with the same
     plan.yaml + intent-map inputs
  2. Merge its outputs into our test-file list with the evo header
     prepended

This stub exists so that:
  - The skill structure is final
  - Tests can verify the composition surface is defined
  - Importers don't need to refactor when full composition lands
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


def discover_integration_flow_testing() -> Optional[Path]:
    """Return the path to integration-flow-testing's scripts/ dir, or None.

    Checked locations:
      - ~/.claude/skills/integration-flow-testing/scripts/
      - <skill_factory>/skills/integration-flow-testing/scripts/
    """
    here = Path(__file__).resolve().parent.parent.parent
    candidates = [
        Path.home() / ".claude" / "skills" / "integration-flow-testing" / "scripts",
        here / "integration-flow-testing" / "scripts",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def is_available() -> bool:
    """Return True iff integration-flow-testing is discoverable as a sibling skill."""
    return discover_integration_flow_testing() is not None


def compose(
    component_id: str,
    plan_path: Path,
    intent_map_path: Path,
    *,
    mode: str,
) -> List[Dict[str, Any]]:
    """Compose integration-flow-testing for one component.

    Returns a list of {filename, content, seed_id, test_type} dicts.
    v1 stub: returns [] (no composed tests yet). Future implementations
    will populate this with flow-test outputs from the sibling skill.

    The contract is stable so callers (run.py, tests) don't need to change
    when full composition lands.
    """
    # Defensive: log if requested but unavailable
    if not is_available():
        return []
    # v1 stub — return empty list, deliberate non-action
    return []
