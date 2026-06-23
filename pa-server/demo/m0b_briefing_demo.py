#!/usr/bin/env python3
"""m0b_briefing_demo.py — a runnable, real-data AMY M0b briefing demo.

Seeds a REALISTIC workspace into a throwaway SQLite pa.db (the production schema
via pa_server.init_db) and composes the catch-up briefing through the REAL
routine-engine (pa_core.pa_brief), so a human can SEE the M0b routine engine
working end-to-end:

  * the urgency taxonomy ordering   (CONFLICT < OVERDUE_NUDGE < BLOCKER <
                                     DUE_TODAY < DELEGATION_FOLLOWUP < IN_FLIGHT
                                     < FYI);
  * the in-composer NUDGE DRAIN     (a due, repeatedly-deferred ingested nudge
                                     promoted + surfaced louder as OVERDUE_NUDGE);
  * the ROLE-LENS reweight          (within-urgency reorder per the workspace
                                     role_profile; membership invariant);
  * the FOLD                         (exactly 5 above the fold + a MANDATORY
                                     [+N more] affordance — nothing dropped);
  * remote-field DELIMITER WRAPPING  (a sync conflict_detail + an ingested nudge
                                     message stay <untrusted_remote_content>…
                                     wrapped end-to-end; the user's own blocker
                                     note is NOT wrapped).

This module carries ZERO business logic of its own — every behavior shown is the
production code path. It is imported by
``pa-server/tests/integration/test_m0b_real_data_demo.py`` (which asserts the
behaviors) and is directly runnable:

    cd pa-server && python3 demo/m0b_briefing_demo.py
    # or, deterministic clock:
    python3 demo/m0b_briefing_demo.py --now 2026-06-15T12:00:00

stdlib only — no new pip deps (AMY D-plus lock).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

# pa_core / pa_server live one directory up (pa-server/).
_PA_SERVER_ROOT = Path(__file__).resolve().parent.parent
if str(_PA_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_PA_SERVER_ROOT))

# A fixed default clock so the demo is reproducible (DUE_TODAY / drain windows).
DEFAULT_NOW = "2026-06-15T12:00:00"
TODAY = "2026-06-15"


def seed_realistic_workspace(conn, ws_id):
    """Seed a realistic Monday-morning catch-up: a remote sync conflict, a
    repeatedly-deferred ingested nudge, a critical blocker, today-due work, an
    owed delegation, in-flight work, and several FYI items — PLUS a Scrum
    role_profile so the role lens has a signal.

    All enums are VALID M0a values: status in
    ('new','designed','executing','blocked','done','failed','cancelled');
    priority in ('critical','high','medium','low'). Remote-authored fields are
    written RAW — the production read paths wrap them.
    """
    # --- CONFLICT (loudest): a sync conflict with a remote-authored detail. ---
    conn.execute(
        "INSERT INTO sync_state (workspace_id, source, remote_id, status, conflict_detail) "
        "VALUES (?, 'jira', 'ACME-204', 'conflict', ?)",
        (ws_id, "Reporter changed the acceptance criteria while you were away"),
    )

    # --- OVERDUE_NUDGE: an ingested (remote) nudge, due yesterday, snoozed 3x ---
    # (>= escalation threshold) so the drain promotes it AND escalates it.
    conn.execute(
        "INSERT INTO nudges (workspace_id, kind, message, source, due_at, "
        "snooze_until, snooze_count, state) "
        "VALUES (?, 'followup', ?, 'ingested', '2026-06-14T17:00:00', NULL, 3, 'pending')",
        (ws_id, "Vendor is still waiting on the signed MSA"),
    )

    # --- BLOCKER (critical): a locally-authored blocker note (NOT remote). ---
    conn.execute(
        "INSERT INTO blockers (workspace_id, description, severity, status) "
        "VALUES (?, 'Security review blocking the prod release', 'critical', 'active')",
        (ws_id,),
    )
    conn.execute(
        "INSERT INTO blockers (workspace_id, description, severity, status) "
        "VALUES (?, 'Staging env down — waiting on infra', 'high', 'active')",
        (ws_id,),
    )

    # --- DUE_TODAY: today-due active tasks. ---
    conn.execute(
        "INSERT INTO tasks (workspace_id, title, status, priority, due_at, tags) "
        "VALUES (?, 'Submit the Q2 board deck', 'executing', 'high', ?, ?)",
        (ws_id, TODAY + "T16:00:00", '["reporting"]'),
    )

    # --- DELEGATION_FOLLOWUP: an open delegation owed to me + one chased out. ---
    conn.execute(
        "INSERT INTO delegations (workspace_id, direction, status, expected_by) "
        "VALUES (?, 'owed_to_me', 'open', '2026-06-13T00:00:00')",
        (ws_id,),
    )
    conn.execute(
        "INSERT INTO delegations (workspace_id, direction, status, expected_by) "
        "VALUES (?, 'delegated_out', 'chased', '2026-06-12T00:00:00')",
        (ws_id,),
    )

    # --- IN_FLIGHT: executing tasks with no due date. ---
    conn.execute(
        "INSERT INTO tasks (workspace_id, title, status, priority, tags) "
        "VALUES (?, 'Refactor the sync adapter', 'executing', 'medium', ?)",
        (ws_id, '["platform"]'),
    )

    # --- FYI: non-due, non-executing active tasks. ---
    conn.execute(
        "INSERT INTO tasks (workspace_id, title, status, priority) "
        "VALUES (?, 'Review the new on-call rota', 'new', 'low')",
        (ws_id,),
    )
    conn.execute(
        "INSERT INTO tasks (workspace_id, title, status, priority) "
        "VALUES (?, 'Read the architecture RFC', 'new', 'low')",
        (ws_id,),
    )

    # --- role_profile: Scrum -> 'velocity' week-review framing (role-lens). ---
    conn.execute(
        "INSERT INTO role_profile (workspace_id, role_title, aims, responsibilities, "
        "methodology, escalation_threshold, tone) "
        "VALUES (?, 'Engineering Manager', 'ship the release', "
        "'unblock the team, manage stakeholders', 'Scrum', 'high', 'concise')",
        (ws_id,),
    )
    conn.commit()


def compose_demo_brief(workspace_path: Path, now: str | None = None) -> dict:
    """Build a pa.db at `workspace_path`, seed it realistically, and compose the
    briefing via the REAL routine-engine. Returns the pa_brief dict (brief_output).
    """
    import pa_core  # noqa: PLC0415
    import pa_server  # noqa: PLC0415

    db_path = workspace_path / "pa.db"
    conn = pa_server.init_db(db_path)
    try:
        ws_id = pa_core.workspace_id_from_path(workspace_path)
        pa_core.ensure_workspace(conn, ws_id, workspace_path.name, str(workspace_path))
        seed_realistic_workspace(conn, ws_id)
        params = {} if now is None else {"now": now}
        return pa_core.pa_brief(conn, ws_id, params)
    finally:
        conn.close()


def run_demo(now: str | None = None, workspace_path: Path | None = None) -> dict:
    """Compose the demo briefing in a temp workspace (or the given one) and
    return the brief_output dict. Used by both the CLI and the test."""
    if workspace_path is not None:
        workspace_path.mkdir(parents=True, exist_ok=True)
        return compose_demo_brief(workspace_path, now=now)
    with tempfile.TemporaryDirectory(prefix="amy-m0b-demo-") as td:
        ws = Path(td) / "acme-platform"
        ws.mkdir()
        return compose_demo_brief(ws, now=now)


def _print_report(brief: dict) -> None:
    """Print the rendered briefing + a short explanation of what each line is."""
    print("=" * 64)
    print("AMY M0b routine-engine — real-data briefing demo")
    print("=" * 64)
    print()
    print("RENDERED BRIEFING (the ~12-line terminal brief_output):")
    print("-" * 64)
    print(brief["rendered_text"])
    print("-" * 64)
    print()
    print(f"  total concerns surfaced : {len(brief['items'])}")
    print(f"  above the fold          : {len(brief['above_fold'])} (cap = 5)")
    print(f"  overflow (folded)       : {brief['overflow_count']}  "
          f"-> affordance {brief['overflow_affordance']!r}")
    print(f"  week-review framing     : {brief['week_review_framing']}  (role-lens / Scrum)")
    print()
    print("  urgency order (top to bottom):")
    for i, it in enumerate(brief["items"], start=1):
        marker = "  (folded)" if i > len(brief["above_fold"]) else ""
        print(f"    {i:>2}. {it['urgency']:<20} {it.get('source_kind',''):<11}{marker}")
    print()
    print("  remote fields stay <untrusted_remote_content>-wrapped end-to-end "
          "(see the conflict + ingested nudge detail).")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", default=DEFAULT_NOW,
                        help="ISO clock override for a reproducible run "
                             f"(default {DEFAULT_NOW})")
    parser.add_argument("--workspace", default=None,
                        help="persist the demo pa.db at this path (default: temp dir)")
    args = parser.parse_args(argv)
    ws = Path(args.workspace) if args.workspace else None
    brief = run_demo(now=args.now, workspace_path=ws)
    _print_report(brief)
    return 0


if __name__ == "__main__":
    sys.exit(main())
