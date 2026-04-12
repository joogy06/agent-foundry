# Narrative Flows

Reference catalog of narrative frameworks used by `presentation-narrative` for slide outline
generation. Each flow is a structured template the skill selects based on audience + purpose
(see `presentation-narrative/SKILL.md` Section 1 for the selection matrix).

**Status:** This reference is incrementally populated. Phase 1 (WP-F8) introduces the
`yc-pitch` and `sequoia-pitch` flow stubs for the founder family integration. Other flows
referenced in the SKILL.md selection matrix (e.g., `minto-scr`, `pyramid-principle`,
`situation-complication-resolution`, etc.) are expected to be added as `presentation-narrative`
matures.

---

## yc-pitch (10-slide YC Demo Day format)

**Audience:** Investors (YC partners, Demo Day audience, follow-on VCs)
**Purpose:** Seed-stage pitch for a YC-style batch investor audience — short, punchy, data-first
**Slide count:** 10
**Time:** 2-3 minutes speaking + Q&A
**Reads from:** `.founder/venture-brief.yaml` when the founder family is active — populates
problem, solution, traction, team, ask fields from the brief.

### Slide-by-slide template

```
Slide 1: Title + One-Liner
  - Product name + memorable one-line positioning
  - e.g. "Acme — reconciliation SaaS for UK accountants handling multi-currency"
  - Team (founder names)
  - Batch (YC batch identifier)

Slide 2: The Problem
  - Specific, named pain (NOT "accounting is hard")
  - Quantified if possible ("UK practices spend ~12 hours/month on FX reconciliation")
  - WHO has the pain (specific persona)
  - Cited from venture-brief.ideas_considered[validated].data_sources

Slide 3: The Solution
  - What you built (1-sentence)
  - How it works (1-2 sentences)
  - Why it's 10x not 10% better
  - Demo image or screenshot

Slide 4: Why Now
  - What changed that makes this possible RIGHT NOW
  - Regulatory / technology / market shift enabling the timing
  - Cited if possible from venture-brief GDELT inflection data

Slide 5: Traction
  - Real numbers — users, revenue, growth rate
  - Pre-revenue: LOIs, waitlist, beta commitments
  - Growth curve chart [CHART: growth over time]

Slide 6: Business Model
  - How you make money (pricing tier)
  - Unit economics — one sentence ("CAC £X, LTV £Y, payback Z months")
  - Revenue trajectory assumption

Slide 7: Market
  - TAM/SAM/SOM — calculator mode only, user-supplied inputs
  - Hard rule: if venture-brief has no TAM inputs, this slide shows "TAM: calculated from
    [inputs]" and refuses to fabricate numbers
  - Why this market, why now

Slide 8: Competition / Differentiation
  - Who else is in the space (named incumbents)
  - Why you win (counter-positioning from venture-brief contrarian team output if available)
  - Moat / defensibility

Slide 9: Team
  - Why THIS team can execute this
  - Relevant background + unfair advantage from venture-brief.intake.user_assets
  - Advisors / early backers

Slide 10: Ask
  - Amount raising
  - Use of funds (3-4 bullets)
  - Milestone you'll hit with this round
  - CTA — contact info
```

### Data binding from venture-brief.yaml

When founder family is active and `venture-brief.yaml` exists:

| Slide | Populated from |
|---|---|
| 1. Title | `intake.niche` + `ideas_considered[validated].content` |
| 2. Problem | `ideas_considered[validated].content` + `data_sources` |
| 3. Solution | `ideas_considered[validated].content` + `first_experiment` |
| 4. Why Now | `ideas_considered[validated].data_sources` (GDELT entries) |
| 5. Traction | `experiments[].result` (Phase 2); Phase 1 = user input |
| 6. Business Model | `business_model` (Phase 2); Phase 1 = user input (calculator mode only, HR-3) |
| 7. Market | `business_model.tam_inputs` (Phase 2); Phase 1 = user input (HR-3) |
| 8. Competition | `ideas_considered[validated].attack_history` (contrarian team critiques used as positioning) |
| 9. Team | `intake.user_assets` |
| 10. Ask | user input only |

**HR-1 / HR-3 reminder:** this flow MUST NOT fabricate TAM, valuation, or financials. Slides 6-7
are user-input-only; the flow prompts the user if venture-brief has no data, refuses to generate
placeholder numbers.

### Narrative Construction Rules

When constructing the yc-pitch narrative:

1. **Slide 1 (Title):** Pull from `intake.niche` + selected idea content. If venture-brief
   is missing, prompt the user for a one-liner.
2. **Slide 2 (Problem):** MUST cite a real data source from `ideas_considered[validated].data_sources`.
   If no data source exists, show `[PROBLEM: cite real data — do not fabricate]`.
3. **Slide 3 (Solution):** Pull from selected idea content + first_experiment description.
4. **Slide 4 (Why Now):** Use GDELT inflection data from `data_sources` if available. If not,
   prompt user: "What changed recently that makes this possible now?"
5. **Slide 5 (Traction):** Phase 2: reads `experiments[].evidence` for real metrics. Pre-validation:
   show `[TRACTION: user to supply — pre-revenue metrics, waitlist, LOIs]`.
6. **Slide 6 (Business Model):** Phase 2: reads `business_model` block with ranges and tags.
   Show confidence tags (observed/assumed/target). NEVER fabricate numbers (HR-BM1).
7. **Slide 7 (Market):** Calculator mode only (HR-3). If `business_model.tam_inputs` missing,
   show `[MARKET SIZE: user to supply inputs for calculator mode]`. REFUSE to fabricate TAM.
8. **Slide 8 (Competition):** Use `attack_history` from contrarian team if available. Otherwise
   prompt user for competitor names.
9. **Slide 9 (Team):** Pull from `intake.user_assets`. Highlight founder-market fit.
10. **Slide 10 (Ask):** Always user input. NEVER auto-generate valuation (HR-1).

### Degraded Mode

When venture-brief fields are missing, the flow degrades gracefully:
- Missing field -> placeholder: `[FIELD_NAME: user to supply]`
- Missing data source -> warn: "This slide lacks data grounding — strengthen before presenting"
- Missing business_model -> skip unit economics, show `[UNIT ECONOMICS: run founder-business-model first]`

### Status

**Phase 1:** Flow definition + data binding table.
**Phase 2 (current):** Full specification with narrative construction rules, degraded mode,
and Phase 2 field bindings (experiments, business_model, forge_brief). Wired to
`founder-sprint` at the fundraising-prep stage via `presentation-builder` with
`flow: "yc-pitch"`, passing `venture-brief.yaml` as input context.

---

## sequoia-pitch (10-slide Sequoia Business Plan format)

**Audience:** Investors (Sequoia partners, institutional VCs, structured investor audiences)
**Purpose:** Institutional-grade business plan pitch, more detailed than YC's Demo Day format
**Slide count:** 10 (Sequoia's canonical template)
**Time:** 15-30 minutes presenting + deep Q&A
**Reads from:** `.founder/venture-brief.yaml` same as yc-pitch

### Slide-by-slide template

Based on the well-known Sequoia Capital "Writing a Business Plan" template:

```
Slide 1: Company Purpose
  - Define the company's business in a single declarative sentence
  - Not feature list — mission
  - "We reconcile FX-delta-aware bank feeds for UK accounting practices handling multi-currency
     client portfolios."

Slide 2: Problem
  - Describe the pain of the customer (or customer's customer)
  - Outline how the customer addresses the issue today
  - Populated from venture-brief.ideas_considered[validated].data_sources

Slide 3: Solution
  - Demonstrate your company's value proposition to make customer's life better
  - Show where your product physically sits
  - Provide use cases

Slide 4: Why Now
  - Set up the historical evolution of your category
  - Define recent trends that make your solution possible
  - Populated from venture-brief GDELT inflection data

Slide 5: Market Size
  - Identify/profile the customer
  - TAM/SAM/SOM in CALCULATOR mode (HR-3) — user-supplied inputs only
  - Refuses to fabricate market sizes if venture-brief has no inputs

Slide 6: Competition
  - List competitors
  - List competitive advantages
  - From venture-brief attack_history (what the contrarian team said about incumbents)

Slide 7: Product
  - Product line
  - Features and functions
  - Intellectual property
  - Development roadmap

Slide 8: Business Model
  - Revenue model
  - Pricing
  - Average account size and/or lifetime value
  - Sales & distribution model
  - Customer/pipeline list

Slide 9: Team
  - Founders and Key Team Members
  - Board of Directors / Board of Advisors
  - Investors

Slide 10: Financials
  - P&L
  - Balance sheet
  - Cash flow
  - Cap table
  - The deal
  - HR-1 / HR-3: financials must be user-supplied; no LLM-generated valuation, no cap table advice
```

### Data binding from venture-brief.yaml

Same pattern as yc-pitch. The sequoia-pitch is longer and expects more structured business model
+ financials sections — it assumes the user has done `founder-business-model` work first (Phase 2).

### Narrative Construction Rules

When constructing the sequoia-pitch narrative:

1. **Slide 1 (Company Purpose):** Derive from `forge_brief.problem` + selected idea. If missing,
   prompt: "Define your company's business in one sentence."
2. **Slide 2 (Problem):** Same data binding as yc-pitch slide 2. Cite real data source (HR-5).
3. **Slide 3 (Solution):** Pull from selected idea + forge_brief.solution. Include use cases
   from validation evidence if available.
4. **Slide 4 (Why Now):** Same as yc-pitch slide 4 — GDELT inflection data preferred.
5. **Slide 5 (Market Size):** CALCULATOR MODE ONLY (HR-3). User supplies: avg revenue per
   customer, reachable customers in named segment, penetration assumption. Show arithmetic +
   assumption table. REFUSE to fabricate market sizes.
6. **Slide 6 (Competition):** Use `attack_history` from adversarial brainstorm contrarian team.
   List named incumbents and counter-positioning. If no attack_history, prompt user.
7. **Slide 7 (Product):** Pull from forge_brief if available. Product line, features, IP
   (show `[IP: see patent counsel]` for deep-tech mode per HR-2).
8. **Slide 8 (Business Model):** Phase 2: reads `business_model` block with ranges (HR-BM5).
   Show confidence tags. Revenue model + pricing + unit economics ranges. NEVER single-point
   estimates.
9. **Slide 9 (Team):** Pull from `intake.user_assets`. Founder-market fit emphasis.
10. **Slide 10 (Financials):** Show contribution margin RANGES only (HR-BM5). NOT projections.
    NOT valuation (HR-1). NOT cap table advice (HR-1). If user has no financials:
    `[FINANCIALS: run founder-business-model first, then supply observed data]`.

### Degraded Mode

Same as yc-pitch: missing fields degrade to placeholders, not fabrication.

### Sequoia-Specific Depth

The sequoia-pitch expects MORE depth than yc-pitch on:
- Competition (slide 6): detailed competitive landscape, not just one differentiator
- Product (slide 7): feature roadmap, IP landscape (without legal advice)
- Business Model (slide 8): multi-line revenue model, not just one pricing tier
- Financials (slide 10): P&L structure (user-supplied ranges), NOT LLM-generated projections

If the user has not completed `founder-business-model`, slides 8 and 10 will be heavily
degraded. Recommend running calculator mode first.

### Status

**Phase 1:** Flow definition + data binding table.
**Phase 2 (current):** Full specification with narrative construction rules, degraded mode,
sequoia-specific depth requirements, and Phase 2 field bindings. Wired to `founder-sprint`
at the fundraising-prep stage.

### HR reminders (both flows)

- **HR-1** (no valuation / cap table / securities advice) — slides 9-10 of sequoia-pitch and
  slide 10 of yc-pitch must NOT fabricate cap table or valuation data. If the user hasn't
  supplied numbers, the flow shows a placeholder like `[FINANCIALS: user to provide]` and moves
  on.
- **HR-2** (no legal / tax / regulatory advice) — slide 7 of sequoia-pitch (IP) must NOT advise
  on patent strategy; it displays "[IP: see patent counsel]" for users in deep-tech mode.
- **HR-3** (no LLM-generated TAM) — slides 5 of sequoia-pitch and 7 of yc-pitch are
  calculator-mode only; user provides inputs, flow shows the arithmetic + assumption table.

---

## Other flows (stubs to be expanded in future skill updates)

The following flows are referenced in `presentation-narrative/SKILL.md` Section 1 selection
matrix but not yet fully documented here. They will be added in subsequent updates:

- `minto-scr` — Minto Pyramid / Situation-Complication-Resolution (executive recommendation)
- `pyramid-principle` — Barbara Minto's pyramid (consulting / executive synthesis)
- `status-risks-next` — status update (project / steering committee)
- `bluf` — Bottom Line Up Front (military / executive)
- `situation-complication-resolution` — McKinsey SCR (strategic narrative)
- `adr-presentation` — Architecture Decision Record as presentation
- `rfc-design-review` — Request for Comments / design review
- `problem-demo-architecture-next` — technical demo flow
- `show-and-tell` — engineering show-and-tell
- `aida` — Attention / Interest / Desire / Action (sales)
- `hook-problem-solution-proof-cta` — startup pitch / landing page narrative
- `problem-solution-benefit` — proposal / SOW
- `before-during-after` — change / transformation narrative
- `heros-journey` — inspirational / vision narrative
- `tell-show-do-review` — training / enablement
- `progressive-disclosure` — training / documentation
- `exec-deepdive-appendix` — banking / regulatory / compliance
- `kawasaki-10-20-30` — Guy Kawasaki's 10 slides / 20 min / 30pt font rule
- `ignite` — Ignite format (5 min, 20 slides, 15s each)
- `pecha-kucha` — Pecha Kucha (20 slides × 20 seconds)
- `timeline-retrospective` — retrospective with timeline
- `what-so-what-now-what` — retrospective / learning review

These will be added incrementally as `presentation-narrative` receives updates. Callers that name
a flow not yet documented should fall back to the closest documented flow OR ask the user to
clarify.
