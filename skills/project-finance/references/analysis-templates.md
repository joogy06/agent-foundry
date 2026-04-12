# Analysis Templates Reference

Complete templates for the five built-in analysis types: Budget vs Actual, Spend Trend, Cost Breakdown Structure, Financial Forecasting, and custom queries.

For EVM analysis, see `evm-formulas.md`.

---

## 1. Budget vs Actual Analysis

### Required Columns

| Concept | Required? | Notes |
|---------|-----------|-------|
| Budget | Yes | Planned/approved budget amount |
| Actual | Yes | Actual spend to date |
| Category/Task | Recommended | Grouping dimension (e.g., work package, department) |
| Period | Optional | For time-series variance tracking |

### Calculations

```python
import pandas as pd

def budget_vs_actual(df, budget_col, actual_col, group_col=None):
    """Compute budget vs actual variance analysis."""

    if group_col:
        result = df.groupby(group_col).agg({
            budget_col: 'sum',
            actual_col: 'sum'
        }).reset_index()
    else:
        result = pd.DataFrame({
            budget_col: [df[budget_col].sum()],
            actual_col: [df[actual_col].sum()]
        })

    result['Variance'] = result[budget_col] - result[actual_col]
    result['Variance_Pct'] = (result['Variance'] / result[budget_col] * 100).round(1)
    result['Status'] = result['Variance_Pct'].apply(classify_variance)

    # Add totals row
    totals = result[[budget_col, actual_col, 'Variance']].sum()
    totals['Variance_Pct'] = round(totals['Variance'] / totals[budget_col] * 100, 1)
    totals['Status'] = classify_variance(totals['Variance_Pct'])
    if group_col:
        totals[group_col] = 'TOTAL'
    result = pd.concat([result, pd.DataFrame([totals])], ignore_index=True)

    return result
```

### RAG Status Thresholds (Configurable)

| Variance % | Status | Indicator |
|------------|--------|-----------|
| > +10% | Significantly under budget | Blue |
| +2% to +10% | Under budget | Green |
| -2% to +2% | On budget | Grey |
| -2% to -10% | Over budget | Amber |
| < -10% | Significantly over budget | Red |

```python
def classify_variance(variance_pct):
    """Classify budget variance into RAG status."""
    if variance_pct > 10:
        return "Significantly under budget"
    elif variance_pct > 2:
        return "Under budget"
    elif variance_pct >= -2:
        return "On budget"
    elif variance_pct >= -10:
        return "Over budget"
    else:
        return "Significantly over budget"
```

### Output Template

```markdown
## Budget vs Actual Analysis -- [Project Name] -- [Period]

| Category | Budget | Actual | Variance ($) | Variance (%) | Status |
|----------|--------|--------|-------------|-------------|--------|
| [cat1] | $X | $X | +/-$X | +/-X.X% | [status] |
| [cat2] | $X | $X | +/-$X | +/-X.X% | [status] |
| **TOTAL** | **$X** | **$X** | **+/-$X** | **+/-X.X%** | **[status]** |

### Key Observations
- [Top overspend category and magnitude]
- [Top underspend category and magnitude]
- [Overall budget position and trend]

### Assumptions
- [Currency, time period, data source]
- [Any data quality issues noted]
```

---

## 2. Spend Trend Analysis

### Required Columns

| Concept | Required? | Notes |
|---------|-----------|-------|
| Actual Cost | Yes | Spend amount per period |
| Period/Date | Yes | Time dimension for trending |
| Budget (cumulative) | Recommended | For S-curve comparison |

### Calculations

```python
import numpy as np

def spend_trend(df, actual_col, period_col, budget_col=None, total_budget=None):
    """Compute spend trend metrics."""

    # Sort by period
    df = df.sort_values(period_col)

    # Period-level spend
    periodic_spend = df[actual_col].values
    cumulative_spend = np.cumsum(periodic_spend)

    # Burn rate
    n_periods = len(periodic_spend)
    avg_burn_rate = cumulative_spend[-1] / n_periods

    # Burn rate trend (linear regression on periodic spend)
    x = np.arange(n_periods)
    if n_periods >= 2:
        slope, intercept = np.polyfit(x, periodic_spend, 1)
        if slope > 0.05 * avg_burn_rate:
            trend = "Accelerating"
        elif slope < -0.05 * avg_burn_rate:
            trend = "Decelerating"
        else:
            trend = "Stable"
    else:
        slope, trend = 0, "Insufficient data"

    # Projected total and runway
    result = {
        "periods_elapsed": n_periods,
        "total_spend_to_date": float(cumulative_spend[-1]),
        "avg_burn_rate": float(avg_burn_rate),
        "burn_rate_trend": trend,
        "burn_rate_slope": float(slope),
        "periodic_spend": periodic_spend.tolist(),
        "cumulative_spend": cumulative_spend.tolist(),
    }

    if total_budget:
        remaining_budget = total_budget - cumulative_spend[-1]
        if avg_burn_rate > 0:
            periods_remaining = remaining_budget / avg_burn_rate
            result["remaining_budget"] = float(remaining_budget)
            result["periods_until_exhaustion"] = round(float(periods_remaining), 1)
            result["projected_total_at_current_rate"] = None  # Needs total_periods
        else:
            result["periods_until_exhaustion"] = "N/A -- no spend recorded"

    return result
```

### Output Template

```markdown
## Spend Trend Analysis -- [Project Name]

### Summary
| Metric | Value |
|--------|-------|
| Periods elapsed | X |
| Total spend to date | $X |
| Average burn rate | $X per [period] |
| Burn rate trend | Accelerating / Stable / Decelerating |
| Remaining budget | $X |
| Periods until exhaustion | X.X [periods] at current rate |

### Period-by-Period Spend
| Period | Spend | Cumulative | Cumulative Budget (Plan) |
|--------|-------|------------|--------------------------|
| [p1] | $X | $X | $X |
| [p2] | $X | $X | $X |

### Interpretation
- [Burn rate trend observation]
- [Budget exhaustion risk assessment]
- [Comparison to planned spend curve if available]

### Confidence
[LOW/MEDIUM/HIGH] -- based on [N] data points
[If LOW: "Trend analysis based on fewer than 3 periods. Treat as indicative only."]
```

---

## 3. Cost Breakdown Structure (CBS)

### Required Columns

| Concept | Required? | Notes |
|---------|-----------|-------|
| Cost Amount | Yes | Dollar value |
| Category | Yes | At least one grouping dimension |
| Sub-Category | Optional | For hierarchical breakdown |
| Period | Optional | For cross-period comparison |

### Calculations

```python
def cost_breakdown(df, amount_col, category_cols, top_n=10):
    """Compute hierarchical cost breakdown with percentages."""

    # Single-level breakdown
    if len(category_cols) == 1:
        breakdown = df.groupby(category_cols[0])[amount_col].sum()
        breakdown = breakdown.sort_values(ascending=False)
        total = breakdown.sum()
        result = pd.DataFrame({
            'Category': breakdown.index,
            'Amount': breakdown.values,
            'Pct_of_Total': (breakdown.values / total * 100).round(1),
            'Cumulative_Pct': (np.cumsum(breakdown.values) / total * 100).round(1)
        })
        return result

    # Multi-level breakdown
    breakdown = df.groupby(category_cols)[amount_col].sum()
    breakdown = breakdown.sort_values(ascending=False)
    total = breakdown.sum()
    # Return with hierarchy preserved
    result = breakdown.reset_index()
    result['Pct_of_Total'] = (result[amount_col] / total * 100).round(1)
    return result
```

### Output Template

```markdown
## Cost Breakdown Structure -- [Project Name]

### Total Cost: $X

| Rank | Category | Amount | % of Total | Cumulative % |
|------|----------|--------|------------|--------------|
| 1 | [cat1] | $X | X.X% | X.X% |
| 2 | [cat2] | $X | X.X% | X.X% |
| ... | | | | |

### Top Cost Drivers
The top [N] categories account for [X]% of total spend:
1. **[Category]** ($X, X.X%) -- [brief note on what this covers]
2. **[Category]** ($X, X.X%) -- [brief note]
3. **[Category]** ($X, X.X%) -- [brief note]

### Observations
- [Concentration risk: if top 3 categories > 80% of spend]
- [Unexpected categories or proportions]
- [Comparison to plan/benchmark if available]
```

---

## 4. Financial Forecasting

### Three Methods

#### Method 1: Trend-Based (Linear Regression)

```python
import numpy as np

def forecast_linear(actuals, total_periods):
    """Linear regression forecast from historical spend data."""
    n = len(actuals)
    if n < 2:
        return {"error": "Need at least 2 data points for trend-based forecast"}

    x = np.arange(n)
    coeffs = np.polyfit(x, actuals, 1)  # [slope, intercept]

    # Project remaining periods
    future_x = np.arange(n, total_periods)
    future_values = np.polyval(coeffs, future_x)

    # Ensure non-negative forecast values
    future_values = np.maximum(future_values, 0)

    eac = sum(actuals) + sum(future_values)

    # Confidence based on data points
    if n < 3:
        confidence = "LOW"
    elif n < 6:
        confidence = "MEDIUM"
    else:
        confidence = "HIGH"

    return {
        "method": "Trend-based (linear regression)",
        "burn_rate_per_period": float(coeffs[0]),
        "forecast_remaining": float(sum(future_values)),
        "eac": float(eac),
        "confidence": confidence,
        "data_points_used": n,
        "periods_remaining": total_periods - n,
        "caveat": "This is a projection based on historical trend, not a prediction. "
                  "Actual results may vary significantly."
    }
```

**Best when:** Spend pattern is relatively stable and predictable.

#### Method 2: EVM-Based

```python
def forecast_evm(bac, ev, ac, cpi, spi=None):
    """EVM-based forecast using CPI and optionally SPI."""

    results = {}

    # EAC variant 1: CPI-based
    if cpi and cpi != 0:
        results["eac_cpi"] = bac / cpi

    # EAC variant 2: No further variance
    results["eac_no_variance"] = ac + (bac - ev)

    # EAC variant 3: Combined
    if cpi and spi and (cpi * spi) != 0:
        results["eac_combined"] = ac + (bac - ev) / (cpi * spi)

    # Select primary forecast
    primary = results.get("eac_cpi", results["eac_no_variance"])
    results["primary_eac"] = primary
    results["etc"] = primary - ac
    results["vac"] = bac - primary
    results["method"] = "EVM-based"
    results["caveat"] = "EVM forecast assumes past performance patterns continue. " \
                        "Significant scope or team changes may invalidate this projection."

    return results
```

**Best when:** Project has active EVM tracking with reliable % complete data.

#### Method 3: Manual / Expert Judgment

```python
def forecast_manual(actuals_to_date, manual_forecast_remaining, bac):
    """Pass-through forecast with variance calculation."""
    eac = sum(actuals_to_date) + manual_forecast_remaining
    return {
        "method": "Manual (expert judgment)",
        "eac": eac,
        "etc": manual_forecast_remaining,
        "vac": bac - eac,
        "variance_pct": round((bac - eac) / bac * 100, 1) if bac else "N/A",
        "caveat": "Based on user-provided forecast. Verify assumptions and basis."
    }
```

**Best when:** Irregular spend pattern, major scope changes, or expert has better information than the trend.

### Forecast Output Template

```markdown
## Financial Forecast -- [Project Name]

### Forecast Summary
| Method | EAC | Variance to BAC | Confidence |
|--------|-----|-----------------|------------|
| Trend-based | $X | +/-$X (X.X%) | [LOW/MED/HIGH] |
| EVM (CPI-based) | $X | +/-$X (X.X%) | [note] |
| EVM (combined) | $X | +/-$X (X.X%) | [note] |

BAC (Original Budget): $X
ETC (Estimate to Complete): $X

### Confidence Range
| Scenario | EAC | Based On |
|----------|-----|----------|
| Optimistic | $X | Best 3-period CPI |
| Most Likely | $X | Cumulative CPI |
| Pessimistic | $X | Worst 3-period CPI |

> This is a projection based on historical data, not a prediction.
> Actual results may vary. Review assumptions before using for decisions.

### Assumptions
- [Data points used, periods covered]
- [Method selection rationale]
- [Known upcoming changes that could affect forecast]
```

---

## 5. Custom Query Support

When none of the standard analysis types fit, support ad-hoc queries:

### Supported Custom Operations

| Operation | Example Request | Implementation |
|-----------|----------------|----------------|
| Filter and aggregate | "Show spend by department for Q1 only" | `df.query()` + `groupby().sum()` |
| Top/bottom N | "Top 10 cost items" | `nlargest()` / `nsmallest()` |
| Period comparison | "Compare Q1 vs Q2 spend" | Pivot or side-by-side aggregation |
| Threshold detection | "Show items over $100K" | Boolean filter |
| Growth rate | "Month-over-month spend growth" | `pct_change()` |
| Running totals | "Cumulative spend over time" | `cumsum()` |

### Custom Query Output

Always format custom query results as a markdown table with:
- Clear column headers
- Sorted meaningfully (by amount, date, or category)
- Total row where applicable
- Interpretation paragraph explaining what the results show

---

## Bash Fallback for Basic CSV Analysis

When Python/pandas is unavailable, provide basic CSV analysis using bash:

```bash
# Budget vs Actual (simple sum comparison)
echo "Category,Budget,Actual,Variance"
awk -F',' 'NR>1 {
    budget[$3] += $4;
    actual[$3] += $5;
}
END {
    for (cat in budget) {
        var = budget[cat] - actual[cat];
        printf "%s,%.2f,%.2f,%.2f\n", cat, budget[cat], actual[cat], var
    }
}' data.csv | sort -t',' -k4 -n

# Total budget and actual
awk -F',' 'NR>1 {b+=$4; a+=$5} END {printf "Total Budget: %.2f\nTotal Actual: %.2f\nVariance: %.2f\n", b, a, b-a}' data.csv

# Spend by period
awk -F',' 'NR>1 {spend[$2] += $5} END {for (p in spend) printf "%s: %.2f\n", p, spend[p]}' data.csv | sort
```

Note: Bash fallback handles simple aggregations only. For EVM, forecasting, or chart generation, Python is required.

---

## Data Validation Checks

Run these before any analysis:

```python
def validate_financial_data(df, budget_col, actual_col, period_col=None):
    """Run standard validation checks on financial data."""
    issues = []

    # Null check
    for col in [budget_col, actual_col]:
        null_count = df[col].isnull().sum()
        if null_count > 0:
            issues.append(f"{col}: {null_count} null values ({null_count/len(df)*100:.1f}%)")

    # Duplicate check
    dup_count = df.duplicated().sum()
    if dup_count > 0:
        issues.append(f"{dup_count} duplicate rows detected")

    # Negative value check
    for col in [budget_col, actual_col]:
        neg_count = (df[col] < 0).sum()
        if neg_count > 0:
            issues.append(f"{col}: {neg_count} negative values (credits/adjustments?)")

    # Mixed currency detection (check for multiple symbols in string columns)
    # Run only on raw string data before numeric conversion

    # Date consistency (if period column exists)
    if period_col:
        try:
            pd.to_datetime(df[period_col])
        except Exception:
            issues.append(f"{period_col}: inconsistent date formats detected")

    return issues
```

Present all issues to the user before proceeding with analysis. Require explicit user decision for each issue.
