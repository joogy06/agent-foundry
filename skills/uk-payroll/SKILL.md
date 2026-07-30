---
name: uk-payroll
description: Use when running or checking payroll for a small UK limited company — PAYE and National Insurance, RTI Full Payment Submissions and Employer Payment Summaries, the Employment Allowance and its single-director restriction, director NI calculated on an annual basis, auto-enrolment pension duties, statutory pay, and year-end P60 and P11D obligations. Covers the wages control account proof that ties payroll to the books.
disambiguation: Running the payroll of a UK company — PAYE, NI, RTI, auto-enrolment. Posting the resulting journal and proving the wages control account is bookkeeping-double-entry; corporation tax relief on employment costs is uk-corporation-tax; personal tax planning for a director is outside this family.
---

# UK payroll — small Ltd

For a small company, typically with directors and a handful of employees. Rates and thresholds are
**not** repeated here — see `accounting-uk-ltd/references/rates-2026-27.md`.

## 1. RTI — the deadline that catches people

**An FPS must reach HMRC on or before every payday.** Not after. Late FPS filings trigger penalties,
and "we paid on time but filed the next day" is still late.

| Submission | When | Purpose |
|---|---|---|
| **FPS** (Full Payment Submission) | **On or before** each payday | Pay, tax, NI for every employee |
| **EPS** (Employer Payment Summary) | By the 19th of the following month | Reclaims (SMP etc.), Employment Allowance, nil-payment months |

**File an EPS for a nil-payment month.** Without it HMRC expects a payment that is not coming and
raises a specified charge.

**PAYE/NIC payment: the 22nd electronically.** The 19th is the *postal* deadline — using it for an
electronic payment date makes the payment late.

## 2. Directors' NI is not calculated like employees' NI

**Directors use an annual (cumulative) earnings period**, regardless of how often they are paid. An
employee's NI is worked out each pay period in isolation; a director's is worked out on cumulative
earnings for the year.

This matters practically: a director paid irregularly, or taking a large one-off payment, gets a very
different NI result from an employee on the same total. Payroll software has a specific director
setting — **if it is not switched on, the NI is wrong all year** and only surfaces at year end.

There is also an alternative method that smooths the deductions and trues up at year end. Either is
acceptable; **using neither, by treating a director as an ordinary employee, is not.**

## 3. Employment Allowance — and the single-director restriction

The Employment Allowance reduces employer's secondary Class 1 NIC liability, claimed via EPS.

**A company whose only employee paid above the secondary threshold is a single director cannot
claim.** This is the most common misclaim in small companies, it is recoverable by HMRC with
interest, and it is easy to trip into when a second employee leaves mid-year.

Check eligibility **at the point of claim and again when the workforce changes** — not once at
incorporation.

## 4. The payroll journal and the wages control proof

Every payroll run posts:

```
Dr  Gross wages (expense)
Dr  Employer's NI (expense)
Dr  Employer's pension (expense)
    Cr  Net pay              (bank, when paid)
    Cr  PAYE/NIC control     (HMRC, when paid)
    Cr  Pension control      (provider, when paid)
```

**The wages control account must clear to nil** once net pay, PAYE/NIC and pension have been paid.
A residual balance means something was not paid, was paid twice, or was posted wrong — see
`bookkeeping-double-entry` §3.

**Employer's NI and employer's pension are company costs**, not deductions from the employee. Posting
them as if deducted understates the true cost of employment and misstates the P&L.

## 5. Auto-enrolment

Every employer has duties. In outline: assess each worker at each pay period against the earnings
trigger and age criteria, enrol those who qualify, deduct and pay contributions on qualifying
earnings, allow opt-outs within the window and refund promptly, re-enrol roughly every three years,
and complete the declaration of compliance.

**Directors with no employment contract can be exempt** — but that is a specific test, not an
assumption, and a company with any non-director employee almost certainly has duties.

## 6. Year-end and statutory pay

| Obligation | Deadline |
|---|---|
| Final FPS/EPS for the tax year | By 19 April |
| **P60** to every employee employed at 5 April | **31 May** |
| **P11D / P11D(b)** for benefits in kind | **6 July** |
| **Class 1A NIC** on those benefits | **22 July** (electronic) |

Statutory pay to know exists and to check current rates for: SSP, SMP/SPP/ShPP/SAP, and statutory
redundancy. Some are recoverable via EPS — small employers can often reclaim a higher percentage of
statutory parental payments, which is money frequently left unclaimed.

Benefits in kind worth flagging in a small company: company cars, private medical, beneficial loans
(including an **overdrawn director's loan**), and assets made available for private use.

## 7. Before each run

- Starters have a P45 or starter declaration; leavers processed and given a P45
- Tax codes match the latest HMRC notices — not last year's
- **Director setting on** for directors
- National Living/Minimum Wage checked for anyone near it, **including after salary sacrifice**,
  which can push pay below the legal minimum
- Employment Allowance eligibility still true
- Auto-enrolment assessed this period
- FPS submitted **on or before** payday
- Journal posted; wages control proves to nil

## 8. Anti-patterns

- **Filing the FPS after payday.**
- **Not filing an EPS for a nil month** — HMRC raises a charge that was never due.
- **Paying PAYE by the 19th electronically** when the electronic deadline is the 22nd.
- **Treating a director as an ordinary employee for NI.**
- **Claiming the Employment Allowance as a single-director company.**
- **Leaving a residual in wages control** and calling payroll reconciled.
- **Posting employer's NI as an employee deduction.**
- **Ignoring NMW after salary sacrifice.**
- **Missing an overdrawn director's loan** as a benefit in kind.
