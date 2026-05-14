"""migration_confirm.py — Emit api_delta-aware migration tests.

For each breaking change in api_delta, emit a test that:
  1. Captures legacy output for a representative input (the oracle)
  2. Exercises the same input post-migration
  3. Asserts byte/structural equivalence (HARD-RULE 2 bug-for-bug)

The test stubs are intentionally `pytest.skip` until the user fills them
in — we cannot synthesize realistic inputs from api_delta alone.
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
    api_delta: Dict[str, Any],
    *,
    mode: str = "version-upgrade",
    wiring_snapshot_hash: str = "unknown",
) -> List[Dict[str, Any]]:
    """Emit one migration-confirmation test per breaking_line that touches this component."""
    breaking = api_delta.get("breaking_lines", []) or []
    affected = api_delta.get("affected_components", []) or []
    # Filter affected to just this component
    this_comp = next((c for c in affected if c.get("name") == component_id), None)
    if this_comp is None:
        return []

    package = api_delta.get("package", "package")
    old_ver = api_delta.get("old_version", "old")
    new_ver = api_delta.get("new_version", "new")

    out: List[Dict[str, Any]] = []
    for i, line in enumerate(breaking):
        # Use position-based id for stable filename
        bl_slug = f"bl{i:03d}"
        filename = f"test_evo_{mode}_{component_id}__{bl_slug}__migration.py"

        header = test_header.build_header(
            language="python",
            confidence_level="characterization-aid",
            mode=mode,
            source_basis=f"api_delta.breaking_lines[{i}]",
            source_seed=bl_slug,
            wiring_evidence=f"{wiring_snapshot_hash} @ {component_id} @ {bl_slug}",
        )

        body = f'''
@pytest.fixture
def legacy_oracle_{bl_slug}():
    """The LEGACY oracle for migration. Bug-for-bug — even if the legacy
    behaviour is technically wrong, the migration must preserve it.

    Breaking change: {line!r}
    Package: {package} {old_ver} -> {new_ver}
    """
    # TODO-IMPLEMENT-ORACLE: capture pre-migration output for a fixed
    # representative input. Store under tests/fixtures/legacy_oracle_{bl_slug}.json
    return {{}}


def test_migration_{bl_slug}_bug_for_bug(legacy_oracle_{bl_slug}):
    """Migration must preserve legacy behaviour exactly (HARD-RULE 2).

    Breaking change to evaluate: {line!r}
    """
    # ARRANGE — same input as legacy_oracle_{bl_slug} captured
    # ACT     — exercise the post-migration code on the same input
    # ASSERT  — equivalence with legacy_oracle_{bl_slug}
    pytest.skip(
        "evo-generated migration stub — fill ARRANGE/ACT/ASSERT against "
        "tests/fixtures/legacy_oracle_{bl_slug}.json before relying on it"
    )
'''
        out.append({
            "filename": filename,
            "content": header + body,
            "seed_id": bl_slug,
            "test_type": "migration",
        })
    return out


def emit_jest(
    component_id: str,
    api_delta: Dict[str, Any],
    *,
    mode: str = "version-upgrade",
    wiring_snapshot_hash: str = "unknown",
) -> List[Dict[str, Any]]:
    """Emit migration tests for JS/TS via jest."""
    breaking = api_delta.get("breaking_lines", []) or []
    affected = api_delta.get("affected_components", []) or []
    this_comp = next((c for c in affected if c.get("name") == component_id), None)
    if this_comp is None:
        return []
    package = api_delta.get("package", "package")
    old_ver = api_delta.get("old_version", "old")
    new_ver = api_delta.get("new_version", "new")

    out: List[Dict[str, Any]] = []
    for i, line in enumerate(breaking):
        bl_slug = f"bl{i:03d}"
        filename = f"test_evo_{mode}_{component_id}__{bl_slug}__migration.test.js"
        header = test_header.build_header(
            language="javascript",
            confidence_level="characterization-aid",
            mode=mode,
            source_basis=f"api_delta.breaking_lines[{i}]",
            source_seed=bl_slug,
            wiring_evidence=f"{wiring_snapshot_hash} @ {component_id} @ {bl_slug}",
        )
        body = f'''
describe("evo migration {package} {old_ver}->{new_ver} :: {component_id} :: {bl_slug}", () => {{
  // breaking change: {line}
  test.skip("legacy oracle must be preserved (HARD-RULE 2)", () => {{
    // ARRANGE — load tests/fixtures/legacy_oracle_{bl_slug}.json
    // ACT     — exercise post-migration call
    // ASSERT  — equivalent to legacy oracle
  }});
}});
'''
        out.append({
            "filename": filename,
            "content": header + body,
            "seed_id": bl_slug,
            "test_type": "migration",
        })
    return out
