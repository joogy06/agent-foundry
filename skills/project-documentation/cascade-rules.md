# Update Cascade Rules

Reference for `project-documentation`. Defines when and how architecture docs are updated based on who is making changes and what kind of changes they are.

## The Gate Question

Before updating any architecture document ABOVE the current working level, ask:

> **"Does this change affect how this component INTERACTS with other components, external services, or the project's public entry points?"**

- **YES** → cascade up one level. That level independently re-evaluates whether to cascade further.
- **NO** → update current level only.

Short form: **cascade upward only when a boundary changed, not when an implementation changed.**

## Caller Context Detection

The skill must determine who is calling it to set the default documentation scope.

| Caller | Detection Signal | Default Scope | Can Update |
|--------|-----------------|---------------|-----------|
| **forge** | Design phase, architecture work, creating PROJECT.md | Level 0 + Level 1 stubs | PROJECT.md, COMPONENT.md stubs |
| **agent-teams** | Multi-team orchestration, cross-component work | Level 0 reconciliation | PROJECT.md (edge updates) |
| **team-manager** | Assigned as coordinator for a component | Level 1 + Level 2 | COMPONENT.md, subcomponent docs |
| **coding agent** | Working on specific files within a component | Level 2 + Level 1 internals | Subcomponent docs, COMPONENT.md internals |
| **user directly** | Direct session, no orchestration context | Any level | Determined by what changed |

### Detection Heuristic

When the skill is invoked, determine caller by checking:

1. Is this inside a forge workflow? (forge step references, design doc creation) → **forge**
2. Is this inside agent-teams orchestration? (.forge/ directory exists, team manifests) → **agent-teams**
3. Is this a team-manager coordinating specialists? (team-manager skill active, task assignment) → **team-manager**
4. Is this a specialist working on specific files? (narrow file scope, implementation task) → **coding agent**
5. None of the above → **user directly**

## Change Classification

Every change falls into exactly one of five types. Classify BEFORE deciding what to update.

### Type 1: Trivial Change
**Examples:** comments, formatting, variable rename, test for unchanged behavior, dependency version bump (same API)

**Action:** No architecture doc update. Update history.md only if notable.

**How to recognize:** The change is entirely internal to a single file and does not change any function signature, data flow, or observable behavior.

### Type 2: Internal Implementation Change
**Examples:** algorithm swap, performance optimization, refactor within component, file reorganization without boundary change, new internal helper function

**Action:** Update COMPONENT.md internals only if the internal flow or key files materially changed. Do NOT cascade to PROJECT.md.

**How to recognize:** The change is within a component, doesn't change any public interface, and no other component needs to know about it.

### Type 3: Local Contract Change
**Examples:** sub-area changes its input/output assumptions within the same component, internal API between sub-components changes

**Action:** Update subcomponent doc (if exists) + update COMPONENT.md internal flow. Do NOT cascade to PROJECT.md.

**How to recognize:** The change crosses sub-component boundaries within ONE component but doesn't change what the component exposes to the outside.

### Type 4: Component Boundary Change
**Examples:** new public interface added, existing interface contract changed, new consumed dependency from another component, removed interface

**Action:** Update COMPONENT.md (interfaces section) + update PROJECT.md (interaction edges table). **Both in the same session.**

**How to recognize:** Another component would need to change its code or behavior because of this change. The answer to the gate question is YES.

### Type 5: Project Topology Change
**Examples:** new component created, component removed/renamed, new external service integrated, new entry point, changed async/sync mode between components, new failure mode that affects multiple components

**Action:** Update PROJECT.md (components table, edges table, external deps) + update/create affected COMPONENT.md files. **All in the same session.**

**How to recognize:** The project's high-level structure or integration map has changed. A new agent reading PROJECT.md tomorrow would see something different.

## Decision Tree

```
CHANGE MADE
    |
    v
Is it trivial? (comments, formatting, rename, tests)
    |
    +-- YES --> no doc update (maybe history.md)
    |
    +-- NO --> continue
            |
            v
        Does it change a PUBLIC INTERFACE of any component?
            |
            +-- YES --> Type 4 or 5
            |       |
            |       +-- Is it a new component, removed component, or new external service?
            |               |
            |               +-- YES --> Type 5: update PROJECT.md + COMPONENT.md files
            |               |
            |               +-- NO --> Type 4: update COMPONENT.md + PROJECT.md edges
            |
            +-- NO --> continue
                    |
                    v
                Does it change how sub-areas interact WITHIN a component?
                    |
                    +-- YES --> Type 3: update subcomponent doc + COMPONENT.md internals
                    |
                    +-- NO --> continue
                            |
                            v
                        Does it materially change internal flow or key files?
                            |
                            +-- YES --> Type 2: update COMPONENT.md internals only
                            |
                            +-- NO --> Type 1: no doc update
```

## Ownership Rules

### Critical: Same-Session Updates

The actor that makes the change updates ALL affected documentation levels in the same session. Do NOT:
- Flag a cascade need and hand it off asynchronously
- Leave PROJECT.md for "someone else" to update later
- Queue doc updates for end-of-sprint cleanup

Async handoffs guarantee drift. Close all doc updates before closing the task.

### Who Updates What

| Situation | Who Updates | Scope |
|-----------|------------|-------|
| Single agent changes internal implementation | Same agent | COMPONENT.md internals |
| Single agent adds/changes public interface | Same agent | COMPONENT.md + PROJECT.md |
| Team of agents building a new component | Team-manager updates COMPONENT.md; coordinator updates PROJECT.md before task close |
| Forge creates new architecture | Forge | PROJECT.md + COMPONENT.md stubs |
| Cross-component refactor | Coordinator (agent-teams) | All affected COMPONENT.md files + PROJECT.md |

### Coding Agents: What NOT To Update

Coding agents working on specific files should NOT directly edit:
- PROJECT.md (unless they are the only agent and the change is Type 4/5)
- Other components' COMPONENT.md files

If a coding agent detects a boundary change that affects PROJECT.md, and they are part of a managed team:
1. Note the boundary change in their task completion output
2. The team-manager/coordinator handles the PROJECT.md update

If the coding agent is working solo (no team context):
1. Apply the gate question
2. Update all affected levels directly

## Practical Examples

| Change | Type | Docs Updated |
|--------|------|-------------|
| Fix JWT clock skew tolerance | 1 (trivial) | None (maybe history.md) |
| Refactor auth middleware to use decorator pattern | 2 (internal) | COMPONENT.md internal flow if materially different |
| Change token format from HS256 to RS256 | 3 (local contract) | auth subcomponent doc + COMPONENT.md |
| Add new `/api/v2/users` endpoint consumed by frontend | 4 (boundary) | api COMPONENT.md + PROJECT.md edges |
| Add Stripe payment integration (new component) | 5 (topology) | PROJECT.md + new payments COMPONENT.md |
| Remove deprecated email service, switch to SendGrid | 5 (topology) | PROJECT.md external deps + workers COMPONENT.md |
| Add rate limiting middleware to API | 2 (internal) | api COMPONENT.md if it affects how requests flow |
| Frontend starts calling workers directly (bypassing API) | 4 (boundary) | PROJECT.md edges + frontend COMPONENT.md + workers COMPONENT.md |

## History rotation interaction

Every append to `history.md` triggers `rotate.run` automatically. If the file is already stamped and within thresholds, this is a <50ms no-op. Sessions older than `N=3` (or content over `CAP=600` lines) are archived into `history/<YYYY-MM>.md`. See `SKILL.md` "History rotation policy" for the full contract; the cascade rules above are unchanged by rotation.

## Freshness Checks

Architecture docs include `last_verified_at` in metadata. Check freshness:

- If `last_verified_at` is older than 30 days and changes are being made to owned_paths, verify the doc is still accurate before relying on it.
- After verifying and updating, bump `last_verified_at` to today.
- Set `confidence: low` on docs that haven't been verified in 60+ days.

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Cascade on every internal change | Over-updating creates noise and doc fatigue |
| Defer PROJECT.md updates to "later" | Drift is guaranteed within 1-2 sessions |
| Let coding agents freely edit PROJECT.md in team contexts | Conflicting edits, lost coherence |
| Skip the gate question | Without it, every change feels like it should cascade |
| Update docs for Type 1 changes | Trivial changes need no architecture doc update |
| Create subcomponent docs proactively | Only when threshold is met — default to 2 levels |
