# Tribunal Protocol — Four-Role Hearing Procedure

The **Capability Delta Tribunal** is the process that fills `constraint-map.yaml`. Four roles run
sequentially, each reading the prior role's output and contributing to a shared artifact. The Judge
runs LAST and has license to overrule.

This file specifies the per-role burden of proof, evidence requirements, handoff rules, and
rejection criteria. The invoking LLM follows this procedure when the skill is loaded — the tribunal
is a procedure, not a program.

---

## Role 1 — The Historian

**Burden of proof:** "Has this been attempted before? If not, what 2020-era constraint stopped it?"

**Evidence requirements:**
- Cite ≥1 historical precedent — a prior attempt (with outcome) OR a reason to believe the thing
  was impossible (with mechanism). Acceptable forms: named prior product, paper, project, or a
  widely-known technical blocker.
- If no prior attempt found, explain WHY (impossible / unprofitable / unfashionable — all
  legitimate, all lead to different verdicts).
- If the idea was clearly possible in 2020 and someone built it, say so. This leads toward
  `coherent-but-not-novel` without shame.

**Artifact contribution:** `prior_era_constraints[]` (each with `id`, `description`, `mechanism`,
`evidence_ref`) + `historian_null_result` boolean (true iff already possible in 2020).

**Rejection:** no evidence → rejected. Claim without mechanism ("AI wasn't as good") → rejected.
Only mechanistic claims ("4k-32k context windows could not hold a multi-file codebase") accepted.

**Handoff to Builder:** output passes as-is. Builder cannot change Historian findings; only the
Judge can contradict them.

---

## Role 2 — The Builder

**Burden of proof:** "Which 2020→2026 capability deltas actually remove the Historian's blockers?"

**Evidence requirements:**
- Cite delta IDs from `references/capability-deltas-2020-2026.md` (D-01..D-08 in v1). Do NOT
  invent IDs. If a ninth delta is needed, flag it — Judge may downgrade on "delta-catalog-miss".
- For each cited delta, name the specific 2020 constraint it removes (cross-reference to Historian's
  `prior_era_constraints[].id`). Delta-to-constraint pairing is the load-bearing claim.
- ≥1 cited delta must have a measurable 2020→2026 dimension (e.g. "32k → 1M context" — a concrete
  30× multiplier, not "bigger context"). Vague capability language rejected.

**Artifact contribution:** `deltas_invoked[]` + `lifted_constraints[]` (mapping Historian
constraint-id → delta-id with mechanism) + `builder_confidence` (high/medium/low; low caps the
verdict at `novel-but-fragile` unless Skeptic finds zero current constraints).

**Rejection:** cited delta not in catalog → rejected. Incoherent pairing (e.g. "D-01 context removes
2020 inference-cost constraint") → rejected. "AI can do this now" without dimension → rejected.

**Handoff to Skeptic:** Builder output + Historian constraints both visible to Skeptic.

---

## Role 3 — The Skeptic

**Burden of proof:** "Which 2026-era constraints does this idea ignore? What will fail in practice?"

**Evidence requirements:**
- Name specific 2026 failure modes — not "AI hallucinates" (too vague) but "1M-context recency-bias
  degradation omits mid-context instructions at >200k tokens" (specific, named, mechanism-bearing).
- ≥1 current-era constraint required. A clean `current_constraints: []` is rare and itself deserves
  Judge scrutiny.
- Red flags (pattern-match warnings) allowed as supporting evidence but cannot be the ONLY evidence.

**Artifact contribution:** `current_constraints[]` (each with `id`, `description`, `mechanism`,
`severity: blocker|degrader|risk`) + OPTIONAL `red_flags[]`.

**Rejection:** "It might not work" → no mechanism, no critique. Attacking Historian's findings →
out of scope (Skeptic is forward-looking). Zero constraints AND zero red flags → suspicious;
Judge downgrades.

**Handoff to Judge:** all prior outputs visible to the Judge.

---

## Role 4 — The Coherence Judge

**Burden of proof:** "Is this a real system with coherent composition, or stapled primitives? Did
the prior roles do their jobs?"

**Evidence requirements:** explicit assessment of each prior role — Historian's constraint claim
strength, Builder's delta-to-constraint pairing coherence, Skeptic's current-era constraint
plausibility — plus the final verdict from the 2×2 grid (see `references/verdict-rubric.md`).

**License to overrule:**
- Historian's null result → Judge MUST return `coherent-but-not-novel` regardless of Builder/Skeptic
  (HARD-RULE 3).
- Builder's D-NN pairings don't actually remove the blockers → downgrade to `novel-but-fragile` or
  `coherent-but-not-novel`.
- Composition smells like "LLM + vector DB + agent loop = product" with no contradiction being
  resolved → flag Frankenstein risk, return `incoherent`.

**Artifact contribution (final):** `coherence_verdict` (one of four) + `contradiction_resolved` OR
`frankenstein_risk` (mutually exclusive, filled for non-incoherent) + `falsifying_experiment`
(mandatory for non-incoherent, HARD-RULE 2) + `recur_flag: false` (HARD-RULE 5) +
`judge_rationale` (one paragraph citing load-bearing findings and overrules).

**Rejection:** rubber-stamp without independent assessment (HARD-RULE 4), non-incoherent verdict
without falsifier (HARD-RULE 2), or `recur_flag: true` in v1 (HARD-RULE 5) → output rejected,
tribunal re-run.

---

## Sequential flow and handoff rules

Roles MUST run in order: Historian → Builder → Skeptic → Coherence Judge → `constraint-map.yaml`.
Each contributes: prior_era_constraints, then deltas_invoked + lifted_constraints, then
current_constraints + red_flags, then verdict + falsifier.

**Parallel execution is forbidden.** Each role is a critique-gate on the prior role's output.
Parallel collapses the tribunal into an echo chamber — the exact failure mode this skill is
designed to defeat.

**On rejected output** (per rejection criteria above): re-run that role once with the rejection
reason cited. Still failing after one re-run → `verdict: incoherent` with `judge_rationale:
"tribunal failed at <role>"`. Do NOT fake evidence.

**Judge-only final verdict.** Builder and Skeptic may express preferences; only the Judge emits
the verdict field.
