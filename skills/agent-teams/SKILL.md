---
name: agent-teams
description: Use when forge or bob needs to split work across multiple parallel agent teams — topology selection, team sizing, cross-team dependencies, inbox/outbox coordination, and result aggregation.
---

# Agent Teams — Multi-Team Orchestration Engine

## Overview

You are the orchestration layer between forge/bob (workflow) and team-manager (single-team coordination). You receive work packages from forge or bob and decide HOW to execute them: how many teams, what topology, what size, what roles, and how teams coordinate.

<HARD-RULE>
You are NOT standalone. You are always invoked by forge or bob. Do not interact with the user directly — report back to your caller.
</HARD-RULE>

<HARD-RULE>
You do NOT implement code. You orchestrate teams. If you catch yourself writing application code, STOP. Create a team and delegate.
</HARD-RULE>

<HARD-RULE>
Native `Task*` NEVER mirrors the ledger. `TaskCreate`/`TaskUpdate`/`TaskList`
(and `SendMessage`/`Monitor`) are VISIBILITY-ONLY scratch. `progress/integration-ledger.md`
and `.ledger/**` remain bob-only (CB4); nothing reads native task state as
transition authority, and nothing copies ledger stages into `Task*` or back.
Native teams are a strictly-optional visibility/messaging enhancement
(`capabilities.native_teams`) — experimental, one team at a time, NEVER a
dependency, NEVER the coordination store.
</HARD-RULE>

## Three backends (S055 — workflow-adoption keystone)

agent-teams runs the SAME policy layer over three explicit, named backends. The
backend is **feature-detected via `probe.sh get capabilities.*` ONLY** (never
raw jq, never inline probing) AND the live context (`probe.sh context`):

- **Part I — Policy layer** (backend-independent): dependency-graph analysis,
  the parallelism-ratio kill rule, topology selection, sizing ceilings.
  `contracts.md` + `deps.md` stay the durable cross-team ledgers in ALL backends.
  The Workflow concurrency cap `min(16, cores−2)` does NOT raise the 10-agent
  policy ceiling.
- **Part II — Backend selection**:
  - main loop + `capabilities.workflow_tool` ⇒ **Workflow-stage backend** (Part III)
  - main loop + `capabilities.agent_spawn` only ⇒ **File backend** (Part IV)
  - no spawn facility (inside bob/alf/evo/pa/wiki — a subagent) ⇒
    **plan-compilation return** (Part V)
- **Part III — Workflow-stage backend**: topology → primitive mapping
  (CONCURRENT → `parallel()` of team stages with `deliverable.v1` schema-forced;
  PIPELINE → sequential awaits; TOURNAMENT → delegate to
  adversarial-team-brainstorm); worktree policy per "Worker isolation + merge
  order" below (isolation ONLY for all-`worktree_ok` teams; merge via the
  controlled merge step `_meta/worktree_merge.py`); NO inbox/outbox files in
  this backend. Native teams (TeamCreate/SendMessage/Monitor/Task*) are a
  separate, strictly-optional visibility enhancement gated on
  `capabilities.native_teams` — never a dependency, never the coordination store.
- **Part IV — File backend** (portable fallback): the current Steps 1–8 below,
  PRESERVED UNCHANGED (exact phrases, leading-space enum grammar).
- **Part V — When delegation is unavailable**: run the POLICY layer only,
  serialize as `team_plan`, return `status: needs_main_loop` — the caller (bob)
  embeds it in `progress/work-packages.yaml` and HALTs `needs: plan-execution`.
  The last-resort serial-bob-with-checkpointing prose is retained below.

### Worker isolation + merge order (Part III; S055 §6.6)

CB4 protection for worker stages is FILESYSTEM-shaped, not prompt-only:

1. **Every non-bob worker stage runs worktree-isolated** (`isolation:'worktree'`),
   legal ONLY for WPs with `executor: worker` (which the `work-packages.v1`
   schema constrains to `machinery: []` + `worktree_ok: true`). Machinery WPs
   are canonical-tree bob stages, always.
2. **Merge order** (the compile of any mixed plan):
   `bob-serial-exec [preflight/scaffold WPs]` →
   `agent-teams backend [isolated worker WPs, parallel]` →
   **controlled merge** (`_meta/worktree_merge.py`, Bash-invoked): applies each
   worktree's diff to the canonical tree and **REJECTS any diff touching the
   forbidden-path list** (`.ledger/**`, `progress/integration-ledger.md`,
   `.bob-checkpoint.md`, `progress/work-packages.yaml`, `.forge/session.key`,
   `progress/workflow-runs.jsonl`) → `bob-serial-exec [verification/finalize WPs]`.
   A rejected diff fails that worker's WP (`needs: user-decision`), never
   silently drops files.

## When delegation is unavailable (S030-quickwins #52 / Part V)

Some Claude Code spawn contexts are configured WITHOUT the Task / Agent tool
in the subagent. Confirmed empirically across S028 #45 spawn 1 and S029 retry
2026-04-27: when bob is itself spawned as a subagent (e.g. by forge or alf via
the general-purpose Agent tool), bob's own subagent context lacks Task/Agent.
That means **agent-teams cannot spawn parallel team-leads from inside bob's
subagent context** — the very tool that would create them is unavailable.

This is an environmental constraint of the spawning harness, not a bug in
agent-teams. Symptoms:

- `Agent(...)` calls fail at first use with "tool not available" or similar.
- Repeated team-lead spawns each fail at the same point in execution.
- Parallel orchestration silently degenerates into a single-team execution
  with no actual parallelism.

### Preferred remedy (S055): run POLICY only, return `needs_main_loop`

When agent-teams runs inside a subagent (bob/alf/evo/pa/wiki) with no spawn
facility, the FIRST-CHOICE remedy is NOT to flatten into serial bob spawns
manually — it is to run the **POLICY layer only** (dependency analysis,
topology, sizing, parallelism-ratio) and SERIALIZE that as a `team_plan`
block, returning `status: needs_main_loop`. The caller (bob) embeds the
`team_plan` in `progress/work-packages.yaml` (host-neutral DATA) and HALTs
`needs: plan-execution`. The MAIN LOOP then executes the plan — preferentially
through the `bob-serial-exec` saved workflow when `capabilities.workflow_tool`
is true, else through the serial-with-checkpointing fallback below. This is the
inversion-of-control flow: delegation flows UP, never down.

### Proven workaround: serial bob spawns with `.bob-checkpoint.md`

When the harness will not give bob's subagent the Agent tool, the caller
(forge / alf / pa / standalone) MUST orchestrate the WP cycle as **serial
bob spawns** — one bob per WP-batch — with state persisted in
`.bob-checkpoint.md` between spawns. agent-teams cannot rescue a bob that
has been deprived of Agent; the only path forward is to flatten the
orchestration into the outer caller. Bob in turn must HALT cleanly and
escalate to the caller (per HARD-RULE 1, see `~/.claude/agents/bob.md`)
rather than silently direct-execute work that the design said should be
parallelised.

`.bob-checkpoint.md` is bob's own restart-resume contract; agent-teams
does NOT touch it.

## Input Contract

Your caller passes you a structured request:

```
work_packages: [
  { id, description, dependencies: [id...], estimated_complexity: S|M|L, file_scope: [globs] }
]
constraints: { max_teams, max_agents_per_team }
shared_context: { design_document, codebase_summary, style_guide, architecture_docs }
isolation_preference: "worktree" | "shared"  # optional, defaults to "shared"
```

## Output Contract

You return to your caller:

```
status: complete | partial | failed
teams_used: number
deliverables: [
  { work_package_id, team_id, files_modified: [paths], summary }
]
integration_notes: string
unresolved_conflicts: [ { description, teams_involved, options } ]
```

---

---

# Part IV — File backend (portable fallback)

The Steps 1–8 below are the **File backend**: the portable, spawn-facility path
preserved UNCHANGED from prior versions (exact phrases, leading-space enum
grammar). When `capabilities.workflow_tool` is true and you are in the main
loop, prefer the Workflow-stage backend (Part III); the policy layer (Steps 1–3)
is shared across both.

## Step 1: Analyze Work Packages

Build a dependency graph from the work packages:

```
1. Parse all work_packages and their dependencies
2. Find connected components (independent groups)
3. Find longest dependency chain (sequential depth)
4. Count distinct domains (directories, tech stacks)
5. Calculate parallelism ratio: independent_packages / total_packages
```

**Key rule:** If parallelism ratio < 0.3, DO NOT use multi-team — sequential overhead (39-70% degradation) will destroy value.

## Step 2: Select Topology

```
IF dependency_graph is disconnected (independent groups):
    -> CONCURRENT

ELIF dependency_graph is a linear chain:
    -> PIPELINE

ELIF dependency_graph has a star shape (one core, N consumers):
    -> SPECIALIST_TEAMS (Phase 2 — fall back to CONCURRENT with sequenced blocking deps)

ELSE:
    -> CONCURRENT with blocking deps handled by sequencing
```

### Concurrent Topology

Teams run in parallel on independent work packages. Results fan-in to you for aggregation.

```
    agent-teams
    /    |    \
  TM-1  TM-2  TM-3    (parallel)
    \    |    /
    agent-teams         (collect results)
```

Best for: multi-domain work with clear file boundaries (frontend + backend + infra).

### Pipeline Topology

Teams run sequentially. Team N's output becomes Team N+1's input.

```
  TM-1 --output--> agent-teams --input--> TM-2 --output--> agent-teams --input--> TM-3
```

Best for: progressive refinement (research -> design -> implement -> test).

### Tournament Topology (Adversarial Brainstorm)

Multiple independent teams generate outputs in parallel, then attack each other's outputs, refine,
and synthesize. Used when a caller needs adversarially-validated outputs with explicit kill
criteria — not parallel implementation, but parallel divergent exploration with structured
contention.

**This topology is implemented via the `adversarial-team-brainstorm` primitive** — it is a pure
prompt-orchestration skill that spawns teams, runs the four rounds (diverge → cross-fire → refine
→ arbiter), and returns ranked outputs. When a caller invokes agent-teams in "tournament" mode,
delegate to `adversarial-team-brainstorm` directly rather than building the rounds yourself.

```
  adversarial-team-brainstorm
         /    |    |    \
       T-A   T-B  T-C   T-D    (Round 1: diverge, parallel)
         \    |    |    /
       cross-fire (Round 2: each team attacks the others)
         \    |    |    /
       refine (Round 3: absorb attacks)
              |
          arbiter (Round 4: rank, hybridize, kill criteria, confidence)
```

Callers:
- `forge` design exploration tournaments (alternative to the single-team design exploration)
- `founder-ideation` (business idea generation with problem-first / asset-first / trend-first /
  contrarian lenses)
- `alf` (adversarial review of skills, code, products)
- Any workflow that needs a ranked output list with explicit kill criteria

**When to use:** exploratory / creative / research questions where the answer is not "one correct
approach" but "a ranked list of options with trade-offs spelled out and explicit kill criteria
per option."

**When NOT to use:** implementation work. Tournament mode is for divergent exploration, not for
splitting parallel code writing — that's CONCURRENT or PIPELINE topology.

### Specialist Teams Topology (Phase 2)

Core team produces shared artifacts at a sync point. Spoke teams consume them in parallel.

```
         TM-core
            |
      [sync point]
       /    |    \
    TM-A  TM-B  TM-C   (parallel, consuming core output)
```

Best for: API-first development (core team builds API contract, consumer teams build against it).

## Step 3: Size Teams

### Sizing Table

| Work Packages | Domains | Teams | Agents/Team | Total Agents |
|---------------|---------|-------|-------------|-------------|
| 1-3, sequential | Any | 1 | 2-3 | 2-3 |
| 1-6 | 1 | 1 | 3 | 3 |
| 4-6 | 2+ | 2 | 3 | 6 + 1 integrator = 7 |
| 7-12 | 2+ | 3 | 3-4 | 9-12 max 10 |
| 12+ | 3+ | 4 | 3 | Cap at 10 total |

### Hard Limits

- **Per-team:** min 2, optimal 3, max 4
- **System ceiling:** 10 concurrent agents (across all teams)
- **Max teams:** 4

### Role Assignment

```
team_size 2: 1 implementer + 1 challenger
team_size 3: 2 implementers + 1 challenger
team_size 4: 2 implementers + 1 challenger + 1 (qa OR ux_reviewer)

UI-facing work: include ux_reviewer (replaces qa or extra implementer)
Multi-team: you (agent-teams) act as the system-level integrator
```

## Step 4: Set Up Coordination Infrastructure

### Single-Team Optimization

If topology is single-team (1 team only):
- Skip contracts.md (no cross-team contracts needed)
- Skip deps.md (no cross-team dependencies)
- Create only: session_control.md + team manifest + inbox/outbox
- This saves ~500 tokens of coordination metadata for simple jobs

### Full Infrastructure (Multi-Team)

Before spawning ANY team, create the .forge directory:

```
.forge/
+-- contracts.md              # Interface contracts (YOU write this)
+-- deps.md                   # Dependency gates (YOU write this)
+-- session_control.md        # File ownership (YOU write this)
+-- team-{id}/
|   +-- manifest.md           # Team spawn context (YOU write this)
|   +-- inbox.md              # Messages TO team (YOU write this)
|   +-- outbox.md             # Messages FROM team (team lead writes)
```

### contracts.md

Pre-populate with ALL known interface contracts between teams:

```markdown
# Interface Contracts

## [Contract Name] (owner: Team-{id}, work_package: {id})
Status: DRAFT | PUBLISHED
```typescript
// The interface definition
```
Consumers: Team-{id}, Team-{id}
```

### deps.md

```markdown
# Cross-Team Dependencies

| ID | From (needs) | Provider | Artifact | Status |
|----|-------------|----------|----------|--------|
| DEP-001 | Team-A:WP-003 | Team-B:WP-007 | User model | WAITING |
```

### session_control.md

```markdown
# File Ownership

| File/Directory | Owner | Status |
|---------------|-------|--------|
| src/auth/** | Team-A | ACTIVE |
| src/models/** | Team-B | ACTIVE |
| src/routes/** | Team-C | ACTIVE |
```

### Write Ownership Rules

| File | Writer | Readers |
|------|--------|---------|
| contracts.md | You only | All teams |
| deps.md | You only | All teams |
| team-X/manifest.md | You (at spawn) | Team-X |
| team-X/inbox.md | You only | Team-X lead |
| team-X/outbox.md | Team-X lead only | You |
| session_control.md | You (setup), team leads (claim/release) | All |

**Concurrency model: convention-based file ownership.** Teams share one repo unless spawned with `isolation: "worktree"`. File ownership in session_control.md is a coordination convention, not a hard lock. When `isolation_preference: "worktree"` is set in the input, spawn team leads with `isolation: "worktree"` in the Agent call to give each team an isolated copy. Otherwise, rely on non-overlapping file scopes and accept residual collision risk on shared files (config, tests, generated code).

## Step 5: Spawn Teams

### Team Lead Spawn Prompt (~600 tokens)

```
Agent(name: "team-{id}-lead", subagent_type: "general-purpose", prompt: """
[TEAM_MANIFEST]
team_id: {id}
team_name: "{descriptive name}"
objective: "{team's specific goal}"

[SCOPE]
work_packages: {list of assigned WP ids and descriptions}
files_owned: {glob patterns}
files_readonly: {glob patterns for cross-team interfaces}

[TEAM_ROSTER]
specialists: {count}, roles: {role list}

[COORDINATION]
your_outbox: .forge/team-{id}/outbox.md (WRITE status updates here)
your_inbox: .forge/team-{id}/inbox.md (CHECK for cross-team messages)
contracts: .forge/contracts.md (READ for interface definitions)
file_locks: .forge/session_control.md

[INSTRUCTIONS]
1. Invoke the `team-manager` skill — it contains your full methodology
2. Read your inbox before starting
3. Create tasks for your specialists using TaskCreate
4. After EACH task completes, write a STATUS_UPDATE to your outbox
5. Check your inbox between task cycles for cross-team updates
6. When all tasks done, write TEAM_COMPLETE to your outbox
7. Assign these skills to specialists: {domain-specific skill list}
8. All specialists must follow `development-lifecycle` verification gate before marking done
""")
```

### Outbox Format (team leads write this)

```markdown
## [HH:MM:SS] STATUS_UPDATE
task_id: {id}
status: COMPLETE | IN_PROGRESS | BLOCKED
artifact: {file path if applicable}
summary: {1-2 sentences}
cross_team_note: {any published interface or dependency need}

## [HH:MM:SS] TEAM_COMPLETE
tasks_completed: {N}/{total}
artifacts: {list of file paths}
decisions_made: {key decisions}
```

### Inbox Format (you write this)

```markdown
## [HH:MM:SS] DEPENDENCY_RESOLVED
from_team: {id}
artifact: {description}
location: see contracts.md section "{name}"
action: unblock task {id}

## [HH:MM:SS] PRIORITY_CHANGE
reason: {why}
action: {what the team should do differently}
```

## Step 6: Monitor and Coordinate

### Active Monitoring Loop

After spawning all teams, you actively monitor:

```
LOOP while any team is running:
  1. Read all team outboxes
  2. For each new STATUS_UPDATE:
     a. Track progress (tasks completed per team)
     b. Check for cross_team_note — does another team need this?
     c. If yes: update contracts.md, write to consuming team's inbox, update deps.md
  3. For each TEAM_COMPLETE:
     a. Collect deliverables
     b. Check if completion unblocks other teams (pipeline topology)
     c. If pipeline: spawn next team with previous team's output as context
  4. For each BLOCKED with reason in outbox:
     - skill_gap -> invoke research-for-skills, write DEPENDENCY_RESOLVED to team inbox
     - external_dependency -> log, escalate to caller (bob/forge)
     - file_conflict -> attempt auto-merge per ownership rules, if fails escalate
     - scope_change -> defer to bob's pause cycle. Do NOT auto-restart the team
       and do NOT escalate as a team failure. Bob's `claims.request_scope_pause`
       (S029 design §10) drives the freeze-the-world / amend / resume arc;
       team-managers and specialists MUST NOT call `pause_state.request_pause`
       directly (CB4: bob is the sole pause-cycle caller). When the gate fires,
       bob takes over orchestration; agent-teams holds the team in a paused
       outbox state until bob signals resume via the team's inbox (RESUMING ->
       NORMAL transitions land as DEPENDENCY_RESOLVED messages).
     - unknown -> escalate to caller with full context
  5. Check circuit breakers (see Failure Handling)
  6. Continue until all teams complete or failure
```

### Cross-Team Dependency Flow

When Team-A produces output that Team-B needs:

```
1. Team-A lead writes to outbox: STATUS_UPDATE with cross_team_note
2. You read Team-A's outbox, see the cross_team_note
3. You update contracts.md with the published interface
4. You update deps.md (mark DEP as RESOLVED)
5. You write to Team-B's inbox: DEPENDENCY_RESOLVED
6. Team-B lead reads inbox, unblocks waiting work
```

**Team leads and specialists NEVER communicate across teams directly.**

## Step 7: Handle Failures

### Circuit Breaker (Per Team)

Track a stall counter per team. Increment when a team's outbox shows no new completions between check cycles.

```
stall_count < 3:  CLOSED (normal)
stall_count >= 3: OPEN (broken) -> intervene
after intervention: HALF_OPEN (one more cycle to verify recovery)
```

### Interventions

| Stall Count | Action |
|-------------|--------|
| 3 | SendMessage to team lead: "Status check — what's blocking progress?" |
| 4 | Kill stalled specialist, respawn with simplified task |
| 5 | Restructure team tasks or merge with another team |
| 6+ | Return failure report to caller |

### Circular Dependencies

If deps.md shows a cycle (A needs B, B needs A):

1. **Interface-first:** Force both teams to publish interface contracts NOW. Code against the contract. Reconcile later.
2. **Merge:** Pull the blocking task into the other team's scope.
3. **Stub:** Create a mock for one direction. Resolve after both complete.

## Step 8: Aggregate Results

When all teams complete:

1. Read all team outboxes for final deliverables
2. Read all modified files listed in deliverables
3. Check for conflicts (two teams modified overlapping files)
4. If conflicts: attempt automated resolution or flag as unresolved
5. Compile integration notes
6. If component boundary changes detected (new components added, topology changed):
   - Invoke `project-documentation` cascade rules
   - Update COMPONENT.md for affected components
   - Update PROJECT.md interaction edges if topology changed
7. Return structured result to your caller (see Output Contract)
8. Clean up: on `status: complete` remove `.forge/`; on `status: partial|failed` move to `.forge-archive-{timestamp}/` for forensic analysis

---

## Anti-Patterns

- **Implementing instead of orchestrating** — you create teams, you don't write code
- **Skipping pre-flight dependency analysis** — leads to blocked teams and wasted compute
- **Allowing cross-team direct messaging** — all cross-team flows through you via inbox/outbox
- **Exceeding 10 concurrent agents** — coordination overhead destroys value beyond this
- **Using multi-team for sequential work** — 39-70% degradation penalty
- **Spawning teams without interface contracts** — guarantees integration failures
- **Ignoring outbox updates** — stale dependencies cause teams to work against wrong assumptions

## Quick Reference

```
Max teams: 4
Max agents/team: 4
System ceiling: 10 concurrent agents
Optimal team: 3 agents
Topologies: CONCURRENT, PIPELINE (Phase 2: SPECIALIST_TEAMS)
Communication: inbox/outbox files, convention-based file ownership (worktrees when available)
Dependencies: contracts.md + deps.md, you mediate all cross-team flow
Failure: circuit breaker at 3 stalls, escalate at 6
```
