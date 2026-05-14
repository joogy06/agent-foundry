"""changelog.py — fetch API-change hints between two versions of a package.

Strategy: single source = GitHub `/releases` API. Cross-ecosystem because
most active packages publish release notes there, and parsing per-ecosystem
CHANGELOG.md files is a quagmire (every project uses different conventions).

For each declared->latest version delta we:
  1. Discover the package's GitHub repo URL from registry metadata
     (PyPI project_urls.Source / npm repository.url / crates.io repository / etc.)
  2. List releases on that repo (single API call, paginated up to 100)
  3. Filter to release tags that parse as semver and fall in (declared, latest]
  4. For each in-range release, extract the body and pull lines matching
     breaking/deprecation/migration keywords
  5. Return a structured `ApiDelta` dict, capped in size

Best-effort. Returns None on:
  - no discoverable GitHub repo URL
  - rate-limit hit (60/hr unauthenticated, 5000/hr with GITHUB_TOKEN env)
  - any HTTP / parse error

Cached for 7 days under cache namespace 'changelog' — release notes don't
change once published.

No LLM calls. Pure stdlib. Cap on total bytes returned: 3 KB per finding.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional
from urllib.parse import urlparse

from .cache import Cache

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_NAMESPACE = "changelog"     # TTL configured in cache.TTL
HTTP_TIMEOUT_S = 10
MAX_RELEASES_FETCHED = 100
MAX_VERSIONS_IN_RANGE = 5            # cap notes to 5 most-relevant versions
MAX_BODY_CHARS_PER_VERSION = 500     # truncate each release body
MAX_BREAKING_LINES = 15              # cap keyword-extracted lines
MAX_TOTAL_BYTES = 3000               # absolute size cap for ApiDelta payload

BREAKING_KEYWORDS = (
    "BREAKING", "Breaking", "breaking change",
    "removed", "Removed", "REMOVED",
    "deprecat", "Deprecat", "DEPRECAT",
    "no longer", "drop support", "incompat",
    "migration", "Migration", "MIGRATION",
)

SEMVER_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
# also accept package-prefixed tags ("pandas-1.5.3", "react-v18.0.0")
PREFIXED_TAG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]*-v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover_repo_url(package: str, ecosystem: str) -> Optional[str]:
    """Best-effort GitHub repo URL discovery from ecosystem metadata.

    Covers python / js / rust today (matches manifests.Ecosystem literals).
    Other ecosystems (go / ruby / java) return None and callers gracefully
    degrade to no `api_delta`.
    """
    try:
        if ecosystem == "python":
            return _discover_pypi(package)
        if ecosystem == "js":
            return _discover_npm(package)
        if ecosystem == "rust":
            return _discover_crates(package)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError, json.JSONDecodeError):
        return None
    return None


def fetch_api_delta(
    package: str,
    ecosystem: str,
    repo_url: Optional[str],
    from_version: str,
    to_version: str,
    cache: Optional[Cache] = None,
) -> Optional[dict]:
    """Return a structured ApiDelta dict, or None if not fetchable.

    `repo_url` is whatever the ecosystem registry told us. We extract the
    GitHub owner/repo from it if it's a github.com URL; otherwise return None.

    Shape on success:
      {
        "source": "github_releases",
        "repo_url": "https://github.com/owner/repo",
        "from_version": "1.5.3",
        "to_version": "2.2.3",
        "versions_in_range": ["2.0.0", "2.1.0", "2.2.0"],
        "breaking_lines": [
            "pandas 2.0.0: Series.append() removed",
            "pandas 2.0.0: deprecated get_option('compute.use_numexpr')",
            ...
        ],
        "release_notes_excerpt": "## 2.0.0\\n...\\n## 2.1.0\\n...",
        "truncated": true|false,
      }
    """
    if not repo_url:
        return None

    owner_repo = _extract_github_owner_repo(repo_url)
    if not owner_repo:
        return None

    # Cache scoped per (ecosystem, package, from->to). Use cache's
    # (class_, ecosystem, package) tuple with the version-pair appended to
    # the package field so each delta has its own entry.
    cache_pkg = f"{package}__{from_version}__{to_version}"
    if cache is not None:
        hit = cache.get(CACHE_NAMESPACE, ecosystem, cache_pkg)
        if hit is not None:
            return hit

    try:
        releases = _list_releases(*owner_repo)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        return None

    in_range = _filter_in_range(releases, from_version, to_version)
    if not in_range:
        return None

    in_range = in_range[:MAX_VERSIONS_IN_RANGE]

    breaking_lines: list[str] = []
    note_chunks: list[str] = []
    for rel in in_range:
        version = rel["version"]
        body = rel.get("body") or ""
        excerpt = body[:MAX_BODY_CHARS_PER_VERSION]
        note_chunks.append(f"## {version}\n{excerpt}")
        for line in _extract_breaking(body):
            if len(breaking_lines) >= MAX_BREAKING_LINES:
                break
            breaking_lines.append(f"{package} {version}: {line}")

    excerpt = "\n\n".join(note_chunks)
    truncated = False
    if len(excerpt.encode("utf-8")) > MAX_TOTAL_BYTES:
        excerpt = excerpt.encode("utf-8")[:MAX_TOTAL_BYTES].decode("utf-8", errors="ignore")
        truncated = True

    result = {
        "source": "github_releases",
        "repo_url": f"https://github.com/{owner_repo[0]}/{owner_repo[1]}",
        "from_version": from_version,
        "to_version": to_version,
        "versions_in_range": [r["version"] for r in in_range],
        "breaking_lines": breaking_lines,
        "release_notes_excerpt": excerpt,
        "truncated": truncated,
    }
    if cache is not None:
        cache.put(CACHE_NAMESPACE, ecosystem, cache_pkg, result)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _discover_pypi(package: str) -> Optional[str]:
    url = f"https://pypi.org/pypi/{package}/json"
    raw = _get_json(url)
    if not raw:
        return None
    info = raw.get("info") or {}
    # Prefer project_urls; check Source / Repository / Homepage in that order
    urls = info.get("project_urls") or {}
    for key in ("Source", "Source Code", "Repository", "Homepage", "Home"):
        v = urls.get(key)
        if v and "github.com" in v:
            return v
    home = info.get("home_page") or ""
    return home if "github.com" in home else None


def _discover_npm(package: str) -> Optional[str]:
    url = f"https://registry.npmjs.org/{urllib.parse.quote(package, safe='/@')}"
    raw = _get_json(url)
    if not raw:
        return None
    repo = raw.get("repository") or {}
    if isinstance(repo, dict):
        repo_url = repo.get("url") or ""
    else:
        repo_url = str(repo)
    # npm repository URLs are commonly "git+https://github.com/...", strip prefix
    if repo_url.startswith("git+"):
        repo_url = repo_url[4:]
    if repo_url.startswith("git://"):
        repo_url = "https://" + repo_url[len("git://"):]
    return repo_url if "github.com" in repo_url else None


def _discover_crates(package: str) -> Optional[str]:
    url = f"https://crates.io/api/v1/crates/{package}"
    raw = _get_json(url)
    if not raw:
        return None
    crate = raw.get("crate") or {}
    repo = crate.get("repository") or ""
    return repo if "github.com" in repo else None


def _get_json(url: str) -> Optional[dict]:
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "dep-currency-check/1.1",
    })
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return json.load(resp)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError, json.JSONDecodeError):
        return None


def _extract_github_owner_repo(repo_url: str) -> Optional[tuple[str, str]]:
    """Parse 'https://github.com/owner/repo[.git]' -> ('owner', 'repo')."""
    if not repo_url:
        return None
    try:
        parsed = urlparse(repo_url)
    except ValueError:
        return None
    host = (parsed.netloc or "").lower().replace("www.", "")
    if host != "github.com":
        return None
    parts = [p for p in (parsed.path or "").strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def _list_releases(owner: str, repo: str) -> list[dict]:
    """GET /repos/{owner}/{repo}/releases (per_page=100, page=1)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={MAX_RELEASES_FETCHED}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "dep-currency-check/1.1",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        data = json.load(resp)
    if not isinstance(data, list):
        return []
    return data


def _parse_version_from_tag(tag: str) -> Optional[tuple[int, int, int]]:
    """Extract (major, minor, patch) from a release tag, or None."""
    if not tag:
        return None
    m = SEMVER_TAG_RE.match(tag) or PREFIXED_TAG_RE.match(tag)
    if not m:
        return None
    try:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    except (ValueError, IndexError):
        return None


def _parse_version_string(v: str) -> Optional[tuple[int, int, int]]:
    """Same as _parse_version_from_tag but for a stripped version string."""
    if not v:
        return None
    v = v.lstrip("v")
    parts = v.split(".")
    if len(parts) < 3:
        # accept '1.5' as '1.5.0'
        while len(parts) < 3:
            parts.append("0")
    try:
        return int(parts[0]), int(parts[1]), int(parts[2].split("-")[0].split("+")[0])
    except (ValueError, IndexError):
        return None


def _filter_in_range(
    releases: list[dict], from_version: str, to_version: str
) -> list[dict]:
    """Keep releases whose parsed tag is in (from_version, to_version].

    Returned list is sorted ASCENDING by version (oldest to newest), so the
    excerpt reads chronologically.
    """
    lo = _parse_version_string(from_version)
    hi = _parse_version_string(to_version)
    if lo is None or hi is None:
        return []
    kept: list[tuple[tuple[int, int, int], dict]] = []
    for r in releases:
        if r.get("draft") or r.get("prerelease"):
            continue
        tag = r.get("tag_name") or ""
        ver = _parse_version_from_tag(tag)
        if ver is None:
            continue
        if ver <= lo or ver > hi:
            continue
        kept.append((ver, {
            "version": ".".join(str(x) for x in ver),
            "tag": tag,
            "name": r.get("name") or tag,
            "body": r.get("body") or "",
            "published_at": r.get("published_at") or "",
        }))
    kept.sort(key=lambda kv: kv[0])
    return [r for _, r in kept]


def _extract_breaking(body: str) -> list[str]:
    """Return lines from `body` that mention breaking/deprecation keywords.

    Strips markdown bullets, collapses whitespace, trims to ~150 chars/line.
    """
    if not body:
        return []
    out: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        # strip markdown bullets / heading markers
        line = re.sub(r"^[-*+#>\s]+", "", line)
        if not line:
            continue
        if any(kw in line for kw in BREAKING_KEYWORDS):
            out.append(line[:150])
            if len(out) >= MAX_BREAKING_LINES:
                break
    return out
