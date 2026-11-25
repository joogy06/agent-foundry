---
name: avengers
description: "Standing-team deliberation by structured contention: seats with conflicting incentives across Claude, Codex and agy cross-examine a decision, design or claim and return one outcome with attributed dissent. Triggers: 'convene the team', 'deliberate on X', 'ratify this decision', 'have the panel weigh in', 'red-team this with the standing team', 'avengers on this'. Not for execution or tournaments."
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
>   "no anti-sycophancy floor for this provider" note). **No tier is retired** (S081,
>   2026-09-14): `high` resolves like any other codex tier. The 2026-07-11 finding that
>   `high` never beat `medium` is kept as a model-scoped advisory note for
>   `gpt-5.6-sol` only, and the seat-class tiers are recorded as PROVISIONAL on any
>   other codex model.
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
DECLARED ARBITER (D23, S081 revision 4). A profile may instead DECLARE its arbiter:
`arbiter: {provider: claude, role: consultant_support}` (the Claude support tier, through the
`seat_model` row) with the top-level `arbiter_independence: separate-session`. For that profile
the provider-exclusion rule is RELAXED to: the arbiter's MODEL differs from every member seat's
model (a shared model fails CLOSED; the `-high` and `-medium` of one agy family version count as one
model), and it runs in its OWN SESSION — a fresh context that never held a member seat's turns
(its Claude label says so, and the chair spawns it that way). Context independence stands in for
provider independence; a provider that deliberated keeps `path: fallback` with the residual
flagged. The declared arbiter's obligations travel on the plan's arbiter object: it must cite
evidence for each ruling, it may abstain, and it must send unresolved material disputes to the
user. The arbiter block is a closed vocabulary: an unknown key, half a declaration (a provider /
role without `arbiter_independence`, or the reverse), a declared provider unavailable at plan
build, or a declared arbiter with no eligible model fails CLOSED — a declaration is never silently
ignored and never replaced by the selection. A profile that declares nothing resolves exactly as
above.
</HARD-RULE>

<HARD-RULE>
GUARD STACKS ARE RESOLVER-INJECTED INVARIANTS, not per-prompt discipline. Every
external seat call uses its pinned stack verbatim, and every Claude seat is spawned
with the model its label names:
- codex: `timeout <T> codex exec -s read-only -m <slug> -c model_reasoning_effort=<tier> "…" < /dev/null`
  — the MODEL `-m <slug>` comes from `skills/_meta/seat_model.py` (codex member seats →
  `consultant_main` whatever their `seat_weight`, a codex arbiter → `arbiter`), resolved
  FAIL-CLOSED: a seat that cannot be pinned is a `ConveneError`, never an unpinned call.
  No `--ephemeral` on ANY codex seat (#302): TOP and support seats alike run metered, so
  every seat's rollout records quota (and its prompt persists — no secrets in a brief). `<T>` = `codex_model.timeout_for(slug, tier)`, the ONE
  codex timeout owner. Per-call effort PINS from `{low, medium, high, xhigh, max}`
  (xhigh floor for challenger/ballot/arbiter seats; max for ratification-arbiter calls, whose
  floor-table ceiling is 1200). `high` RESOLVES — no tier is retired; for
  `gpt-5.6-sol` @ `high` the plan records the measured note "never beat medium —
  benchmark 2026-07-11, 14 scored runs" (advisory and model-scoped, never a rejection).
  Retry once on capacity.
- agy: `(d="$(mktemp -d)" && cd "$d" && timeout <T> agy --sandbox --mode plan --model <slug> [flags-before -p] -p "…" < /dev/null)`
  — `--model <slug>` via `seat_model.py` (member seats by `seat_weight`: `main` →
  `consultant_main` = TOP-argon `-high`, otherwise `consultant_support` = TOP-argon
  `-medium`; the arbiter → `arbiter` = TOP-argon `-high`; the agy family rule —
  `model_roster.AGY_FAMILY`, rev 6 argon — enforced in code);
  `<T>` from the seat_model role row (600); advisory-only preamble; NO `--add-dir` in v1. The
  stack carries `--mode plan` (no native writes) and starts in an empty temp directory, so no repo
  is in the seat's workspace: its whole brief goes inline (#366, measured on agy 1.4.12).
- claude: a host-native spawn, not a shell CLI, so the stack is a LABEL the chair reads:
  `(claude host seat · model=<alias> via seat_model <role> · effort=<e> · non-CLI spawn, timeout <T>s)`.
  The seat resolves a REAL model from `seat_model.py` by `seat_weight` (`main` →
  `consultant_main` = the Claude main tier, otherwise `consultant_support` = the Claude support tier;
  a Claude arbiter → `arbiter` = the Claude main tier, or a DECLARED arbiter's own role, e.g.
  `consultant_support` = the Claude support tier (tier values: `skills/_meta/model_roster.py`), whose
  label adds `· separate session: …`), fail-closed like the other providers; `<T>` from the role row
  (600, arbiter 1200). The chair spawns the seat with that model; the kernel does not
  dispatch the label.
`seat_weight` is an optional top-level roster-card field (`main` | `support`, default
`support`; a profile seat entry may override it; any other value fails closed). Every
seat and the arbiter carry the plan-time resolved `model`; the optional `served_model`
slot holds what the provider REPORTED serving. A `served_by` probe rides every external
call and is recorded as provider-REPORTED (not verified). Zero un-pinned codex calls.
- CODEX UNAVAILABLE → PLAN-TIME CLAUDE MAIN-TIER SUBSTITUTE (S081 amendment 1 D6, which named it "astra unavailable"). When the plan is
  built, `convene.py` makes ONE availability evaluation (a fresh `rate_limit_reached` /
  `quota_exhausted` codex rollout reading, or no `codex` binary on PATH) and checks each
  codex member seat for "no eligible TOP model for this effort". A codex seat codex cannot
  serve is re-seated as a Claude seat on `consultant_main` (the Claude main tier) WHATEVER its
  `seat_weight`, keeps its `adversarial_role`, declares `fallback_ok` (so a one-family plan
  still passes the structural floor) and records `substitute_for: codex`,
  `substitution_reason` and `requested_model` — BEFORE the structural validate. The arbiter
  is then chosen with codex EXCLUDED from both paths (nothing left → fail CLOSED). Never a
  codex std or support model: every codex model draws the same quota. A plan-wide outage re-seats every codex seat; since
  #368 every profile seats agy, so every profile's codex outage still leaves a Claude + Google round. The
  OpenAI provider gap is named on the ONE pre-spend review line, e.g.
  `codex unavailable (rate_limit_reached): skeptic, operator served by claude/<Claude main tier> — provider gap: openai; arbiter recomputed`
  (the live line names the model the tier resolves to).
  Only a persisted (non-`--dry-run`) convene records one `deliberation` substitution row per
  substituted seat in `~/.claude/projects/<slug>/astra-budget.jsonl` (reviewed 2026-09-28).
  **Quota wait (#322 fix round 1).** When the reason is QUOTA (`quota_exhausted` / `rate_limit_reached`)
  the pre-spend review adds `CODEX_QUOTA_WAIT: avengers <session> (reason …; wait_advice wait|notify;
  resets_in_s …; seats …)`. The lead acts on it BEFORE the persisted convene, by the codex-orchestration
  `CODEX_QUOTA_WAIT` steps: with `notify`, `codex_quota.py notify-claim` and on its exit 0 push the
  notification; then `codex_quota.py await-reset --cycle-id <session>` in a BACKGROUND call; exit 0 →
  re-run the `--dry-run` once (codex back on its seats); any other exit → convene as planned, with the
  Claude stand-in.
- ADMIT-GATED AT PLAN BUILD (S081 revision 4, WP-D2 — closes I11). The session id is minted before
  the substitution, and each codex seat is admit-gated once: admitted in-process at plan build by
  `codex_quota.admit("deliberation", <session id>, size=…, model_class=…)`, ONE decision per model
  class per session. Four of the five shipped profiles seat two codex seats (a `consultant_main` seat and
  a `consultant_support` seat, both std-class since the astra reserve), so they take one std-class
  `deliberation` admission per session; research-synthesis takes one. A refusal — `budget_spent`,
  `budget_store_unavailable` or an unavailable token (a ≥70% `threshold` too, until #322 retired it) — re-seats the seat through the
  SAME substitution with the decision's reason, and codex is excluded from the arbiter selection.
  The decision's `admission_id` sits on the seat, beside `substitute_for` / `substitution_reason` /
  `requested_model` (not inside `provenance`). `--dry-run` and a bare `build_session_plan` decide
  check-only and write nothing (no row, no store, no `.lock`); a persisted convene records the
  admission and any substitution row, both keyed on the session id. `--size light|medium|complex`
  sizes the codex seat (absent = complex, D17).
  HONEST LIMITS: the session's `deliberation` admissions (one per model class) cover every turn, so a
  trip-wire that trips mid-session is not seen by the frozen plan; a spent forge `consult` budget
  substitutes nothing (a different key and use); an invalid freeze pin is a broken resolver and fails
  closed, never a substitution; agy seats are unchanged; a persisted build that fails after its
  admission keeps that row, so a retry with the same session id is refused `budget_spent` (re-run with
  a fresh `--session-id`); and there is NO mid-session re-seating — a codex stack that fails after the
  plan is frozen keeps today's no-show handling (the plan froze its arbiter), a recorded gap.
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

## Composition (D15, D23)

Four of the five shipped profiles seat two codex seats (a `consultant_main` seat and a `consultant_support`
seat: two models, ONE std model class since the astra reserve) and research-synthesis seats one; every profile
seats exactly ONE `consultant_main` codex seat, always paired with a Claude main-tier seat in the same
profile. **Since the astra reserve (roster rev 4, 2026-09-27) the visionary codex seat is the codex std tier
(Sol @ `xhigh`), no longer astra:** codex TOP is kept for the escalation seat and complex code review, and no
avengers seat — member or codex arbiter — reaches it. The design-level Sol → TOP retry (U2) is not wired into
convene yet (a follow-up task): an avengers codex failure keeps the existing D6 path. In the three idea profiles codex is the VISIONARY LEAD and a Claude main-tier skeptic holds
the adversary; in coding-ratification and writing-cv codex keeps the adversarial skeptic seat. The
arbiter column is what convene resolves for each profile as shipped (provider and `seat_model` role in
brackets).

<!-- composition-table:start (test_convene.py pins these rows to the profiles on disk) -->
| Profile | codex seats | paired Claude main-tier seat | agy seat | arbiter |
|---|---|---|---|---|
| business-ideation | operator (support), architect (visionary lead) | skeptic, economist | user-advocate (main) | Claude support tier (claude consultant_support), separate session |
| research-synthesis | architect (visionary lead) | skeptic | operator (support) | Claude support tier (claude consultant_support), separate session |
| website-ux | user-advocate (support), architect (visionary lead) | skeptic | operator (main) | Claude support tier (claude consultant_support), separate session |
| coding-ratification | skeptic (adversary), operator (support) | architect | user-advocate (main) | Claude main tier (claude arbiter), selected, fallback path |
| writing-cv | user-advocate (support), skeptic (adversary) | wordsmith | architect (main) | Claude support tier (claude consultant_support), separate session |
<!-- composition-table:end -->

- **agy is a deliberation seat in every profile again (#368, 2026-10-24).** Amendment 3 (D25) had removed
  agy from every profile but `research-synthesis`, on the previous agy family's evidence; on Gemini 4 Argon (#365, #367:
  deliberation equal to Opus, slower) #368 ADDED one agy seat to each of the other four, keeping every
  existing seat: business-ideation `user-advocate` (the customer's voice), website-ux `operator`
  (build-and-run feasibility), writing-cv `architect` (structure and narrative coherence),
  coding-ratification `user-advocate` (whoever uses or maintains the result). These seats are
  `seat_weight: main` (`consultant_main` → `-high` unsized; a sized convene serves
  `model_roster.AGY_LEVEL_BY_SIZE`: light `-low`, medium `-medium`, complex `-high`), Pattern 1 only
  (`--sandbox --mode plan` from an empty cwd, inline brief, `< /dev/null`). research-synthesis keeps its support-weight operator.
  agy never arbitrates a healthy session (D23, below), and astra and the benched Claude family are not
  seated.
- **Codex took the seats agy vacated at amendment 3, and keeps them.** A profile may hold TWO codex seats of different MODELS: a `main` card on seat_model
  `consultant_main` (the codex std tier, Sol — the visionary lead) and a `support` card on
  `consultant_support` (the codex support tier literal). Both are the std class since the astra reserve,
  so a session takes one std-class `deliberation` admission per session (`codex_quota.BUDGET_LIMITS
  {"top": 1, "std": 1}`, once per model class per session) whose row lists every seat model and role it covers (`models` /
  `roles`, #302); a refused codex seat falls back to a fresh **Claude main-tier** seat (D18), not to the
  support tier. A home-tier codex freeze no longer reaches any avengers seat (F8). **Exception, stated so the
  class claim stays honest:** the class follows the resolving row AND the roster — when the vendor ranks the
  std model TOP (a reordered roster, or a stale roster whose recorded TOP is the std model) the Sol literal IS
  the roster TOP and is billed `top`, so that session's admission is a TOP one (seat_model.pin_model_class).
- **agy never arbitrates a healthy session** (`convene.ARBITER_INELIGIBLE_PROVIDERS`, scoped by D29).
  Removing agy's seats is exactly what would have qualified it for the CLEAN arbiter path, so the bar
  is explicit rather than incidental. It applies only while no provider is excluded: a session that has
  already lost a provider (codex unavailable, a codex seat substituted or refused, or codex excluded for
  lack of an eligible arbiter model) keeps agy as the last-resort arbiter instead of failing closed —
  `coding-ratification` on a codex refusal resolves agy `gemini-4-argon-high` on the fallback path
  (agy holds a seat there since #368; it was the clean path while D25 left agy seatless). A
  declared arbiter is not selection and does not consult the bar (no shipped profile declares agy).
  **Since #368 every profile is a three-provider deliberation (Claude + codex + agy) and every
  healthy-session arbiter is Claude** — the declared Claude support tier in a separate session, or a recorded fallback
  residual for `coding-ratification`. A session whose codex arm is refused no longer has a Claude-only
  deliberation: every profile's codex outage still leaves a Claude + Google round, and its dissent
  record must name the OpenAI gap. (Under D25 the four agy-free profiles fell to Claude-only; that was
  the price #368 removed.)
- **business-ideation declares its arbiter** since amendment 3. It could not before: its economist seat
  resolved the Claude support tier (then `opus`), the model a declared `consultant_support` arbiter
  resolves, and the relaxed rule refuses an arbiter that shares a seat's model. D26 moved the economist
  to the Claude main tier (`seat_weight: main`),
  so the rule keeps its full teeth instead of being narrowed to fit the profile.
- **TRIP-WIRE (§4.9), all three idea profiles:** if the user overturns the arbiter's decision in 2 of a
  profile's first 3 flipped sessions, revert that profile. NO AUTOMATED COUNTER EXISTS: neither convene
  nor the run record tracks an overturned decision, so a person counts these sessions by hand.
- **Convergence in the idea profiles (CONV-1):** where an idea profile's outcome is ONE chosen direction
  (`business-ideation` and `website-ux` on a `decision` outcome), the arbiter chooses it under CONV-1
  (`~/.claude/skills/_meta/convergence-rule.md`); the rule is defined there and is not restated here. The
  decision record names the winning direction and each borrowed part with the seat it came from.
  `research-synthesis` falls under that rule's exclusions, as does any session that fails its applicability
  test. The mandatory dissent record is unchanged either way.

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
- `references/dialogue-protocol.md` (§4 phase machine), `references/convene-contract.md`
  (§8 input contract + external arbiter + run-record), `references/outcome-routing.md` (§8
  output router + `avengers_brief` schema), `references/intent-artifact.md` (v2 §5 steward
  `intent.md` contract), `references/memory-policy.md` + `references/trust-boundary.md`
  (§5/§6), `references/reuse-map.md` (alf blast-radius map),
  `references/v2-deferred-backlog.md` (v2 deferred items — nothing silent).
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
