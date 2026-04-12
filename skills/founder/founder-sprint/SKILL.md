---
name: founder-sprint
description: >
  Use when the user asks to run a structured venture sprint, check their stage, advance to the
  next phase, hand off to forge for execution, or asks "what should I do next" in the context of
  building a venture. Phase 2 subskill of the founder family. Lean gatekeeper and state machine:
  Diagnose -> Evidence -> Decision -> Handoff. Gate enforcement, next-subskill picker. NOT a
  planner, NOT an executor. Routes via parent `founder` skill. Trigger on: "run a sprint",
  "where am I", "what's next", "advance to next stage", "hand off to forge", "am I ready to
  build", "check my gates", "sprint status".
---

# Founder Sprint (Phase 2)

Child of `founder`. Lean gatekeeper and state machine managing the founder journey from idea to
forge handoff. Four stages with gate enforcement. Picks the next subskill. Updates venture-brief.
NOT a planner, NOT an executor -- a gatekeeper.

**Scope:** Stage management and gate enforcement only. Sprint picks the right subskill to invoke,
checks gate criteria, and advances the venture-brief state. It does NOT do task decomposition,
work package creation, owner assignment, or sequencing beyond "which subskill next." Task
decomposition is bob's job after forge takes over.

**Siblings (parent = `founder`):**
- `founder-ideation` — Phase 1 — adversarial brainstorm + data grounding
- `founder-validation` — Phase 2 — experiments, interviews, evidence capture
- `founder-business-model` — Phase 2 — calculator mode unit economics
- `founder-gtm` — Phase 3 (deferred) — positioning, distribution, channel selection

---

<HARD-RULE>
**No stage-skipping.** Sprint refuses to jump stages (e.g., Diagnose directly to Handoff).
Each stage must be completed with gate-passing evidence before advancing. Reset to an earlier
stage is allowed (e.g., Decision back to Evidence after a pivot). Skipping is never allowed.
</HARD-RULE>

<HARD-RULE>
**Brief is authoritative.** When sprint and subskills disagree on venture state, the
venture-brief.yaml file wins. Sprint reads it on entry and trusts it. Sprint does not maintain
separate state.
</HARD-RULE>

<HARD-RULE>
**Evidence or no transition.** Each gate requires artifacts (experiments with results, interview
evidence, calculator output, user acknowledgment), not assertions. "Trust me, it's validated"
does not pass a gate.
</HARD-RULE>

<HARD-RULE>
**Sprint does NOT do task decomposition.** Sprint is purely a gatekeeper — it decides which
subskill to invoke next and whether the gate criteria are met. It does NOT create work packages,
assign owners, sequence tasks, or build project plans. That is bob's job (after forge takes over
at Handoff).
</HARD-RULE>

<HARD-RULE>
**If no venture-brief.yaml exists, refuse and tell the user to run founder-ideation first.**
Sprint requires an existing brief with at least intake populated. It does not create briefs.
</HARD-RULE>

**Inherited hard rules (from parent `founder`):** HR-1 through HR-11 all apply. Additionally,
HR-V1 through HR-V5 (from validation) and HR-BM1 through HR-BM6 (from business-model) are
enforced through the subskill invocations sprint orchestrates.

---

## The Four Stages

### Stage 1: DIAGNOSE

**Question:** Is there anything worth validating?

**Invokes:** `founder-ideation` (Phase 1)

**Gate criteria:**
- [ ] venture-brief has >= 3 ranked ideas with data citations (HR-5)
- [ ] 1 idea selected (status: `candidate` or better, marked as selected)
- [ ] >= 3 assumptions listed in `venture-brief.assumptions[]`
- [ ] >= 3 kill criteria across the selected idea (HR-4)

**Venture-brief updates on stage entry:**
```yaml
sprint_state:
  stage: diagnose
```

**Venture-brief updates on gate pass:**
```yaml
sprint_state:
  stage_completed_at:
    diagnose: <timestamp>
```

**Abort condition:** All ideas scored below kill threshold by adversarial cross-fire.
```yaml
sprint_state:
  stage: aborted
  outcome: "no viable ideas — all scored below kill threshold"
  abort_reason: "adversarial cross-fire killed all candidate ideas"
```

### Stage 2: EVIDENCE

**Question:** Do we have enough evidence to commit?

**Invokes:** `founder-validation` (Phase 2)

**Gate criteria:**
- [ ] Top-3 riskiest assumptions each have >= 1 experiment with recorded evidence
- [ ] >= 1 real interview logged (`interview_count >= 1`, HR-V2)
- [ ] No high-risk viability assumption falsified without either:
  - A documented pivot (`pivots[]` entry), OR
  - An explicit `accepted_risk` disposition with user-stated reasoning

**Venture-brief updates on stage entry:**
```yaml
sprint_state:
  stage: evidence
```

**Venture-brief updates on gate pass:**
```yaml
sprint_state:
  stage_completed_at:
    evidence: <timestamp>
interview_count: <N>
```

**Abort condition:** Viability assumption falsified, user refuses pivot or accept-risk.
```yaml
sprint_state:
  stage: aborted
  outcome: "killed at evidence gate"
  abort_reason: "viability assumption '[claim]' falsified; user declined pivot"
```

### Stage 3: DECISION

**Question:** Is this a viable business we should build?

**Invokes:** `founder-business-model` (Phase 2), optionally `conversion-psychology` for CTA work

**Gate criteria:**
- [ ] `business_model` block populated in venture-brief:
  - `price` with tag
  - `unit_econ` ranges (contribution_margin at minimum)
  - `decision_rule` stated
  - `decision_verdict`: GREEN or CONDITIONAL_GO with user acknowledgment
- [ ] `forge_brief` block drafted:
  - `problem` (non-empty)
  - `solution` (non-empty)
  - `success_criteria` (non-empty list)
  - `non_goals` (non-empty list)

**Venture-brief updates on stage entry:**
```yaml
sprint_state:
  stage: decision
```

**Venture-brief updates on gate pass:**
```yaml
sprint_state:
  stage_completed_at:
    decision: <timestamp>
business_model: { ... }      # populated by founder-business-model
forge_brief: { ... }         # drafted during this stage
```

**Abort condition:** Calculator mode returns RED on decision rule AND user declines to adjust.
```yaml
sprint_state:
  stage: aborted
  outcome: "killed at decision gate — unit economics"
  abort_reason: "decision rule returned RED; user declined to adjust pricing/costs"
```

### Stage 4: HANDOFF

**Question:** Are we ready to build?

**Invokes:** Nothing — runs a checklist, flips the flag, invokes forge.

**Gate criteria:**
- [ ] All previous stages have `stage_completed_at` timestamps
- [ ] `forge_brief` populated with all required fields
- [ ] User gives explicit "ship it" confirmation

**Venture-brief updates on gate pass:**
```yaml
sprint_state:
  stage: handoff
  stage_completed_at:
    handoff: <timestamp>
forge_handoff_ready: true
handoff_at: <timestamp>
```

**Handoff method:** Sprint routes to `forge` with explicit spawn prompt:
```
came_from_founder: true
venture_brief_path: .founder/venture-brief.yaml
forge_brief:
  problem: <from venture-brief>
  solution: <from venture-brief>
  success_criteria: <from venture-brief>
  non_goals: <from venture-brief>
  complexity_hint: <from venture-brief>
  open_questions: <from venture-brief>
```

Forge reads the brief from the spawn prompt, NOT from ambient session-start discovery.

**Abort condition:** User changes mind.
```yaml
sprint_state:
  stage: handoff
  outcome: "paused at handoff"
forge_handoff_ready: false
# forge_brief remains intact for later
```

---

## Sprint Operation

### On Entry

1. Read `venture-brief.yaml`. Refuse if missing.
2. Check `schema_version`. Must be `2`. Refuse with migration guidance if `1`.
3. Read `sprint_state.stage` to determine current position.
4. If no `sprint_state` exists, initialize at `diagnose`.
5. Present current state to user:
   > "Your venture is at stage **[STAGE]**. Here's what we need to advance:
   > [list gate criteria with checked/unchecked status]"

### Advancing

1. Check ALL gate criteria for current stage.
2. If all pass: advance to next stage. Update venture-brief.
3. If some fail: show what's missing and invoke the appropriate subskill.
4. Never auto-advance through multiple stages in one invocation.

### Subskill Picker

| Current stage | Gate failing on | Invoke |
|---|---|---|
| diagnose | < 3 ranked ideas | `founder-ideation` with `generate_ideas` |
| diagnose | < 3 assumptions | Help user list assumptions (direct, no subskill) |
| diagnose | < 3 kill criteria | `founder-ideation` with `evaluate_idea` |
| evidence | Top assumptions untested | `founder-validation` with `design_experiment` |
| evidence | 0 interviews | `founder-validation` with `draft_interview` |
| evidence | Evidence uncaptured | `founder-validation` with `capture_evidence` |
| evidence | Assumption falsified | Present pivot options; if user pivots, re-run validation |
| decision | No business model | `founder-business-model` with `unit_economics` |
| decision | No forge_brief | Help user draft forge_brief (direct, uses template) |
| decision | Decision rule RED | `founder-business-model` with `what_must_be_true` |
| handoff | forge_brief incomplete | Return to decision stage |
| handoff | User not ready | Pause; record outcome |

### Resetting

User can request reset to an earlier stage:
- Reset clears the later `stage_completed_at` timestamps
- Reset does NOT delete evidence, experiments, or business model data
- Reset records a `pivots[]` entry explaining why
- Reset is an explicit user action, not automatic

---

## Cross-Stage Rules

1. **Brief is authoritative** — when sprint and subskills disagree, venture-brief.yaml wins
2. **No stage-skipping** — sprint refuses to jump. Reset allowed.
3. **Evidence or no transition** — each gate requires artifacts, not assertions
4. **Aborts are recorded** — outcome + reason written to brief so next invocation knows
5. **Sprint does NOT do task decomposition** — that's bob's job after forge takes over
6. **If no venture-brief.yaml exists** — refuse; tell user to run `founder-ideation` first

---

## Venture-Brief Integration

Sprint reads and writes the following venture-brief fields:

| Stage | Reads | Writes |
|---|---|---|
| diagnose | ideas_considered[], assumptions[] | sprint_state.stage, sprint_state.stage_completed_at.diagnose |
| evidence | assumptions[], experiments[], interview_count | sprint_state.stage, sprint_state.stage_completed_at.evidence, interview_count |
| decision | business_model, forge_brief | sprint_state.stage, sprint_state.stage_completed_at.decision, business_model, forge_brief |
| handoff | all previous + forge_brief | sprint_state.stage, forge_handoff_ready, handoff_at |
| abort | sprint_state | sprint_state.outcome, sprint_state.abort_reason |

See `references/venture-brief-state-rules.md` for the complete field-level contract.

---

## Failure Modes

| Failure | Detection | Response |
|---|---|---|
| No venture-brief | File not found | Refuse: "Run founder-ideation first to create your venture brief" |
| Schema version mismatch | schema_version != 2 | Refuse with migration guidance |
| Stage-skip attempt | User asks to jump from diagnose to handoff | Refuse: "Cannot skip stages. Current stage: [X]. Next required: [Y]." |
| Gate criteria not met | Checklist has unchecked items | Show what's missing, invoke appropriate subskill |
| Abort without reason | User wants to quit without explaining | Record outcome but require a 1-line reason |
| Subskill invocation fails | Subskill returns error | Surface the error, don't auto-retry; let user decide |
| Concurrent modification | venture-brief changed by another process | Re-read on entry; always use latest state |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Skipping Evidence stage ("I know it's valid") | Without evidence, you're building on assumptions | Enforce gate: >= 1 interview, >= 1 experiment per top assumption |
| Sprint doing task decomposition | Sprint is a gatekeeper, not a project manager | Surface what's needed; let subskills and eventually bob handle the work |
| Auto-advancing through multiple stages | Loses user control; decisions need human deliberation | One stage advance per invocation; present the next gate |
| Maintaining separate state from venture-brief | Drift between sprint's view and brief's view | venture-brief is the single source of truth (HR-7) |
| Accepting "trust me" for gate criteria | Evidence-free gates produce false confidence | Require artifacts: experiments, interviews, calculator output |
| Calling forge without explicit handoff | Ambient coupling creates stale-state bugs | Use explicit `came_from_founder: true` spawn prompt |

---

## Reference Files

Read these as needed during sprint operation:

- `references/stage-machine-spec.md` — complete state transition diagram, allowed/forbidden
  paths, edge cases
- `references/gate-criteria.md` — detailed checklist per gate with specific evidence artifacts
  required and pass/fail rubrics
- `references/venture-brief-state-rules.md` — which fields sprint reads/writes per stage,
  schema version check, migration notes
- `references/forge-handoff-protocol.md` — explicit handoff spawn prompt template,
  `came_from_founder` flag, what forge does on receipt

---

## When NOT to Use This Skill

- **User wants quick ideas without committing to a sprint** — use `founder-ideation` directly
- **User wants to validate without the stage machine** — use `founder-validation` directly
- **User wants unit economics without the stage machine** — use `founder-business-model` directly
- **User is already building (post-forge handoff)** — sprint is done; use `forge`/`bob` directly
- **User wants legal/tax/valuation advice** — REFUSED (HR-1, HR-2)
- **Sprint is optional** — users CAN invoke subskills directly without going through sprint
