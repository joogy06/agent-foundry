# The intent artifact (`intent.md`) — steward grounding (design §5)

The **steward** is a principal-proxy seat: it represents the *requester's* desired
outcome and standards, pushes for the best outcome, challenges drift, and judges "is
this what was asked / good enough?". A seat with a persona but no independent authority
is decoration (the challengers' warning); the steward's authority comes from a durable
**`intent.md`** artifact. This doc is the contract for that artifact.

This is DATA the steward READS. Nothing here is executed. The reader lives in
`scripts/seat_prompt.py` (`read_intent`, `parse_intent_markdown`,
`classify_intent_trust`, `assess_intent_alignment`).

---

## What it holds

The requester's desired outcome and the bar for "good". Recognized sections (all
optional; a missing section is simply not asserted against):

| Section heading (any alias) | Canonical key | Meaning |
|---|---|---|
| `Desired outcome` / `Outcome` | `desired_outcome` | What the requester actually wants delivered. |
| `What good looks like` / `Good enough` | `good_looks_like` | The quality bar / definition of done. |
| `Standards` / `Quality bar` | `standards` | Standards the result must meet. |
| `Non-goals` / `Out of scope` | `non_goals` | What NOT to do — the anti-scope-creep guard. |
| `Risk limits` / `Risk` | `risk_limits` | Tradeoffs/risks the requester will and will not accept. |

Example:

```markdown
# Desired outcome
Lower the default codex reasoning effort so bounded reviews stop overspending, without
losing edge-case catching on the hard ones.

# What good looks like
Per-call effort pins; the config default is advisory only. No regression on the
2026-07-11 sol benchmark's xhigh quality ceiling.

# Non-goals
Do not touch the interactive session model. Do not add a new external dependency.

# Risk limits
Accept a small latency increase on hard reviews; do NOT accept a correctness regression.
```

### Forward-compatible parsing (load-bearing)

Parsing **ignores unknown headings** (kept aside in `additional_sections`, never
rejected). This is deliberate: the deferred **autonomy layer** upgrades `intent.md` into
an intent + **delegation charter** by *adding* sections — `may-decide`,
`acceptable-tradeoffs`, `must-escalate` — and that must be a clean ADDITIVE extension. An
`intent.md` carrying charter sections parses today without error; v2 simply doesn't act
on them.

---

## Trust-class (design §5) — where it came from decides how it's read

`intent.md` is requester-authored, so a TRUSTED one is read like the
`AUTHORIZED_TASK_DIRECTIVE`. But a repo-committed file is an injection surface (a PR
could edit it to steer the steward). Trust therefore depends on the SOURCE:

| Source | Trust-class | How the steward reads it |
|---|---|---|
| convene-supplied path, OR a home-tier location (`~/...`) | **trusted** | Requester-authored directive — the steward's authoritative lens. |
| working-repo-only file | **untrusted** | Reference DATA only; the steward flags **"unverified intent source — confirm"** and does not treat it as an authoritative directive. |
| none found | **provisional** | The steward extracts a PROVISIONAL intent from the original ask and flags **"operating on inferred intent — confirm"**. It NEVER silently invents standards / non-goals / risk-limits (escalate-unknown — the codex guardrail). |

This mirrors the home-tier trusted-state rule from the fixes cycle.

---

## How the steward uses it

1. **Blind position** — files a position from the requester-intent lens (what the
   requester asked for, what "good" means here).
2. **Cross-exam** — PUSHES for the best outcome and CHALLENGES drift ("this has drifted
   from the stated outcome"; "is this good enough vs what was asked?").
3. **Converge** — emits an **intent-alignment assessment**: for each intent item, a
   status of `pass | fail | unknown`.
   - `fail` (drift) → an actionable **trip-wire** on the decision.
   - `unknown` (no finding for that item) → a **confirm** flag (escalate, do not invent).
   The external arbiter weighs the steward's push like any seat; the assessment reaches
   the human as trip-wires.

**The steward does NOT decide and does NOT arbitrate.** It has skin in the outcome, so it
is never the neutral judge (`adversarial_role: false`, and `can_arbitrate` is inert under
v2 — the arbiter is a fresh external seatless call; NO seat adjudicates). Decide-authority
is the deferred autonomy layer's, granted only through the charter extension above and
never in an interactive convene where you are present.
