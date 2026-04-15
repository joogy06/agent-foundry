#!/usr/bin/env python3
"""test_g4_r0.py — new-component exception.

When a component's src_component is absent from previous latest.json AND
present in the current source tree, R1 becomes advisory regardless of mode.

Note: in v1 there is no previous-snapshot rotation, so R0's conditional
logic reduces to "if previous_components set is empty, skip R0 downgrade,
R1 operates normally". We test both branches:

  - Branch A: no previous snapshot exists (the common v1 case) — R0 does
    nothing; R1 fires per strict/advisory mode normally.
  - Branch B: simulated previous_components set carrying known components;
    a new component's R1 violation gets downgraded to advisory.

Because `_g4_previous_components` currently loads None (v1), Branch B is
exercised via a direct call to check_G4's helpers with a synthetic prior.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gates import check_G4  # type: ignore  # noqa: E402
import gates  # type: ignore  # noqa: E402
from g4_fixture import build_project, make_edge  # noqa: E402


def _touch_diff_file(project_dir: Path, path_in_src: str):
    f = project_dir / "src" / path_in_src
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# modified\n")
    subprocess.run(["git", "-C", str(project_dir), "add", str(f)], check=True)


class G4R0Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g4-r0-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_branch_a_no_previous_snapshot(self):
        # With no previous snapshot, R0 cannot apply; R1 fires as hard in strict
        edges = [make_edge("auth-service", "auth.x",
                           "user-service", "user-service.y", "calls",
                           evidence_kinds=("agent_asserted",),
                           extractor_id="bob-assertion")]
        build_project(self.tmp, edges=edges,
                      components=("auth-service", "user-service"))
        _touch_diff_file(self.tmp, "auth-service/changed.py")
        result = check_G4(self.tmp, mode="strict")
        r1_hard = [v for v in result["violations"]
                    if v["rule"] == "R1" and v["severity"] == "hard"]
        self.assertEqual(len(r1_hard), 1)
        # Message must NOT include "[R0 new-component exception applied]"
        # since there is no previous snapshot.
        self.assertNotIn("[R0 new-component exception applied]",
                         r1_hard[0]["message"])

    def test_branch_b_new_component_downgrades(self):
        """Simulate previous latest.json without 'auth-service'; R0 kicks in."""
        edges = [make_edge("auth-service", "auth.x",
                           "user-service", "user-service.y", "calls",
                           evidence_kinds=("agent_asserted",),
                           extractor_id="bob-assertion")]
        build_project(self.tmp, edges=edges,
                      components=("auth-service", "user-service"))
        _touch_diff_file(self.tmp, "auth-service/changed.py")

        # Monkey-patch _g4_previous_components to return a set that EXCLUDES
        # auth-service (i.e. auth-service is "new" in this snapshot)
        original = gates._g4_previous_components
        try:
            gates._g4_previous_components = lambda previous_snapshot: {"user-service"}
            # Also need previous_snapshot to be non-None — easier: inline a
            # minimal prior with a dummy edge. The existing check_G4 uses
            # previous_snapshot = None, so we need to override check_G4's
            # inner assignment. Simpler: override the "previous_components"
            # call path. _g4_previous_components(None) returns the mock set.
            result = check_G4(self.tmp, mode="strict")
        finally:
            gates._g4_previous_components = original

        # In strict mode with an R0 exception, R1 downgrades to advisory
        r1_entries = [v for v in result["violations"] if v["rule"] == "R1"]
        self.assertEqual(len(r1_entries), 1)
        self.assertEqual(r1_entries[0]["severity"], "advisory")
        self.assertIn("[R0 new-component exception applied]",
                      r1_entries[0]["message"])


if __name__ == "__main__":
    unittest.main()
