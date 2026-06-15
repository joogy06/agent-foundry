# Output Shapes — templates for the `summarize` skill

Pick one in Step 1. Every shape obeys the faithfulness + attribution HARD-RULEs. Lead with the answer; keep figures/names/dates verbatim.

---

## §1 TL;DR (default)

1–3 sentences capturing the single most important thing a reader needs. No preamble ("This document discusses…" is banned — say the thing).

> **TL;DR** — Migration to the new billing provider is approved and starts 2026-07-01; the cutover freezes refunds for 48h and needs the data team to backfill 3 months of invoices first.

## §2 Key points (default companion to TL;DR)

≤7 bullets, ordered by importance, each one fact. Group only if >7 forces it (max ~7 per group, Miller's law).

> - Provider chosen: **Stripe Billing** (board-approved 2026-06-09).
> - Cutover window: **2026-07-01 → 07-03**, refunds frozen 48h.
> - Blocker: data team must backfill **3 months** of invoices first — owner unassigned.
> - Cost delta: **+$1,200/mo**, offset by retiring two legacy jobs.

## §3 Executive summary

For a manager/stakeholder. Structure: **lead paragraph** (what + why it matters) → **3–5 bullets** (the substance) → **bottom line** (decision needed / status / risk). One screen max. Audience = exec: drop jargon, keep money/dates/risk.

> **<Subject> — Executive Summary**
> <Lead paragraph: the situation and why it matters now.>
> - <key point with figure>
> - <key point with date/owner>
> - <key risk or dependency>
> **Bottom line:** <the one decision, status, or ask>.

## §4 Action items & decisions

The "what do I need to do" shape. Two tables. An item with no owner in the source is listed with **owner: (unassigned — not stated)** — never invent one.

> **Decisions**
> | Decision | Made by | Date | Source |
> |---|---|---|---|
> | Adopt Stripe Billing | Board | 2026-06-09 | [Billing RFC, p.1] |
>
> **Action items**
> | Action | Owner | Due | Source |
> |---|---|---|---|
> | Backfill 3mo invoices | Data team (lead unassigned) | before 07-01 | [thread: A.Patel 06-08] |
> | Draft refund-freeze comms | (unassigned — not stated) | — | [Billing RFC, p.3] |

## §5 Meeting minutes

For a meeting transcript or a decision thread. Sections: **Context** (1 line) · **Attendees/participants** (if stated) · **Decisions** · **Action items** (owner·due) · **Open questions** (unresolved in the source). Keep it skimmable; don't narrate the discussion blow-by-blow.

## §6 Abstract

A single dense paragraph (≈4–8 sentences) for a paper/report: problem → approach → key findings/numbers → conclusion. No bullets, no headings. Every claim from the source.

## §7 Structured (per-section)

For a long structured document. One line per section + an overall TL;DR on top. Mirrors the source's own headings so the reader can navigate back.

> **Overall:** <TL;DR>
> - **<Section 1 heading>** — <one-line summary>
> - **<Section 2 heading>** — <one-line summary>
> …

---

## Length budgets

| Budget | Means |
|---|---|
| "one line" | TL;DR, single sentence |
| "a paragraph" | TL;DR + ~3 bullets, or one abstract paragraph |
| "one page" | Executive summary or full minutes |
| "as long as it needs" | Structured per-section + key points; still ruthlessly drop redundancy |

When a length budget forces cuts, state the *class* of detail dropped ("dropped per-meeting attendance lists; kept decisions + actions"). Compression is allowed; silent omission of load-bearing facts is not.

## Audience tuning

- **Exec** — money, dates, risk, the ask. Drop implementation detail and jargon.
- **Technical** — keep the mechanism, version numbers, error specifics; drop business framing.
- **Personal** (the user's own inbox/notes) — keep it terse and action-first; "you need to…" framing is fine here.
