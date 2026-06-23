"""M0b integration tests for amy-brief-hook (WP-5).

Exercises the contract-map ``amy-brief-hook`` integration point:

  * ``sessionstart_hook_io`` (kind: process_io) — the shim is invoked AS A
    SUBPROCESS exactly as Claude Code runs a SessionStart command (env +
    hook JSON on stdin -> stdout envelope), and as the ``--emit-pending`` CLI
    stager (env -> file output). This proves the real process wire contract, not
    just the in-process functions.

The non-empty path seeds a workspace with a real surfaced concern (an active
blocker -> BLOCKER BriefItem) so the briefing the shim emits is the routine
engine's actual rendered output flowing across the process boundary.

VALID M0a enums only. stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import _load_pa_server  # noqa: E402

PA_SERVER_ROOT = Path(__file__).resolve().parent.parent.parent  # pa-server/
HOOK = PA_SERVER_ROOT / "amy_brief_hook.py"
NOW = "2026-06-15T12:00:00"


def _seed_blocker(ws_path: Path):
    pa_server = _load_pa_server()
    import pa_core  # noqa: PLC0415

    conn = pa_server.init_db(ws_path / "pa.db")
    try:
        ws_id = pa_core.workspace_id_from_path(ws_path)
        pa_core.ensure_workspace(conn, ws_id, ws_path.name, str(ws_path))
        conn.execute(
            "INSERT INTO blockers (workspace_id, kind, description, severity, status) "
            "VALUES (?, 'decision', ?, 'critical', 'active')",
            (ws_id, "Sign-off pending on the migration plan"),
        )
        conn.commit()
    finally:
        conn.close()


def _run(args, ws_path, stdin_bytes=b""):
    env = dict(os.environ)
    env["PA_WORKSPACE"] = str(ws_path)
    proc = subprocess.run(
        [sys.executable, str(HOOK), *args],
        input=stdin_bytes, capture_output=True, env=env, timeout=60,
    )
    return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")


class TestSessionStartProcessIO:
    def test_nonempty_briefing_flows_across_process_boundary(self, tmp_path):
        """process_io: a seeded concern is composed by the routine engine and
        surfaces as additionalContext on the SessionStart envelope (suppressOutput
        still True so the raw JSON is not echoed to the transcript)."""
        ws = tmp_path / "ws-blk"
        ws.mkdir()
        _seed_blocker(ws)
        payload = json.dumps({"hook_event_name": "SessionStart"}).encode("utf-8")
        rc, out, err = _run(["--now", NOW], ws, stdin_bytes=payload)

        assert rc == 0, f"stderr={err!r}"
        env = json.loads(out.strip())
        assert env.get("suppressOutput") is True
        assert env.get("continue") is True
        hso = env.get("hookSpecificOutput")
        assert hso and hso.get("hookEventName") == "SessionStart"
        ctx = hso.get("additionalContext", "")
        assert "AMY briefing" in ctx
        assert "BLOCKER" in ctx

    def test_empty_workspace_silent_envelope(self, tmp_path):
        """process_io: an empty workspace yields the silent suppress envelope (no
        additionalContext) across the process boundary."""
        ws = tmp_path / "ws-empty"
        ws.mkdir()
        rc, out, err = _run(["--now", NOW], ws, stdin_bytes=b"")
        assert rc == 0
        env = json.loads(out.strip())
        assert env == {"continue": True, "suppressOutput": True}


class TestEmitPendingProcessIO:
    def test_emit_pending_file_artifact_across_process_boundary(self, tmp_path):
        """process_io: --emit-pending writes the routine-engine rendered briefing
        to a file and exits 0, no scheduler involved."""
        ws = tmp_path / "ws-emit"
        ws.mkdir()
        _seed_blocker(ws)
        target = tmp_path / "out" / "brief.txt"
        rc, out, err = _run(["--emit-pending", str(target), "--now", NOW], ws)
        assert rc == 0, f"stderr={err!r}"
        assert target.exists()
        text = target.read_text(encoding="utf-8")
        assert "AMY briefing" in text and "BLOCKER" in text
