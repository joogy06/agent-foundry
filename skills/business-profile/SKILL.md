---
name: business-profile
description: Use when a business's operational knowledge should persist across sessions instead of being rediscovered every time — who each vendor and customer is, the bank narratives they appear under, how and how often they bill, their normal amount range, their category and VAT treatment, plus free-text notes on how each one actually behaves. Learns baselines from transaction history and flags when a pattern CHANGES — a renamed supplier, an amount outside its usual range, a recurring bill that stopped arriving, or a VAT treatment that shifted.
disambiguation: The OPERATIONAL profile — counterparties, billing patterns, learned baselines and drift. Market position, competitors and share of voice are business-edge; the obligation calendar and deadlines are accounting-uk-ltd's tracker; posting the transactions is bookkeeping-double-entry.
---

# Business profile — learn it once, notice when it changes

Stops every session starting from zero, and turns "that transaction looks odd" into "that
transaction **changed**, here is what it used to be."

## 1. What it holds

Per counterparty, learned from history rather than declared:

| | |
|---|---|
| **Narratives** | Every bank text this counterparty has appeared under |
| **Cadence** | monthly · weekly · quarterly · annual · irregular, inferred from the gaps |
| **Amount range** | Observed min / max / median — **or an explicit "too few observations"** |
| **Category & VAT treatment** | What it is normally coded as |
| **Notes** | Free text: *how this one actually bills* — the knowledge that otherwise lives in someone's head |

The notes field is the one that pays off. *"Worldpay deducts the whole month's fees from a single
settlement around the 12th"* is exactly the kind of thing that is rediscovered painfully every year
(`bookkeeping-double-entry/references/transaction-patterns.md` §2b).

## 2. The routine

```bash
P=.accounting/business-profile.json

# once, and again whenever you have a fresh batch of history
python3 ~/.claude/skills/business-profile/scripts/profile.py --profile "$P" \
    learn --transactions transactions.json

# every session, before working: what changed?
python3 ~/.claude/skills/business-profile/scripts/profile.py --profile "$P" \
    check --transactions new-transactions.json

# "who is this?" — instead of guessing again
python3 ~/.claude/skills/business-profile/scripts/profile.py --profile "$P" \
    match --narrative "WORLDPAY SETTLEMENT 14/06"

# record what you learn about a counterparty
python3 ~/.claude/skills/business-profile/scripts/profile.py --profile "$P" \
    note --id "WORLDPAY SETTLEMENT" --text "monthly fees deducted from one settlement ~12th"
```

**Run `check` before working, not after.** Its findings change what the rest of the session should
look at.

## 3. What drift detection actually catches

| Finding | Why it matters |
|---|---|
| **missed_recurrence** | A monthly bill stopped arriving. **Cancelled, or a feed gap** — and nothing else in the books can see this, because a transaction that never arrived has nothing to appear as |
| **possible_rename** | An unknown narrative resembling a known counterparty. Its history is about to be orphaned, and **the bank rule keyed on the old name has silently stopped matching** |
| **narrative_changed** | Known counterparty, new bank text. Same rule consequence |
| **amount_outside_range** | Price rise, a different service, or a keying error |
| **vat_treatment_changed** | **Never fails a control-account proof** — the money still balances, so nothing else will flag it |
| **category_changed** | Deliberate reclassification, or a mis-code |
| **unknown_counterparty** | Classify once, known from then on |

**`missed_recurrence` is the one worth having.** It is the only check in this whole family that
detects an *absence*. It caught the feed-gap class from the opposite direction to
`quickbooks-bookkeeping` §4 — that reconciles to a balance, this notices a habit that stopped.

**`amount_outside_range` catches the Worldpay pattern for free.** A settlement of £640 against an
observed £990–£1,010 is flagged without anyone knowing why yet — which is the right order.

## 4. Every finding is a question

**The tool reports what moved against what baseline. It never concludes.**

Vendors legitimately rename. Prices rise. Billing moves from monthly to annual. A business changes
what it buys. Auto-classifying change as error would train people to dismiss the findings, which is
worse than not producing them.

So the output is always *"this changed, from this, is that expected?"* — and a human answers.

**Confidence is stated honestly.** A baseline built on fewer than four observations reports
`insufficient` rather than asserting a range it cannot support. Two data points are not a pattern,
and a tool that pretends otherwise flags noise until nobody reads it.

## 5. Narrative matching

Bank descriptions carry dates, references, card suffixes and payment ids that differ every time.
Matching raw text means every transaction looks new, so narratives are normalised — volatile parts
stripped, the stable stem kept — before comparison.

That is why `ACME SUPPLIES LTD REF:88213` and `ACME SUPPLIES LTD REF:92100` are one counterparty,
while `ACME SUPPLIES LIMITED T/A ACME` surfaces as a **possible rename** rather than silently
matching or silently not.

**Rename detection is deliberately a weak signal offered as a question.** "Ltd" becoming "Limited"
and a genuinely new vendor sharing a word look identical from here.

## 6. Where it fits

- **Feeds it:** `financial-document-ingestion` (validated rows), a bank/processor export, or the
  QuickBooks API (`quickbooks-api`).
- **Feeds into it:** `quickbooks-bookkeeping` — a `narrative_changed` finding is precisely the bank
  rule that needs fixing before it silently mis-files a month.
- **Escalates to:** `ledger-error-diagnosis` when a finding turns out to be a real error.
- **Distinct from** `accounting-uk-ltd`'s tracker, which holds *obligations and deadlines*. This
  holds *who and how*. Both persist; they answer different questions.

## 7. Anti-patterns

- **Treating a finding as a verdict.** It is a question with a baseline attached.
- **Learning from unvalidated extractions.** Garbage in becomes a confident baseline
  (`financial-document-ingestion` §4).
- **Building a baseline from two transactions** and trusting the range.
- **Ignoring `missed_recurrence`** because nothing looks wrong — that is the point of it.
- **Not recording what you learn.** The note you do not write is the thing rediscovered next year.
- **Letting a rename orphan a counterparty's history** instead of linking it.
