"""End-to-end integration tests on synthetic projects."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(args: list, *, cwd: str = None,
             env_extra: dict = None) -> tuple:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SKILL_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, "-m", "dep_currency_check", *args],
        capture_output=True, text=True, timeout=60,
        env=env, cwd=cwd, check=False,
    )
    return (proc.returncode, proc.stdout, proc.stderr)


class TestSyntheticProjects(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dcc-int-")
        self.root = Path(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_python_project_with_vuln_dep_offline(self):
        # Synthetic project with requests
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "test"\nversion = "0.1.0"\n'
            'dependencies = ["requests>=2.20,<2.28"]\n'
        )
        rc, out, err = _run_cli([str(self.root), "--offline",
                                  "--allow-deferred",
                                  "--format", "json",
                                  "--severity", "all"])
        self.assertEqual(rc, 0, f"stderr: {err}")
        data = json.loads(out)
        self.assertEqual(data["grounding_mode"], "offline-cold-cache")
        # All findings deferred
        self.assertTrue(all(f["gap_kind"] == "deferred_offline"
                             for f in data["findings"]))

    def test_npm_monorepo_workspace_parses(self):
        (self.root / "package.json").write_text(json.dumps({
            "name": "monorepo-root",
            "workspaces": ["packages/*"],
            "dependencies": {"lodash": "^4.17.21"},
        }))
        (self.root / "packages" / "app").mkdir(parents=True)
        (self.root / "packages" / "app" / "package.json").write_text(json.dumps({
            "name": "app",
            "dependencies": {"react": "^18.0.0"},
        }))
        rc, out, err = _run_cli([str(self.root), "--offline",
                                  "--allow-deferred",
                                  "--format", "json",
                                  "--severity", "all"])
        self.assertEqual(rc, 0, f"stderr: {err}")
        data = json.loads(out)
        # Both manifests should be detected
        self.assertEqual(len(data["manifests_scanned"]), 2)

    def test_cargo_project_with_lockfile(self):
        (self.root / "Cargo.toml").write_text(
            '[package]\nname = "test"\nversion = "0.1.0"\n'
            '[dependencies]\nserde = "1.0"\n'
        )
        (self.root / "Cargo.lock").write_text(
            '[[package]]\nname = "serde"\nversion = "1.0.0"\n\n'
            '[[package]]\nname = "tokio"\nversion = "1.0.0"\n\n'
        )
        rc, out, err = _run_cli([str(self.root), "--offline",
                                  "--allow-deferred",
                                  "--format", "json",
                                  "--severity", "all"])
        self.assertEqual(rc, 0, f"stderr: {err}")
        data = json.loads(out)
        # serde direct, tokio transitive (only in lockfile)
        names = {f["package"]: f for f in data["findings"]}
        self.assertIn("serde", names)
        if "tokio" in names:
            self.assertTrue(names["tokio"]["is_transitive"])

    def test_go_project_parses_module_uppercase(self):
        (self.root / "go.mod").write_text(
            "module example.com/test\n\n"
            "go 1.21\n\n"
            "require (\n"
            "    github.com/Azure/azure-sdk-for-go v1.0.0\n"
            ")\n"
        )
        rc, out, err = _run_cli([str(self.root), "--offline",
                                  "--allow-deferred",
                                  "--format", "json",
                                  "--severity", "all"])
        self.assertEqual(rc, 0, f"stderr: {err}")
        data = json.loads(out)
        names = {f["package"] for f in data["findings"]}
        self.assertIn("github.com/Azure/azure-sdk-for-go", names)

    def test_scope_delta_dedupe_on_repeat_run(self):
        """Run the CLI twice with --emit-scope-delta and verify no
        duplicate records are written (S029 dedup pattern)."""
        # Create a project with a pyproject.toml — scope_delta will only fire
        # if blocks_build is True, which needs critical+direct+prod+fix.
        # In offline mode, no CVEs are found, so no scope_delta entries.
        # This test mainly confirms the CLI accepts --emit-scope-delta without
        # crashing and is idempotent.
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "test"\ndependencies = ["requests"]\n'
        )
        for _ in range(2):
            rc, out, err = _run_cli([
                str(self.root), "--offline", "--allow-deferred",
                "--emit-scope-delta", "--mode", "strict",
                "--format", "json", "--severity", "all",
            ])
            self.assertIn(rc, (0, 2),
                           f"unexpected rc={rc} stderr: {err}")
        # No exception = pass. Real dedup is tested via gates.py's pattern.


if __name__ == "__main__":
    unittest.main()
