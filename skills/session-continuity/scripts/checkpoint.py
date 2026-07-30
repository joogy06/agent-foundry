#!/usr/bin/env python3
"""checkpoint.py — S074. Prompt the degradation check; never declare the verdict.

Measures what IS measurable about a session — elapsed time, checkpoint age, handover
freshness — and says when a check is due. It deliberately does not claim the session has
degraded, because it cannot know.

WHY IT ONLY PROMPTS

Elapsed time CORRELATES with degradation; it does not measure it. A session that stayed on
one task at 90 minutes may be fine; one that touched five unrelated tasks at 30 may not.
The reliable detector is a human noticing an answer got worse. A tool that announced
"quality is degraded" from a clock would be wrong often enough to be ignored — and then
ignored when it was right.

NO SCHEDULER REQUIRED

Designed for poll-on-use: run it from something already happening (a gate, a hook, a build
task). No cron, no daemon, no background process — enterprise environments frequently have
none of those, so the mechanism must not assume them.

Exit: 0 nothing due · 2 a checkpoint is due · 3 cannot write state.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_INTERVAL_MIN = 40
HANDOVER_STALE_MIN = 90


def now() -> datetime:
    return datetime.now(timezone.utc)


def age_minutes(ts: str) -> Optional[float]:
    try:
        return (now() - datetime.fromisoformat(ts)).total_seconds() / 60.0
    except (ValueError, TypeError):
        return None


def load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def evaluate(state: Dict[str, Any], interval_min: int, handover: Optional[Path]) -> Dict[str, Any]:
    prompts: List[Dict[str, str]] = []
    started = state.get("session_started_at")
    last_cp = state.get("last_checkpoint_at") or started
    session_age = age_minutes(started) if started else None
    since_cp = age_minutes(last_cp) if last_cp else None

    if session_age is None:
        prompts.append({"kind": "no_session_state",
                        "prompt": "no session start recorded — run `--start` when a working session begins"})
    else:
        if since_cp is not None and since_cp >= interval_min:
            prompts.append({"kind": "checkpoint_due",
                            "prompt": f"{since_cp:.0f} min since the last checkpoint (interval {interval_min}). "
                                      f"Update the handover, and compact if continuing the same task."})
        if session_age >= 120:
            prompts.append({"kind": "long_session",
                            "prompt": f"session has run {session_age/60:.1f} hours. Contradictions typically "
                                      f"appear around here — if it reverses an earlier decision, restart with a "
                                      f"handover rather than correcting and continuing."})
        elif session_age >= 60:
            prompts.append({"kind": "watch_for_vagueness",
                            "prompt": f"session has run {session_age:.0f} min. Watch for vagueness and "
                                      f"re-derivation — the first signals, and the cue to compact while "
                                      f"recall is still clear."})

    if handover:
        if not handover.exists():
            prompts.append({"kind": "no_handover",
                            "prompt": f"no handover at {handover} — write one BEFORE you need it; one "
                                      f"composed while degraded is degraded"})
        else:
            h_age = (now() - datetime.fromtimestamp(handover.stat().st_mtime, timezone.utc)).total_seconds() / 60.0
            if h_age >= HANDOVER_STALE_MIN:
                prompts.append({"kind": "handover_stale",
                                "prompt": f"handover is {h_age:.0f} min old — it no longer reflects the session"})

    return {
        "checked_at": now().isoformat(timespec="seconds"),
        "session_age_min": round(session_age, 1) if session_age is not None else None,
        "since_checkpoint_min": round(since_cp, 1) if since_cp is not None else None,
        "prompts": prompts,
        "action_due": bool(prompts),
        "note": ("These are PROMPTS TO CHECK, not a verdict. Elapsed time correlates with degradation "
                 "and does not measure it — the reliable detector is you noticing an answer got worse. "
                 "Content diversity matters as much as duration: several unrelated tasks degrade a "
                 "session faster than one long task, and argue for /clear rather than /compact."),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Prompt a session-degradation check. No scheduler needed.")
    ap.add_argument("--state", type=Path, default=Path(".foundry/session-continuity.json"))
    ap.add_argument("--handover", type=Path, default=None)
    ap.add_argument("--interval-min", type=int, default=DEFAULT_INTERVAL_MIN)
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--checkpoint", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    state = load(args.state)

    if args.start or args.checkpoint:
        stamp = now().isoformat(timespec="seconds")
        if args.start:
            state["session_started_at"] = stamp
        state["last_checkpoint_at"] = stamp
        state.setdefault("checkpoints", []).append(stamp)
        try:
            args.state.parent.mkdir(parents=True, exist_ok=True)
            args.state.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"CHECKPOINT_ENV_ERROR: {exc}\n")
            return 3
        print(f"{'SESSION STARTED' if args.start else 'CHECKPOINT RECORDED'} {stamp}")
        return 0

    r = evaluate(state, args.interval_min, args.handover)
    if args.json:
        print(json.dumps(r, indent=2))
    else:
        age = f"{r['session_age_min']:.0f} min" if r["session_age_min"] is not None else "unknown"
        print(f"SESSION CHECK — running {age}, {len(r['prompts'])} prompt(s)\n")
        for p in r["prompts"]:
            print(f"  [{p['kind']}]\n    {p['prompt']}\n")
        if not r["prompts"]:
            print("  nothing due\n")
        print(f"  {r['note']}")
    return 2 if r["action_due"] else 0


if __name__ == "__main__":
    sys.exit(main())
