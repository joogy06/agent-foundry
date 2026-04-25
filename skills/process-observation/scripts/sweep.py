#!/usr/bin/env python3
"""
sweep.py - retention sweep for .process-observations/active.yaml.

D12 MODIFIED semantics:
    - Entries with last_seen > 14 days ago -> demoted to stale.yaml (compressed: evidence_tail dropped).
    - Entries with status == "resolved" -> ALSO demoted to stale.yaml (NOT deleted).
    - stale.yaml grows indefinitely; no size limit.
    - Holds .sweep.lock (separate from .write.lock so writers never wait).
    - 24h sentinel .last_sweep prevents redundant work (unless --force).
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from write import (  # noqa: E402
    atomic_write_bytes, discover_project_root, dump_active,
    load_active, now_iso, parse_iso, sweep_lock, write_lock,
    SCHEMA_AGGREGATE, yaml,
)

ACTIVE_MAX_AGE_DAYS = 14
SENTINEL_STALENESS_HOURS = 24

STALE_COMPRESSED_KEEP_FIELDS = (
    "dedup_key", "category", "subject", "count", "count_last_7d",
    "first_seen", "last_seen", "status", "resolution", "severity",
    "what_happened", "promoted_to_task",
)


def _compress_for_stale(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Strip evidence_tail + sessions from a demoted entry."""
    out: Dict[str, Any] = {k: entry[k] for k in STALE_COMPRESSED_KEEP_FIELDS if k in entry}
    out.setdefault("demoted_at", now_iso())
    return out


def _load_stale(obs_dir: Path) -> Dict[str, Any]:
    path = obs_dir / "stale.yaml"
    if not path.is_file() or yaml is None:
        return {
            "schema": SCHEMA_AGGREGATE,
            "kind": "stale",
            "generated_at": now_iso(),
            "observations": {},
        }
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(doc, dict):
            return {"schema": SCHEMA_AGGREGATE, "kind": "stale", "generated_at": now_iso(), "observations": {}}
        doc.setdefault("schema", SCHEMA_AGGREGATE)
        doc.setdefault("kind", "stale")
        doc.setdefault("observations", {})
        if not isinstance(doc["observations"], dict):
            doc["observations"] = {}
        return doc
    except Exception as e:
        sys.stderr.write(f"SWEEP_STALE_LOAD_FAIL: {e}\n")
        return {"schema": SCHEMA_AGGREGATE, "kind": "stale", "generated_at": now_iso(), "observations": {}}


def _dump_stale(obs_dir: Path, doc: Dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("pyyaml not installed")
    doc["generated_at"] = now_iso()
    doc["observations"] = dict(sorted((doc.get("observations") or {}).items()))
    payload = yaml.safe_dump(doc, sort_keys=True, allow_unicode=True, default_flow_style=False)
    atomic_write_bytes(obs_dir / "stale.yaml", payload.encode("utf-8"))


def _sentinel_fresh(obs_dir: Path) -> bool:
    sentinel = obs_dir / ".last_sweep"
    if not sentinel.is_file():
        return False
    age = datetime.now(timezone.utc).timestamp() - sentinel.stat().st_mtime
    return age < SENTINEL_STALENESS_HOURS * 3600


def _touch_sentinel(obs_dir: Path) -> None:
    sentinel = obs_dir / ".last_sweep"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text(now_iso())


def run_sweep(project_root: Path, *, force: bool = False,
              max_age_days: int = ACTIVE_MAX_AGE_DAYS) -> Dict[str, int]:
    """Perform the sweep. Returns {demoted_age, demoted_resolved, retained}."""
    obs_dir = project_root / ".process-observations"
    obs_dir.mkdir(parents=True, exist_ok=True)

    if not force and _sentinel_fresh(obs_dir):
        return {"demoted_age": 0, "demoted_resolved": 0, "retained": -1, "skipped": 1}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)

    demoted_age = 0
    demoted_resolved = 0
    retained = 0

    # Hold .sweep.lock during stale.yaml reading/writing, .write.lock during
    # active.yaml mutation. The two locks are independent so hot writes are
    # not blocked by sweep.
    with sweep_lock(obs_dir):
        stale_doc = _load_stale(obs_dir)
        with write_lock(obs_dir):
            active_doc = load_active(obs_dir, project_root.name)
            kept: Dict[str, Any] = {}
            for key, entry in (active_doc.get("observations") or {}).items():
                try:
                    last_s = parse_iso(entry["last_seen"])
                except Exception:
                    retained += 1
                    kept[key] = entry
                    continue
                is_aged = last_s < cutoff
                is_resolved = entry.get("status") == "resolved"
                if is_aged or is_resolved:
                    # Compress + merge into stale (overwrite on dedup_key match)
                    stale_doc.setdefault("observations", {})[key] = _compress_for_stale(entry)
                    if is_resolved and not is_aged:
                        demoted_resolved += 1
                    else:
                        demoted_age += 1
                else:
                    kept[key] = entry
                    retained += 1
            active_doc["observations"] = kept
            dump_active(obs_dir, active_doc)
        _dump_stale(obs_dir, stale_doc)
        _touch_sentinel(obs_dir)

    return {
        "demoted_age": demoted_age,
        "demoted_resolved": demoted_resolved,
        "retained": retained,
        "skipped": 0,
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="process-observation-sweep",
                                     description="Sweep age-out and resolved observations into stale.yaml.")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--force", action="store_true", help="ignore .last_sweep sentinel")
    parser.add_argument("--max-age-days", type=int, default=ACTIVE_MAX_AGE_DAYS)
    ns = parser.parse_args(argv)
    if ns.project_root:
        root = Path(ns.project_root).resolve()
    else:
        root = discover_project_root()
        if root is None:
            sys.stderr.write("SWEEP: no project root found\n")
            return 3
    result = run_sweep(root, force=ns.force, max_age_days=ns.max_age_days)
    import json
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
