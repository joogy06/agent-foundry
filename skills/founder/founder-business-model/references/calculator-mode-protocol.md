# Calculator Mode Protocol

Input capture, tagging, range enforcement, and YAML snapshot mechanics for
`founder-business-model`.

---

## Input Capture Q&A

Maximum ~8 questions. Adaptive — skip questions where the answer is already in venture-brief.

### Standard Question Sequence

```
Q1: "What's your core product/service?"
    → free text, used for context only

Q2: "What pricing model? (subscription / usage-based / one-time / hybrid)"
    → enum, tag: observed if already selling, target if planned

Q3: "What price are you charging or planning to charge?"
    → float + period (monthly/annual/one-time)
    → tag: observed (already charging), assumed (researched), target (aspirational)

Q4: "What does it cost you to serve one customer per [period]?"
    → float (COGS: hosting, API calls, support time, etc.)
    → tag: observed (real costs), assumed (estimated)

Q5: "How do you acquire customers? What channel?"
    → free text, used for CAC derivation context

Q6: "What's your CAC (customer acquisition cost) or ad spend per customer?"
    → float or range or "unknown"
    → tag: observed (real spend data), assumed (estimated), unknown

Q7: "What's your monthly churn rate? (% of customers lost per month)"
    → float or "unknown"
    → tag: observed (real data), assumed (estimated), unknown

Q8: "What's your go/no-go decision rule? When would you say 'this works'?"
    → free text, structured into a testable rule
    → e.g., "LTV:CAC >= 3 and payback <= 12 months"
```

### Tagging Protocol

Every input is tagged at capture time:

| Tag | Meaning | Impact on confidence |
|---|---|---|
| `observed` | User has real data from actual operations | Highest confidence |
| `assumed` | User believes this is correct but hasn't validated | Medium confidence |
| `target` | User wants this to be true | Low confidence |
| `unknown` | User has no data or estimate | Degrades to scenario mode |

**Tagging is explicit.** After each answer, confirm the tag:
> "Got it — $29/month, and that's a target price (not yet validated with customers). Tagging as
> `target`. Correct?"

### Adaptive Shortening

- If venture-brief already has pricing data from `founder-validation`: skip Q3, use existing
- If user ran `founder-ideation` with market data: skip Q1, reference existing
- If all inputs are in a prior `.founder/business-model-*.yaml`: skip Q&A entirely, re-compute

---

## Range Enforcement (HR-BM5)

Every output MUST be a range. Derivation:

```
If input is a single value:
  low = value * 0.8
  expected = value
  high = value * 1.2

If input is already a range {low, high}:
  low = low
  expected = (low + high) / 2
  high = high

If input is unknown:
  Use industry benchmark range IF available (tagged as "reference, not your number")
  OR show "cannot compute — needs data"
```

Ranges propagate through formulas:
```
CM_low = price_low - cogs_high
CM_expected = price_expected - cogs_expected
CM_high = price_high - cogs_low
```

---

## YAML Snapshot

Emitted to `.founder/business-model-<slug>.yaml` where `<slug>` is derived from the venture
name or product description (lowercase, hyphens, no spaces).

The snapshot is designed to be human-editable:
- Comments explain each field
- Tags are visible
- User can edit values and re-run the skill to get updated analysis

See the YAML snapshot format in the parent SKILL.md for the complete schema.

### Re-run Protocol

When the user edits the YAML and asks to re-compute:
1. Read the edited YAML
2. Validate: all required fields present, tags valid, values in reasonable ranges
3. Re-compute all derived values
4. Update `last_computed_at`
5. Present updated analysis with change highlights
