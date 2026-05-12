"""Tests for cache.py."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from dep_currency_check.cache import TTL, Cache


class TestCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dcc-cache-")
        self.cache = Cache(base=Path(self.tmp))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cache_put_then_get_within_ttl(self):
        self.cache.put("versions", "python", "requests",
                        {"latest_stable": "2.32.3"})
        v = self.cache.get("versions", "python", "requests")
        self.assertIsNotNone(v)
        self.assertEqual(v["latest_stable"], "2.32.3")

    def test_cache_expires_after_ttl(self):
        self.cache.put("vulns", "python", "x", {"cves": []})
        # Manually age it past the TTL (vulns = 2h)
        p = self.cache._path("vulns", "python", "x")
        old = time.time() - TTL["vulns"] - 10
        os.utime(str(p), (old, old))
        v = self.cache.get("vulns", "python", "x")
        self.assertIsNone(v)

    def test_cache_atomic_write_no_partial_file(self):
        self.cache.put("versions", "js", "react", {"version": "18"})
        # Make sure no .tmp file lingers
        d = self.cache._path("versions", "js", "react").parent
        tmps = list(d.glob("react.json.tmp*"))
        self.assertEqual(tmps, [])

    def test_no_cache_flag_bypasses_cache(self):
        self.cache.put("versions", "python", "x", {"v": "1"})
        no_cache = Cache(base=self.cache.base, no_cache=True)
        self.assertIsNone(no_cache.get("versions", "python", "x"))

    def test_etag_round_trip(self):
        self.cache.set_etag("versions", "python", "x", '"abc123"')
        self.assertEqual(
            self.cache.etag_for("versions", "python", "x"), '"abc123"'
        )

    def test_ignore_ttl_returns_stale_entries(self):
        self.cache.put("vulns", "python", "x", {"cves": []})
        # Age past TTL
        p = self.cache._path("vulns", "python", "x")
        old = time.time() - TTL["vulns"] - 10
        os.utime(str(p), (old, old))
        # Standard cache: get returns None
        self.assertIsNone(self.cache.get("vulns", "python", "x"))
        # ignore_ttl cache: get returns the stale value
        c2 = Cache(base=self.cache.base, ignore_ttl=True)
        self.assertEqual(c2.get("vulns", "python", "x"), {"cves": []})


if __name__ == "__main__":
    unittest.main()
