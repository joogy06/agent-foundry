# Scenario Tables

NxM matrix generation for `founder-business-model` scenario_table mode. Covers variable
selection, computation, and visual formatting with green/yellow/red zones.

---

## Table Structure

An NxM scenario table varies two inputs across their ranges while holding all other inputs
constant. The output is a matrix of a chosen metric at each combination.

```
              Col Variable →  val_1   val_2   val_3   val_4
Row Variable ↓
  val_A                      [cell]  [cell]  [cell]  [cell]
  val_B                      [cell]  [cell]  [cell]  [cell]
  val_C                      [cell]  [cell]  [cell]  [cell]
  val_D                      [cell]  [cell]  [cell]  [cell]
```

Each cell contains the output metric value and a color code.

---

## Variable Selection

### Good Combinations (high information value)

| Row variable | Column variable | Output metric | When to use |
|---|---|---|---|
| monthly_churn | price | ltv_cac_ratio | Exploring price-churn trade-off |
| cac | price | payback_months | Exploring acquisition cost vs price |
| monthly_churn | cac | ltv_cac_ratio | Exploring retention vs acquisition cost |
| price | cogs_per_unit | contribution_margin | Exploring price vs cost structure |
| conversion_rate | traffic | customers_per_month | Exploring growth assumptions |

### Bad Combinations (low information value)

- Same variable on both axes (degenerate — shows a line, not a matrix)
- Two variables that don't interact (e.g., geography and pricing_model)
- Variables where the user has observed data for both (no uncertainty to explore)

### Auto-Selection

If the user doesn't specify variables, select the two inputs with:
1. The highest downstream sensitivity (from sensitivity analysis)
2. The most uncertain tags (unknown > assumed > target > observed)

---

## Color Coding

Against the user's decision rule:

| Color | Meaning | Criteria |
|---|---|---|
| GREEN | Meets decision rule | metric >= threshold |
| YELLOW | Within 20% of threshold | threshold * 0.8 <= metric < threshold |
| RED | Below threshold | metric < threshold * 0.8 |

For metrics where lower is better (e.g., payback_months):
| Color | Meaning | Criteria |
|---|---|---|
| GREEN | Meets decision rule | metric <= threshold |
| YELLOW | Within 20% of threshold | threshold < metric <= threshold * 1.2 |
| RED | Above threshold | metric > threshold * 1.2 |

---

## Visual Formatting

### Markdown Table (default output)

```markdown
| | Price $19 | Price $29 | Price $39 | Price $49 |
|---|---|---|---|---|
| **Churn 2%** | **4.2** | **6.3** | **8.5** | **10.6** |
| **Churn 3%** | *2.8* | **4.2** | **5.6** | **7.1** |
| **Churn 5%** | ~~1.7~~ | *2.5* | **3.4** | **4.2** |
| **Churn 8%** | ~~1.1~~ | ~~1.6~~ | *2.1* | *2.7* |
| **Churn 10%** | ~~0.8~~ | ~~1.3~~ | ~~1.7~~ | *2.1* |
```

Convention: **bold** = GREEN, *italic* = YELLOW, ~~strikethrough~~ = RED

### Insight Summary

Below the table, always add:
1. The boundary line: "You need churn below X% at price $Y to meet your rule"
2. The fragile variable: "Churn is the bigger lever — a 2% change in churn matters more than $10 in price"
3. The safe zone: "At $39+ and churn 5% or below, you're safely in green territory"
4. The danger zone: "Below $29 with churn above 5%, the business model doesn't work"

---

## Computation

For each cell (row_i, col_j):

1. Take the base_inputs (all inputs held constant)
2. Replace row_variable with row_values[i]
3. Replace col_variable with col_values[j]
4. Compute output_metric using the standard formulas
5. Apply color coding against decision_rule

Total computations = len(row_values) * len(col_values)

---

## Default Value Ranges

If the user doesn't specify values:

| Variable | Default range |
|---|---|
| price | [base * 0.5, base * 0.75, base, base * 1.25, base * 1.5] |
| monthly_churn | [0.02, 0.03, 0.05, 0.08, 0.10] |
| cac | [base * 0.5, base * 0.75, base, base * 1.5, base * 2.0] |
| conversion_rate | [0.01, 0.02, 0.03, 0.05, 0.10] |
| cogs_per_unit | [base * 0.5, base * 0.75, base, base * 1.25, base * 1.5] |

Where `base` is the user's current value for that input.
