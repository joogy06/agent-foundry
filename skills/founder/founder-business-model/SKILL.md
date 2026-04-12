---
name: founder-business-model
description: >
  Use when the user asks about unit economics, pricing strategy, contribution margin, LTV/CAC,
  payback period, "what should I charge", "will this business work financially", or any pre-execution
  business model question. Phase 2 subskill of the founder family. Calculator mode: helps founders
  think with incomplete numbers. Contribution margin, pricing sensitivity, payback intuition,
  "what must be true" thresholds. Never invents numbers. Tolerates uncertainty. Modes: unit_economics,
  pricing_explorer, what_must_be_true, scenario_table. Routes via parent `founder` skill. Trigger on:
  "unit economics", "what should I charge", "pricing", "contribution margin", "LTV", "CAC",
  "payback period", "will this make money", "business model", "revenue model", "calculator mode".
---

# Founder Business Model (Phase 2)

Child of `founder`. Calculator mode: helps founders think with incomplete numbers. Contribution
margin, pricing sensitivity, payback intuition, "what must be true" thresholds. Never invents
numbers. Tolerates uncertainty. Every output is a range, not a point estimate.

**Scope:** Pre-execution business model analysis. Produces ranges, sensitivity analysis, scenario
tables, and decision rule verdicts. Does NOT produce financial projections, fundraising materials,
or valuations. Does NOT advise on legal/tax/securities matters.

**Siblings (parent = `founder`):**
- `founder-ideation` — Phase 1 — adversarial brainstorm + data grounding
- `founder-validation` — Phase 2 — experiments, interviews, evidence capture
- `founder-sprint` — Phase 2 — lean gatekeeper stage machine
- `founder-gtm` — Phase 3 (deferred) — positioning, distribution, channel selection

---

<HARD-RULE id="HR-BM1">
**Never present a number the user did not supply or that was not derived from user-supplied
numbers via a visible formula.** No LLM-generated revenue projections. No fabricated market
sizes. No invented customer counts. If a number appears in the output, it traces back to a
user-supplied input or to arithmetic the user can verify.
</HARD-RULE>

<HARD-RULE id="HR-BM2">
**Every derived number comes with: formula, inputs used, sensitivity range (+-20%), and
confidence tag based on input provenance.** A derived number without its derivation chain is
unverifiable. The user must be able to check every calculation.
</HARD-RULE>

<HARD-RULE id="HR-BM3">
**Benchmarks (e.g., "SaaS LTV:CAC >= 3:1") introduced as reference ranges only, tagged
"industry rule-of-thumb, not your number".** Never present a benchmark as the user's actual
metric. Never use a benchmark as a substitute for user-supplied data. Always label: source,
applicability, and caveats.
</HARD-RULE>

<HARD-RULE id="HR-BM4">
**`unknown` is a valid input.** It degrades downstream confidence and falls back to
scenario-table mode showing "what must be true" instead of computing a point estimate. The
calculator does not refuse to work with incomplete data — it shows what the missing data means
for the decision.
</HARD-RULE>

<HARD-RULE id="HR-BM5">
**Single-point estimates forbidden.** Every output is a low/expected/high range. A single number
creates false precision. The user must see the spread to understand their risk.
</HARD-RULE>

<HARD-RULE id="HR-BM6">
**At pre-product stage, contribution margin + pricing sensitivity + payback intuition are the
primary primitives, NOT LTV/CAC.** LTV requires retention data the user does not have pre-product.
CAC requires acquisition data the user does not have. Contribution margin and pricing are
actionable pre-product. LTV/CAC are computed when the inputs exist but flagged as "assumed" or
"unknown" at pre-product stage.
</HARD-RULE>

**Inherited hard rules (from parent `founder`):** HR-1 through HR-11 all apply. Key inherited
constraints: no valuation/legal/tax advice (HR-1, HR-2), no LLM-generated TAM (HR-3), kill
criteria on all ideas (HR-4), data citations (HR-5), founder is pre-execution only (HR-6),
venture-brief is canonical state (HR-7), intake required (HR-8), epistemic honesty (HR-10).

---

## Calculator Mode Interaction Pattern

Hybrid: interactive Q&A that emits a YAML snapshot.

### First Run

1. Conversational Q&A (max ~8 questions). Each user input is tagged:
   - `observed` — the user has real data (e.g., "I'm charging $29, 15 customers paying")
   - `assumed` — the user believes this but hasn't validated (e.g., "I think CAC is ~$100")
   - `target` — the user wants this to be true (e.g., "I want to charge $29")
   - `unknown` — the user has no idea (e.g., "no clue about churn")

2. After Q&A, emit `.founder/business-model-<slug>.yaml` snapshot containing:
   - All inputs with their tags
   - All derived outputs with formulas, ranges, and confidence
   - Decision rule verdict
   - Needs-more-data flags

3. Present analysis to the user with the calculation chain visible.

### Subsequent Runs

User edits the YAML directly. Skill re-reads, re-computes, and presents updated analysis.
This avoids re-asking questions the user has already answered.

---

## Modes

### 1. `unit_economics`

Core calculator: contribution margin, LTV, CAC, payback period, LTV:CAC ratio.

**Input (from Q&A or YAML):**
```yaml
mode: "unit_economics"
inputs:
  price:
    value: float               # e.g., 29.00
    tag: enum                  # observed | assumed | target
    period: enum               # monthly | annual | one-time
  pricing_model: enum          # subscription | usage | one-time | hybrid
  cogs_per_unit:               # cost to serve one customer per period
    value: float
    tag: enum
  cac:                         # customer acquisition cost
    value: float | range       # single value or {low, high}
    tag: enum
  monthly_churn:               # percentage of customers lost per month
    value: float | null        # null = unknown
    tag: enum
  gross_margin_pct:            # gross margin percentage
    value: float
    tag: enum
  decision_rule: string        # user's go/no-go criteria
```

**Computation:**
```
Contribution Margin = Price - COGS per unit
  range: {low: CM * 0.8, expected: CM, high: CM * 1.2}
  confidence: based on input tags

If churn is known:
  Customer Lifetime = 1 / monthly_churn (months)
  LTV = Contribution Margin * Customer Lifetime
  range: {low, expected, high} propagated from CM and churn ranges

If CAC is known:
  LTV:CAC Ratio = LTV / CAC
  Payback Period = CAC / Contribution Margin (months)
  range: propagated

If churn is unknown:
  LTV = CANNOT COMPUTE (HR-BM4)
  Fall back to: "What must be true about churn for LTV:CAC >= 3?"
  Show scenario table: churn at 2%, 3%, 5%, 8%, 10% -> resulting LTV:CAC
```

**Sensitivity analysis:** For each input, show the output impact at +-20% variation.
Highlight the input with the largest sensitivity ("churn is the biggest lever").

**Output:**
```yaml
unit_economics:
  inputs:
    - name: string
      value: float | range
      tag: enum
      source: string           # "user-stated" / "user-YAML" / "industry-benchmark (ref only)"
  derived:
    contribution_margin:
      low: float
      expected: float
      high: float
      formula: "price - cogs_per_unit"
      confidence: enum
    ltv:
      low: float | null
      expected: float | null
      high: float | null
      formula: "contribution_margin / monthly_churn"
      confidence: enum
      note: null | string      # "churn is unknown — using industry range" etc.
    cac:
      low: float | null
      expected: float | null
      high: float | null
      confidence: enum
    payback_months:
      low: float | null
      expected: float | null
      high: float | null
      formula: "cac / contribution_margin"
      confidence: enum
    ltv_cac_ratio:
      low: float | null
      expected: float | null
      high: float | null
      formula: "ltv / cac"
      confidence: enum
  sensitivity:
    biggest_lever: string      # "churn" / "price" / "cac"
    table: list[{input, -20%, base, +20%, impact}]
  decision_rule:
    rule: string
    verdict: enum              # green | conditional_go | red
    verdict_rationale: string
  needs_more_data: list[string]
  not_computed: list[string]   # what was skipped and why
```

### 2. `pricing_explorer`

"What should I charge?" — guided pricing analysis.

**Input:**
```yaml
mode: "pricing_explorer"
product_description: string
target_persona: string
competitive_prices: list[{competitor, price, features}]  # user-supplied
value_created: string          # what value does the product create for the customer?
cost_to_serve: float           # from unit_economics or user-stated
```

**Flow:**

1. **Value-based pricing anchor:** "What is the cost of the problem you're solving? What would
   the customer pay to make it go away?" Derive a value ceiling.
2. **Competitive anchoring:** Where do competitors sit? Position relative to them with reasoning.
3. **Cost-plus floor:** What's the minimum price to be contribution-margin positive?
4. **Van Westendorp adapted questions** (for the user to ask their customers):
   - "At what price would you consider this too expensive to consider?"
   - "At what price would you start to think it's getting expensive but still consider it?"
   - "At what price would you think it's a bargain?"
   - "At what price would you think it's so cheap you'd question the quality?"
5. **Produce pricing scenarios:**
   ```yaml
   scenarios:
     - name: "penetration"
       price: float
       rationale: string
       trade_offs: string
       contribution_margin: float
       break_even_customers: int
     - name: "value_based"
       price: float
       rationale: string
       trade_offs: string
       contribution_margin: float
       break_even_customers: int
     - name: "competitive"
       price: float
       rationale: string
       trade_offs: string
       contribution_margin: float
       break_even_customers: int
   ```
6. **Recommendation:** which scenario fits the user's stage and goals, with reasoning.

### 3. `what_must_be_true`

Given a target outcome, reverse-engineer the assumptions that must hold.

**Input:**
```yaml
mode: "what_must_be_true"
target: string                 # "$10K MRR in 6 months"
known_inputs:                  # whatever the user knows
  price: {value, tag}
  # ... any subset of unit_economics inputs
```

**Flow:**

1. Parse the target into quantitative components (revenue, timeline, etc.)
2. Work backwards through the unit economics chain:
   - Revenue target -> customers needed -> conversion rate needed -> traffic needed -> CAC ceiling
   - Revenue target -> contribution margin needed -> price floor
   - Timeline -> growth rate needed -> churn ceiling
3. For each assumption: surface it, show the formula, tag it by fragility:
   ```yaml
   assumptions_required:
     - assumption: "Monthly churn <= 3%"
       fragility: high          # small changes here have large downstream impact
       formula: "churn = 1 / (LTV / CM)"
       current_status: enum     # observed | assumed | unknown
       what_if_wrong: string    # "If churn is 8% instead of 3%, you need 2.5x more customers"
     - assumption: "CAC <= $150"
       fragility: medium
       formula: "CAC = budget / customers_acquired"
       current_status: unknown
       what_if_wrong: string
   ```
4. Highlight the most fragile assumptions ("these are the deal-breakers").

### 4. `scenario_table`

Generate an NxM scenario matrix varying 2 inputs across their ranges.

**Input:**
```yaml
mode: "scenario_table"
row_variable: string           # e.g., "monthly_churn"
row_values: list[float]        # e.g., [0.02, 0.03, 0.05, 0.08, 0.10]
col_variable: string           # e.g., "price"
col_values: list[float]        # e.g., [19, 29, 39, 49]
output_metric: string          # e.g., "ltv_cac_ratio"
decision_rule: string          # e.g., "LTV:CAC >= 3"
base_inputs: map               # all other inputs held constant
```

**Output:**

A visual NxM matrix with color-coding:
```
                    Price $19    Price $29    Price $39    Price $49
Churn 2%           [GREEN 4.2]  [GREEN 6.3]  [GREEN 8.5]  [GREEN 10.6]
Churn 3%           [YELLOW 2.8] [GREEN 4.2]  [GREEN 5.6]  [GREEN 7.1]
Churn 5%           [RED 1.7]    [YELLOW 2.5] [GREEN 3.4]  [GREEN 4.2]
Churn 8%           [RED 1.1]    [RED 1.6]    [YELLOW 2.1] [YELLOW 2.7]
Churn 10%          [RED 0.8]    [RED 1.3]    [RED 1.7]    [YELLOW 2.1]
```

- GREEN: meets decision rule
- YELLOW: within 20% of threshold (conditional)
- RED: below threshold

**Insight:** "You need churn below 5% at $29 or below 8% at $39 to meet your LTV:CAC >= 3 rule."

---

## YAML Snapshot Format

Emitted to `.founder/business-model-<slug>.yaml` after first computation:

```yaml
# Business Model Snapshot — <venture name>
# Generated by founder-business-model
# Edit inputs below and re-run to update analysis

snapshot_version: 1
venture_brief_ref: .founder/venture-brief.yaml
generated_at: timestamp
last_computed_at: timestamp

inputs:
  price: {value: 29.00, tag: target, period: monthly}
  pricing_model: subscription
  cogs_per_unit: {value: 3.50, tag: assumed}
  cac: {low: 100, high: 300, tag: assumed}
  monthly_churn: {value: null, tag: unknown}
  gross_margin_pct: {value: 85, tag: assumed}

derived:
  contribution_margin: {low: 20.40, expected: 25.50, high: 30.60}
  ltv: {low: null, expected: null, high: null, note: "churn unknown"}
  cac: {low: 100, expected: 200, high: 300}
  payback_months: {low: 3.3, expected: 7.8, high: 14.7}
  ltv_cac_ratio: {low: null, expected: null, high: null, note: "churn unknown"}

sensitivity:
  biggest_lever: churn
  note: "churn is unknown and dominates LTV — get real retention data"

decision_rule: "LTV:CAC >= 3, payback <= 12mo"
decision_verdict: conditional_go
verdict_rationale: "Payback looks achievable; LTV:CAC cannot be computed without churn data"

needs_more_data:
  - "monthly_churn: INDUSTRY BENCHMARK used (2-5%), not your data. Run 90 days real."
  - "cac: assumed range, no ad spend data yet"

not_computed:
  - "TAM: no inputs provided (HR-3 — will not fabricate)"
  - "valuation: refused (HR-1)"
```

---

## Confidence Tagging

Every derived value carries a confidence tag based on its input provenance:

| Input tags | Derived confidence |
|---|---|
| All `observed` | high |
| Mix of `observed` + `assumed` | medium |
| Any `target` in the chain | low |
| Any `unknown` in the chain | speculative |
| All `unknown` | scenario-only (cannot compute point range) |

---

## Benchmark Reference Ranges

When the user has no data for an input, offer industry benchmarks AS REFERENCE ONLY (HR-BM3):

```yaml
benchmarks:
  saas_monthly_churn: {low: 0.02, typical: 0.05, high: 0.10, source: "industry rule-of-thumb"}
  saas_ltv_cac_target: {value: 3.0, source: "industry rule-of-thumb, not your number"}
  saas_payback_target: {value: 12, unit: months, source: "industry rule-of-thumb"}
  saas_gross_margin: {low: 0.70, typical: 0.85, high: 0.95, source: "industry range"}
```

Always label: "This is an industry rule-of-thumb, not your number. Replace with observed data
as soon as you have it."

---

## Venture-Brief Integration

On completion, write to venture-brief.yaml:

```yaml
business_model:
  price: {value, tag}
  pricing_model: enum
  unit_econ:
    contribution_margin: {low, expected, high}
    ltv: {low, expected, high}
    cac: {low, expected, high}
    payback_months: {low, expected, high}
    ltv_cac_ratio: {low, expected, high}
  decision_rule: string
  decision_verdict: enum        # green | conditional_go | red
  needs_more_data: list[string]
  snapshot_path: string         # .founder/business-model-<slug>.yaml
```

---

## Failure Modes

| Failure | Detection | Response |
|---|---|---|
| User asks for LTV without churn data | `monthly_churn` is null/unknown | Fall back to scenario table: "what must be true about churn?" (HR-BM4) |
| User asks for TAM | TAM request detected | Refuse LLM-generated TAM (HR-3); offer calculator mode with user inputs |
| User supplies only 1-2 inputs | Most inputs null | Run `what_must_be_true` mode instead of `unit_economics` |
| All inputs are `unknown` | Nothing to compute | Show the framework + empty template; explain what each input means |
| User wants valuation | Valuation request detected | Refuse (HR-1); explain why LLMs should not produce valuations |
| Price is unreasonably high/low | Sanity check fails | Flag but don't override: "This price is [X]x the competitive range — intentional?" |
| Venture-brief missing | File not found | Return to parent with intake error |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Producing single-point estimates | Creates false precision (HR-BM5) | Always produce low/expected/high ranges |
| Using benchmarks as the user's numbers | Benchmarks are averages, not the user's reality (HR-BM3) | Label as "reference range, not your number" |
| Computing LTV pre-product | User has no retention data; LTV is fiction | Use contribution margin as primary (HR-BM6); show LTV with explicit unknown tag |
| Hiding the formula behind a number | User cannot verify or challenge (HR-BM2) | Show every formula, every input, every derivation step |
| Refusing to work with incomplete data | Founders always have incomplete data | Degrade gracefully: unknown -> scenario table -> what must be true (HR-BM4) |
| Presenting a "financial projection" | LLMs fabricate projections that look authoritative (HR-BM1) | Present ranges, sensitivities, and decision rules instead |
| Generating TAM from LLM knowledge | All LLM TAM is fabricated (HR-3) | Calculator mode only with user-supplied inputs |
| Advising on valuation or fundraising | Jurisdiction-specific, high-stakes (HR-1) | Refuse; refer to counsel |

---

## Reference Files

Read these as needed during business model work:

- `references/calculator-mode-protocol.md` — input capture protocol, observed/assumed/target/unknown
  tagging, range enforcement, YAML snapshot format
- `references/contribution-margin-primary.md` — why CM is the primary primitive pre-product, not
  LTV/CAC; formulas and derivation chains
- `references/pricing-sensitivity.md` — Van Westendorp adapted, value-based pricing, competitive
  anchoring, pricing scenario generation
- `references/scenario-tables.md` — NxM matrix generation, green/yellow/red zones, variable
  selection, visual formatting
- `references/decision-rule-library.md` — standard decision rules (LTV:CAC >= 3, payback <= 12mo,
  CM > 60%, etc.) with when-to-use context and caveats

---

## When NOT to Use This Skill

- **User wants to generate ideas** — use `founder-ideation`
- **User wants to validate with real users** — use `founder-validation`
- **User wants a financial projection for investors** — REFUSED (HR-BM1); suggest user work
  with a CFO or financial advisor
- **User wants valuation / cap table** — REFUSED (HR-1)
- **User wants TAM without inputs** — REFUSED (HR-3); offer calculator mode
- **User wants post-launch financial analysis** (actual revenue data) — use `project-finance`
  instead; this skill is pre-execution
- **User wants to build the product** — hand off to `forge` via sprint
