# avengers — Convene Contract (reference)

The input contract that `scripts/convene.py` validates before a single seat call is
spent. This is the authoritative prose for design §8. Convene is the **fail-closed
pre-spend gate**: if the resolved composition is structurally unsound, there is
**no run and no spend** — the error is explicit, never silently converted to a
degraded run.

Convene reads only two config layers — **shipped defaults ← profile** — plus the
caller's request below. It reads **no repo-local override file** (a drive-by
injection vector, design §3/§14).

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
   relaxation is recorded as `quorum.fallback_relaxed`.)
3. **Arbiter constraint**: no `can_arbitrate` seat has a provider **different from
   every `adversarial_role: true` seat's provider**. (Same error class as the
   family floor — an explicit message, never a silent degrade.)
4. **No adversary**: zero `adversarial_role: true` seats. Every profile MUST
   resolve ≥1 adversarial seat (design §6).

Runtime collapse (LOW_QUORUM case (b)) is the **kernel's** concern
(`kernel.classify_runtime_quorum`), not convene's.

## Effort-tier policy (design §2/§4)

- The retired tier **`high` is REJECTED** for any provider.
- **codex** seats must pin an explicit tier ∈ `{minimal, low, medium, xhigh, max}`
  — `default` (un-pinned) is rejected (success criterion #4: zero un-pinned codex
  calls). Challenger/ballot/arbiter seats floor at `xhigh`; a **ratification**
  arbiter that resolves to codex pins `max` (timeout 1200).
- **claude / agy** seats use `default` (smart-config advisory tier).

## Guard-stack injection (resolver-owned invariants, design §2)

Convene injects the exact external-CLI stacks — this is not per-prompt discipline:

- **codex**: `timeout <T> codex exec --ephemeral -s read-only -c model_reasoning_effort=<tier> "…" < /dev/null` (`T`: medium 180, xhigh 300, ratification-arbiter max 1200).
- **agy**: `timeout 600 agy --sandbox -p "…" < /dev/null` — every flag BEFORE `-p`, advisory-only, no `--add-dir` in v1.
- **claude**: host-native spawn marker (smart-config tier), not a shell command.

The `"…"` slot is filled at call time with the assembled `seat_prompt.py` envelope.

## Output: the frozen session-plan

Convene materializes a **flat JSON** `session-plan.json` that validates against
[`schemas/session-plan.v1.schema.json`](../schemas/session-plan.v1.schema.json),
carrying `profile_sha256` provenance, the resolved seats + arbiter with injected
guard stacks, the merged budgets, the quorum summary, `phases_planned`, and the
`merge_provenance` (layers = `[shipped_defaults, profile]`; `repo_local_overrides:
none`). Written atomically (temp+rename) to
`<project>/.avengers/sessions/<session-id>/session-plan.json`.

## `--dry-run` (pre-spend review)

`convene.py --dry-run` resolves + validates + prints a pre-spend review (seats,
providers, efforts, guard stacks, quorum, budgets, arbiter, an estimator band from
the §9 cold-start seeds, and the retired-tier note) and **stops — no session dir,
no spend**. A structural failure still exits non-zero even under `--dry-run`.

## CLI

```
# fail-closed review, no spend:
python3 scripts/convene.py --profile coding-ratification --task "…" --dry-run

# materialize + freeze the session-plan under <project>/.avengers/sessions/<id>/:
python3 scripts/convene.py --contract convene.json --project-root .

# inline convenience contract (no file):
python3 scripts/convene.py --profile coding-ratification --task "…" --outcome decision
```
