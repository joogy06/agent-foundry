---
name: innovation-first-principles
description: >
  Use when evaluating whether an idea is newly possible because of 2020→2026 capability
  deltas (LLM context, tool use, multi-agent, cheap inference, etc.), whether a proposed
  combination of elements will actually function, or whether stapling primitives together
  makes coherent sense. Runs a four-role "Capability Delta Tribunal" (Historian / Builder /
  Skeptic / Coherence Judge) and emits a signed constraint-map with one of four verdicts:
  novel-and-coherent, coherent-but-not-novel, novel-but-fragile, incoherent. Callable as a
  primitive by forge / founder-ideation / alf, or standalone. Trigger on: "is X newly
  possible?", "will this combination work?", "does it make sense to combine these?",
  "what capability delta unlocks this?", "forward-thinking check".
---

# Innovation — First Principles

A forward-thinking primitive that answers three questions about novel ideas:

1. **Forward-thinking.** Has this been done? If not, was it impossible before, or still impossible?
2. **Feasibility.** Will the combination actually function under 2026-era constraints?
3. **Coherence.** Does combining these elements make sense, or are they stapled primitives?

**Scope.** A constraint-removal explorer, not a feasibility checker. Does NOT design systems, write
code, or produce plans — hand off to `forge` for that. Does NOT replace `adversarial-team-brainstorm`
(critique primitive) or `founder-ideation` (venture-specific). Operates one abstraction layer above
`component-contract-mapping` — validates idea-level constraint claims, not code contracts.

**Callers.**
- `forge` — optional Step 2a pre-filter before approach exploration (v1.1)
- `founder-ideation` — "is this newly possible?" gate before adversarial brainstorm (v1.1)
- `alf` — periodic recur-detection during skill-library reviews (v1.1)
- standalone — user invokes directly with a problem statement (v1.1)
- **v1 spike**: primitive-only; callers pass `{problem, context}` and receive a `constraint-map.yaml`
  text block plus a verdict

---

## Core reframe

The skill is **not a feasibility checker. It is a constraint-removal explorer.**

The primary question is not "will this work?" but:

> **"What 2020-era constraint is this idea still respecting that no longer exists?"**

If no prior-era constraint is being escaped, the idea is **not innovation** — it is something nobody
built yet, possibly for good reasons (Chesterton's Fence). The skill's most valuable output is the
contrarian `coherent-but-not-novel` verdict: "yes it works, no it is not new, build it anyway if the
market is underserved — but do not frame it as innovation."

The three user questions fall out of the reframe:
- **Q1 forward-thinking** = "which prior-era constraint are we escaping?" (via capability delta)
- **Q2 feasibility** = "are there current-era constraints we're ignoring?" (anti-pro-innovation bias)
- **Q3 coherence** = "does removing the constraints resolve a contradiction, or is this a Frankenstein?"

---

## Three-layer architecture

**Layer 1 — Process: the Capability Delta Tribunal.** A four-role sequential hearing. Each role has
an explicit burden of proof and contributes to a shared artifact.

| Role | Burden of proof | Artifact contribution |
|---|---|---|
| **Historian** | "Has this been done? If not, what stopped it in 2020?" | `prior_era_constraints[]` |
| **Builder** | "Which 2020→2026 deltas actually remove those blockers?" | `deltas_invoked[]`, `lifted_constraints[]` |
| **Skeptic** | "Why will the combination still fail in practice?" | `current_constraints[]`, `red_flags[]` |
| **Coherence Judge** | "Is this a real system, or stack glue?" | `coherence_verdict`, `contradiction_resolved` or `frankenstein_risk` |

Roles run **sequentially**, each reading the prior role's output as evidence. The Judge runs LAST and
can downgrade the verdict regardless of Builder/Skeptic findings. Full protocol in
`references/tribunal-protocol.md`.

**Layer 2 — Artifact: `constraint-map.yaml`.** A diff-able, grep-able record of the tribunal's
findings. Core fields:

- `problem` + `problem_atoms[]` — decomposition of what the idea actually is
- `prior_era_constraints[]` + `lifted_by[]` — what 2020-era assumption is being escaped
- `current_constraints[]` — 2026-era realities the idea must NOT ignore
- `tribunal_findings` — per-role evidence
- `verdict` — one of `novel-and-coherent` / `coherent-but-not-novel` / `novel-but-fragile` /
  `incoherent`
- `falsifying_experiment` — mandatory for all non-incoherent verdicts
- `recur_flag` — hardcoded `false` in v1; v1.1 adds persistent recur-log

Full rubric and schema in `references/verdict-rubric.md`.

**Layer 3 — Gates (v1.1, deferred).** A thin Python validator that checks structural completeness of
the emitted `constraint-map.yaml` (all required fields present, delta-ids resolve to catalog entries,
verdicts in the valid enum, falsifier present when required). **Not in v1 spike** — the tribunal
output is exercised manually against 2–3 real problems before investing in automation.

---

## Invocation contract

Three modes. Only **Mode A (primitive)** is implemented in v1 spike. Mode B and Mode C shapes are
specified here so callers can rely on the contract; their invocation wrappers ship in v1.1.

### Mode A — Primitive (v1 spike)

Called by `forge` / `founder-ideation` / `alf` or any other caller.

**Input:**

```yaml
problem: string                # "autonomous coding agent with 1M context"
context:
  callers_lens: string         # optional — "forge-step-2a" / "founder-pregate" / "alf-review"
  prior_decisions: list[string]  # optional — any prior constraints the caller has already ruled in/out
  evidence_required: bool      # default true — whether Builder must cite delta-ids from the catalog
```

**Output:** a `constraint-map.yaml` text block conforming to the schema in
`references/verdict-rubric.md`, plus a one-line verdict summary.

### Mode B — Standalone (v1.1, specified for contract stability)

User invokes directly: `/innovation-first-principles "is X newly possible?"`. Same output shape as
Mode A. v1.1 adds clarifying-question loop when the problem statement is too vague for the Historian
to proceed.

### Mode C — Forge pre-filter (v1.1, specified for contract stability)

Optional `forge` Step 2a gate. Runs a 15–30s fast profile: Historian + Builder only, Skeptic and
Judge deferred. Returns `needs_full_tribunal: true|false` — if false, `forge` proceeds directly to
approach exploration with the partial map attached; if true, `forge` calls back for the full four-role
tribunal before approach exploration.

---

<HARD-RULE>
**Burden of proof per role.** Each tribunal role MUST cite evidence. A role that asserts without
evidence (delta-id from `references/capability-deltas-2020-2026.md`, precedent-id, or external URL)
is rejected. Historian cites historical precedent or impossibility mechanism; Builder cites
delta-ids; Skeptic cites failure modes with mechanism; Judge cites prior-role outputs. Opinion-only
responses break the contract.
</HARD-RULE>

<HARD-RULE>
**Falsifying experiment required.** Any verdict except `incoherent` MUST include a
`falsifying_experiment` field naming the cheapest test that would invalidate the verdict. No
falsifier = no verdict. The falsifier must be concrete (runnable in days, not quarters) and must
name the specific observation that would flip the verdict.
</HARD-RULE>

<HARD-RULE>
**`coherent-but-not-novel` is a valid verdict.** The skill has NO pro-innovation bias. When the
Historian finds the idea was already possible in 2020, the Builder/Skeptic/Judge MUST return
`coherent-but-not-novel` without special-casing. Rewriting it into "novel anyway" because the idea
is "interesting" breaks the skill. The contrarian verdict is the most valuable output.
</HARD-RULE>

<HARD-RULE>
**No self-grading. Judge runs LAST and can overrule.** The Coherence Judge reads all prior-role
outputs and has explicit license to downgrade. If the Judge finds Historian's constraint claim weak
or Builder's delta citation does not remove the claimed blocker, the verdict downgrades regardless
of Builder/Skeptic confidence. Tribunal roles cannot grade their own evidence.
</HARD-RULE>

<HARD-RULE>
**`recur_flag` hardcoded false in v1.** Every invocation emits `recur_flag` in the constraint-map
output. In v1 spike the field is hardcoded to `recur_flag: false` in all schema examples and all
emitted maps — no persistent recur-log storage yet. v1.1 adds the jsonl store at
`~/.claude/state/innovation-first-principles/recur.jsonl` and allows `true` when a pattern recurs
across 2+ sessions within 30 days. v1 callers MUST NOT branch on `recur_flag`.
</HARD-RULE>

---

## Anti-patterns

| Anti-pattern | Why it fails | Correct approach |
|---|---|---|
| Treating every idea as innovation | Pro-innovation bias erases the `coherent-but-not-novel` verdict — the skill's most contrarian and valuable output | The Historian's null result (no prior-era constraint escaped) is a legitimate finding. Return `coherent-but-not-novel` without apology. |
| Role collapse (Builder and Judge agreeing by default) | Tribunal degenerates into an echo chamber; Judge becomes a rubber stamp | Judge receives prior-role outputs AS EVIDENCE, with explicit license to overrule. HARD-RULE 4 enforces Judge-last. |
| Verdicts without falsifying experiments | Unfalsifiable opinion, not analysis — indistinguishable from LLM confabulation | HARD-RULE 2: mandatory `falsifying_experiment` field for all non-incoherent verdicts. |
| Citing "AI can do this now" as a delta | Too vague; no mechanism; the caller cannot check whether the delta actually removes the claimed blocker | Deltas must name a specific dimension (D-01 context window, D-02 inference cost, D-03 tool use, etc.) with measurable 2020-vs-2026 state. See `references/capability-deltas-2020-2026.md`. |
| Skipping current-era constraints | Pro-innovation bias — the failure modes matter more than the enabling deltas | Skeptic role's burden is explicitly "what WILL fail in 2026 practice." Without current-era constraints, the verdict caps at `novel-but-fragile`. |
| Merging into `constraint-map.yaml` without tribunal | Artifact without process is static data | Tribunal output is the source; in v1 spike the LLM follows `references/tribunal-protocol.md`. |

---

## Reference files

Read these as needed during tribunal execution:

- `references/tribunal-protocol.md` — the four-role hearing procedure: per-role burden of proof,
  evidence requirements, sequential flow (Historian → Builder → Skeptic → Coherence Judge), handoff
  rules between roles, rejection criteria.
- `references/verdict-rubric.md` — the 2×2 verdict taxonomy (novel × coherent), decision rules,
  mandatory-falsifier enforcement, full `constraint-map.yaml` schema, and worked examples of each
  verdict citing delta IDs.
- `references/capability-deltas-2020-2026.md` — the v1 seed catalog of 8 capability deltas
  (D-01..D-08) covering context window, inference cost, tool use, multi-agent orchestration,
  grounding, modality, latency, and persistent memory. Each entry lists 2020 baseline, 2026 state,
  lifted constraints, not-lifted constraints, and last-verified date.

---

## When NOT to use this skill

- **Implementation / coding.** Not the job — hand off to `forge` + `bob` with the verdict as input.
- **Pure critique of an existing plan.** Use `adversarial-team-brainstorm` — that is the critique
  primitive. This skill answers the prior question: "is this idea newly possible?"
- **Venture-specific ideation.** Use `founder-ideation` with its Reddit/GDELT grounding and
  kill-criteria enforcement. This skill can be called BY founder-ideation as a pre-gate but does not
  replace it.
- **Known-possible incremental work.** If the user knows the idea is possible and wants to build it,
  skip this skill entirely — the tribunal adds no value when the Historian's null result is
  predetermined.
- **Live production latency budgets.** The tribunal is slow (sequential four-role hearing). Do not
  put it on a user-facing response path.

---

Each boundary skill has a distinct abstraction layer; no overlap. See Scope section above for the
positioning of this skill vs `forge`, `adversarial-team-brainstorm`, `founder-ideation`,
`research-for-skills`, and `component-contract-mapping`.
