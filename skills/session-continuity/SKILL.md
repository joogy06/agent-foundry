---
name: session-continuity
description: Use when a working session has run long enough that quality may be degrading, or before it does — detecting the signals that precede degradation, choosing between compacting, clearing and restarting, writing a handover that survives the reset, and resuming without re-deriving everything. Covers why automatic compaction fires too late to be trusted, how to schedule checkpoints without depending on cron, and what can honestly be automated versus what needs a person.
disambiguation: The SESSION lifecycle — degradation, checkpointing, handover, restart, resume. Spinning an out-of-scope task off into its own session is handoff; keeping to the original instructions within a session is anti-drift; condensing a document is summarize; what the PROJECT is remains project-profile.
---

# Session continuity

Long sessions degrade. This is how to notice before it costs you, and how to reset without losing
the thread.

## 1. The trap: automatic compaction fires too late

**Auto-compaction triggers when context approaches the window limit — around 80%. By then the model
is already operating in a degraded state, so the summary it writes is itself produced under degraded
conditions.** You get a worse summary exactly when you most need a good one, and everything after it
inherits that.

**Compact proactively, at roughly 60% utilisation, while recall is still clear.** The difference is
not marginal: a summary written with headroom preserves decisions and reasoning; one written at the
limit preserves whatever survived the squeeze.

**Never treat auto-compaction as the plan.** It is the safety net for when you forgot.

## 2. Degradation signals — in the order they appear

| Signal | What it looks like |
|---|---|
| **Vagueness** (~1 hour of active work) | Answers get general; specifics from earlier stop being cited |
| **Re-deriving** | Re-reads a file it already read, re-asks something already settled |
| **Contradiction** (~2 hours) | Reverses a decision made earlier in the same session, without noticing |
| **Instruction slip** | Drops a standing constraint — the `anti-drift` failure mode |
| **Topic bleed** | Detail from an unrelated earlier task leaks into the current answer |
| **Hedging** | More qualifiers, fewer commitments, longer answers saying less |

**Contradiction is the hard stop.** Vagueness is a prompt to checkpoint; contradicting a settled
decision means the session can no longer be trusted on anything it decided, and the fix is a restart
with a handover, not another correction.

**Content diversity matters as much as volume.** A session that stayed on one task degrades far more
slowly than one that touched five. **Unrelated tasks are the strongest argument for `/clear`**, not
`/compact` — a clean session with a well-formed prompt reliably beats a long one carrying accumulated
corrections.

## 3. Choosing the reset

| | Keeps | Use when |
|---|---|---|
| **`/compact`** | A summary of this session | Same task, continuing; approaching ~60% |
| **`/clear`** | Nothing | **Switching to unrelated work** |
| **Restart + handover** | A written document | Long task spanning sessions; degradation already visible |

**The decision rule:** *is the next work continuous with this session's work?* If yes, compact. If no,
clear. If yes but the session is already showing §2 signals, restart with a handover — compacting a
degraded session preserves the degradation.

## 4. Checkpointing without a scheduler

Cron exists on some machines and is unavailable or restricted on many enterprise ones, so **nothing
here may depend on it.** In descending order of portability:

**(a) Poll-on-use — the portable default.** Check elapsed time and turn count whenever something is
already running: a gate, a hook, a build task. No scheduler, no daemon, no background process. It
costs nothing because it rides work that was happening anyway.

```bash
python3 ~/.claude/skills/session-continuity/scripts/checkpoint.py --check
```

**(b) A session-start hook** that reads the continuity file and reports its age. Where SessionStart
hooks exist (Claude Code), this makes resumption automatic. Where they do not (VS Code), it becomes a
task or an agent instruction — `vs-code/docs/startup.md`.

**(c) A user-run watcher** started deliberately alongside the session and stopped with it. Portable,
but it is a process someone has to remember; treat it as opt-in.

**(d) `cron` / `systemd --user` timers — optional only.** Fine on a personal machine, unavailable or
locked down in many enterprises. **Never make the mechanism depend on it**; if it is present it is an
accelerator, not the foundation.

**On headless invocation (`claude -p`) as an automation route —** it consumes the same quota as
interactive use rather than being free background capacity, so a polling loop built on it spends real
budget. Confirm current billing before relying on it, and prefer (a), which spends nothing.

## 5. The handover document

A handover is what makes a restart cheap. Write it **before** you need it — one composed while
degraded is exactly as degraded as the session.

```
# Handover — <task> — <date/time>

## Goal
What we are trying to achieve, and what "done" looks like.

## Decisions taken (and WHY)
- <decision> — because <reason>; would reverse if <condition>

## State
Done: <what is finished and verified>
In progress: <what is half-done, and precisely where>
Next: <the immediate next action>

## Constraints and gotchas
<what was learned the hard way — the things a fresh session would repeat>

## Files touched
<paths, so the next session does not re-explore>

## Open questions
<what is unresolved, and what would settle it>
```

**"Decisions and WHY" is the section that pays.** Without reasons, a fresh session re-litigates them
and often decides differently — the same rule `project-profile` applies to project decisions.

**Verified state, not claimed state.** "Tests pass" belongs in the handover only if they were run;
otherwise it seeds a false premise into a session that cannot check it.

## 6. What can honestly be automated

| Can automate | Cannot automate |
|---|---|
| Measuring elapsed time, turns, files touched | Judging whether answers have got worse |
| Warning at a threshold | Deciding compact vs clear vs restart |
| **Templating** the handover with observable state | Writing decisions and their reasons |
| Detecting a stale continuity file | Confirming the handover is accurate |
| Reminding at a milestone | Noticing a contradiction |

**Degradation detection is proxy-based, and the proxies are weak.** Elapsed time and context
percentage correlate with degradation; they do not measure it. **The reliable detector is a human
noticing an answer got worse** — so automation's job is to prompt the check, never to declare the
verdict.

A tool that announced "quality is degraded" from a token count would be wrong often enough to be
ignored, and then wrong when it mattered.

## 7. A working rhythm

- **Every 30–45 minutes of active work, or at each milestone** — checkpoint: update the handover,
  compact if continuing.
- **On task switch** — `/clear`, and open with a specific prompt carrying forward what you learned.
- **At the first contradiction** — stop, write the handover, restart. Do not correct and continue.
- **At session end** — write the handover even if you think you are finished. You are usually not.

## 8. Anti-patterns

- **Relying on auto-compaction**, which fires when the model is already degraded.
- **Compacting a session that has already contradicted itself** — it preserves the damage.
- **`/compact` on a task switch** where `/clear` is right.
- **Writing the handover while degraded.**
- **Handover without reasons** — guarantees re-litigation.
- **Claiming state in a handover that was not verified.**
- **Depending on cron** for a mechanism that must work in a locked-down environment.
- **Automating the verdict** rather than the prompt to check.
