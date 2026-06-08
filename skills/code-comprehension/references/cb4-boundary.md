# CB4 boundary — the claimless / read-only guarantee

CB4 (the ecosystem invariant): **bob is the sole writer of the integration ledger** (`progress/integration-ledger.md`, `.ledger/claims/`, `.ledger/deltas/`, …). Skills emit transition *requests* to `.ledger/requests/`; bob consumes them. A leased skill run must be **provably unable to drive a real ledger transition** — that is the challenger's kill-criterion for this skill.

## How code-comprehension satisfies it: by ABSENCE

`code-comprehension` (via `comprehension_run.py`) writes **only** under the target repo's `.comprehension/` scratch dir (and, on the separate human-gated `--migrate`, the real docs). It writes **nothing** under `.ledger/` or `progress/`.

The two extractors it composes (`wiring-extract-static`, `intent-extract`) DO, in their normal bob-driven mode, claim + heartbeat + emit `.ledger/requests/`. To make the standalone pipeline CB4-safe **structurally** (not by convention), both gain a `--standalone` mode:

| Property | Normal mode | `--standalone` mode |
|---|---|---|
| Claim required | `--claim-uuid` required | **no `--claim-uuid` accepted** |
| Heartbeat thread | constructed + started | **never constructed** (the object is not instantiated) |
| Transition request | emitted to `.ledger/requests/` | **unreachable** (guarded at the call site by the standalone flag) |
| Output root | `.wiring/` (bob-created) | configurable under `.comprehension/` |

"Structural" means: in standalone mode there is **no code path** that constructs a claim heartbeat or writes a `.ledger/requests/` file. It is not `--no-heartbeat` sugar over a still-present path.

## `.wiring/` single-creator invariant

`wiring-extract-static` refuses to run unless `.wiring/` already exists ("never creates `.wiring/` root — that's bob's job, single-creator invariant"). For a standalone run there is no bob, so **the orchestrator owns `.wiring/` creation** — it plays the single-creator role for the non-bob run, under `.comprehension/.wiring/`. There is exactly one creator (the orchestrator) per standalone run, so the invariant is preserved. Both dirs are scratch the orchestrator also cleans.

## The HARD acceptance test

`tests/test_cb4_boundary.py`: snapshot `.ledger/` and `progress/` (recursive file list + per-file sha256) **before** and **after** a full standalone run on a fixture repo → assert **byte-identical** (zero new/changed/deleted files). This is the central guarantee and the gate the design names first.

On a real dogfood repo that happens to carry a stale signed `progress/contract-map.yaml`+`.sig` (a leftover partial-cycle map), the run additionally asserts it never touched that map or its signature — the pristine signed map must remain byte-identical.
