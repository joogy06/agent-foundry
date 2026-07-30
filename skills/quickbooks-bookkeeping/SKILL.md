---
name: quickbooks-bookkeeping
description: Use when working inside QuickBooks Online day to day — clearing the For Review bank feed, choosing Match versus Add versus Exclude, writing and ordering bank rules without them conflicting, running the Reconcile tool to a statement, and above all finding and repairing the gaps where a feed such as PayPal, Stripe or a card provider failed to sync completely. Covers the QBO-specific dumping grounds (Reconciliation Discrepancy, Undeposited Funds, Opening Balance Equity) where forced differences hide.
disambiguation: Working IN the QuickBooks product — bank feed, rules, matching, the Reconcile tool, feed gaps. Connecting to it programmatically is quickbooks-api; the double-entry principles underneath are bookkeeping-double-entry; diagnosing an unexplained difference in any ledger is ledger-error-diagnosis.
---

# QuickBooks Online — day-to-day bookkeeping

The operational layer: clearing the feed, keeping rules sane, and catching the transactions the feed
never delivered.

## 1. Categorised is not reconciled

The single most costly misunderstanding in QBO. Three different states, and only the third proves
anything:

| State | Means | Proves |
|---|---|---|
| **For Review** | The feed delivered it; nobody has decided what it is | nothing |
| **Categorised** | It has been Added or Matched and sits in the ledger | nothing about completeness |
| **Reconciled** | The **Reconcile tool** agreed the period to a statement balance | that the period is complete |

**An empty For Review queue means nothing.** It says every transaction the feed *delivered* was
dealt with. It says nothing about transactions the feed **never delivered** — which is exactly the
PayPal failure mode in §4.

**Only the Reconcile tool, run against the statement's closing balance, proves completeness.** If
you never run it, a missing transaction is invisible forever.

## 2. Match vs Add vs Exclude vs Transfer

| Action | When | Danger |
|---|---|---|
| **Match** | The transaction already exists in QBO (invoice, bill, payment) | Matching to the *wrong* one leaves the right one open forever |
| **Add** | It genuinely does not exist yet | Adding when you should Match **duplicates** it — the classic QBO duplicate |
| **Transfer** | Money moved between your own accounts | Categorising a transfer as income or expense **inflates both** |
| **Exclude** | Genuinely not a business transaction, or a known duplicate feed line | Excluding to make a queue tidy **deletes evidence from the workflow** |

**Add-when-you-should-Match is the commonest way duplicates enter QBO**, and it is why the aged
debtors list stops agreeing the debtors control: the invoice stays open while a duplicate income
line sits alongside it.

**Exclude is not a bin.** Use it for a genuine double-feed line, not for anything you cannot be
bothered to classify. An excluded real transaction is a hole in the accounts that no reconciliation
will find, because QBO no longer considers it.

## 3. Bank rules — and why they collide

Rules auto-categorise incoming feed lines. They are a large time saving and a large silent-error
source.

**How they go wrong:**

- **Overlap.** Two rules match the same transaction; the one that wins is decided by rule **order**,
  not by which is more specific. A broad rule sitting above a narrow one silently swallows it.
- **Over-broad conditions.** A rule on `contains "AMAZON"` will catch AWS hosting, office
  consumables, and a personal purchase, and file all three identically.
- **Auto-add.** A rule set to add automatically posts without anyone looking. A wrong auto-add rule
  is wrong for every future transaction until someone notices.
- **Silent drift.** A supplier changes its bank narrative, the rule stops matching, and transactions
  quietly start landing uncategorised — or worse, get caught by a broader rule below it.

**Discipline that holds:**

1. **Order narrowest first.** Specific supplier rules above generic keyword rules.
2. **Condition on more than one field** — description *and* amount range, or description *and*
   bank account.
3. **Do not auto-add anything with VAT consequences** until the rule has been observed for a period.
   Auto-add is for the utility bill, not the mixed-use purchase.
4. **Review the rule list quarterly** and delete anything unused — an unused rule is either dead
   weight or is quietly shadowed by another.
5. **When a rule changes, the past does not re-categorise.** Fix the historical entries deliberately.

**Split rules and mixed purchases:** a rule cannot make a judgement. Anything needing a private-use
apportionment or a capital/revenue decision must not be auto-added — see
`business-expenses-and-assets`.

## 4. The feed gap — PayPal, Stripe, cards

**This is the failure you actually hit.** The feed connects, transactions flow, and then a subset
silently never arrives — or arrives as a net figure instead of the underlying detail. Nothing in the
For Review queue tells you something is missing, because a missing transaction has nothing to appear as.

### Detect it — do not hover through both screens

Comparing statements to QBO line by line is the slow way to find it, and it is what people end up
doing because nobody told them the fast checks:

1. **Reconcile to the statement closing balance.** This is the only check that catches a gap by
   arithmetic rather than by eye. A difference *is* the missing amount.
2. **Count transactions per period** — statement count vs QBO count for the same date range. A count
   mismatch localises the gap to a month in seconds.
3. **Look for date-range holes.** Feeds usually fail as a *window*, not as scattered singles. Sort by
   date and look for a suspiciously quiet stretch.
4. **Reconcile the payment processor separately.** PayPal is not a bank feed on your bank account —
   it is its **own account** with its own balance. If it is not being reconciled in its own right,
   gaps there are invisible from the bank side.
5. **Feed one amount into `ledger-error-diagnosis`.** The difference itself often names the class —
   equal to a real transaction, twice one, divisible by 9.

### The partial-transaction problem

A processor payout arriving as a single net line, with the gross sale and the fees never posted, is
**not** a missing transaction — it is a *partially* recorded one, and it is worse because the feed
looks complete.

**The payout is not the sale.** One payout is many orders, minus fees, minus refunds, often across a
period boundary. Post it through a **clearing account**: gross sales in, fees out, net payout out.
Posting only the net understates turnover *and* costs, and for a VAT-registered company understates
output VAT (`bookkeeping-double-entry` §5).

### Repair

- **Small number missing:** add each from the source document, dated correctly.
- **A window missing:** import the provider's CSV for that range rather than keying it. Then check
  for duplicates at both edges — re-imports overlap.
- **Feed broken at source:** disconnect and relink the account, then expect an overlap and dedupe.
- **Always re-run Reconcile afterwards.** A repair you have not re-reconciled is a hypothesis
  (`ledger-error-diagnosis` §5).

## 5. Where QBO hides forced differences

Three accounts that fill up when someone makes a problem go away. **Check all three before trusting
any set of QBO figures.**

| Account | What lands there | What it means |
|---|---|---|
| **Reconciliation Discrepancy** | The difference when a reconciliation is forced through | Someone plugged it — this is QBO's version of posting to suspense |
| **Undeposited Funds** / Payments to deposit | Payments received but never matched to a deposit | Classic with PayPal/Stripe; balloons quietly and overstates debtors-side cash |
| **Opening Balance Equity** | Balances entered at setup and never cleared | Should be empty after setup; a balance means an unfinished migration |

**A non-zero balance on any of these is a finding.** Investigate it rather than presenting accounts
drawn over the top of it. `ledger-error-diagnosis` §1 applies exactly: forcing the books to balance
converts a visible error into an invisible one.

## 6. Replay — when a period that used to reconcile no longer does

QBO keeps an **Audit Log**: every create, edit and delete, with user, timestamp and before/after
values. It answers the question no balance check can — *what did someone change?*

**Reach for it first when a previously-clean period goes bad.** A reconciled period does not
un-reconcile on its own; something was edited, deleted, or had its date changed. The Audit Log names
it, and it is **the only route that finds a deletion**, which by definition leaves nothing behind.

Watch for: a transaction's **date** edited into or out of the period · an amount changed after
reconciliation · a deleted transaction that was part of a reconciled set · a changed opening balance.

For locating *when* a drift began rather than *what* was changed, bisect the periods rather than
scanning them — `ledger-error-diagnosis` §2b and its `bisect_periods.py`.

## 7. A working rhythm

**Weekly** — clear For Review; anything you cannot classify stays in review with a note, never
excluded and never guessed.

**Monthly** — reconcile *every* account to its statement, including PayPal, Stripe and cards as
accounts in their own right; check the three §5 accounts; investigate any count mismatch.

**Quarterly, before VAT** — reconcile everything, prove the VAT control account (`uk-vat` §3), review
the bank-rule list.

**Annually** — everything above, plus the year-end checklist in `uk-statutory-accounts` §4.

## 8. Anti-patterns

- **Treating an empty For Review queue as a completed month.** It only shows what arrived.
- **Never running the Reconcile tool.** Categorising is not reconciling, and only reconciling proves
  completeness.
- **Add-when-you-should-Match**, creating a duplicate and leaving the invoice open.
- **Excluding transactions to tidy the queue.**
- **Forcing a reconciliation** and letting the difference land in Reconciliation Discrepancy.
- **Auto-add rules on anything needing judgement** — private use, capital vs revenue, mixed VAT.
- **Broad rules above narrow ones**, silently shadowing them.
- **Treating a processor payout as the sale.**
- **Not reconciling PayPal/Stripe as accounts in their own right.**
- **Leaving Undeposited Funds or Opening Balance Equity with a balance.**
- **Hunting a broken period by scanning forward** instead of bisecting, or by eye instead of the Audit Log.
