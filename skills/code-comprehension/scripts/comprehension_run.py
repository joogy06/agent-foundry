#!/usr/bin/env python3
"""comprehension_run.py — claimless, read-only orchestrator for code-comprehension.

Owns the whole pipeline for a NON-bob run on an arbitrary repo. CB4-safe by
absence: writes ONLY under the repo's `.comprehension/` scratch (+ generated docs)
and the orchestrator-owned wiring scratch; NEVER under `.ledger/` or `progress/`.

Sequence (design §3 + §11 render-bundle + §12 standalone):
  1. wiring-extract-static --standalone --contract-map-path none   (clean first pass)
  2. partition.py  → .comprehension/synthetic-contract-map.yaml (+ lock + report)
  3. wiring-extract-static --standalone --contract-map-path <synthetic>  (real ids)
  4. intent-extract --standalone --contract-map-path <synthetic>   (per-component intent;
       degraded/structural-only components are SKIPPED — no LLM spend)
  5. render-bundle (in-memory):
       a. merge per-component intent caches → one {"components":[...]} intent-map
       b. reconciler.reconcile(static_edges, [], manifest, comp_ids, ...) → edge view
  6. render_docs.render_all(...) → shadow PROJECT.md + COMPONENT.md (WP-6)

The orchestrator is the SINGLE CREATOR of the wiring scratch root for the run
(there is no bob to create it), preserving the single-creator invariant.

CB4 boundary: the run touches nothing under `.ledger/` or `progress/`. The two
extractors run in `--standalone` (claims structurally impossible). See
`tests/test_cb4_boundary.py` for the byte-identical snapshot gate.

CLI:
    python3 comprehension_run.py --project-dir REPO [--shadow] [--backend fake --fake-yaml ...]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    sys.stderr.write("FATAL: pyyaml not installed\n")
    sys.exit(1)

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import partition as partition_mod  # noqa: E402

# Skill locations (global library)
SKILLS_ROOT = Path.home() / ".claude" / "skills"
WIRING_RUN = SKILLS_ROOT / "wiring-extract-static" / "scripts" / "run.py"
INTENT_RUN = SKILLS_ROOT / "intent-extract" / "scripts" / "run.py"
RECONCILER_DIR = SKILLS_ROOT / "wiring-reconcile" / "scripts"

# Allow render_docs (co-located) to be imported lazily after WP-6 lands.


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def _run(cmd: List[str], *, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def compute_tree_hash(project_dir: Path) -> str:
    """git write-tree, or a zero hash if not a git repo (extractors still run)."""
    try:
        cp = _run(["git", "-C", str(project_dir), "write-tree"], timeout=60)
        if cp.returncode == 0 and len(cp.stdout.strip()) == 40:
            return cp.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "0" * 40


# ---------------------------------------------------------------------------
# Wiring passes
# ---------------------------------------------------------------------------


def run_wiring(
    project_dir: Path,
    wiring_root: Path,
    run_id: str,
    contract_map_path: str,
    *,
    timeout: int = 1800,
) -> Tuple[int, Path, Path]:
    """Run wiring-extract-static --standalone. Returns (rc, static_jsonl, manifest)."""
    cmd = [
        sys.executable, str(WIRING_RUN),
        "--project-dir", str(project_dir),
        "--run-id", run_id,
        "--standalone",
        "--contract-map-path", contract_map_path,
        "--wiring-root", str(wiring_root),
    ]
    cp = _run(cmd, timeout=timeout)
    if cp.returncode != 0:
        sys.stderr.write(f"[wiring] rc={cp.returncode}\n{cp.stderr}\n")
    static_jsonl = wiring_root / "runs" / run_id / "static.jsonl"
    manifest = wiring_root / "runs" / run_id / "manifest.json"
    return cp.returncode, static_jsonl, manifest


# ---------------------------------------------------------------------------
# Intent pass
# ---------------------------------------------------------------------------


def run_intent(
    project_dir: Path,
    wiring_root: Path,
    run_id: str,
    synthetic_map_path: Path,
    component_ids: List[str],
    workspace_tree_hash: str,
    *,
    backend: str = "anthropic",
    fake_yaml: str = "",
    two_arm: str = "strict",
    timeout: int = 3600,
) -> Tuple[int, Path]:
    """Run intent-extract --standalone for the LLM-eligible components.

    intent-extract writes its cache + per-run dir under <project_root>/.wiring/. We
    pass --project-root = project_dir (source resolution must see the real files) and
    point --static-jsonl-path at the orchestrator-owned wiring root. The cache lands
    under <project_dir>/.wiring/intent-cache — orchestrator-owned scratch (NOT under
    .ledger/ or progress/, so CB4 holds).
    """
    static_jsonl = wiring_root / "runs" / run_id / "static.jsonl"
    cmd = [
        sys.executable, str(INTENT_RUN),
        "--project-root", str(project_dir),
        "--run-id", run_id,
        "--workspace-tree-hash", workspace_tree_hash,
        "--components", ",".join(component_ids),
        "--standalone",
        "--contract-map-path", str(synthetic_map_path),
        "--static-jsonl-path", str(static_jsonl),
        "--two-arm", two_arm,
        "--backend", backend,
    ]
    if backend == "fake":
        cmd += ["--fake-yaml", fake_yaml]
    cp = _run(cmd, timeout=timeout)
    if cp.returncode != 0:
        sys.stderr.write(f"[intent] rc={cp.returncode}\n{cp.stderr}\n")
    manifest = project_dir / ".wiring" / "runs" / run_id / "intent-manifest.json"
    return cp.returncode, manifest


# ---------------------------------------------------------------------------
# Render-bundle (BLOCKER-1 + BLOCKER-2 resolution)
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def merge_intent_caches(
    project_dir: Path,
    run_id: str,
    component_ids: List[str],
) -> Dict[str, Any]:
    """BLOCKER-2: collect per-component intent cache files → one {"components":[...]}.

    intent-extract writes one functional-intent.v1 file per component (hard-linked
    into .wiring/runs/<run_id>/intent/<component_id>.yaml). We read those and build
    the merged map intent-map-render's loader.load_intent_map accepts directly.
    Components without an intent file (degraded/structural-only/gap) get a minimal
    structural stub so they still appear in the docs with a confidence badge.
    """
    intent_dir = project_dir / ".wiring" / "runs" / run_id / "intent"
    components: List[Dict[str, Any]] = []
    for cid in sorted(component_ids):
        f = intent_dir / f"{cid}.yaml"
        if f.is_file():
            try:
                doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                if isinstance(doc, dict) and doc.get("component_id"):
                    components.append(doc)
                    continue
            except yaml.YAMLError:
                pass
        # structural stub (no LLM intent available)
        components.append({
            "schema_version": "1.0.0",
            "component_id": cid,
            "function_class": "unknown",
            "entry_points": [],
            "inputs": [], "outputs": [], "side_effects": [],
            "flows_participated": [], "error_paths": [], "test_seeds": [],
            "unknowns": [],
            "intent": {"one_line": f"(structural-only; no LLM intent for {cid})",
                       "confidence_level": "structural-only"},
            "determinism_class": "structural_only",
        })
    return {"components": components}


def build_edge_view(
    static_jsonl: Path,
    manifest_path: Path,
    component_ids: List[str],
    run_id: str,
    workspace_tree_hash: str,
) -> Dict[str, Any]:
    """BLOCKER-1: component-level edge view via wiring-reconcile's PURE merge core.

    Calls reconciler.reconcile(static_edges, [], manifest, component_ids, ...) — no
    file I/O, no HMAC, no promotion to latest.json. Returns the snapshot dict
    (edges[] + components[] + statistics) the renderer consumes.
    """
    sys.path.insert(0, str(RECONCILER_DIR))
    import reconciler  # noqa: E402  (pure merge core only)

    static_edges = _read_jsonl(static_jsonl)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {"sources": []}
    except (OSError, json.JSONDecodeError):
        manifest = {"sources": []}

    snapshot = reconciler.reconcile(
        static_edges=static_edges,
        asserted_edges=[],
        manifest=manifest,
        contract_map_components=component_ids,
        run_id=run_id,
        workspace_tree_hash=workspace_tree_hash,
        generated_at="1970-01-01T00:00:00Z",   # deterministic; renderer strips it anyway
        snapshot_generation=1,
    )
    return snapshot


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def orchestrate(
    project_dir: Path,
    *,
    out_dir: Optional[Path] = None,
    cfg: Optional[partition_mod.PartitionConfig] = None,
    backend: str = "anthropic",
    fake_yaml: str = "",
    two_arm: str = "strict",
    shadow: bool = True,
    render: bool = True,
) -> Dict[str, Any]:
    """Run the full pipeline. Returns a result dict (paths + summaries).

    The orchestrator creates (and is the single creator of) the wiring scratch root
    for the run, and cleans nothing destructive under the repo.
    """
    project_dir = project_dir.resolve()
    out_dir = out_dir or (project_dir / ".comprehension")
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg or partition_mod.PartitionConfig()

    # The wiring scratch root the orchestrator owns. We keep it under .comprehension/
    # so all scratch is co-located; the cache that intent-extract writes lands under
    # <repo>/.wiring/ (orchestrator-owned scratch, NOT .ledger/ or progress/).
    wiring_root = out_dir / ".wiring"
    wiring_created = not wiring_root.exists()
    wiring_root.mkdir(parents=True, exist_ok=True)

    run_id = str(uuid.uuid4())
    tree_hash = compute_tree_hash(project_dir)
    result: Dict[str, Any] = {"run_id": run_id, "project_dir": str(project_dir),
                              "out_dir": str(out_dir), "steps": []}

    # 1. wiring pass 1 (clean — unmapped_path:* first pass)
    rc1, static1, manifest1 = run_wiring(project_dir, wiring_root, run_id, "none")
    result["steps"].append({"step": "wiring_pass1", "rc": rc1,
                            "static_jsonl": str(static1)})

    # 2. partition
    doc = partition_mod.partition(
        project_dir,
        static_jsonl_path=static1 if static1.is_file() else None,
        out_dir=out_dir, cfg=cfg, ratify=True,
    )
    synthetic_map = out_dir / "synthetic-contract-map.yaml"
    component_ids = [c["id"] for c in doc["components"]]
    llm_components = [c["id"] for c in doc["components"] if c["intent_mode"] == "llm"]
    result["partition"] = {
        "components": component_ids,
        "llm_components": llm_components,
        "decisions": doc["decisions"],
        "partition_hash": doc["partition_hash"],
        "map_path": str(synthetic_map),
    }
    result["steps"].append({"step": "partition", "components": len(component_ids)})

    # 3. wiring pass 2 (with synthetic map → real component ids on edges)
    run_id2 = str(uuid.uuid4())
    rc3, static2, manifest2 = run_wiring(project_dir, wiring_root, run_id2, str(synthetic_map))
    result["steps"].append({"step": "wiring_pass2", "rc": rc3,
                            "static_jsonl": str(static2)})

    # 4. intent (LLM-eligible components only — degraded/structural-only are skipped)
    intent_manifest_path: Optional[Path] = None
    if llm_components:
        rc4, intent_manifest_path = run_intent(
            project_dir, wiring_root, run_id2, synthetic_map, llm_components,
            tree_hash, backend=backend, fake_yaml=fake_yaml, two_arm=two_arm,
        )
        result["steps"].append({"step": "intent", "rc": rc4,
                               "manifest": str(intent_manifest_path)})
    else:
        result["steps"].append({"step": "intent", "rc": 0, "skipped": "no llm components"})

    # 5. render-bundle
    intent_map = merge_intent_caches(project_dir, run_id2, component_ids)
    edge_view = build_edge_view(static2, manifest2, component_ids, run_id2, tree_hash)
    result["bundle"] = {
        "components_in_map": len(intent_map["components"]),
        "edges": edge_view.get("statistics", {}).get("total_edges", 0),
    }

    # 6. render (WP-6) — imported lazily so WP-5 stands alone if render not yet present
    if render:
        try:
            import render_docs  # noqa: E402
            render_result = render_docs.render_all(
                project_dir=project_dir,
                out_dir=out_dir,
                partition_doc=doc,
                intent_map=intent_map,
                edge_view=edge_view,
                shadow=shadow,
            )
            result["render"] = render_result
            result["steps"].append({"step": "render", "ok": True})
        except ImportError:
            result["steps"].append({"step": "render", "ok": False,
                                    "note": "render_docs not available"})

    # Persist a run report (post-hoc inspection)
    report = out_dir / "run-report.json"
    report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["report_path"] = str(report)
    result["wiring_root_created_by_orchestrator"] = wiring_created
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="code-comprehension.run")
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--cap", type=int, default=12)
    ap.add_argument("--max-files", type=int, default=40)
    ap.add_argument("--max-bytes", type=int, default=512_000)
    ap.add_argument("--per-component-token-budget", type=int, default=120_000)
    ap.add_argument("--backend", default="anthropic", choices=["anthropic", "fake"])
    ap.add_argument("--fake-yaml", default="")
    ap.add_argument("--two-arm", default="strict", choices=["strict", "skip"])
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--shadow", action="store_true", default=True,
                    help="generate to a shadow path (default; never overwrites real docs)")
    ns = ap.parse_args(argv)

    project_dir = Path(ns.project_dir)
    if not project_dir.is_dir():
        sys.stderr.write(f"project-dir not found: {project_dir}\n")
        return 1
    cfg = partition_mod.PartitionConfig(
        cap=ns.cap, max_files=ns.max_files, max_bytes=ns.max_bytes,
        per_component_token_budget=ns.per_component_token_budget,
    )
    out_dir = Path(ns.out_dir) if ns.out_dir else None
    result = orchestrate(
        project_dir, out_dir=out_dir, cfg=cfg, backend=ns.backend,
        fake_yaml=ns.fake_yaml, two_arm=ns.two_arm, shadow=ns.shadow,
        render=not ns.no_render,
    )
    sys.stdout.write(json.dumps({
        "run_id": result["run_id"],
        "components": result["partition"]["components"],
        "llm_components": result["partition"]["llm_components"],
        "edges": result["bundle"]["edges"],
        "report": result["report_path"],
        "render": result.get("render", {}),
    }, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
