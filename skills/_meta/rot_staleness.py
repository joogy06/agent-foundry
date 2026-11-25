#!/usr/bin/env python3
"""rot_staleness.py - how old is the rot report, and is that an alarm?

The rot scan (`rot_scan.py`) is only as good as its last run. In 2026 the report sat 60 days
old: the freshness sweep that refreshes it had stopped, and a skill created after the last
run (`markdown-for-agents`) was never scanned at all. The SessionStart digest said only "rot
scan stale", with no age, so nothing distinguished a week from two months.

This module gives the digest an age and a threshold. The age comes from the report's own
`generated_at` (what the scan says about itself). A report that is not a valid successful scan
is never fresh, whatever its mtime: its age is the newest success in rot-history.jsonl. Pure and stdlib-only; it reads nothing the caller has not handed it
except the mtime, so it stays inside the digest's latency budget.

    python3 rot_staleness.py [--report PATH]   # print the segment, or nothing when fresh
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

#: The rot report is refreshed by the freshness sweep past 7 days (sweep-cadence.md).
STALE_DAYS = 7
#: Twice the refresh cadence: the sweep has missed at least one run. An alarm, not a note.
ALARM_DAYS = 14
REFRESH_HINT = "python3 ~/.claude/skills/_meta/rot_scan.py --refresh"
HISTORY_TAIL_BYTES = 64 << 10   # the digest stays inside its latency budget


def _default_report() -> Path:
    home = os.environ.get("HOME") or str(Path.home())
    return Path(home) / ".claude" / "state" / "freshness" / "rot-report.json"


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _last_success_age(history: Path, now: datetime) -> float | None:
    """Age in days of the newest successful run in rot-history.jsonl (bounded tail read)."""
    try:
        with open(history, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - HISTORY_TAIL_BYTES))
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    best = None
    for line in tail.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("last_success") is True:
            ts = _parse_ts(row.get("generated_at"))
            if ts is not None and (best is None or ts > best):
                best = ts
    return None if best is None else max(0.0, (now - best).total_seconds() / 86400)


def report_age_days(report: dict | None, path: Path, now: datetime) -> float | None:
    """Age in days from `generated_at`, else from the file mtime; None when neither exists."""
    ts = _parse_ts(report.get("generated_at")) if isinstance(report, dict) else None
    if ts is None:
        try:
            ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return None
    return max(0.0, (now - ts).total_seconds() / 86400)


def _grade(age: float, prefix: str) -> str | None:
    days = int(age)
    if age > ALARM_DAYS:
        return (f"{prefix}rot-report {days} days old [ALARM >{ALARM_DAYS}d: skills added since "
                f"are unscanned] — run {REFRESH_HINT}")
    if age > STALE_DAYS:
        return f"{prefix}rot scan stale ({days} days old)"
    return None


def _valid_success(report) -> bool:
    """A report the digest may call fresh: an object that says it succeeded and when."""
    return (isinstance(report, dict) and report.get("last_success") is True
            and _parse_ts(report.get("generated_at")) is not None)


def segment(report, path: Path, now: datetime,
            history: Path | None = None) -> str | None:
    """The digest segment, or None when the last scan succeeded within STALE_DAYS.

    Only a valid successful report (an object with `last_success: true` and a parseable
    `generated_at`) can be fresh. Anything else - a failed scan, or a report that is
    unparseable, null, empty or the wrong shape - is never fresh, however new its mtime: its
    age is the age of the newest successful run in rot-history.jsonl, and with none on record it
    is an alarm. A missing report is a note: the scan has never run here, so nothing is being
    checked.
    """
    history = history or path.parent / "rot-history.jsonl"
    if report is None and not path.exists():
        return f"rot-report missing: no rot scan on record — run {REFRESH_HINT}"
    if not _valid_success(report):
        failed = isinstance(report, dict) and report.get("last_success") is False
        reason = "last rot scan failed" if failed else "rot-report invalid (not a successful scan)"
        age = _last_success_age(history, now)
        if age is None:
            return (f"{reason} and no successful scan is on record [ALARM] — "
                    f"run {REFRESH_HINT}")
        return (_grade(age, f"{reason}; ")
                or f"{reason} (last success {int(age)} days ago) — run {REFRESH_HINT}")
    return _grade(report_age_days(report, path, now), "")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="rot report age check")
    p.add_argument("--report")
    a = p.parse_args(argv)
    path = Path(a.report) if a.report else _default_report()
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        report = None
    seg = segment(report, path, datetime.now(timezone.utc))
    if seg:
        print(seg)
    return 0


if __name__ == "__main__":
    from portable_cli import run_cli  # noqa: E402  (#251 stream hardening; sibling module)
    raise SystemExit(run_cli(main))
