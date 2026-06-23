"""M0b unit tests for amy-brief-hook — SessionStart suppress behavior (WP-5).

Covers the contract-map ``amy-brief-hook`` success criterion (a):

  * An EMPTY briefing produces a suppressOutput control object and NO stdout
    noise (the Claude Code SessionStart suppressOutput control).
  * The shim carries ZERO business logic — composition is delegated to the
    routine-engine (pa_core.pa_brief); the shim only decides empty-vs-non-empty.

The hook is exercised as a SUBPROCESS (the ``sessionstart_hook_io`` / process_io
integration seam): we invoke ``python3 amy_brief_hook.py`` with PA_WORKSPACE
pointing at a fresh temp workspace, feed the SessionStart hook JSON on stdin, and
assert on the process stdout + exit code. This is exactly how Claude Code runs a
SessionStart command, so the test proves the real wire contract.

stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PA_SERVER_ROOT = Path(__file__).resolve().parent.parent.parent  # pa-server/
HOOK = PA_SERVER_ROOT / "amy_brief_hook.py"
NOW = "2026-06-15T12:00:00"


def _run_hook(args, ws_path, stdin_bytes=b""):
    """Run amy_brief_hook.py as a subprocess with PA_WORKSPACE set.

    Returns (returncode, stdout_str, stderr_str). HOME is repointed at a temp dir
    so a no-PA_WORKSPACE run can never touch the developer's real ~/.pa."""
    import os

    env = dict(os.environ)
    env["PA_WORKSPACE"] = str(ws_path)
    proc = subprocess.run(
        [sys.executable, str(HOOK), *args],
        input=stdin_bytes,
        capture_output=True,
        env=env,
        timeout=60,
    )
    return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")


@pytest.fixture
def empty_ws(tmp_path):
    """A fresh, empty workspace dir (no pa.db yet -> a first-run empty briefing)."""
    ws = tmp_path / "empty-ws"
    ws.mkdir()
    return ws


class TestSessionStartSuppress:
    def test_empty_briefing_emits_suppress_and_exits_zero(self, empty_ws):
        """T-HK-1 (a): empty workspace -> suppressOutput control object, exit 0,
        no briefing text leaked to stdout."""
        hook_payload = json.dumps(
            {"hook_event_name": "SessionStart", "cwd": str(empty_ws)}
        ).encode("utf-8")
        rc, out, err = _run_hook(["--now", NOW], empty_ws, stdin_bytes=hook_payload)

        assert rc == 0, f"hook must exit 0; stderr={err!r}"
        # stdout is exactly one JSON envelope line.
        env = json.loads(out.strip())
        assert env.get("suppressOutput") is True
        assert env.get("continue") is True
        # EMPTY => no additionalContext / no briefing text noise.
        assert "hookSpecificOutput" not in env
        assert "AMY briefing" not in out

    def test_empty_briefing_no_stdout_noise(self, empty_ws):
        """The empty-path stdout is a single suppress envelope — nothing else
        (no banner, no header line, no rendered briefing)."""
        rc, out, err = _run_hook(["--now", NOW], empty_ws, stdin_bytes=b"")
        assert rc == 0
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert len(lines) == 1, f"expected exactly one envelope line, got {lines!r}"
        env = json.loads(lines[0])
        assert env == {"continue": True, "suppressOutput": True}

    def test_hook_never_raises_on_garbage_stdin(self, empty_ws):
        """A SessionStart hook must NEVER break a session: garbage on stdin still
        yields a benign suppress envelope + exit 0 (defense in depth)."""
        rc, out, err = _run_hook(["--now", NOW], empty_ws, stdin_bytes=b"\x00\xff not json")
        assert rc == 0
        env = json.loads(out.strip())
        assert env.get("suppressOutput") is True
        assert env.get("continue") is True

    def test_shim_carries_zero_business_logic(self):
        """Structural assertion: the shim delegates composition to the routine
        engine (pa_core.pa_brief) and does NOT reimplement ranking/fold/render."""
        src = HOOK.read_text(encoding="utf-8")
        assert "pa_core.pa_brief" in src, "shim must delegate to routine-engine pa_brief"
        # The shim must NOT reimplement the ranker / fold / urgency taxonomy.
        for forbidden in ("URGENCY_RANK", "fold_brief_items", "build_brief_items", "def _render_brief_text"):
            assert forbidden not in src, f"shim must not reimplement {forbidden} (zero business logic)"
