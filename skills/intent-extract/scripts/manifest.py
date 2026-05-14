"""manifest.py — Write per-run intent-manifest.json.

Mirrors wiring-source-manifest.v1 shape — records per-component status:
  hit         : cache hit, no LLM call
  regenerated : LLM called, fresh output written
  failed      : LLM call failed (budget exhaust / API error / schema violation)
  gap         : component listed in --components but absent from contract-map

Used by run.py to summarize a run's outcome. Read by evo's manifest.yaml
and the verdict aggregator.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional


def manifest_path(project_root: Path, run_id: str) -> Path:
    return project_root / ".wiring" / "runs" / run_id / "intent-manifest.json"


def empty_manifest(run_id: str) -> Dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "extractor_id": "intent-extract",
        "extractor_version": "1.0.0",
        "components": [],
        "summary": {
            "total": 0,
            "hit": 0,
            "regenerated": 0,
            "failed": 0,
            "gap": 0,
            "llm_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
        },
    }


def record_component(
    manifest: Dict[str, object],
    component_id: str,
    status: str,
    *,
    cache_key: str = "",
    output_path: str = "",
    error: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> None:
    """Append a per-component record to the manifest in place."""
    if status not in {"hit", "regenerated", "failed", "gap"}:
        raise ValueError(f"invalid status: {status}")
    entry = {
        "component_id": component_id,
        "status": status,
        "cache_key": cache_key,
        "output_path": output_path,
    }
    if error:
        entry["error"] = error
    if tokens_in or tokens_out:
        entry["tokens_in"] = tokens_in
        entry["tokens_out"] = tokens_out

    components = manifest.setdefault("components", [])
    assert isinstance(components, list)
    components.append(entry)

    summary = manifest.setdefault("summary", {})
    assert isinstance(summary, dict)
    summary["total"] = summary.get("total", 0) + 1
    summary[status] = summary.get(status, 0) + 1
    if status == "regenerated":
        summary["llm_calls"] = summary.get("llm_calls", 0) + 1
        summary["tokens_in"] = summary.get("tokens_in", 0) + tokens_in
        summary["tokens_out"] = summary.get("tokens_out", 0) + tokens_out


def write_manifest(project_root: Path, run_id: str, manifest: Dict[str, object]) -> Path:
    out = manifest_path(project_root, run_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + f".tmp.{os.getpid()}.{int(time.time() * 1e6)}")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=False), encoding="utf-8")
    os.replace(str(tmp), str(out))
    return out


def read_manifest(project_root: Path, run_id: str) -> Optional[Dict[str, object]]:
    p = manifest_path(project_root, run_id)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
