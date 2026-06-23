"""M0b unit tests for amy-brief-hook — --emit-pending OS-agnostic stager (WP-5).

Covers the contract-map ``amy-brief-hook`` success criterion (b):

  * ``--emit-pending FILE`` writes the rendered briefing to FILE and exits 0 with
    NO scheduler dependency — pure stdlib, cross-platform (POSIX or Windows path).

The stager is exercised as a SUBPROCESS (the process_io seam): we seed a workspace
with a due item (an active blocker -> a BLOCKER BriefItem, time-independent), run
``python3 amy_brief_hook.py --emit-pending <FILE>``, and assert the file contains
the rendered briefing and the process exited 0.

VALID M0a enums only for any DB seeding (blockers.severity in critical/high/medium/
low, status in active/cleared). stdlib + pytest only — no new pip deps.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

PA_SERVER_ROOT = Path(__file__).resolve().parent.parent.parent  # pa-server/
HOOK = PA_SERVER_ROOT / "amy_brief_hook.py"
NOW = "2026-06-15T12:00:00"

# Import init_db + ensure_workspace via the in-process loader (conftest idiom) so
# the test seeds the SAME schema the stager reads.
from tests.conftest import _load_pa_server  # noqa: E402


def _seed_ws_with_due_item(ws_path: Path):
    """Create pa.db under ws_path and seed ONE active blocker (a deterministic,
    time-independent BriefItem). Returns the ws_id."""
    pa_server = _load_pa_server()
    import pa_core  # noqa: PLC0415

    db_path = ws_path / "pa.db"
    conn = pa_server.init_db(db_path)
    try:
        ws_id = pa_core.workspace_id_from_path(ws_path)
        pa_core.ensure_workspace(conn, ws_id, ws_path.name, str(ws_path))
        conn.execute(
            "INSERT INTO blockers (workspace_id, kind, description, severity, status) "
            "VALUES (?, 'decision', ?, 'critical', 'active')",
            (ws_id, "Prod deploy blocked on the security sign-off"),
        )
        conn.commit()
    finally:
        conn.close()
    return ws_id


def _run_stager(target, ws_path):
    env = dict(os.environ)
    env["PA_WORKSPACE"] = str(ws_path)
    proc = subprocess.run(
        [sys.executable, str(HOOK), "--emit-pending", str(target), "--now", NOW],
        capture_output=True,
        env=env,
        timeout=60,
    )
    return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")


class TestEmitPending:
    def test_emit_pending_writes_briefing_and_exits_zero(self, tmp_path):
        """T-HK-1 (b): --emit-pending FILE with a due item writes the rendered
        briefing to FILE and exits 0."""
        ws = tmp_path / "ws-due"
        ws.mkdir()
        _seed_ws_with_due_item(ws)
        target = tmp_path / "pending" / "brief.txt"

        rc, out, err = _run_stager(target, ws)

        assert rc == 0, f"stager must exit 0; stderr={err!r}"
        assert target.exists(), "stager must create the target file (incl. parent dir)"
        text = target.read_text(encoding="utf-8")
        assert "AMY briefing" in text, f"rendered briefing missing: {text!r}"
        assert "BLOCKER" in text, "the seeded active blocker must surface in the briefing"

    def test_emit_pending_no_scheduler_imports(self):
        """HARD constraint: pure stdlib, ZERO scheduler dependency — the source
        must not import/shell-out to cron/systemd/Task-Scheduler."""
        src = HOOK.read_text(encoding="utf-8").lower()
        # No scheduler library imports or invocations anywhere in the shim.
        for forbidden in ("import crontab", "python-crontab", "schtasks", "systemctl",
                          "crontab -", "import schedule"):
            assert forbidden not in src, f"stager must not depend on a scheduler ({forbidden!r})"

    def test_emit_pending_overwrites_existing_file(self, tmp_path):
        """Re-running the stager onto an existing file overwrites cleanly (a
        scheduled run replaces yesterday's pending briefing)."""
        ws = tmp_path / "ws-over"
        ws.mkdir()
        _seed_ws_with_due_item(ws)
        target = tmp_path / "brief.txt"
        target.write_text("STALE PREVIOUS CONTENT\n", encoding="utf-8")

        rc, out, err = _run_stager(target, ws)
        assert rc == 0
        text = target.read_text(encoding="utf-8")
        assert "STALE PREVIOUS CONTENT" not in text
        assert "AMY briefing" in text

    def test_emit_pending_empty_workspace_still_writes_and_exits_zero(self, tmp_path):
        """An empty workspace via --emit-pending still writes a (header-only)
        briefing file and exits 0 — the stager never errors for an external
        scheduler."""
        ws = tmp_path / "ws-empty"
        ws.mkdir()
        target = tmp_path / "empty-brief.txt"

        rc, out, err = _run_stager(target, ws)
        assert rc == 0
        assert target.exists()
        # Header line always present; for an empty brief the body says nothing pressing.
        text = target.read_text(encoding="utf-8")
        assert "AMY briefing" in text

    def test_emit_pending_missing_path_arg_returns_nonzero(self, tmp_path):
        """--emit-pending with no FILE arg is a usage error (exit != 0), distinct
        from the success exit 0 of a real stage."""
        ws = tmp_path / "ws"
        ws.mkdir()
        env = dict(os.environ)
        env["PA_WORKSPACE"] = str(ws)
        proc = subprocess.run(
            [sys.executable, str(HOOK), "--emit-pending"],
            capture_output=True, env=env, timeout=60,
        )
        assert proc.returncode != 0
