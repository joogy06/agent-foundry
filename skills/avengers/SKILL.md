---
name: avengers
description: >
  Use when a decision, design, claim, or deliverable needs STRUCTURED CONTENTION
  from a standing team of AI members with deliberately conflicting incentives and
  mixed providers (Claude / Codex / agy) — sustained addressed dialogue, not a
  single-agent monologue and not a one-shot tournament. The deliberation surface
  of the orchestration layer and a sibling of forge: it convenes per task from
  declarative composition profiles, runs blind-diverge → docket → cross-examine →
  converge → arbiter, and returns ONE decision / deliverable / forge_brief with a
  mandatory attributed dissent record and actionable trip-wires. Trigger on:
  "convene the team", "deliberate on X", "ratify this decision", "have the panel
  weigh in", "red-team this with the standing team", "get conflicting expert
  takes", "avengers on this". NOT for hierarchical execution (that is bob +
  agent-teams) and NOT for ephemeral idea tournaments (that is
  adversarial-team-brainstorm).
---

# avengers — Standing AI Deliberation Team

A standing professional team: persistent members with conflicting incentives,
mixed providers, sustained addressed dialogue, per-member project-tier memory,
convened per task from declarative profiles. **Deliberation, not delegation.**

> **v1 build status:** COMPLETE. WP-1 vertical slice (SKILL.md, dialogue-protocol
> reference, minimal `seat_prompt.py`, `coding-ratification` profile, three role
> cards + one live end-to-end session) → WP-2 deterministic kernel/resolver
> (`kernel.py`, `convene.py`, session-plan schema) → WP-3 memory subsystem
> (`memory_writeback.py`, complete 7-section `seat_prompt.py`) → WP-4 upstream ATB
> `arbiter_mode` + forge `came_from_avengers` intake → WP-5 remaining profiles/role
> cards, the outcome router, this UX surface, the adversarial-fixture suite, the
> visual-companion adapter note, and `reuse-map.md`.

> **v2 team-composition redesign:** COMPLETE (2026-07-13, design
> `docs/plans/2026-07-13-avengers-v2-team-composition-design.md`). A NON-mutating
> redesign of the team-composition internals. The v2 surface:
> - **Constraint-based diversified staffing** — `capability-priors.yaml` (owned DATA,
>   fail-open) + seat affinity + an ordered-constraint resolver; per-seat provider pins
>   become **opt-in DATA** (a profile with no pins resolves a valid ≥2-family staffing).
> - **Seat-class effort semantics** — effort pins resolve per `(provider, seat-class)`;
>   a challenger provider-swap off codex no longer crashes the resolver (it records a
>   "no anti-sycophancy floor for this provider" note). The retired tier `high` stays
>   rejected.
> - **External, SEATLESS, cold-context arbiter** — the provider is SELECTED (never a
>   promoted seat); no seat both ballots and adjudicates. Clean/fallback paths;
>   `fallback_arbiter_residual` flagged; all-adversarial fails CLOSED.
> - **The steward** — a principal-proxy member seat grounded in a durable/provisional
>   `intent.md`; pushes on drift, emits a converge intent-alignment assessment, and
>   **never decides / never arbitrates**.
> - **`evidence_run`** — a sandboxed, read-only, time-boxed runner any seat may REQUEST;
>   results enter the docket as fenced UNTRUSTED DATA. NEVER writes, NEVER spawns bob.
> - **Divergence overlays + lint**, **memory provider-stamping**, and **`run-record.json`**
>   (§6a instrumentation, non-optional).
> - **ONE rebuilt profile** — `coding-ratification` (4 deliberation seats + external
>   arbiter, `max_seat_calls: 13`). The other four profiles + everything else v2 chose
>   not to build are recorded in [`references/v2-deferred-backlog.md`](references/v2-deferred-backlog.md)
>   (nothing deferred silently).

## What it is (and is not)

- **Sibling of forge**, not a subcomponent. Callers: the user directly (primary),
  pa, forge (design-exploration mode), founder, alf.
- **Deliberation vs delegation**: bob + agent-teams own hierarchical execution.
  avengers owns structured *contention*. It does not create work packages, own
  files, or verify builds.
- **Sibling of `adversarial-team-brainstorm` (ATB)**: seats not teams; sustained
  addressed dialogue not fixed tournament rounds; ONE decision/deliverable not a
  ranked idea list; persistent members not ephemeral lenses. The arbiter
  **output-synthesis** machinery is SHARED with ATB via the upstream `arbiter_mode`
  switch, never forked. (v2: the arbiter *provider* is selected internally — external
  and seatless — which is orthogonal to that output-synthesis switch.)

<HARD-RULE>
EXECUTION BOUNDARY. avengers is a deliberation surface, NOT an executor.
avengers NEVER spawns bob, NEVER signs contract maps, and NEVER marks anything
bob-ready. Build-flavored outcomes exit ONLY as an `avengers_brief` handed into
forge's gate machinery (classification → contract map → spec review → bob), where
`contract_map_signed: false` and `bob_ready: false` are mechanically always-false.
Deliverable/decision outcomes return directly to the caller, ALWAYS with a
dissent record. There is no path by which avengers itself starts a build.
</HARD-RULE>

<HARD-RULE>
DELIBERATION INTEGRITY (anti-sycophancy, inherited from cross-cli-deliberation).
(1) Member seats form BLIND positions before any peer or chair signal is visible.
(2) The chair/orchestrator and the user opinion NEVER enter a seat prompt; the
chair is non-voting and never leaks a preferred outcome. (3) The burden of
evidence is on the CHANGE-claim, not the status quo. (4) `NONE_FOUND` (with what
was tested) is a valid, honest seat answer — NEVER manufacture dissent to look
useful. (5) The dissent record is MANDATORY on every outcome, with attribution
and a convergence margin (`unanimous` / `converged N-M` / `arbiter broke tie`); a
unanimous run prints the honesty line rather than hiding that a single agent might
have sufficed.
</HARD-RULE>

<HARD-RULE>
EXTERNAL SEATLESS ARBITER (v2, design §4 — the highest-value fix). The arbiter is a
FRESH, persona-free, deliberation-EXTERNAL cold-context CALL — it did NOT file a
position, argue, or ballot, and is NOT a promoted seat. NO seat both ballots and
adjudicates (the participant-judge violation is gone). Its provider is SELECTED by
`convene.py` (never inherited from a seat): a provider used by no deliberation seat
(CLEAN path, no residual), else the strongest-adjudication-prior NON-adversarial
provider cold-context (FALLBACK path — authorship anonymized, style-recognition
self-preference an ACCEPTED residual flagged `fallback_arbiter_residual: true` in
`run-record.json`). Every provider deliberating AND every one being adversarial is the
ONLY unsatisfiable case → fail CLOSED (`ConveneError`, no run, no spend). `can_arbitrate`
on seats is INERT under v2. The adjudication prior is editable `capability-priors.yaml`
DATA (fail-open to built-ins). The arbiter synthesizes over ALL positions (never drops
one) on an authorship-anonymized docket.
</HARD-RULE>

<HARD-RULE>
GUARD STACKS ARE RESOLVER-INJECTED INVARIANTS, not per-prompt discipline. Every
external seat call uses its pinned stack verbatim:
- codex: `timeout <T> codex exec --ephemeral -s read-only -c model_reasoning_effort=<tier> "…" < /dev/null`
  — per-call effort PINS (xhigh floor for challenger/ballot/arbiter seats; max for
  ratification-arbiter calls with `timeout 1200`); the tier `high` is RETIRED and
  MUST be rejected by validation; retry once on capacity.
- agy: `timeout 600 agy --sandbox [flags-before -p] -p "…" < /dev/null`
  — advisory-only preamble; NO `--add-dir` in v1; `git status --short` tripwire
  after any repo exposure.
A `served_by` probe rides every external call and is recorded as provider-REPORTED
(not verified). Zero un-pinned codex calls.
</HARD-RULE>

<HARD-RULE>
MEMBER MEMORY IS FILE-BASED, HOME-TIER, AND HUMAN-INSPECTABLE — never
provider-native session resume / hidden memory. v1 tier = PROJECT only
(`~/.claude/projects/<slug>/avengers/…`); the loader REFUSES any member-memory
path outside `~/.claude/projects/<slug>/` and there is NO global-tier loader
branch in v1. Standing memory is admitted ONLY from the four admissible source
classes (user_confirmed_constraint / verified_project_artifact /
user_selected_decision / observed_outcome); seat opinions, refuted positions, and
single-session conclusions are NOT admissible. Write-back is gated: default-reject,
per-item, proposals persist home-tier for later approval. **v2 provider-stamping:**
every standing-memory entry is stamped with its writing provider; an INHERITED entry
(writing provider ≠ the reading seat's provider) renders THIRD-PERSON at prompt
assembly ("the previous skeptic (codex) recorded …"), converting the cross-provider
first-person confabulation hazard into calibration metadata.
</HARD-RULE>

## The dialogue protocol

`CONVENE → BLIND_DIVERGE → DOCKET → CROSS_EXAM (1..2 cycles) → CONVERGE →
ARBITER → ROUTE → WRITEBACK_PROPOSE → CLOSED`, with the `ABORTED` and
`LOW_QUORUM` side exits (never silently converted to success). v2 adds, WITHIN
DOCKET/CROSS_EXAM, the **`evidence_run` request path** (any seat may REQUEST a
sandboxed read-only probe; results enter as fenced UNTRUSTED DATA), and, at
CONVERGE, the **steward's intent-alignment assessment** (per-item pass/fail/unknown →
trip-wires / confirm-flags). Full semantics: **`references/dialogue-protocol.md`**.

## UX contract (design §9)

### Gate table (definitive — which pauses BLOCK)

| Gate | Blocking? |
|---|---|
| Pre-convene triage: "this looks single-agent-shaped — convene anyway?" (fires ONLY when inference says the cheap path wins) | **yes, once** |
| Roster / estimate confirmation card | **yes** — skippable with `--go` |
| forge-brief handoff | **yes, ALWAYS** (even under `--go`) |
| Blind-reveal pause, phase boundaries, memory approval | **never block** — interjections are queued; write-back proposals persist for later |

The blocking gates are the ONLY three. Everything else runs unattended and never
stalls: user interjections are queued and applied at the next turn/phase boundary
(absence never blocks), and memory write-back proposals persist home-tier for a
later `avengers memory review` rather than pausing the run.

### Pre-convene triage gate

Before spending a single seat call, if inference says the task looks
single-agent-shaped (a lookup, a one-answer question, no genuine axis of
contention), avengers asks ONCE: *"This looks single-agent-shaped — convene the
team anyway?"* A `--go` invocation still honors this one gate. This is the
pre-spend defense against sycophancy-theater-at-full-price (design §13.1).

### Estimator (upfront, before the confirmation card)

Shown as `~N seats · ~M calls · est. X–Y min`, derived from the profile shape ×
per-call latencies. **Cold-start seed constants (pinned, from 2026-07-11 measured
runs; `convene.py::SEED_LATENCY_S`):**

| Provider · tier | Seed latency |
|---|---|
| codex `xhigh` | 60s median (30–120s range) |
| codex `max` | 300s |
| agy | 45s |
| Claude seat spawn | 60s |

Recorded actuals per session self-calibrate thereafter (success criterion #4:
estimator within 2× of actual by run 1 via the seeds). `convene.py --dry-run`
prints the estimator band as part of the pre-spend review — no session, no spend.

### Narration — `--narrate quiet|digest|full` (default `digest`)

- `quiet`: outcome + dissent record only.
- `digest` (default): phase-boundary digests + per-round clash digests.
- `full`: verbatim turns to the terminal (always written verbatim to disk
  regardless of the flag).
- **Spoiler discipline during `BLIND_DIVERGE`**: progress only ("3/3 seats in"),
  never a seat's content, until the simultaneous reveal — this is what prevents
  user contamination of blind positions.
- Liveness: a per-external-call heartbeat with the typical duration from the
  estimator seeds.

### Footer (every completed run)

```
Xm Ys · N calls · M seats · converged A-B · K open trip-wires
```

The convergence margin (`unanimous` / `converged N-M` / `arbiter broke tie`) is
MANDATORY. **Unanimous runs print the honesty line**: *"unanimous, empty dissent —
a single agent would likely have sufficed"* — the team never hides that the
contention it charged for did not materialize.

### Output ordering — dissent first

The dissent record is surfaced BEFORE the decision/deliverable body (design §9).
Trip-wires are actionable ("reopen if X"), never vague. The `forge_brief` route
always stops at the ALWAYS user gate before entering forge's machinery. Full route
semantics: **[`references/outcome-routing.md`](references/outcome-routing.md)**.

### Visual track

`website-ux` auto-invokes visual-companion `show-comparison` at ROUTE time — a
deliberate override of visual-companion's offer-first default (adapter note in
`skills/visual-companion/SKILL.md`). Elsewhere the visual companion is offered
once; never for pure-text deliverables.

### Inspection

`avengers roster [<profile>|<member>]`, `avengers member <id>` (read-only); the
session directory is printed at start and end.

## Architecture (honest split)

Code where determinism is load-bearing AND semantics-free; LLM judgment where
semantics live.

| Piece | Kind | Charter |
|---|---|---|
| `scripts/kernel.py` | code | phase legality/transitions, budgets, quorum, atomic transcript append, JSON event log — no LLM, no network |
| LLM chair | prose | non-voting orchestrator; dockets, judges obligation status, never opines |
| `scripts/seat_prompt.py` | code | THE single trust-envelope assembler (7-section; v2: overlay inject/strip, memory provider-stamp, fenced evidence-run DATA, `intent.md` reader) |
| `scripts/convene.py` | code | fail-closed resolver → frozen flat-JSON session-plan (v2) + injected guard stacks + external seatless arbiter + `run-record.json` + evidence-request path |
| `scripts/evidence_run.py` (v2) | code | sandboxed, read-only, time-boxed probe runner; NEVER writes, NEVER spawns bob |
| `roster/*.yaml`, `profiles/*.yaml`, `capability-priors.yaml` | DATA | identity cards (core + overlay), composition profiles, adjudication/affinity priors (fail-open) |
| memory subsystem | code+DATA | admissibility + gated write-back + provider-stamping |

**Security posture (honest):** fences, JSON-escaping, and schema extraction are
parser-integrity controls. Semantic injection (persuasive instructions inside
valid data) has a REAL residual, mitigated by the trust envelope + memory
admissibility + shipped adversarial fixtures + chair adjudication — never claimed
"structurally secure".

## Files (v1 + v2 surface)

- `SKILL.md` — this file (slim parent + the §9 UX surface).
- `references/` — `dialogue-protocol.md` (§4 phase machine), `convene-contract.md`
  (§8 input contract + external arbiter + run-record), `outcome-routing.md` (§8 output
  router + `avengers_brief` schema), `intent-artifact.md` (v2 §5 steward `intent.md`
  contract), `memory-policy.md` + `trust-boundary.md` (§5/§6), `reuse-map.md` (alf
  blast-radius map), `v2-deferred-backlog.md` (v2 deferred items — nothing silent).
- `scripts/` — `kernel.py` (phases/budgets/quorum/atomic append), `convene.py`
  (fail-closed resolver → frozen session-plan v2, external seatless arbiter,
  `run-record.json`, evidence-request path), `seat_prompt.py` (7-section trust envelope;
  overlay inject/strip, memory provider-stamp, fenced evidence DATA, `intent.md` reader),
  `memory_writeback.py` (admissibility + gated write-back), `evidence_run.py` (v2 —
  sandboxed read-only probe runner).
- `schemas/` — `session-plan.v1.schema.json` (unmutated), `session-plan.v2.schema.json`
  (v2), `run-record.v1.schema.json` (v2 §6a), `memory-record.v1.schema.json`.
- `capability-priors.yaml` — v2 owned DATA (adjudication + affinity priors; fail-open).
- `profiles/` — `coding-ratification` (rebuilt to v2), `business-ideation`, `website-ux`,
  `writing-cv` (PII-hardened), `research-synthesis` (5 families; the latter 4 rebuild to
  v2 the week each is next convened — see `v2-deferred-backlog.md`).
- `roster/` — `skeptic`, `architect`, `operator` (core+overlay split), `steward` (v2
  principal-proxy), `economist`, `user-advocate`, `wordsmith`.
- `tests/` — kernel / convene / arbiter-external / steward / evidence-run / memory-gate /
  prompt-boundaries / adversarial-suite.
