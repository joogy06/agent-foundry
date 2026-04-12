# Checkpoint protocols — when and how to checkpoint

## When to checkpoint

| Trigger | Type | Action |
|---|---|---|
| Session start | Light | Read drift-symptoms.md briefly to prime detection |
| Every 50 tool calls | Standard | Re-read hard-rules-checklist.md, run symptom scan |
| Before spawning a sub-agent | Standard | Verify task brief, externalize state, anchor sub-agent |
| Before claiming task complete | Heavy | Full metacognitive audit (see below) |
| When drift symptom detected | Standard | Re-anchor immediately |
| Every 10 sub-tasks completed | Heavy | Externalize state, summarize, consider session restart |
| Before any destructive action | Standard | Re-read relevant hard rules |

## Light checkpoint (~50 tokens)

```
[CHECKPOINT] Task: <one-sentence summary of current task>. Next: <next action>.
Active constraints: <2-3 most relevant from hard-rules-checklist.md>.
```

## Standard checkpoint (~200 tokens)

1. Re-read `~/.claude/skills/_meta/hard-rules-checklist.md` (the section relevant
   to your current phase)
2. Re-read the original user message OR the task brief OR the design doc
3. Scan recent 5 messages for drift symptoms (see `drift-symptoms.md`)
4. If symptoms detected: externalize state, fix the symptom, then continue
5. If no symptoms: report "no drift detected" and proceed

## Heavy checkpoint (~500 tokens) — metacognitive audit

This is the most important checkpoint. Use before claiming any non-trivial task complete.

**Step 1: Persona switch**
"I am now a Checker, separate from the implementer. I have no investment in claiming
this task done. My job is to find gaps."

**Step 2: Re-read original requirements verbatim**
- The user's original message (do not paraphrase from memory)
- The design doc, if any
- The session_control.md, if any

**Step 3: Enumerate every requirement**
List every distinct deliverable from the requirements. Do not summarize or group —
each one is a separate row.

**Step 4: Demand evidence for each**
For each requirement, ask: "What is the tangible evidence this was done?"
- File path that was created/modified?
- Command output showing success?
- Test result showing pass?
- Build artifact?
- Visible behavior change?

If you cannot point to evidence, the requirement is NOT done.

**Step 5: Check verification artifacts**
- Tests run? Capture output.
- Lint passed? Capture output.
- Build succeeded? Capture output.
- Grep clean for forbidden patterns? Capture output.

**Step 6: Spot the gap**
Any requirement with no evidence is the gap. Stop the audit. Address the gap.
Then re-run the audit from Step 1.

**Step 7: Only after zero gaps, claim complete**
Even then, present the evidence to the user. Don't say "done" — say "here's what
was done, with the evidence: [list]".

## Anti-pattern: skipping the audit

The audit feels redundant when you're confident. That's exactly when drift happens.
Always run the audit. The few minutes it takes is far cheaper than producing wrong
output.
