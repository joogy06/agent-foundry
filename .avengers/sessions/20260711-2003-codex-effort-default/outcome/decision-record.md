# Decision Record — codex effort default

- **Session**: `20260711-2003-codex-effort-default`
- **Profile**: `coding-ratification` (ratification family)
- **Decision question**: Should `~/.codex/config.toml` `model_reasoning_effort` default be LEFT at `max` or LOWERED (and to which tier)? Delegated/orchestrated calls already pin effort per-call; the default affects interactive sessions + any un-pinned call only.
- **Incumbent premise**: "Leave the default at `max`." → **REJECTED unanimously** (all three seats voted `CHANGE_NEEDED`).

## Decision (arbiter recommendation — NOT self-executed)

**Lower the default `model_reasoning_effort` in `~/.codex/config.toml` from `max` to `xhigh`.**
Keep `max` available as an explicit per-call escalation for the hardest design/debug tasks.

- **Convergence margin**: converged **2-1** — skeptic + operator on `xhigh`; architect split on `medium`.
- **Grounding**: 2026-07-11 codex-sol effort benchmark (14 scored runs) — `xhigh` is the reliable tail-find floor at ~60s median; `max`/`ultra` are pure waste on bounded work at ~300s. External grounding present.
- **Confidence**: `medium` (ceiling set by the small benchmark sample; grounding rule respected — no higher without a larger run).

## How the deliberation moved (value proof)

The blind round was a soft, correlated unanimous "`medium`". Cross-examination changed the outcome:
- **OB-2** (operator→skeptic): skeptic **conceded** that opt-in escalation is undemonstrated (no classifier/warning exists) → flipped `medium`→`xhigh`.
- **OB-3** (architect→operator): operator **conceded** that `medium` latency was never measured while `xhigh` is measured (~60s) → flipped `medium`→`xhigh`.
- **OB-1** (skeptic→architect): architect **held** `medium`, defending it as the true low-latency baseline and framing hard tasks as a distinct opt-in state (answered, not conceded).

A single agent would most likely have returned the soft "`medium`" without surfacing that `medium`'s latency advantage over `xhigh` is unmeasured — the core evidence gap that flipped two of three seats.

## Trip-wires (actionable; reopen conditions)

1. **Reopen if** unpinned hard-task failure/rework rate rises materially (arbiter: >10%) under the new `xhigh` default.
2. **Reopen if** a larger benchmark (>50 runs) shows `xhigh` is not a reliable tail-find floor, or its median latency exceeds ~90s.
3. **Reopen if** end-to-end interactive trials show `medium` matches `xhigh`'s hard-task correctness at materially lower latency/cost (architect's standing position would then win).

## Route

- Outcome type: `decision` (per `coding-ratification` profile). Returned directly to the user with the dissent record.
- avengers does NOT apply this change. **The user owns the final call and the edit** (this decision is exactly the `tasks.md` "Leave or lower — user call" item).
- Write-back proposal phase: **deferred** — the memory subsystem lands in WP-3; this slice proposes no standing memory.

## Provenance / caveats

- Session plan (frozen): `../session-plan.json` (profile sha `cd11e224…`).
- Live-run seat substitutions from the shipped profile (recorded in session-plan.json): architect `claude→agy`, operator `agy→codex(medium)`. Reason: the prose chair is a bob subagent (S055) and cannot cold-spawn Claude member seats; substitutions preserved 3 member seats + 2 provider families and the arbiter≠adversarial-provider invariant.
- **Correlation caveat** (chair-added; the arbiter missed it): the arbiter (agy/Gemini) shares its provider with the architect seat — the lone `medium`-holder. The arbiter still decided *against* its provider-sibling (`xhigh`, not `medium`), which mitigates but does not erase the correlation.
- `served_by` is provider-REPORTED and was inconsistent for codex (`GPT-5.6-Codex` / `gpt-5.6-sol` / `GPT-5`) — recorded, not verified.
