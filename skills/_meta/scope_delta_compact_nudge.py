#!/usr/bin/env python3
"""scope_delta_compact_nudge.py — SessionStart auto-compaction hook (design §B).

Conservative, self-limiting auto-trigger for scope-delta retention. Runs
`compact_ledger(apply=True)` ONLY when the active-undecided count exceeds a
threshold (default 200) AND only ever touches records older than 30 days. On a
healthy ledger it is SILENT and does nothing — it never surprises, never removes
resolved/referenced records (the compaction policy itself guarantees that).

Shape mirrors the existing SessionStart freshness hook
(`~/.claude/skills/_meta/freshness_nudge.py`):
  * `--hook` emits a SessionStart hook JSON envelope on stdout (the wired path).
  * Bare invocation prints a human-readable line (or "(silent)").
  * Drains stdin so it never blocks the hook protocol.
  * NEVER raises to the caller — any internal failure emits the benign silent
    envelope and exits 0.
  * Fast: reads the small per-record YAMLs once via scope_delta.read_records;
    typical <~50ms on a healthy ledger (it early-exits without scanning when the
    directory is small).

Threshold logic:
  * If active-undecided count <= THRESHOLD → SILENT no-op.
  * Else → compact_ledger(apply=True): only >30-day undecided records are
    removed; resolved/referenced records are always kept; archive summary is
    written to .ledger/scope-deltas-archive/compact-<date>.json.

CLI:
  scope_delta_compact_nudge.py --hook   # SessionStart hook JSON (wired path)
  scope_delta_compact_nudge.py          # human-readable result line
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Defaults (design §B): auto-fire only above 200 active-undecided; only touch
# records older than 30 days. Both are conservative-by-construction.
ACTIVE_UNDECIDED_THRESHOLD = 200
UNDECIDED_MAX_AGE_DAYS = 30

# Locate scope_delta.py. Prefer the synced canonical copy under ~/.claude; fall
# back to a repo-relative path so the hook also works pre-sync / in-tree.
_HOME = Path(os.environ.get("HOME", str(Path.home())))
_CANDIDATE_META_DIRS = [
    _HOME / ".claude" / "skills" / "_meta",
    Path(__file__).resolve().parent.parent / "skills" / "_meta",
]


def _load_scope_delta():
    for d in _CANDIDATE_META_DIRS:
        if (d / "scope_delta.py").is_file():
            if str(d) not in sys.path:
                sys.path.insert(0, str(d))
            import scope_delta  # noqa: E402

            return scope_delta
    return None


def _project_root() -> Path:
    """The project the session started in. The hook runs from CWD."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))


def run() -> str | None:
    """Return a human-readable result line, or None if silent (no action)."""
    try:
        sd = _load_scope_delta()
        if sd is None:
            return None
        project_root = _project_root()
        sdir = project_root / ".ledger" / "scope-deltas"
        if not sdir.is_dir():
            return None
        # Count active-undecided cheaply (read_records is the only authoritative
        # reader; the directory is the thing we are trying to bound, so a quick
        # status-filtered pass is acceptable and only happens at session start).
        undecided = sd.read_records(project_root, status_filter="undecided")
        if len(undecided) <= ACTIVE_UNDECIDED_THRESHOLD:
            return None  # healthy ledger — SILENT no-op
        plan = sd.compact_ledger(
            project_root,
            undecided_max_age_days=UNDECIDED_MAX_AGE_DAYS,
            apply=True,
        )
        if plan.get("compacted_count", 0) <= 0:
            # Over threshold but nothing is old enough yet — stay silent.
            return None
        return (
            f"[scope-delta] auto-compacted {plan['compacted_count']} stale "
            f"undecided records (>{UNDECIDED_MAX_AGE_DAYS}d); "
            f"{plan['kept_count']} kept · archive {plan.get('archive_path')}"
        )
    except Exception:  # noqa: BLE001 — best-effort; never break a session
        return None


def emit_hook(line: str | None) -> None:
    if line:
        out = {
            "continue": True,
            "suppressOutput": True,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": line,
            },
        }
    else:
        out = {"continue": True, "suppressOutput": True}
    sys.stdout.write(json.dumps(out))
    sys.stdout.write("\n")


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    # Drain stdin if piped (hook protocol) so we never block.
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:
        pass

    hook_mode = "--hook" in argv
    try:
        line = run()
        if hook_mode:
            emit_hook(line)
        else:
            print(line if line else "(silent — nothing to compact)")
        return 0
    except Exception:  # noqa: BLE001 — never break a session
        if hook_mode:
            sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}) + "\n")
        else:
            print("(silent — compact-nudge error)")
        return 0


if __name__ == "__main__":
    from portable_cli import run_cli          # #251 — see portable_cli.py
    sys.exit(run_cli(main))
