"""dep_currency_check.py — CLI entry point + orchestration.

Stdlib only. Wraps manifests + community_wrappers (primary) + registry (fallback)
+ compare + report. Returns one of the documented exit codes.

Public entry: main() — called from __main__.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import __schema_version__, __version__
from .cache import Cache
from .community_wrappers import (
    cargo_audit_available, govulncheck_available, osv_scanner_available,
    pip_audit_available, query_go_via_govulncheck,
    query_python_via_pip_audit, query_rust_via_cargo_audit,
    query_via_osv_scanner,
)
from .compare import compare, Gap
from . import manifests as _manifests_mod
from .manifests import Dependency, Manifest, detect_manifests
from .registry import Registry, VersionInfo
from .report import (
    Finding, Report, assemble_report, compute_blocks_build,
    render_json, render_markdown, render_osv_records, render_table,
    render_yaml,
)

SOURCES_JSON = Path.home() / ".claude" / "state" / "sources.json"
SEVERITY_RANK = {"critical": 5, "high": 4, "moderate": 3, "low": 2,
                 "unknown": 1, "none": 0}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dep-currency-check",
        description="Surface stale library versions and known CVEs in project dependencies.",
    )
    p.add_argument("project_root", help="Project root containing manifests")
    # Output options
    p.add_argument("--format", choices=["json"], default="json",
                    help="Output format (default: json). YAML is a --render value, NOT a format.")
    p.add_argument("--render",
                    choices=["markdown", "table", "yaml", "osv"],
                    default=None,
                    help="Rendering view over the canonical JSON")
    p.add_argument("--include-osv-records", action="store_true",
                    help="Embed OSV-format records inline (default: on if any CVEs)")
    p.add_argument("--output", default=None, help="Write report to file")
    p.add_argument("--json-output", default=None,
                    help="ALSO write JSON sidecar (regardless of --render)")
    # Severity + mode
    p.add_argument("--severity", choices=["critical", "high", "all"],
                    default="high", help="Minimum severity to report")
    p.add_argument("--mode", choices=["advisory", "strict"], default="advisory",
                    help="Blocking criteria for exit code 1 (default: advisory)")
    # Filter
    p.add_argument("--ecosystems", default="auto",
                    help="Comma-separated; default: auto-detect all")
    p.add_argument("--changed-manifests", default=None,
                    help="Comma-separated paths; delta mode for pre-commit")
    # Cache + network
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--strict-airgap", action="store_true")
    p.add_argument("--max-network-s", type=int, default=60)
    p.add_argument("--allow-deferred", action="store_true",
                    help="Exit 0 even with offline-cold-cache findings")
    # LLM
    p.add_argument("--no-llm", action="store_true",
                    help="Disable LLM fallback entirely")
    p.add_argument("--llm-cve-judge", action="store_true",
                    help="Opt-in: LLM judges CVE applicability (informational only)")
    # Integration
    p.add_argument("--emit-scope-delta", action="store_true",
                    help="Emit scope_delta entries (only fires under --mode strict)")
    p.add_argument("--schema-version", default=__schema_version__)
    # Verbose
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--version", action="version",
                    version=f"dep-currency-check {__version__}")
    return p


def _read_sources_json() -> dict:
    """Read ~/.claude/state/sources.json fresh on every invocation."""
    try:
        return json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _filter_manifests(manifests: list, changed: Optional[str],
                       project_root: Path) -> list:
    """If --changed-manifests provided, only return manifests matching those paths."""
    if not changed:
        return manifests
    changed_paths = [p.strip() for p in changed.split(",") if p.strip()]
    if not changed_paths:
        return manifests
    # Match by basename OR full path
    result: list = []
    changed_basenames = {Path(p).name for p in changed_paths}
    changed_resolved = {str((project_root / p).resolve())
                         for p in changed_paths
                         if not Path(p).is_absolute()}
    changed_resolved |= {str(Path(p).resolve())
                          for p in changed_paths
                          if Path(p).is_absolute()}
    for m in manifests:
        if m.path.name in changed_basenames \
                or str(m.path.resolve()) in changed_resolved:
            result.append(m)
        elif m.lockfile_path and (
                m.lockfile_path.name in changed_basenames
                or str(m.lockfile_path.resolve()) in changed_resolved):
            result.append(m)
    return result


def _filter_severity(report: Report, min_severity: str) -> Report:
    """Drop findings below min_severity (keeps deprecated/yanked always)."""
    if min_severity == "all":
        return report
    min_rank = SEVERITY_RANK.get(min_severity, 4)
    out: list = []
    for f in report.findings:
        # Always keep yanked / deprecated / blocks_build
        if f.blocks_build or f.gap.gap_kind in (
                "yanked", "deprecated", "unmaintained"):
            out.append(f)
            continue
        # Keep if any CVE meets threshold
        max_cve_rank = max((SEVERITY_RANK.get(c.severity, 0) for c in f.cves),
                            default=0)
        if max_cve_rank >= min_rank:
            out.append(f)
    return Report(
        project_root=report.project_root,
        schema_version=report.schema_version,
        generated_at=report.generated_at,
        grounding_mode=report.grounding_mode,
        manifests_scanned=report.manifests_scanned,
        findings=tuple(out),
        summary=report.summary,
        advisories=report.advisories,
        meta=report.meta,
    )


def _orchestrate_one_ecosystem(
    ecosystem: str,
    manifests_for_eco: list,
    project_root: Path,
    *,
    registry: Registry,
    no_cache: bool,
    offline: bool,
    advisories: list,
    wrappers_available: dict,
) -> list:
    """For one ecosystem, try wrapper first; fall back to HTTP. Returns list[Finding]."""
    # Collect all deps for this ecosystem from the relevant manifests
    all_deps: list = []
    for m in manifests_for_eco:
        all_deps.extend(m.deps)

    # 1. Try osv-scanner first if available (covers all ecosystems uniformly)
    if wrappers_available.get("osv-scanner"):
        result = query_via_osv_scanner(project_root, ecosystems=[ecosystem])
        if result is not None and ecosystem in result:
            # Reconcile against our manifests for is_direct, is_dev metadata
            reconciled = _reconcile_findings(result[ecosystem], all_deps)
            # Also produce findings for deps the wrapper did NOT report (means clean)
            wrapper_pkgs = {(f.dep.name, f.dep.ecosystem) for f in reconciled}
            for d in all_deps:
                if (d.name, d.ecosystem) in wrapper_pkgs:
                    continue
                # Add a clean Finding (no CVEs)
                gap = Gap(dep=d, declared_resolves_to=d.declared_version,
                           latest_stable=None, gap_kind="unknown",
                           semver_distance=None, last_release_age_days=None)
                reconciled.append(Finding(dep=d, gap=gap, cves=tuple(),
                                            blocks_build=False))
            # S038 Batch C — enrich gap_kind=unknown findings with PyPI/npm/etc
            # latest-version data. Wrappers (pip-audit, cargo-audit, govulncheck,
            # osv-scanner) emit CVE info but NOT current-stable; this fills it
            # in via the registry. Closes #87 + #104 (the latest=unknown bug).
            return _enrich_findings_with_versions(
                reconciled, registry,
                no_cache=no_cache, offline=offline,
            )
        advisories.append(
            f"osv-scanner unavailable or failed for {ecosystem}; falling back")

    # 2. Try per-ecosystem wrapper
    if ecosystem == "python" and wrappers_available.get("pip-audit"):
        result = query_python_via_pip_audit(project_root)
        if result is not None:
            reconciled = _reconcile_findings(result, all_deps)
            wrapper_pkgs = {f.dep.name for f in reconciled}
            for d in all_deps:
                if d.name in wrapper_pkgs:
                    continue
                gap = Gap(dep=d, declared_resolves_to=d.declared_version,
                           latest_stable=None, gap_kind="unknown",
                           semver_distance=None, last_release_age_days=None)
                reconciled.append(Finding(dep=d, gap=gap, cves=tuple(),
                                            blocks_build=False))
            return _enrich_findings_with_versions(
                reconciled, registry,
                no_cache=no_cache, offline=offline,
            )
        advisories.append("pip-audit unavailable or failed for python; falling back")
    elif ecosystem == "rust" and wrappers_available.get("cargo-audit"):
        result = query_rust_via_cargo_audit(project_root)
        if result is not None:
            reconciled = _reconcile_findings(result, all_deps)
            wrapper_pkgs = {f.dep.name for f in reconciled}
            for d in all_deps:
                if d.name in wrapper_pkgs:
                    continue
                gap = Gap(dep=d, declared_resolves_to=d.declared_version,
                           latest_stable=None, gap_kind="unknown",
                           semver_distance=None, last_release_age_days=None)
                reconciled.append(Finding(dep=d, gap=gap, cves=tuple(),
                                            blocks_build=False))
            return _enrich_findings_with_versions(
                reconciled, registry,
                no_cache=no_cache, offline=offline,
            )
        advisories.append("cargo-audit unavailable or failed for rust; falling back")
    elif ecosystem == "go" and wrappers_available.get("govulncheck"):
        result = query_go_via_govulncheck(project_root)
        if result is not None:
            reconciled = _reconcile_findings(result, all_deps)
            wrapper_pkgs = {f.dep.name for f in reconciled}
            for d in all_deps:
                if d.name in wrapper_pkgs:
                    continue
                gap = Gap(dep=d, declared_resolves_to=d.declared_version,
                           latest_stable=None, gap_kind="unknown",
                           semver_distance=None, last_release_age_days=None)
                reconciled.append(Finding(dep=d, gap=gap, cves=tuple(),
                                            blocks_build=False))
            return _enrich_findings_with_versions(
                reconciled, registry,
                no_cache=no_cache, offline=offline,
            )
        advisories.append("govulncheck unavailable or failed for go; falling back")

    # 3. HTTP fallback
    findings: list = []
    cve_map = registry.query_cves_batch(all_deps, no_cache=no_cache, offline=offline)
    for d in all_deps:
        vi = registry.query_version_latest(d.ecosystem, d.name,
                                             no_cache=no_cache, offline=offline)
        gap = compare(d, vi)
        cves = cve_map.get((d.name, d.ecosystem), tuple())
        blocks = compute_blocks_build({"dep": d, "cves": cves})
        findings.append(Finding(dep=d, gap=gap, cves=cves, blocks_build=blocks))
    return findings


def _enrich_findings_with_versions(
    findings: list,
    registry,
    *,
    no_cache: bool = False,
    offline: bool = False,
) -> list:
    """Backfill latest_stable + gap_kind for wrapper-emitted findings.

    Per-ecosystem wrappers (pip-audit, cargo-audit, govulncheck, osv-scanner)
    return CVE info but NOT the current latest-stable version, so they emit
    gap_kind="unknown" / latest_stable=None for every finding. This helper
    runs a SECOND pass that queries the registry for each finding's latest
    version and re-computes the gap via `compare()`.

    S038 Batch C (2026-05-24) — closes tasks #87 + #104 which surfaced as
    `latest column shows unknown for many deps even with pip-audit on PATH`.
    Root cause per Gemini freshness probe 2026-05-22 is upstream pip-audit
    not exposing latest-stable in its default JSON. Our wrapper path was
    propagating that absence; the HTTP-fallback path (lines 246+) already
    does both lookups. This helper closes the gap.

    Idempotent: findings already with known gap_kind are returned unchanged.
    Best-effort: if a registry lookup fails (offline / 404 / etc.), the
    finding is returned as-is. Never raises.
    """
    out: list = []
    for f in findings:
        if f.gap.gap_kind != "unknown" or f.gap.latest_stable is not None:
            out.append(f)
            continue
        try:
            vi = registry.query_version_latest(
                f.dep.ecosystem, f.dep.name,
                no_cache=no_cache, offline=offline,
            )
        except Exception:
            out.append(f)
            continue
        if vi is None:
            out.append(f)
            continue
        new_gap = compare(f.dep, vi)
        out.append(Finding(
            dep=f.dep, gap=new_gap, cves=f.cves,
            blocks_build=f.blocks_build,
        ))
    return out


def _reconcile_findings(wrapper_findings: list,
                         our_deps: list) -> list:
    """Reconcile wrapper-emitted Findings against our Manifest-derived deps.
    Fills in is_direct/is_dev/transitive_depth from our authoritative parse."""
    # Build lookup by (name) — wrapper may not preserve our manifest metadata
    our_by_name = {d.name: d for d in our_deps}
    out: list = []
    for f in wrapper_findings:
        our_dep = our_by_name.get(f.dep.name)
        if our_dep is not None:
            # Merge: keep wrapper's version, keep our metadata
            merged_dep = Dependency(
                name=our_dep.name,
                declared_version=f.dep.declared_version or our_dep.declared_version,
                constraint_type=our_dep.constraint_type,
                ecosystem=our_dep.ecosystem,
                is_dev=our_dep.is_dev,
                workspace_root=our_dep.workspace_root,
                is_transitive=our_dep.is_transitive,
                transitive_depth=our_dep.transitive_depth,
                parent_chain=our_dep.parent_chain,
            )
            # Recompute blocks_build with the correct is_direct/is_dev
            blocks = compute_blocks_build({"dep": merged_dep, "cves": f.cves})
            gap = Gap(
                dep=merged_dep,
                declared_resolves_to=f.gap.declared_resolves_to,
                latest_stable=f.gap.latest_stable,
                gap_kind=f.gap.gap_kind,
                semver_distance=f.gap.semver_distance,
                last_release_age_days=f.gap.last_release_age_days,
            )
            out.append(Finding(dep=merged_dep, gap=gap, cves=f.cves,
                                blocks_build=blocks))
        else:
            # Wrapper reports a package we didn't know about
            # (transitive dep not in our lockfile parse, or resolver mismatch)
            out.append(f)
    return out


# ---------------------------------------------------------------------------
# scope_delta emission
# ---------------------------------------------------------------------------


def _emit_scope_deltas(report: Report, project_root: Path,
                        requesting_wp: str, advisories: list) -> int:
    """Emit scope_delta entries for STRICT blocking criteria findings.
    Returns count emitted. Dedup BEFORE write (S029 lesson)."""
    try:
        # Lazy import: scope_delta lives in foundry-lab's _meta dir
        sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "_meta"))
        import scope_delta as _sd
    except ImportError:
        advisories.append(
            "scope_delta module unavailable; skipping --emit-scope-delta")
        return 0

    # Read existing undecided records for dedup
    existing_keys = set()
    try:
        for rec in _sd.read_records(project_root, status_filter="undecided"):
            if rec.get("created_by") != "dep-currency-check":
                continue
            path = rec.get("path", "")
            manifest_path, _, package = path.partition("#")
            em = rec.get("extractor_meta") or {}
            for cve_id in em.get("cve_ids") or []:
                existing_keys.add((manifest_path, package, cve_id))
    except Exception:
        # If the ledger is malformed or missing, proceed with empty dedup set
        pass

    # Need contract_map_hash + revision for the record
    map_path = project_root / "progress" / "contract-map.yaml"
    contract_map_hash = "sha256:" + ("0" * 64)
    contract_map_revision = 0
    if map_path.is_file():
        try:
            contract_map_hash = "sha256:" + hashlib.sha256(
                map_path.read_bytes()).hexdigest()
        except OSError:
            pass

    emitted = 0
    for f in report.findings:
        if not f.blocks_build:
            continue
        manifest_path = ""
        for m_path in report.manifests_scanned:
            # Find manifest whose path indicates this finding (best-effort)
            manifest_path = str(m_path)
            break
        for cve in f.cves:
            if cve.severity != "critical" or not cve.fixed_versions:
                continue
            dedup_key = (manifest_path, f.dep.name, cve.id)
            if dedup_key in existing_keys:
                continue
            try:
                delta_id = _sd.new_delta_id()
                # content_hash: sha256(manifest_path + package + cve_id)
                ch = hashlib.sha256(
                    f"{manifest_path}|{f.dep.name}|{cve.id}".encode()
                ).hexdigest()
                latest = f.gap.latest_stable or ",".join(cve.fixed_versions[:1])
                record = {
                    "delta_id": delta_id,
                    "schema_version": "scope_delta.v1",
                    "created_at": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"),
                    "created_by": "dep-currency-check",
                    "project_root": str(project_root),
                    "contract_map_hash": contract_map_hash,
                    "contract_map_revision": contract_map_revision,
                    "artifact_kind": "file",
                    "operation": "changed",
                    "path": f"{manifest_path}#{f.dep.name}",
                    "content_hash": ch,
                    "severity": "critical",
                    "requesting_wp": requesting_wp,
                    "detection_point": "wp_boundary",
                    "status": "undecided",
                    "critical_reason": (
                        f"{cve.id} in {f.dep.name} {cve.affected_range} "
                        f"(declared: {f.dep.declared_version}). "
                        f"Pause and amend contract-map to require "
                        f"{f.dep.name}>={latest}, or excuse with rationale."
                    ),
                    "extractor_meta": {
                        "source": "dep-currency-check",
                        "schema": __schema_version__,
                        "cve_ids": [cve.id],
                        "cvss": cve.cvss_score,
                        "latest_stable": latest,
                    },
                }
                _sd.write_record(project_root, record)
                existing_keys.add(dedup_key)
                emitted += 1
            except Exception as e:
                advisories.append(
                    f"scope_delta write failed for {f.dep.name}/{cve.id}: {e}")
    return emitted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[list] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        sys.stderr.write(f"ENV_ERROR: project_root not a directory: {project_root}\n")
        return 3

    # Read sources.json fresh
    sources = _read_sources_json()
    grounding_mode = sources.get("grounding_mode", "full")
    if args.offline:
        grounding_mode = "internal-only"

    # Build cache and registry
    cache = Cache(
        no_cache=args.no_cache,
        ignore_ttl=(grounding_mode == "internal-only" or args.offline),
    )
    registry = Registry(cache=cache, strict_airgap=args.strict_airgap)

    advisories: list = []

    # Detect manifests
    manifests = detect_manifests(project_root)
    # Capture degraded-scan advisory (S035 fail-open fix). Read IMMEDIATELY
    # after the walk — module-level flags are reset on every _walk call.
    scan_meta: dict = {}
    if getattr(_manifests_mod, "_LAST_SCAN_DEGRADED", False):
        scan_meta["degraded"] = True
        reason = getattr(_manifests_mod, "_LAST_SCAN_REASON", None)
        if reason:
            scan_meta["degraded_reason"] = reason
        advisories.append(
            f"manifest discovery DEGRADED: {scan_meta.get('degraded_reason', 'unknown reason')} "
            f"— results may be incomplete"
        )
    manifests = _filter_manifests(manifests, args.changed_manifests, project_root)

    # Ecosystem filter
    if args.ecosystems and args.ecosystems != "auto":
        wanted = {e.strip() for e in args.ecosystems.split(",") if e.strip()}
        manifests = [m for m in manifests if m.ecosystem in wanted]

    if not manifests:
        # No manifests = clean output, exit 0
        report = assemble_report(
            project_root, [], [],
            grounding_mode=grounding_mode,
            advisories=advisories or ["no recognized manifests found"],
            meta=scan_meta,
        )
        _write_output(report, args)
        return 0

    # Probe wrappers once per run. Wrappers require network (most query OSV
    # internally), so in offline/strict-airgap mode treat them as unavailable.
    if args.offline or args.strict_airgap or grounding_mode == "internal-only":
        wrappers_available = {
            "osv-scanner": False, "pip-audit": False,
            "cargo-audit": False, "govulncheck": False,
        }
        if args.verbose:
            sys.stderr.write(
                "offline/airgap mode: skipping all community wrappers\n"
            )
    else:
        wrappers_available = {
            "osv-scanner": osv_scanner_available(),
            "pip-audit": pip_audit_available(),
            "cargo-audit": cargo_audit_available(),
            "govulncheck": govulncheck_available(),
        }
        if args.verbose:
            for name, avail in wrappers_available.items():
                sys.stderr.write(
                    f"wrapper {name}: "
                    f"{'available' if avail else 'missing'}\n"
                )

    # Group manifests by ecosystem
    by_eco: dict = {}
    for m in manifests:
        by_eco.setdefault(m.ecosystem, []).append(m)

    # Run orchestration per ecosystem
    all_findings: list = []
    for eco, mlist in by_eco.items():
        if args.verbose:
            sys.stderr.write(f"orchestrating {eco}: {len(mlist)} manifests\n")
        findings = _orchestrate_one_ecosystem(
            eco, mlist, project_root,
            registry=registry,
            no_cache=args.no_cache,
            offline=args.offline,
            advisories=advisories,
            wrappers_available=wrappers_available,
        )
        all_findings.extend(findings)

    # Detect offline-cold-cache promotion
    if grounding_mode == "internal-only":
        deferred = [f for f in all_findings if f.gap.gap_kind == "deferred_offline"]
        if deferred and len(deferred) == len(all_findings):
            grounding_mode = "offline-cold-cache"
            advisories.append(
                "grounding_mode: offline-cold-cache — all version queries deferred"
            )

    # Enrich findings with api_delta for major-version-stale / deprecated
    # entries (advisory v1.1; no-op in offline/airgapped mode).
    if not args.offline and grounding_mode != "offline-cold-cache":
        try:
            from .changelog import discover_repo_url, fetch_api_delta
            enriched = []
            for f in all_findings:
                if (
                    f.gap.gap_kind in ("major_behind", "deprecated")
                    and not f.dep.is_transitive
                    and f.gap.latest_stable
                    and f.gap.declared_resolves_to
                ):
                    repo_url = discover_repo_url(f.dep.name, f.dep.ecosystem)
                    delta = fetch_api_delta(
                        package=f.dep.name,
                        ecosystem=f.dep.ecosystem,
                        repo_url=repo_url,
                        from_version=f.gap.declared_resolves_to,
                        to_version=f.gap.latest_stable,
                        cache=cache,
                    )
                    if delta is not None:
                        enriched.append(Finding(
                            dep=f.dep, gap=f.gap, cves=f.cves,
                            blocks_build=f.blocks_build, api_delta=delta,
                        ))
                        continue
                enriched.append(f)
            all_findings = enriched
        except Exception as e:  # noqa: BLE001 — advisory; never fail the run
            advisories.append(f"changelog enrichment skipped: {type(e).__name__}: {e}")

    # Assemble report
    report = assemble_report(
        project_root, manifests, all_findings,
        grounding_mode=grounding_mode,
        advisories=advisories,
        meta=scan_meta,
    )

    # Filter to requested severity
    report = _filter_severity(report, args.severity)

    # Emit scope_delta entries if requested AND strict mode
    if args.emit_scope_delta and args.mode == "strict":
        requesting_wp = os.environ.get("REQUESTING_WP", "unknown")
        _emit_scope_deltas(report, project_root, requesting_wp, advisories)
        # Re-assemble with updated advisories (preserve meta).
        report = Report(
            project_root=report.project_root,
            schema_version=report.schema_version,
            generated_at=report.generated_at,
            grounding_mode=report.grounding_mode,
            manifests_scanned=report.manifests_scanned,
            findings=report.findings,
            summary=report.summary,
            advisories=tuple(advisories),
            meta=report.meta,
        )

    # Write output
    _write_output(report, args)

    # Compute exit code
    return _compute_exit_code(report, args)


def _write_output(report: Report, args) -> None:
    """Write according to --format / --render / --output / --json-output."""
    # Always canonical JSON in memory
    json_text = render_json(report)

    # Build primary output
    if args.render == "markdown":
        out_text = render_markdown(report)
    elif args.render == "table":
        out_text = render_table(report)
    elif args.render == "yaml":
        out_text = render_yaml(report)
    elif args.render == "osv":
        out_text = render_osv_records(report)
    else:
        out_text = json_text

    if args.output:
        try:
            Path(args.output).write_text(out_text, encoding="utf-8")
        except OSError as e:
            sys.stderr.write(f"failed to write --output: {e}\n")
    else:
        if not args.quiet:
            sys.stdout.write(out_text)
            if not out_text.endswith("\n"):
                sys.stdout.write("\n")

    if args.json_output:
        try:
            Path(args.json_output).write_text(json_text, encoding="utf-8")
        except OSError as e:
            sys.stderr.write(f"failed to write --json-output: {e}\n")


def _compute_exit_code(report: Report, args) -> int:
    # 4: offline + cold cache for required packages
    if report.grounding_mode == "offline-cold-cache":
        if args.allow_deferred:
            return 0
        return 4

    # Check for strict-blocking findings
    has_strict_block = any(f.blocks_build for f in report.findings)

    # Check for soft findings (any non-current finding)
    has_soft = any(f.gap.gap_kind not in ("current", "unknown")
                    or f.cves
                    for f in report.findings)

    if has_strict_block and args.mode == "strict":
        return 1
    if has_soft:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
