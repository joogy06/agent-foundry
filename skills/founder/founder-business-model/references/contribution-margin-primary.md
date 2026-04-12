# Contribution Margin as Primary Primitive (Pre-Product)

Why contribution margin is the primary business model primitive at pre-product stage, not
LTV/CAC. This reference explains the reasoning behind HR-BM6 and provides the formulas.

---

## The Problem with LTV/CAC Pre-Product

LTV (Lifetime Value) requires:
- Monthly churn rate (requires months of retention data)
- Revenue per customer per period (requires real pricing validation)
- Gross margin (requires real cost data)

CAC (Customer Acquisition Cost) requires:
- Actual ad spend or sales cost data
- Actual customer count from that spend
- Time period for attribution

**Pre-product, the founder has NONE of these.** Computing LTV/CAC pre-product means:
- Churn is assumed or benchmarked (not observed)
- Revenue is a target price (not validated)
- CAC is a guess (no ad spend data)

The result: a precisely-calculated ratio built entirely on assumptions. It looks rigorous
but is fiction.

---

## Why Contribution Margin Works Pre-Product

Contribution Margin = Price - Variable Cost per Unit

Pre-product, the founder CAN reason about:
- **Price:** they have a target price (from competitive research, customer conversations)
- **Variable cost:** they can estimate hosting, API costs, support time per customer

This gives a contribution margin that is:
- Directionally correct (even if imprecise)
- Actionable (tells them if the price covers costs)
- Testable (they can validate price with real customers via `founder-validation`)

---

## The Pre-Product Primitive Stack

At pre-product stage, use these primitives in order of reliability:

1. **Contribution Margin** = Price - COGS per unit
   - Can be estimated from target price + known costs
   - Primary go/no-go signal: is CM positive?

2. **Pricing Sensitivity** = how does CM change if price moves +-20%?
   - Testable via `pricing_explorer` mode
   - Tells the founder how much pricing flexibility they have

3. **Payback Intuition** = CAC / Contribution Margin (months)
   - Even with assumed CAC, tells the founder the order of magnitude
   - "If CAC is $200 and CM is $25/mo, payback is 8 months — can you fund 8 months of growth?"

4. **"What Must Be True"** = reverse-engineering from target outcome
   - Given a target MRR, what churn ceiling + conversion rate + traffic are needed?
   - Surfaces the most fragile assumptions

5. **LTV/CAC Ratio** (computed with heavy caveats)
   - Only when churn is known (observed) or when showing scenarios
   - Always tagged with input provenance
   - Never treated as reliable pre-product

---

## Formulas

### Contribution Margin
```
CM = Price - COGS_per_unit
CM_monthly = CM (if subscription monthly)
CM_monthly = CM / 12 (if subscription annual)
CM_monthly = CM * usage_per_month (if usage-based)
```

### Customer Lifetime (when churn is known)
```
Lifetime_months = 1 / monthly_churn_rate
Example: 5% monthly churn → 1/0.05 = 20 months
```

### LTV (when churn is known)
```
LTV = CM_monthly * Lifetime_months
   = CM_monthly / monthly_churn_rate
```

### CAC
```
CAC = total_acquisition_spend / customers_acquired
```

### Payback Period
```
Payback_months = CAC / CM_monthly
```

### LTV:CAC Ratio
```
LTV_CAC = LTV / CAC
```

### Break-Even Customers
```
Break_even = Fixed_costs / CM_monthly
```

---

## Transition to Post-Product Metrics

Once the founder has real data (post-launch), the primitives shift:

| Stage | Primary metrics | Data source |
|---|---|---|
| Pre-product | CM, pricing sensitivity, payback intuition | Estimates, validation interviews |
| Post-MVP (1-3 months) | CM (observed), early churn, CAC from first channel | Real data, small sample |
| Post-traction (3-6 months) | LTV/CAC (observed), cohort retention, unit economics | Enough data for cohort analysis |
| Growth (6+ months) | Full unit economics, CAC by channel, payback by cohort | Statistical significance |

At each stage, tag the metrics with the data quality:
- Pre-product: `assumed` / `target`
- Post-MVP: `observed (small sample, low confidence)`
- Post-traction: `observed (adequate sample, medium confidence)`
- Growth: `observed (high confidence)`
