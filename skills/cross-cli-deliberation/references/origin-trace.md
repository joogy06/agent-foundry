# Origin Trace

Record of the deliberation that produced this skill, captured here as both provenance and worked example. The protocol was self-applied during its own design — the artifact (this skill's stacked-protocol synthesis) was ratified through the very gates the artifact defines.

Date: 2026-05-04. Session in `/path/to/project` (then named `foundry-lab`).

> **Tooling note (historical record).** The original arc used the now-retired Gemini CLI as the second consultant, invoked with a per-call `-m <model>` flag and OAuth-tier routing. On this host that consultant role is now filled by the Antigravity CLI (`agy -p`), which exposes a single configured model — no `-m` flag, no env prefix, no tier selection. The model names and tier-routing mechanics below are preserved verbatim as a faithful record of what actually happened during that arc; they are NOT a description of the current invocation pattern. The transferable lesson — *capture `served_by` observationally; the model that serves a request, not the one requested, drives the verdict* — survives the CLI change.

## Round 1 — Open consultation (no protocol yet)

**Question to Codex and Gemini, asked in parallel without peer visibility:** what protocol or framing change would let multi-CLI consultation actually deliberate, where "no change needed" is a respected response and pushback is structural?

- **Codex (gpt-5.5)** proposed the **null-hypothesis ballot**: each CLI files a private structured ballot before seeing peers or the orchestrator's view. Verdict / confidence / burden / expected loss / minimum action. "No change" is the default incumbent. Sycophancy measurable via seeded probes.

- **Gemini (gemini-2.5-pro, served via OAuth tier)** proposed the **burden of falsification**: a CHANGE_NEEDED ballot must ship hard evidence under exactly one of three classes — reproduction script, constraint violation, efficiency regression. No artifact → Null Verdict. Orchestrator must execute the evidence; bogus evidence is "hallucinatory helpfulness."

The two proposals stacked cleanly: Codex's gate fires first (decide if anything should happen), Gemini's gate fires second (if change is proposed, ground it). Stacking rationale: Codex catches "I was asked, so I objected"; Gemini catches "I objected, so I invented a flaw."

Synthesis was constructed by the orchestrator (Claude Opus 4.7).

## Round 2 — Self-application (the synthesis voted on by both consultants)

Same protocol, both consultants asked to ballot on the synthesis itself.

- **Codex (gpt-5.5)**: `CHANGE_NEEDED 78`. Reproduction trace: a non-code protocol artifact with a structural objection cannot fit any of Gemini's three evidence classes → Null Verdict → valid dissent silently treated as validation. Patch: add 4th evidence class `counterexample trace`. Self-check: ego low-moderate, capture moderate.

- **Gemini Round 2 first attempt (model unclear, likely 2.5-pro)**: `CHANGE_NEEDED 85`. Reproduction trace: a monolithic implementation passes every test today but will require painful refactor for the next planned feature; consultant correctly votes CHANGE_NEEDED but no falsifying evidence under the three classes works for "future cognitive load." Patch: 4th class `Design Risk` with future-modification trace.

The two CHANGE_NEEDED verdicts converged on the same diagnosis from different angles: the 3-class evidence schema is too narrow for non-code artifacts.

## Round 2 (rerun) — Tier matters

After fixing Gemini CLI model selection (settings.json + OAuth subscription routing), the same Round 2 prompt was reissued.

- **No `-m` flag, settings.json default**: served by `gemini-2.5-pro` → `CHANGE_NEEDED 85` (consistent with first run).
- **`-m gemini-2.5-pro` flag (silently routed)**: served by **`gemini-3.1-pro-preview`** → **`ACCEPT_AS_IS 95`**.

Different served tiers gave different verdicts on the SAME ballot. The higher-tier model concluded: *"I have analyzed the stacked protocol for failure modes, constraint violations, and excessive cost, and I cannot construct a case for any of them. Under this system, the inability to falsify the proposal is the strongest form of validation."*

The protocol working as designed: gemini-3.1-pro-preview applied Gate 2 strictly, found no admissible evidence, voted ACCEPT_AS_IS, and acknowledged capture risk transparently.

This was the most informative finding of the arc. The protocol produces real disagreement — not echo — when applied to itself, and **capability tier affects the verdict**. Implications baked into the skill:
- Always capture `served_by` at the call layer.
- Pin top-tier models for deliberation work.
- Same-prompt verdict variance across tiers is real, not noise.

## Round 3 — Tiebreak at top tier

User asked Codex (gpt-5.5) to ratify its Round 2 verdict knowing gemini-3.1-pro-preview voted ACCEPT_AS_IS. Codex returned `CHANGE_NEEDED 84` (confidence raised from 78 → 84) with a **reframe**:

> "The burden is met as a *reproduction script for a decision protocol*: instantiate a concrete non-code proposal, a concrete valid objection, then apply Gate 2 strictly. The protocol produces Null Verdict because the objection is structural rather than script/quote/cost evidence. **Gemini's ballot strengthens the case by demonstrating the self-sealing reading: 'inadmissible under the current taxonomy' becomes 'therefore no failure exists.'**"

Codex no longer claimed a new evidence class. It classified its evidence as **Reproduction script under category 1** of the existing schema, arguing that "reproduction" admits procedural traces (sub-form b/c), not just executable tests (sub-form a).

This made the final patch a **clarification of what reproduction admits** rather than an addition of a new category.

Self-check (transparent):
- Ego: moderate — defending Round 2 vote but revising the justification.
- Capture by capability: low-moderate — Gemini's confidence "relevant but not decisive; its reasoning appears to instantiate the failure mode under dispute."
- Sycophancy of dissent: moderate — controlled by keeping the patch narrow.

## Final synthesis (locked at decision F1)

Gate 2 reproduction class explicitly admits three sub-forms:
1a. Executable test (current state fails, proposed state passes)
1b. Procedural trace (step-by-step through the protocol/system on a representative artifact)
1c. Failure mechanics with minimal remedy (trace + concrete patch)

Constraint violation and efficiency regression unchanged.

The synthesis became the SKILL.md you're reading.

## What the protocol's self-application demonstrated

- **Genuine disagreement, not echo**: Codex consistently CHANGE_NEEDED; Gemini-3.1-pro-preview ACCEPT_AS_IS. Same prompt, contrary verdicts, both grounded in the protocol's own rules.
- **Tier matters**: Gemini-2.5-pro and Gemini-3.1-pro-preview returned opposite verdicts on identical input. Tier-stratified verdict variance is a real protocol-design concern.
- **Self-validation works**: the protocol applied to its own synthesis surfaced a real failure mode (the F1 patch). The fact that the patch itself was contested across tiers is also evidence the protocol handles disagreement without collapsing.
- **Recursive observation**: Codex's Round 2 evidence wouldn't qualify under Gate 2 as Gemini-3.1-pro-preview read it. That's either (a) proof the schema needs widening, or (b) proof Codex was producing-because-asked. The Round 3 reframe (Codex re-classified its evidence as procedural reproduction under category 1) collapsed both interpretations: the patch is right either way, just framed differently.

## Operational lessons baked into the skill

- Capture served_by at the call layer; never trust model self-ID. (Probe: append `served_by=<model>` line to prompts.)
- Quorum rule: declare absent consultants explicitly. (One consultant round failed with 10× 429 retries; the implicit "missing ballot = no opinion" must be explicit.)
- Use a top-tier model for deliberation work where the CLI lets you choose; on a single-model CLI like `agy`, capture `served_by` observationally and treat verdict variance across model versions as real.
- The orchestrator must verify every CHANGE_NEEDED evidence — running the trace, walking the steps, checking the quote.
- Requested model identity is advisory; server-side routing dominates. Capture observationally.

## Ledger of model selection during the arc

| Round | Consultant | -m flag asked | served_by actual | Verdict |
|---|---|---|---|---|
| R1 | Codex | n/a | gpt-5.5 | "Burden of falsification" proposal |
| R1 | Gemini | none | gemini-2.5-pro (likely) | "Null hypothesis" proposal |
| R2 | Codex | n/a | gpt-5.5 | CHANGE_NEEDED 78 |
| R2 | Gemini (1st) | none | gemini-cli (self-ID broken) | CHANGE_NEEDED 85 |
| R2 (rerun, no flag) | Gemini | none | gemini-2.5-pro | CHANGE_NEEDED 85 |
| R2 (rerun, -m 2.5-pro) | Gemini | gemini-2.5-pro | **gemini-3.1-pro-preview** ← surprise | **ACCEPT_AS_IS 95** |
| R3 | Codex | n/a | gpt-5.5 | CHANGE_NEEDED 84 (reframe) |

The "asked vs served" divergence in the second R2 rerun is itself a protocol-design data point — orchestrator-controlled model identity is unreliable.
