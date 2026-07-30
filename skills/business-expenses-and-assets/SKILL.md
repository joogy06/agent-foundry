---
name: business-expenses-and-assets
description: Use when deciding how to treat a business purchase — whether a laptop, phone, tool or piece of equipment is a capital asset or a revenue expense, how to depreciate it and over what life, how depreciation interacts with capital allowances for tax, how to apportion mixed business and private use, and how to handle consumables, subscriptions, low-value items and a capitalisation policy. Covers the categories a small company actually spends on and the ones that are commonly mis-posted.
disambiguation: The DECISION about how to treat a purchase — capital vs revenue, depreciation, private-use apportionment. Posting the resulting entries is bookkeeping-double-entry; claiming the tax relief on a CT600 is uk-corporation-tax; reclaiming the VAT is uk-vat; benefits-in-kind on assets made available to a director is uk-payroll.
---

# Business expenses and assets

The decision that gets made hundreds of times a year and is wrong often enough to matter: **is this
a cost, or is it a thing the company now owns?**

## 1. Capital or revenue — the question that decides everything else

| | **Capital** | **Revenue** |
|---|---|---|
| Test | Lasting benefit beyond this period | Consumed in the running of the business |
| Examples | Laptop, phone, drill, van, machinery, office fit-out | Paper, ink, fuel, rent, software subscription, repairs |
| In the accounts | **Balance sheet**, then depreciated | **P&L** immediately |
| For tax | **Capital allowances** | Deducted in the year |

**The practical test is durability, not price.** A £900 laptop lasting three years is capital. A
£900 stock of paper consumed this year is revenue. A £900 repair restoring something to working
order is revenue; a £900 upgrade making it materially better is capital.

**Repairs vs improvements** is the pair that catches people: replacing a broken part is a repair
(revenue); replacing the whole thing with something better is an improvement (capital).

### Set a capitalisation policy and write it down

Below a stated threshold, treat purchases as revenue regardless of durability. **£200–£500 is
typical for a small company.** A drill at £80 is not worth an asset register entry and a decade of
depreciation lines.

A policy only works if it is **consistent and recorded** — applied the same way every year, and
written down so the treatment can be explained later. Ad-hoc capitalisation of whatever happens to
feel large is what makes a fixed-asset register untrustworthy.

## 2. Depreciation — the accounting view

Depreciation spreads a capital asset's cost across the periods that benefit. **It is an accounting
estimate, and it is NOT the tax deduction** — see §3.

| Method | How | Use for |
|---|---|---|
| **Straight line** | Cost ÷ useful life, same each year | Most small-company assets — simple and defensible |
| **Reducing balance** | Fixed % of the written-down value | Assets losing value fastest early — vehicles |

Typical useful lives (a judgement, applied consistently, not a rule):

| Asset | Life |
|---|---|
| Laptop, phone, tablet | 2–3 years |
| Office furniture | 5–10 years |
| Tools and small equipment | 3–5 years |
| Vehicles | 4–5 years |
| Fit-out / leasehold improvements | Over the lease term |

**Residual value** is what it will be worth at the end. For a laptop, usually nil. Do not invent a
residual value to reduce the charge.

Entries: `Dr Depreciation (P&L) / Cr Accumulated depreciation (balance sheet)`. **Never credit the
asset account directly** — cost and accumulated depreciation are shown separately, and netting them
loses the asset's history.

**On disposal:** remove cost *and* accumulated depreciation, and put the difference against proceeds
as a profit or loss on disposal. An asset scrapped but left on the register overstates the balance
sheet indefinitely.

## 3. Depreciation is not the tax deduction — the point people miss

**Depreciation is added back in the corporation tax computation, every year, without exception.**
Tax relief comes instead through **capital allowances** (`uk-corporation-tax` §2–§3).

So for a laptop:

- **Accounts:** capitalise, depreciate over ~3 years, and add the depreciation back for tax.
- **Tax:** claim capital allowances — often **100% in year one** under the Annual Investment
  Allowance, or full expensing for qualifying new plant.

The two run on completely different timetables and that is normal. The consequence worth
understanding: **the tax relief is usually faster than the depreciation.** A company can have a
laptop still depreciating in year three whose full cost was relieved in year one.

Rates and limits are **not repeated here** — `accounting-uk-ltd/references/rates-2026-27.md`.

## 4. Mixed business and private use

A phone used for both, a laptop used at home, a car. **Apportion honestly and record the basis.**

- Claim only the business proportion, in the accounts, for VAT, and for capital allowances.
- **Record how the split was reached** — a call log, a mileage log, a stated percentage with a
  reason. "50%" with nothing behind it is the number an inspector asks about first.
- **VAT:** input VAT is recoverable only on the business proportion. Cars are effectively blocked
  entirely; commercial vehicles differ (`uk-vat` §4).
- **Assets made available to a director** for private use can create a **benefit in kind** — a
  P11D matter, not just an apportionment (`uk-payroll` §6).

**A rule cannot make this judgement**, which is why mixed-use purchases must never be auto-added by
a bank rule (`quickbooks-bookkeeping` §3).

## 5. The categories a small company actually spends on

| Category | Treatment | Watch |
|---|---|---|
| Consumables — paper, ink, cleaning | Revenue | Bulk buys spanning periods are a prepayment if material |
| Software subscriptions | Revenue | Annual licence paid up front spans periods — prepay it |
| Perpetual software licence | Often capital | Depends on term and substance |
| Tools and small equipment | Policy threshold decides | Be consistent |
| Repairs | Revenue | Improvement ≠ repair |
| Professional fees | Revenue — **unless** capital-related | Fees on buying an asset are capital |
| Entertaining clients | Revenue but **disallowed for tax**, VAT blocked | Staff entertaining differs |
| Staff costs | Revenue | Employer's NI and pension are company costs, not deductions |
| Motor | Depends on vehicle and use | Cars are treated very differently from vans |
| Home office | Apportioned | Use a defensible basis |
| Stock | **Neither** — it is an asset until sold | Not an expense on purchase |

**Stock is the one that is neither.** Buying stock is not a cost; it becomes cost of sales when sold.
Treating purchases as an expense with no stock adjustment misstates profit in both directions.

## 6. Keep a fixed-asset register

For every capital item: description, date acquired, cost, supplier, invoice reference, useful life,
method, depreciation to date, net book value, and disposal details when it goes.

Without it, depreciation becomes a guess, disposals never get removed, and the balance sheet slowly
fills with assets that no longer exist. It is also what a capital-allowances claim is built from —
`financial-document-ingestion` §6 stores the invoice; the register links it to the asset.

## 7. Anti-patterns

- **Expensing a capital item** — overstates costs now, loses the allowance claim, and is an add-back
  waiting to be found.
- **Capitalising consumables** to flatter profit.
- **Forgetting to add back depreciation** in the tax computation.
- **Assuming depreciation is the tax deduction.** It never is.
- **Claiming 100% on a mixed-use asset** without a basis.
- **Capitalising ad hoc**, with no written policy or threshold.
- **Leaving disposed assets on the register.**
- **Treating stock purchases as an expense.**
- **Netting depreciation against cost**, losing the asset's history.
- **Auto-categorising a mixed-use purchase by bank rule.**
