---
name: uk-statutory-accounts
description: Use when preparing year-end statutory accounts for a small UK limited company — choosing between FRS 105 micro-entity and FRS 102 Section 1A small-company frameworks, the profit and loss account and balance sheet formats, required notes and disclosures, directors' responsibilities, iXBRL tagging for HMRC, and filing with Companies House including what the public register shows.
disambiguation: The YEAR-END statutory accounts and the Companies House filing. The corporation tax computation and CT600 that accompany them is uk-corporation-tax; the underlying bookkeeping and trial balance is bookkeeping-double-entry; deadlines across all obligations are mapped in accounting-uk-ltd.
---

# UK statutory accounts — small Ltd

Turning a reconciled trial balance into accounts that satisfy Companies House and accompany the
CT600.

## 1. Choose the framework first — it changes the output

| | **FRS 105** (micro-entity) | **FRS 102 Section 1A** (small) |
|---|---|---|
| Thresholds | Meet 2 of 3 micro limits | Meet 2 of 3 small limits |
| Statements | P&L + balance sheet, highly abridged | P&L + balance sheet + notes |
| Notes | Minimal; footnotes on the balance sheet | Fuller disclosure required |
| Fair value / revaluation | **Not permitted** | Permitted |
| Deferred tax | **Not recognised** | Recognised |
| Effort | Lowest | Higher |

**FRS 105 is not automatically the right answer** just because it is the least work. It forbids
revaluation and deferred tax, which can misrepresent a company holding property or carrying material
timing differences. If the company has investment property, significant deferred tax, or wants
accounts a lender or buyer will take seriously, FRS 102 1A is usually better.

**Check the thresholds against the actual figures**, and remember they apply on a 2-of-3 basis over
consecutive periods.

## 2. Balance sheet format

```
FIXED ASSETS
  Intangible assets
  Tangible assets                    (cost − accumulated depreciation)
  Investments
CURRENT ASSETS
  Stock
  Debtors                            (trade + prepayments + other)
  Cash at bank and in hand
CREDITORS: amounts falling due within one year
  Trade creditors, accruals, VAT, PAYE/NIC, corporation tax, director's loan
NET CURRENT ASSETS / (LIABILITIES)
TOTAL ASSETS LESS CURRENT LIABILITIES
CREDITORS: amounts falling due after more than one year
NET ASSETS
                                      ═══════════
CAPITAL AND RESERVES
  Called up share capital
  Profit and loss account             (retained earnings)
SHAREHOLDERS' FUNDS                   (= NET ASSETS)
```

**Net assets must equal shareholders' funds.** If they do not, the accounts are wrong — do not
present them.

## 3. Profit and loss

```
Turnover
  − Cost of sales
= Gross profit
  − Administrative expenses
= Operating profit
  ± Interest / other income and charges
= Profit before taxation
  − Tax on profit
= Profit for the financial year
```

The tax line must **agree the corporation tax computation** (`uk-corporation-tax`). A tax charge that
does not tie to the computation is one of the two numbers a reviewer checks first.

## 4. Year-end checklist

1. **Reconcile everything** — bank, VAT control, PAYE/wages control, debtors, creditors
2. **Stock** counted and valued at the lower of cost and net realisable value
3. **Fixed assets** — additions capitalised, disposals removed, depreciation charged consistently
4. **Debtors** reviewed for bad debts; **creditors** for completeness (unrecorded liabilities are
   the classic year-end understatement)
5. **Accruals and prepayments** posted, and prior-year ones reversed
6. **Director's loan account** agreed and its sign checked — an **overdrawn** account has real tax
   consequences (s455 charge, and a benefit-in-kind on beneficial loan interest)
7. **Dividends** — legal only out of distributable reserves, with paperwork. An "dividend" paid from
   insufficient reserves is not a dividend; it is a loan, and taxed as such
8. **Corporation tax** computed and posted
9. **Comparatives** agree last year's filed accounts exactly
10. **Net assets = shareholders' funds**

Item 7 is worth stopping on: paying dividends out of reserves that do not exist is common in
owner-managed companies and is usually discovered a year later, when it is expensive to unwind.

## 5. Company size — which regime applies

For accounting periods beginning **on or after 6 April 2025**, meet at least **2 of 3**:

| | Turnover | Balance sheet total | Employees |
|---|---|---|---|
| **Micro-entity** | ≤ £1m | ≤ £500,000 | ≤ 10 |
| **Small** | ≤ £15m | ≤ £7.5m | ≤ 50 |

**Audit exemption** for a small company mirrors the small thresholds (≤ £15m / ≤ £7.5m / ≤ 50, 2 of 3).
Exemption is **not automatic in every case** — it is lost if the company is in an ineligible group or
regulated sector, or if members holding **10% or more** of shares demand an audit. When exemption is
taken, the balance sheet must carry the **directors' statement** claiming it.

## 6. Full vs filleted vs abridged — three different documents

This is the distinction that causes the most confusion, because "small accounts" means different
things to different recipients.

| | **Full accounts** | **Filleted accounts** | **Abridged accounts** |
|---|---|---|---|
| Contains | P&L + balance sheet + all notes + directors' report | Balance sheet + limited notes; **P&L and directors' report omitted** | Reduced detail *within* the primary statements |
| Goes to | **Members** and **HMRC** (with the CT600) | **Companies House** (public register) | Wherever prepared, if members consent |
| Requires member consent | No — it is their right | No | **Yes — all members must consent, every year** |

**The company prepares ONE set of full accounts.** Filleting is a choice about what subset is
*filed publicly*; it is not a different set of books, and it never reduces what members or HMRC
receive.

- **Members always get the full accounts.** Filing filleted accounts does not reduce that right.
- **HMRC always gets the full accounts** in iXBRL with the CT600. Sending HMRC the filleted version
  is a filing error.
- **Abridged is not the same as filleted** and needs unanimous member consent each year — which is
  why most small companies use filleting and not abridgement.

### This is changing — April 2028

From **1 April 2028**, under ECCTA:

- Small and micro-entity companies **must file a profit and loss account**.
- **Abridged accounts are abolished** — small companies will no longer be able to prepare or file them.
- Companies claiming **audit exemption must give an enhanced directors' statement** on the balance
  sheet naming **which exemption** is claimed and confirming the company qualifies.

**So filleting away the P&L is correct advice today and expires in April 2028.** When advising, say
both: what is permitted now, and what is coming. A client planning on permanent P&L privacy is
planning on something that ends.

## 7. What the public register shows

Accounts filed at Companies House are **public**. Today, a small company filing filleted accounts
publishes its balance sheet and limited notes but not its P&L — **from April 2028 the P&L will be
filed too**.

**Tell the user what will be visible.** Net assets, share capital and director's loan balances are on
a public record that customers, suppliers and competitors can read, and turnover and profit will join
them. That is not a reason to misstate anything — it is a reason not to be surprised.

## 8. Filing

| Destination | What | Route |
|---|---|---|
| **Companies House** | Statutory accounts | CH online service, third-party software, or **paper by post**. Software-only from **April 2028**. |
| **HMRC** | Same accounts in **iXBRL**, with CT600 + computation | **Commercial software** effectively mandatory since the joint service closed 31 March 2026 |

**The accounts go to both bodies, separately, on different deadlines, in different formats.** The
joint service that used to do both at once no longer exists.

**iXBRL** is machine-readable tagging of the accounts. It is produced by accounts-production
software — **this skill does not generate it**, and hand-tagging is not a realistic path.

Deadlines: **9 months** after the ARD (**21 months** from incorporation for a first period). The
confirmation statement is a **separate** annual filing on its own date — it is not part of the
accounts, and believing otherwise causes a late filing every year.

## 9. Directors' responsibilities — state them

The directors, not the preparer, are responsible for accounts giving a true and fair view, for
adequate accounting records, and for filing on time. Late filing brings automatic penalties that
escalate, and persistent default can lead to strike-off and disqualification.

**Recommend a qualified accountant reviews the first set of accounts**, any year with an unusual
transaction, and any year where the framework changes.

## 10. Anti-patterns

- **Choosing FRS 105 purely to save effort** where revaluation or deferred tax matters.
- **Presenting accounts where net assets ≠ shareholders' funds.**
- **A tax charge that does not agree the computation.**
- **Comparatives that do not match last year's filed accounts.**
- **Dividends from reserves that do not exist.**
- **Missing an overdrawn director's loan** and its s455 consequence.
- **Treating the confirmation statement as part of the accounts filing** — see
  `accounting-uk-ltd/references/confirmation-statement.md`.
- **Sending HMRC the filleted accounts.** HMRC gets the FULL accounts with the CT600.
- **Confusing abridged with filleted** — abridged needs unanimous member consent every year.
- **Promising permanent P&L privacy.** Filleting away the P&L ends in April 2028.
- **Assuming audit exemption is automatic** — an ineligible group, a regulated sector, or members
  holding 10%+ demanding an audit all remove it.
- **Assuming the old joint filing service still exists** — it closed 31 March 2026.
- **Claiming to produce iXBRL.** That comes from accounts-production software.
