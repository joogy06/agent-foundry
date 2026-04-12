# Forge Handshake — The Scope→Launch Handoff Contract

How the founder family hands off to `forge` when the user is ready to build. This document
captures both sides of the contract, with explicit Phase 1 vs Phase 2 split.

---

## The Problem

Two failure modes motivate this handshake:

1. **User enters via forge with "build me a startup".** forge is the global creative router —
   it matches first and drops the user into design-team machinery WITHOUT validation. The user
   ends up with a beautifully architected product for a problem nobody has.

2. **founder-sprint (Phase 2) calls forge at the Scope→Launch gate, but user entered via
   forge.** If founder calls forge, and forge is already the caller, we get forge → founder →
   forge recursion.

The handshake solves both by explicitly defining who owns what and when control transfers.

---

## Contract

### Founder owns

- **Pre-execution.** Ideation (what to build), validation (is it real), business model (will it
  pay), GTM (how to reach them), sprint (coordination of the above).
- **Venture state.** `.founder/venture-brief.yaml` is the single source of truth for everything
  about the venture. Forge reads from it, doesn't write to it.
- **The decision to build.** Founder (with the user) decides when the idea is ready for execution.
- **Preparing the forge brief.** The `forge_brief` field in venture-brief is populated by
  founder before handoff — it contains the distilled problem statement, constraints, success
  criteria, and ruled-out approaches.

### Forge owns

- **Execution.** From "we are building this" onwards — design team, contract map, component
  decomposition, bob handoff, agent-teams orchestration, verification, delivery.
- **Architecture decisions.** Founder does not design the architecture. Forge does.
- **Code.** Founder never writes code. Forge (via bob, via agent-teams) writes code.

### Neither owns

- **Legal / tax / securities.** Hard refused by founder (HR-1, HR-2). Not forge's job either.
- **Fundraising advice.** Same. Not forge's job.

---

## The handoff moment

The handoff happens when ALL of these are true:

1. `venture-brief.yaml.ideas_considered[]` has at least one entry with `status: validated`
2. `venture-brief.yaml.ideas_considered[<validated>].kill_criteria` is populated (HR-4)
3. `venture-brief.yaml.ideas_considered[<validated>].first_experiment` has been run and is
   documented in `experiments[]` (Phase 2)
4. `venture-brief.yaml.ideas_considered[<validated>].data_sources` has ≥1 entry (HR-5)
5. `venture-brief.yaml.forge_brief` is populated with:
   ```yaml
   forge_brief:
     problem: string                 # the problem statement, distilled from ideation
     constraints: list[string]       # what forge must respect (tech, budget, time, legal)
     success_criteria: list[string]  # what "built" means — specific, testable
     ruled_out_approaches: list[string]  # approaches cross-fire killed, with reasoning
   ```
6. `venture-brief.yaml.forge_handoff_ready: true`

If any of these fails, founder refuses the handoff and tells the user what's missing.

---

## The forge_brief format

When populated, `forge_brief` is passed to forge as the problem statement. Example:

```yaml
forge_brief:
  problem: |
    Build a SaaS for FX-delta-aware bank-feed reconciliation targeted at UK accounting
    practices with 1-5 employees handling multi-currency client portfolios. Existing
    tools (Xero, QBO) handle multi-currency poorly for gain/loss delta accounting,
    which is the specific wedge.
  constraints:
    - "Solo bootstrap for year 1 (no VC capital)"
    - "Must integrate with HMRC Making Tax Digital phase-4 APIs"
    - "UK and EU GDPR compliance from day 1 (user data includes client financial records)"
    - "Python stack (user's existing skill)"
    - "MVP budget: single-person time across 8-12 weeks"
  success_criteria:
    - "Validated with 3 beta practices from user's network in first 4 weeks"
    - "Pre-revenue: 2 practices commit to £80/mo before code ships"
    - "Post-MVP: 10 practices paying within 6 months of public launch"
    - "Correctly reconciles FX delta for 95%+ of ingested transactions across test data"
  ruled_out_approaches:
    - "Mobile app first — practice bookkeepers work on desktop, mobile is a distraction"
    - "General-purpose bookkeeping (Xero/QBO competitor) — no wedge, saturated market"
    - "Accountant marketplace model — wrong business type for the user's assets"
    - "AI-first (LLM-bookkeeper) — unit economics don't work for £80/mo tier + hallucination risk"
```

---

## Phase 1 — What ships now

### Founder side (this skill family, this bob run)

- `venture-brief.yaml.forge_brief` schema is documented (see
  `references/venture-brief-schema.md`)
- `venture-brief.yaml.forge_handoff_ready` flag is documented
- Parent skill mentions the handshake in its routing table ("Build me an MVP → Hand off to
  forge via Scope→Launch artifact")
- `founder-ideation` populates `ideas_considered[]` per the schema — downstream subskills
  (Phase 2) will populate `experiments[]`, `validation_report`, and `forge_brief`

### Forge side (WP-F6 text patches only — no behavior change)

- `forge/SKILL.md` Checklist Step 3 (clarifying questions): "If the request is 'I have a startup
  idea' / 'generate ideas' / 'validate my idea' / pre-execution founder intent — route to
  `founder` skill first. Founder will hand back at the Scope→Launch gate when ready for
  execution."
- `forge/SKILL.md` Red Flags: "Starting design-team exploration before the user has validated
  their idea via `founder-validation` (Phase 2) / `founder-ideation` (Phase 1)"
- **No code / behavior change** in forge. Phase 1 is pure text patch.

### What Phase 1 does NOT do

- Forge does NOT auto-read `venture-brief.yaml` on session start
- Forge does NOT treat `forge_handoff_ready: true` as a trust signal
- Founder does NOT invoke forge via any programmatic handoff
- Founder-sprint (the coordinator that would actually trigger the handoff) does NOT exist yet —
  it's Phase 2

---

## Phase 2 — Planned

### Founder side

- Ship `founder-validation` (Mom Test, assumption ledger, browser-MCP outreach)
- Ship `founder-business-model` (calculator mode unit economics)
- Ship `founder-gtm` (positioning, distribution-first)
- Ship `founder-sprint` — the stage machine (Diagnose → Test → Scope → Launch) that actually
  triggers the handoff to forge
- Extend `venture-brief.yaml` schema to `schema_version: 2` with `assumptions[]`, `experiments[]`,
  `validation_report`, `business_model`, `gtm_plan`, `sprint_state`
- Ship a migration helper for schema v1 → v2

### Forge side (separate forge cycle, NOT piggybacked on founder)

- Teach forge to read `.founder/venture-brief.yaml` on session start
- When `forge_handoff_ready: true`:
  - Skip early exploration (problem statement is already distilled)
  - Skip some clarifying questions (constraints are already captured)
  - Treat `ruled_out_approaches` as hard "do not explore" signals in design team
- When `forge_handoff_ready: false`:
  - If design is a pre-execution topic, route to founder instead
  - This is the real behavior change — must be scoped and designed in a separate forge cycle

### Recursion prevention

When forge reads `venture-brief.yaml.last_subskill == "founder-sprint"` and
`forge_handoff_ready: true`, forge sets a session flag `came_from_founder: true`. This blocks
forge from routing BACK to founder for the same venture in the same session. No loops.

---

## Reverse handoff — forge back to founder

After bob finishes execution, the control transfers back to forge. Forge does NOT call founder
again automatically — that's the user's decision. If the user wants to iterate (post-launch
validation, pivot consideration, GTM planning), THEY invoke founder in a new session.

The design principle: each handshake is a deliberate user action, not automatic background
routing. This prevents drift from intended scope.

---

## Integration with other skills (via founder routing)

Founder also routes to non-forge skills for specific tasks. These are NOT "handoffs" in the
Scope→Launch sense — they're lightweight delegations:

| User intent | Delegates to | Contract |
|---|---|---|
| Pitch deck | `presentation-builder` with `yc-pitch` / `sequoia-pitch` flow | Pass `venture-brief.yaml` as input context; the narrative flows will read from it |
| Landing copy | `content-writer` + `conversion-psychology` | Pass product description + target persona from `venture-brief.yaml` |
| SEO strategy | `seo-content-strategist` + `seo-keyword-strategist` | Pass niche + product description |
| Webstore questions (GamingBuilds-specific) | `entrepreneur-webstore` | Separate venture — not this one |
| "Should I leave my job" | `career-transition` | Separate domain — career, not venture |

These delegations don't invoke the forge handoff. They're just routing to the right specialist
for a specific task.

---

## What to tell the user at the handoff moment

When all 6 handoff conditions are met and the user confirms they want to build:

> "OK — you've got an idea with kill criteria, a first experiment, data grounding, and a clear
> problem statement. I'm handing this off to `forge` for execution. Forge will take the
> `forge_brief` from your venture-brief, run its design team with dual challengers, write a
> spec, and spawn `bob` to orchestrate the build.
>
> From here, you're out of the founder family and into the execution cascade:
> `forge → bob → agent-teams → team-manager → specialists`.
>
> If you need to come back for post-launch validation, pivot consideration, or GTM work, invoke
> `founder` again with the same venture-brief."

Then invoke forge (Phase 2 — in Phase 1, instruct the user to invoke forge manually with the
brief).
