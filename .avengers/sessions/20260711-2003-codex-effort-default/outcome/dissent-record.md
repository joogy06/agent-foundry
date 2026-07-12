# Dissent Record — codex effort default (MANDATORY, always present)

- **Session**: `20260711-2003-codex-effort-default`
- **Convergence margin**: converged **2-1** (not unanimous). The honesty line does NOT apply — this run produced genuine, non-empty, attributed dissent.
- **Decision it dissents from**: "Lower the default to `xhigh`."

## Attributed dissent

### architect (minority position — holds `medium`, provider: agy)
Dissents from `xhigh`; recommends `medium`.
- `xhigh`'s ~60s median (30-120s tail) is a **flow tax** on the routine interactive loop (quick edits, config changes) that dominates unpinned use.
- The default should be the **cheapest sufficient baseline**, with high-effort explicitly pinned at the boundary of hard sessions — a cleaner, more legible system boundary.
- **Shared concern (also held even in the majority):** lowering below `max` at all creates a **silent under-powering hazard** for unpinned hard tasks because users routinely fail to classify a task as hard, and there is no auto-escalation/detection mechanism.

### skeptic (in the majority for `xhigh`, but holds a residual, provider: codex)
- `xhigh` **still misses** findings that only `max` reached on the hardest tasks. No default eliminates the correctness/latency trade-off without automatic task classification; `xhigh` merely reduces the under-reasoning cliff while avoiding `max`'s routine blast radius.

### operator (in the majority for `xhigh`, but holds a residual, provider: codex)
- **No monetary cost** was measured — the cost-saving case is directional, not quantified.
- `xhigh`'s latency **range is broad (30-120s)**; the ~60s figure is a median, not a guarantee.

## Unresolved obligation carried to the user

- **OB-1** (medium vs xhigh) was *answered*, not *conceded* — architect's `medium` case was not defeated on evidence, it was outweighed by the (conceded) unmeasured-latency and unreliable-opt-in points. If the missing measurements land the other way, the minority position wins. This is the live tension the user should weigh.

## Chair-added caveat (not from a seat)

- **Provider correlation:** the arbiter and the lone `medium`-dissenter (architect) both ran on agy/Gemini; the arbiter's own claim of "no shared providers" is factually wrong. The arbiter decided against its provider-sibling, but a user weighing the 2-1 margin should note that the two `xhigh` votes were both codex and the one `medium` vote plus the arbiter were both agy — the provider split mirrors the position split.
