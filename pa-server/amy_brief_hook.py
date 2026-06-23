#!/usr/bin/env python3
"""amy_brief_hook.py — AMY's thin SessionStart shim + OS-agnostic --emit-pending stager.

A THIN shim (mirrors skills/_meta/freshness_nudge.py): it carries ZERO business
logic. All composition (snapshot read, nudge drain, role-lens reweight, ranking,
fold, render) lives in the M0b routine-engine (pa_core.pa_brief). This module only:

  1. resolves the workspace pa.db (the same resolution pa_server uses);
  2. calls pa_core.pa_brief to compose the briefing;
  3. decides empty-vs-non-empty and emits the right envelope.

Two modes:

  SessionStart hook (default / --hook):
    Claude Code runs this as a SessionStart command, passing the hook JSON on
    stdin. We drain stdin (so we never block), compose the briefing, and:
      * EMPTY briefing (no surfaced concerns) -> emit a suppressOutput control
        object and exit 0 with NO stdout noise (the Claude Code SessionStart
        suppressOutput control).
      * NON-EMPTY briefing -> emit the rendered briefing as additionalContext
        (still suppressOutput so the raw JSON envelope is not echoed to the
        transcript), exit 0.

  --emit-pending FILE (the OS-agnostic CLI stager):
    Compose the briefing WITHOUT a session and write the rendered text to FILE,
    then exit 0. PURE STDLIB, CROSS-PLATFORM (POSIX or Windows path), with ZERO
    scheduler dependency — the SCHEDULING mechanism is entirely EXTERNAL (cron /
    systemd-timer / Windows Task Scheduler / manual; see pa-server/AMY_ACTIVATION.md).
    This module imports / shells out to NO scheduler and assumes none.

"Empty" is decided from the COMPOSED RESULT, not from the rendered text: pa_brief
always renders a header line, so emptiness == the routine-engine surfaced no items
(``not result["items"]``). The shim never inspects item internals beyond that —
remote-authored fields stay delimiter-wrapped end-to-end (security floor L1).

Activation is NOT auto-wired (user decision): this file does NOT edit
~/.claude/settings.json and installs NO scheduler. See pa-server/AMY_ACTIVATION.md.

NEVER raises to the caller in hook mode: any internal failure emits the benign
silent (suppressOutput) envelope and exits 0, so a SessionStart never breaks.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# pa_core lives next to this file (pa-server/). Import it the same way the adapter
# does, independent of CWD.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def resolve_workspace() -> Path:
    """Resolve the workspace path from $PA_WORKSPACE or CWD.

    Mirrors pa_server.resolve_workspace EXACTLY so the shim reads the same pa.db
    the MCP server writes. $PA_WORKSPACE wins; otherwise the CWD basename under
    ~/.pa/workspaces/. Creates the directory if missing (a first-run session on a
    fresh workspace is a valid, empty briefing — never an error)."""
    env = os.environ.get("PA_WORKSPACE")
    if env:
        ws_path = Path(env)
    else:
        cwd = Path.cwd()
        name = cwd.name or "default"
        ws_path = Path.home() / ".pa" / "workspaces" / name
    ws_path.mkdir(parents=True, exist_ok=True)
    return ws_path


def compose_brief(workspace_path: Path, now: str | None = None) -> dict:
    """Compose the briefing for a workspace via the routine-engine (pa_core.pa_brief).

    Opens the pa.db with the production init_db (so the schema/migrations match the
    server), bootstraps the workspaces row, composes, and returns the pa_brief
    dict UNCHANGED. ZERO business logic here — this only wires the conn + ws_id and
    delegates. The caller decides empty-vs-non-empty from the returned ``items``.

    ``now`` is an optional ISO override threaded through to pa_brief for
    deterministic testing; production passes None (pa_brief uses the wall clock).
    """
    import pa_core  # noqa: PLC0415 — deferred so import errors are caught by callers

    # pa_server owns init_db (base schema + FTS + indexes + triggers + migrations).
    # Load it the same SourceFileLoader-free way: it is a sibling module on path.
    import pa_server  # noqa: PLC0415

    db_path = workspace_path / "pa.db"
    conn = pa_server.init_db(db_path)
    try:
        ws_id = pa_core.workspace_id_from_path(workspace_path)
        # Bootstrap the workspaces row so FK targets exist (idempotent, _with_tx).
        pa_core.ensure_workspace(conn, ws_id, workspace_path.name, str(workspace_path))
        params = {} if now is None else {"now": now}
        return pa_core.pa_brief(conn, ws_id, params)
    finally:
        conn.close()


def is_empty_brief(result: dict) -> bool:
    """A briefing is EMPTY when the routine-engine surfaced no items.

    Decided from the composed result (``items``), NOT from the rendered text —
    pa_brief always renders a header, so a blank-text check would never fire."""
    if not isinstance(result, dict):
        return True
    return not result.get("items")


# ── envelope emission (mirrors freshness_nudge.emit_hook) ─────────────────────

def emit_hook(result: dict | None) -> None:
    """Emit the SessionStart hook JSON envelope on stdout.

    EMPTY (or failed) -> a silent suppressOutput envelope, no additionalContext.
    NON-EMPTY -> suppressOutput + the rendered briefing as additionalContext.
    """
    if result is not None and not is_empty_brief(result):
        out = {
            "continue": True,
            "suppressOutput": True,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": result.get("rendered_text", ""),
            },
        }
    else:
        out = {"continue": True, "suppressOutput": True}
    sys.stdout.write(json.dumps(out))
    sys.stdout.write("\n")


# ── --emit-pending stager (OS-agnostic, zero scheduler dependency) ────────────

def emit_pending(target: str, now: str | None = None) -> int:
    """Compose the briefing and WRITE its rendered text to ``target``; return 0.

    Pure stdlib + cross-platform: ``target`` is any POSIX or Windows path string;
    parent dirs are created. NO session, NO scheduler — scheduling is external.
    On any composition failure, write a single benign line (so a scheduled run
    always produces a readable artifact) and still return 0 — the stager never
    breaks an external scheduler.
    """
    try:
        ws_path = resolve_workspace()
        result = compose_brief(ws_path, now=now)
        text = result.get("rendered_text", "") if isinstance(result, dict) else ""
    except Exception:  # noqa: BLE001 — never break an external scheduler
        text = "AMY briefing — (unavailable)"
    target_path = Path(target)
    if target_path.parent and not target_path.parent.exists():
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    target_path.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def _drain_stdin() -> None:
    """Drain piped stdin (the SessionStart hook protocol passes JSON there) so we
    never block. Best-effort; a TTY or closed stdin is fine."""
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:  # noqa: BLE001
        pass


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])

    # --emit-pending FILE : OS-agnostic stager mode (no session, no stdin protocol).
    if "--emit-pending" in argv:
        i = argv.index("--emit-pending")
        target = argv[i + 1] if i + 1 < len(argv) else None
        # Optional --now ISO override (deterministic tests); production omits it.
        now = None
        if "--now" in argv:
            j = argv.index("--now")
            now = argv[j + 1] if j + 1 < len(argv) else None
        if not target:
            sys.stderr.write("amy_brief_hook: --emit-pending requires a FILE path\n")
            return 2
        return emit_pending(target, now=now)

    # SessionStart hook mode (default). Drain stdin, compose, emit the envelope.
    _drain_stdin()
    now = None
    if "--now" in argv:
        j = argv.index("--now")
        now = argv[j + 1] if j + 1 < len(argv) else None
    try:
        ws_path = resolve_workspace()
        result = compose_brief(ws_path, now=now)
        emit_hook(result)
    except Exception:  # noqa: BLE001 — a SessionStart hook must NEVER break a session
        emit_hook(None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
