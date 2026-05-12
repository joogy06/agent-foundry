"""Tests for community_wrappers.py — wrappers stubbed via fake binary."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path

from dep_currency_check.community_wrappers import (
    cargo_audit_available, govulncheck_available, osv_scanner_available,
    pip_audit_available, query_go_via_govulncheck,
    query_python_via_pip_audit, query_rust_via_cargo_audit,
    query_via_osv_scanner,
)


def _write_fake_binary(dir_: Path, name: str, output: str,
                        exit_code: int = 0) -> Path:
    # Use a Python shebang so we don't depend on /bin/cat being on PATH
    # when callers isolate PATH for the test.
    p = dir_ / name
    p.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.write({output!r})\n"
        f"sys.stdout.write(chr(10))\n"
        f"sys.exit({exit_code})\n"
    )
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _isolate_path(*include_dirs: Path) -> str:
    """Build a PATH containing the given dirs PLUS standard system bins
    (so /bin/sh dependencies like `cat` continue to work)."""
    return os.pathsep.join([*[str(d) for d in include_dirs],
                              "/usr/bin", "/bin"])


class TestWrapperAvailability(unittest.TestCase):
    """Test the availability probes — these probe the real PATH, so we
    don't strongly assert presence."""

    def test_probes_return_bool(self):
        # Just verify return types
        self.assertIsInstance(osv_scanner_available(), bool)
        self.assertIsInstance(pip_audit_available(), bool)
        self.assertIsInstance(cargo_audit_available(), bool)
        self.assertIsInstance(govulncheck_available(), bool)


class TestWrapperFailureSemantics(unittest.TestCase):
    """All wrappers must return None on (a) missing binary, (b) non-zero exit,
    (c) timeout, (d) JSON parse fail."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dcc-wrap-")
        self.bin_dir = Path(self.tmp) / "bin"
        self.bin_dir.mkdir()
        self.proj_dir = Path(self.tmp) / "project"
        self.proj_dir.mkdir()
        self._orig_path = os.environ.get("PATH", "")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ["PATH"] = self._orig_path

    def test_osv_scanner_missing_binary_returns_none(self):
        os.environ["PATH"] = "/nonexistent"
        out = query_via_osv_scanner(self.proj_dir)
        self.assertIsNone(out)

    def test_pip_audit_missing_binary_returns_none(self):
        os.environ["PATH"] = "/nonexistent"
        out = query_python_via_pip_audit(self.proj_dir)
        self.assertIsNone(out)

    def test_wrapper_returns_none_on_invalid_json(self):
        _write_fake_binary(self.bin_dir, "osv-scanner", "not json output")
        os.environ["PATH"] = _isolate_path(self.bin_dir)
        out = query_via_osv_scanner(self.proj_dir)
        self.assertIsNone(out)

    def test_no_npm_audit_wrapper_exists(self):
        # Negative test: there should be no symbol named query_npm_audit
        import dep_currency_check.community_wrappers as cw
        self.assertFalse(hasattr(cw, "query_npm_audit"))
        self.assertFalse(hasattr(cw, "npm_audit_available"))


class TestWrapperOutputParsing(unittest.TestCase):
    """Test that wrappers parse valid JSON correctly when present."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dcc-wrap-out-")
        self.bin_dir = Path(self.tmp) / "bin"
        self.bin_dir.mkdir()
        self.proj_dir = Path(self.tmp) / "project"
        self.proj_dir.mkdir()
        self._orig_path = os.environ.get("PATH", "")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ["PATH"] = self._orig_path

    def test_osv_scanner_parses_valid_output(self):
        # Realistic osv-scanner JSON shape
        output = json.dumps({
            "results": [{
                "source": {"path": "Cargo.lock", "type": "lockfile"},
                "packages": [{
                    "package": {"name": "openssl", "version": "0.10.0",
                                 "ecosystem": "crates.io"},
                    "vulnerabilities": [{
                        "id": "RUSTSEC-2024-0001",
                        "aliases": ["CVE-2024-1234"],
                        "summary": "openssl vuln",
                        "severity": [{"type": "CVSS_V3", "score": "9.0"}],
                        "affected": [{"ranges": [{"events": [
                            {"introduced": "0"}, {"fixed": "0.11.0"}
                        ]}]}],
                        "database_specific": {"severity": "critical"},
                    }],
                }],
            }]
        })
        _write_fake_binary(self.bin_dir, "osv-scanner", output)
        os.environ["PATH"] = _isolate_path(self.bin_dir)
        out = query_via_osv_scanner(self.proj_dir)
        self.assertIsNotNone(out)
        self.assertIn("rust", out)
        self.assertEqual(len(out["rust"]), 1)
        f = out["rust"][0]
        self.assertEqual(f.dep.name, "openssl")
        self.assertEqual(f.cves[0].id, "CVE-2024-1234")
        self.assertEqual(f.cves[0].severity, "critical")


if __name__ == "__main__":
    unittest.main()
