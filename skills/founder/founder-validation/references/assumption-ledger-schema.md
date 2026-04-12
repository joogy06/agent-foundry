# Assumption Ledger Schema

YAML schema for structured assumptions in the venture-brief. Each assumption is a testable claim
about the venture that must be validated through real-world evidence before advancing.

---

## Schema

```yaml
assumptions:
  - id: uuid                    # unique identifier
    claim: string               # the testable claim ("UK accountants spend >10h/month on FX reconciliation")
    category: enum              # problem | solution | market | channel | pricing | technical | regulatory
    risk_level: enum            # high (core viability) | medium (growth) | low (nice-to-have)
    confidence: enum            # high | medium | low | speculative | untested
    source: string              # where this assumption came from: "founder-ideation:contrarian-team", "user-stated", etc.
    created_at: timestamp
    updated_at: timestamp

    # Evidence trail
    evidence: list[
      {
        experiment_id: uuid     # links to experiments[]
        evidence_type: enum     # interview | landing_page | ad_test | survey | concierge | other
        date: date
        summary: string         # 1-sentence summary
        raw_data_ref: string    # reference to full evidence artifact in experiments[].evidence
        verdict_contribution: enum  # supports | contradicts | neutral
      }
    ]

    # Disconfirmation
    disconfirmers: list[string]  # what would prove this wrong
    falsified_at: null | timestamp
    falsified_by: null | string  # experiment_id that falsified it

    # Testing status
    test_designed: bool          # has an experiment been designed for this?
    test_ref: null | string      # pointer to experiment in experiments[]

    # Disposition
    status: enum                 # active | confirmed | falsified | pivoted | accepted_risk | deferred
    disposition_reason: null | string  # why it was confirmed/falsified/pivoted
    disposition_at: null | timestamp
```

---

## Category Definitions

| Category | Description | Example | Typical risk level |
|---|---|---|---|
| problem | The pain point exists and is severe enough to motivate action | "UK accountants spend >10h/month on FX reconciliation" | high |
| solution | The proposed solution addresses the pain effectively | "Automated FX delta matching reduces reconciliation time by 80%" | high |
| market | The addressable market is large enough to sustain the business | "10,000+ UK practices handle multi-currency clients" | medium |
| channel | The target customers can be reached via the proposed distribution | "LinkedIn ads reach UK practice managers effectively" | medium |
| pricing | The target price point is acceptable to the customer | "UK practices will pay GBP 80/month for this tool" | high |
| technical | The technical approach is feasible within constraints | "HMRC bank feed API supports multi-currency delta queries" | medium |
| regulatory | The business model complies with relevant regulations | "No FCA registration needed for a reconciliation tool" | high |

---

## Confidence Scoring

| Level | Criteria |
|---|---|
| high | Multiple experiments, consistent results, behavioral evidence, large sample |
| medium | At least one experiment with adequate sample, some behavioral evidence |
| low | Limited evidence, small sample, or only stated-preference data |
| speculative | No direct evidence; inference from adjacent data or LLM reasoning |
| untested | No experiments run for this assumption |

---

## Status Transitions

```
untested --> active (experiment designed)
active --> confirmed (behavioral evidence meets success criteria)
active --> falsified (evidence meets kill criteria)
active --> pivoted (assumption reformulated based on evidence)
active --> accepted_risk (user acknowledges risk, proceeds anyway)
active --> deferred (not testing now, will revisit later)
falsified --> pivoted (user reformulates after falsification)
```

**Transition rules:**
- `confirmed` requires behavioral evidence (HR-V1) — verbal "I'd buy it" does not qualify
- `falsified` requires experiment results below kill criteria
- `pivoted` must reference the original assumption and explain what changed
- `accepted_risk` must be an explicit user decision with reasoning recorded

---

## Linking to Experiments

Each assumption links to experiments via `test_ref` and `evidence[].experiment_id`. The
experiment record in venture-brief.experiments[] contains the full evidence artifact with
raw data. The assumption ledger maintains a summary reference, not a copy.

```
assumption.test_ref --> experiments[].id (designed experiment)
assumption.evidence[].experiment_id --> experiments[].id (completed experiment with results)
```

This two-way linking ensures that:
1. Every assumption knows which experiments were run to test it
2. Every experiment knows which assumption it was designed to test
3. Evidence review can walk the full chain: assumption -> experiment -> evidence -> verdict
