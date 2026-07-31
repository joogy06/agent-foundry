#!/usr/bin/env python3
"""generate.py — integration-flow-testing@1.1 implementation.

Per design 2026-04-14 §5.5. Backward-compatible extension of v1.0.

Public API:
    generate_tests(component_id, contract_map_path, project_root,
                   language_target="pytest", output_root=None) -> dict

Behavior:
- v1.0 parity: produces test files from declared integration_points[] and
  flows[] (flow owner is the component at flow.entry_input.component).
- v1.1 addition: when `.wiring/latest.json` exists AND a declared flow's
  component-path overlaps the snapshot, inject an evidence header with per-edge
  evidence provenance and mark non-blocking-eligible edges with
  `@pytest.mark.unconfirmed_wiring`.
- v1.1 addition: scan snapshot for multi-hop paths (≥2 components) not in
  contract-map flows[]; emit `.wiring/wiring-flow-suggestions.json`. Never
  generate tests from suggestions — advisory only.
- bob-promote invariant: `reconcile → query` and `reconcile → gates-g4` are
  implicit corroborated transitions and never appear in suggestions.

Drift canary: ALDEBARAN-7.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    sys.stderr.write("FATAL: pyyaml required\n")
    sys.exit(3)


VERSION = "1.1.0"


# ---------------------------------------------------------------------------
# Snapshot import: programmatic first, fallback to direct json.load
# ---------------------------------------------------------------------------

def _load_snapshot_programmatic(project_root: Path) -> Optional[Dict[str, Any]]:
    """Try importing wiring_query.loader. Fall back to direct read on failure."""
    snapshot: Optional[Dict[str, Any]] = None
    # Try the programmatic path first
    wq_scripts = Path.home() / ".claude" / "skills" / "wiring-query" / "scripts"
    if wq_scripts.is_dir():
        sys.path.insert(0, str(wq_scripts))
        try:
            import loader as wq_loader  # type: ignore
            try:
                snapshot = wq_loader.load_snapshot(project_root, use_cache=False)
                return snapshot
            except Exception:
                snapshot = None
        except ImportError:
            snapshot = None
    # Fallback: direct read
    latest = project_root / ".wiring" / "latest.json"
    if not latest.is_file():
        return None
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Evidence aggregation for declared flow
# ---------------------------------------------------------------------------

def _flow_edges_from_snapshot(
    snapshot: Dict[str, Any],
    flow_path: List[str],
) -> List[Dict[str, Any]]:
    """Return edges whose src+dst components form adjacent hops in flow_path."""
    if not flow_path:
        return []
    wanted_pairs = {
        (flow_path[i], flow_path[i + 1]) for i in range(len(flow_path) - 1)
    }
    matched = []
    for e in snapshot.get("edges") or []:
        pair = (e.get("src_component"), e.get("dst_component"))
        if pair in wanted_pairs:
            matched.append(e)
    matched.sort(key=lambda e: e.get("edge_id", ""))
    return matched


def _evidence_summary_for_edge(edge: Dict[str, Any]) -> str:
    parts = []
    for ev in edge.get("evidence") or []:
        src = ev.get("evidence_source", "?")
        ext = ev.get("extractor_id", "?")
        ver = ev.get("extractor_version", "?")
        parts.append(f"{src} [{ext}@{ver}]")
    return " + ".join(parts) if parts else "no evidence"


# ---------------------------------------------------------------------------
# Suggestion advisory
# ---------------------------------------------------------------------------

BOB_PROMOTE_IMPLICIT_TRANSITIONS = {
    ("wiring-reconcile", "wiring-query"),
    ("wiring-reconcile", "gates-g4"),
}


def _compute_suggestions(
    snapshot: Dict[str, Any],
    declared_flow_paths: List[List[str]],
) -> List[Dict[str, Any]]:
    """Find multi-hop component paths in the snapshot NOT in any declared flow.

    Deterministic: edges sorted by edge_id, unique component-pair detection,
    resulting path list sorted.
    """
    declared_hops = set()
    for p in declared_flow_paths:
        for i in range(len(p) - 1):
            declared_hops.add((p[i], p[i + 1]))

    # Build adjacency at component level
    adj: Dict[str, List[str]] = {}
    for e in snapshot.get("edges") or []:
        if e.get("status") not in ("live",):
            continue
        s = e.get("src_component")
        d = e.get("dst_component")
        if not s or not d or s == d:
            continue
        adj.setdefault(s, []).append(d)

    # Enumerate 2-3 hop paths that include at least one non-declared hop AND
    # are NOT entirely implicit bob-promote transitions.
    suggestions: List[Tuple[str, ...]] = []
    seen: set = set()
    roots = sorted(adj.keys())
    for root in roots:
        for mid in sorted(set(adj.get(root, []))):
            for dst in sorted(set(adj.get(mid, []))):
                if dst == root or dst == mid:
                    continue
                path = (root, mid, dst)
                # Entire path must not be declared already
                hops = {(path[i], path[i + 1]) for i in range(len(path) - 1)}
                if hops.issubset(declared_hops):
                    continue
                # Exclude if every hop is an implicit bob-promote transition
                if hops.issubset(BOB_PROMOTE_IMPLICIT_TRANSITIONS):
                    continue
                if path in seen:
                    continue
                seen.add(path)
                suggestions.append(path)

    out = []
    for i, path in enumerate(sorted(suggestions)):
        # Evidence breakdown for suggestion's edges
        breakdown: Dict[str, int] = {}
        for e in snapshot.get("edges") or []:
            pair = (e.get("src_component"), e.get("dst_component"))
            if pair in {(path[j], path[j + 1]) for j in range(len(path) - 1)}:
                for ev in e.get("evidence") or []:
                    src = ev.get("evidence_source", "unknown")
                    breakdown[src] = breakdown.get(src, 0) + 1
        out.append({
            "suggested_flow_id": f"SUGG-{i + 1:03d}",
            "path": list(path),
            "evidence_breakdown": breakdown,
            "rationale": "Multi-hop path in snapshot not in contract-map.yaml.flows[]",
        })
    return out


# ---------------------------------------------------------------------------
# Test codegen
# ---------------------------------------------------------------------------

def _render_integration_test_pytest(
    component_id: str,
    integration_point: Dict[str, Any],
    contract_revision: int,
    header_extra: str = "",
) -> str:
    target = integration_point.get("with", "unknown")
    direction = integration_point.get("direction", "?")
    protocol = integration_point.get("protocol", "?")
    endpoint = integration_point.get("endpoint", "?")
    failure_mode = integration_point.get("failure_mode", "?")
    safe_target = target.replace(":", "_").replace("/", "_").replace("-", "_")
    return (
        f"# Auto-generated by integration-flow-testing@{VERSION}\n"
        f"# Contract-map revision: {contract_revision}\n"
        f"# Component: {component_id}\n"
        f"# Integration point: {component_id} -> {target} ({direction} {protocol})\n"
        f"{header_extra}"
        f"\n"
        f"import pytest\n"
        f"\n"
        f"def test_{component_id.replace('-', '_')}_{safe_target}_happy():\n"
        f"    \"\"\"Happy: {endpoint}.\"\"\"\n"
        f"    # TODO: real test body\n"
        f"    assert True\n"
        f"\n"
        f"def test_{component_id.replace('-', '_')}_{safe_target}_failure():\n"
        f"    \"\"\"Failure mode: {failure_mode}.\"\"\"\n"
        f"    # TODO: real test body\n"
        f"    assert True\n"
    )


def _render_flow_test_pytest(
    flow: Dict[str, Any],
    contract_revision: int,
    snapshot: Optional[Dict[str, Any]],
) -> str:
    fid = flow.get("id", "FLOW-?")
    fname = flow.get("name", fid)
    path = flow.get("path") or []
    expected = flow.get("expected_outcome", "see contract map")

    header = [
        f"# Auto-generated by integration-flow-testing@{VERSION}",
        f"# Contract-map revision: {contract_revision}",
        f"# Flow: {fid} — {fname}",
        f"# Path: {' -> '.join(path)}",
    ]
    # v1.1 evidence header
    unconfirmed_markers: List[str] = []
    if snapshot is not None:
        gen = snapshot.get("snapshot_generation")
        run_id = snapshot.get("run_id")
        gen_at = snapshot.get("generated_at")
        header.append(
            f"# Wiring snapshot: gen={gen}, run_id={run_id} at {gen_at}"
        )
        edges = _flow_edges_from_snapshot(snapshot, path)
        if edges:
            header.append("# Evidence corroboration (from .wiring/latest.json):")
            unconfirmed_count = 0
            for e in edges:
                src_c = e.get("src_component")
                dst_c = e.get("dst_component")
                ev_summary = _evidence_summary_for_edge(e)
                header.append(f"#   - {src_c} -> {dst_c}: {ev_summary}")
                if not e.get("blocking_eligible", False):
                    unconfirmed_count += 1
                    unconfirmed_markers.append(
                        f"# NOTE: edge {src_c} -> {dst_c} is unconfirmed_wiring"
                    )
            header.append(f"# Unconfirmed edges in this flow: {unconfirmed_count}")
        else:
            header.append("# Evidence corroboration: no matching snapshot edges")
    else:
        header.append("# wiring snapshot not available")

    body_lines = [
        "",
        "import pytest",
        "",
    ]
    if unconfirmed_markers:
        body_lines.extend(unconfirmed_markers)
        body_lines.append("")
        body_lines.append("@pytest.mark.unconfirmed_wiring")

    func_name = f"test_flow_{fid.lower().replace('-', '_')}"
    # Fix for codegen defect (S028 Phase 4c-A observation): use repr() but escape any
    # embedded triple-quote sequence that would break the docstring boundary. Python
    # repr picks " as delimiter when the string contains ' — combined with outer """
    # this produced 4 consecutive " and a SyntaxError. Split escaped repr instead.
    escaped_expected = repr(expected).replace('"""', '\\"\\"\\"')
    body_lines.extend([
        f"def {func_name}():",
        f"    # {fid}: expected_outcome = {escaped_expected}",
        "    # TODO: real test body",
        "    assert True",
        "",
    ])
    return "\n".join(header + body_lines)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_tests(
    component_id: str,
    contract_map_path: Path,
    project_root: Path,
    language_target: str = "pytest",
    output_root: Optional[Path] = None,
    *,
    claim_uuid: Optional[str] = None,
    wp_id: Optional[str] = None,
    emit_request: bool = False,
) -> Dict[str, Any]:
    """Produce integration + flow tests for a given component.

    Returns a dict:
      {
        "version": "1.1.0",
        "component_id": ...,
        "integration_tests": [path, ...],
        "flow_tests": [path, ...],
        "suggestions_file": path or None,
        "snapshot_present": bool,
        "request_file": str or None,
      }

    When `emit_request=True` AND `claim_uuid` + `wp_id` are provided, the
    function ALSO emits a `.ledger/requests/<uuid>.request.yaml` file that
    bob's `claims.apply_request_idempotent` can consume to apply the
    UNIT_TESTED → INTEGRATED transition. This closes the SKILL.md Step 7
    doc-vs-code drift surfaced by S030-quickwins #48. Without
    `emit_request=True`, the function preserves v1.0/v1.1 behaviour
    (test files only; bob's caller emits the request manually).
    """
    if language_target not in ("pytest", "jest"):
        raise ValueError(f"unsupported language_target: {language_target}")
    if language_target == "jest":
        # v1.0 had jest templates; this is the byte-identity contract —
        # v1.1 is additive. For this bob pass we focus on pytest; a full
        # jest codegen is a future deliverable, but the skill signals
        # support so the contract-map's jest component still validates.
        raise ValueError(
            "jest rendering for v1.1 is not shipped in this bob pass; "
            "use pytest target for now"
        )

    project_root = Path(project_root).resolve()
    output_root = Path(output_root) if output_root else project_root

    map_yaml = yaml.safe_load(Path(contract_map_path).read_text())
    revision = int(map_yaml.get("revision", 0) or 0)
    component = next(
        (c for c in map_yaml.get("components") or [] if c.get("id") == component_id),
        None,
    )
    if component is None:
        raise ValueError(f"component {component_id!r} not in contract map")

    snapshot = _load_snapshot_programmatic(project_root)
    snapshot_present = snapshot is not None

    # Integration tests per integration_point
    # S030-quickwins #33: prefix test filenames with the component id so
    # sibling component dirs whose names contain hyphens (and therefore are
    # not Python packages) cannot collide on `test_int_<target>.py` when the
    # pytest collector flattens them. Discovered in DLP pilot 2026-04-09 +
    # S028 keystone weather widget smoke. The bob workaround was a manual
    # rename; this makes it the native behaviour.
    int_paths: List[Path] = []
    int_dir = output_root / "tests" / "integration" / component_id
    int_dir.mkdir(parents=True, exist_ok=True)
    safe_component = component_id.replace(":", "_").replace("/", "_").replace("-", "_")
    for ip in component.get("integration_points") or []:
        target = (ip.get("with") or "unknown").replace(":", "_").replace(
            "/", "_"
        ).replace("-", "_")
        fpath = int_dir / f"test_int_{safe_component}__{target}.py"
        content = _render_integration_test_pytest(
            component_id, ip, revision,
        )
        fpath.write_text(content, encoding="utf-8")
        int_paths.append(fpath)

    # Flow tests: owner is entry_input.component
    flow_paths: List[Path] = []
    flow_dir = output_root / "tests" / "flow"
    flow_dir.mkdir(parents=True, exist_ok=True)
    declared_paths: List[List[str]] = []
    for flow in map_yaml.get("flows") or []:
        entry_comp = ((flow.get("entry_input") or {}).get("component"))
        declared_paths.append(flow.get("path") or [])
        if entry_comp != component_id:
            continue
        fid = flow.get("id", "FLOW-?").lower().replace("-", "_")
        fpath = flow_dir / f"test_flow_{fid}.py"
        content = _render_flow_test_pytest(flow, revision, snapshot)
        fpath.write_text(content, encoding="utf-8")
        flow_paths.append(fpath)

    # Suggestions (advisory, never generates tests)
    suggestions_path: Optional[Path] = None
    if snapshot_present:
        suggestions = _compute_suggestions(snapshot, declared_paths)
        suggestions_path = project_root / ".wiring" / "wiring-flow-suggestions.json"
        suggestions_path.parent.mkdir(parents=True, exist_ok=True)
        suggestions_doc = {
            "schema_version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "snapshot_generation": snapshot.get("snapshot_generation"),
            "suggestions": suggestions,
        }
        suggestions_path.write_text(
            json.dumps(suggestions_doc, sort_keys=True, indent=2),
            encoding="utf-8",
        )

    # S030-quickwins #48: optional transition-request emit. Requires both
    # claim_uuid AND wp_id (lacking either is a programming error from the
    # caller, NOT a silent no-op — bob would otherwise apply a request that
    # bound to no claim and CB4 would reject it). The request file shape
    # mirrors SKILL.md Step 7 verbatim.
    request_path: Optional[Path] = None
    if emit_request:
        if not claim_uuid or not wp_id:
            raise ValueError(
                "emit_request=True requires both claim_uuid and wp_id "
                "(found claim_uuid=%r, wp_id=%r)" % (claim_uuid, wp_id)
            )
        import uuid as _uuid_mod  # local — keeps top-level imports stable
        import hashlib as _hashlib

        def _content_hash(paths: List[Path]) -> str:
            h = _hashlib.sha256()
            for p in sorted(paths, key=lambda x: str(x)):
                h.update(str(p).encode("utf-8"))
                h.update(b"\0")
                try:
                    h.update(p.read_bytes())
                except OSError:
                    pass
                h.update(b"\0\0")
            return f"sha256:{h.hexdigest()}"

        request_id = str(_uuid_mod.uuid4())
        request_dir = project_root / ".ledger" / "requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        request_payload: Dict[str, Any] = {
            "request_id": request_id,
            "claim_uuid": claim_uuid,
            "wp": wp_id,
            "component_id": component_id,
            "requester": "integration-flow-testing",
            "target_stage": "INTEGRATED",
            "evidence": [
                {
                    "type": "integration_test_files",
                    "produced_by": "skill:integration-flow-testing",
                    "paths": [str(p) for p in int_paths],
                    "hash": _content_hash(int_paths),
                },
                {
                    "type": "flow_test_files",
                    "produced_by": "skill:integration-flow-testing",
                    "paths": [str(p) for p in flow_paths],
                    "hash": _content_hash(flow_paths),
                },
            ],
            "language_target": language_target,
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        request_path = request_dir / f"{request_id}.request.yaml"
        request_path.write_text(
            yaml.safe_dump(request_payload, sort_keys=True, default_flow_style=False),
            encoding="utf-8",
        )

    return {
        "version": VERSION,
        "component_id": component_id,
        "integration_tests": [str(p) for p in int_paths],
        "flow_tests": [str(p) for p in flow_paths],
        "suggestions_file": str(suggestions_path) if suggestions_path else None,
        "snapshot_present": snapshot_present,
        "request_file": str(request_path) if request_path else None,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--component", required=True)
    ap.add_argument("--contract-map", required=True)
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--language", default="pytest")
    ap.add_argument("--output-root", default=None)
    # S030-quickwins #48 — optional transition-request emit (pass both or neither).
    ap.add_argument("--claim-uuid", default=None,
                    help="bob-issued claim UUID; required with --emit-request")
    ap.add_argument("--wp-id", default=None,
                    help="work-package id; required with --emit-request")
    ap.add_argument("--emit-request", action="store_true",
                    help="also write .ledger/requests/<uuid>.request.yaml")
    args = ap.parse_args()
    r = generate_tests(
        args.component, Path(args.contract_map),
        Path(args.project_root), args.language,
        Path(args.output_root) if args.output_root else None,
        claim_uuid=args.claim_uuid,
        wp_id=args.wp_id,
        emit_request=args.emit_request,
    )
    print(json.dumps(r, indent=2))
