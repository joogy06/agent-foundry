---
name: ledger-error-diagnosis
description: Use when a ledger will not agree — a trial balance that does not balance, a bank or control account that will not reconcile, a VAT return that does not tie to the VAT control account, a balance sheet where net assets do not equal shareholders' funds, or suspected duplicate, missing, mis-signed or mis-period transactions. Covers the arithmetic signatures that identify an error class from the difference alone, the detection query for each class, and the correction protocol that fixes the books without destroying the audit trail.
disambiguation: DIAGNOSING and CORRECTING a discrepancy that already exists in the books. The routine proofs that surface one (control accounts, bank rec, month-end close) are bookkeeping-double-entry; errors in EXTRACTION before posting are financial-document-ingestion; VAT-specific error-correction routes and thresholds are uk-vat.
---

# Ledger error diagnosis

Something does not agree. This is how you find out what, and fix it without making the record worse.

## 1. The rule

**A difference is information. Never force it away.**

Plugging a difference to suspense, journalling it to P&L "to tidy up", or deleting a transaction that
looks wrong all convert a *visible* error into an *invisible* one. The books then balance and are
wrong, which is strictly worse than not balancing — because nothing will ever flag it again.

**Corrections are new entries, never overwrites or deletions.** The audit trail is the point: an
enquiry asks what happened, and "it was edited" is not an answer.

## 2. Narrow before you hunt

Do not scan the ledger. Halve the search space first — this usually takes minutes and turns an
open-ended hunt into a short list.

1. **Which proof failed?** Trial balance · bank rec · a control account · VAT · net assets. Each
   implicates a different set of accounts.
2. **When did it last agree?** The last clean period bounds the error to one window. If nothing was
   ever proved, prove the oldest period first and walk forward — errors compound, and the earliest is
   usually the cause of several later ones.
3. **Is the difference stable or growing?** Stable = one event. Growing = a recurring posting rule
   is wrong, which is a bigger and more valuable find.
4. **Note the difference exactly**, signed and to the penny. §3 reads it.

## 2b. Replay — three real techniques, cheapest first

"Play the accounts back to find where it broke" is a real thing, in three distinct forms. They cost
very different amounts and answer different questions, so pick deliberately.

### (a) Period bisect — the one to reach for

**Do not scan forward through months.** Binary-search them.

You have a period-end proof (control-account balance, or bank rec) that agrees at some early point
and fails now. The error entered in exactly one period. So:

1. Take the midpoint period. Prove it.
2. Agrees → the error is **after** it. Fails → the error is **at or before** it.
3. Repeat on the surviving half.

**24 months collapses to about 5 checks instead of 24.** The output is not "something is wrong" but
"it broke in March 2026" — which is a short list of transactions rather than a hunt.

`scripts/bisect_periods.py` does this over a series of period-end expected-vs-actual balances and
names the first divergent period, plus how much entered *in* that period as opposed to being
inherited from before it. That distinction matters: a balance that is wrong because the opening
balance was already wrong is not an error in that period at all.

### (b) The change log — what someone did

Most systems keep one, and it answers a different question: not *when the balance broke* but *what
was changed*. QuickBooks Online has an **Audit Log** recording every create, edit and delete with
user, timestamp and before/after values.

Use it when the numbers moved and nobody knows why — a prior period that used to reconcile and no
longer does is almost always an edit or a deletion, and the log names it. **This is the fastest route
when a previously-clean period goes bad**, and it is the only route that identifies a deletion, which
by definition leaves nothing behind to find.

### (c) Deterministic rebuild — what it *should* be

If the source documents are stored and indexed (`financial-document-ingestion` §6), the books can be
recomputed from them and diffed against what the system holds. The first divergence is the error, and
the rebuild also tells you the correct figure rather than just that the current one is wrong.

This is the strongest technique and the most expensive: it needs complete, indexed sources and stable
posting rules. It is the pay-off for the document store — build the store as you go, and this becomes
possible; skip it, and you are left with (a) and (b).

**Order of attack:** (b) if a clean period went bad · (a) to localise anything else · (c) when you
need the right answer rather than just the location.

## 3. Read the difference — arithmetic signatures

The number itself narrows the class before you look at a single transaction. These are classic and
they hold:

| Signature | Almost certainly | Why |
|---|---|---|
| **Divisible by 9** | **Transposition** — 54 keyed as 45 | Any digit swap yields a multiple of 9 |
| **Divisible by 9, order of magnitude** | **Digit slide** — 100 as 1,000 | Same arithmetic property |
| **Exactly 2× a real transaction** | **Wrong side** — debit posted as credit | The entry is out by twice its value |
| **Equals a transaction exactly** | **Missing** or **duplicated** entry | One posting absent or present twice |
| **Small pence** | **Rounding** or **FX** | Accumulated fractions, or a rate difference |
| **Round hundreds/thousands** | **Missing whole transaction** | Real invoices are rarely round; estimates are |
| **Difference is a VAT fraction** (÷6, ÷5) | **VAT treated wrongly** | Gross posted as net, or standard vs zero-rated |

Run the cheap checks first: divide by 9, divide by 2, and search for a transaction of exactly the
difference. `scripts/diagnose_difference.py` does all three and reports the candidate classes.

## 4. The error classes — detect and correct

### Rounding
**Detect:** differences under ~£1 that persist; VAT lines where net + VAT ≠ gross by pennies.
**Cause:** recomputing VAT instead of taking the invoice figure; rounding at each line rather than
once at the end; float arithmetic.
**Correct:** post a documented rounding adjustment to a dedicated account — never to suspense, and
never silently. If it recurs, **fix the rule, not the symptom**: money should be integer pence, and
the invoice's own VAT figure is the one that counts (`financial-document-ingestion` §3).

### Missing transaction
**Detect:** bank line with no book entry; supplier statement showing invoices you do not hold; a gap
in an invoice number sequence; a direct debit present in prior months and absent this one.
**Correct:** post it from the source document, in **its own period**, not the current one.
**VAT:** if it falls in a filed period, this is an error correction — `uk-vat` §6 decides the route.

### Duplicated transaction
**Detect:** same date + amount + reference twice (V7 in `financial-document-ingestion`); a supplier
paid twice; a statement boundary where the last lines of one period repeat as the first of the next.
**Distinguish carefully:** genuine repeats exist. Standing orders, identical monthly subscriptions
and split invoices all look like duplicates. **Check the source document before reversing anything.**
**Correct:** reverse the duplicate with a journal referencing the original. **Do not delete it** —
deletion hides that a duplicate was ever posted, which is exactly what an enquiry wants to see
handled properly.

### Missing invoice or bill
**Detect:** debtors/creditors control not agreeing the aged list; a payment with no matching invoice;
income received with no sales invoice raised.
**Correct:** obtain the document, then post. **An accrual is not a substitute for an invoice you can
still obtain** — and for VAT, no valid invoice means no input claim, full stop.

### Wrong period (cut-off)
**Detect:** the difference appears in one period and reverses in the next; year-end creditors
understated; an invoice dated in one period paid and posted in another.
**Correct:** move it to the correct period with accruals/prepayments. **Cut-off errors are the most
common year-end misstatement** — anchor on the tax point and the delivery date, not the payment date.

### Wrong sign / wrong side
**Detect:** difference is exactly 2× a transaction; a refund posted as an expense; a negative balance
that cannot be negative (stock, most bank accounts).
**Correct:** reverse and repost. **A refund is negative income, not a cost** — posting it as a cost
overstates turnover and costs simultaneously and misstates VAT.

### Wrong account
**Detect:** an expense category that moved sharply with no business reason; capital items in repairs;
director's personal spending in overheads.
**Correct:** reclassify by journal. **This one has tax consequences** — capital vs revenue changes
the corporation tax computation (`uk-corporation-tax` §2/§3), and personal spending belongs in the
director's loan account, where it may trigger s455.

### Foreign currency
**Detect:** small unexplained differences on foreign supplier accounts; balances that move without
transactions.
**Correct:** post the exchange difference to a realised/unrealised FX account. Record the rate used
and its source.

## 5. The correction protocol

Every correction, without exception:

1. **Identify the source document** proving what should have happened.
2. **Post a correcting journal** — new entry, dated correctly, never an edit or a delete.
3. **Narrate it** so a stranger understands: what was wrong, what it should be, which document proves
   it. *"Adjustment"* is not a narrative.
4. **Reference the original** transaction id.
5. **Consider VAT** — if the period is filed, `uk-vat` §6 decides adjust-on-next-return vs separate
   disclosure. Deliberate errors are never quietly adjusted.
6. **Consider corporation tax** — a corrected prior year may change a filed CT600.
7. **Re-run the proof that failed.** A correction you have not re-verified is a hypothesis.
8. **Record it** in the document index with a `posted_ref` (`financial-document-ingestion` §6).

**If the correction does not fully clear the difference, you have found a second error.** Do not
absorb the remainder — repeat from §2. Two errors partially offsetting is common, and absorbing the
remainder is how a plug hides one of them.

## 6. When it is bigger than a correction

Escalate rather than quietly fixing when:

- The period is **filed** and the error is material — VAT disclosure or an amended CT600.
- The error is **systematic** — a wrong posting rule means every affected period is wrong.
- It crosses a **year end** — prior-period adjustment, and comparatives may need restating.
- It changes a **statutory figure** already on the public register.
- It suggests something other than error — **stop, and involve the director and a qualified
  accountant.** Do not "correct" a possible fraud on your own initiative.

## 7. Anti-patterns

- **Plugging the difference to suspense** so it balances. The single most damaging habit here.
- **Deleting a transaction** rather than reversing it. Destroys the audit trail; in QuickBooks,
  prefer a reversing entry and keep deletes disabled (`quickbooks-api` §4).
- **Correcting in the current period** what belongs in a prior one.
- **Reversing a "duplicate"** without checking the source document.
- **Recomputing VAT** to make an invoice foot instead of reading it.
- **Accepting a partial clear** and absorbing the rest.
- **Not re-running the proof** after correcting.
- **Fixing the symptom of a systematic error** one period at a time.
