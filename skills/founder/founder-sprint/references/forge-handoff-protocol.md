# Forge Handoff Protocol

How `founder-sprint` hands off to `forge` at the Handoff stage. Defines the explicit spawn
prompt, the `came_from_founder` flag, and what forge does on receipt.

---

## The Handoff Moment

All of these must be true before sprint triggers the handoff:

1. All 3 prior stages completed (`stage_completed_at` has diagnose, evidence, decision timestamps)
2. `forge_brief` populated with all required fields (problem, solution, success_criteria, non_goals)
3. User gives explicit "ship it" / "build it" / "let's go" confirmation

---

## Spawn Prompt Template

Sprint constructs this spawn prompt and passes it to forge:

```
came_from_founder: true
venture_brief_path: .founder/venture-brief.yaml

forge_brief:
  problem: |
    <from venture-brief.forge_brief.problem>
  solution: |
    <from venture-brief.forge_brief.solution>
  success_criteria:
    <from venture-brief.forge_brief.success_criteria>
  non_goals:
    <from venture-brief.forge_brief.non_goals>
  complexity_hint: <from venture-brief.forge_brief.complexity_hint>
  open_questions:
    <from venture-brief.forge_brief.open_questions>

Prior founder exploration:
  ideas_considered: <count> ideas evaluated via adversarial brainstorm
  assumptions_tested: <count> assumptions with evidence
  interviews_conducted: <interview_count>
  business_model_verdict: <decision_verdict>
  pivots: <count> pivots during validation
```

---

## What Forge Does on Receipt

When forge receives `came_from_founder: true`:

1. **Read the forge_brief** from the spawn prompt (NOT from venture-brief.yaml directly)
2. **Skip "what are we building?" questions** — `forge_brief.problem` is the pre-clarified task
3. **Use `success_criteria` as constraints** for design agents
4. **Use `non_goals` as explicit scope boundaries** (design agents must not explore these)
5. **Use `complexity_hint`** to seed Step 4 complexity assessment
6. **Ask ONLY `open_questions`** in Step 3 (skip all other clarifying questions)
7. **Include prior founder exploration** in `shared_context` for design agents:
   - `ideas_considered` and `assumptions` as background ("this was already validated")
   - `experiments` as evidence ("here's what we know from real-world testing")
   - `business_model` as constraints ("pricing and unit economics already explored")

---

## What Forge Does NOT Do

- Forge does NOT read `.founder/venture-brief.yaml` at session start without `came_from_founder`
- Forge does NOT auto-discover or auto-read venture-brief.yaml
- Forge does NOT route back to founder (no recursion — came_from_founder blocks re-routing)
- Forge does NOT modify venture-brief.yaml (founder owns venture state; forge owns execution)

---

## Recursion Prevention

Sprint sets `came_from_founder: true` in the spawn prompt. Forge detects this flag and:
1. Does NOT check for founder-intent routing (Step 3 of forge checklist)
2. Does NOT route to founder skill
3. Proceeds directly with the pre-clarified task

This prevents: user says "build it" -> sprint calls forge -> forge detects "startup intent" ->
forge routes to founder -> founder calls sprint -> infinite loop.

---

## After Handoff

Once forge takes over:
- Sprint is done. Its job was to get to this point.
- Forge runs its full cycle: design team, challengers, spec, bob, agent-teams, etc.
- User can re-invoke founder later (new session) for post-launch validation, pivot, GTM planning
- The venture-brief remains intact as a historical record

---

## User-Facing Message at Handoff

Sprint presents this to the user at the handoff moment:

> "Your venture has passed all gates:
>
> - **Diagnose:** [N] ideas evaluated, 1 selected, [M] assumptions listed
> - **Evidence:** [X] experiments run, [Y] interviews conducted, key assumptions tested
> - **Decision:** Business model analyzed — [verdict] at $[price]/mo, [key metric]
>
> Ready to hand off to forge for execution. Forge will:
> 1. Read your forge_brief (problem, solution, success criteria, non-goals)
> 2. Run its design team with dual challengers
> 3. Write an architecture spec
> 4. Spawn bob to orchestrate the build
>
> From here, you're in the execution cascade: forge -> bob -> agent-teams -> specialists.
>
> To come back for post-launch validation or pivoting, invoke `founder` again.
>
> Confirm: ship it?"
