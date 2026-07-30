---
name: uk-corporation-tax
description: Use when preparing or checking a UK Company Tax Return — the CT600, the tax computation that turns accounting profit into taxable profit, add-backs and disallowables, capital allowances including the annual investment allowance and full expensing, losses, associated companies and marginal relief, and the separate payment and filing deadlines. Covers what a small Ltd must hand to filing software.
disambiguation: Corporation tax and the CT600 specifically. The statutory accounts that accompany it are uk-statutory-accounts; VAT is uk-vat; the bookkeeping the computation starts from is bookkeeping-double-entry.
---

# UK corporation tax (CT600)

For a small Ltd. Rates, limits and the marginal-relief fraction are **not** repeated here — see
`accounting-uk-ltd/references/rates-2026-27.md`.

## 1. Two deadlines, and they are not the same date

| Obligation | When |
|---|---|
| **PAY** the corporation tax | **9 months + 1 day** after the end of the accounting period |
| **FILE** the CT600 | **12 months** after the end of the accounting period |

**Payment comes first, and by three months.** Filing on time while paying late still attracts
interest and penalties. This confusion is routine and expensive — state which one you mean.

**Filing route:** the joint HMRC/Companies House service closed 31 March 2026. A CT600 now goes
through **commercial software** (or an agent); paper only with a reasonable excuse or in Welsh.
**This skill prepares the figures; it cannot submit them.**

## 2. The computation — accounting profit is not taxable profit

```
Profit before tax (per the accounts)
  +  Add-backs: disallowable expenditure
  −  Capital allowances
  −  Losses brought forward / other reliefs
  =  Taxable total profits
  ×  Rate (with marginal relief if applicable)
  =  Corporation tax payable
```

**Never file the accounting profit as the taxable profit.** They differ by design, and the
computation is the document that shows how — HMRC, the user and any reviewing accountant all read it.

### Add-backs a small company actually hits

| Item | Treatment |
|---|---|
| **Depreciation** | **Always added back** — replaced by capital allowances |
| **Client entertaining** | Disallowed (staff entertaining within limits is different) |
| **Fines and penalties** | Disallowed |
| **General/unspecified provisions** | Disallowed; specific provisions may be allowed |
| **Capital items expensed in error** | Added back, then claim capital allowances instead |
| **Legal fees on capital transactions** | Capital, not revenue |
| **Non-business / private proportion** | Disallowed |
| **Gifts** (beyond a small branded limit) | Disallowed |

**Depreciation is the one that must never be missed.** It appears in every set of accounts and is
disallowed in every computation.

## 3. Capital allowances

Plant and machinery relief replaces depreciation for tax:

- **Annual Investment Allowance (AIA)** — 100% on qualifying plant and machinery up to the limit.
- **Full expensing** — 100% first-year relief for companies on qualifying *new* main-rate plant.
- **Writing down allowances** — main pool and special rate pool, for what does not qualify above.
- **Cars** are excluded from AIA and get emissions-based rates.
- **Structures and buildings** have their own separate allowance.
- **April 2027 adds two CT600 boxes** for a new 40% first-year allowance.

Check the current limits and rates in the rates reference — they move at fiscal events, and a stale
AIA limit produces a wrong return.

## 4. Marginal relief and associated companies — the small-company trap

Between the lower and upper limits, tax is charged at the main rate then reduced by marginal relief.

**The limits are divided by the number of associated companies**, and pro-rated for accounting
periods shorter than 12 months.

That division is the error worth checking first. A director with two companies has limits **halved**
in each — a company with £60,000 profit and one associate is over the halved £25,000 lower limit and
is not on the small profits rate at all. Ask about other companies under common control; do not
assume there are none.

## 5. Losses

- **Carried forward** against future profits (post-2017 losses are more flexible but restricted at
  higher levels).
- **Carried back** one year against the previous period's profits.
- **Group relief** if part of a group.

Losses are an asset. Track them explicitly, on the return and in the accounts, or they get lost.

## 6. What a filing package contains

1. **CT600** — the return form (currently CT600 (2026) Version 3)
2. **Tax computation** — accounting profit to tax payable, showing every adjustment
3. **Statutory accounts in iXBRL** — tagged, from `uk-statutory-accounts`

All three go to HMRC together. Companies House gets its own copy of the accounts, separately, on its
own deadline.

## 7. Before it goes anywhere

- Books reconciled and the trial balance agrees (`bookkeeping-double-entry`)
- Depreciation added back
- Capital additions reviewed for allowances rather than left as expenses
- Associated companies confirmed, limits divided
- Period length checked — short or long periods pro-rate, and a long period needs **two** returns
- Losses brought forward agreed to last year's return
- Tax charge in the accounts agrees the computation
- **A qualified accountant reviews it before submission** — particularly a first return, a loss
  claim, a scheme change, or anything with a disclosure

## 8. Anti-patterns

- **Confusing the payment date with the filing date.**
- **Filing accounting profit as taxable profit.**
- **Forgetting to add back depreciation.**
- **Ignoring associated companies** when applying the limits.
- **Expensing capital items** instead of claiming allowances.
- **Applying a rate to a period it does not cover** — straddling periods need apportionment.
- **Losing brought-forward losses** by not tracking them.
- **Claiming to have filed.** You cannot submit a CT600.
