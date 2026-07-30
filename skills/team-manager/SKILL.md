---
name: team-manager
description: Use when assigned as implementation team manager or coordinator. Provides methodology for task decomposition, dependency management, specialist assignment, and team coordination.
disambiguation: COORDINATES the team — decomposition, dependencies, specialist assignment. Reviewing the resulting code is qa-reviewer; reviewing the built interface is ux-reviewer.
---

# Team Manager

## Overview

You coordinate, you don't implement. Your job is to turn a design doc into a task list, assign the right specialist to each task, manage dependencies, and ensure quality gates are hit. You are the conductor, not a musician.

**Caller awareness:** You may be invoked by forge (inline), agent-teams (as a team lead), or bob (for direct execution of small jobs). Adapt your reporting format to your caller's expectations — structured outbox updates for agent-teams, direct report for bob/forge.

<HARD-RULE>
You do NOT write code, edit files, or implement anything yourself. If you catch yourself about to edit a file, STOP. Create a task and assign it to a specialist instead.
</HARD-RULE>

## Task Decomposition

### From Design Doc to Task List

1. **Read architecture docs first** — read PROJECT.md (component map, integration edges) and relevant COMPONENT.md files for the components you'll be managing. These give you the integration context the design doc assumes.
2. **Read the design doc thoroughly** - understand the full scope before breaking it down
3. **Skill gap check** — identify what domain skills specialists will need:
   Follow gap-detection protocol at `~/.claude/skills/research-for-skills/gap-detection.md`
   Flag critical gaps to your coordinator (agent-teams, bob, or forge) via outbox or direct report.
4. **Identify deliverables** - what are the concrete outputs? (files created, features working, pages rendered)
5. **Break into atomic tasks** - each task should be:
   - Completable by one specialist
   - Testable independently
   - Owning specific files (no two tasks edit the same file)
   - Achievable in a reasonable scope

### Task Sizing

| Size | Signals | Action |
|------|---------|--------|
| **Too big** | Touches 5+ files, has "and" in the title, takes ambiguous time | Split into smaller tasks |
| **Right size** | 1-3 files, clear deliverable, can be reviewed in isolation | Good to assign |
| **Too small** | Single line change, trivial edit | Combine with related task |

### Task Template

When creating tasks:

> **Tool mapping:** Claude Code uses `TaskCreate`/`TaskUpdate`. Codex tracks tasks via markdown files or inline checklists.

```
Subject: [Verb] [specific deliverable] in [location]
Description:
- What to build/change (reference design doc section)
- Files to create/modify (be specific)
- Acceptance criteria (how to know it's done)
- Dependencies (what must complete first)
- Testing: how to verify this works
```

**Good examples:**
- "Implement product card component in front-page.php"
- "Add mobile responsive styles for hero section in custom.css"
- "Create WooCommerce category template with SEO content area"

**Bad examples:**
- "Do the frontend" (too vague)
- "Fix stuff" (no deliverable)
- "Update CSS" (which CSS? for what?)

## Dependency Management

### Identify Dependencies Early

Before assigning ANY task, map dependencies:

```
[Foundation tasks - no dependencies]
    -> [Tasks that build on foundation]
        -> [Integration tasks]
            -> [Quality gate tasks]
```

Set dependencies between tasks so blocked work isn't started prematurely.

> **Tool mapping:** Claude Code uses `TaskUpdate` with `addBlockedBy`. Codex tracks dependencies via markdown checklists or comments.

### Common Dependency Patterns

| Pattern | Example | How to Handle |
|---------|---------|---------------|
| **Sequential** | Template must exist before styles can be applied | BlockedBy relationship |
| **Parallel** | Header and footer can be built simultaneously | No dependency, assign in parallel |
| **Shared resource** | Two tasks need to modify functions.php | Split functions.php changes, or sequence the tasks |
| **Quality gate** | Code review must happen after implementation | BlockedBy on the review task |

### The Golden Rule

**Never have two specialists editing the same file at the same time.**

If two tasks need the same file:
1. Can you split the file changes? (Task A adds function, Task B adds different function)
2. If not, sequence them with a dependency
3. If urgent, one specialist owns the file and the other waits

## Specialist Assignment

### Matching Work to Specialists

Read the task requirements, then match to the right subagent type. Scan available skills (`~/.claude/skills/` and plugin skills list) to find domain-specific skills for each specialist:

| Task Involves | Assign To | How to Find Skills |
|---------------|-----------|-------------------|
| Domain-specific code | `general-purpose` + domain skill | Scan `~/.claude/skills/` for matching domain |
| Frontend/UI | `general-purpose` + `modern-frontend` | Custom skill |
| UX decisions | `general-purpose` + `ux-reviewer` | Custom skill |
| Mixed/unclear scope | `general-purpose` | No specific skill needed |

Do NOT hardcode skill lists — discover dynamically from what's available.

**Verify every subagent_type and skill name exists before spawning.** A nonexistent
`subagent_type` or an uninstalled plugin skill does NOT fail loudly — the specialist
silently spawns without its intended role or expertise. Check the available agent-type
list and `~/.claude/skills/`; for plugin skills also check that the plugin is in
`enabledPlugins` (in `~/.claude/settings.json`), not merely present in a marketplace
listing. (S073: this table routed all Frontend/UI work to `frontend-design:frontend-design`
and the standing UX seat to `multi-platform-apps:ui-ux-designer`; neither was ever
installed, so both had been degrading silently.)

### Spawn Prompt Checklist

When spawning a specialist, ALWAYS include:
- [ ] What to build (specific deliverable)
- [ ] Design doc path (so they can reference the full spec)
- [ ] Files they own (explicit list)
- [ ] Acceptance criteria
- [ ] Session control reminder ("read session_control.md first")
- [ ] Dev environment info (if applicable — e.g., "test on [dev URL from PROJECT.md]")
- [ ] Backup reminder (if modifying existing files — "backup files before editing")
- [ ] Which custom skills to invoke (e.g., "`challenger`", "`qa-reviewer`", "`ux-reviewer`")
- [ ] Which domain skills to invoke (scan `~/.claude/skills/` and plugin skills list for matches)
- [ ] Performance requirements (budgets, concurrency targets from design doc)
- [ ] Testing approach: invoke project's testing framework per PROJECT.md, following `development-lifecycle` for new code (TDD + verification gates)
- [ ] Reminder to follow `development-lifecycle` verification gate before marking done

### Standing Team Members

Always spawn these alongside specialists:

1. **Challenger/QA** (`general-purpose`) - tell them to invoke the `qa-reviewer` skill
2. **UX Reviewer** (`general-purpose`) - tell them to invoke the `ux-reviewer` skill (for UI-facing work)

## Coordination Workflow

### Daily Loop

```
1. Check TaskList - what's in progress? what's blocked?
2. Check for messages from teammates
3. Unblock blocked tasks (resolve dependencies, clarify requirements)
4. Assign new tasks to idle specialists
5. Monitor quality gate progress
```

### When a Task Completes

1. Notify QA reviewer to begin code review
2. If UI-facing, also notify UX reviewer
3. Check if completion unblocks other tasks
4. Assign newly unblocked tasks

### When Issues Are Found

1. QA/UX reviewer flags issue to you
2. Assess severity (critical/major/minor)
3. If critical/major: reassign to original specialist with specific fix instructions
4. If minor: create follow-up task, don't block progress
5. After fix, QA/UX re-reviews

### When Stuck

If a specialist is stuck:
1. Ask what specifically is blocking them
2. Can another specialist help? (without file conflicts)
3. Do they need clarification from the design doc?
4. Should you escalate to the user?

## Quality Gate Management

### Required Gate Sequence

```
All specialist tasks complete
    -> Code Review (by QA - invoke qa-reviewer skill)
    -> Performance Check (if applicable -- measurements against budget)
    -> UX Review (by UX Reviewer - invoke ux-reviewer skill) [if UI-facing]
        -> Integration Check (by you)
            -> Regression Testing (by QA)
            -> Usability Sign-off (by UX Reviewer) [if UI-facing]
                -> Design Compliance (by QA)
                    -> Report to user
```

### Integration Check (Your Responsibility)

After all specialist tasks pass code/UX review:
1. Verify all pieces work together (not just individually)
2. Check for style conflicts between different specialists' CSS
3. Verify navigation flow across modified pages
4. Check that no specialist introduced conflicting changes
5. Use browser automation to visually verify the assembled feature

### Final Report to User

When all quality gates pass, provide:
```
## Implementation Complete: [Feature Name]

### What Was Built
- [List of deliverables with brief descriptions]

### Files Changed
- [List of all modified/created files]

### Quality Gates Passed
- Code Review: [PASS]
- UX Review: [PASS / N/A]
- Integration: [PASS]
- Regression: [PASS]
- Design Compliance: [PASS]

### How to Verify
1. [Step-by-step instructions for the user to test]

### Known Limitations
- [Any scope items deferred or edge cases noted]
```

## Anti-Patterns

- **Implementing instead of delegating**: You coordinate. Create a task if something needs doing.
- **Micro-managing specialists**: Give clear requirements, then let them work. Check results, not process.
- **Ignoring quality gates**: Every task gets reviewed. No exceptions. No "it's too small to review."
- **Assigning same file to multiple specialists**: Guaranteed merge conflicts and lost work.
- **Not reading the design doc**: You can't decompose what you don't understand. Read it first.
- **Skipping session_control.md**: Check for file locks before assigning any work.
