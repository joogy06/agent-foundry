#!/usr/bin/env python3
"""refresh_awacy.py - rebuild data/awacy-snapshot.json from Are We Anti-Cheat Yet.

The anti-cheat game list goes stale weekly, so it is data, never rules. This
script downloads (or reads) AWACY's games.json, keeps only each game's name
and status, stamps the snapshot with as_of, and writes it atomically.
pc_check.py warns when the snapshot is older than stale_after_days (30) and
blocks --final after block_after_days (60).

Usage:
    python3 refresh_awacy.py                      # download, write data/awacy-snapshot.json
    python3 refresh_awacy.py --input games.json   # offline, from a saved download
    python3 refresh_awacy.py --output FILE --today YYYY-MM-DD --min-games N

Exit codes: 0 written, 3 bad or suspicious input (nothing written).
Standard library only.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

SOURCE_URL = "https://raw.githubusercontent.com/AreWeAntiCheatYet/AreWeAntiCheatYet/HEAD/games.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "data" / "awacy-snapshot.json"
KNOWN_STATUSES = {"Supported", "Running", "Broken", "Denied", "Planned"}
MIN_GAMES = 500  # a real download holds ~1,100; far fewer means a truncated or changed feed


class BadInput(Exception):
    pass


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pc-builder-refresh-awacy"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def trim(raw: bytes, today: str, min_games: int) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BadInput(f"not JSON: {e}") from e
    if not isinstance(data, list):
        raise BadInput("expected a JSON list of games")
    games = []
    for i, g in enumerate(data):
        if not isinstance(g, dict) or not isinstance(g.get("name"), str) or not isinstance(g.get("status"), str):
            raise BadInput(f"entry {i} has no string name/status")
        if g["status"] not in KNOWN_STATUSES:
            raise BadInput(f"entry {i} ({g['name']!r}) has an unknown status {g['status']!r}; update KNOWN_STATUSES "
                           "and the checker's status classes together")
        games.append({"name": g["name"], "status": g["status"]})
    if len(games) < min_games:
        raise BadInput(f"only {len(games)} games (expected at least {min_games}); refusing to overwrite the snapshot")
    return {
        "schema": "awacy-snapshot.v1",
        "source_url": SOURCE_URL,
        "as_of": today,
        "stale_after_days": 30,
        "block_after_days": 60,
        "note": "Trimmed copy of Are We Anti-Cheat Yet games.json (name and status only). Regenerate with "
                "scripts/refresh_awacy.py; never edit by hand and never copy the list into rules.",
        "counts": dict(sorted(collections.Counter(g["status"] for g in games).items())),
        "games": games,
    }


def write_atomic(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, indent=1, ensure_ascii=True)
            f.write("\n")
        os.chmod(tmp, 0o644)  # mkstemp creates 0600; the snapshot is shared data
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rebuild the AWACY anti-cheat snapshot.")
    ap.add_argument("--input", help="a saved games.json (default: download from AWACY)")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    ap.add_argument("--today", help="as_of date (default: today)")
    ap.add_argument("--min-games", type=int, default=MIN_GAMES)
    args = ap.parse_args(argv)
    try:
        today = args.today or datetime.date.today().isoformat()
        datetime.date.fromisoformat(today)
        raw = Path(args.input).read_bytes() if args.input else fetch(SOURCE_URL)
        snap = trim(raw, today, args.min_games)
        write_atomic(Path(args.output), snap)
    except (OSError, ValueError, BadInput) as e:
        sys.stderr.write(f"refresh_awacy: {e}\n")
        return 3
    sys.stdout.write(f"refresh_awacy: wrote {len(snap['games'])} games, as_of {snap['as_of']}: "
                     f"{', '.join(f'{k} {v}' for k, v in snap['counts'].items())}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
