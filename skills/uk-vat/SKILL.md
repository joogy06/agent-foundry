---
name: uk-vat
description: Use when preparing or checking a UK VAT return — the nine boxes, choosing between standard accrual, cash accounting, flat rate and annual accounting schemes, Making Tax Digital digital-link requirements, what input VAT can and cannot be reclaimed, reverse charge, and correcting errors from an earlier period. Covers the VAT control account proof that must hold before any return is submitted.
disambiguation: UK VAT specifically — schemes, the nine boxes, MTD, error correction. The bookkeeping underneath (VAT control account, reconciliation) is bookkeeping-double-entry; corporation tax is uk-corporation-tax; extracting VAT figures from invoices is financial-document-ingestion.
---

# UK VAT

For a VAT-registered small Ltd. Rates and thresholds are **not** repeated here — see
`accounting-uk-ltd/references/rates-2026-27.md`.

## 1. Establish the scheme before touching a single box

**The scheme changes the arithmetic of every box.** Assuming standard accrual when the company is on
flat rate or cash accounting produces a wrong return that looks entirely normal.

| Scheme | Output VAT recognised | Input VAT reclaimed | Watch |
|---|---|---|---|
| **Standard (accrual)** | Invoice date / tax point | Invoice date | The default, not the certainty |
| **Cash accounting** | When customer **pays** | When you **pay** supplier | Debtors/creditors do not enter the return |
| **Flat rate** | Fixed % of **VAT-inclusive** turnover | **Not reclaimable** except capital assets over the set limit | The commonest source of badly wrong returns |
| **Annual accounting** | One return a year, interim payments on account | | Cash-flow shape differs |
| **Margin / retail schemes** | Special calculation | | Second-hand goods, retail mixes |

**Flat rate is the biggest trap.** The percentage applies to *gross* turnover, input VAT is generally
not recoverable, and a "limited cost business" test can force a higher percentage. A flat-rate return
prepared as if it were standard is wrong in both directions at once.

## 2. The nine boxes

| Box | Contents |
|---|---|
| **1** | VAT due on **sales and other outputs** |
| **2** | VAT due on **acquisitions from EU member states** (Northern Ireland protocol goods) |
| **3** | **Total VAT due** — box 1 + box 2 |
| **4** | VAT **reclaimed** on purchases and other inputs |
| **5** | **Net VAT** to pay or reclaim — the difference between 3 and 4 |
| **6** | Total value of **sales excluding VAT** |
| **7** | Total value of **purchases excluding VAT** |
| **8** | Total value of **goods supplied** to EU (NI protocol) |
| **9** | Total value of **goods acquired** from EU (NI protocol) |

Checks worth running every quarter:
- **Boxes 3 and 5 are computed, never typed.** 3 = 1 + 2; 5 = 3 − 4.
- **Box 6 excludes VAT.** Entering gross turnover here is a frequent and visible error.
- **Box 6 against the P&L turnover for the same period** — differences should be explainable
  (zero-rated, exempt, outside-scope income), not mysterious.
- **Box 1 ÷ box 6** should land near the standard rate for a wholly standard-rated business. A wildly
  different ratio is a signal to stop and investigate.

## 3. The VAT control account proof — do this before you submit

The books must agree with the return. Prove it:

```
VAT control account balance at period end
  =  Box 5 net VAT due for the period
  ±  amounts unpaid / unclaimed from prior periods
```

**If the control account does not prove, the return is not ready.** The difference is real — a
missing invoice, a mis-coded transaction, a duplicated entry — and submitting around it files a known
error. See `bookkeeping-double-entry` §3.

## 4. Input VAT — what cannot be reclaimed

Getting this wrong is the most common assessment on a small-company inspection.

- **No valid VAT invoice → no claim.** A bank statement line is not evidence. The invoice needs the
  supplier's VAT number and the VAT shown.
- **Business entertainment** — blocked.
- **Cars** — blocked, except genuinely 100% business use with no private availability (a very high
  bar). Commercial vehicles differ.
- **Private / personal use** — apportion honestly; a director's phone or home office is rarely 100%.
- **Exempt supplies** — input VAT attributable to exempt activity is not recoverable; partial
  exemption applies. If the company has any exempt income, get advice.
- **Pre-registration** — recoverable within limits (goods still held, services in a limited window).
- **Reverse charge** (most notably CIS construction, and many overseas services): the *customer*
  accounts for the VAT. Both an output and an input entry, often netting to nil, and both must appear.

## 5. Making Tax Digital

MTD applies to **all** VAT-registered businesses regardless of turnover.

- **Digital records** of every supply, kept in functional compatible software.
- **Digital links end to end** — from the record to the return. **A manual re-key between a
  spreadsheet and the portal breaks the digital link**, even if the number is right.
- Filing through **MTD-compatible software**.

**This skill cannot submit a return.** It prepares and proves the figures; the submission goes
through compatible software (see `accounting-uk-ltd` §1).

## 6. Correcting an error from an earlier period

Do not silently adjust the current return without checking which route applies.

- Below the threshold and not deliberate → generally adjust on the **next return**, and **keep a
  record of what was corrected and why**.
- Above the threshold, or deliberate, or HMRC has asked → **separate disclosure** to HMRC.
- **Deliberate errors are never corrected quietly on the next return.**

The record matters as much as the correction: an adjustment with no explanation is indistinguishable
from a new error.

## 6b. Mis-coded VAT — finding it before HMRC does

The commonest VAT error is not arithmetic, it is **coding**: the right amount recorded under the
wrong treatment. It never fails a control-account proof, because the money still balances.

| Mis-code | Signature | Effect |
|---|---|---|
| Standard-rated sale coded **zero-rated or no-VAT** | Box 1 ÷ box 6 well below the standard rate | Output VAT **understated** — the expensive direction |
| Zero-rated/exempt sale coded standard | Ratio above the standard rate | Output VAT overpaid |
| Purchase with **no valid VAT invoice** coded as reclaimable | Input VAT high relative to purchases | Over-claim, recoverable with penalties |
| **Exempt** purchase (many merchant fees, insurance, some finance) coded standard | Small persistent input-VAT excess | Over-claim |
| Gross posted as net | Difference divisible by 6 | Both boxes wrong |
| Reverse-charge item coded as a normal purchase | Boxes 1 and 4 both short by the same amount | Return understates both sides |

**The ratio test is the cheapest detection there is.** For a wholly standard-rated business, box 1 ÷
box 6 should sit near the standard rate. Materially off, and something is mis-coded — a two-second
check that catches a whole class of error before submission.

**Other quick sweeps:** list transactions coded no-VAT above a threshold and confirm each is genuinely
outside scope · check every supplier coded standard actually shows a VAT number and VAT amount ·
compare this quarter's VAT-code mix against last quarter's and explain any shift.

**Merchant-service and payment-processor fees are frequently exempt, not standard-rated.** Reclaiming
VAT on an exempt fee is an over-claim that recurs every month until someone checks the invoice.

Correcting a mis-code follows §6 — the route depends on size and whether the period is filed.

## 7. Working from incomplete records

A quarter with gaps still needs a return by the deadline. Prepare on what exists, and state the gap:

```
VAT RETURN (provisional) — Q ending 30 Jun 2026
  proved:      bank reconciled to zero; VAT control proves to box 5
  gap:         3 purchase invoices missing (~£340 input VAT, per supplier statements)
  effect:      box 4 understated; box 5 overstated — the return errs in HMRC's favour
  to resolve:  copies from the supplier; correct on the next return if outside the window
```

**Say which direction the error runs.** An understatement of a reclaim is a different risk from an
understatement of output VAT, and the user needs to know which one they are carrying.

## 8. Anti-patterns

- **Assuming the standard scheme.** Establish it first, every time.
- **Never running the box 1 ÷ box 6 ratio check** before submitting.
- **Reclaiming VAT on exempt merchant fees** because the amount looked standard-rated.
- **Preparing a flat-rate return as if standard** — wrong output *and* wrong input.
- **Putting VAT-inclusive turnover in box 6.**
- **Typing boxes 3 and 5** instead of computing them.
- **Submitting while the VAT control account does not prove.**
- **Reclaiming without a valid VAT invoice**, or on entertainment or cars.
- **Re-keying between spreadsheet and portal** — breaks the MTD digital link.
- **Quietly adjusting a large or deliberate error** on the next return.
- **Claiming to have filed the return.** You cannot.
