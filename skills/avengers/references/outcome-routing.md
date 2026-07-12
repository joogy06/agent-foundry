# avengers — Outcome Routing (reference)

The authoritative prose for design §8 outcome routing. After `ARBITER` produces a
single result + the mandatory dissent record, `ROUTE` sends it to exactly one of
four destinations. `outcome: auto` (or absent) resolves to the profile's
`outcome.default`; an explicit `outcome` must be offered by the profile's
`outcome.type` (enforced in `convene.py::_resolve_outcome`).

The convene-time input contract (what selects the outcome) lives in
[`convene-contract.md`](convene-contract.md). This file is the OUTPUT side: what
each route emits and where it goes.

<HARD-RULE>
avengers is a deliberation surface, not an executor. The `forge_brief` route hands
a brief INTO forge's gate machinery and STOPS. avengers NEVER spawns bob, NEVER
signs a contract map, NEVER marks anything bob-ready. `contract_map_signed` and
`bob_ready` in the brief are mechanically ALWAYS FALSE. There is no route by which
avengers itself starts a build.
</HARD-RULE>

## The four routes (design §8)

| Route | Emits | Destination | User gate |
|---|---|---|---|
| `decision` | `outcome/decision-record.md` + `outcome/dissent-record.md` | returned to the caller | none (caller owns I/O) |
| `deliverable` | `outcome/deliverable.md` (+ `dissent-record.md`) | returned to the caller; optional profile `handoff` (e.g. writing-cv → career-*) | none |
| `forge_brief` | `outcome/avengers-brief.yaml` + `dissent-record.md` | forge Step 3 intake | **yes, ALWAYS** (even with `--go`) |
| `auto` | resolves to the profile default, then one of the above | — | per resolved route |

`dissent-record.md` is emitted on EVERY route (design §4 ARBITER — mandatory).
Dissent-first output ordering (§9): the dissent record is surfaced before the
decision/deliverable body.

## Caller routing table (design §8)

| Caller | interactive | outcome | user I/O owner | build path |
|---|---|---|---|---|
| user | yes | auto | avengers | yes → forge intake (explicit user gate, ALWAYS) |
| pa | no | decision | pa | no |
| forge (design-exploration) | no | decision (forced) | forge | **blocked** (recursion guard: `forge_session_id` present ⇒ non-build; depth-capped) |
| founder | no | decision | founder | no (founder→forge owns build) |
| alf | no | decision | alf | no |

**Recursion guard (avengers ↔ forge):** a forge-convened avengers session carries
`came_from.forge_session_id`. It is `decision`-forced and its build path is
BLOCKED — it can never emit a `forge_brief` back into the forge that convened it
(forge already pays for its own challengers). This mirrors the note wired into
forge SKILL.md Step 6 (WP-4). See design §8.

## `decision` route

`outcome/decision-record.md`:

- The single decision (front-runner selected by the arbiter).
- Convergence margin: `unanimous` / `converged N-M` / `arbiter broke tie`.
- ≥2 actionable trip-wires ("reopen if X").
- A pointer to `dissent-record.md` (never inlined into the decision body).
- If the run was unanimous with an empty dissent record, the honesty line
  ("unanimous, empty dissent — a single agent would likely have sufficed").

## `deliverable` route

`outcome/deliverable.md` — the produced artifact (a positioning brief, a UX
direction write-up, etc.) with the dissent record attached. A profile MAY declare
a `handoff` (e.g. `writing-cv` → `career-application-writer` for the rendered CV);
avengers deliberates and hands the brief off — it does not render the final
document itself. For `website-ux` the deliverable is accompanied by the auto
`show-comparison` visual (design §9 visual track; see the visual-companion adapter
note).

## `forge_brief` route — the build path

`outcome/avengers-brief.yaml`. This block is the EXACT input contract that forge
SKILL.md Step 3 reads (WP-4 `came_from_avengers` intake); the field set and names
here MUST match that intake mapping (blast-radius control — see
[`reuse-map.md`](reuse-map.md)):

```yaml
# outcome/avengers-brief.yaml — the founder-handshake-shaped build brief (design §8/§10)
came_from_avengers: true
avengers_session_id: <session-id>            # <ts>-<slug>
problem: >                                   # -> forge: the design challenge (skip "what are we building")
  <the decision/design challenge in one paragraph>
constraints:                                 # -> forge: passed to design agents as constraints
  - <hard constraint 1>
success_criteria:                            # -> forge: passed to design agents as constraints
  - <falsifiable success criterion 1>
ruled_out_approaches:                        # -> forge: non-goals + hard "do not explore" signals
  - approach: <approach the team killed>
    killed_by: <seat_id>                     # which seat killed it (founder phase-2 rule mirror)
    why: <one-line reason>
recommended_direction: >                     # -> forge Step 6 seed front-runner (ADVISORY, never locked)
  <the arbiter's front-runner; design agents MAY reject it>
dissent:                                     # -> forge Step 7, surfaced VERBATIM to the user
  - seat: <seat_id>
    position: <the dissenting position, verbatim>
    trip_wire: <the actionable "reopen if X">
confidence: <high|medium|low|speculative>    # -> forge Step 4 complexity input
deliberation_record: <path to the session dir>   # -> forge shared_context (path, NEVER inlined)
contract_map_signed: false                   # MECHANICALLY ALWAYS FALSE — avengers never signs a map
bob_ready: false                             # MECHANICALLY ALWAYS FALSE — avengers never marks bob-ready
```

Field-by-field correspondence with the forge Step 3 intake (WP-4):

| avengers_brief field | forge intake use (Step) |
|---|---|
| `problem` | the design challenge (skip "what are we building") |
| `constraints` | design-agent constraints |
| `success_criteria` | design-agent constraints |
| `ruled_out_approaches` | non-goals + hard "do not explore" (each with `killed_by`) |
| `recommended_direction` | Step 6 seed front-runner — advisory, never locked |
| `dissent[]` | Step 7 presentation — surfaced verbatim |
| `confidence` | Step 4 complexity assessment |
| `deliberation_record` | shared_context prior-exploration reference (path) |
| `contract_map_signed` / `bob_ready` | mechanically always-false; if true ⇒ forge treats the brief as malformed |

If `contract_map_signed` or `bob_ready` is ever true, forge MUST treat the brief
as malformed and re-clarify (WP-4 anti-pattern). They are always-false by
construction here.

## `auto` route (interactive user caller)

For the primary interactive user caller, `outcome: auto` lets avengers infer the
shape from the arbiter result:

- A build-flavored result (the answer is "build X this way") → propose the
  `forge_brief` route and STOP at the ALWAYS user gate before handing to forge.
- A pure decision/deliverable → return it directly.

The forge-brief handoff gate is BLOCKING and fires even under `--go` (design §9
gate table). The user explicitly authorizes the crossing into forge's build
machinery; avengers never crosses it on its own.
