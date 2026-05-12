"""Tests for the CLI — subprocess-based, mirrors foundry-server pattern."""
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
    """Run the CLI as a subprocess; return (rc, stdout, stderr)."""
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


class TestCLISimpleProjects(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dcc-cli-")
        self.root = Path(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cli_runs_on_empty_project(self):
        rc, out, err = _run_cli([str(self.root), "--format", "json"])
        self.assertEqual(rc, 0, f"stderr: {err}")
        data = json.loads(out)
        self.assertEqual(data["schema_version"], "dep-currency.v1")
        self.assertEqual(data["findings"], [])

    def test_cli_runs_on_python_project_offline(self):
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["requests>=2.20,<2.28"]\n'
        )
        rc, out, err = _run_cli([str(self.root), "--format", "json",
                                  "--offline", "--severity", "all"])
        # exit 4 (deferred-only) unless --allow-deferred
        self.assertIn(rc, (0, 4),
                       f"unexpected rc={rc} stderr: {err}")
        data = json.loads(out)
        self.assertEqual(data["grounding_mode"], "offline-cold-cache")

    def test_cli_offline_with_allow_deferred_exits_0(self):
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["requests>=2.20,<2.28"]\n'
        )
        rc, out, err = _run_cli([str(self.root), "--format", "json",
                                  "--offline", "--allow-deferred",
                                  "--severity", "all"])
        self.assertEqual(rc, 0, f"stderr: {err}")

    def test_cli_render_markdown(self):
        rc, out, err = _run_cli([str(self.root), "--format", "json",
                                  "--render", "markdown"])
        self.assertEqual(rc, 0, f"stderr: {err}")
        self.assertIn("# dep-currency-check", out)

    def test_cli_render_yaml(self):
        rc, out, err = _run_cli([str(self.root), "--format", "json",
                                  "--render", "yaml"])
        self.assertEqual(rc, 0, f"stderr: {err}")
        self.assertIn("schema_version: dep-currency.v1", out)

    def test_cli_format_yaml_rejected(self):
        # --format yaml does NOT exist; argparse should reject
        rc, out, err = _run_cli([str(self.root), "--format", "yaml"])
        self.assertNotEqual(rc, 0)
        # argparse usually returns 2
        self.assertIn("invalid choice", err.lower())

    def test_cli_strict_airgap_fails_on_cold_cache(self):
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["requests"]\n'
        )
        rc, out, err = _run_cli([str(self.root), "--strict-airgap",
                                  "--format", "json", "--offline"])
        # Should exit 4 (deferred-only) since cache is cold
        self.assertEqual(rc, 4, f"stderr: {err}")

    def test_cli_version_flag(self):
        rc, out, err = _run_cli(["--version"])
        self.assertEqual(rc, 0)
        self.assertIn("dep-currency-check", out)


if __name__ == "__main__":
    unittest.main()
