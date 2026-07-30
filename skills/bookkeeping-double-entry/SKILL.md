---
name: bookkeeping-double-entry
description: Use when posting transactions, designing a chart of accounts, reconciling a bank account, clearing suspense and control accounts, running a month-end close, or producing a trial balance, profit and loss account and balance sheet from underlying records. Covers double-entry mechanics, accruals and prepayments, control-account proofs, and the reconciliation discipline that has to hold before any tax return or set of accounts is drawn from the books.
disambiguation: The bookkeeping ENGINE — double entry, reconciliation, control accounts, trial balance — and it is jurisdiction-neutral. UK filing obligations and tax computations live in accounting-uk-ltd and its uk-* siblings. Reading source documents into transactions is financial-document-ingestion. Project budget-vs-actual and EVM is project-finance.
---

# Double-entry bookkeeping

The engine underneath every return and every set of accounts. Get this wrong and everything computed
from it is wrong in a way no downstream check will catch.

## 1. The rule everything else rests on

**Every transaction has equal debits and credits, and the accounting equation always holds:**

```
Assets = Liabilities + Equity
```

| | Debit increases | Credit increases |
|---|---|---|
| **Assets** (bank, debtors, stock, equipment) | ✓ | |
| **Expenses** (purchases, wages, rent) | ✓ | |
| **Liabilities** (creditors, VAT owed, loans) | | ✓ |
| **Income** (sales) | | ✓ |
| **Equity** (share capital, retained profit) | | ✓ |

Mnemonic that survives pressure: **DEAD CLIC** — **D**ebit **E**xpenses **A**ssets **D**rawings,
**C**redit **L**iabilities **I**ncome **C**apital.

**If a trial balance does not balance, you have made an error — you have not found a rounding
quirk.** Do not plug it.

## 2. Chart of accounts for a small Ltd

Keep it small. A chart nobody can hold in their head gets mis-posted.

| Range | Type | Typical accounts |
|---|---|---|
| 1000–1999 | Assets | Bank current, bank savings, trade debtors, stock, equipment, accumulated depreciation |
| 2000–2999 | Liabilities | Trade creditors, **VAT control**, **PAYE/NIC control**, **wages control**, director's loan, corporation tax payable |
| 3000–3999 | Equity | Share capital, retained earnings |
| 4000–4999 | Income | Sales (split by stream if VAT treatment differs), other income |
| 5000–5999 | Cost of sales | Purchases, carriage, direct labour |
| 6000–7999 | Overheads | Rent, utilities, software, professional fees, insurance, motor, **depreciation** |
| 9999 | **Suspense** | Temporary only — see §5 |

**Split sales by VAT treatment**, not by curiosity. Standard, zero-rated, exempt and outside-scope
income must be separable or the VAT return cannot be built without re-analysing everything.

## 3. Control accounts — the proofs that make books trustworthy

A control account is a running total whose balance must equal an independently-derived figure. When
they agree, a whole class of error is excluded. **Prove each one every period.**

| Control | Must equal |
|---|---|
| **Bank** | The bank statement balance, after listing unpresented items |
| **VAT control** | The VAT due per the return for the period, plus/minus anything unpaid from prior periods |
| **Trade debtors** | Sum of unpaid sales invoices in the aged list |
| **Trade creditors** | Sum of unpaid purchase invoices in the aged list |
| **Wages control** | Net pay + PAYE + NI + pension per the payroll run — should clear to nil |
| **Director's loan** | The director's own record; it is a real debt in both directions |

**A control account that does not prove is a finding, not a rounding issue.** When one will not
prove, `ledger-error-diagnosis` reads the difference itself to narrow the class before you start
hunting — a difference divisible by 9 is a transposition, twice a real amount is a wrong-side
posting.

## 4. Bank reconciliation — the non-negotiable one

```
Balance per bank statement
  −  unpresented payments (written, not yet cleared)
  +  outstanding lodgements (banked, not yet credited)
  =  balance per cash book
```

Procedure that actually works:
1. Tick statement lines against book entries, oldest first.
2. Anything on the statement and not in the books → **post it** (bank charges, interest, direct
   debits, card fees).
3. Anything in the books and not on the statement → **age it**. An unpresented item older than ~6
   months is usually an error, not a slow cheque.
4. Anything that matches by amount but not by date → check it is not a **duplicate**.
5. Reconcile to **zero difference**. Not "close". If it will not, go to `ledger-error-diagnosis`
   rather than absorbing the remainder.

**Reconcile before every VAT return and before year end.** A return drawn from unreconciled books is
a guess with a number on it.

## 5. Suspense and clearing accounts — and the discipline they need

- **Suspense** holds what you cannot yet classify. It is a *question*, never an answer.
- **Clearing accounts** hold items mid-journey — payments in transit, inter-account transfers, card
  settlement, marketplace payouts. They are legitimate and should **clear to nil** each period.

Rules that keep them honest:

- **Nothing stays in suspense past period end without being reported.** List every item, its age and
  its amount.
- **Never post a balancing figure to suspense to make a trial balance agree.** That converts a
  visible error into an invisible one — the single most damaging habit in small-company books.
- **A clearing account with a residual balance is unfinished work.** Investigate the residual; do not
  journal it to P&L to tidy up.
- Marketplace and payment-processor payouts belong in a clearing account: gross sale in, fees out,
  net payout out. Posting only the net payout **understates both turnover and costs** — and for a
  VAT-registered company understates output VAT, which is an error with penalty exposure.
- **The awkward shapes have their own reference** — `references/transaction-patterns.md`: net-vs-gross
  splits, the three processor-fee patterns (including the monthly aggregate deducted from a single
  settlement), supplier debit balances and paying in credit, refunds and chargebacks, and
  part-payments. Each with its detection signature and the failure it causes.

## 6. Accruals, prepayments, and getting the period right

Accounts are prepared on the **accruals basis**: recognise income and expense in the period they
relate to, not when cash moved. (VAT may be on a *cash* basis if the company is on cash accounting —
these are different questions; see `uk-vat`.)

| Adjustment | Meaning | Entry |
|---|---|---|
| **Accrual** | Cost incurred, not yet invoiced | Dr Expense / Cr Accruals |
| **Prepayment** | Paid in advance of the period | Dr Prepayments / Cr Expense |
| **Deferred income** | Invoiced in advance of delivery | Dr Income / Cr Deferred income |
| **Depreciation** | Spreading an asset's cost | Dr Depreciation / Cr Accumulated depreciation |

**Reverse accruals and prepayments in the following period** or they double-count. A permanent
accrual that nobody reverses is one of the most common small-company errors.

## 7. Month-end close — a repeatable order

1. Ingest and post everything (`financial-document-ingestion`)
2. Reconcile every bank and card account to zero difference
3. Prove each control account (§3)
4. Clear clearing accounts; report anything left
5. Post accruals, prepayments, depreciation
6. Review suspense — it should be empty
7. Produce the **trial balance**; confirm it balances
8. Produce **P&L** and **balance sheet**; compare to prior period and explain the movements
9. Record what is unresolved, with its potential impact

**Step 9 is not optional.** A close that reports only what tidied up hides the part that matters.

## 8. Reading the statements

**Profit & loss** — performance over a period:
```
Turnover − Cost of sales = Gross profit
Gross profit − Overheads = Operating profit
Operating profit − Interest ± Other = Profit before tax
Profit before tax − Corporation tax = Profit after tax
```

**Balance sheet** — position at one instant:
```
Fixed assets + (Current assets − Current liabilities) − Long-term liabilities
  = Net assets
  = Capital and reserves
```

Sanity checks worth running every time: net assets equals capital and reserves · retained earnings
moved by exactly this period's profit after tax (plus any dividend) · debtors and creditors are
plausible against turnover · **no negative stock, and no bank balance that contradicts the statement**.

## 9. Anti-patterns

- **Plugging a difference to suspense** so the trial balance agrees.
- **Posting only the net marketplace payout** — understates turnover, costs and output VAT.
- **Never reversing an accrual or prepayment**, so the cost lands twice.
- **Reconciling to "close enough".** Zero or unreconciled; there is no third state.
- **Mixing the director's personal spending into overheads** instead of the director's loan account.
- **A chart of accounts nobody can hold in their head** — mis-posting follows.
- **Not splitting sales by VAT treatment**, forcing a re-analysis at every return.
- **Calling the books done while a clearing account still holds a residual.**
