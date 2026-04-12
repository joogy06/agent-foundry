# Integration recipes — wiring anti-drift into your environment

The `anti-drift` skill is necessary but not sufficient. A skill alone is vulnerable
to the exact problem it tries to solve: if the agent drifts, it forgets to invoke
the skill. Use these integration recipes for layered defense.

## Recipe 1: CLAUDE.md baseline (always-on)

Add to `~/.claude/CLAUDE.md`:

```markdown
## Anti-drift discipline

Read `~/.claude/skills/_meta/hard-rules-checklist.md` at the start of every session
and again at every decision checkpoint. After 50+ tool calls in a session, re-read
it explicitly before:
- Spawning any sub-agent
- Claiming any task complete
- Making any destructive change (rm, force push, drop table, deploy)

If you notice any of these symptoms, invoke the `anti-drift` skill immediately:
- Proposing the same fix twice in different forms
- Hedging heavily ("I think", "perhaps", "this should")
- Forgetting which sub-task you're on
- Claiming completion without verifiable evidence
- Generic responses that don't reference the specific task context
```

Place this section at the END of CLAUDE.md (recency anchor).

## Recipe 2: settings.json hook (deterministic injection)

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "test $(date +%s) -gt $(stat -c %Y /tmp/last-anti-drift-check 2>/dev/null || echo 0) && expr $(date +%s) - $(stat -c %Y /tmp/last-anti-drift-check 2>/dev/null || echo 0) -gt 600 && head -25 ~/.claude/skills/_meta/hard-rules-checklist.md && touch /tmp/last-anti-drift-check"
          }
        ]
      }
    ]
  }
}
```

This re-injects the top of the hard-rules-checklist every 10 minutes when a destructive
tool is called. Adjust the interval and matcher to your tolerance for noise.

## Recipe 3: Per-skill checkpoint integration

Add to skills that orchestrate long workflows (`forge`, `bob`, `alf`):

In `forge/SKILL.md`, after Step 4 (Complexity Assessment), add Step 4c:

```markdown
### Step 4c: Anti-drift check (NEW — April 2026)

Before spawning the design exploration team:
1. Invoke `anti-drift` skill, operation `check-drift`
2. If drift signals detected, run operation `checkpoint` first
3. Externalize task state via `externalize-state` if 5+ sub-tasks expected
4. Only proceed once focus is verified
```

In `bob.md` (agent), add to Step 4 (Verify):

```markdown
**Pre-completion: anti-drift audit**

Before compiling the execution report and claiming COMPLETE:
1. Invoke `anti-drift` skill, operation `metacognitive-audit`
2. Switch to Checker persona, re-read original design doc
3. For each requirement, demand tangible evidence
4. Only claim COMPLETE if zero gaps after audit
```

In `alf.md` (agent), add to Step 6 (Verify Handoff):

```markdown
**Pre-handoff: drift check**

Before generating the design doc for bob:
1. Invoke `anti-drift` skill, operation `check-drift`
2. If drift detected, run `checkpoint` to re-anchor
3. Re-read the target file fresh (don't rely on cached recall)
4. Then proceed with the handoff
```

## Recipe 4: Project-level state externalization

For any project with `.claude-link` (project-bound), add a `.session-state.md`
template that the anti-drift skill auto-creates:

```markdown
# Session state — <project name>

## Current task
<one-sentence summary>

## Completed sub-tasks
- [ ] sub-task 1
- [ ] sub-task 2

## Active constraints
- (from hard-rules-checklist.md, scoped to this task)

## Failed approaches (do not retry)
- approach X: failed because Y

## Next planned action
<specific next action>

## Updated
<timestamp>
```

The skill operation `externalize-state` writes/updates this file at every checkpoint.

## Recipe 5: User-side discipline

Even with all the technical defenses, the user plays a role:

- **Notice drift symptoms** in the agent's output and call them out: "you're hedging,
  re-read the brief"
- **Reset sessions** when drift becomes obvious — sometimes a fresh start is faster
  than re-anchoring a 100-turn session
- **Use shorter, more focused sessions** when possible
- **Externalize state outside the conversation** — design docs, history.md, etc.

## Layered defense summary

| Layer | Mechanism | When it fires |
|---|---|---|
| 1 | CLAUDE.md baseline | Every session start |
| 2 | settings.json hook | Every N tool calls (deterministic) |
| 3 | Per-skill checkpoint | At specific decision points in workflows |
| 4 | Project state file | Every 5+ sub-task session |
| 5 | User-side notice | When user spots a symptom |
| 6 | Anti-drift skill | When invoked manually or by other layers |

No single layer is sufficient. Together, they create defense in depth.
