"""Unit tests for changelog.py — pure-function helpers, no network."""
from __future__ import annotations

import unittest

from dep_currency_check.changelog import (
    _extract_breaking,
    _extract_github_owner_repo,
    _filter_in_range,
    _parse_version_from_tag,
    _parse_version_string,
)


class TestExtractGithubOwnerRepo(unittest.TestCase):
    def test_canonical(self):
        self.assertEqual(
            _extract_github_owner_repo("https://github.com/pandas-dev/pandas"),
            ("pandas-dev", "pandas"),
        )

    def test_dot_git_suffix(self):
        self.assertEqual(
            _extract_github_owner_repo("https://github.com/foo/bar.git"),
            ("foo", "bar"),
        )

    def test_www_prefix(self):
        self.assertEqual(
            _extract_github_owner_repo("https://www.github.com/x/y"),
            ("x", "y"),
        )

    def test_not_github(self):
        self.assertIsNone(_extract_github_owner_repo("https://gitlab.com/x/y"))

    def test_empty(self):
        self.assertIsNone(_extract_github_owner_repo(""))

    def test_short_path(self):
        self.assertIsNone(_extract_github_owner_repo("https://github.com/onlyone"))


class TestParseVersionFromTag(unittest.TestCase):
    def test_bare(self):
        self.assertEqual(_parse_version_from_tag("1.2.3"), (1, 2, 3))

    def test_v_prefix(self):
        self.assertEqual(_parse_version_from_tag("v1.2.3"), (1, 2, 3))

    def test_prerelease_suffix(self):
        self.assertEqual(_parse_version_from_tag("v1.2.3-alpha.1"), (1, 2, 3))

    def test_prefixed(self):
        self.assertEqual(_parse_version_from_tag("pandas-1.5.3"), (1, 5, 3))
        self.assertEqual(_parse_version_from_tag("react-v18.2.0"), (18, 2, 0))

    def test_not_semver(self):
        self.assertIsNone(_parse_version_from_tag("master"))
        self.assertIsNone(_parse_version_from_tag(""))
        self.assertIsNone(_parse_version_from_tag("release"))


class TestParseVersionString(unittest.TestCase):
    def test_canonical(self):
        self.assertEqual(_parse_version_string("1.5.3"), (1, 5, 3))

    def test_v_prefix(self):
        self.assertEqual(_parse_version_string("v2.0.0"), (2, 0, 0))

    def test_two_segments(self):
        self.assertEqual(_parse_version_string("1.5"), (1, 5, 0))

    def test_prerelease(self):
        self.assertEqual(_parse_version_string("2.0.0-rc1"), (2, 0, 0))


class TestFilterInRange(unittest.TestCase):
    def setUp(self):
        # Mock releases — order is intentionally scrambled to test sorting
        self.releases = [
            {"tag_name": "v2.2.0", "body": "feature work", "draft": False, "prerelease": False},
            {"tag_name": "v2.0.0", "body": "## BREAKING\n- removed Series.append()", "draft": False, "prerelease": False},
            {"tag_name": "v1.5.3", "body": "patch", "draft": False, "prerelease": False},
            {"tag_name": "v2.1.0", "body": "## Deprecated\n- iteritems", "draft": False, "prerelease": False},
            {"tag_name": "v3.0.0-alpha", "body": "alpha", "draft": False, "prerelease": True},  # filtered as prerelease
            {"tag_name": "main", "body": "non-semver", "draft": False, "prerelease": False},   # filtered as non-semver
        ]

    def test_in_range_exclusive_lower_inclusive_upper(self):
        kept = _filter_in_range(self.releases, "1.5.3", "2.2.3")
        versions = [r["version"] for r in kept]
        self.assertEqual(versions, ["2.0.0", "2.1.0", "2.2.0"])  # sorted ASC

    def test_excludes_lower_bound(self):
        kept = _filter_in_range(self.releases, "1.5.3", "1.5.3")
        self.assertEqual(kept, [])

    def test_above_latest_excluded(self):
        kept = _filter_in_range(self.releases, "1.5.3", "2.0.0")
        self.assertEqual([r["version"] for r in kept], ["2.0.0"])

    def test_skips_prerelease_and_non_semver(self):
        kept = _filter_in_range(self.releases, "1.5.3", "3.0.0")
        # alpha + main filtered
        self.assertEqual([r["version"] for r in kept], ["2.0.0", "2.1.0", "2.2.0"])


class TestExtractBreaking(unittest.TestCase):
    def test_extracts_breaking_keywords(self):
        body = """
        ## What's new
        - Added: new feature X
        - BREAKING: removed support for legacy Y
        - deprecated: old_api() will be removed in next major
        - Bug fixes
        """
        lines = _extract_breaking(body)
        self.assertEqual(len(lines), 2)
        self.assertTrue(any("BREAKING" in ln for ln in lines))
        self.assertTrue(any("deprecated" in ln for ln in lines))

    def test_caps_at_15(self):
        body = "\n".join(f"- BREAKING change #{i}" for i in range(50))
        lines = _extract_breaking(body)
        self.assertEqual(len(lines), 15)

    def test_empty_body(self):
        self.assertEqual(_extract_breaking(""), [])
        self.assertEqual(_extract_breaking(None or ""), [])

    def test_strips_markdown_bullets(self):
        body = "- BREAKING: foo removed\n* deprecated: bar"
        lines = _extract_breaking(body)
        for ln in lines:
            self.assertFalse(ln.startswith("-"))
            self.assertFalse(ln.startswith("*"))


if __name__ == "__main__":
    unittest.main()
