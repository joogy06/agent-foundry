# Kill Criteria Library — Standard Venture Kills

The arbiter in founder-ideation must ensure every output has ≥2 kill criteria (HR-4). When teams
don't produce sharp kill criteria in Round 3 (refine), the arbiter falls back to this library.

Kill criteria from this library are GENERIC — the arbiter specializes them to the specific output
when attaching. For example, "Unit economics negative at scale" becomes "Unit economics negative
at scale: fails if CAC > £400 AND 18-month LTV < £2000".

---

## Standard library

### Distribution gap

**Generic:** "Fails if we cannot acquire customers at CAC < X given first-channel realities."

**When to use:** any idea with an implicit "if we build it, they will come" assumption. Most
software and marketplace ideas fall here.

**Specialization template:**
- Software: "Fails if CAC > ${X} on the first chosen channel within 90 days of launch"
- Marketplace: "Fails if supply-side acquisition costs > revenue per active buyer"
- Service: "Fails if the user cannot secure 3 paying clients within 60 days of offering the service"

### Unit economics negative

**Generic:** "Fails if contribution margin is negative or payback period exceeds N months at
reasonable scale."

**When to use:** when the idea depends on optimistic unit economics that haven't been verified.

**Specialization template:**
- "Fails if contribution margin remains negative at 1000 customers"
- "Fails if CAC payback period exceeds 18 months at target pricing"
- "Fails if gross margin is below 60% at scale (software) / 30% (services) / 25% (physical)"

### Regulatory block

**Generic:** "Fails if [specific regulator] blocks or materially restricts the mechanism."

**When to use:** any idea that touches regulated industries (health, finance, food, crypto, AI,
labor).

**Specialization template:**
- "Fails if the FCA classifies this as a regulated payment service requiring an e-money license"
- "Fails if GDPR Article 22 forbids the automated decision-making mechanism"
- "Fails if the FDA requires 510(k) clearance before first sale"

### Saturated market

**Generic:** "Fails if incumbents ship equivalent functionality within N months of our launch."

**When to use:** ideas in spaces where incumbents have the resources to copy quickly.

**Specialization template:**
- "Fails if Xero or QBO ship FX-delta-aware reconciliation in their 2026 roadmap"
- "Fails if the category leader acquires a competitor in the next 6 months"

### No switching cost

**Generic:** "Fails if customers switch away within M months because the lock-in mechanism is
weak."

**When to use:** ideas where customer retention is the core value driver.

**Specialization template:**
- "Fails if churn exceeds 5% monthly at steady state"
- "Fails if the customer can migrate to an alternative in < 1 day"
- "Fails if the switching cost is below £500 of effort per customer"

### No compounding moat

**Generic:** "Fails if the nth customer provides no advantage to the 1st customer's experience."

**When to use:** ideas without network effects, data moats, or scale economies.

**Specialization template:**
- "Fails if the 100th customer doesn't improve the experience for the 1st customer (no network
  effect, no data moat, no scale economy)"
- "Fails if acquiring the 2nd customer is no easier than the 1st"

### Wrong customer

**Generic:** "Fails if the identified buyer persona does not exist, does not have the budget we
assume, or does not have decision authority."

**When to use:** any idea where the buyer isn't the user or where the budget assumption is weak.

**Specialization template:**
- "Fails if practice owners (buyers) don't have the £80/mo discretionary software budget we assume"
- "Fails if the decision to adopt requires partner approval that takes > 90 days"

### Timing — too early

**Generic:** "Fails if the enabling condition (technology, regulation, market awareness) hasn't
arrived by N months after launch."

**When to use:** ideas that depend on a macro shift that hasn't fully landed yet.

**Specialization template:**
- "Fails if HMRC Making Tax Digital phase-4 rules haven't been confirmed by end of 2026"
- "Fails if retail LLM adoption hasn't crossed 20% in the target segment by Q4 2026"

### Timing — too late

**Generic:** "Fails if the market is already beyond the window; first-movers have locked in."

**When to use:** ideas in spaces with late-mover disadvantage.

**Specialization template:**
- "Fails if 2 of the top 5 incumbents have already shipped an equivalent feature"
- "Fails if the TAM is shrinking year-over-year"

### Execution capability gap

**Generic:** "Fails if the user cannot acquire the required capability (skill, hire, partner)
within N months."

**When to use:** ideas that require specific execution skills the user doesn't have.

**Specialization template:**
- "Fails if the user cannot hire or partner with a regulatory consultant by month 4"
- "Fails if the user cannot acquire the manufacturing capability via a contract manufacturer
  within budget"

### Data-dependency kill

**Generic:** "Fails if the required data source becomes unavailable or restricted."

**When to use:** ideas that depend on third-party data (APIs, scraped public data, aggregators).

**Specialization template:**
- "Fails if Reddit API restricts the access needed for the signal pipeline"
- "Fails if the public dataset is taken down or price-walled"
- "Fails if the LLM API provider raises prices > 3x"

### Platform risk

**Generic:** "Fails if the host platform changes policy to disallow or penalize the mechanism."

**When to use:** ideas built on top of social platforms, app stores, payment rails.

**Specialization template:**
- "Fails if LinkedIn restricts the automation used for outreach"
- "Fails if Apple App Store changes its policy on [X]"
- "Fails if Stripe classifies this as a restricted business"

### Margin collapse under scale

**Generic:** "Fails if the unit economics that work at small scale break under operational load."

**When to use:** services and marketplaces that look good on a spreadsheet but degrade with
scale.

**Specialization template:**
- "Fails if per-transaction support load > 20 minutes average at 1000 customers"
- "Fails if fraud loss exceeds 2% at scale"

### Capital intensity trap

**Generic:** "Fails if the required upfront capital exceeds available runway and cannot be raised."

**When to use:** physical / hardware / deep-tech ideas with significant upfront investment.

**Specialization template:**
- "Fails if first manufacturing run requires > £50k upfront and user cannot raise"
- "Fails if tooling cost > 6 months of runway"

### Trust / brand risk

**Generic:** "Fails if a bad early experience or compliance failure damages brand sufficiently to
prevent recovery."

**When to use:** ideas in trust-sensitive categories (health, finance, children, food).

**Specialization template:**
- "Fails if a single bad outcome generates PR that makes acquisition impossible"
- "Fails if a compliance failure results in regulator enforcement action"

---

## Deep-tech-specific additions (when `deep_tech_mode: true`)

### IP block

**Generic:** "Fails if freedom-to-operate search reveals blocking patents that cannot be designed
around or licensed."

**Specialization:** "Fails if US patent 9876543 blocks the control algorithm and licensing costs
exceed £100k/year"

### Certification delay

**Generic:** "Fails if certification timeline exceeds runway."

**Specialization:** "Fails if FDA 510(k) clearance takes > 24 months with founder's £200k budget"

### Manufacturability failure

**Generic:** "Fails if DFM review reveals unit cost > N× the target, invalidating the business
model."

**Specialization:** "Fails if DFM review with contract manufacturer shows unit cost > £400 at
1000-unit volume (target: £200)"

### Supply chain single-point-of-failure

**Generic:** "Fails if a key component has a single source and that source becomes unavailable."

**Specialization:** "Fails if a tariff, sanction, or supplier failure removes access to the key
component"

---

## Arbiter usage protocol

When the arbiter sees an output with < 2 kill criteria:

1. **First try** — extract from Round 2 attacks that were absorbed in Round 3 refine. Attacks
   convert naturally to kill criteria ("attack: distribution gap" → "kill criterion: fails if
   CAC > £X").
2. **Second try** — use this library. Pick the 2-3 most relevant entries based on the idea's
   biz_type, risk profile, and execution assumptions. Specialize them to the specific output.
3. **Third try** — arbiter writes 1-2 bespoke kill criteria based on tournament-wide patterns it
   observes (e.g., "this whole batch of ideas assumes X is durable — if X changes, all ideas fail").
4. **Failure** — if even with library + bespoke, the arbiter cannot produce 2 specific, testable
   kill criteria, the output is DROPPED. Do not fabricate untestable kill criteria.

## Testability criteria

A kill criterion is testable if:

- It names a specific, measurable outcome
- The measurement could be performed in the first 6-12 months of operation (not "fails if the
  market changes in 10 years")
- A human can determine pass/fail by examining the outcome (not "fails if vibes are bad")
- It's falsifiable — you can describe the world where the kill condition is met

Examples of UNTESTABLE kill criteria (reject these):
- "Fails if we don't achieve product-market fit"
- "Fails if customers don't love it"
- "Fails if we run out of money"
- "Fails if we pick the wrong strategy"

Examples of TESTABLE kill criteria:
- "Fails if first-month churn > 15%"
- "Fails if CAC > £200 on LinkedIn ads after £5k test spend"
- "Fails if 0 of 10 target customers commit to a paid pilot within 6 weeks of first outreach"
- "Fails if the single-engineer MVP takes > 10 weeks to ship"
