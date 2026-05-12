"""community_wrappers.py — PRIMARY data path (per Codex Rev 2 pivot).

4 wrappers around community scanners:
    osv-scanner (cross-ecosystem cover-all)
    pip-audit   (Python — native marker + extras + lockfile semantics)
    cargo-audit (Rust — RustSec)
    govulncheck (Go — CALL-AWARE)

NO npm_audit wrapper (FP rate per Gemini).

Each wrapper returns None on:
    (a) tool binary not on $PATH
    (b) tool exits non-zero
    (c) tool times out (60s default per-wrapper)
    (d) JSON output fails to parse / doesn't match expected schema

Reconciliation against our `Manifest` list happens in the orchestrator
(dep_currency_check.py) — wrappers just return wrapper-shape Findings.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .compare import Gap
from .manifests import Dependency, Ecosystem, Manifest
from .registry import CVE
from .report import Finding

DEFAULT_TIMEOUT_S = 60.0


# ---------------------------------------------------------------------------
# Availability probes
# ---------------------------------------------------------------------------


def osv_scanner_available() -> bool:
    return shutil.which("osv-scanner") is not None


def pip_audit_available() -> bool:
    return shutil.which("pip-audit") is not None


def cargo_audit_available() -> bool:
    return shutil.which("cargo-audit") is not None or _cargo_subcommand("audit")


def govulncheck_available() -> bool:
    return shutil.which("govulncheck") is not None


def _cargo_subcommand(name: str) -> bool:
    """Check if cargo subcommand <name> is installed (e.g. `cargo audit`)."""
    if shutil.which("cargo") is None:
        return False
    try:
        proc = subprocess.run(
            ["cargo", "--list"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    if proc.returncode != 0:
        return False
    for line in proc.stdout.splitlines():
        if line.strip().startswith(name):
            return True
    return False


# ---------------------------------------------------------------------------
# Subprocess invocation helper
# ---------------------------------------------------------------------------


def _run_capture(argv: list, *, cwd: Optional[Path] = None,
                 timeout: float = DEFAULT_TIMEOUT_S) -> Optional[str]:
    """Run a subprocess and return stdout text on success. Returns None on:
    - timeout
    - non-zero exit
    - tool not found
    - any OS error
    """
    try:
        proc = subprocess.run(
            argv,
            capture_output=True, text=True,
            cwd=str(cwd) if cwd else None,
            timeout=timeout, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        # Some scanners return non-zero when they find issues (osv-scanner, cargo-audit)
        # Only treat as failure if stdout is empty or unparseable JSON.
        if not proc.stdout.strip():
            return None
        # Parse on stdout regardless; if it's bad JSON, parse caller returns None.
    return proc.stdout


# ---------------------------------------------------------------------------
# Wrappers
# ---------------------------------------------------------------------------


def query_via_osv_scanner(
    project_root: Path,
    ecosystems: Optional[list] = None,
) -> Optional[dict]:
    """Shell out to `osv-scanner`. Returns dict[Ecosystem, list[Finding]]
    or None on any failure mode."""
    if not osv_scanner_available():
        return None
    raw = _run_capture(
        ["osv-scanner", "--format=json", "--output=-",
         str(project_root)],
        cwd=project_root,
    )
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    out: dict = {}
    for result in data.get("results") or []:
        for pkg in result.get("packages") or []:
            pkg_data = pkg.get("package") or {}
            osv_eco = pkg_data.get("ecosystem", "")
            our_eco = _osv_eco_to_ours(osv_eco)
            if our_eco is None:
                continue
            if ecosystems and our_eco not in ecosystems:
                continue
            vulns = pkg.get("vulnerabilities") or []
            cves = tuple(_osv_vuln_to_cve(v) for v in vulns)
            dep = Dependency(
                name=pkg_data.get("name", ""),
                declared_version=pkg_data.get("version", ""),
                constraint_type="exact",
                ecosystem=our_eco,
            )
            gap = Gap(
                dep=dep, declared_resolves_to=pkg_data.get("version", ""),
                latest_stable=None, gap_kind="unknown",
                semver_distance=None, last_release_age_days=None,
            )
            blocks = any(c.severity == "critical" and c.fixed_versions
                         for c in cves)
            f = Finding(dep=dep, gap=gap, cves=cves, blocks_build=blocks)
            out.setdefault(our_eco, []).append(f)
    return out


def query_python_via_pip_audit(project_root: Path) -> Optional[list]:
    if not pip_audit_available():
        return None
    raw = _run_capture(["pip-audit", "-f", "json"], cwd=project_root)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    out: list = []
    deps = data.get("dependencies") or data.get("vulnerabilities") or []
    for entry in deps:
        name = entry.get("name", "")
        version = entry.get("version", "")
        vulns = entry.get("vulns") or entry.get("vulnerabilities") or []
        if not vulns:
            continue
        cves: list = []
        for v in vulns:
            cves.append(CVE(
                id=v.get("id", ""), severity="unknown",
                cvss_score=None, summary=v.get("description", "")[:200],
                affected_range="", fixed_versions=tuple(v.get("fix_versions") or []),
                published=None, source="osv",
                osv_id=v.get("id") if v.get("id", "").startswith("GHSA-") else None,
            ))
        dep = Dependency(
            name=name, declared_version=version,
            constraint_type="exact", ecosystem="python",
        )
        gap = Gap(
            dep=dep, declared_resolves_to=version,
            latest_stable=None, gap_kind="unknown",
            semver_distance=None, last_release_age_days=None,
        )
        out.append(Finding(dep=dep, gap=gap, cves=tuple(cves),
                            blocks_build=any(c.fixed_versions for c in cves)))
    return out


def query_rust_via_cargo_audit(project_root: Path) -> Optional[list]:
    if not cargo_audit_available():
        return None
    raw = _run_capture(["cargo", "audit", "--json"], cwd=project_root)
    if not raw:
        # Some installations expose `cargo-audit` as a separate binary
        raw = _run_capture(["cargo-audit", "audit", "--json"], cwd=project_root)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    out: list = []
    vulns_block = (data.get("vulnerabilities") or {}).get("list") or []
    for v in vulns_block:
        adv = v.get("advisory") or {}
        pkg = v.get("package") or {}
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        cve_id = adv.get("id", "") or (adv.get("aliases") or [""])[0]
        # cargo-audit doesn't always give CVSS; mark severity unknown
        sev = adv.get("severity", "unknown") or "unknown"
        if sev.lower() not in ("critical", "high", "moderate", "low", "unknown"):
            sev = "unknown"
        cve = CVE(
            id=cve_id, severity=sev,
            cvss_score=None, summary=adv.get("title", ""),
            affected_range="", fixed_versions=tuple(v.get("versions", {})
                                                    .get("patched") or []),
            published=None, source="osv", osv_id=cve_id,
        )
        dep = Dependency(name=name, declared_version=version,
                          constraint_type="exact", ecosystem="rust")
        gap = Gap(dep=dep, declared_resolves_to=version,
                   latest_stable=None, gap_kind="unknown",
                   semver_distance=None, last_release_age_days=None)
        out.append(Finding(dep=dep, gap=gap, cves=(cve,),
                            blocks_build=sev == "critical"
                            and bool(cve.fixed_versions)))
    return out


def query_go_via_govulncheck(project_root: Path) -> Optional[list]:
    """CALL-AWARE Go vulnerability check. Substantially lower FP rate."""
    if not govulncheck_available():
        return None
    raw = _run_capture(
        ["govulncheck", "-json", "./..."],
        cwd=project_root,
    )
    if not raw:
        return None
    # govulncheck output is line-delimited JSON
    findings: dict = {}  # name -> Finding accumulator
    for line in raw.splitlines():
        s = line.strip()
        if not s or not s.startswith("{"):
            continue
        try:
            rec = json.loads(s)
        except json.JSONDecodeError:
            continue
        # 'osv' records describe vulnerabilities
        if "osv" in rec:
            osv = rec["osv"]
            osv_id = osv.get("id", "")
            for affected in osv.get("affected", []) or []:
                pkg_data = affected.get("package") or {}
                name = pkg_data.get("name", "")
                if not name:
                    continue
                fixed: list = []
                for r in affected.get("ranges") or []:
                    for ev in r.get("events") or []:
                        if "fixed" in ev:
                            fixed.append(ev["fixed"])
                sev = "high"  # govulncheck only emits when reachable
                cve = CVE(
                    id=osv_id, severity=sev, cvss_score=None,
                    summary=osv.get("summary", "")[:200],
                    affected_range="", fixed_versions=tuple(fixed),
                    published=None, source="osv", osv_id=osv_id,
                )
                if name in findings:
                    old = findings[name]
                    findings[name] = Finding(
                        dep=old.dep, gap=old.gap,
                        cves=old.cves + (cve,),
                        blocks_build=old.blocks_build,
                    )
                else:
                    dep = Dependency(
                        name=name, declared_version="",
                        constraint_type="exact", ecosystem="go",
                    )
                    gap = Gap(dep=dep, declared_resolves_to=None,
                               latest_stable=None, gap_kind="unknown",
                               semver_distance=None,
                               last_release_age_days=None)
                    findings[name] = Finding(
                        dep=dep, gap=gap, cves=(cve,),
                        blocks_build=bool(fixed),
                    )
    return list(findings.values())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _osv_eco_to_ours(osv_eco: str) -> Optional[str]:
    m = {"PyPI": "python", "npm": "js", "crates.io": "rust",
         "Go": "go", "RubyGems": "ruby", "Maven": "java"}
    return m.get(osv_eco)


def _osv_vuln_to_cve(vuln: dict) -> CVE:
    """Map an OSV vuln record (as emitted by osv-scanner JSON) to our CVE shape."""
    cve_id = vuln.get("id", "")
    aliases = vuln.get("aliases") or []
    for a in aliases:
        if a.startswith("CVE-"):
            cve_id = a
            break
    severity = "unknown"
    cvss_score = None
    for s in vuln.get("severity") or []:
        if s.get("type", "").upper().startswith("CVSS"):
            score_raw = s.get("score", "")
            # Extract numeric portion from CVSS vector if present
            try:
                if "CVSS" in score_raw and "/" in score_raw:
                    # bare score might be missing; default unknown
                    score = None
                else:
                    score = float(score_raw)
            except (ValueError, TypeError):
                score = None
            if score is not None:
                cvss_score = score
                if score >= 9.0:
                    severity = "critical"
                elif score >= 7.0:
                    severity = "high"
                elif score >= 4.0:
                    severity = "moderate"
                else:
                    severity = "low"
    db_spec = vuln.get("database_specific") or {}
    raw_sev = (db_spec.get("severity") or "").lower()
    if raw_sev in ("critical", "high", "moderate", "low"):
        severity = raw_sev
    elif raw_sev == "medium":
        severity = "moderate"

    fixed: list = []
    affected_str_parts: list = []
    for aff in vuln.get("affected") or []:
        for r in aff.get("ranges") or []:
            for ev in r.get("events") or []:
                if "fixed" in ev:
                    fixed.append(ev["fixed"])
                    affected_str_parts.append(f"<{ev['fixed']}")
                if "introduced" in ev:
                    affected_str_parts.append(f">={ev['introduced']}")
    return CVE(
        id=cve_id, severity=severity, cvss_score=cvss_score,
        summary=vuln.get("summary", "")[:200],
        affected_range=",".join(affected_str_parts) or "*",
        fixed_versions=tuple(fixed),
        published=None, source="osv", osv_id=vuln.get("id"),
    )
