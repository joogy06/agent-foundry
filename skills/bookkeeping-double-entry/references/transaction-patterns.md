# Awkward transaction patterns — splits, fees, credits

The shapes that break naive bookkeeping. Each entry gives the **signature** (how you recognise it),
the **correct posting**, and the **failure** it produces when posted at face value.

The single idea underneath all of them: **a bank line is a net cash movement, not a transaction.**
One line is often several postings, and the difference between "what hit the bank" and "what
happened commercially" is where the errors live.

---

## 1. Split transactions — one bank line, several postings

### Shape A — gross in, fee out separately
```
Bank +£1,000.00   Dr Bank            1,000.00
                      Cr Sales                833.33
                      Cr VAT control          166.67
Bank  −£25.00     Dr Merchant fees      25.00
                      Cr Bank                  25.00
```
The easy case: both sides are visible on the statement.

### Shape B — net in, fee never appears (the common one)
```
Bank +£975.00     Dr Bank              975.00
                  Dr Merchant fees      25.00     <-- NOT on the bank statement
                      Cr Sales                833.33
                      Cr VAT control          166.67
```

**The fee has to be created from the settlement report — the bank never shows it.**

**Failure if posted at face value:** sales recorded as £975 instead of £1,000. Turnover understated,
costs understated, and **output VAT understated by the VAT on £25** — an error with penalty exposure.
It also compounds: every settlement is slightly wrong, so the difference grows and never resolves to
a single findable transaction.

**Signature:** turnover per the books is consistently a few percent below the platform's own sales
report, and the gap scales with volume rather than being a fixed amount.

---

## 2. Processor fee patterns — three shapes, very different problems

### (a) Per-transaction deduction (Stripe, PayPal typical)
Each payout is already net. Post per Shape B, using the settlement report for the fee.
**Reconciles cleanly once you gross up.**

### (b) Monthly aggregate deducted from ONE settlement (the Worldpay pattern)

**This is the one that produces a single inexplicable transaction.** Settlements arrive at or near
gross all month, then on one day the processor takes the entire month's fees out of a single
settlement. That one payout is short by an amount that has nothing to do with the sales it contains.

```
Normal day    Bank +£1,000.00   -> sales £1,000.00
Fee day       Bank   +£640.00   -> sales £1,000.00, fees £360.00 (the WHOLE month)
```

**Failure if posted at face value:** that day's sales are recorded as £640. Turnover understated by
£360, the month's fees never recorded as a cost at all, and output VAT understated. Worse, it looks
like a *one-off* error of a strange amount, so it gets written off to suspense or "bank charges"
rather than recognised as the month's fees.

**Signature — and it is distinctive:**
- Exactly **one settlement per month** fails to match its expected batch total.
- The shortfall is **much larger** than any single transaction's fee.
- The shortfall **≈ the month's total fees** on the processor statement.
- Same calendar point each month (month end, or a fixed billing date).

**Correct posting:** gross the settlement up to the true sales figure and post the fee deduction as
its own expense line, dated to the fee period it covers — not spread across the day's transactions.

```
Dr Bank             640.00
Dr Merchant fees    360.00
    Cr Sales                 833.33   (per the settlement's own sales total)
    Cr VAT control           166.67
```

**Check the fee's own VAT treatment.** Merchant-service fees are often **exempt** rather than
standard-rated — do not assume a 1/6 VAT element. Take it from the processor's invoice, and if the
fee is exempt it may affect partial exemption (`uk-vat` §4).

### (c) Invoiced separately, paid by separate debit
Cleanest. Post the fee invoice as a normal purchase; the settlement is gross.

**Whichever shape applies, everything runs through a clearing account** so the processor's balance
is provable: gross sales in, fees out, payouts out, residual = money the processor still holds.
**A processor clearing account that will not clear to the processor's own reported balance is a
finding**, not a rounding issue.

---

## 3. Paying a vendor in credit — supplier debit balances

A creditor account that is **debit** means the supplier owes *you*. Legitimate, and routinely
mis-posted.

| Situation | Posting | Watch |
|---|---|---|
| **Prepayment / deposit** | Dr Trade creditors (or Prepayments) / Cr Bank | Sitting in creditors it *reduces* the creditors total, understating what you owe others |
| **Overpayment** | Dr Trade creditors / Cr Bank; sits as a debit until used or refunded | Chase it — small overpayments are quietly forgotten |
| **Credit note received** | Dr Trade creditors / Cr Purchases (**and reverse the input VAT**) | Forgetting the VAT reversal leaves an over-claim |
| **Payment on account** | Dr Trade creditors / Cr Bank, unallocated | **Allocate it** to the invoice when it arrives, or the aged list shows both an open invoice and an open credit |
| **Refund from supplier** | Dr Bank / Cr Trade creditors | Not income — it reverses a cost |

**The failure it causes:** trade creditors nets debit and credit balances together, so the control
account still agrees while the **aged creditors list is wrong in both directions**. You appear to owe
less than you do, and the supplier appears settled when they are holding your money.

**Rule: report supplier debit balances separately** at period end. In statutory accounts a material
supplier debit balance belongs in **debtors**, not as a reduction of creditors — netting them
overstates neither total but misstates both.

**A supplier refund is never income.** Posting it to sales inflates turnover and, for a
VAT-registered company, creates output VAT on money that was never a sale.

---

## 4. Refunds, part-refunds and chargebacks

| | Posting | Failure if wrong |
|---|---|---|
| **Customer refund** | Dr Sales / Dr VAT control / Cr Bank | Posted as an expense: turnover *and* costs both overstated, VAT misstated |
| **Partial refund** | Same, for the part only | Refunding the whole line leaves the sale understated |
| **Chargeback** | Reverse the sale; post any chargeback fee as a cost | Treating it as a cost leaves phantom turnover |
| **Refund crossing a VAT period** | Adjust in the period the refund occurs | Backdating changes a filed return (`uk-vat` §6) |

**A refund is negative income, not a cost.** This is the single most repeated mis-posting in
e-commerce books, and it inflates both turnover and expenses simultaneously — which is why it
survives a profit check that only looks at the bottom line.

---

## 5. Part-payments and payments on account

- **Part-payment of an invoice:** allocate against that invoice. Leaving it unallocated shows the
  invoice fully open and a floating credit — the aged list is then wrong twice.
- **One payment covering several invoices:** split the allocation. Do not post it as a lump against
  the oldest.
- **Payment before invoice:** payment on account, allocated when the invoice arrives.
- **Round-sum payments** against a supplier statement rather than invoices: allocate to specific
  invoices, or the account becomes impossible to reconcile.

**Unallocated cash is the commonest reason a debtors or creditors control agrees while the aged list
does not.** The total is right; the composition is wrong.

---

## 6. Detection summary

| Symptom | Likely pattern |
|---|---|
| Turnover consistently below the platform's sales report, gap scales with volume | §1 Shape B — net posted as gross |
| **One settlement a month** short by far more than a single fee | §2(b) — the monthly aggregate deduction |
| Processor clearing account will not clear | Fees or refunds missing from the clearing chain |
| Creditors control agrees, aged list does not | §5 unallocated cash, or §3 netted debit balances |
| Both turnover and costs look inflated | §4 refunds posted as expenses |
| Input VAT higher than purchases justify | §3 credit note posted without reversing the VAT |

Feed any unexplained amount to `ledger-error-diagnosis` — the difference's own arithmetic often names
the class before you open a single report.
