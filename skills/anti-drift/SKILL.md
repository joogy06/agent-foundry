---
name: anti-drift
description: >
  Use when starting a long-running session, before claiming task completion, or every
  several major tool calls to prevent AI drift from initial instructions. Defines drift
  mechanisms (context rot, lost-in-the-middle, persona collapse, instruction budget),
  symptoms to watch for, and protocols for periodic checkpointing, state externalization,
  metacognitive audit, and recency anchoring. Builds on hard-rules-checklist.md.
  Trigger phrases: "anti drift check", "drift check", "checkpoint rules", "am I still
  on task", "session discipline", "re-anchor", "state externalization", "metacognitive
  audit".
---

# Anti-Drift

A discipline skill for preventing instruction drift in long-running Claude sessions.

## Why this skill exists

LLMs drift. As of April 2026, this is no longer speculative: every frontier model tested
by independent benchmarks (Chroma's 18-model context rot study, the "Drift No More" KL
divergence paper, the multi-agent reliability cascade research) shows measurable
degradation as context grows. The mechanisms are now well-documented:

- **Context rot** — accuracy drops with input length, even on simple retrieval
- **Lost-in-the-middle** — U-shaped recall, instructions buried in mid-context get forgotten
- **Persona collapse** — system prompt influence weakens after ~10-15 turns
- **Instruction budget** — ~150-200 reliable instructions before density-induced collapse
- **Compounding error** — multi-step reliability degrades multiplicatively

Reference: `references/drift-mechanisms.md` for citations and detailed research.

## Hard rules

<HARD-RULE>
**Never trust a "rules" memory more than 50 tool calls old.** After 50 tool calls in
a single conversation, you MUST re-read `~/.claude/skills/_meta/hard-rules-checklist.md`
before proceeding with any decision-point action (spawning agents, claiming completion,
making destructive changes).
</HARD-RULE>

<HARD-RULE>
**Externalize state, do not retain it.** For sessions with 5+ sub-tasks, write progress
to a `.session-state.md` file in the current working directory. Do not rely on context
recall to track what you've done.
</HARD-RULE>

<HARD-RULE>
**Run a metacognitive audit before claiming complete.** Switch to a Checker persona,
re-read your recent output against the original task brief, and verify each requirement
has tangible evidence. Do NOT skip this for "obvious" cases — those are exactly when
drift happens.
</HARD-RULE>

<HARD-RULE>
**Negative framing only.** When stating rules, use NEVER / FORBIDDEN / MUST NOT, not
"Always" / "Should" / "Try to". Negative boundaries survive long contexts; positive
suggestions decay.
</HARD-RULE>

<HARD-RULE>
**Recency anchor at end of prompt.** When invoking sub-agents or writing protocols
that other skills will follow, place the most critical constraints at the END, not
the beginning. The model's last-token bias is structurally stronger than first-token
recall.
</HARD-RULE>

## When to invoke this skill

| Trigger | Action |
|---|---|
| Session starts (any agent) | Read drift-symptoms.md briefly to prime detection |
| Every 50 tool calls | Re-read hard-rules-checklist.md + run quick symptom check |
| Before spawning a sub-agent | Read checkpoint-protocols.md, run pre-spawn checklist |
| Before claiming task complete | Run full metacognitive audit (audit-protocol.md) |
| When you notice you're proposing the same fix twice | Drift symptom — externalize state and start fresh |
| When user gives feedback that contradicts your recent action | Drift symptom — re-read task brief |
| When responses feel "generic" or hedge-heavy | Drift symptom — persona collapse warning |

## Operations

### `check-drift` — quick symptom scan

Trigger phrases: "drift check", "am I drifting", "anti drift check"

1. Count tool calls so far in this session (rough estimate from your context)
2. If >50: re-read `~/.claude/skills/_meta/hard-rules-checklist.md`
3. Scan your recent 5-10 messages against the symptoms in `references/drift-symptoms.md`
4. Report findings: "no drift detected" / "X drift signals detected — recommend Y"

### `checkpoint` — mid-session re-anchoring

Trigger phrases: "checkpoint rules", "re-anchor", "checkpoint"

1. Read the current task brief (from session_control.md or the original user message)
2. Read `~/.claude/skills/_meta/hard-rules-checklist.md` relevant section
3. Read the project's CLAUDE.md if present
4. Write a brief "current focus" summary to remind yourself
5. Continue with refreshed context

### `externalize-state` — write session state to disk

Trigger phrases: "externalize state", "save state", "checkpoint state"

1. Determine the project root (CWD or git root)
2. Create or update `.session-state.md` in the project root with:
   - Current task brief (1-2 sentences)
   - Completed sub-tasks (bullets)
   - Active constraints (from hard-rules-checklist.md, scoped to this task)
   - Failed approaches (so you don't repeat them)
   - Next planned action
3. Reference this file in subsequent decisions instead of recalling from context

### `metacognitive-audit` — self-check before claiming complete

Trigger phrases: "audit", "metacognitive audit", "verify before complete"

This is the most important operation. Follow the protocol in `references/anti-drift-patterns.md`:

1. **Switch persona**: "I am now a Checker, not the implementer. I have no investment in claiming this is done."
2. **Re-read the task brief verbatim** (from session_control.md, the user's original message, or the design doc)
3. **For each requirement**, ask: "What is the tangible evidence this was done?" — file path, command output, test result. If you cannot point to evidence, the requirement is NOT done.
4. **Check verification artifacts**: tests run? lint passed? build succeeded? grep clean?
5. **Spot the gap**: any requirement with no evidence is the gap. Stop. Address it. Then re-audit.
6. **Only after the audit reports zero gaps**: claim completion.

### `inject-recency-anchor` — when invoking a sub-agent

Trigger phrases: "anchor sub-agent", "spawn with anchor", "anti-drift wrap"

When you're about to spawn a sub-agent (forge spawning bob, bob spawning specialists, etc.), ensure the most critical constraints appear at the END of the spawn prompt, not just the beginning. The structure:

```
[Long task brief at the top — context, design doc, file paths, approach]

[...]

CRITICAL REMINDERS (re-read before each action):
- NEVER do X
- MUST verify Y
- ALWAYS write evidence to Z
```

The end-of-prompt placement is structurally important. Don't bury critical rules in the middle of a 2000-token brief — they get lost.

## Integration recipes

For full anti-drift coverage, the skill alone is insufficient (you might forget to invoke it). Use these complementary mechanisms:

### Recipe 1: CLAUDE.md hook (always-on baseline)

Add this section to `~/.claude/CLAUDE.md`:

```markdown
## Anti-drift discipline

Read `~/.claude/skills/_meta/hard-rules-checklist.md` at the start of every session
and again at every decision checkpoint. After 50+ tool calls in a session, re-read it
explicitly before:
- Spawning any sub-agent
- Claiming any task complete
- Making any destructive change (rm, force push, drop table, deploy)

If you notice any of these symptoms, invoke the `anti-drift` skill immediately:
- Proposing the same fix twice in different forms
- Hedging heavily ("I think", "perhaps", "this should")
- Forgetting which sub-task you're on
- Claiming completion without verifiable evidence
```

### Recipe 2: settings.json hook (deterministic injection)

In `~/.claude/settings.json`, add a `PreToolUse` hook that injects a recency anchor every N tool calls:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "if [ $(($(date +%s) % 50)) -eq 0 ]; then cat ~/.claude/skills/_meta/hard-rules-checklist.md | head -20; fi"
          }
        ]
      }
    ]
  }
}
```

(This is a simplified example. The hook system supports more sophisticated triggers — see `update-config` skill for details.)

### Recipe 3: Per-skill checkpoint

Skills that orchestrate long workflows (`forge`, `bob`, `alf`) should add an explicit anti-drift check at decision points. For example, in forge:

```markdown
### Step 4b: Anti-drift check (NEW)

Before spawning the design exploration team:
1. Invoke `anti-drift` skill, operation `check-drift`
2. If drift signals detected, run `checkpoint` first
3. Only proceed once focus is verified
```

## Anti-patterns

| Anti-pattern | Why it fails | Correct approach |
|---|---|---|
| Long bullet lists of "MUST" rules at top of CLAUDE.md | Density-induced collapse — model loses track | Compact rules, recency-anchored at end |
| "ALWAYS verify before claiming complete" | Positive framing decays in long context | "NEVER claim complete without tangible evidence" |
| Trusting your own context recall after 50+ tool calls | Context rot is empirically proven | Externalize to `.session-state.md`, re-read |
| Skipping the metacognitive audit because "this is obviously done" | Drift happens exactly when you're confident | Audit always — the "obvious" cases are when you're most likely wrong |
| Long monolithic CLAUDE.md with reference docs mixed in | Instruction density degrades attention | Split: rules at top, reference content via @import |
| Relying on the skill alone | The skill itself is forgettable when drifted | Pair with hooks + CLAUDE.md baseline |
| "Just this once" exceptions to hard rules | Ambiguity seeds drift | No exceptions. If a rule needs an exception, fix the rule. |

## When NOT to use this skill

- Single-shot prompts (one user message, one response, done) — drift hasn't happened yet
- Pure information queries ("explain X", "what does Y do") — no decision points
- The first 5 turns of any session — overhead exceeds benefit
- When the user explicitly says "skip the checks" — respect user judgement

## Reference files

- `references/drift-mechanisms.md` — research-backed mechanisms (context rot, LITM, persona collapse, instruction budget, compounding error)
- `references/drift-symptoms.md` — catalog of symptoms with examples
- `references/anti-drift-patterns.md` — techniques that work (with citations)
- `references/checkpoint-protocols.md` — when and how to checkpoint
- `references/2026-research.md` — current research citations (April 2026)
- `references/integration-recipes.md` — how to wire CLAUDE.md, hooks, and skill-to-skill integration
- `templates/state.md.template` — externalized session state template
- `templates/checkpoint-prompt.md` — mid-session re-anchor template
- `templates/hard-rules-injection.md` — end-of-prompt recency anchor template

## Related

- `~/.claude/skills/_meta/hard-rules-checklist.md` — the structural anchor this skill builds on
- `~/.claude/skills/development-lifecycle/` — TDD + verification gate enforcement
- `~/.claude/skills/forge/SKILL.md` — references this skill at design checkpoints
- `~/.claude/skills/bob.md` (agent) — references this skill before claiming complete
- `~/.claude/skills/alf.md` (agent) — references this skill in evolution sweeps
