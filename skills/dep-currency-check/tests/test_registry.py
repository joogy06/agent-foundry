"""Tests for registry.py — HTTP layer with mocked urllib."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from dep_currency_check.cache import Cache
from dep_currency_check.manifests import Dependency
from dep_currency_check.registry import (
    Registry, _escape_go_caps, _crates_sparse_prefix,
    _query_pypi, _pypi_to_versioninfo,
)


def _mock_response(body: str, status: int = 200, headers: dict = None):
    """Build a fake HTTPResponse for urlopen mock."""
    m = MagicMock()
    m.read.return_value = body.encode("utf-8")
    m.status = status
    m.headers = headers or {}
    # Context-manager protocol
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


class TestGoCapEscaping(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(_escape_go_caps("github.com/foo"),
                          "github.com/foo")

    def test_capital_letters(self):
        self.assertEqual(_escape_go_caps("github.com/Azure/azure-sdk-for-go"),
                          "github.com/!azure/azure-sdk-for-go")

    def test_all_lower(self):
        self.assertEqual(_escape_go_caps("github.com/gin-gonic/gin"),
                          "github.com/gin-gonic/gin")


class TestCratesSparsePrefix(unittest.TestCase):
    def test_one_char(self):
        self.assertEqual(_crates_sparse_prefix("a"), "1/a")

    def test_two_char(self):
        self.assertEqual(_crates_sparse_prefix("ab"), "2/ab")

    def test_three_char(self):
        self.assertEqual(_crates_sparse_prefix("abc"), "3/a/abc")

    def test_long(self):
        self.assertEqual(_crates_sparse_prefix("serde"), "se/rd/serde")


class TestPyPIParsing(unittest.TestCase):
    def test_pypi_returns_version_info(self):
        raw = {
            "info": {"name": "requests", "version": "2.32.3"},
            "releases": {
                "2.0.0": [{"yanked": False, "upload_time_iso_8601": "2020-01-01T00:00:00Z"}],
                "2.32.3": [{"yanked": False, "upload_time_iso_8601": "2024-05-01T00:00:00Z"}],
                "2.31.0": [{"yanked": True, "upload_time_iso_8601": "2023-05-22T00:00:00Z"}],
            },
        }
        vi = _pypi_to_versioninfo(raw, "requests")
        self.assertIsNotNone(vi)
        self.assertEqual(vi.latest_stable, "2.32.3")
        self.assertIn("2.31.0", vi.yanked_versions)

    def test_handles_empty_releases(self):
        raw = {"info": {"name": "x", "version": "0.1.0"}, "releases": {}}
        vi = _pypi_to_versioninfo(raw, "x")
        self.assertIsNotNone(vi)
        self.assertEqual(vi.latest_stable, "0.1.0")


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dcc-cache-")
        self.cache = Cache(base=Path(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_offline_mode_returns_none_when_cache_cold(self):
        r = Registry(cache=self.cache)
        v = r.query_version_latest("python", "nonexistent-pkg-x",
                                     offline=True)
        self.assertIsNone(v)

    def test_offline_mode_returns_cached_when_cache_warm(self):
        # Pre-populate cache
        self.cache.put("versions", "python", "requests", {
            "package": "requests", "ecosystem": "python",
            "latest_stable": "2.32.3", "latest_any": "2.32.3",
            "yanked_versions": [], "deprecated": False,
            "deprecation_notice": None,
            "last_release_at": None,
            "fetched_at": "2026-05-11T00:00:00+00:00",
            "source": "pypi",
        })
        r = Registry(cache=self.cache)
        v = r.query_version_latest("python", "requests", offline=True)
        self.assertIsNotNone(v)
        self.assertEqual(v.latest_stable, "2.32.3")

    @patch("dep_currency_check.registry.urllib.request.urlopen")
    def test_pypi_http_success(self, mock_urlopen):
        body = json.dumps({
            "info": {"version": "2.32.3"},
            "releases": {"2.32.3": [{"yanked": False,
                                      "upload_time_iso_8601": "2024-01-01T00:00:00Z"}]},
        })
        mock_urlopen.return_value = _mock_response(body)
        r = Registry(cache=self.cache)
        v = r.query_version_latest("python", "requests")
        self.assertIsNotNone(v)
        self.assertEqual(v.latest_stable, "2.32.3")

    @patch("dep_currency_check.registry.urllib.request.urlopen")
    def test_strict_airgap_blocks_network(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response("{}")
        r = Registry(cache=self.cache, strict_airgap=True)
        v = r.query_version_latest("python", "requests")
        self.assertIsNone(v)  # blocked by strict_airgap
        self.assertEqual(mock_urlopen.call_count, 0)

    @patch("dep_currency_check.registry.urllib.request.urlopen")
    def test_osv_querybatch_returns_cves(self, mock_urlopen):
        # Mock: first call is OSV POST, returns one vuln for requests
        body = json.dumps({
            "results": [
                {
                    "vulns": [{
                        "id": "GHSA-9wx4-h78v-vm56",
                        "aliases": ["CVE-2024-35195"],
                        "summary": "requests vulnerable",
                        "severity": [{"type": "CVSS_V3", "score": "7.5"}],
                        "affected": [{"ranges": [{"events": [
                            {"introduced": "0"}, {"fixed": "2.32.0"}
                        ]}]}],
                    }]
                }
            ]
        })
        mock_urlopen.return_value = _mock_response(body)
        r = Registry(cache=self.cache)
        dep = Dependency(name="requests", declared_version="2.27.1",
                          constraint_type="exact", ecosystem="python")
        out = r.query_cves_batch([dep])
        self.assertIn(("requests", "python"), out)
        cves = out[("requests", "python")]
        self.assertEqual(len(cves), 1)
        self.assertEqual(cves[0].id, "CVE-2024-35195")

    @patch("dep_currency_check.registry.urllib.request.urlopen")
    def test_429_triggers_defer(self, mock_urlopen):
        # Simulate 3 consecutive timeouts → defer
        mock_urlopen.side_effect = urllib.error.URLError("timeout")
        r = Registry(cache=self.cache)
        for _ in range(3):
            v = r.query_version_latest("python", "x")
            self.assertIsNone(v)
        self.assertIn("pypi.org", r.deferred_hosts)


if __name__ == "__main__":
    unittest.main()
