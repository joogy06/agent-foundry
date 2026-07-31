"""regression_replay.py — Emit baseline regression-replay tests.

Reads a functional-intent.v1 file's test_seeds[] and emits one
characterization test per seed. The test exercises the seed's
given/when/then scenario as a fixture replay — captures the LEGACY
behaviour as the oracle.

Python output: pytest.
JavaScript output: jest.

Determinism: same inputs → byte-identical output.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import test_header  # noqa: E402


def emit_pytest(
    component_id: str,
    intent: Dict[str, Any],
    *,
    mode: str = "version-upgrade",
    wiring_snapshot_hash: str = "unknown",
) -> List[Dict[str, Any]]:
    """Emit regression-replay pytest tests for one component.

    Returns list of {filename, content} dicts. One file per test seed.
    """
    seeds = intent.get("test_seeds", []) or []
    out: List[Dict[str, Any]] = []
    for seed in seeds:
        sid = seed.get("seed_id", "S-unknown")
        scenario = seed.get("scenario", "characterization scenario")
        given = seed.get("given", "")
        when = seed.get("when", "")
        then = seed.get("then", "")

        # Sanitize seed_id for filename
        seed_slug = sid.lower().replace("-", "_")
        filename = f"test_evo_{mode}_{component_id}__{seed_slug}__regression.py"

        header = test_header.build_header(
            language="python",
            confidence_level="characterization-aid",
            mode=mode,
            source_basis=f"intent-map.test_seeds[{sid}]",
            source_seed=sid,
            wiring_evidence=f"{wiring_snapshot_hash} @ {component_id} @ {sid}",
        )

        body = f'''
def test_{seed_slug}_regression():
    """{scenario}

    GIVEN: {given}
    WHEN:  {when}
    THEN:  {then}

    Note: this test currently asserts the LEGACY behaviour as oracle.
    Replace TODO-IMPLEMENT-FIXTURE with the actual call to your code
    under test. Bug-for-bug compatibility: if the legacy returns wrong
    output for some input, this test MUST capture that wrong output.
    """
    # GIVEN
    # TODO-IMPLEMENT-FIXTURE: replace with concrete setup matching: {given}

    # WHEN
    # TODO-IMPLEMENT-CALL: replace with the actual call matching: {when}

    # THEN
    # TODO-IMPLEMENT-ASSERT: replace with assertion matching: {then}
    pytest.skip("evo-generated stub — fill in before relying on this test")
'''

        out.append({
            "filename": filename,
            "content": header + body,
            "seed_id": sid,
            "test_type": "regression",
        })
    return out


def emit_jest(
    component_id: str,
    intent: Dict[str, Any],
    *,
    mode: str = "version-upgrade",
    wiring_snapshot_hash: str = "unknown",
) -> List[Dict[str, Any]]:
    """Emit regression-replay jest tests for one component."""
    seeds = intent.get("test_seeds", []) or []
    out: List[Dict[str, Any]] = []
    for seed in seeds:
        sid = seed.get("seed_id", "S-unknown")
        scenario = seed.get("scenario", "characterization scenario")
        given = seed.get("given", "")
        when = seed.get("when", "")
        then = seed.get("then", "")
        seed_slug = sid.lower().replace("-", "_")
        filename = f"test_evo_{mode}_{component_id}__{seed_slug}__regression.test.js"

        header = test_header.build_header(
            language="javascript",
            confidence_level="characterization-aid",
            mode=mode,
            source_basis=f"intent-map.test_seeds[{sid}]",
            source_seed=sid,
            wiring_evidence=f"{wiring_snapshot_hash} @ {component_id} @ {sid}",
        )

        body = f'''
describe("evo regression replay: {component_id} :: {sid}", () => {{
  // {scenario}
  // GIVEN: {given}
  // WHEN:  {when}
  // THEN:  {then}
  test.skip("evo-generated stub — fill in before relying on this test", () => {{
    // GIVEN — TODO-IMPLEMENT-FIXTURE
    // WHEN  — TODO-IMPLEMENT-CALL
    // THEN  — TODO-IMPLEMENT-ASSERT
  }});
}});
'''
        out.append({
            "filename": filename,
            "content": header + body,
            "seed_id": sid,
            "test_type": "regression",
        })
    return out
