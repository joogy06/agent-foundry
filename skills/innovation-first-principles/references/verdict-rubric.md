# Verdict Rubric — 2×2 Grid, Decision Rules, and `constraint-map.yaml` Schema

The Coherence Judge's final output is one of four verdicts on a 2×2 grid (novel × coherent). This
file specifies the rubric, decision rules, mandatory-falsifier enforcement, and the full YAML
schema with worked examples for each verdict.

---

## The 2×2 grid

```
                  coherent                  incoherent
                ┌─────────────────────┬─────────────────────┐
                │                     │                     │
       novel    │  novel-and-coherent │   novel-but-fragile │
                │                     │                     │
                ├─────────────────────┼─────────────────────┤
                │                     │                     │
    not-novel   │  coherent-but-      │      incoherent     │
                │  not-novel          │                     │
                │                     │                     │
                └─────────────────────┴─────────────────────┘
```

| Verdict | Meaning | Caller action |
|---|---|---|
| `novel-and-coherent` | A 2020-era constraint is escaped AND composition is coherent | Proceed (possibly into `forge` for design) |
| `coherent-but-not-novel` | Composition works, but no prior constraint escaped | Build it if useful, but do NOT frame as innovation |
| `novel-but-fragile` | Constraint truly escaped, but composition has high failure risk | Needs mitigation design before `forge` |
| `incoherent` | Frankenstein — stapled primitives, no coherent output | Reject |

---

## Decision rules

The Judge arrives at a verdict by answering two questions:

**Q-novel: "Did the tribunal establish a 2020-era constraint is genuinely escaped?"**

- YES if: Historian named a specific `prior_era_constraints[].id` with mechanism, AND Builder paired
  it with a specific delta-id from the catalog that plausibly removes that blocker.
- NO if: Historian's `historian_null_result: true`, OR the Builder's delta-to-constraint pairing
  fails coherence inspection (Judge's independent assessment).

**Q-coherent: "Is the composition a real system, or stack glue?"**

- YES if: the Builder articulated a contradiction or tension that the delta-driven composition
  resolves (e.g., "before, long-horizon reasoning was blocked by 4k context AND expensive inference;
  the 1M context + 10× cheaper frontier tokens jointly enable multi-hour reasoning loops — the
  combination, not either alone, unlocks the idea").
- NO if: the composition is capabilities-stapled-together without explaining the contradiction being
  resolved. "LLM + vector DB + agent loop" is stack glue; "LLM-with-1M-context + ledger-of-claims
  replacing human-reviewer-gate" is a contradiction resolved.

| Q-novel | Q-coherent | Verdict |
|---|---|---|
| YES | YES | `novel-and-coherent` |
| NO | YES | `coherent-but-not-novel` |
| YES | NO | `novel-but-fragile` |
| NO | NO | `incoherent` |

---

## Mandatory `falsifying_experiment` rule (HARD-RULE 2)

Every verdict EXCEPT `incoherent` MUST include a `falsifying_experiment` field. The falsifier:

- Names a specific observation that would flip the verdict
- Is runnable in days, not quarters (cheap test, not a pilot program)
- Has a binary or near-binary outcome (pass/fail, threshold crossed / not crossed)
- Is falsifiable in principle, not just in theory

Example falsifiers by verdict:

- `novel-and-coherent`: "Run the 1M-context agent against the 50-file SWE-Bench test set; if
  recency-bias degradation causes omission of early-context instructions in >30% of runs, the
  verdict flips to `novel-but-fragile`."
- `coherent-but-not-novel`: "Identify ≥1 pre-2022 production deployment of the same pattern
  (functional equivalent, not identical stack). If found and operationally stable, the
  `coherent-but-not-novel` verdict holds; if the closest match crashed within 6 months of
  deployment, consider whether a 2020→2026 delta actually fixed that crash mode — if yes,
  re-verdict."
- `novel-but-fragile`: "Run a 24-hour loop of the proposed composition on a benchmark task; if the
  identified current-era constraint (e.g., tool-call reliability) manifests as blocking failure in
  <10% of runs, the fragility concern is overstated and the verdict upgrades to
  `novel-and-coherent`; if >30%, it holds."

No falsifier = no verdict. The tribunal returns `incoherent` by default if the Judge cannot name a
falsifier for a non-incoherent verdict.

---

## `constraint-map.yaml` — full schema

Canonical output shape. Required unless marked OPTIONAL.

```yaml
schema_version: 1
generated_at: <ISO8601 timestamp>
skill: innovation-first-principles
skill_version: v1-spike

problem: string                         # original problem statement
problem_atoms:                          # decomposition of the idea
  - {atom: string, role: enabler|constraint|composition-glue}

prior_era_constraints:                  # Historian
  - {id: string, description: string, mechanism: string, evidence_ref: string}
historian_null_result: bool             # true iff already possible in 2020

deltas_invoked: [string]                # Builder — delta-ids (e.g. "D-01")
lifted_constraints:                     # Builder — pairing to Historian constraints
  - {prior_era_constraint_id: string, delta_id: string, mechanism_of_removal: string}
builder_confidence: high|medium|low

current_constraints:                    # Skeptic
  - {id: string, description: string, mechanism: string, severity: blocker|degrader|risk}
red_flags: [string]                     # OPTIONAL — Skeptic pattern-match warnings

tribunal_findings:                      # one-paragraph summary per role
  {historian: string, builder: string, skeptic: string, judge: string}

verdict: novel-and-coherent|coherent-but-not-novel|novel-but-fragile|incoherent
contradiction_resolved: string          # required for novel-and-coherent; else empty
frankenstein_risk: string               # required for incoherent/novel-but-fragile; else empty
falsifying_experiment: string           # MANDATORY for non-incoherent verdicts (HARD-RULE 2)
recur_flag: false                       # hardcoded false in v1 spike (HARD-RULE 5)
```

---

## Worked examples

### Example 1 — `novel-and-coherent`

Problem: "autonomous coding agent with 1M context replacing human-reviewer gate for small-diff changes"

```yaml
verdict: novel-and-coherent
historian_null_result: false
prior_era_constraints:
  - id: "ctx-window-2020"
    mechanism: "4k-32k context windows forced RAG-stuffing, lost cross-file reasoning"
deltas_invoked: [D-01, D-03, D-08]
lifted_constraints:
  - {prior_era_constraint_id: "ctx-window-2020", delta_id: "D-01",
     mechanism_of_removal: "1M tokens holds full multi-file codebase in one reasoning context"}
current_constraints:
  - {id: "recency-bias-degradation", severity: degrader,
     mechanism: "Mid-context instructions demonstrably omitted in 1M-context runs"}
tribunal_findings:
  judge: "Constraint genuinely escaped via D-01/D-03/D-08; composition resolves the pre-2023 reviewer-dependency contradiction. Recency-bias fragility is a degrader, not a blocker."
contradiction_resolved: "Pre-2026, autonomous coding required human reviewer because agents could not retain whole-codebase context; D-01 + D-03 + D-08 jointly remove that dependency."
falsifying_experiment: "Run on SWE-Bench Verified; if >30% of runs omit early-context instructions due to recency bias, verdict flips to novel-but-fragile."
recur_flag: false
```

### Example 2 — `coherent-but-not-novel`

Problem: "CRM for dentists with appointment reminders"

```yaml
verdict: coherent-but-not-novel
historian_null_result: true
deltas_invoked: []                      # no deltas needed; possible in 2020
tribunal_findings:
  historian: "Dental CRMs with SMS reminders were a commodity product by 2018 (Dentrix, Curve). No 2020-era constraint is being escaped."
  judge: "Coherent-but-not-novel: the composition works, the market may be underserved in specific geographies, but this is not innovation. Build if the distribution play is strong; do not frame as newly-possible."
contradiction_resolved: ""
frankenstein_risk: ""
falsifying_experiment: "Identify ≥1 pre-2022 production dental CRM with SMS reminders. If found (Dentrix Ascend, for one, cites D-02 cheap-inference-era cost pressure but the base product existed pre-2020), the verdict holds; if no such product is findable, revisit historian."
recur_flag: false
```

### Example 3 — `novel-but-fragile`

Problem: "Multi-agent swarm generating and executing trading strategies autonomously on live funds"

```yaml
verdict: novel-but-fragile
deltas_invoked: [D-04, D-02]
current_constraints:
  - id: "eval-drift"
    description: "No reliable method to prevent agents from converging on overfit strategies"
    mechanism: "Backtest-to-live divergence is a known failure mode; no 2026 delta directly addresses it"
    severity: blocker
  - id: "capital-at-risk"
    description: "Agent failure directly loses money"
    severity: blocker

tribunal_findings:
  judge: "Novel-but-fragile: D-04 multi-agent orchestration is a genuine 2020→2026 delta (pre-2023, manual prompt chaining was the state of the art), so novelty holds; but the eval-drift current constraint is a blocker the Builder did not address, and capital-at-risk makes fragility unacceptable. Needs mitigation design before proceeding."

falsifying_experiment: "Paper-trade the swarm for 30 days with kill-switch. If eval-drift manifests (backtest-to-live Sharpe drop >50%) in <20% of runs, upgrade to novel-and-coherent; otherwise verdict holds and live deployment is rejected."
recur_flag: false
```

### Example 4 — `incoherent`

Problem: "LLM + blockchain + NFT-gated vector database for enterprise knowledge management"

```yaml
verdict: incoherent
deltas_invoked: [D-01, D-05]
tribunal_findings:
  judge: "Incoherent: the Builder cited D-01 and D-05 (both real deltas), but could not articulate what contradiction the composition resolves. Blockchain and NFT-gating add no mechanism that D-05 grounding does not already provide; the composition is capabilities-stapled-together, not a coherent system. Frankenstein risk confirmed."

frankenstein_risk: "Blockchain and NFT layers add no mechanism; they are capabilities stapled to a working LLM+RAG pattern. The tension being resolved is unnamed — the stack is larger but not more capable."
falsifying_experiment: ""                # not required for incoherent
recur_flag: false
```

---

## Verdict enforcement summary

- `novel-and-coherent`: requires `historian_null_result: false`, ≥1 delta invoked, paired, coherent composition, AND falsifier
- `coherent-but-not-novel`: requires `historian_null_result: true` OR Judge-override on weak Builder pairing; `deltas_invoked: []` acceptable; falsifier required
- `novel-but-fragile`: requires delta(s) invoked AND ≥1 `current_constraint` at `severity: blocker`; falsifier required
- `incoherent`: frankenstein_risk required; falsifier NOT required

Rule violations → Judge rejects output, tribunal re-runs the offending role once; still failing →
`verdict: incoherent` with `judge_rationale` noting tribunal failure.
