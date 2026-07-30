# Startup — re-expressing the SessionStart hooks

<!-- REVIEW-BY: 2026-10-31 -->

> ## ⚠ SUPERSEDED IN PART — 2026-07-29. The premise below is now FALSE.
>
> **VS Code has a real hook system, with a `SessionStart` event that injects into model context.**
> Read from the docs on 2026-07-29 (§"Agent hooks"): eight events — `SessionStart`,
> `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PreCompact`, `SubagentStart`, `SubagentStop`,
> `Stop` — where `SessionStart` fires before the user's first turn and returns
> `hookSpecificOutput.additionalContext`, which is exactly what the Claude Code hook does.
>
> **And the read locations include `~/.claude/settings.json` and `.claude/settings.json`** — the
> files our six hooks already live in. Per-hook `windows` / `linux` / `osx` command overrides are
> part of the format, which also answers the cross-platform half.
>
> This is the case §"The `hooks` frontmatter field" below anticipated, and it lands wider than
> expected: not agent-scoped hooks, but a standalone hook system. **If it behaves as documented, the
> four layers collapse to one and the enforcement grade goes from convention to HARD.**
>
> **Nothing here has been executed** — this host has no VS Code, so every line above is
> documentation, not a measurement. **Do not delete the four layers on the strength of it.** The
> verification task is #241: run the existing hooks unmodified on the Windows and Mac machines, and
> confirm the digest actually reaches the model rather than merely running. A hook that executes and
> whose output is silently dropped is precisely the failure mode this file was written about.

The original four-layer answer follows, **still correct as a fallback** and still the only tested
path. Only one of the four is actually enforced; saying which is which is the point — a convention
presented as a guarantee is how the harness's own incident happened.

## Layer 1 — `folderOpen` task (the only real automatic trigger)

VS Code tasks support `runOptions.runOn: "folderOpen"`, which runs **without anyone asking**. It
cannot inject into chat context, but it can do the *mechanical* half: run the probes and write the
state file.

```jsonc
// .vscode/tasks.json
{
  "version": "2.0.0",
  "tasks": [{
    "label": "foundry: session prime",
    "type": "shell",
    "command": "python3 ${workspaceFolder}/vs-code/scripts/session_prime.py",
    "runOptions": { "runOn": "folderOpen" },
    "presentation": { "reveal": "silent", "panel": "dedicated" },
    "problemMatcher": []
  }]
}
```

**Enforcement: HARD for the state file, NONE for the model reading it.** The task guarantees the
digest exists and is fresh. It cannot guarantee anyone looks at it. Verify `runOn: folderOpen`
behaves as expected on the target machine before relying on it.

## Layer 2 — always-on instructions (convention, but always present)

`AGENTS.md`, `.github/copilot-instructions.md` and `CLAUDE.md` are collected into every request.
Putting the startup contract there means the model *sees* the obligation on every turn without
anyone invoking anything.

**Enforcement: CONVENTION.** The model can ignore it. It is always present, which is worth a great
deal, but presence is not compulsion — the same distinction as `enforcement: convention` in the UX
evidence contract.

## Layer 3 — `VSPrime`, an agent whose instructions ARE the startup

A custom agent carries its body as standing instructions. **Selecting the agent is the trigger.** No
keyword to remember, no task to fire — choosing `VSPrime` in the picker means the sequence is in
context from the first turn.

**Enforcement: SOFT.** Automatic *for that agent*, absent for every other. Best default for VS Code
work, and it is also where VS Code-specific behaviour belongs — see `agents/vsprime.agent.md`.

## Layer 4 — `/prime`, the explicit keyword

A prompt file becomes a slash command. `/prime` runs the sequence on demand, from any agent, at any
point in a session.

**Enforcement: MANUAL, and it is the most reliable of the four** — because it is the only one where
someone deliberately asked. It is also the recovery path when a session has drifted, or when the
folderOpen task did not run.

## How they compose

```
folderOpen task ──► writes .foundry/session-state.json     [HARD: the file exists and is fresh]
                              │
AGENTS.md ────────────────────┼──► "read it before working" [CONVENTION: always present]
                              │
VSPrime agent ────────────────┼──► same, in its own body    [SOFT: automatic when selected]
                              │
/prime ───────────────────────┘                             [MANUAL: deliberate, most reliable]
```

**State the grade in the output.** When the digest was produced by the task and read, say so. When it
was not read, or is stale, say that instead of implying a primed session. A stale digest confidently
presented is worse than none — it is the `enforcement: convention` lesson in a new place.

## A lead worth chasing on the target machine

**`.agent.md` frontmatter also accepts a `hooks` field** (verified present in the custom-agent docs
2026-07-29, behaviour NOT yet tested here). If agent-scoped hooks can fire on session or agent start,
that would move Layer 3 from SOFT toward HARD and materially close this gap.

**Do not assume it does.** Verify on the target: what events fire, whether output reaches chat
context or only the terminal, and whether it runs on agent selection or only on explicit invocation.
Until tested, the four layers above stand as written — and a `hooks` field that turns out to fire
only on tool use would change nothing about startup.

Frontmatter also carries **`handoffs`** (buttons that pass context to another agent, with optional
auto-submit) and **`agents`** (which agents may be invoked as subagents). Together those map the
forge → bob → alf cascade far more directly than expected.

## What is honestly lost

**Nothing forces the model to consume the state.** In Claude Code the hook injects into context; here
the best available is a file plus an instruction to read it. Layers 1 and 4 are real; 2 and 3 change
the default, not the ceiling.

**Say that plainly in any parity claim.** VS Code startup is *approximately* equivalent, not
equivalent, and the difference is exactly the enforcement grade.
