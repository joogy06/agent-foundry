"""registry.py — stdlib HTTP layer + OSV.dev integration.

Stdlib only (urllib.request). Covers all 6 ecosystems as FALLBACK data path
(primary is community_wrappers.py). See references/http-protocol.md.

Public API:
    Severity = Literal["none","low","moderate","high","critical","unknown"]
    VersionInfo (frozen dataclass)
    CVE (frozen dataclass)
    Registry class
        .query_version_latest(ecosystem, package, *, no_cache, offline) -> VersionInfo | None
        .query_cves_batch(deps, *, no_cache, offline) -> dict[(name, eco), list[CVE]]
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Mapping, Optional, Sequence

from .cache import Cache
from .manifests import Dependency, Ecosystem

Severity = Literal["none", "low", "moderate", "high", "critical", "unknown"]


@dataclass(frozen=True)
class VersionInfo:
    package: str
    ecosystem: str
    latest_stable: str
    latest_any: str
    yanked_versions: tuple
    deprecated: bool
    deprecation_notice: Optional[str]
    last_release_at: Optional[datetime]
    fetched_at: datetime
    source: str


@dataclass(frozen=True)
class CVE:
    id: str
    severity: Severity
    cvss_score: Optional[float]
    summary: str
    affected_range: str
    fixed_versions: tuple
    published: Optional[datetime]
    source: str  # "osv" | "pypi-advisory"
    osv_id: Optional[str]


# OSV ecosystem mapping
OSV_ECO = {
    "python": "PyPI",
    "js": "npm",
    "rust": "crates.io",
    "go": "Go",
    "ruby": "RubyGems",
    "java": "Maven",
}

USER_AGENT = "dep-currency-check/0.1.0"
DEFAULT_TIMEOUT_S = 10.0


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------


class NetworkError(Exception):
    """Raised internally on irrecoverable network failure (vs deferred)."""


class StrictAirgapViolation(Exception):
    """Raised when --strict-airgap is set and any network attempt occurs."""


def _ssl_ctx() -> ssl.SSLContext:
    return ssl.create_default_context()


def _http_get(url: str, *, headers: Optional[Mapping[str, str]] = None,
              timeout: float = DEFAULT_TIMEOUT_S,
              strict_airgap: bool = False) -> tuple:
    """GET request. Returns (status, body_text, response_headers).
    Raises NetworkError on connection issues; HTTPError caller-handled."""
    if strict_airgap:
        raise StrictAirgapViolation(f"strict-airgap: GET {url}")
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                     context=_ssl_ctx()) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return (resp.status, body, dict(resp.headers))
    except urllib.error.HTTPError as e:
        # 304 is success-with-no-body, 4xx/5xx are errors caller handles
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return (e.code, body, dict(e.headers) if e.headers else {})
    except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as e:
        raise NetworkError(f"GET {url} failed: {e}")


def _http_post_json(url: str, body: dict, *,
                    timeout: float = DEFAULT_TIMEOUT_S,
                    strict_airgap: bool = False) -> tuple:
    """POST JSON. Returns (status, body_text)."""
    if strict_airgap:
        raise StrictAirgapViolation(f"strict-airgap: POST {url}")
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": USER_AGENT,
                 "Content-Type": "application/json",
                 "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                     context=_ssl_ctx()) as resp:
            return (resp.status, resp.read().decode("utf-8",
                                                      errors="replace"))
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return (e.code, body_text)
    except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as e:
        raise NetworkError(f"POST {url} failed: {e}")


# ---------------------------------------------------------------------------
# Per-ecosystem registry queries
# ---------------------------------------------------------------------------


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Try with Z
        if s.endswith("Z"):
            return datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _query_pypi(package: str, *, strict_airgap: bool = False) -> Optional[dict]:
    """Return raw PyPI JSON or None on network failure."""
    url = f"https://pypi.org/pypi/{urllib.parse.quote(package)}/json"
    try:
        status, body, _ = _http_get(url, strict_airgap=strict_airgap)
    except NetworkError:
        return None
    if status != 200:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _pypi_to_versioninfo(raw: dict, package: str) -> Optional[VersionInfo]:
    if not raw:
        return None
    info = raw.get("info") or {}
    releases = raw.get("releases") or {}
    yanked = []
    last_release = None
    for ver, files in releases.items():
        if not files:
            continue
        for f in files:
            if f.get("yanked"):
                yanked.append(ver)
                break
        # Track last release time
        for f in files:
            t = _parse_iso(f.get("upload_time_iso_8601", ""))
            if t and (last_release is None or t > last_release):
                last_release = t
    latest_stable = info.get("version", "") or ""
    return VersionInfo(
        package=package, ecosystem="python",
        latest_stable=latest_stable, latest_any=latest_stable,
        yanked_versions=tuple(yanked),
        deprecated=False,  # PyPI doesn't have a registry-level deprecation flag
        deprecation_notice=None,
        last_release_at=last_release,
        fetched_at=datetime.now(timezone.utc),
        source="pypi",
    )


def _query_npm(package: str, *, strict_airgap: bool = False) -> Optional[dict]:
    """Query npm registry. Returns raw response."""
    encoded = urllib.parse.quote(package, safe="@/")
    url = f"https://registry.npmjs.org/{encoded}/latest"
    try:
        status, body, _ = _http_get(url, strict_airgap=strict_airgap)
    except NetworkError:
        return None
    if status != 200:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _npm_to_versioninfo(raw: dict, package: str) -> Optional[VersionInfo]:
    if not raw:
        return None
    version = raw.get("version", "")
    if not version:
        return None
    deprecated_msg = raw.get("deprecated")
    is_dep = bool(deprecated_msg) and deprecated_msg is not True
    notice = deprecated_msg if isinstance(deprecated_msg, str) else None
    return VersionInfo(
        package=package, ecosystem="js",
        latest_stable=version, latest_any=version,
        yanked_versions=tuple(),
        deprecated=bool(deprecated_msg),
        deprecation_notice=notice,
        last_release_at=None,
        fetched_at=datetime.now(timezone.utc),
        source="npm",
    )


def _crates_sparse_prefix(name: str) -> str:
    """crates.io sparse index path prefix per name length."""
    n = name.lower()
    if len(n) == 1:
        return f"1/{n}"
    if len(n) == 2:
        return f"2/{n}"
    if len(n) == 3:
        return f"3/{n[0]}/{n}"
    return f"{n[:2]}/{n[2:4]}/{n}"


def _query_crates_sparse(package: str, *,
                         strict_airgap: bool = False) -> Optional[VersionInfo]:
    """Query crates.io sparse index. No rate limit on this endpoint."""
    url = f"https://index.crates.io/{_crates_sparse_prefix(package)}"
    try:
        status, body, _ = _http_get(url, strict_airgap=strict_airgap)
    except NetworkError:
        return None
    if status != 200:
        return None
    # JSONL: one record per version
    latest_stable = ""
    yanked = []
    last_time = None
    for line in body.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        ver = rec.get("vers", "")
        if not ver:
            continue
        if rec.get("yanked"):
            yanked.append(ver)
            continue
        # Skip pre-release (contains -)
        if "-" in ver:
            continue
        latest_stable = ver  # last non-yanked non-prerelease wins (sparse is ordered)
    if not latest_stable:
        return None
    return VersionInfo(
        package=package, ecosystem="rust",
        latest_stable=latest_stable, latest_any=latest_stable,
        yanked_versions=tuple(yanked),
        deprecated=False, deprecation_notice=None,
        last_release_at=last_time,
        fetched_at=datetime.now(timezone.utc),
        source="crates-sparse",
    )


def _escape_go_caps(module: str) -> str:
    """Go module proxy escaping: capital letter X → !x."""
    out = []
    for ch in module:
        if ch.isupper():
            out.append("!" + ch.lower())
        else:
            out.append(ch)
    return "".join(out)


def _query_go_proxy(module: str, *,
                    strict_airgap: bool = False) -> Optional[VersionInfo]:
    """Query Go module proxy /@latest. Returns VersionInfo or None."""
    escaped = _escape_go_caps(module)
    url = f"https://proxy.golang.org/{urllib.parse.quote(escaped, safe='/.!')}/@latest"
    try:
        status, body, _ = _http_get(url, strict_airgap=strict_airgap)
    except NetworkError:
        return None
    if status != 200:
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    version = data.get("Version", "")
    if not version:
        return None
    t = _parse_iso(data.get("Time", ""))
    return VersionInfo(
        package=module, ecosystem="go",
        latest_stable=version, latest_any=version,
        yanked_versions=tuple(),
        deprecated=False, deprecation_notice=None,
        last_release_at=t,
        fetched_at=datetime.now(timezone.utc),
        source="go-proxy",
    )


def _query_rubygems(package: str, *,
                    strict_airgap: bool = False) -> Optional[VersionInfo]:
    url = f"https://rubygems.org/api/v1/gems/{urllib.parse.quote(package)}.json"
    try:
        status, body, _ = _http_get(url, strict_airgap=strict_airgap)
    except NetworkError:
        return None
    if status != 200:
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    version = data.get("version", "")
    if not version:
        return None
    return VersionInfo(
        package=package, ecosystem="ruby",
        latest_stable=version, latest_any=version,
        yanked_versions=tuple(),
        deprecated=False, deprecation_notice=None,
        last_release_at=None,
        fetched_at=datetime.now(timezone.utc),
        source="rubygems",
    )


def _query_maven(coord: str, *,
                 strict_airgap: bool = False) -> Optional[VersionInfo]:
    """coord = 'group:artifact'. Returns VersionInfo or None."""
    if ":" not in coord:
        return None
    group, artifact = coord.split(":", 1)
    url = (f"https://search.maven.org/solrsearch/select?"
           f"q=g:{urllib.parse.quote(group)}+AND+a:{urllib.parse.quote(artifact)}"
           f"&core=gav&rows=1&wt=json")
    try:
        status, body, _ = _http_get(url, strict_airgap=strict_airgap)
    except NetworkError:
        return None
    if status != 200:
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    docs = (data.get("response") or {}).get("docs") or []
    if not docs:
        return None
    version = docs[0].get("v", "") or docs[0].get("latestVersion", "")
    if not version:
        return None
    return VersionInfo(
        package=coord, ecosystem="java",
        latest_stable=version, latest_any=version,
        yanked_versions=tuple(),
        deprecated=False, deprecation_notice=None,
        last_release_at=None,
        fetched_at=datetime.now(timezone.utc),
        source="maven-central",
    )


# ---------------------------------------------------------------------------
# OSV /v1/querybatch
# ---------------------------------------------------------------------------


def _osv_severity(vuln: dict) -> tuple:
    """Return (severity, cvss_score) from an OSV record."""
    # Try database_specific.severity
    db = vuln.get("database_specific") or {}
    sev_raw = (db.get("severity") or "").lower()
    if sev_raw in ("critical", "high", "moderate", "medium", "low"):
        sev = "moderate" if sev_raw == "medium" else sev_raw
        return (sev, None)
    # Try CVSS v3 score from severity[] array
    for s in vuln.get("severity") or []:
        if s.get("type", "").upper().startswith("CVSS"):
            try:
                score = float(s.get("score", "").split("/")[1].split(":")[1]
                              if "/" in s.get("score", "") else s.get("score", ""))
            except (ValueError, IndexError, AttributeError):
                # Score might already be a bare number
                try:
                    score = float(s.get("score", 0))
                except (ValueError, TypeError):
                    continue
            if score >= 9.0:
                return ("critical", score)
            if score >= 7.0:
                return ("high", score)
            if score >= 4.0:
                return ("moderate", score)
            return ("low", score)
    return ("unknown", None)


def _osv_to_cve(vuln: dict, ecosystem: str) -> CVE:
    """Convert one OSV vuln record into our CVE shape."""
    sev, score = _osv_severity(vuln)
    cve_id = vuln.get("id", "")
    # Prefer CVE-* aliases when available
    aliases = vuln.get("aliases") or []
    for alias in aliases:
        if alias.startswith("CVE-"):
            cve_id_alias = alias
            break
    else:
        cve_id_alias = cve_id
    # Affected ranges and fixed_versions
    affected_str_parts = []
    fixed_vers: list = []
    for affected in vuln.get("affected") or []:
        for r in affected.get("ranges") or []:
            for ev in r.get("events") or []:
                if "introduced" in ev:
                    affected_str_parts.append(f">={ev['introduced']}")
                if "fixed" in ev:
                    fixed_vers.append(ev["fixed"])
                    affected_str_parts.append(f"<{ev['fixed']}")
    return CVE(
        id=cve_id_alias,
        severity=sev,
        cvss_score=score,
        summary=vuln.get("summary", "") or vuln.get("details", "")[:200],
        affected_range=",".join(affected_str_parts) if affected_str_parts else "*",
        fixed_versions=tuple(fixed_vers),
        published=_parse_iso(vuln.get("published", "")),
        source="osv",
        osv_id=cve_id if cve_id != cve_id_alias else None,
    )


# ---------------------------------------------------------------------------
# Registry class — public API
# ---------------------------------------------------------------------------


class Registry:
    def __init__(self, *, cache: Optional[Cache] = None,
                 strict_airgap: bool = False) -> None:
        self.cache = cache or Cache()
        self.strict_airgap = strict_airgap
        # Per-host failure tally for deferred-after-3-fails behavior
        self.host_failures: dict = {}
        self.deferred_hosts: set = set()

    def _maybe_defer(self, host: str, ok: bool) -> bool:
        """Returns True if the host is now deferred."""
        if not ok:
            self.host_failures[host] = self.host_failures.get(host, 0) + 1
            if self.host_failures[host] >= 3:
                self.deferred_hosts.add(host)
                return True
        return host in self.deferred_hosts

    def query_version_latest(self, ecosystem: str, package: str,
                              *, no_cache: bool = False,
                              offline: bool = False) -> Optional[VersionInfo]:
        """Returns VersionInfo or None. None ONLY when offline AND cache cold,
        OR registry not reachable, OR package not found."""
        # Cache lookup (always — even in no_cache we check ignore_ttl version)
        if not no_cache:
            cached = self.cache.get("versions", ecosystem, package)
            if cached is not None:
                try:
                    return _dict_to_versioninfo(cached)
                except (KeyError, ValueError):
                    pass
        if offline:
            # No network attempt allowed
            return None

        # Dispatch per ecosystem
        host_map = {
            "python": "pypi.org", "js": "registry.npmjs.org",
            "rust": "index.crates.io", "go": "proxy.golang.org",
            "ruby": "rubygems.org", "java": "search.maven.org",
        }
        host = host_map.get(ecosystem, "")
        if host in self.deferred_hosts:
            return None

        try:
            if ecosystem == "python":
                raw = _query_pypi(package, strict_airgap=self.strict_airgap)
                vi = _pypi_to_versioninfo(raw, package) if raw else None
            elif ecosystem == "js":
                raw = _query_npm(package, strict_airgap=self.strict_airgap)
                vi = _npm_to_versioninfo(raw, package) if raw else None
            elif ecosystem == "rust":
                vi = _query_crates_sparse(package,
                                           strict_airgap=self.strict_airgap)
            elif ecosystem == "go":
                vi = _query_go_proxy(package,
                                      strict_airgap=self.strict_airgap)
            elif ecosystem == "ruby":
                vi = _query_rubygems(package,
                                      strict_airgap=self.strict_airgap)
            elif ecosystem == "java":
                vi = _query_maven(package,
                                    strict_airgap=self.strict_airgap)
            else:
                return None
        except StrictAirgapViolation:
            return None

        self._maybe_defer(host, vi is not None)

        if vi is not None:
            self.cache.put("versions", ecosystem, package,
                            _versioninfo_to_dict(vi))
        return vi

    def query_cves_batch(self, deps: Sequence[Dependency],
                          *, no_cache: bool = False,
                          offline: bool = False) -> dict:
        """Returns dict[(package, ecosystem), list[CVE]]. Empty list = no CVEs."""
        out: dict = {}
        # Cache lookup per dep (vulns class)
        to_query: list = []
        for d in deps:
            key = (d.name, d.ecosystem)
            if key in out:
                continue
            if not no_cache:
                cached = self.cache.get("vulns", d.ecosystem, d.name)
                if cached is not None:
                    try:
                        out[key] = tuple(_dict_to_cve(c) for c in cached.get("cves", []))
                    except (KeyError, ValueError):
                        cached = None
                    if cached is not None:
                        continue
            to_query.append(d)

        if offline or not to_query:
            for d in deps:
                out.setdefault((d.name, d.ecosystem), tuple())
            return out

        # Group by OSV ecosystem and batch
        if "api.osv.dev" in self.deferred_hosts:
            for d in deps:
                out.setdefault((d.name, d.ecosystem), tuple())
            return out

        queries = []
        query_index: list = []  # parallel: (package, ecosystem) for each entry
        for d in to_query:
            osv_eco = OSV_ECO.get(d.ecosystem)
            if not osv_eco:
                continue
            # OSV wants either version or no version (latter returns all CVEs).
            # We use the resolved version when available; declared otherwise.
            version = d.declared_version.lstrip("<>=^~ !").split(",")[0].strip()
            if not version or not version.replace(".", "").replace("-", "").isalnum():
                # Bad version — query without version (returns broader set)
                queries.append({
                    "package": {"name": d.name, "ecosystem": osv_eco},
                })
            else:
                queries.append({
                    "package": {"name": d.name, "ecosystem": osv_eco},
                    "version": version,
                })
            query_index.append((d.name, d.ecosystem))

        if not queries:
            for d in deps:
                out.setdefault((d.name, d.ecosystem), tuple())
            return out

        try:
            status, body = _http_post_json(
                "https://api.osv.dev/v1/querybatch",
                {"queries": queries},
                timeout=30.0,
                strict_airgap=self.strict_airgap,
            )
        except (NetworkError, StrictAirgapViolation):
            self._maybe_defer("api.osv.dev", False)
            for d in deps:
                out.setdefault((d.name, d.ecosystem), tuple())
            return out

        if status != 200:
            self._maybe_defer("api.osv.dev", False)
            for d in deps:
                out.setdefault((d.name, d.ecosystem), tuple())
            return out

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            for d in deps:
                out.setdefault((d.name, d.ecosystem), tuple())
            return out

        results = data.get("results") or []
        for i, result in enumerate(results):
            if i >= len(query_index):
                break
            name, eco = query_index[i]
            vulns = result.get("vulns") or []
            cves = tuple(_osv_to_cve(v, eco) for v in vulns)
            out[(name, eco)] = cves
            # Persist to cache
            self.cache.put("vulns", eco, name,
                            {"cves": [_cve_to_dict(c) for c in cves]})

        # Fill in misses with empty tuple (no CVEs found)
        for d in deps:
            out.setdefault((d.name, d.ecosystem), tuple())
        return out


# ---------------------------------------------------------------------------
# Dataclass <-> dict converters for cache persistence
# ---------------------------------------------------------------------------


def _versioninfo_to_dict(vi: VersionInfo) -> dict:
    return {
        "package": vi.package,
        "ecosystem": vi.ecosystem,
        "latest_stable": vi.latest_stable,
        "latest_any": vi.latest_any,
        "yanked_versions": list(vi.yanked_versions),
        "deprecated": vi.deprecated,
        "deprecation_notice": vi.deprecation_notice,
        "last_release_at": vi.last_release_at.isoformat() if vi.last_release_at else None,
        "fetched_at": vi.fetched_at.isoformat(),
        "source": vi.source,
    }


def _dict_to_versioninfo(d: dict) -> VersionInfo:
    return VersionInfo(
        package=d["package"], ecosystem=d["ecosystem"],
        latest_stable=d["latest_stable"], latest_any=d["latest_any"],
        yanked_versions=tuple(d.get("yanked_versions", [])),
        deprecated=d.get("deprecated", False),
        deprecation_notice=d.get("deprecation_notice"),
        last_release_at=_parse_iso(d.get("last_release_at", "") or ""),
        fetched_at=_parse_iso(d["fetched_at"]) or datetime.now(timezone.utc),
        source=d.get("source", "unknown"),
    )


def _cve_to_dict(c: CVE) -> dict:
    return {
        "id": c.id, "severity": c.severity, "cvss_score": c.cvss_score,
        "summary": c.summary, "affected_range": c.affected_range,
        "fixed_versions": list(c.fixed_versions),
        "published": c.published.isoformat() if c.published else None,
        "source": c.source, "osv_id": c.osv_id,
    }


def _dict_to_cve(d: dict) -> CVE:
    return CVE(
        id=d["id"], severity=d["severity"], cvss_score=d.get("cvss_score"),
        summary=d.get("summary", ""), affected_range=d.get("affected_range", ""),
        fixed_versions=tuple(d.get("fixed_versions", [])),
        published=_parse_iso(d.get("published", "") or ""),
        source=d.get("source", "osv"), osv_id=d.get("osv_id"),
    )
