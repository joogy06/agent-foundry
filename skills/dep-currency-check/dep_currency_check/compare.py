"""compare.py — semver diff + gap classification.

Stdlib only. Stateless functions. Public API:
    Gap (frozen dataclass)
    compare(declared: Dependency, latest: VersionInfo | None) -> Gap
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

from .manifests import Dependency
from .registry import VersionInfo

GapKind = Literal[
    "current", "minor_behind", "major_behind", "deprecated",
    "yanked", "unmaintained", "unknown", "deferred_offline",
]


@dataclass(frozen=True)
class Gap:
    dep: Dependency
    declared_resolves_to: Optional[str]
    latest_stable: Optional[str]
    gap_kind: GapKind
    semver_distance: Optional[tuple]
    last_release_age_days: Optional[int]


SEMVER_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def _parse_semver(version: str) -> Optional[tuple]:
    """Parse a semver-ish string into (major, minor, patch). Best-effort.
    Strips leading 'v', operator chars."""
    if not version:
        return None
    v = version.strip().lstrip("v=^~ <>!")
    # Take just the bare version (drop pre-release / build metadata)
    v = v.split("-", 1)[0].split("+", 1)[0]
    # Drop ranges: ">=2.0,<3" → take "2.0"
    v = v.split(",", 1)[0].lstrip("<>=^~ !").strip()
    m = SEMVER_RE.match(v)
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2)) if m.group(2) else 0
    patch = int(m.group(3)) if m.group(3) else 0
    return (major, minor, patch)


def _resolve_declared(dep: Dependency) -> Optional[str]:
    """Best-effort: what concrete version does dep.declared_version
    resolve to? Returns version string or None.

    For exact / git / path: use as-is or None.
    For range: take the lower bound.
    For caret/tilde: take the base version.
    """
    ct = dep.constraint_type
    v = dep.declared_version.strip()
    if ct == "exact":
        return v.lstrip("=").strip()
    if ct in ("caret", "tilde"):
        return v.lstrip("^~").strip()
    if ct == "range":
        # Take the >= bound
        for part in v.split(","):
            p = part.strip()
            if p.startswith(">="):
                return p[2:].strip()
            if p.startswith(">"):
                return p[1:].strip()
        # Just take the first version-looking token
        m = SEMVER_RE.search(v)
        if m:
            return m.group(0)
        return None
    if ct == "wildcard":
        # "1.2.*" → "1.2.0" approximately
        return v.replace("*", "0").strip()
    if ct == "unspecified":
        return None
    # git, path: opaque
    return None


def compare(declared: Dependency,
            latest: Optional[VersionInfo]) -> Gap:
    """Compare declared dep against latest VersionInfo. Return Gap."""
    if latest is None:
        return Gap(
            dep=declared, declared_resolves_to=_resolve_declared(declared),
            latest_stable=None, gap_kind="deferred_offline",
            semver_distance=None, last_release_age_days=None,
        )

    declared_v = _resolve_declared(declared)
    latest_v = latest.latest_stable

    # Yanked check
    if declared_v and declared_v in latest.yanked_versions:
        return Gap(
            dep=declared, declared_resolves_to=declared_v,
            latest_stable=latest_v, gap_kind="yanked",
            semver_distance=None, last_release_age_days=None,
        )

    # Deprecated check (registry-level)
    if latest.deprecated:
        return Gap(
            dep=declared, declared_resolves_to=declared_v,
            latest_stable=latest_v, gap_kind="deprecated",
            semver_distance=None, last_release_age_days=None,
        )

    # Unmaintained soft-signal: no release in 18+ months
    age_days = None
    if latest.last_release_at:
        try:
            now = datetime.now(timezone.utc)
            delta = now - latest.last_release_at
            age_days = delta.days
        except (TypeError, ValueError):
            age_days = None

    # Parse both versions
    decl_p = _parse_semver(declared_v or "")
    lat_p = _parse_semver(latest_v)

    if not lat_p:
        return Gap(
            dep=declared, declared_resolves_to=declared_v,
            latest_stable=latest_v, gap_kind="unknown",
            semver_distance=None, last_release_age_days=age_days,
        )
    if not decl_p:
        # Can't compare — unknown
        if age_days and age_days > 540:  # 18 months
            return Gap(
                dep=declared, declared_resolves_to=declared_v,
                latest_stable=latest_v, gap_kind="unmaintained",
                semver_distance=None, last_release_age_days=age_days,
            )
        return Gap(
            dep=declared, declared_resolves_to=declared_v,
            latest_stable=latest_v, gap_kind="unknown",
            semver_distance=None, last_release_age_days=age_days,
        )

    # Compute distance
    dist = (lat_p[0] - decl_p[0], lat_p[1] - decl_p[1], lat_p[2] - decl_p[2])

    if dist == (0, 0, 0):
        kind: GapKind = "current"
    elif dist[0] > 0:
        kind = "major_behind"
    elif dist[1] > 0 or dist[2] > 0:
        kind = "minor_behind"
    elif dist[0] < 0 or dist[1] < 0 or dist[2] < 0:
        # Declared is ahead of "latest_stable" — quirk; treat as current
        kind = "current"
    else:
        kind = "current"

    # Unmaintained overrides if very old
    if age_days and age_days > 540 and kind != "current":
        kind = "unmaintained"

    return Gap(
        dep=declared, declared_resolves_to=declared_v,
        latest_stable=latest_v, gap_kind=kind,
        semver_distance=dist, last_release_age_days=age_days,
    )
