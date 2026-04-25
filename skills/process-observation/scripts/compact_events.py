#!/usr/bin/env python3
"""
compact_events.py - compress events-<YYYY-MM-DD>.jsonl files older than 30 days
into monthly hashed summaries at summaries/<YYYY-MM>.jsonl.

Per design section 4.5 (D12 MODIFIED):
    - Each summary line: {count, first_seen_of_month, last_seen_of_month,
                          distinct_sessions_count, evidence_shape, dedup_key, category, month}
    - Summaries themselves age out at 180 days (deleted by rotate_and_age.sh).
"""

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from write import discover_project_root  # noqa: E402

RAW_MAX_AGE_DAYS = 30
DATE_FILE_RE = re.compile(r"^events-(\d{4}-\d{2}-\d{2})\.jsonl$")
SUMMARY_MAX_AGE_DAYS = 180


def _normalize_for_shape(text: str) -> str:
    """Reduce free-form text to a stable shape hash (strip paths, ids, numbers)."""
    t = re.sub(r"/[\w./-]+", "<path>", text or "")
    t = re.sub(r"\b\d+\b", "<N>", t)
    t = re.sub(r"[0-9a-f]{8,}", "<hash>", t)
    return t[:240]


def _parse_date_from_filename(name: str) -> Optional[datetime]:
    m = DATE_FILE_RE.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _read_jsonl(path: Path):
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except FileNotFoundError:
        return


def compact_events(project_root: Path, *, max_age_days: int = RAW_MAX_AGE_DAYS) -> Dict[str, int]:
    """Compact old daily event files. Returns {files_compacted, summaries_written, files_deleted}."""
    obs_dir = project_root / ".process-observations"
    summaries_dir = obs_dir / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    files_compacted = 0
    files_deleted = 0
    summaries_written = 0

    # (month, dedup_key) -> aggregated counters
    Agg = Dict[str, Any]
    per_month: Dict[str, Dict[str, Agg]] = defaultdict(dict)
    source_files_by_month: Dict[str, List[Path]] = defaultdict(list)

    for candidate in sorted(obs_dir.glob("events-*.jsonl")):
        if candidate.name == "events.jsonl":
            continue
        d = _parse_date_from_filename(candidate.name)
        if d is None or d >= cutoff:
            continue
        month_key = d.strftime("%Y-%m")
        source_files_by_month[month_key].append(candidate)
        files_compacted += 1
        for ev in _read_jsonl(candidate):
            key = ev.get("dedup_key") or ""
            if not key:
                continue
            month_bucket = per_month[month_key].setdefault(key, {
                "dedup_key": key,
                "category": ev.get("category"),
                "month": month_key,
                "count": 0,
                "first_seen_of_month": ev.get("ts"),
                "last_seen_of_month": ev.get("ts"),
                "distinct_sessions": set(),
                "shape_inputs": [],
            })
            month_bucket["count"] += 1
            ts = ev.get("ts")
            if ts:
                if ts < (month_bucket["first_seen_of_month"] or ts):
                    month_bucket["first_seen_of_month"] = ts
                if ts > (month_bucket["last_seen_of_month"] or ""):
                    month_bucket["last_seen_of_month"] = ts
            sid = ev.get("session_id")
            if sid:
                month_bucket["distinct_sessions"].add(sid)
            wh = ev.get("what_happened") or ""
            if wh and len(month_bucket["shape_inputs"]) < 5:
                month_bucket["shape_inputs"].append(wh)

    for month, buckets in per_month.items():
        out_path = summaries_dir / f"{month}.jsonl"
        # Append-only: merge with any existing summaries for that month
        existing: Dict[str, Dict[str, Any]] = {}
        if out_path.is_file():
            for prior in _read_jsonl(out_path):
                k = prior.get("dedup_key")
                if k:
                    existing[k] = prior
        for key, agg in buckets.items():
            shape_text = " | ".join(_normalize_for_shape(s) for s in agg["shape_inputs"])
            evidence_shape = hashlib.sha256(shape_text.encode("utf-8")).hexdigest()[:16]
            summary_line = {
                "schema": "observation-summary.v1",
                "dedup_key": agg["dedup_key"],
                "category": agg["category"],
                "month": agg["month"],
                "count": agg["count"],
                "first_seen_of_month": agg["first_seen_of_month"],
                "last_seen_of_month": agg["last_seen_of_month"],
                "distinct_sessions_count": len(agg["distinct_sessions"]),
                "evidence_shape": evidence_shape,
            }
            # Merge with prior (incremental compact same month)
            if key in existing:
                prior = existing[key]
                summary_line["count"] += int(prior.get("count") or 0)
                summary_line["first_seen_of_month"] = min(
                    prior.get("first_seen_of_month") or summary_line["first_seen_of_month"],
                    summary_line["first_seen_of_month"],
                )
                summary_line["last_seen_of_month"] = max(
                    prior.get("last_seen_of_month") or summary_line["last_seen_of_month"],
                    summary_line["last_seen_of_month"],
                )
                summary_line["distinct_sessions_count"] = max(
                    prior.get("distinct_sessions_count") or 0,
                    summary_line["distinct_sessions_count"],
                )
            existing[key] = summary_line

        # Rewrite summary file (dedup by dedup_key, stable ordering)
        lines = [json.dumps(v, sort_keys=True, separators=(",", ":")) + "\n"
                 for _, v in sorted(existing.items())]
        out_path.write_text("".join(lines), encoding="utf-8")
        summaries_written += len(buckets)

    # Delete the source files that contributed (after summaries committed)
    for _, files in source_files_by_month.items():
        for f in files:
            try:
                f.unlink()
                files_deleted += 1
            except FileNotFoundError:
                pass

    # Age out summaries older than SUMMARY_MAX_AGE_DAYS
    summary_cutoff = datetime.now(timezone.utc) - timedelta(days=SUMMARY_MAX_AGE_DAYS)
    for s in summaries_dir.glob("*.jsonl"):
        try:
            mtime = datetime.fromtimestamp(s.stat().st_mtime, tz=timezone.utc)
            if mtime < summary_cutoff:
                s.unlink()
        except Exception:
            continue

    return {
        "files_compacted": files_compacted,
        "summaries_written": summaries_written,
        "files_deleted": files_deleted,
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="process-observation-compact-events",
                                     description="Compact old events-*.jsonl into summaries/<month>.jsonl.")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--max-age-days", type=int, default=RAW_MAX_AGE_DAYS)
    ns = parser.parse_args(argv)
    if ns.project_root:
        root = Path(ns.project_root).resolve()
    else:
        root = discover_project_root()
        if root is None:
            sys.stderr.write("COMPACT: no project root found\n")
            return 3
    result = compact_events(root, max_age_days=ns.max_age_days)
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
