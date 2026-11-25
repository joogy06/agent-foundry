# avengers — Convene Contract (reference)

The input contract that `scripts/convene.py` validates before a single seat call is
spent. This is the authoritative prose for design §8. Convene is the **fail-closed
pre-spend gate**: if the resolved composition is structurally unsound, there is
**no run and no spend** — the error is explicit, never silently converted to a
degraded run.

Convene reads only two config layers — **shipped defaults ← profile** — plus the
caller's request below. It reads **no repo-local override file** (a drive-by
injection vector, design §3/§14).

## Contents

- Input contract (design §8)
- Caller routing (design §8)
- Fail-closed structural validation (design §4 LOW_QUORUM case (a))
- External arbiter (design §4, WP-2 — the highest-value fix)
- Effort-tier policy (design §2/§4; S080 §4.4; S081 2026-09-14)
- Guard-stack injection (resolver-owned invariants, design §2; S081 §4.2, §4.8, §4.9)
- Codex unavailable → plan-time Claude main-tier substitution (S081 amendment 1 D6, item 4)
- Output: the frozen session-plan (v2)
- Output: the run-record (§6a instrumentation sink)
- `--dry-run` (pre-spend review)
- CLI

## Input contract (design §8)

A convene contract is a JSON or YAML mapping. Fields:

| Field | Type | Notes |
|---|---|---|
| `task` | string | The decision/deliverable question. (`decision` accepted as an alias.) |
| `profile` \| `task_family` | string | One is REQUIRED. `profile` selects `profiles/<name>.yaml`; `task_family` is a synonym for the family name. |
| `roster_override` | list | Optional. Replaces the profile's `seats` list with `{ref, provider?, effort?, adversarial_role?}` entries. Same validation applies. |
| `context[]` | list | Optional. Each item `{kind, trust=untrusted (default), sensitivity, egress}`. Untrusted context flows into `[UNTRUSTED_REFERENCE_MATERIALS]` (never trusted-by-default). |
| `outcome` | enum | `decision \| deliverable \| forge_brief \| auto`. `auto`/absent ⇒ the profile's `outcome.default`. Must be offered by the profile's `outcome.type`. |
| `depth` | enum | `default \| full \| quick`. |
| `budget` | object | `{max_seat_calls, wall_clock_s, max_cycles}` — the caller REQUEST (applied on top of the two-layer config merge, provenance recorded; NOT a config layer). |
| `caller` | enum | `user \| pa \| forge \| founder \| alf`. |
| `came_from` | object | `{caller_session_id, forge_session_id?}`. `forge_session_id` present ⇒ recursion guard (non-build; design §8). |
| `memory` | enum | `project \| off`. v1 tier = project only. |
| `interactive` | bool | Whether the caller owns live user I/O. |

`max_cycles` is the **canonical cross-exam cycle-budget name everywhere** (contract,
session-plan, and kernel). The stalemate detector's "2 unchanged exchanges" counter
is INTERNAL to the kernel and DISTINCT from `max_cycles`.

## Caller routing (design §8)

| Caller | interactive | outcome | user I/O owner | build path |
|---|---|---|---|---|
| user | yes | auto | avengers | yes → forge intake (explicit user gate, always) |
| pa | no | decision | pa | no |
| forge (design-exploration) | no | decision (forced) | forge | **blocked** (recursion guard: `forge_session_id` present ⇒ non-build; depth-capped) |
| founder | no | decision | founder | no (founder→forge owns build) |
| alf | no | decision | alf | no |

Build-flavored outcomes exit as an `avengers_brief` into **forge's** gate machinery.
avengers NEVER spawns bob, signs a contract map, or marks anything bob-ready
(`contract_map_signed` / `bob_ready` are mechanically always-false). The full router
and `avengers_brief` schema land in WP-5 (`references/outcome-routing.md`); WP-4
wires the forge Step-3 intake.

## Fail-closed structural validation (design §4 LOW_QUORUM case (a))

`convene.py` refuses to run (exit code 2, no spend) when ANY of these hold on the
resolved roster:

1. **Sub-quorum**: fewer than **3 member seats**.
2. **Provider-family floor**: fewer than **2 provider families** AND no seat
   declares `provider.fallback_ok: true`. (A declared fallback relaxes this; the
   relaxation is recorded as `quorum.fallback_relaxed`. A codex seat re-seated on Claude
   because codex was unavailable declares the fallback itself — see *Codex unavailable*.)
3. **No adversary**: zero `adversarial_role: true` seats. Every profile MUST
   resolve ≥1 adversarial seat (design §6).

The **arbiter** is resolved separately (see *External arbiter*, below) and has its
own single fail-closed case (all-adversarial). Runtime collapse (LOW_QUORUM case
(b)) is the **kernel's** concern (`kernel.classify_runtime_quorum`), not convene's.

## External arbiter (design §4, WP-2 — the highest-value fix)

The arbiter is a **fresh, persona-free, deliberation-EXTERNAL cold-context CALL** —
it did NOT file a position, argue, or ballot; it is NOT a promoted seat. Unless the
profile DECLARES its arbiter (*A declared arbiter is not selection*, below), its provider
is **selected, never inherited from a seat**: a SELECTED arbiter's provider MUST differ
from **every deliberation seat's provider** (widened from adversarial-only) whenever an
ELIGIBLE provider does — the CLEAN path — and only when none does is it a non-adversarial
provider that deliberated — the FALLBACK path, its residual recorded. ELIGIBLE means
neither excluded (*UNAVAILABLE PROVIDERS* and *NO ELIGIBLE ARBITER MODEL*, below) nor
barred (*The agy bar*, below):

- **CLEAN path** — an eligible provider used by **no** deliberation seat is chosen: genuinely
  external, authorship linkage total-excluded, **no residual**.
- **FALLBACK path** — no eligible provider is free of deliberation: the
  strongest-adjudication-prior **non-adversarial** provider is invoked cold-context.
  Authorship is anonymized, but style-recognition self-preference is an **ACCEPTED,
  DOCUMENTED residual** (arXiv 2410.21819), flagged `fallback_arbiter_residual: true` in
  `run-record.json` (§6a). We do not pretend the fallback is residual-free.
  In a healthy session coding-ratification lands here: its seats hold all three provider
  families (codex, claude, and agy again since #368), and agy is barred, so the arbiter is
  the non-adversarial claude (`arbiter`, the Claude main tier) with the residual flagged. That
  is a property of a healthy session, not of the profile: under any codex refusal its
  arbiter is agy on the fallback path (*The bar is scoped by D29*, below).
- **ALL-ADVERSARIAL** — every eligible provider deliberated **and** every one is adversarial:
  no non-adversarial arbiter exists → **fail CLOSED** (`ConveneError`). This is the
  **only** unsatisfiable arbiter case; it never hangs.
- **UNAVAILABLE PROVIDERS** (S081 amendment 1 D6) — `resolve_arbiter(...,
  unavailable_providers=...)` excludes a provider that cannot serve a call at plan build
  (today only codex, when codex is unavailable) from **both** paths, and the `constraint`
  text names it. If nothing remains — e.g. the only non-adversarial provider was codex —
  the arbiter fails **CLOSED**, the same way.
- **NO ELIGIBLE ARBITER MODEL** (#282 R8) — when the chosen provider is codex and its
  roster cannot serve the arbiter at its effort (since the astra reserve the codex arbiter is the
  codex std literal, so: the roster does not list it, or lists it without that effort;
  `NoEligibleCodexModelError`:
  e.g. a profile with no codex member seat, so nothing at plan build evaluated the roster,
  or an arbiter `max` the members' effort did not need), codex is excluded and the selection
  is **recomputed once** — clean path, then fallback — and the `constraint` text names the
  exclusion (`codex excluded after the arbiter pin found no eligible codex model for effort
  'max' (no_eligible_model); arbiter selection recomputed once`). Nothing left → **fail
  CLOSED** as above. No budget row is written (no seat was substituted). A broken resolver
  (an invalid freeze pin, unreadable pins) or an invalid codex roster is a plain
  `ConveneError` and is **never** recomputed.

**The agy bar (S081 revision 4, amendment 3 D25 + D23).** `convene.ARBITER_INELIGIBLE_PROVIDERS`
(agy), applied in `_select_arbiter_provider`, bars agy from SELECTION in a HEALTHY session —
one in which nothing is excluded — so **agy never arbitrates a healthy session**. D25 removed
agy's seats from every profile but `research-synthesis`, and a provider no seat uses is what
qualifies for the CLEAN path, so without the bar that removal would have made agy the arbiter
of the one shipped profile that selects: with the bar lifted, `coding-ratification`'s healthy
arbiter measured as agy on the clean path. #368 seated agy again in all five profiles, so agy is
no longer a clean-path candidate there; the bar now keeps agy, a non-adversarial seat, from
being chosen on the fallback path, and the healthy arbiter stays Claude.

**The bar is scoped by D29 (user-approved 2026-09-19).** It applies only while nothing is
excluded. A session that has already lost a provider — codex unavailable at plan build, a
codex seat substituted (an admission refusal included), or codex excluded after the arbiter
pin found no eligible model — keeps agy as the **last-resort arbiter** rather than failing
closed. Measured 2026-09-23 in a fixture HOME seeded with the live roster, and re-measured at
#368: `coding-ratification`'s arbiter is agy (today `gemini-4-argon-high`), path clean before
#368 and path fallback since (agy holds the user-advocate seat), under
`rate_limit_reached`, `quota_exhausted`, `cli_missing`, a `threshold` or `budget_spent`
admission refusal, and a roster listing no eligible model for its codex skeptic. (Its healthy
arbiter is Claude, which never reaches the arbiter-pin exclusion.)

**A declared arbiter is not selection (D23).** A profile that declares `arbiter: {provider,
role}` with the top-level `arbiter_independence: separate-session` is pinned on its declared
seat_model role: neither the selection rule above nor the agy bar is consulted. It is held to
the RELAXED rule instead — its MODEL differs from every member seat's model (a shared model
fails CLOSED) and it runs in its own session — and it is never recomputed or silently
replaced: a declared provider unavailable at plan build, or a declared codex arbiter with no
eligible model, fails CLOSED. Its `path` still records whether its provider deliberated (clean,
or fallback with the residual flagged). Four shipped profiles declare (`business-ideation`,
`research-synthesis`, `website-ux`, `writing-cv`: the Claude support tier through the `consultant_support` row);
`coding-ratification` selects; no shipped profile declares agy.

`can_arbitrate` is **inert** under v2 — no seat is ever the adjudicator, so no seat
both ballots and adjudicates (the participant-judge violation is gone). The
adjudication prior comes from the editable `capability-priors.yaml` DATA (designer
belief, not measured capability); the resolver fails **open** to built-in defaults
if that file is missing.

The arbiter object in the session-plan **drops `seat`**, **adds**
`{is_external: true, cold_context: true, path: clean|fallback}`, and **keeps** the
runtime-load-bearing `{provider, effort, guard_stack}` (`constraint` is optional).

### Arbiter output contract (versioned system contract)

The external arbiter emits a fixed-shape synthesis over **all** positions (a
position is never dropped from the synthesis set): a **decision**, the **rejected
alternatives**, **≥2 actionable trip-wires**, a **mandatory attributed dissent
record**, and the **convergence margin** (unanimous / converged N-M / arbiter broke
tie).

## Effort-tier policy (design §2/§4; S080 §4.4; S081 2026-09-14)

- **No tier is retired.** `high` resolves like any other tier. `convene.py` keeps the
  retired-tier check (`RETIRED_EFFORT_TIERS`, now empty) so a future policy retirement
  has one place to land, and the pre-spend review prints
  `retired effort tiers rejected: none`.
- **Measured findings are model-scoped notes, never rejections.**
  `MEASURED_EFFORT_FINDINGS` keys a note on `(model, tier)`. A seat that resolves
  `gpt-5.6-sol` @ `high` records "never beat medium — benchmark 2026-07-11, 14 scored
  runs" and still runs at `high`. LEGALITY (does this model support this tier?) belongs
  to `skills/_meta/codex_model.py` / `seat_model.py`, read from the codex roster; the note
  only says whether a legal pair measured well. The seat-class rows
  (`challenger_floor`, `ratification_arbiter`) were measured on `gpt-5.6-sol`, so a
  codex seat resolving any other model records a PROVISIONAL note instead of silently
  inheriting that benchmark.
- **codex** seats must pin an explicit tier ∈ `{low, medium, high, xhigh, max}`
  — `default` (un-pinned) is rejected (success criterion #4: zero un-pinned codex
  calls), and so is `minimal` (no listed codex model supports it). Challenger/ballot
  seats floor at `xhigh`; a **ratification** arbiter that resolves to codex pins `max`
  (timeout 1200) via the `ratification_arbiter` seat-class (moot for
  coding-ratification, whose arbiter is claude/agy — codex is the excluded adversary;
  the `max`-vs-2026-07-11-sol re-derivation is deferred).
- **claude / agy** seats carry no effort pin (`default`). Their MODEL is not an effort
  setting: it is resolved by `seat_weight` (see *Guard-stack injection*).
- Effort pins are **seat-class semantics** (design §2a): a semantic name
  (`challenger_floor`, `ratification_arbiter`) or a raw tier resolves per
  `(provider, seat-class)`. A raw tier with no native equivalent on the resolved
  provider resolves **down** to that provider's advisory tier **with a recorded
  note** (e.g. "no codex-equivalent anti-sycophancy floor for this provider") — the
  note flows to `run-record.json`, so a challenger provider-swap no longer crashes
  the resolver (success criterion #2).

## Guard-stack injection (resolver-owned invariants, design §2; S081 §4.2, §4.8, §4.9)

Convene injects the exact external-CLI stacks — this is not per-prompt discipline.
Every seat's MODEL, Claude included, comes from `skills/_meta/seat_model.py` by role.
It is resolved at plan build, frozen into the plan, and FAIL-CLOSED: a seat that cannot
be pinned is a `ConveneError` (exit 2, no spend), never an unpinned call.

| Seat | seat_model role |
|---|---|
| codex member seat | `consultant_main`, whatever its `seat_weight` |
| a codex member seat re-seated on claude (codex unavailable) | `consultant_main` (the Claude main tier), whatever its `seat_weight` |
| agy or claude member seat with `seat_weight: main` | `consultant_main` |
| agy or claude member seat otherwise | `consultant_support` |
| the external arbiter, any provider | `arbiter` |

`seat_weight` is an optional top-level roster-card field, `main` | `support` (default
`support`). A profile seat entry may override it, and any other value fails closed.
The skeptic and architect cards set `main`.

- **codex**: `timeout <T> codex exec -s read-only -m <slug> -c model_reasoning_effort=<tier> "…" < /dev/null`.
  `<T>` = `codex_model.timeout_for(slug, tier)`, the one codex timeout owner (a
  ratification-arbiter `max` → 1200). No `--ephemeral` on any codex seat (#302): TOP and
  support seats alike run metered.
- **agy**: `(d="$(mktemp -d)" && cd "$d" && timeout <T> agy --sandbox --mode plan --model <slug> -p "…" < /dev/null)` — every flag
  BEFORE `-p`, advisory-only, no `--add-dir` in v1, an empty cwd so no repo is in the workspace (#366). `consultant_main` and `arbiter`
  resolve TOP-argon `-high`, `consultant_support` TOP-argon `-medium` (the agy family rule,
  `model_roster.AGY_FAMILY`, is enforced in code). `<T>` from the role row (600).
- **claude**: a host-native spawn, not a shell command. The stack is a label that names a
  REAL model: `(claude host seat · model=<alias> via seat_model <role> · effort=<e> · non-CLI spawn, timeout <T>s)`.
  `consultant_main` and `arbiter` resolve the Claude main tier, `consultant_support` the Claude support
  tier (values in `skills/_meta/model_roster.py`; the current ones are in codex-orchestration "Seat Models");
  `<T>` from the role row (600, arbiter 1200). The chair spawns the seat with that model;
  the kernel does not dispatch the label.

The `"…"` slot is filled at call time with the assembled `seat_prompt.py` envelope.

## Codex unavailable → plan-time Claude main-tier substitution (S081 amendment 1 D6, item 4)

A codex member seat codex cannot serve is re-seated on Claude **at plan build**, before any
spend, instead of being skipped or falling back to a codex std or support model (every codex model draws the same quota).

**When.** `build_session_plan` makes **one** availability evaluation per build —
`shutil.which("codex")` (an in-process PATH lookup, never the stale inventory) and
`codex_quota.unavailable()` (a **fresh** rollout reading carrying `rate_limit_reached_type`,
or fresh primary / weekly usage ≥ 99%; a stale, uncertain or unknown reading is never
unavailability).
Each codex seat is then resolved in `seat_model.py argv --use` order:

| Codex seat's situation | Result | `substitution_reason` | `requested_model` |
|---|---|---|---|
| roster cannot serve the seat's model at its effort (the std literal unlisted or without the effort; a TOP row with no eligible TOP) | substituted (this seat only) | `no_eligible_model` | `null` |
| **no** roster file (`~/.codex/models_cache.json` absent) | unchanged codex seat on its harness literal (the std / support slug itself since the astra reserve; sanctioned — the seat_model pin's provenance records `harness_literal`) | — | — |
| roster file **invalid** (unreadable, not JSON, wrong shape or field types; #282 R4) | **`ConveneError` naming `roster_invalid`, fail-closed — never a substitution** (the arbiter too) | — | — |
| roster file **invalid** AND the seat is **frozen** (`~/.claude/state/seat-model-pins.json` holds a codex `top`) | a freeze reaches only codex TOP rows, and no avengers codex seat is one since the astra reserve (F8): **`ConveneError` naming `roster_invalid`**, as for any invalid roster. (On a TOP row the freeze is still honoured UNVALIDATED and records `roster_invalid: true`.) | — | — |
| any other resolution failure (invalid / unlisted freeze pin, unreadable pins) | **`ConveneError`, fail-closed — never a substitution** | — | — |
| pin resolves, no `codex` binary on PATH | substituted | `cli_missing` | the codex model |
| pin resolves, fresh unavailability token | substituted | `rate_limit_reached` / `quota_exhausted` | the codex model |
| pin resolves, no signal, and the session's plan-time admission **admits** (S081 revision 4, WP-D2) | unchanged codex seat, carrying the decision's `admission_id` | — | — |
| pin resolves, no signal, and the session's plan-time admission **refuses** (S081 revision 4, WP-D2) | substituted, through the same re-seating as the rows above | the decision's own reason: `threshold` / `budget_spent` / `budget_store_unavailable` / an unavailability token | the codex model |

**The freeze row, spelled out (#282 fix round 1 F15; behaviour UNCHANGED since #282 R4 / plan
K14 — this documents it, it does not alter it).** A codex freeze is honoured **unvalidated**
when the roster is invalid. `seat_model` cannot check the frozen slug's eligibility against a
document it could not read, and it deliberately does **not** refuse on that account: the freeze
is the operator's **emergency override**, and it is exactly what restored `gpt-6-astra` during
the 2026-09-15 vendor priority tie. A freeze that stopped working the moment the roster broke
would be useless at the one moment it is needed. The exception is the **freeze and nothing
else** — every other codex path (TOP without a freeze, a pinned literal, the arbiter) still
raises `ConveneError` naming `roster_invalid`, so an unreadable roster cannot silently seat a
model nobody chose. Because the document never loaded, the plan's `roster_fetched_at` is
`null`; the plan therefore also records **`roster_invalid: true`** in that seat's `provenance`,
which is what distinguishes a freeze honoured against a **broken** roster from one honoured
against an **absent** one. Both are null-stamped; only one had a file that failed to parse.

**What the seat becomes.** Provider `claude`, seat_model role `consultant_main` (the Claude main tier,
600s) **whatever its `seat_weight`** — it stands in for a TOP seat, so a `support` weight does
not demote it to the Claude support tier. It keeps `seat_id`, `seat_weight`, `adversarial_role`,
`can_arbitrate` and `overlay_type`; sets `fallback_ok: true` (the declared fallback that lets a
plan left with one provider family pass the structural floor, recorded as
`quorum.fallback_relaxed`); re-resolves its effort for Claude through `resolve_effort` (an
adversarial `challenger_floor` seat keeps the "no codex-equivalent anti-sycophancy floor" note);
and records `substitute_for: "codex"`, `substitution_reason` and `requested_model`. A
substitute model that starts with `gpt-` fails closed.

**Then.** The structural validate runs on the substituted seats, and the arbiter is chosen with
codex in `unavailable_providers` (whenever a plan-wide signal exists or any seat was
substituted). The pre-spend review gains exactly one line, for example:

```
codex unavailable (rate_limit_reached): skeptic, operator served by claude/<Claude main tier> — provider gap: openai; arbiter recomputed
```

(The live line names the model the Claude main tier resolves to.)

In this coding-ratification example both codex seats are served by the Claude main tier and the agy user-advocate (#368) keeps its seat, so the deliberation is Claude + Google with the OpenAI provider gap named; since #368 every profile's codex outage still leaves a Claude + Google round. The run
record's staffing seats carry the same three fields. A plan with no signal whose admission
admits is byte-identical to a plan built before this change, apart from the codex seat's
`admission_id` (see *The plan-time admission* below).

**The plan-time admission (S081 revision 4, WP-D2; closes I11).** Convene is admit-gated once
per session and model class. `build_session_plan` mints the session id first (the same
`make_session_id` expression, moved ahead of the substitution, so the id's value and derivation
are unchanged). Then, after each codex seat's pin and the plan-wide checks above, it calls
`codex_quota.admit("deliberation", <session id>, size=…, model_class=…)` in-process at plan
build. It never uses the `codex_quota.py admit` CLI, which is check-only by design and cannot
record. There is one decision per model class across the codex seats still standing. Four of
the five shipped profiles seat two codex seats (a `consultant_main` seat, the codex std tier since
the astra reserve, and a `consultant_support` seat, the codex support tier literal): two models in ONE
std class, so they take one std-class `deliberation` admission per session whose row lists every seat model and
role it covers (`models` / `roles`, #302); research-synthesis seats one and takes one. No shipped seat
serves the TOP class any more — EXCEPT when the vendor ranks the std model TOP (a reordered roster, or a
stale roster whose recorded TOP is the std model): the Sol literal is then the roster TOP and is billed
`top` (seat_model.pin_model_class), so that session takes a TOP admission. Each class's
`deliberation` slot covers all of the session's turns, and no turn's guard stack carries an
admission step.

The size is the caller's `--size light|medium|complex`. Absent, it is D17's `complex`, recorded
as `size_source: default`, and `.forge/size` is not read, because sizing is opt-in. A given size
resolves through `seat_model`'s L7 rule under `--project-root`: inside a forge cycle forge's
own size wins and a conflict takes the larger, and `light` / `medium` serve the codex seat
on the codex std tier. A forge-convened session passes forge's own size (forge `references/02-design-team.md`, Step 6B).

An **admitted** seat stays codex. A **refused** seat is re-seated through the same substitution
as the table above, carrying the decision's reason (`threshold`, `budget_spent`,
`budget_store_unavailable`, or an unavailability token). Codex then joins the arbiter's excluded
providers, so the arbiter is recomputed exactly as for any other substitution. There is no new
substitution path, and a refusal reason outside `codex_quota.SUBSTITUTION_REASONS` fails closed.
The decision's `admission_id` sits **on the seat**, beside `substitute_for`,
`substitution_reason` and `requested_model`, and the run record's staffing seat copies it. It
is not inside the closed `provenance` object, which holds seat_model pin keys only. It is a
32-hex id when the build recorded, and `null` for a check-only decision.

**Budget rows.** `--dry-run`, and `build_session_plan` with its default
`record_admission=False`, decide the admission check-only and write nothing: no row, no store,
no `.lock`, and the seat's `admission_id` is `null`. Only a persisted convene (`main()` without
`--dry-run`) records, into `~/.claude/projects/<slug>/astra-budget.jsonl` for `--project-root`.
It records the session's admission decision first, at plan build, whether it admitted or
refused. Then, after the plan and run record are written, it records one `deliberation`
substitution row per substituted seat through `seat_model.substitute(...)`. Both are keyed on
the avengers **session id**, the key the seat's own admission uses, so a substitution row
shares its (key, use) with the admission that preceded it and the seat's `admission_id` names
that admission. Neither is keyed on the forge cycle. A substitution row names no admission of
its own (a refusal replaces none) and never spends a budget. A store the admission cannot write
is itself the refusal `budget_store_unavailable`, so the seat is substituted. A substitution
row that cannot be written is reported on stderr and never blocks the session (under-count,
never invent).

**Honest limits.**
- **Admitted at plan build, not per turn.** A spent session slot or an unwritable store (and,
  until #322 retired it on 2026-09-27, a ≥70% threshold) substitutes an avengers codex seat before any spend. A spent forge `consult`
  budget still substitutes nothing, because it is a different key and a different use. The
  meter is read once, when the plan is built.
- **No mid-session re-seating.** A codex stack that fails after the plan is frozen keeps
  today's no-show handling: the plan froze arbiter ≠ adversarial provider, and re-seating a
  live session could break that. That failure is a recorded gap, not a substitution.
- **The arbiter is never substituted.** A codex arbiter is only avoided through the exclusion
  above, or — when codex has no eligible model for the arbiter's effort in a plan with no
  signal and no substituted seat — by excluding codex and recomputing the selection once
  (*External arbiter*, #282 R8). It is never re-seated on Claude.
- **agy seats are unchanged** by any codex signal.
- **One admission per model class per session.** A custom profile that seats N codex seats of
  one model class takes ONE slot for all N, not N slots. The shipped profiles seat at most one
  codex seat per role (`consultant_main`, `consultant_support`); what keeps a second main codex seat
  out of them is a test over the profiles on disk
  (`test_d3_the_skill_composition_table_matches_the_profiles_on_disk`), not the budget.
- **A build that fails after its admission keeps the row, and a retry with the same session id
  loses its codex seats.** A persisted build records its admission at plan build, before its
  later fail-closed checks (the structural validate, the arbiter, the remaining member seats'
  pins and the plan schema) and before `main()` writes the session. A build that fails after
  that point keeps its admission row, keyed to its session id; an admitted row spends that
  class's slot although no codex call was made. A retry with the same session id — an explicit
  `--session-id`, or the same task re-run within the same minute, since a generated id is
  minute-resolution (`YYYYMMDD-HHMM-<task slug>`) — is refused `budget_spent`, and each codex
  seat of an already-admitted class is re-seated on the Claude main tier, the `consultant_main` (codex std tier) seat included. Re-run with
  a fresh `--session-id`. Recording the admission only after the build's last fail-closed check
  is filed for revision 5.
- **`admission_id` is not declared in the schemas yet.** Seat items are open in
  `session-plan.v2` and `run-record.v1`, so plans and records that carry it validate. Declaring
  it is deferred to revision 5.

## Output: the frozen session-plan (v2)

Convene materializes a **flat JSON** `session-plan.json` that validates against
[`schemas/session-plan.v2.schema.json`](../schemas/session-plan.v2.schema.json),
carrying `profile_sha256` + `capability_priors_sha256` provenance, the resolved
seats (each with its resolved `seat_class` + optional `effort_note`, the plan-time
resolved `model`, and an optional `served_model`), the **external seatless arbiter**
object (`{is_external, cold_context, path, provider, effort, guard_stack}` plus `model`
and an optional `served_model`), the merged budgets, the quorum summary, `phases_planned`, and the
`merge_provenance` (layers = `[shipped_defaults, profile]`; `repo_local_overrides:
none`). Written atomically (temp+rename) to
`<project>/.avengers/sessions/<session-id>/session-plan.json`.

**v2, not a v1 mutation.** `session-plan.v1.schema.json` stays on disk unchanged so
a resumed mid-flight v1 plan can't silently misvalidate. v2 drops `can_arbitrate`
from the seats' `required` set (inert) and redefines the `arbiter` object (drops
`seat`; adds `{is_external, cold_context, path}`).

**Additive S081 edit, no version bump (2026-09-14).** `session-plan.v2` and
`run-record.v1` gained OPTIONAL `model` and `served_model` (string or null) on seats and
on the arbiter, and their effort enums dropped `minimal` and added `high`. `model` is
what convene REQUESTED; `served_model` is what the provider REPORTED serving (null or
absent until observed, never copied from `model`). Optional means a plan or record
written before the edit carries no new required key, so it still validates; only one
that pinned `minimal` would fail the enum. A `required` field would have forced a v3
schema and broken resume of in-flight v2 plans.

**Additive S081 amendment 1 edit, no version bump (2026-09-15).** Seat items in
`session-plan.v2` and staffing seats in `run-record.v1` gained OPTIONAL `substitute_for`
(`"codex"`), `substitution_reason` (string) and `requested_model` (string or null), present
only on a seat re-seated on Claude because codex was unavailable at plan build. Plans and
records without them still validate.

**Additive #282 r14 edit, no version bump (2026-09-15).** Every materialised member seat and
the external arbiter carry an OPTIONAL `provenance` object in `session-plan.v2`, and the
run record copies it onto its staffing seats and arbiter: the seat_model pin provenance of the
model convene resolved, persisted as exactly `{requested_selector, resolved_model, source,
roster_fetched_at}` plus `frozen_slug` — the `~/.claude/state/seat-model-pins.json` `top` as
written — only when `source` is `freeze`. `source` is one of `freeze | env | roster |
harness_literal`; `roster_fetched_at` is null when no roster was read (a Claude seat, a
harness literal). A substituted seat carries its Claude pin's provenance beside
`substitute_for`; the arbiter carries the provenance of the pin that serves it after any
recompute. The object is closed (`additionalProperties: false` inside it): the pin's live
meter and event keys (`quota_state`, `fallback_reason`, `roster_stale`,
`roster_entries_skipped`) are not persisted, so a frozen plan records what was resolved, not a
meter reading. A freeze pin whose provenance lacks its slug fails the schema validate
(fail-closed, no run). Plans and records written before the edit carry no `provenance` and
still validate.

**Additive #282 fix round 1 F15 edit, no version bump (2026-09-16).** The `provenance` object
gains ONE more optional key, the boolean **`roster_invalid`**, in both schemas — present as
`true` only when the pin was resolved against a roster that could not be read, absent
otherwise. It is the single exception to the "no event keys" rule above, and it earns it: in a
fail-closed convene the only pin that can carry it is a **codex freeze** (see the freeze row
above), so the key marks precisely the case where a model was seated without the roster check —
information a frozen plan must keep, because `roster_fetched_at: null` alone cannot tell a
broken roster from an absent one. Plans and records written before this edit carry no
`roster_invalid` and still validate.

## Output: the run-record (§6a instrumentation sink)

Alongside the session-plan, every materialized run writes a **NAMED**
`run-record.json` validating against
[`schemas/run-record.v1.schema.json`](../schemas/run-record.v1.schema.json): the
resolved staffing (provider + effort **with the seat-class name** per seat, plus the
requested `model` and an optional provider-reported `served_model`, and the plan's
`provenance` when it carries one — #282 r14), the
arbiter path + `fallback_arbiter_residual` flag (and the arbiter's `provenance`), the collected §2a `advisory_notes`,
and the **post-run** `outcome` slots (`dissent_margin`, a crude arbiter-scored 1-5
`outcome_grade`, `graded`) — written `null` / `graded: false` at materialization
time and filled by the kernel/arbiter after deliberation. This is the
anti-superstition insurance: v3's measured routing starts from data, and rotation
(deferred) becomes meaningful only once this record exists. Non-optional.

## `--dry-run` (pre-spend review)

`convene.py --dry-run` resolves + validates + prints a pre-spend review (seats,
providers, efforts, guard stacks, quorum, budgets, arbiter, an estimator band from
the §9 cold-start seeds, and the retired-tier line, which reads `none` today) and **stops — no session dir,
no spend**. When a codex seat was substituted it also prints the one `codex unavailable (…)`
line (see *Codex unavailable*); `--dry-run` never writes a budget row. A structural failure
still exits non-zero even under `--dry-run`.

## CLI

```
# fail-closed review, no spend:
python3 scripts/convene.py --profile coding-ratification --task "…" --dry-run

# materialize + freeze the session-plan under <project>/.avengers/sessions/<id>/:
python3 scripts/convene.py --contract convene.json --project-root .

# inline convenience contract (no file):
python3 scripts/convene.py --profile coding-ratification --task "…" --outcome decision
```
