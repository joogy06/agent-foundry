#!/usr/bin/env python3
"""
query.py - process-observation query tool.

Operations:
    hot --threshold=N --window=7d --min-severity=<level>
    stats
    subject:<id>
    category:<name>
    session:<id>
    since:<iso_date>

All output is canonical JSON (sorted keys, compact) on stdout.

Severity-keyed thresholds per design section 4.10:
    blocking=2, degraded=5, slow=10, noisy=20
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from write import (  # noqa: E402
    discover_project_root,
    load_active,
    parse_iso,
    CLOSED_SET_SEVERITIES,
)

SEVERITY_DEFAULT_THRESHOLDS: Dict[str, int] = {
    "blocking": 2,
    "degraded": 5,
    "slow": 10,
    "noisy": 20,
}

SEVERITY_ORDER: Dict[str, int] = {"noisy": 0, "slow": 1, "degraded": 2, "blocking": 3}


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _obs_dir(project_root: Path) -> Path:
    return project_root / ".process-observations"


def _load(project_root: Path) -> Dict[str, Any]:
    return load_active(_obs_dir(project_root), project_root.name)


def _parse_window(raw: str) -> int:
    """Parse '7d' / '24h' / '60m' / '3600s' -> seconds."""
    raw = raw.strip().lower()
    if raw.endswith("d"):
        return int(raw[:-1]) * 86400
    if raw.endswith("h"):
        return int(raw[:-1]) * 3600
    if raw.endswith("m"):
        return int(raw[:-1]) * 60
    if raw.endswith("s"):
        return int(raw[:-1])
    return int(raw)


def op_hot(project_root: Path, *, threshold: Optional[int], window_s: int,
           min_severity: str) -> List[Dict[str, Any]]:
    """Return observations that exceed severity-keyed thresholds within window."""
    doc = _load(project_root)
    min_rank = SEVERITY_ORDER.get(min_severity, 2)
    now = datetime.now(timezone.utc).timestamp()
    hot: List[Dict[str, Any]] = []
    for key, entry in (doc.get("observations") or {}).items():
        sev = entry.get("severity") or "degraded"
        if SEVERITY_ORDER.get(sev, 1) < min_rank:
            continue
        # Only exclude already-promoted observations
        if entry.get("promoted_to_task"):
            continue
        # last_seen within window
        try:
            last_s = parse_iso(entry["last_seen"]).timestamp()
        except Exception:
            continue
        if now - last_s > window_s:
            continue
        # Threshold: explicit --threshold OR severity-keyed default
        sev_threshold = threshold if threshold is not None else SEVERITY_DEFAULT_THRESHOLDS.get(sev, 5)
        count_7d = int(entry.get("count_last_7d") or entry.get("count") or 0)
        if count_7d >= sev_threshold:
            hot.append(entry)
    # Sort by severity rank (desc) then count_last_7d (desc) for stability
    hot.sort(key=lambda e: (-SEVERITY_ORDER.get(e.get("severity"), 1),
                             -int(e.get("count_last_7d") or 0), e.get("dedup_key") or ""))
    return hot


def op_stats(project_root: Path) -> Dict[str, Any]:
    doc = _load(project_root)
    obs = doc.get("observations") or {}
    by_cat: Dict[str, int] = {}
    by_sev: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    total_count = 0
    for entry in obs.values():
        total_count += int(entry.get("count") or 0)
        by_cat[entry.get("category") or "unknown"] = by_cat.get(entry.get("category") or "unknown", 0) + 1
        by_sev[entry.get("severity") or "unknown"] = by_sev.get(entry.get("severity") or "unknown", 0) + 1
        by_status[entry.get("status") or "open"] = by_status.get(entry.get("status") or "open", 0) + 1
    return {
        "aggregate_count": len(obs),
        "total_event_count": total_count,
        "by_category": dict(sorted(by_cat.items())),
        "by_severity": dict(sorted(by_sev.items())),
        "by_status": dict(sorted(by_status.items())),
    }


def op_filter(project_root: Path, *, subject: Optional[str] = None,
              category: Optional[str] = None, session: Optional[str] = None,
              since_iso: Optional[str] = None) -> List[Dict[str, Any]]:
    doc = _load(project_root)
    since_s = None
    if since_iso:
        try:
            since_s = parse_iso(
                since_iso if "T" in since_iso else since_iso + "T00:00:00Z"
            ).timestamp()
        except Exception:
            since_s = None
    out: List[Dict[str, Any]] = []
    for entry in (doc.get("observations") or {}).values():
        if subject is not None and (entry.get("subject") or {}).get("id") != subject:
            continue
        if category is not None and entry.get("category") != category:
            continue
        if session is not None and session not in (entry.get("sessions") or []):
            continue
        if since_s is not None:
            try:
                ls = parse_iso(entry["last_seen"]).timestamp()
            except Exception:
                continue
            if ls < since_s:
                continue
        out.append(entry)
    out.sort(key=lambda e: (e.get("last_seen") or "", e.get("dedup_key") or ""), reverse=True)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_project_root(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).resolve()
    found = discover_project_root()
    if found is None:
        sys.stderr.write("QUERY: no project root found (cwd or --project-root)\n")
        sys.exit(3)
    return found


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="process-observation-query",
        description="Query the .process-observations ledger (canonical-JSON output).",
    )
    parser.add_argument("op", help="hot | stats | subject:<id> | category:<name> | session:<id> | since:<iso>")
    parser.add_argument("--threshold", type=int, default=None)
    parser.add_argument("--window", default="7d")
    parser.add_argument("--min-severity", default="degraded", choices=list(CLOSED_SET_SEVERITIES))
    parser.add_argument("--project-root", default=None)
    ns = parser.parse_args(argv)

    project_root = _resolve_project_root(ns.project_root)
    window_s = _parse_window(ns.window)

    op = ns.op
    if op == "hot":
        result = op_hot(
            project_root,
            threshold=ns.threshold,
            window_s=window_s,
            min_severity=ns.min_severity,
        )
    elif op == "stats":
        result = op_stats(project_root)
    elif op.startswith("subject:"):
        result = op_filter(project_root, subject=op[len("subject:"):])
    elif op.startswith("category:"):
        result = op_filter(project_root, category=op[len("category:"):])
    elif op.startswith("session:"):
        result = op_filter(project_root, session=op[len("session:"):])
    elif op.startswith("since:"):
        result = op_filter(project_root, since_iso=op[len("since:"):])
    else:
        sys.stderr.write(f"QUERY_UNKNOWN_OP: {op!r}\n")
        return 2

    sys.stdout.write(_canon(result))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
