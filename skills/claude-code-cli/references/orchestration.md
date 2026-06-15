# Orchestration: Workflow Tool, Effort/ultracode, Scheduling

> The Claude Code 2.1.x orchestration surface — the Workflow tool (script-driven multi-agent
> orchestration), effort levels and ultracode, session/cloud scheduling primitives, and the one
> hard restriction that shapes every multi-agent design: subagents cannot spawn subagents.

Verified against the official docs and the live 2.1.170 tool surface on 2026-06-10. Companion
file: `native-teams-tasks.md` (experimental agent teams, native task tools, background agents).

## The Workflow tool (official, v2.1.154+, all paid plans)

The Workflow tool lets Claude **write a JavaScript orchestration script** that the Claude Code
runtime executes **in the background** while the main session stays responsive. Instead of the
main loop serially calling the Agent tool and babysitting each result, the script declares the
whole fan-out/fan-in shape up front and the runtime drives it.

### Primitives available inside a workflow script

| Primitive | What it does |
|---|---|
| `agent(prompt, opts)` | Spawns a subagent. `opts`: `schema` (JSON Schema — structured output is **forced**, not best-effort), `agentType` (resolves from the same registry as the Agent tool — custom agents from `.claude/agents/` work as workflow stages), `isolation: 'worktree'` (run in a per-agent git worktree), `model`, `phase`, `label`. |
| `pipeline(items, ...stages)` | Per-item flow through the stage functions. **No barrier** — each item advances to the next stage as soon as it finishes the previous one. |
| `parallel(thunks)` | Run thunks concurrently **with a barrier** — returns when all complete. |
| `phase(name)` / `log(msg)` | Progress reporting back to the session UI. |
| `budget` | Token-budget object with a **hard ceiling**; `budget.spent()` and `budget.remaining()` let the script adapt (e.g. skip optional stages when low). |
| `workflow(name, args)` | Invoke another saved workflow. **One level of nesting only.** |

### meta block

Every workflow script must declare a `meta` block with `name`, `description`, and `phases`. The
block must be a **pure literal** (no computed values) — the runtime parses it statically before
execution.

### Determinism requirement (load-bearing)

Workflow scripts must be **deterministic**. Wall-clock and RNG calls are **unavailable inside
scripts** — they would break journal resume (below). If a workflow's output needs a timestamp,
stamp it **after** the workflow returns, or pass it in via args.

### Saved / named workflows

| Location | Scope |
|---|---|
| `.claude/workflows/` | Project |
| `~/.claude/workflows/` | User (all projects) |

Saved workflows are invocable **by name with args** — a reusable orchestration library, the same
layering as agents and skills.

### Journal resume

Workflow execution is journaled. On resume (e.g. after an interruption), **unchanged `agent()`
calls return cached results** instead of re-running — only stages whose inputs changed re-execute.
This is why determinism is mandatory: a script that reads the clock or RNG would produce
different call arguments on replay and defeat the cache.

### Limits

| Limit | Value |
|---|---|
| Concurrent agents | `min(16, cores - 2)` |
| Lifetime agent cap per workflow | 1000 |
| Nesting | One level (`workflow()` from inside a workflow, no deeper) |

## Effort levels and ultracode

`/effort` (interactive) and `--effort <level>` (CLI, verified in 2.1.170 `--help`) set the
session effort level:

```
low | medium | high | xhigh | max
```

**ultracode** (v2.1.160+) = `xhigh` effort **plus automatic Workflow orchestration for every
substantive task** — Claude proactively writes workflow scripts instead of working serially.
Also triggerable per-prompt with the `ultracode` keyword in the prompt text (same family as
`ultrathink`).

## Scheduling primitives

| Primitive | Kind | What it does |
|---|---|---|
| `CronCreate` / `CronList` / `CronDelete` | Tools | **Session-scoped** cron jobs — fire prompts on a schedule within this session's lifetime. Auto-expire after **7 days**. |
| `ScheduleWakeup` | Tool | Dynamic pacing for `/loop` — the model schedules its own next wake-up instead of a fixed interval. |
| `RemoteTrigger` | Tool | Register an externally-triggerable hook into the session. |
| `/schedule` | Slash command | **Cloud routines** — scheduled cloud agents that run on a cron schedule independent of any local session. |
| `/goal` | Slash command (v2.1.139+) | Persistent goal the session keeps working toward across turns. |

Session-scoped (Cron*, ScheduleWakeup, RemoteTrigger) dies with the session or the 7-day expiry;
`/schedule` routines live in the cloud and survive everything local.

## KEY ASYMMETRY: subagents cannot spawn subagents

This is an **official hard restriction**, not a local quirk: the **Agent and Workflow tools exist
in the main conversation loop ONLY**. A subagent's tool surface contains neither — it cannot
fan out, cannot start a workflow, cannot recurse. (Locally re-confirmed many times — see the
`bob_subagent_depth_restriction` memory; any subagent session can verify by inspecting its own
tool list.)

**Consequence — invert control.** Any agent design that says "the subagent will spawn helpers"
is dead on arrival. The working pattern:

1. Subagent **emits a plan** (structured output: list of work packets / agents to run).
2. The **main loop** reads the plan and does the orchestration (Agent tool, Workflow tool, or
   native teams).
3. Results flow back to the subagent (or a fresh one) for synthesis if needed.

This is exactly why bob uses serial-with-checkpointing instead of nested teams, and why workflow
scripts (which run agents *for* you from the main loop's privilege level) are the sanctioned way
to get deep fan-out.

## Portability rule for THIS ecosystem

Everything on this page is **Claude-Code-only**. Codex CLI, Copilot CLI, and Antigravity (agy)
have none of it — no Workflow tool, no ultracode, no Cron* tools.

Skills in this library MUST therefore:

- **Feature-detect** before relying on any of it (the `affordance-advisor` gating pattern: detect
  the host CLI from the environment, surface the native affordance only when the host is Claude
  Code).
- **Keep a portable fallback** as the documented main path — e.g. the file-based `agent-teams`
  inbox/outbox protocol, serial subagent calls, or plain scripted loops.

Treat Workflow/ultracode/Cron as a fast path a skill may *suggest*, never a dependency it
*requires*.

## See also

- `native-teams-tasks.md` — experimental agent teams, TaskCreate/TaskList/etc., background agents
- `sub-agents.md` — authoring the custom agents that `agentType` resolves to
- `custom-ecosystem.md` — the local forge/bob/alf/pa stack these primitives slot into
- `headless.md` — scripted invocation (`-p`), the other automation axis
