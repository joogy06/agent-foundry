"""Tests for manifests.py — parser unit tests, no network."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dep_currency_check.manifests import (
    Dependency, Manifest, _classify_constraint,
    detect_manifests,
)


class TestClassifyConstraint(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(_classify_constraint("1.2.3"), "exact")
        self.assertEqual(_classify_constraint("=1.2.3"), "exact")

    def test_caret(self):
        self.assertEqual(_classify_constraint("^1.2.3"), "caret")

    def test_tilde(self):
        self.assertEqual(_classify_constraint("~1.2.3"), "tilde")

    def test_range(self):
        self.assertEqual(_classify_constraint(">=2.0,<3"), "range")
        self.assertEqual(_classify_constraint(">1.0"), "range")

    def test_wildcard(self):
        self.assertEqual(_classify_constraint("1.2.*"), "wildcard")

    def test_unspecified(self):
        self.assertEqual(_classify_constraint(""), "unspecified")
        self.assertEqual(_classify_constraint("*"), "unspecified")

    def test_git(self):
        self.assertEqual(
            _classify_constraint("git+https://github.com/x/y"), "git",
        )


class TestDetectManifests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dcc-test-")
        self.root = Path(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detects_pyproject_toml(self):
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["requests>=2.20,<2.28"]\n'
        )
        out = detect_manifests(self.root)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].ecosystem, "python")
        names = {d.name for d in out[0].deps}
        self.assertIn("requests", names)

    def test_detects_package_json_and_devDeps_flag(self):
        (self.root / "package.json").write_text(
            '{"name":"x","dependencies":{"react":"^18.0.0"},'
            '"devDependencies":{"jest":"^29.0.0"}}'
        )
        out = detect_manifests(self.root)
        self.assertEqual(len(out), 1)
        deps = {d.name: d for d in out[0].deps}
        self.assertFalse(deps["react"].is_dev)
        self.assertTrue(deps["jest"].is_dev)

    def test_detects_cargo_workspace_members(self):
        (self.root / "Cargo.toml").write_text(
            '[package]\nname = "x"\nversion = "0.1.0"\n'
            '[dependencies]\nserde = "1.0"\n'
        )
        out = detect_manifests(self.root)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].ecosystem, "rust")

    def test_detects_lockfiles_and_marks_transitive(self):
        # Make a project with pyproject.toml + poetry.lock
        (self.root / "pyproject.toml").write_text(
            '[tool.poetry]\nname = "x"\nversion = "0.1.0"\n'
            '[tool.poetry.dependencies]\nrequests = "^2.20"\n'
        )
        (self.root / "poetry.lock").write_text(
            '[[package]]\nname = "requests"\nversion = "2.27.1"\n\n'
            '[[package]]\nname = "urllib3"\nversion = "1.26.0"\n\n'
        )
        out = detect_manifests(self.root)
        self.assertEqual(len(out), 1)
        m = out[0]
        self.assertTrue(m.has_lockfile)
        names = {d.name: d for d in m.deps}
        # requests is direct (in manifest)
        self.assertFalse(names["requests"].is_transitive)
        # urllib3 is only in lockfile -> transitive
        self.assertTrue(names["urllib3"].is_transitive)

    def test_skips_gitignored_paths(self):
        # node_modules should be skipped
        (self.root / "package.json").write_text('{"name":"root"}')
        nm = self.root / "node_modules" / "deep"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text('{"name":"deep"}')
        out = detect_manifests(self.root)
        # Should find only the root package.json
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].path.parent, self.root)

    def test_handles_malformed_manifest_gracefully(self):
        (self.root / "pyproject.toml").write_text("not [ valid toml @@@")
        # Should not raise
        out = detect_manifests(self.root)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].deps, tuple())


if __name__ == "__main__":
    unittest.main()
