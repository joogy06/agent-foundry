# Native Agent Teams, Task Tools, and Background Agents

> The experimental native multi-agent surface in Claude Code 2.1.x — TeamCreate/SendMessage
> teams, the TaskCreate/TaskList task lifecycle, Monitor, the teammate hooks, and the background
> agent machinery (`run_in_background`, Agent View, worktrees).

Verified against the official docs and the live 2.1.170 tool surface on 2026-06-10. Companion
file: `orchestration.md` (Workflow tool, ultracode, scheduling, the no-nested-subagents rule).

## Status: official but EXPERIMENTAL

Agent teams shipped in v2.1.32+ and remain **disabled by default**. Enable via:

```bash
# env var
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
```

or the equivalent key in `settings.json`.

**Teammates are full parallel Claude instances, NOT subagents.** Each teammate is its own
session-grade process with its own context — which is why teams escape the "subagents cannot
spawn subagents" restriction documented in `orchestration.md` (the lead talks to peers, it does
not nest them).

Known limits (current as of 2.1.170):

| Limit | Detail |
|---|---|
| One team at a time | A session can run a single active team |
| No nested teams | A teammate cannot create its own team |
| No session resumption with in-process teammates | `--resume`/`--continue` does not restore live teammates |

## The team tools

| Tool | What it does |
|---|---|
| `TeamCreate` | Create a team of named teammates |
| `TeamDelete` | Tear the team down |
| `SendMessage` | Message a teammate — including messaging a **NAMED prior agent to continue it with its context intact** (the continuation pattern: instead of re-briefing a fresh agent, address the same named teammate again and it picks up where it left off) |

## The task tools

A native shared task list coordinates who does what:

| Tool | What it does |
|---|---|
| `TaskCreate` | Add a task (description, owner, dependencies) |
| `TaskList` | List tasks and statuses |
| `TaskGet` | Fetch one task's full detail |
| `TaskUpdate` | Update status/owner/notes (in_progress, completed, ...) |
| `TaskStop` | Stop a running task |
| `TaskOutput` | Retrieve the output of a (running or finished) task |
| `Monitor` | Wait on a condition / watch progress without burning turns on polling |

## Teammate hooks (v2.1.152+)

Three hook events fire on team activity, wired in `settings.json` like any other hook
(see `hooks.md`):

| Hook event | Fires when |
|---|---|
| `TeammateIdle` | A teammate runs out of assigned work |
| `TaskCreated` | A task is added to the shared list |
| `TaskCompleted` | A task is marked completed |

Typical use: a `TeammateIdle` hook that assigns the next queued task, or a `TaskCompleted` hook
that kicks verification.

## Relation to the local `agent-teams` skill

This native surface and the local file-based `agent-teams` skill (inbox/outbox directories,
team-manager coordination) solve the same problem at different portability tiers. **Native teams
are the Claude-Code fast path**: real parallel instances, first-class messaging, hook
integration — use them when the host is Claude Code 2.1.32+ with the experimental flag on.
**The inbox/outbox protocol is the portable fallback**: it works from Codex CLI, Copilot CLI,
and Antigravity (agy) too, survives session restarts (it's just files), and stays inside this
library's CB3/CB4 trust boundaries. Skills should feature-detect (affordance-advisor pattern)
and keep the file-based protocol as the documented main path — same rule as the Workflow tool
in `orchestration.md`.

## Background agents

Independent of teams, single agents can run in the background:

| Mechanism | What it does |
|---|---|
| `run_in_background: true` on the Agent tool | Spawns the subagent **async** — the main loop keeps working and is **auto-notified** when the agent finishes |
| `claude agents` — Agent View dashboard (v2.1.139+) | TUI for managing background agent sessions: dispatch, watch, attach. `--json` prints active sessions as a JSON array for scripting (no TTY needed); `--all` includes completed sessions. Verified in 2.1.170 `--help`: dispatch-time defaults via `--agent`, `--model`, `--effort`, `--permission-mode`, `--mcp-config`, `--settings`. |
| `claude --bg --exec` | Launch a background execution directly from the shell |
| Per-session worktrees + `EnterWorktree` (v2.1.154+) | Each background agent can get its own git worktree; `EnterWorktree`/`ExitWorktree` move a session in and out of one — isolation so parallel agents don't trample the working tree |

## See also

- `orchestration.md` — Workflow tool, effort/ultracode, scheduling, the subagent asymmetry
- `hooks.md` / `hooks-guide.md` — wiring TeammateIdle/TaskCreated/TaskCompleted
- `custom-ecosystem.md` — the local agent-teams/team-manager stack this fast-paths
- `cli-reference.md` — `claude agents` flag surface
