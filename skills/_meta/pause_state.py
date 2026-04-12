#!/usr/bin/env python3
"""
pause_state.py — Bob's freeze-the-world pause state machine.

Implements the persisted state machine from spec section 12 (CB5 fix):
NORMAL -> PAUSE_REQUESTED -> PAUSED -> MAP_UPDATING -> RESUMING -> NORMAL
                                           |
                                           v
                                       ROLLBACK -> NORMAL

State is persisted to .ledger/pause-state.yaml so a bob crash mid-pause can be
recovered. Each state has a wall-clock timeout; exceeding the timeout triggers
ROLLBACK rather than indefinite wait. By default, RESUMING force-restarts any
WP whose component was modified by the map update — reconcile_delta() is no
longer trusted blindly.

Public API:
    request_pause(project_root, gap, requesting_wp) -> str  (epoch as str)
    acknowledge_pause(project_root, wp_id) -> None
    transition_to(project_root, new_state, **kwargs) -> None
    current_state(project_root) -> dict | None
    recover_pause_state(project_root) -> str  (action taken: 'none'|'resumed'|'rolled_back')

CLI:
    python -m pause_state status [--project-root <dir>]
    python -m pause_state recover [--project-root <dir>]

Provenance: spec section 12. Critical invariants enforced: CB5.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    sys.stderr.write("FATAL: pyyaml not installed.\n")
    sys.exit(3)


# ---------------------------------------------------------------------------
# State definitions
# ---------------------------------------------------------------------------

STATES = ("NORMAL", "PAUSE_REQUESTED", "PAUSED", "MAP_UPDATING", "RESUMING", "ROLLBACK")

# Per-state timeouts in seconds — section 12.2
STATE_TIMEOUT_SECONDS: Dict[str, int] = {
    "PAUSE_REQUESTED": 30,         # all teams must ack within 30s
    "PAUSED": 600,                 # 10 min for forge to gather gaps and start updating
    "MAP_UPDATING": 900,           # 15 min for forge to produce a valid update
    "RESUMING": 1800,              # 30 min for bob to issue fresh claims
    "ROLLBACK": 300,               # 5 min for rollback to complete
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def state_timeout(state: str) -> int:
    return STATE_TIMEOUT_SECONDS.get(state, 600)


# ---------------------------------------------------------------------------
# State file I/O
# ---------------------------------------------------------------------------


def _state_path(project_root: Path) -> Path:
    return project_root / ".ledger" / "pause-state.yaml"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(content)
    os.replace(str(tmp), str(path))


def current_state(project_root: Path) -> Optional[Dict[str, Any]]:
    p = _state_path(project_root)
    if not p.is_file():
        return None
    try:
        return yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError:
        return {"state": "CORRUPT", "raw": p.read_text()}


def _write_state(project_root: Path, state: Dict[str, Any]) -> None:
    state.setdefault("entered_state_at", now_iso())
    state.setdefault("epoch", 1)
    _atomic_write(_state_path(project_root), yaml.safe_dump(state, sort_keys=True))


def _bump_epoch(project_root: Path) -> int:
    cur = current_state(project_root) or {}
    return int(cur.get("epoch", 0)) + 1


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


def request_pause(project_root: Path, gap: Dict[str, Any], requesting_wp: str) -> str:
    """Bob calls this when a team reports a gap.

    Transitions NORMAL -> PAUSE_REQUESTED. Records the gap and which WP triggered it.
    Returns the new pause epoch as a string.
    """
    cur = current_state(project_root)
    if cur and cur.get("state") not in (None, "NORMAL"):
        # Queue this gap onto the existing pause; do not start a new one
        existing = cur.setdefault("queued_gaps", [])
        existing.append({"requesting_wp": requesting_wp, "gap": gap})
        _write_state(project_root, cur)
        return str(cur.get("epoch", 1))

    epoch = _bump_epoch(project_root)
    state: Dict[str, Any] = {
        "epoch": epoch,
        "state": "PAUSE_REQUESTED",
        "entered_state_at": now_iso(),
        "requesting_wp": requesting_wp,
        "gaps_collected": [gap],
        "teams_pending": [],   # bob populates this with in-flight team ids
        "teams_acked": [],
        "queued_gaps": [],
        "pause_lock_held_by_pid": os.getpid(),
    }
    _write_state(project_root, state)
    return str(epoch)


def acknowledge_pause(project_root: Path, wp_id: str) -> None:
    """A team WP acknowledges that it has paused itself. Bob calls this."""
    cur = current_state(project_root) or {}
    if cur.get("state") != "PAUSE_REQUESTED":
        return
    pending = cur.setdefault("teams_pending", [])
    acked = cur.setdefault("teams_acked", [])
    if wp_id in pending:
        pending.remove(wp_id)
    if wp_id not in acked:
        acked.append(wp_id)
    if not pending:
        # All teams acked; transition to PAUSED
        cur["state"] = "PAUSED"
        cur["entered_state_at"] = now_iso()
    _write_state(project_root, cur)


def transition_to(project_root: Path, new_state: str, **kwargs: Any) -> None:
    """Bob explicitly transitions the state machine. kwargs are merged into state."""
    if new_state not in STATES:
        raise ValueError(f"unknown state: {new_state}")
    cur = current_state(project_root) or {}
    cur["state"] = new_state
    cur["entered_state_at"] = now_iso()
    cur.update(kwargs)
    _write_state(project_root, cur)


def clear_pause_state(project_root: Path) -> None:
    """Terminal: NORMAL means we've returned to normal operation. Delete the state file."""
    p = _state_path(project_root)
    if p.is_file():
        p.unlink()


def is_timed_out(state: Dict[str, Any]) -> bool:
    s = state.get("state")
    if s not in STATE_TIMEOUT_SECONDS:
        return False
    entered_at = state.get("entered_state_at")
    if not entered_at:
        return False
    try:
        elapsed = (datetime.now(timezone.utc) - parse_iso(entered_at)).total_seconds()
    except ValueError:
        return False
    return elapsed > state_timeout(s)


def recover_pause_state(project_root: Path) -> str:
    """On bob startup: read pause-state.yaml and decide next action.

    Returns 'none' if no pause was in flight, 'rolled_back' if recovery rolled
    back a timed-out pause, 'resumed' if recovery picked up a still-valid pause.
    """
    cur = current_state(project_root)
    if not cur:
        return "none"
    s = cur.get("state")
    if s in (None, "NORMAL"):
        clear_pause_state(project_root)
        return "none"
    if s == "CORRUPT":
        # Fail safe: roll back
        cur["state"] = "ROLLBACK"
        cur["entered_state_at"] = now_iso()
        cur["rollback_reason"] = "corrupt state file on recovery"
        _write_state(project_root, cur)
        return "rolled_back"
    if is_timed_out(cur):
        cur["state"] = "ROLLBACK"
        cur["entered_state_at"] = now_iso()
        cur["rollback_reason"] = f"recovery: {s} exceeded timeout"
        _write_state(project_root, cur)
        return "rolled_back"
    # Still within budget — bob picks up where it left off
    return "resumed"


def affected_wps(state: Dict[str, Any]) -> List[str]:
    """Return WP ids affected by the current map update.

    By default in RESUMING, every WP whose component appears in the delta is
    force-restarted. The caller (bob) reads this list, sets each WP back to
    PLANNED, bumps generations, and re-issues claims.
    """
    delta = state.get("delta") or {}
    return list(delta.get("affected_wps") or [])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv
    if len(argv) < 2:
        sys.stderr.write("usage: pause_state.py status|recover [--project-root <dir>]\n")
        sys.exit(2)
    cmd = argv[1]
    project_root = Path(os.getcwd())
    i = 2
    while i < len(argv):
        if argv[i] == "--project-root":
            project_root = Path(argv[i + 1])
            i += 2
        else:
            i += 1
    if cmd == "status":
        cur = current_state(project_root)
        if cur is None:
            sys.stdout.write("NORMAL\n")
            return
        sys.stdout.write(f"state={cur.get('state')} epoch={cur.get('epoch')} timed_out={is_timed_out(cur)}\n")
    elif cmd == "recover":
        action = recover_pause_state(project_root)
        sys.stdout.write(action + "\n")
    else:
        sys.stderr.write(f"unknown command: {cmd}\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
