"""intent_merge.py — wiring-reconcile v1.1 extension (S032 WP-3).

Merges per-component functional-intent.v1 files (produced by intent-extract)
into the snapshot's `components[].intent` block.

Reads:
  .wiring/runs/<run_id>/intent/<component>.yaml

Writes (in place, mutates the snapshot dict):
  snapshot["components"][i]["intent"] = {function_class, one_line, ...}

Backward-compatible:
  - If no intent files exist for a run, snapshot stays v1.0-shaped (no intent block).
  - If intent files exist for some components, only those get the block.
  - Mutating the snapshot also bumps `schema_version` from "1.0.0" to "1.1.0"
    when at least one intent block is added.

This module is a pure post-processor. The original reconcile() flow runs first
and produces v1.0 output; intent_merge.merge_into_snapshot() decorates it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore[import-untyped]
except ImportError as e:
    raise RuntimeError("pyyaml required for intent_merge") from e


def intent_dir_for_run(project_root: Path, run_id: str) -> Path:
    return project_root / ".wiring" / "runs" / run_id / "intent"


def discover_intent_files(project_root: Path, run_id: str) -> Dict[str, Path]:
    """Return dict of {component_id: intent_file_path} for the run."""
    base = intent_dir_for_run(project_root, run_id)
    if not base.is_dir():
        return {}
    out: Dict[str, Path] = {}
    for f in base.glob("*.yaml"):
        component_id = f.stem
        out[component_id] = f
    return out


def load_intent_summary(intent_path: Path) -> Optional[Dict[str, Any]]:
    """Read a functional-intent.v1 YAML and return a v1.1-snapshot intent block.

    Returns None on malformed input or missing required fields.
    """
    if not intent_path.is_file():
        return None
    try:
        data = yaml.safe_load(intent_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None

    function_class = data.get("function_class")
    intent_block = data.get("intent")
    if not function_class or not isinstance(intent_block, dict):
        return None

    one_line = intent_block.get("one_line", "")
    confidence_level = intent_block.get("confidence_level", "interpretive")

    summary: Dict[str, Any] = {
        "function_class": function_class,
        "one_line": one_line,
        "confidence_level": confidence_level,
    }

    # Cache key (if present)
    content_hash = data.get("content_hash")
    if content_hash:
        # The cache_key field in our v1.1 schema is sha256 of the cache file —
        # we use the content_hash as a stable proxy when the actual cache_key
        # is not available in the intent file itself.
        summary["cache_key"] = content_hash

    # Path relative to project root
    summary["intent_path"] = str(intent_path)

    # Counts
    seeds = data.get("test_seeds", []) or []
    errs = data.get("error_paths", []) or []
    summary["test_seed_count"] = len(seeds) if isinstance(seeds, list) else 0
    summary["error_path_count"] = len(errs) if isinstance(errs, list) else 0

    # Aggregate evidence_edge_count across entry_points + side_effects + error_paths
    edge_count = 0
    for field in ("entry_points", "side_effects", "error_paths"):
        items = data.get(field, []) or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    ev = item.get("evidence_edges", []) or []
                    if isinstance(ev, list):
                        edge_count += len(ev)
    summary["evidence_edge_count"] = edge_count

    return summary


def merge_into_snapshot(
    snapshot: Dict[str, Any],
    project_root: Path,
    run_id: str,
) -> Dict[str, Any]:
    """Decorate snapshot["components"] with intent blocks. Mutates in place.

    If any intent block is added, bumps `schema_version` to "1.1.0".
    """
    intent_files = discover_intent_files(project_root, run_id)
    if not intent_files:
        return snapshot

    components: List[Dict[str, Any]] = snapshot.setdefault("components", [])
    added = 0

    # Names of components already present in the snapshot
    existing_names = {c.get("name") for c in components}

    # First pass: decorate existing entries
    for comp in components:
        name = comp.get("name")
        if name in intent_files:
            summary = load_intent_summary(intent_files[name])
            if summary:
                summary["extract_run_id"] = run_id
                comp["intent"] = summary
                added += 1

    # Second pass: intent files for components NOT in the edge-derived list.
    # These are components from contract-map that have no edges (yet) but
    # still got an intent extraction. Add a stub entry so they're visible.
    for cid, fpath in intent_files.items():
        if cid in existing_names:
            continue
        summary = load_intent_summary(fpath)
        if summary:
            summary["extract_run_id"] = run_id
            components.append({
                "name": cid,
                "inbound_edge_count": 0,
                "outbound_edge_count": 0,
                "intent": summary,
            })
            added += 1

    # Resort components by name for deterministic output
    components.sort(key=lambda c: c.get("name", ""))

    if added > 0:
        snapshot["schema_version"] = "1.1.0"
        snapshot["generated_by"] = "wiring-reconcile@1.1.0"

    return snapshot
