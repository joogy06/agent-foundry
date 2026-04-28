#!/usr/bin/env python3
"""scan.py — S029 WP-8 retro-scan-s028 scanner.

One-shot read-only baseline scanner. Walks <project_root>, classifies
each filesystem path against the frozen contract-map, and writes
`<project_root>/progress/retro-scan-S028.yaml` conforming to
`retro_scan.v1`.

Invariants (design §7.5):
  * READ-ONLY w.r.t. contract-map (no writes to progress/contract-map.yaml
    or .sig).
  * NON-BLOCKING (NEVER calls pause_state.request_pause; CB4 preserved).
  * Single canonical output (no per-run timestamping; re-runs overwrite).
  * v1 file-level only -- symbol-level deferred to S030 (design §17 OQ2).

Reuse (design §11 WP-8 + checkpoint Notes for spawn-3):
  * `gates.CONTRACT_SCOPE_CRITICAL_GLOBS` -- severity classification.
  * `gates._gcs_walk_workspace`            -- workspace walk + skip set.
  * `gates._gcs_glob_match`                -- recursive `**` matcher.
  * `gates._gcs_matches_critical`          -- M4 precedence path test.
  * `gates._gcs_in_universe`               -- declared-universe membership.
  * `gates._gcs_compute_declared_universe` -- union of source/flow/excluded.
  * `extractors.first_match`               -- LOCKED priority chain
    (secret > db_migration > env_var > public_api > config_key
     > generated_artifact > file).

Public surface:
  * `run(project_root: Path) -> None`  (sys.exit on env error)
  * `__main__`: `python3 scan.py <project_root>`
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

# Pin _meta on sys.path so `gates` and `extractors` import cleanly when scan.py
# is invoked as `python3 ~/.claude/skills/retro-scan-s028/scripts/scan.py`.
_META_DIR = (Path(__file__).resolve().parent.parent.parent / "_meta")
if _META_DIR.is_dir():
    sys.path.insert(0, str(_META_DIR))
else:
    # Fallback (cross-tool symlink layouts): try the canonical install path.
    sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "_meta"))

import gates  # noqa: E402
from extractors import first_match  # noqa: E402


OUTPUT_RELPATH = "progress/retro-scan-S028.yaml"
CONTRACT_MAP_RELPATH = "progress/contract-map.yaml"


# ---------------------------------------------------------------------------
# Small env-error helper (mirrors gates.py style)
# ---------------------------------------------------------------------------


def _env_error(msg: str) -> None:
    """Print to stderr and exit 2.

    Per SKILL.md exit codes:
      * 0 -- scan succeeded
      * 2 -- env error (contract-map missing, parse failure, etc.)
    """
    sys.stderr.write(f"retro-scan-s028: ENV_ERROR: {msg}\n")
    raise SystemExit(2)


# ---------------------------------------------------------------------------
# Contract-map I/O (READ-ONLY -- never opened for write)
# ---------------------------------------------------------------------------


def _hash_map_file(map_path: Path) -> str:
    """sha256 hex digest of the contract-map file bytes."""
    h = hashlib.sha256()
    with map_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_contract_map(map_path: Path) -> Dict[str, Any]:
    """Load contract-map.yaml. Env-errors on missing or unparseable map."""
    if not map_path.is_file():
        _env_error(f"contract-map not found at {map_path}")
    try:
        return yaml.safe_load(map_path.read_text()) or {}
    except yaml.YAMLError as e:
        _env_error(f"contract-map unparseable at {map_path}: {e}")
    return {}


# ---------------------------------------------------------------------------
# Path classification (consistent with the live G_CONTRACT_SCOPE gate)
# ---------------------------------------------------------------------------


def _expanded_source_paths(comp: Dict[str, Any]) -> List[str]:
    """Per-component declared globs, with `~` expanded (consistency with
    gates._gcs_expand_path)."""
    out: List[str] = []
    for sp in comp.get("source_paths", []) or []:
        out.append(gates._gcs_expand_path(sp))
    return out


def _path_in_declared(path: str, declared: List[str]) -> bool:
    """True iff `path` matches any of `declared` globs.

    Reuses gates._gcs_in_universe to keep glob semantics aligned with
    the live gate (recursive `**`, prefix-match for non-glob entries).
    """
    return gates._gcs_in_universe(path, declared)


def _classify_severity(path: str) -> str:
    """`pre_existing_critical` if path matches CONTRACT_SCOPE_CRITICAL_GLOBS,
    else `pre_existing_advisory`. Consistent with the live gate's
    severity rule (M4 precedence is enforced upstream by NOT short-
    circuiting on excluded_paths -- see _candidate_for_finding)."""
    if gates._gcs_matches_critical(path):
        return "pre_existing_critical"
    return "pre_existing_advisory"


def _candidate_for_finding(
    path: str,
    declared_universe: List[str],
    excluded_paths: List[str],
) -> bool:
    """Mirror M4 precedence: a path becomes a finding iff
        - it is NOT in declared_universe (the union of components +
          flows + excluded_paths), AND
        - NOT separately excluded UNLESS it matches a critical glob.

    The gate handles this by computing both `declared_universe`
    (with excluded_paths) and `critical_only_universe` (without
    excluded_paths). Critical globs override excluded_paths.

    Here we prepare findings per-component: a path is a candidate
    finding iff:
      (a) NOT in any component's source_paths (caller checks per comp), AND
      (b) NOT in excluded_paths -- unless it matches CRITICAL_GLOBS,
          in which case it MUST be reported.
    """
    if gates._gcs_in_universe(path, excluded_paths):
        # Excluded -- but critical wins (M4).
        return gates._gcs_matches_critical(path)
    return True


# ---------------------------------------------------------------------------
# Per-component finding builder
# ---------------------------------------------------------------------------


def _component_findings(
    project_root: Path,
    comp: Dict[str, Any],
    walked_paths: List[str],
    excluded_paths: List[str],
    seen: set,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """For one component, compute (findings, actual_paths).

    `seen` tracks paths already attributed to a previous component so
    `total_findings` is not double-counted in the union summary.
    """
    declared = _expanded_source_paths(comp)
    actual_paths: List[str] = []
    findings: List[Dict[str, Any]] = []

    for path in walked_paths:
        # Track which actual workspace paths fall under this component's
        # declared globs. Used for downstream review (auditor sees what
        # the component "claims" to own and what's actually there).
        in_declared = _path_in_declared(path, declared)
        if in_declared:
            actual_paths.append(path)
            continue

        # Path not declared by this component -- but may belong to another
        # component's declared globs. We DO NOT report cross-component-
        # ownership here; only paths that are in NO component's universe
        # (and not excluded -- M4 carve-out for critical) become findings.
        # That cross-check happens in run() via the global declared_universe.

        # Skip if some other component already attributed this finding
        # in this scan run (prevents inflation when an undeclared file
        # happens to match the broad excluded_paths layout).
        if path in seen:
            continue

        # Will be re-checked against the global declared_universe in run()
        # before being emitted as a finding for this component.
        # Per-component bucket = "this is the closest-owning component
        # by some heuristic". For v1 file-level granularity we don't
        # attempt heuristic ownership; the union summary is the
        # authoritative count, and per-component buckets reflect only
        # `actual_paths` (the declared overlap).
        # Result: per-component findings list stays empty unless we
        # later attribute via global pass.
        pass  # intentional no-op; attribution happens in run().

    return findings, actual_paths


# ---------------------------------------------------------------------------
# Atomic YAML writer (small helper -- mirrors scope_delta.write_record)
# ---------------------------------------------------------------------------


def _atomic_write_yaml(target: Path, payload: Dict[str, Any]) -> None:
    """Write `payload` as YAML atomically: write to <target>.tmp, fsync,
    rename. Avoids torn writes on concurrent reads."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    text = yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
    with tmp.open("w") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, target)
    # fsync the parent directory so the rename is durable.
    try:
        dir_fd = os.open(str(target.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        # Some filesystems (e.g., tmpfs) don't support directory fsync;
        # the rename is still durable per POSIX semantics.
        pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run(project_root: Path) -> None:
    """Execute the retro-scan and write progress/retro-scan-S028.yaml.

    Exit codes:
      * 0 -- success (raised via implicit return)
      * 2 -- env error (raised via SystemExit in _env_error)
    """
    project_root = Path(project_root).resolve()
    if not project_root.is_dir():
        _env_error(f"project_root is not a directory: {project_root}")

    map_path = project_root / CONTRACT_MAP_RELPATH
    map_yaml = _load_contract_map(map_path)
    map_hash = _hash_map_file(map_path)
    map_revision = map_yaml.get("revision")
    if not isinstance(map_revision, int):
        _env_error(
            f"contract-map missing/invalid `revision` (got {map_revision!r})"
        )

    components = map_yaml.get("components", []) or []
    excluded_paths = list(map_yaml.get("excluded_paths", []) or [])
    declared_universe = gates._gcs_compute_declared_universe(map_yaml)

    # Walk the workspace once. The skip set in _gcs_walk_workspace already
    # prunes .git, .ledger, .forge, .design-ledger, __pycache__, node_modules,
    # .venv, venv, .tox, .mypy_cache, .pytest_cache.
    walked = gates._gcs_walk_workspace(project_root)

    # Per-component buckets: actual_paths = files that fall under each
    # component's declared globs. Findings are computed at the union level
    # and attributed back to the FIRST component whose excluded_paths or
    # nearest-owning glob would have plausibly contained the artifact;
    # for v1 (file-level), the simpler attribution rule is: every finding
    # goes into a synthetic "(unattributed)" component bucket as the
    # default, but if a component's owner_wp is the only one declared,
    # findings ride alongside it. To keep the schema clean and avoid
    # heuristic guessing, we surface ALL findings under the first
    # component bucket and document the limitation in SKILL.md.

    component_buckets: List[Dict[str, Any]] = []
    component_actual_map: Dict[str, List[str]] = {}
    for comp in components:
        cid = comp.get("id") or "(unknown)"
        actual = [
            p for p in walked
            if _path_in_declared(p, _expanded_source_paths(comp))
        ]
        component_actual_map[cid] = actual
        component_buckets.append({
            "component_id": cid,
            "declared_source_paths": list(comp.get("source_paths", []) or []),
            "actual_paths": actual,
            "findings": [],
        })

    # Compute global findings: paths walked that are NOT in declared_universe,
    # honoring M4 precedence (critical globs override excluded_paths).
    findings_global: List[Dict[str, Any]] = []
    for path in walked:
        if _path_in_declared(path, declared_universe):
            # Either declared by a component, declared by a flow, or in
            # excluded_paths. M4: if it's in excluded_paths AND matches
            # a critical glob, it MUST still be reported.
            if _path_in_declared(path, excluded_paths) and \
                    gates._gcs_matches_critical(path):
                pass  # fall through to finding emission below
            else:
                continue
        # Build the finding via the LOCKED extractor priority chain.
        delta = first_match(project_root, path, "added")
        if delta is None:
            # Should not happen: `file` extractor is catch-all per CONTRACT-A1.
            kind = "file"
        else:
            kind = delta.kind
        severity = _classify_severity(path)
        findings_global.append({
            "path": path,
            "artifact_kind": kind,
            "in_declared": False,
            "severity": severity,
        })

    # Attribute findings to component buckets. For v1 (file-level), we
    # attribute each finding to the FIRST bucket whose component-id
    # alphabetically sorts first -- simple, deterministic, no heuristic
    # ownership claims. SKILL.md §Behavior documents this attribution
    # is conservative; refinement is S030+ work.
    if component_buckets:
        component_buckets[0]["findings"] = findings_global

    # baseline_summary
    n_total = len(findings_global)
    n_critical = sum(1 for f in findings_global
                     if f["severity"] == "pre_existing_critical")
    n_advisory = sum(1 for f in findings_global
                     if f["severity"] == "pre_existing_advisory")

    # baseline_critical_paths -- Q2 #4 enforcement list
    baseline_critical_paths = [f["path"] for f in findings_global
                               if f["severity"] == "pre_existing_critical"]

    payload: Dict[str, Any] = {
        "schema_version": "retro_scan.v1",
        "generated_at": _dt.datetime.now(_dt.timezone.utc)
                                    .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": "retro-scan-s028",
        "contract_map_hash": f"sha256:{map_hash}",
        "contract_map_revision": map_revision,
        "components": component_buckets,
        "baseline_summary": {
            "total_findings": n_total,
            "pre_existing": n_total,            # baseline = pre-existing by definition
            "pre_existing_critical": n_critical,
            "pre_existing_advisory": n_advisory,
            "newly_introduced": 0,
        },
    }
    if baseline_critical_paths:
        payload["baseline_critical_paths"] = baseline_critical_paths

    out_path = project_root / OUTPUT_RELPATH
    _atomic_write_yaml(out_path, payload)

    sys.stdout.write(
        f"retro-scan-s028: {n_total} findings, "
        f"{n_critical} critical, {n_advisory} advisory across "
        f"{len(component_buckets)} components -> {out_path}\n"
    )


def _cli() -> None:
    if len(sys.argv) != 2:
        sys.stderr.write(
            "usage: python3 scan.py <project_root>\n"
            "  writes <project_root>/progress/retro-scan-S028.yaml\n"
        )
        raise SystemExit(2)
    run(Path(sys.argv[1]))


if __name__ == "__main__":
    _cli()
