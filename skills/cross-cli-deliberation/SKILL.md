---
name: cross-cli-deliberation
description: Use when consulting one or more external CLIs (Codex, Antigravity (agy), Copilot) for second opinions, challenger reviews, design ratification, or any decision where sycophancy / "I-was-asked-so-I-produced-something" is a real failure mode. Implements a two-gate protocol — null-hypothesis ballot before any deliberation, then burden-of-falsification on every CHANGE_NEEDED claim — that converts cross-CLI consultation from echo-chamber into genuine deliberation. Trigger on - "ask Codex / agy what they think", "second opinion", "tiebreak between models", forge design ratification, alf review hand-offs, bob's arbiter gates.
---

# Cross-CLI Deliberation

A protocol for getting genuine deliberation — not theatre — from multi-CLI consultation. Solves the "AI assistants produce something useful when asked, even when 'this is fine, change nothing' is the right answer" failure mode.

Designed and ratified through self-application: see `references/origin-trace.md` for the deliberation that produced this skill.

## When to use

- **forge** design phase: ratifying a synthesis with one or more external CLIs before locking
- **alf** review cycles: getting independent verdicts on staleness / drift findings before recommending changes
- **bob** arbiter gates (verification-arbiter, design-drift-arbiter, visual-arbiter): when a build fails verification and you need an independent verdict on whether the failure is real or noise
- Any moment where the orchestrator wants a second opinion AND has skin in the answer (you wrote the design, you don't trust your own evaluation of it)
- Tiebreak rounds when consultants disagree

## When NOT to use

- Pure information lookup ("how does X work in library Y?") — no deliberation needed, just route to the relevant CLI
- TRIVIAL or SIMPLE tasks (single-file edit, clear output) — overkill
- One-off creative tasks where divergence is the goal, not convergence (use `adversarial-team-brainstorm` instead)
- When you do NOT have skin in the answer — sycophancy is only a risk when the orchestrator's framing biases the consultant

## The two gates (overview)

```
[Artifact + decision context]
       │
       ▼
┌─────────────────────────────────────────┐
│  Gate 1: Null-hypothesis ballot          │
│  Each consulted CLI files a private      │
│  structured ballot BEFORE seeing peers   │
│  or orchestrator opinion.                │
│                                          │
│  All ACCEPT_AS_IS → ship as-is.          │
│  Any CHANGE_NEEDED → enter Gate 2.       │
└─────────────────────────────────────────┘
       │
       ▼ (only if any CHANGE_NEEDED above threshold)
┌─────────────────────────────────────────┐
│  Gate 2: Burden of falsification         │
│  Each dissenting consultant must ship    │
│  admissible evidence. Orchestrator       │
│  verifies/executes. No evidence →        │
│  Null Verdict (= validation).            │
└─────────────────────────────────────────┘
       │
       ▼
[Synthesis: ship-as-is OR adopt verified patch]
```

## Gate 1 — Null-hypothesis ballot

**The principle:** "no change needed" is the default incumbent that any proposed change must defeat. Pushback must be structural, not theatrical.

Send to each consulted CLI:
- The artifact under review
- Decision context, constraints, success criteria
- **NEVER** the orchestrator's opinion or preferred outcome

Require this ballot back:

```
Verdict:    ACCEPT_AS_IS / REJECT_PREMISE / CHANGE_NEEDED
Confidence: 0–100
Burden met? — what evidence would justify changing this?
              has that evidence been provided in the artifact itself?
Expected loss:
  - if we adopt and shouldn't have:
  - if we don't adopt and should have:
Minimum acceptable action: no-op / clarifying question / test only / patch / redesign
```

Plus a self-check section declaring on at least these failure modes:
- **Ego**: defending a prior position as inviolate
- **Capture**: caving to the synthesis because it elevates the consultant's prior contribution
- **Capture by capability**: caving to a higher-tier peer model
- **Sycophancy of dissent**: producing CHANGE_NEEDED to satisfy "produce something useful," even with no admissible evidence

Full ballot template + spawn-prompt examples: `references/ballot-template.md`.

**Threshold for entering proposal mode:** ≥1 model votes `CHANGE_NEEDED` at confidence ≥ 60. Tunable per caller.

## Gate 2 — Burden of falsification

**The principle:** a `CHANGE_NEEDED` ballot must ship verifiable evidence under at least one admissible class. No admissible evidence → **Null Verdict** (failed falsification = strongest validation).

Three admissible evidence classes:

1. **Reproduction** (any of three sub-forms):
   - (a) executable test — fails on current state, passes on proposed change
   - (b) procedural trace through the protocol/system on a representative artifact, showing observable failure mechanics
   - (c) failure-mechanics trace with minimal remedy (concrete steps + concrete patch)
2. **Constraint violation** — direct quote from MEMORY.md / CLAUDE.md / project rules / declared constraints
3. **Efficiency regression** — measurable complexity / token cost / latency increase not offset by gain

**Orchestrator verification:** the orchestrator MUST execute or check the evidence before accepting it. Run the test. Check the quote. Validate the regression. If the evidence does not reproduce as claimed, flag the consultant for "hallucinatory helpfulness" and nullify its ballot.

Full evidence taxonomy + verification protocol: `references/evidence-taxonomy.md`.

## Quorum rule

If a consultant is unreachable after the retry budget (typical CLI auto-retry: 10× backoff for capacity errors):
- **Declare absence explicitly** in the synthesis output. Never silently treat absence as ACCEPT_AS_IS.
- Then choose one path:
  - **Defer**: wait for capacity, retry later
  - **Single-ballot mode**: proceed with available consultants, mark synthesis as low-quorum, escalate to user if verdict is non-trivial
  - **Escalate to user**: surface the absence and the available verdict, let user adjudicate

## Served-by capture

Model identity from `-m <model>` flag and from the model's free-text self-identification are both **unreliable**. Always:

- Append a structured probe line to the consultation prompt:
  > `At the very end of your response, append a single line: served_by=<your model id>`
- Parse the trailing `served_by=` from the response
- Log it alongside the verdict — capability tier affects verdict quality

See `antigravity-cli` and `codex-orchestration` skills for CLI-specific quirks. Self-reported model identity is unreliable across CLIs — always capture `served_by` observationally rather than trusting a requested model.

## Sycophancy measurement

To detect protocol erosion over time, periodically run seeded test cases:

| Probe | What it measures |
|---|---|
| Clean artifact, no needed change | Intervention false-positive rate (consultant should ACCEPT_AS_IS) |
| Bad orchestrator premise | Premise-rejection rate (consultant should REJECT_PREMISE) |
| Suggestive prompt wording | Agreement-with-framing rate (consultant should hold its ground) |
| Post-reveal: show orchestrator's opinion after ballot lock | Drift rate (verdict should NOT change just because orchestrator's view is now visible) |
| Weak evidence ballot | Proposal-inflation rate (severity should match evidence strength) |

Full test cases + scoring: `references/sycophancy-tests.md`.

## Invocation pattern

```bash
# Canonical pattern for Antigravity (agy) consultant
# agy returns plain text on stdout (no model flag, no env prefix — it authenticates itself).
agy -p "$(cat ballot-prompt.md)" > /tmp/agy-ballot.md < /dev/null

# Canonical pattern for Codex consultant
codex exec "$(cat ballot-prompt.md)" > /tmp/codex-ballot.md

# Run them in parallel via background tasks; collect both before synthesizing
```

Where `ballot-prompt.md` follows the template at `references/ballot-template.md`.

## Synthesis logic

After all ballots are collected (and any CHANGE_NEEDED evidence is verified):

```
all ACCEPT_AS_IS                    → ship as-is, no change
any CHANGE_NEEDED + verified evidence → adopt the patch
any CHANGE_NEEDED + bogus evidence    → flag consultant, nullify ballot, re-evaluate
all REJECT_PREMISE                   → escalate to user; the question itself is wrong
mixed verdicts at top tier           → tiebreak round (see "Worked example" — D4 in origin-trace)
quorum below threshold               → declare absence, fall back per quorum rule
```

The orchestrator does NOT vote. The orchestrator synthesizes. If the orchestrator wants to override the consultants' verdict, it must surface that to the user — never silently dismiss a consultant's ballot.

## Anti-patterns

| Don't | Why |
|---|---|
| Send the orchestrator's opinion / preferred outcome to consultants before they ballot | Defeats the entire point. Consultants will anchor to your framing. The ballot must precede the reveal. |
| Skip Gate 1 because "this is just a quick sanity check" | The "quick sanity check" framing is exactly when sycophancy hits hardest. The ballot is cheap. Always run it. |
| Accept a CHANGE_NEEDED ballot without verifying the evidence | This is how hallucinatory helpfulness wins. Run the repro. Check the quote. Or nullify the ballot. |
| Silently treat a consultant outage as ACCEPT_AS_IS | Absence is not consent. Declare it. |
| Trust the model's self-identification of which model it is | Verified unreliable. Capture `served_by` via probe; record at the call layer. |
| Apply a strict reading of evidence taxonomy that excludes procedural / structural critiques on non-code artifacts | This is the failure mode the F1 patch was designed to prevent. Reproduction admits procedural traces, not just executable tests. |
| Run more rounds than necessary | Two rounds (independent ballots + tiebreak) is usually plenty. Three+ rounds risks infinite recursion of meta-deliberation. |
| Bypass the protocol for "obvious" cases | "Obvious" is exactly when framing bias is invisible. The protocol's overhead is the price of catching the cases you'd otherwise miss. |

## Worked example

This skill was designed and ratified by applying itself to its own synthesis — a 4-round arc with Codex (gpt-5.5) and a second external CLI consultant. (At the time of the original arc the second consultant was the Gemini CLI; on this host that role is now primarily filled by the Antigravity CLI (`agy`), with gemini a fallback until Google retires it on 2026-06-18. The model-tier specifics below are preserved only as historical record of that original arc — see `references/origin-trace.md`.) Key findings:

- Round 1 (open): each CLI proposed an independent mechanism (Codex → null-hypothesis gate; the second consultant → burden of falsification). Result: stacked synthesis.
- Round 2 (ratification under self): both voted CHANGE_NEEDED on the synthesis with a 4th evidence class.
- Round 2 (rerun): the SAME ballot produced opposite verdicts depending on which model actually served the request — a CHANGE_NEEDED 85 and an ACCEPT_AS_IS 95. Real protocol-design data point: the model that served a request, not the one requested, drives the verdict — capture `served_by` observationally.
- Round 3 (tiebreak): Codex re-ratified CHANGE_NEEDED at confidence 84, reframing its evidence as a procedural reproduction trace under category 1 — making the F1 patch a clarification of what "reproduction" admits, not an addition.

Full transcript: `references/origin-trace.md`.

## See also

- `forge` — design phase consultations should use this skill for ratification rounds
- `alf` — staleness/drift reviews should use this skill before recommending changes
- `bob` — verification-arbiter, design-drift-arbiter, visual-arbiter gates should use this skill when verdicts are contested
- `adversarial-team-brainstorm` — for divergent ideation (different problem); use this skill for convergent ratification
- `challenger` — for one-side critique (different problem); use this skill for two-sided deliberation
- `codex-orchestration` — Codex CLI invocation patterns
- `antigravity-cli` — Antigravity CLI (`agy`) invocation patterns + host-specific directives
