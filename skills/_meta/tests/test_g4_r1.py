#!/usr/bin/env python3
"""test_g4_r1.py — blocking edges must be corroborated.

R1 fires only for edges whose src_component is in the current PR diff and
which are not blocking_eligible.
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
from g4_fixture import build_project, make_edge  # noqa: E402


def _touch_diff_file(project_dir: Path, path_in_src: str):
    """Modify a file under src/<component>/ so `git diff --name-only HEAD`
    reports something matching a component's source_paths."""
    f = project_dir / "src" / path_in_src
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# modified\n")
    subprocess.run(["git", "-C", str(project_dir), "add", str(f)], check=True)


class G4R1Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g4-r1-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_agent_only_blocking_on_changed_component_fails_strict(self):
        # Edge: auth-service -> user-service, agent_asserted only -> blocking_eligible=false
        edges = [make_edge("auth-service", "auth.x",
                           "user-service", "user-service.y", "calls",
                           evidence_kinds=("agent_asserted",),
                           extractor_id="bob-assertion")]
        build_project(self.tmp, edges=edges,
                      components=("auth-service", "user-service"))
        # Simulate a diff on auth-service
        _touch_diff_file(self.tmp, "auth-service/changed.py")
        result = check_G4(self.tmp, mode="strict")
        r1_hard = [v for v in result["violations"]
                    if v["rule"] == "R1" and v["severity"] == "hard"]
        self.assertEqual(len(r1_hard), 1, result["violations"])

    def test_static_backed_blocking_passes(self):
        edges = [make_edge("auth-service", "auth.x",
                           "user-service", "user-service.y", "calls",
                           evidence_kinds=("static_extract",))]
        build_project(self.tmp, edges=edges,
                      components=("auth-service", "user-service"))
        _touch_diff_file(self.tmp, "auth-service/changed.py")
        result = check_G4(self.tmp, mode="strict")
        rules = {v["rule"] for v in result["violations"]}
        self.assertNotIn("R1", rules)

    def test_advisory_mode_downgrades_r1(self):
        edges = [make_edge("auth-service", "auth.x",
                           "user-service", "user-service.y", "calls",
                           evidence_kinds=("agent_asserted",),
                           extractor_id="bob-assertion")]
        build_project(self.tmp, edges=edges,
                      components=("auth-service", "user-service"))
        _touch_diff_file(self.tmp, "auth-service/changed.py")
        result = check_G4(self.tmp, mode="advisory")
        r1 = [v for v in result["violations"] if v["rule"] == "R1"]
        self.assertEqual(len(r1), 1)
        self.assertEqual(r1[0]["severity"], "advisory")

    def test_no_diff_no_r1(self):
        # Even an agent-only edge does NOT fire R1 when component isn't changed
        edges = [make_edge("auth-service", "auth.x",
                           "user-service", "user-service.y", "calls",
                           evidence_kinds=("agent_asserted",),
                           extractor_id="bob-assertion")]
        build_project(self.tmp, edges=edges,
                      components=("auth-service", "user-service"))
        # No diff
        result = check_G4(self.tmp, mode="strict")
        rules = {v["rule"] for v in result["violations"]}
        self.assertNotIn("R1", rules)


if __name__ == "__main__":
    unittest.main()
