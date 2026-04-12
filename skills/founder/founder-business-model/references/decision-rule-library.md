# Decision Rule Library

Standard business model decision rules with when-to-use context, thresholds, and caveats.
Used by `founder-business-model` to evaluate the user's go/no-go criteria.

---

## Standard Rules

### LTV:CAC Ratio

```
Rule: LTV:CAC >= 3:1
Verdict:
  GREEN: ratio >= 3.0
  CONDITIONAL_GO: 2.0 <= ratio < 3.0
  RED: ratio < 2.0
```

**When to use:** SaaS, subscription businesses with known churn and CAC.

**Caveats:**
- Requires churn data (pre-product: unknown or assumed)
- The "3:1" is a venture capital benchmark, not a universal truth
- Solo bootstrappers may be viable at 2:1 (lower overhead)
- Enterprise SaaS often needs 5:1+ (longer sales cycles, higher CAC)
- Tag as "industry rule-of-thumb, not your number" (HR-BM3)

### Payback Period

```
Rule: Payback <= 12 months
Verdict:
  GREEN: payback <= 12
  CONDITIONAL_GO: 12 < payback <= 18
  RED: payback > 18
```

**When to use:** Any recurring revenue model. More reliable pre-product than LTV:CAC because
it only needs CAC and contribution margin (not churn).

**Caveats:**
- VC-backed: 12 months is standard; some will accept 18
- Bootstrap: 6 months or less preferred (cash flow critical)
- Enterprise: 18-24 months may be acceptable (higher contract values)
- Payback assumes constant CM — if price changes, re-compute

### Contribution Margin

```
Rule: CM > 60%
Verdict:
  GREEN: cm_pct > 60%
  CONDITIONAL_GO: 40% <= cm_pct <= 60%
  RED: cm_pct < 40%
```

**When to use:** Pre-product sanity check. The most reliable pre-product metric (HR-BM6).

**Caveats:**
- Software/SaaS: typically 70-90% CM — 60% floor is conservative
- Services: typically 30-60% CM — different threshold needed
- Hardware: typically 20-50% CM — different threshold needed
- Marketplace: depends on take rate — typically 10-30% of GMV

### Monthly Recurring Revenue Target

```
Rule: MRR >= $X by month Y
Verdict:
  GREEN: trajectory shows MRR >= target at month Y
  CONDITIONAL_GO: trajectory shows 70-100% of target
  RED: trajectory shows < 70% of target
```

**When to use:** When the user has a specific revenue milestone.

**Caveats:**
- Often used with `what_must_be_true` mode to reverse-engineer assumptions
- Trajectory is based on assumed growth rate (which is itself assumed)
- More useful as a framing device than as a precise prediction

### Gross Margin

```
Rule: Gross Margin >= 70% (SaaS)
Verdict:
  GREEN: gm >= 70%
  CONDITIONAL_GO: 50% <= gm < 70%
  RED: gm < 50%
```

**When to use:** SaaS benchmark. Lower thresholds for non-software.

**Caveats:**
- SaaS median is ~80%; 70% is the floor for "good" SaaS margins
- AI/ML products often have lower margins (compute costs)
- Managed services: 50-70% is normal
- Hardware: 40-60% is typical

---

## Compound Rules

Users often combine rules. Common compounds:

```
"LTV:CAC >= 3 AND payback <= 12 months"
  → Both must be GREEN for compound GREEN
  → Either CONDITIONAL_GO → compound CONDITIONAL_GO
  → Either RED → compound RED

"CM > 60% AND MRR >= $10K by month 6"
  → Same logic
```

---

## Verdict Semantics

| Verdict | Meaning | User action |
|---|---|---|
| GREEN | Business model clears all decision rules | Proceed to next stage |
| CONDITIONAL_GO | Business model is close but has identified risks | Proceed with explicit risk acknowledgment; focus validation on the weak inputs |
| RED | Business model fails one or more critical rules | Pivot pricing, rethink costs, or re-examine assumptions before proceeding |

**CONDITIONAL_GO requires user acknowledgment.** The skill does not auto-advance past a
conditional verdict. It surfaces what's conditional and asks the user to decide.

---

## Custom Rules

Users can define custom decision rules beyond the library:

```yaml
custom_rule:
  name: "Bootstrap viability"
  expression: "payback <= 6 AND cm > 50% AND cac < 100"
  thresholds:
    green: "all conditions met"
    conditional: "1 condition missed by < 20%"
    red: "2+ conditions missed OR any condition missed by > 20%"
```

The skill evaluates custom rules with the same compute-and-display protocol as standard rules.

---

## Pre-Product Rule Selection Guidance

| Founder situation | Recommended rules | Rationale |
|---|---|---|
| Solo bootstrapper, no funding | CM > 50%, payback <= 6mo | Cash flow critical, no runway to burn |
| Small team, angel seed | CM > 60%, payback <= 12mo, LTV:CAC >= 2 | Modest runway, need proof |
| VC-backed seed | LTV:CAC >= 3, payback <= 18mo, CM > 60% | Investors expect these benchmarks |
| Enterprise SaaS | LTV:CAC >= 5, payback <= 18mo, ACV > $10K | Longer cycles, higher thresholds |
| Marketplace | Take rate > 15%, GM > 40%, GMV growth > 20% m/m | Different metrics entirely |
| Hardware | GM > 40%, payback <= 12mo, CM > 30% | Lower margins, higher thresholds |
