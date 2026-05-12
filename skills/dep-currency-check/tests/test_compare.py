"""Tests for compare.py."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta

from dep_currency_check.compare import compare, _parse_semver, _resolve_declared
from dep_currency_check.manifests import Dependency
from dep_currency_check.registry import VersionInfo


def make_dep(declared: str, constraint_type: str = "range",
             is_dev: bool = False, is_transitive: bool = False) -> Dependency:
    return Dependency(
        name="x", declared_version=declared,
        constraint_type=constraint_type, ecosystem="python",
        is_dev=is_dev, is_transitive=is_transitive,
    )


def make_vi(latest: str = "1.0.0", deprecated: bool = False,
             yanked: tuple = (), age_days: int = 30) -> VersionInfo:
    return VersionInfo(
        package="x", ecosystem="python",
        latest_stable=latest, latest_any=latest,
        yanked_versions=yanked, deprecated=deprecated,
        deprecation_notice=None,
        last_release_at=datetime.now(timezone.utc) - timedelta(days=age_days),
        fetched_at=datetime.now(timezone.utc),
        source="pypi",
    )


class TestSemverParse(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_parse_semver("1.2.3"), (1, 2, 3))

    def test_with_v_prefix(self):
        self.assertEqual(_parse_semver("v1.2.3"), (1, 2, 3))

    def test_with_caret(self):
        self.assertEqual(_parse_semver("^1.2.3"), (1, 2, 3))

    def test_partial(self):
        self.assertEqual(_parse_semver("1"), (1, 0, 0))
        self.assertEqual(_parse_semver("1.2"), (1, 2, 0))

    def test_strips_prerelease(self):
        self.assertEqual(_parse_semver("1.2.3-beta"), (1, 2, 3))

    def test_invalid(self):
        self.assertIsNone(_parse_semver("not-a-version"))


class TestResolveDeclared(unittest.TestCase):
    def test_exact(self):
        d = make_dep("1.2.3", constraint_type="exact")
        self.assertEqual(_resolve_declared(d), "1.2.3")

    def test_range_takes_lower_bound(self):
        d = make_dep(">=2.0,<3", constraint_type="range")
        self.assertEqual(_resolve_declared(d), "2.0")

    def test_caret(self):
        d = make_dep("^1.2.3", constraint_type="caret")
        self.assertEqual(_resolve_declared(d), "1.2.3")


class TestCompare(unittest.TestCase):
    def test_exact_match_is_current(self):
        d = make_dep("1.0.0", constraint_type="exact")
        vi = make_vi("1.0.0")
        gap = compare(d, vi)
        self.assertEqual(gap.gap_kind, "current")

    def test_minor_behind_flagged_correctly(self):
        d = make_dep("1.0.0", constraint_type="exact")
        vi = make_vi("1.2.3")
        gap = compare(d, vi)
        self.assertEqual(gap.gap_kind, "minor_behind")
        self.assertEqual(gap.semver_distance, (0, 2, 3))

    def test_major_behind(self):
        d = make_dep("1.0.0", constraint_type="exact")
        vi = make_vi("3.0.0")
        gap = compare(d, vi)
        self.assertEqual(gap.gap_kind, "major_behind")

    def test_deprecated_outranks_minor_behind(self):
        d = make_dep("1.0.0", constraint_type="exact")
        vi = make_vi("1.2.3", deprecated=True)
        gap = compare(d, vi)
        self.assertEqual(gap.gap_kind, "deprecated")

    def test_yanked_resolves_to_flag(self):
        d = make_dep("1.0.0", constraint_type="exact")
        vi = make_vi("1.2.3", yanked=("1.0.0",))
        gap = compare(d, vi)
        self.assertEqual(gap.gap_kind, "yanked")

    def test_deferred_offline_when_no_versioninfo(self):
        d = make_dep("1.0.0", constraint_type="exact")
        gap = compare(d, None)
        self.assertEqual(gap.gap_kind, "deferred_offline")
        self.assertIsNone(gap.latest_stable)


if __name__ == "__main__":
    unittest.main()
