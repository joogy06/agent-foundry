#!/usr/bin/env python3
"""test_audit_spawn_ledger_parser.py — tasks.md #59 fix verification.

Covers `_meta/audit_spawn.py.load_ledger_row` across the two ledger shapes
the S023 pipeline produces:

    1. Projection-table form (bob's current authoritative projection — the
       markdown table at the top of progress/integration-ledger.md with
       columns `| WP | component | stage | generation | deps |`). This is
       what the live S023 ledger uses.
    2. Yaml-fenced event form (spec §9.2 shape with ```yaml ... ``` blocks).
       Legacy / spec-compliant shape, supported for backward compatibility.

Plus the mixed case (both shapes present → projection table wins),
unknown-component case (must return UNKNOWN, not PLANNED), and malformed
table (must not crash).

Run:
    python -m pytest /home/USER/.claude/skills/_meta/tests/test_audit_spawn_ledger_parser.py -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import audit_spawn  # noqa: E402


PROJECTION_ONLY_LEDGER = """---
schema_version: 1
contract_map_hash: abc123
writer: bob
---

# Integration Ledger

Projection table. Bob is sole writer.

| WP | component | stage | generation | deps |
|---|---|---|---|---|
| WP-2 | wiring-extract-static | INTEGRATED | 3 | — |
| WP-5 | wiring-reconcile | INTEGRATED | 3 | wiring-extract-static |
| WP-7 | wiring-query | VERIFIED | 4 | wiring-reconcile |
| WP-10 | *smoke-test fixture* | PASS (informational) | — | all of the above |

## Event Log

### 2026-04-15T00:52:00Z — WP-2 UNIT_TESTED → INTEGRATED (bob applied)

Prose event. Should NOT be parsed as stage source.
"""


YAML_FENCED_ONLY_LEDGER = """---
schema_version: 1
contract_map_hash: abc123
writer: bob
---

# Integration Ledger — legacy event-log only

## Events

```yaml
at: 2026-04-15T00:42:00Z
component_id: legacy-component
from: PLANNED
to: SCAFFOLDED
generation: 1
```

```yaml
at: 2026-04-15T00:48:00Z
component_id: legacy-component
from: SCAFFOLDED
to: UNIT_TESTED
generation: 2
```

```yaml
at: 2026-04-15T00:52:00Z
component_id: legacy-component
from: UNIT_TESTED
to: INTEGRATED
generation: 3
```
"""


MIXED_LEDGER = """---
schema_version: 1
---

# Mixed

| WP | component | stage | generation | deps |
|---|---|---|---|---|
| WP-1 | mixed-component | VERIFIED | 5 | — |

## Events

```yaml
at: 2026-04-15T00:42:00Z
component_id: mixed-component
from: PLANNED
to: SCAFFOLDED
generation: 1
```
"""


MALFORMED_TABLE_LEDGER = """---
schema_version: 1
---

# Malformed — header present but rows are junk

| WP | component | stage | generation | deps |
|---|---|---|---|---|
| WP-1 | bad-row   (missing cells)
not a table row at all
"""


NO_TABLE_NO_EVENTS_LEDGER = """---
schema_version: 1
---

# Empty ledger with no projection table and no events
"""


def _write_ledger(tmpdir: Path, content: str) -> Path:
    """Write a temporary ledger file at progress/integration-ledger.md."""
    progress = tmpdir / "progress"
    progress.mkdir(parents=True, exist_ok=True)
    path = progress / "integration-ledger.md"
    path.write_text(content)
    return tmpdir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProjectionTableOnly(unittest.TestCase):
    """Projection-table-only ledger (the shape used in S023 live)."""

    def test_wiring_extract_static_returns_integrated_gen3(self):
        with tempfile.TemporaryDirectory() as td:
            root = _write_ledger(Path(td), PROJECTION_ONLY_LEDGER)
            row = audit_spawn.load_ledger_row(root, "wiring-extract-static")
        self.assertEqual(row["component_id"], "wiring-extract-static")
        self.assertEqual(row["stage"], "INTEGRATED")
        self.assertEqual(row["generation"], 3)
        self.assertEqual(row["wp"], "WP-2")
        self.assertEqual(row["deps"], [])

    def test_wiring_reconcile_captures_single_dep(self):
        with tempfile.TemporaryDirectory() as td:
            root = _write_ledger(Path(td), PROJECTION_ONLY_LEDGER)
            row = audit_spawn.load_ledger_row(root, "wiring-reconcile")
        self.assertEqual(row["stage"], "INTEGRATED")
        self.assertEqual(row["generation"], 3)
        self.assertEqual(row["deps"], ["wiring-extract-static"])

    def test_verified_stage_gen4(self):
        """A component at VERIFIED with a higher generation parses correctly."""
        with tempfile.TemporaryDirectory() as td:
            root = _write_ledger(Path(td), PROJECTION_ONLY_LEDGER)
            row = audit_spawn.load_ledger_row(root, "wiring-query")
        self.assertEqual(row["stage"], "VERIFIED")
        self.assertEqual(row["generation"], 4)

    def test_markdown_emphasis_in_component_cell_stripped(self):
        """Rows like `| WP-10 | *smoke-test fixture* | ...` are tolerated."""
        with tempfile.TemporaryDirectory() as td:
            root = _write_ledger(Path(td), PROJECTION_ONLY_LEDGER)
            row = audit_spawn.load_ledger_row(root, "smoke-test fixture")
        self.assertEqual(row["component_id"], "smoke-test fixture")
        # Non-numeric generation cell "—" falls back to 0
        self.assertEqual(row["generation"], 0)
        # Stage with parentheses preserved as-is
        self.assertIn("PASS", row["stage"])


class TestYamlFencedBackwardCompat(unittest.TestCase):
    """Legacy yaml-fenced event log still works when projection table absent."""

    def test_legacy_events_rebuild_latest_stage(self):
        with tempfile.TemporaryDirectory() as td:
            root = _write_ledger(Path(td), YAML_FENCED_ONLY_LEDGER)
            row = audit_spawn.load_ledger_row(root, "legacy-component")
        self.assertEqual(row["stage"], "INTEGRATED")
        self.assertEqual(row["generation"], 3)

    def test_legacy_events_with_missing_component_returns_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            root = _write_ledger(Path(td), YAML_FENCED_ONLY_LEDGER)
            row = audit_spawn.load_ledger_row(root, "other-component")
        # The component has no events and no projection-table entry → UNKNOWN,
        # NOT PLANNED. PLANNED would be a false positive.
        self.assertEqual(row["stage"], "UNKNOWN")


class TestMixedShapesProjectionWins(unittest.TestCase):
    """When both shapes exist, projection table is authoritative."""

    def test_projection_beats_events_on_stage(self):
        with tempfile.TemporaryDirectory() as td:
            root = _write_ledger(Path(td), MIXED_LEDGER)
            row = audit_spawn.load_ledger_row(root, "mixed-component")
        # Projection says VERIFIED gen 5. Events say SCAFFOLDED gen 1.
        # Projection wins.
        self.assertEqual(row["stage"], "VERIFIED")
        self.assertEqual(row["generation"], 5)


class TestUnknownComponent(unittest.TestCase):
    """Missing component returns UNKNOWN, never PLANNED."""

    def test_missing_from_projection_and_events_returns_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            root = _write_ledger(Path(td), PROJECTION_ONLY_LEDGER)
            row = audit_spawn.load_ledger_row(root, "does-not-exist")
        self.assertEqual(row["stage"], "UNKNOWN")
        self.assertNotEqual(row["stage"], "PLANNED")

    def test_empty_ledger_returns_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            root = _write_ledger(Path(td), NO_TABLE_NO_EVENTS_LEDGER)
            row = audit_spawn.load_ledger_row(root, "anything")
        self.assertEqual(row["stage"], "UNKNOWN")

    def test_missing_ledger_file_returns_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            # No ledger written at all
            root = Path(td)
            row = audit_spawn.load_ledger_row(root, "anything")
        self.assertEqual(row["stage"], "UNKNOWN")
        self.assertEqual(row.get("note"), "ledger missing")


class TestMalformedTable(unittest.TestCase):
    """Malformed projection table must not crash; returns UNKNOWN."""

    def test_malformed_table_does_not_raise(self):
        with tempfile.TemporaryDirectory() as td:
            root = _write_ledger(Path(td), MALFORMED_TABLE_LEDGER)
            # Must not raise
            row = audit_spawn.load_ledger_row(root, "bad-row")
        # The row cell that survives parsing won't match component_id
        # exactly, so we get UNKNOWN.
        self.assertEqual(row["stage"], "UNKNOWN")


class TestLiveS023LedgerIntegration(unittest.TestCase):
    """Integration against the ARCHIVED S023 ledger — asserts tasks.md #59 stays fixed.

    S074 (#177): this used to hardcode an absolute path to the LIVE
    `progress/integration-ledger.md` and assert S023-era rows in it. Two failure modes,
    and the second is the dangerous one:

      * the live ledger is a per-cycle artifact, so every new cycle either broke these
        assertions or (once S023's ledger was archived) silently SKIPPED them — which is
        what it had been doing, a regression test quietly not running;
      * an absolute path to this machine means the suite could never assert anything on
        another host.

    Pinned to the archived copy instead. It is immutable, it is in the repo, and the rows
    it asserts are exactly the ones the parser fix was written against — so the test now
    RUNS everywhere instead of skipping where it matters most.
    """

    LIVE_LEDGER = (
        Path(__file__).resolve().parents[3]
        / "progress" / "archive" / "s023-s024-wiring-skills" / "integration-ledger.md"
    )

    def _root(self):
        """`load_ledger_row` appends progress/integration-ledger.md to a project root, so
        the archived ledger is exposed through a temp root that symlinks to it."""
        tmp = Path(tempfile.mkdtemp())
        (tmp / "progress").mkdir()
        (tmp / "progress" / "integration-ledger.md").write_bytes(self.LIVE_LEDGER.read_bytes())
        return tmp

    @unittest.skipUnless(LIVE_LEDGER.is_file(), "live S023 ledger not present")
    def test_wiring_extract_static_no_longer_returns_planned(self):
        row = audit_spawn.load_ledger_row(self._root(), "wiring-extract-static")
        self.assertEqual(row["stage"], "INTEGRATED",
                         f"regression: expected INTEGRATED, got {row}")
        self.assertEqual(row["generation"], 3)

    @unittest.skipUnless(LIVE_LEDGER.is_file(), "live S023 ledger not present")
    def test_all_five_tracked_components_resolve(self):
        root = self._root()
        for comp in ("wiring-extract-static", "wiring-reconcile",
                     "wiring-query", "gates-g4",
                     "integration-flow-testing-v11"):
            row = audit_spawn.load_ledger_row(root, comp)
            self.assertEqual(row["stage"], "INTEGRATED",
                             f"{comp} stage mismatch: {row}")
            self.assertEqual(row["generation"], 3,
                             f"{comp} generation mismatch: {row}")


if __name__ == "__main__":
    unittest.main()
