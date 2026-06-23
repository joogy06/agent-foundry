# AMY briefing hook — activation (OPTIONAL, user decision)

`pa-server/amy_brief_hook.py` is the thin SessionStart shim for AMY's catch-up
briefing (the M0b routine engine). It is **built and unit-tested in-repo but NOT
auto-wired** — wiring it into your shell/session is a deliberate user decision.
Nothing in this repo edits `~/.claude/settings.json` or installs any scheduler.

Two independent activation paths, both OPTIONAL. Pick either, both, or neither.

The shim composes the briefing entirely via the routine engine
(`pa_core.pa_brief`) over the workspace `pa.db`. Workspace resolution mirrors the
MCP server: `$PA_WORKSPACE` if set, else `~/.pa/workspaces/<cwd-basename>/pa.db`.

---

## A. SessionStart hook (print the briefing when you start a Claude Code session)

This adds a 5th SessionStart hook so AMY prints the briefing (or stays silent
when there is nothing pressing — it emits a `suppressOutput` control with no
stdout noise) at the start of a session.

**OPTIONAL** — add to `~/.claude/settings.json` under `hooks.SessionStart`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          { "type": "command",
            "command": "python3 /ABS/PATH/TO/pa-server/amy_brief_hook.py" }
        ]
      }
    ]
  }
}
```

Replace `/ABS/PATH/TO/` with the absolute path to this repo's `pa-server/`. The
hook drains the SessionStart JSON Claude Code passes on stdin and never blocks; on
any internal error it emits the benign silent envelope (a SessionStart hook must
never break a session). Set `PA_WORKSPACE` in your environment to pin a specific
workspace, otherwise it resolves from the CWD.

---

## B. Schedule the `--emit-pending` stager (stage a briefing to a file)

`--emit-pending FILE` composes the briefing and writes the rendered text to
`FILE`, then exits 0. It is **pure stdlib, cross-platform (POSIX or Windows), and
depends on NO scheduler** — the scheduling mechanism is entirely external and
your choice. The command is simply:

```
python3 /ABS/PATH/TO/pa-server/amy_brief_hook.py --emit-pending /path/to/pending-brief.txt
```

Pick ONE scheduler below (all OPTIONAL). The stager itself is identical on every
OS; only the scheduling wrapper differs.

### B1. cron (Linux / macOS) — OPTIONAL

```cron
# Stage AMY's briefing every weekday at 08:00
0 8 * * 1-5 PA_WORKSPACE=/abs/ws python3 /ABS/PATH/TO/pa-server/amy_brief_hook.py --emit-pending /abs/ws/.pa/pending-brief.txt
```

### B2. systemd-timer (Linux) — OPTIONAL

`~/.config/systemd/user/amy-brief.service`:

```ini
[Unit]
Description=Stage AMY briefing

[Service]
Type=oneshot
Environment=PA_WORKSPACE=/abs/ws
ExecStart=/usr/bin/python3 /ABS/PATH/TO/pa-server/amy_brief_hook.py --emit-pending /abs/ws/.pa/pending-brief.txt
```

`~/.config/systemd/user/amy-brief.timer`:

```ini
[Unit]
Description=Stage AMY briefing on a schedule

[Timer]
OnCalendar=Mon-Fri 08:00
Persistent=true

[Install]
WantedBy=timers.target
```

Then `systemctl --user enable --now amy-brief.timer`.

### B3. Windows Task Scheduler (`schtasks`) — OPTIONAL

```bat
schtasks /Create /TN "AMY Brief" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 08:00 ^
  /TR "python C:\ABS\PATH\TO\pa-server\amy_brief_hook.py --emit-pending C:\ws\pending-brief.txt"
```

(Set `PA_WORKSPACE` as a user/system environment variable, or rely on the CWD the
task runs in.)

### B4. Manual — OPTIONAL

Just run the `--emit-pending` command whenever you want a staged briefing:

```
python3 /ABS/PATH/TO/pa-server/amy_brief_hook.py --emit-pending ./pending-brief.txt
```

---

## Notes

- The MCP server name stays `pa-server` and the tool prefix stays
  `mcp__pa-server__*`. AMY is a persona over the same server — no rename.
- The shim carries zero business logic: all composition (snapshot read, nudge
  drain, role-lens reweight, ranking, fold, render) lives in the routine engine.
- Remote-authored fields stay delimiter-wrapped end-to-end (security floor L1);
  the shim never unwraps them.
