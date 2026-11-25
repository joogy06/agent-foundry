# avengers — Dialogue Protocol (reference)

The phase machine every avengers session runs. This is the authoritative prose
for design §4. In v1 the phase *transitions* are enforced by `kernel.py` (WP-2);
in the WP-1 vertical slice a **prose chair** drives them by hand (no kernel). The
phases, side exits, and their guarantees are identical either way.

```
CONVENE → BLIND_DIVERGE → DOCKET → CROSS_EXAM (1..2 cycles) → CONVERGE → ARBITER → ROUTE → WRITEBACK_PROPOSE → CLOSED
                                                                       side exits: ABORTED, LOW_QUORUM  (never silently converted to success)
```

## Contents

- Roles
- CONVENE
- BLIND_DIVERGE
- DOCKET
- CROSS_EXAM (1..2 cycles; budgeted by `max_cycles`)
- CONVERGE — task-family-dependent semantics
- ARBITER
- ROUTE
- WRITEBACK_PROPOSE
- CLOSED
- Side exits — never silently converted to success
- User interjections (first-class, non-blocking)
- Anti-sycophancy invariants (design §2/§3, inherited from cross-cli-deliberation)

## Roles

- **Member seats** — the deliberators. Each carries a role card with an INCENTIVE
  LOCK (`roster/<seat_id>.yaml`) and a provider affinity (Claude / Codex / agy). A
  card splits into a persona-free CORE incentive (always active) + an optional
  **divergence overlay** (v2, design §3) injected ONLY in blind-diverge/ideation and
  stripped for converge/verify/arbiter; the overlay lint rejects decorative/demographic
  overlays at validate time.
- **Steward** (v2, design §5) — a **principal-proxy** member seat
  (`roster/steward.yaml`, `adversarial_role: false`). It represents the requester's
  desired outcome, grounded in a durable-or-provisional **`intent.md`** artifact; it
  pushes on drift and judges "is this what was asked / good enough?" It has skin in the
  outcome, so it **NEVER decides and NEVER arbitrates**
  ([`intent-artifact.md`](intent-artifact.md)).
- **Chair** — the orchestrator. **Non-voting, stateless, receives NO member
  memory, never opines on the merits, never leaks a preferred outcome.** It
  dockets, judges obligation status, decides re-prompts, and handles malformed
  output (1 retry, then `no-show`).
- **Arbiter** (v2, design §4) — a **fresh, persona-free, deliberation-EXTERNAL
  cold-context CALL**, NOT a promoted seat: it did not file a position, argue, or
  ballot, so no seat both ballots and adjudicates. Its provider is **selected by
  `convene.py`** (never inherited from a seat) and **differs from every deliberation
  seat's provider** on the clean path (widened from adversarial-only). It runs the
  shared ATB output-synthesis policies via `arbiter_mode`. Full rules in the ARBITER
  section below and [`convene-contract.md`](convene-contract.md).

## CONVENE

Resolve the profile → a frozen flat JSON `session-plan.json` (profile-sha
provenance), inject the guard stacks, run the fail-closed structural validate
(including the sub-quorum and arbiter/adversarial-provider checks below), create
the session directory. No seat is called until validation passes; `--dry-run`
prints a pre-spend review and stops.

## BLIND_DIVERGE

All member seats run **in parallel, in a single batch, sealed until every seat
finishes; simultaneous reveal.** A seat sees ONLY: its trust envelope + identity
+ standing memory records. **No episodics, no peer positions, no chair opinion.**
This is the core anti-sycophancy control (inherited from `cross-cli-deliberation`):
positions are formed before any peer or chair signal can contaminate them. The
"simultaneous reveal" is a presentation rationale (clarity / scorecards-up); the
sealing is what actually prevents contamination.

## DOCKET

The chair reads all blind positions and files **≤6 issues** — the material
disagreements and unsupported claims. Each issue is a `challenger → named
respondent` pair and **seeds the obligation ledger**. The docket issues ARE the
initial obligations.

**`evidence_run` request path (v2, design §6).** During DOCKET (and CROSS_EXAM), any
seat may **REQUEST** execution of an EXISTING test suite / benchmark / read-only probe
instead of speculating (the skeptic says "run the suite against the proposal's branch").
`convene.py` phase-gates the request (`EVIDENCE_REQUEST_PHASES = {DOCKET, CROSS_EXAM}`)
and delegates to the sandboxed `scripts/evidence_run.py` runner. Results enter the docket
as **fenced, UNTRUSTED-class DATA** in seat prompts (like peer records / member memory) —
they carry NO executable authority. `evidence_run` is **read-only, time-boxed, and
NEVER writes / NEVER spawns bob** (the NON-MUTATING HARD-RULE holds verbatim; a run is
admitted only with OS-sandbox prevention OR git-clean detection). A seat supplies only a
`probe_id` from a TRUSTED registry — a raw command in the request is refused.

## CROSS_EXAM (1..2 cycles; budgeted by `max_cycles`)

- **Addressed turns only** (`@seat`). Obligation-holders respond **FIRST and
  serially** — a rebuttal must see the latest state, so no parallel-turn phantom
  disagreements. Then each seat may raise **≤2 new challenges per cycle**.
- **A turn must add value**: new evidence, expose a contradiction, or concede.
  Pure repetition is **not** a turn.
- **`NONE_FOUND` is admissible** — a seat that finds nothing to attack says so and
  states what it tested. Never force fake dissent.
- **Cycle 2 runs ONLY if** a named unresolved obligation carries new evidence.
- **Stalemate detector**: after **2 unchanged exchanges** on an obligation
  (an INTERNAL counter, distinct from `max_cycles`), the obligation **flows to the
  arbiter as unresolved dissent**. This is the termination guarantee — the process
  cannot loop forever.

Obligation statuses (`answered` / `conceded` / `stalemate`) are **judged by the
chair**, not self-declared by seats (self-declaration is gameable).

## CONVERGE — task-family-dependent semantics

- **Ratification families** (e.g. `coding-ratification`; research claims vs a
  stated incumbent): each seat privately files a cross-cli **Gate-1
  null-hypothesis ballot**: `ACCEPT_AS_IS` / `CHANGE_NEEDED` (+evidence) /
  `REJECT_PREMISE`. Ballots are **private** — no peer-ballot visibility.
- **Generative families** (`business-ideation`, `writing-cv`, `website-ux`):
  each seat files a dissent-schema convergence: final position + **required**
  `unresolved_concerns[]` + `compromises_made[]`. Empty concerns are allowed
  ONLY with an explicit "genuine unanimity" declaration.

**Steward intent-alignment assessment (v2, design §5).** In profiles that resolve a
steward, the steward emits — alongside its ballot/position — an **intent-alignment
assessment**: for each `intent.md` item, a status of `pass | fail | unknown`. A `fail`
(drift from the stated outcome) becomes an actionable **trip-wire** on the decision; an
`unknown` (no finding for that item) becomes a **confirm** flag (escalate, never invent).
On a provisional intent (no `intent.md`), the steward carries the "operating on inferred
intent — confirm" flag. The external arbiter weighs the steward's push like any seat; the
assessment reaches the human as trip-wires / confirm-flags.

## ARBITER

A **fresh, persona-free, deliberation-EXTERNAL cold-context CALL** (v2, design §4) —
NOT a promoted seat. It did not file a position, argue, or ballot, so **no seat both
ballots and adjudicates** (the participant-judge violation is gone). Its provider is
**selected by `convene.py`, never inherited from a seat**:

- **CLEAN path** — a provider used by **no** deliberation seat: genuinely external,
  authorship linkage total-excluded, **no residual**.
- **FALLBACK path** — no eligible provider is free of deliberation: the
  strongest-adjudication-prior **non-adversarial** provider, cold-context. Authorship is
  anonymized, but style-recognition self-preference is an **ACCEPTED, DOCUMENTED residual**,
  flagged `fallback_arbiter_residual: true` in `run-record.json` (§6a).
- **ALL-ADVERSARIAL** — every eligible provider deliberated **and** every one is
  adversarial: no non-adversarial arbiter exists → **fail CLOSED** (`ConveneError`). The only
  unsatisfiable arbiter case; it never hangs.

**agy never arbitrates a healthy session (S081 revision 4, amendment 3 D25 + D23, scoped by
D29), and it is barred from SELECTION in code** (`convene.ARBITER_INELIGIBLE_PROVIDERS`,
applied in `_select_arbiter_provider`), not merely absent by accident. This is the half of D25
that is easy to miss: D25 removed agy's *seats* from every profile but `research-synthesis`,
and a provider with no seat is precisely what qualifies for the CLEAN path — so the seat
removal, left alone, would have **promoted agy from member to arbiter**. Measured before the
bar was added: `coding-ratification` resolved agy (the agy family of the day), path clean, in the
one profile whose arbiter the amendment says is Claude (the Claude main tier). #368 seated agy
again in every profile, so agy is no longer a clean-path candidate; the bar still keeps agy, a
non-adversarial seat, off the fallback path, and the healthy arbiter stays Claude.

**The bar is scoped (D29, user-approved 2026-09-19).** It applies only while no provider is
excluded. A session that has already lost a provider — codex unavailable at plan build, a codex
seat substituted (an admission refusal included), or codex excluded after the arbiter pin found
no eligible model — keeps agy as the **last-resort arbiter** rather than failing closed: on any
codex refusal `coding-ratification` resolves `agy gemini-4-argon-high, path fallback` (path clean
before #368 seated agy there). (Barring
agy unconditionally made 32 substitution paths fail closed, `coding-ratification` among them.)
A declared arbiter is not selection and does not consult the bar; no shipped profile declares agy.

The consequence is stated plainly rather than presented as equivalence. **Since #368 every
profile is a three-provider deliberation (Claude + codex + agy), and every healthy-session
arbiter is Claude** — D25 had made the four profiles other than `research-synthesis` two-provider
(Claude + codex); #368 added ONE agy (Gemini 4 Argon) seat to each, on the main weight, keeping
every existing seat (business-ideation `user-advocate`, website-ux `operator`, writing-cv
`architect`, coding-ratification `user-advocate`). Every profile seats agy, so the clean path is
unreachable while codex serves, and each arbiter is either **DECLARED** (`business-ideation`,
`research-synthesis`, `website-ux`, `writing-cv`: the Claude support tier through the protected
`consultant_support` row, `arbiter_independence: separate-session`, context independence standing in
for provider independence) or a **recorded FALLBACK residual** (`coding-ratification`: the selected
Claude `arbiter` row, the Claude main tier, `fallback_arbiter_residual`). agy is a *seat* everywhere,
never an arbiter of a healthy session. A session whose codex arm is refused (every codex seat
re-seated on the Claude main tier) no longer has a Claude-only deliberation: every profile's codex
outage still leaves a Claude + Google round, and its dissent record must name the OpenAI gap (jc10).
The four declaring profiles keep their Claude support-tier arbiter, while `coding-ratification`'s
recomputed arbiter is agy, on the fallback path.

`can_arbitrate` on the seats is **inert** under v2. The adjudication prior comes from the
editable `capability-priors.yaml` DATA (fail-open to built-ins). The arbiter runs the
shared ATB output-synthesis policies via `arbiter_mode`:
- **Synthesizes over ALL positions** — a position is never dropped from the synthesis
  set; the docket it sees is **authorship-anonymized**.
- **Survivor selection keyed on open/stalemate obligations** — the arbiter does
  not re-litigate settled points.
- **No invention** of novel proposals not raised by a seat.
- **Grounding rule**: no confidence above `speculative` without external
  grounding.
- **≥2 kill-criteria / trip-wires** on any decision — actionable ("reopen if X").
- **MANDATORY dissent record** with attribution + **convergence margin**:
  `unanimous` / `converged N-M` / `arbiter broke tie`.

## ROUTE

By profile `outcome` and caller (design §8):
`decision` | `deliverable` | `forge_brief` | `auto`. Build-flavored outcomes exit
as an `avengers_brief` into **forge's** gate machinery — avengers never spawns
bob, never signs a contract map, never marks anything bob-ready.

## WRITEBACK_PROPOSE

The chair drafts ≤3 memory candidates (PII profiles 0–1), **default-reject,
per-item**; proposals **persist home-tier** at
`~/.claude/projects/<slug>/avengers/proposals/<session-id>.json` for later batch
approval. **Never blocks** an unattended run; never silently discards. (Full
subsystem lands in WP-3; WP-1 has no memory subsystem — this phase is a no-op in
the vertical slice and is recorded as deferred.)

## CLOSED

Write the outcome (`decision-record.md` | `deliverable.md` |
`avengers-brief.yaml`) plus the **always-present `dissent-record.md`**, the
footer line, and the served-by log. Print the session directory.

---

## Side exits — never silently converted to success

### LOW_QUORUM — two distinct cases

- **(a) Convene-time structural sub-quorum** — the resolved profile yields
  **<3 member seats**, OR **<2 provider families** with no declared fallback,
  **OR the external arbiter is unsatisfiable** (v2: every provider deliberated
  **and** every one is `adversarial_role: true`, so no non-adversarial external
  arbiter exists — the all-adversarial case). → `convene.py` **fail-closed validate
  error. No run, no spend.**
- **(b) Runtime collapse** — seat no-show / failover during the session drops the
  live roster below the quorum floor. → the run **CONTINUES if ≥2 member seats
  remain**; the result carries `status: LOW_QUORUM`, confidence is capped `low`,
  and the label is printed in the footer and the decision record. **<2 remaining
  seats → `ABORTED`.**

### ABORTED

Fewer than 2 member seats remain live, a hard budget is exhausted before a result
exists, or an unrecoverable resolver/IO error. The session records `status:
ABORTED` with the reason. **Never** dressed up as a completed deliberation.

---

## User interjections (first-class, non-blocking)

Scheduled `seat=user` turns, **queued**, applied at the next turn/phase boundary.
Verbs: `constraint:` (broadcast), `@seat:` (addressed), `converge now`,
`extend/drop-thread`. **Absence never blocks** (gate table, design §9) — an
unattended run completes and parks its memory-writeback proposals for later.

## Anti-sycophancy invariants (design §2/§3, inherited from cross-cli-deliberation)

1. Blind positions **before** any peer visibility.
2. Burden of evidence is on the **change-claim**, not the status quo.
3. The chair's / user's opinion **never** enters a seat prompt.
4. A `served_by` probe on every external call — recorded as provider-**REPORTED**,
   not verified.
