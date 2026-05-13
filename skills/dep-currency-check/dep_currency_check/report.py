"""report.py — assemble Report + canonical JSON + rendering layer.

Stdlib only. JSON is the canonical data contract; everything else (markdown,
table, yaml, osv) is a rendering over the JSON.

Public API:
    Finding (frozen dataclass)
    Report (frozen dataclass)
    assemble_report(...)
    render_json(report) -> str
    render_markdown(report) -> str
    render_table(report) -> str
    render_yaml(report) -> str
    render_osv_records(report) -> str
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Mapping, Optional

from .compare import Gap, GapKind
from .manifests import Dependency, Manifest
from .registry import CVE, VersionInfo

SCHEMA_VERSION = "dep-currency.v1"


@dataclass(frozen=True)
class Finding:
    dep: Dependency
    gap: Gap
    cves: tuple
    blocks_build: bool
    api_delta: Optional[dict] = None   # set when gap is major_behind/deprecated and changelog fetch succeeded


GroundingMode = Literal["full", "internal-only", "offline-cold-cache"]


@dataclass(frozen=True)
class Report:
    project_root: Path
    schema_version: str
    generated_at: datetime
    grounding_mode: GroundingMode
    manifests_scanned: tuple
    findings: tuple
    summary: dict
    advisories: tuple


def compute_blocks_build(finding_inputs: dict) -> bool:
    """Per spec: blocks_build is True ONLY when ALL of:
    - severity == "critical"
    - is_direct (not transitive)
    - NOT is_dev (production dep)
    - at least one CVE has non-empty fixed_versions
    """
    dep: Dependency = finding_inputs["dep"]
    cves: tuple = finding_inputs["cves"]
    if dep.is_transitive:
        return False
    if dep.is_dev:
        return False
    for cve in cves:
        if cve.severity == "critical" and cve.fixed_versions:
            return True
    return False


def assemble_report(
    project_root: Path,
    manifests: list,
    findings: list,
    *,
    grounding_mode: GroundingMode = "full",
    advisories: Optional[list] = None,
) -> Report:
    """Assemble findings + manifests into a canonical Report."""
    manifests_scanned = tuple(m.path.relative_to(project_root)
                               if project_root in m.path.parents
                               or project_root == m.path.parent
                               else m.path
                               for m in manifests)
    # Compute summary counts
    summary: dict = {
        "critical": 0, "high": 0, "moderate": 0, "low": 0,
        "deprecated": 0, "yanked": 0, "unmaintained": 0,
        "deferred_offline": 0, "current": 0, "major_behind": 0,
        "minor_behind": 0, "unknown": 0,
    }
    for f in findings:
        # Gap kind counts (current / minor_behind / major_behind / ...)
        summary[f.gap.gap_kind] = summary.get(f.gap.gap_kind, 0) + 1
        # Severity counts (per CVE)
        for cve in f.cves:
            if cve.severity in summary:
                summary[cve.severity] += 1
    # Trim zero-count entries for cleanliness
    summary = {k: v for k, v in summary.items() if v > 0}

    return Report(
        project_root=project_root,
        schema_version=SCHEMA_VERSION,
        generated_at=datetime.now(timezone.utc),
        grounding_mode=grounding_mode,
        manifests_scanned=manifests_scanned,
        findings=tuple(findings),
        summary=summary,
        advisories=tuple(advisories or []),
    )


# ---------------------------------------------------------------------------
# Rendering layer (pure functions of Report)
# ---------------------------------------------------------------------------


def _cve_to_dict(c: CVE) -> dict:
    return {
        "id": c.id, "severity": c.severity, "cvss_score": c.cvss_score,
        "summary": c.summary, "affected_range": c.affected_range,
        "fixed_versions": list(c.fixed_versions),
        "published": c.published.isoformat() if c.published else None,
        "source": c.source, "osv_id": c.osv_id,
    }


def _finding_to_dict(f: Finding) -> dict:
    g = f.gap
    d = f.dep
    return {
        "package": d.name,
        "ecosystem": d.ecosystem,
        "declared_version": d.declared_version,
        "declared_resolves_to": g.declared_resolves_to,
        "latest_stable": g.latest_stable,
        "is_direct": not d.is_transitive,
        "is_dev": d.is_dev,
        "is_transitive": d.is_transitive,
        "transitive_depth": d.transitive_depth,
        "parent_chain": list(d.parent_chain),
        "gap_kind": g.gap_kind,
        "semver_distance": list(g.semver_distance) if g.semver_distance else None,
        "last_release_age_days": g.last_release_age_days,
        "cves": [_cve_to_dict(c) for c in f.cves],
        "blocks_build": f.blocks_build,
        "recommended_action": _recommend_action(g.gap_kind, f.cves),
        "api_delta": f.api_delta,
    }


def _recommend_action(gap_kind: str, cves: tuple) -> str:
    if any(c.severity == "critical" for c in cves):
        return "upgrade_to_latest_stable_with_fix"
    if gap_kind == "deferred_offline":
        return "retry_when_online"
    if gap_kind == "deprecated":
        return "evaluate_successor"
    if gap_kind == "yanked":
        return "upgrade_immediately"
    if gap_kind == "unmaintained":
        return "evaluate_alternatives"
    if gap_kind == "major_behind":
        return "evaluate_upgrade"
    if gap_kind == "minor_behind":
        return "upgrade_when_convenient"
    return "no_action"


def _report_to_dict(report: Report) -> dict:
    return {
        "schema_version": report.schema_version,
        "generated_at": report.generated_at.isoformat(),
        "project_root": str(report.project_root),
        "grounding_mode": report.grounding_mode,
        "manifests_scanned": [str(p) for p in report.manifests_scanned],
        "summary": report.summary,
        "findings": [_finding_to_dict(f) for f in report.findings],
        "advisories": list(report.advisories),
        "osv_records": [_cve_to_dict(c) for f in report.findings for c in f.cves],
    }


def render_json(report: Report) -> str:
    """Canonical machine format."""
    return json.dumps(_report_to_dict(report), indent=2, ensure_ascii=False,
                       sort_keys=False)


def render_markdown(report: Report) -> str:
    """Markdown rendering — default for chat / forge / alf."""
    lines = []
    lines.append(f"# dep-currency-check — {report.project_root}")
    lines.append("")
    lines.append(f"- **Schema**: `{report.schema_version}`")
    lines.append(f"- **Generated**: {report.generated_at.isoformat()}")
    lines.append(f"- **Grounding**: `{report.grounding_mode}`")
    lines.append(f"- **Manifests scanned**: {len(report.manifests_scanned)}")
    lines.append("")
    if report.summary:
        lines.append("## Summary")
        lines.append("")
        for k, v in sorted(report.summary.items()):
            lines.append(f"- {k}: {v}")
        lines.append("")
    if report.findings:
        lines.append("## Findings")
        lines.append("")
        lines.append("| Package | Ecosystem | Declared | Latest | Gap | CVEs | Blocks? |")
        lines.append("|---|---|---|---|---|---|---|")
        for f in report.findings:
            cves_str = ", ".join(c.id for c in f.cves) if f.cves else "—"
            lines.append(
                f"| `{f.dep.name}` | {f.dep.ecosystem} | "
                f"`{f.dep.declared_version}` | "
                f"`{f.gap.latest_stable or '?'}` | "
                f"{f.gap.gap_kind} | {cves_str} | "
                f"{'YES' if f.blocks_build else 'no'} |"
            )
        lines.append("")
        # API-delta detail blocks (only for findings that have it)
        deltas = [f for f in report.findings if f.api_delta]
        if deltas:
            lines.append("## API changes since declared version")
            lines.append("")
            for f in deltas:
                d = f.api_delta or {}
                versions = ", ".join(d.get("versions_in_range") or []) or "—"
                lines.append(f"### `{f.dep.name}` ({d.get('from_version')} → {d.get('to_version')})")
                lines.append(f"Source: {d.get('source', 'unknown')} · versions covered: {versions}")
                breaking = d.get("breaking_lines") or []
                if breaking:
                    lines.append("")
                    lines.append("**Breaking / deprecation hints (keyword-extracted):**")
                    for ln in breaking:
                        lines.append(f"- {ln}")
                excerpt = (d.get("release_notes_excerpt") or "").strip()
                if excerpt:
                    lines.append("")
                    lines.append("<details><summary>Release notes excerpt</summary>")
                    lines.append("")
                    lines.append("```")
                    lines.append(excerpt)
                    lines.append("```")
                    if d.get("truncated"):
                        lines.append("_(truncated — fetch the full release notes from the repo for the complete diff)_")
                    lines.append("</details>")
                lines.append("")
    if report.advisories:
        lines.append("## Advisories")
        lines.append("")
        for a in report.advisories:
            lines.append(f"- {a}")
        lines.append("")
    return "\n".join(lines)


def render_table(report: Report) -> str:
    """Plain ASCII table — TTY-friendly."""
    if not report.findings:
        return f"No findings ({report.project_root})\n"
    cols = ["package", "eco", "declared", "latest", "gap", "cves", "blocks"]
    rows = []
    for f in report.findings:
        cves_str = ",".join(c.id for c in f.cves) if f.cves else "-"
        rows.append([
            f.dep.name, f.dep.ecosystem, f.dep.declared_version,
            f.gap.latest_stable or "?", f.gap.gap_kind,
            cves_str, "YES" if f.blocks_build else "no",
        ])
    widths = [max(len(str(r[i])) for r in [cols] + rows) for i in range(len(cols))]
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out_lines = [sep]
    out_lines.append("| " + " | ".join(c.ljust(widths[i])
                                          for i, c in enumerate(cols)) + " |")
    out_lines.append(sep)
    for r in rows:
        out_lines.append("| " + " | ".join(str(r[i]).ljust(widths[i])
                                              for i in range(len(cols))) + " |")
    out_lines.append(sep)
    return "\n".join(out_lines) + "\n"


def render_yaml(report: Report) -> str:
    """YAML rendering — pure, dependency-free. (Stdlib has no yaml; emit
    a minimal block-style dump that round-trips through PyYAML if present)."""
    d = _report_to_dict(report)
    return _stdlib_yaml_dump(d) + "\n"


def render_osv_records(report: Report) -> str:
    """Emit ONLY the OSV records (no Report wrapper)."""
    records = [_cve_to_dict(c) for f in report.findings for c in f.cves]
    return json.dumps(records, indent=2, ensure_ascii=False)


def _stdlib_yaml_dump(obj, indent: int = 0) -> str:
    """Tiny stdlib-only YAML emitter for our flat dict structure.
    Supports: dicts of (str, primitive | list | dict), lists of primitives or dicts.
    Does NOT handle: cycles, complex types, custom tags."""
    out_lines: list = []
    sp = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                out_lines.append(f"{sp}{k}:")
                out_lines.append(_stdlib_yaml_dump(v, indent + 1))
            else:
                out_lines.append(f"{sp}{k}: {_yaml_scalar(v)}")
        return "\n".join(out_lines)
    if isinstance(obj, list):
        if not obj:
            return "[]"
        for item in obj:
            if isinstance(item, dict):
                rendered = _stdlib_yaml_dump(item, indent + 1).splitlines()
                if rendered:
                    out_lines.append(f"{sp}- {rendered[0].lstrip()}")
                    for line in rendered[1:]:
                        out_lines.append(f"{sp}  {line.lstrip(' ')}")
            else:
                out_lines.append(f"{sp}- {_yaml_scalar(item)}")
        return "\n".join(out_lines)
    return _yaml_scalar(obj)


def _yaml_scalar(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    # Quote when needed
    if any(ch in s for ch in ":#\n\"'") or s in ("null", "true", "false",
                                                    "~", "")\
            or s.startswith(("-", "?", "&", "*", "!", "|", ">", "@", "`")):
        # JSON-style quoting handles escapes
        return json.dumps(s, ensure_ascii=False)
    return s
