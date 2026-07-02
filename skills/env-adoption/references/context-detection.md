# Context detection — the canonical recipe (Q3, live)

This is the **single source of truth** for "can THIS context call orchestration
RIGHT NOW?" (Q3 of the three-question taxonomy). Consumer skills/agents **LINK
to this file — they never restate the recipe**. (S055 workflow-adoption keystone.)

## The three-question taxonomy

| # | Question | Answered by | Lifecycle |
|---|----------|-------------|-----------|
| Q1 | Does this **host** have an orchestration-capable Claude Code? | `inventory.json → harness.*` | persistent, 24h |
| Q2 | Does this **session's harness** expose the surface? | session file `capabilities.*` | per-session |
| Q3 | Can **this context** call it RIGHT NOW? | `probe.sh context` / tool-list check | **live, NEVER cached** |

## The decision rule (greppable — restate verbatim in every consumer)

```
can_orchestrate = capabilities.<surface> AND context == main-loop
```

**`capabilities.*` alone NEVER authorizes orchestration.** Session files are
keyed by the ROOT session ID and are **SHARED with subagents** — children
inherit `CLAUDE_CODE_SESSION_ID` (live-verified, challenger A-1), so
`capabilities.workflow_tool` read from a subagent returns the **parent's** value,
which answers Q2 for the HOST session, never Q3 for the child. The context
conjunct is mandatory.

## Truth: session files are shared parent↔child (no "context-correct for free")

There is **no** mechanism by which the session file becomes context-correct
automatically. The session JSON is one file per ROOT session ID, written once,
and read by both the main loop and every subagent it spawns. A subagent that
trusts `capabilities.*` without the context conjunct **will misclassify itself
as the main loop**. The live canary test
(`tests/test_probe_orchestration.sh`) asserts the child-inherits-parent-session-ID
fact so any future harness change that breaks this assumption is caught.

## The recipe (3 layers)

1. **Capability read** — `probe.sh get capabilities.<surface>`
   (`workflow_tool` | `native_teams` | `agent_spawn`). `false`/missing ⇒ take the
   portable fallback, stop. This is the ONLY capability API — never raw `jq` on
   `inventory.json`, never inline `claude --version`.

2. **Context** —
   - **model-level (primary):** is the orchestration surface in YOUR tool list
     (active or deferred)? An agent/skill running in the model loop can see
     whether `Workflow` / `Agent` is callable. This is the most reliable signal
     for model-driven paths.
   - **script-level (bash paths):** `probe.sh context` returns one of:

     ```
     CLAUDECODE != "1"                                   -> non-claude-host[:<host-id>]
     CLAUDECODE == "1" + CLAUDE_CODE_CHILD_SESSION set   -> child-session
     CLAUDECODE == "1" + CLAUDE_CODE_SUBAGENT set        -> child-session
     CLAUDECODE == "1" alone                             -> main-loop
     ```

3. **Safety net** — a *rejected* orchestration call is treated as
   `child-session`: take the portable fallback or emit a plan artifact, and
   **never retry natively**. A failed spawn attempt is not a retry candidate —
   it is proof you are a subagent. `child-session` + fan-out needed ⇒ the
   plan-compilation protocol (emit a host-neutral DATA plan, HALT).

## Host-neutral branch (HN steer, binding)

The `non-claude-host` branch routes through the **existing host-detection
precedence** (per affordance-advisor's `detect_host_cli.py`):

```
CLAUDECODE -> CODEX_VERSION -> COPILOT_* -> VS Code markers -> unknown
```

Output is one of:

```
non-claude-host:codex | non-claude-host:copilot | non-claude-host:vscode | non-claude-host
```

so portable callers (launchers, skills running under Codex/Copilot) get a usable
host identity from the SAME single recipe instead of inventing per-skill probes.
A non-Claude executor consuming a registry plan artifact serially is a CONFORMING
execution (W-HN).

## Workflow-stage env — recorded WP-2 live experiment

| context | `CLAUDECODE` | child marker | `probe.sh context` | notes |
|---------|--------------|--------------|--------------------|-------|
| main loop | `1` | unset | `main-loop` | orchestration legal |
| subagent | `1` | `CLAUDE_CODE_CHILD_SESSION` set (inherited) | `child-session` | NO Agent/Workflow tool |
| workflow stage | `1` | `CLAUDE_CODE_CHILD_SESSION=1` (CONFIRMED live, WP-2) | `child-session` | `AGENT_TOOL_IN_MY_LIST: no`, `WORKFLOW_TOOL_IN_MY_LIST: no` — stages CANNOT orchestrate |
| non-claude host | unset/`!=1` | n/a | `non-claude-host:<id>` | portable fallback path |

**Workflow stages are `child-session`** (CONFIRMED by the WP-2 live experiment,
forge #159, 2026-06-11): a workflow stage MUST NOT assume it can spawn agents or
invoke nested workflows beyond the one declared child level.

**WP-2 ENV DUMP (recorded — forge #159, Claude Code 2.1.172, 2026-06-11):** a
workflow stage sees `CLAUDECODE=1`, **`CLAUDE_CODE_CHILD_SESSION=1`**,
`AI_AGENT=claude-code_2-1-172_agent`, and **`CLAUDE_CODE_SESSION_ID` = the
PARENT's session id** (children inherit — confirms challenger A-1; NEVER key
session state by session-id alone). Stage self-report:
`AGENT_TOOL_IN_MY_LIST: no`, `WORKFLOW_TOOL_IN_MY_LIST: no`. The native-teams
experimental env gate observed live is
**`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`** (the var `probe.sh
harness.native_teams` tests, + the version floor). Nesting is ONE level,
strictly (a `workflow()` call from inside a child workflow is REFUSED — so
`ratify-design` must always be invoked TOP-LEVEL). **Stage-Bash → external
CLIs:** the historical stage hang was observed with `agy -p --sandbox` even with
`< /dev/null` — since found (2026-07-02) to be a flag-order bug (`-p` swallows
`--sandbox` as the prompt; sandbox off, real prompt discarded, agy free-runs/
recurses). The corrected `agy --sandbox -p` is UNVERIFIED from workflow stages —
keep treating agy as UNREACHABLE from stages until re-probed (use pre-launched
inline transcripts passed via args, design §4.4); `codex exec` from a stage is
UNTESTED — attempt with the full guard set but implement the same inline fallback.

<!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: claude-code-workflow-surface
    verified_against: "2.1.173 (gating is by manifest harness.* field, never this number)"
    verified_on: "2026-06-11"
    volatility: high
  - kind: status_snapshot
    subject: child-session-id-inheritance
    verified_against: "children inherit CLAUDE_CODE_SESSION_ID (live-verified, A-1)"
    verified_on: "2026-06-11"
    volatility: medium
-->


## Observed limitation — env arm is conservative-only (2026-06-11, Claude Code 2.1.173)

Live finding from the S055 forge spot-check: `CLAUDE_CODE_CHILD_SESSION=1` is present in **main-loop Bash tool shells too**, not only in true subagent contexts (observed on 2.1.173; the WP-2 probe that motivated the marker observed it from inside a genuine workflow stage and could not see this case). Consequences, binding for all consumers:

- `probe.sh context` reporting `child-session` is **NOT proof the caller is a subagent** — any script-level check can only be conservative (it may under-claim main-loop, never over-claim it). This is fail-closed in the safe direction and changes no gate semantics.
- The **model-level check stays the ONLY authoritative main-loop proof** (R2): "is Workflow/Agent in MY OWN tool list" — exactly as the three-layer recipe already orders it. No consumer may authorize orchestration from script-level context alone.
- Capability *support* detection is unaffected: `probe.sh get capabilities.workflow_tool` reads host/session support facts and is the correct launcher-side gate (the alf launcher deliberately gates on capabilities ONLY and leaves the context decision to the model reading its printed invocation).
