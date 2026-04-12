# Earned Value Management (EVM) Formulas Reference

Complete EVM formula set with worked examples, interpretation tables, and division-by-zero guards.

---

## Core EVM Inputs

| Symbol | Name | Definition |
|--------|------|------------|
| **BAC** | Budget at Completion | Total approved budget for the project/work package |
| **PV** | Planned Value | Budgeted cost of work scheduled to be done by now (also BCWS) |
| **EV** | Earned Value | Budgeted cost of work actually performed by now (also BCWP) |
| **AC** | Actual Cost | Actual cost incurred for work performed by now (also ACWP) |

**Relationships:**
- At project start: PV = 0, EV = 0, AC = 0
- At project end (if on plan): PV = BAC, EV = BAC
- EV can be derived: EV = % Complete x BAC (verify % complete source)

---

## Variance Metrics

### Schedule Variance (SV)

```
SV = EV - PV
```

| SV Value | Interpretation |
|----------|---------------|
| SV > 0 | Ahead of schedule -- more work done than planned |
| SV = 0 | On schedule -- work matches plan |
| SV < 0 | Behind schedule -- less work done than planned |

**Note:** SV is in dollar terms. A $50K SV means $50K worth of work ahead/behind plan. At project completion, SV always equals zero (all work is done) regardless of whether it was late.

### Cost Variance (CV)

```
CV = EV - AC
```

| CV Value | Interpretation |
|----------|---------------|
| CV > 0 | Under budget -- work cost less than budgeted |
| CV = 0 | On budget -- actual cost matches earned value |
| CV < 0 | Over budget -- work cost more than budgeted |

**Note:** CV is in dollar terms. A -$100K CV means $100K over budget. Unlike SV, CV does NOT reset at project completion -- it reflects the permanent cost position.

---

## Performance Index Metrics

### Schedule Performance Index (SPI)

```
SPI = EV / PV

Guard: If PV = 0, report "N/A -- no planned value recorded yet (project may not have started)"
```

| SPI Value | Interpretation |
|-----------|---------------|
| SPI > 1.0 | Ahead of schedule -- delivering more work than planned |
| SPI = 1.0 | On schedule -- work progress matches plan |
| SPI < 1.0 | Behind schedule -- delivering less work than planned |

**Rule of thumb:** SPI of 0.85 means for every $1 of work planned, only $0.85 is being delivered. The project is 15% behind schedule.

### Cost Performance Index (CPI)

```
CPI = EV / AC

Guard: If AC = 0, report "N/A -- no actual cost recorded yet"
```

| CPI Value | Interpretation |
|-----------|---------------|
| CPI > 1.0 | Under budget -- getting more value per dollar than planned |
| CPI = 1.0 | On budget -- spending exactly as planned per unit of work |
| CPI < 1.0 | Over budget -- spending more per unit of work than planned |

**Rule of thumb:** CPI of 0.90 means for every $1 of value earned, $1.11 is being spent (1/0.90). The project will overrun by approximately 11% if the trend continues.

**Research finding:** CPI typically stabilizes after 20% of the project is complete. Once established, it rarely improves by more than 10%. This makes CPI a powerful early warning indicator.

---

## Forecasting Metrics

### Estimate at Completion (EAC) -- Four Variants

**EAC Variant 1: CPI-based (most common)**
```
EAC = BAC / CPI

Guard: If CPI = 0, report "N/A -- cannot forecast (CPI is zero)"
Use when: Past cost performance will continue for the rest of the project
```

**EAC Variant 2: No further variance**
```
EAC = AC + (BAC - EV)

Use when: Current variances are atypical and future work will proceed at the original rate
```

**EAC Variant 3: Combined CPI and SPI pressure**
```
EAC = AC + (BAC - EV) / (CPI * SPI)

Guard: If CPI * SPI = 0, report "N/A -- cannot forecast (CPI or SPI is zero)"
Use when: Both cost and schedule pressure will affect remaining work
```

**EAC Variant 4: Bottom-up re-estimate**
```
EAC = AC + bottom-up ETC

Use when: Original estimates are fundamentally flawed; fresh estimate of remaining work is needed
```

### Estimate to Complete (ETC)

```
ETC = EAC - AC
```

Represents how much more money is needed to finish the project.

### Variance at Completion (VAC)

```
VAC = BAC - EAC
```

| VAC Value | Interpretation |
|-----------|---------------|
| VAC > 0 | Expected to finish under budget |
| VAC = 0 | Expected to finish on budget |
| VAC < 0 | Expected to finish over budget |

### To-Complete Performance Index (TCPI)

**TCPI against original budget (BAC):**
```
TCPI_bac = (BAC - EV) / (BAC - AC)

Guard: If BAC = AC, report "N/A -- entire budget has been spent"
```

**TCPI against revised estimate (EAC):**
```
TCPI_eac = (BAC - EV) / (EAC - AC)

Guard: If EAC = AC, report "N/A -- revised estimate equals actual cost"
```

| TCPI Value | Interpretation |
|------------|---------------|
| TCPI > 1.0 | Must improve performance -- need better efficiency than historical to hit target |
| TCPI = 1.0 | Maintain current performance -- current rate is sufficient |
| TCPI < 1.0 | Can relax slightly -- budget cushion exists |
| TCPI > 1.3 | Almost certainly unachievable -- consider revising the target |

---

## Percent Complete Metrics

```
% Complete (planned) = PV / BAC * 100
% Complete (earned)  = EV / BAC * 100
% Spent              = AC / BAC * 100

Guard: If BAC = 0, report "N/A -- no budget defined"
```

These three percentages tell different stories:
- **Planned vs Earned gap** = schedule status
- **Earned vs Spent gap** = cost status
- **All three together** = full picture

---

## Worked Example

**Project Alpha -- Month 6 of 12**

| Input | Value |
|-------|-------|
| BAC | $1,200,000 |
| PV | $600,000 (50% of work should be done) |
| EV | $480,000 (40% of work is actually done) |
| AC | $550,000 (amount actually spent) |

**Calculations:**

```
Schedule:
  SV  = $480K - $600K = -$120,000  (behind schedule)
  SPI = $480K / $600K = 0.80       (20% behind schedule)

Cost:
  CV  = $480K - $550K = -$70,000   (over budget)
  CPI = $480K / $550K = 0.873      (13% over budget per unit of work)

Forecasts:
  EAC (CPI-based)  = $1.2M / 0.873    = $1,374,570  (will overrun by $174K)
  EAC (no variance) = $550K + ($1.2M - $480K) = $1,270,000  (will overrun by $70K)
  EAC (combined)    = $550K + ($1.2M - $480K) / (0.873 * 0.80) = $1,580,709  (worst case)

  ETC (CPI-based)  = $1,374,570 - $550K = $824,570  (still need to spend)
  VAC (CPI-based)  = $1.2M - $1,374,570 = -$174,570  (expected overrun)

To-Complete:
  TCPI_bac = ($1.2M - $480K) / ($1.2M - $550K) = $720K / $650K = 1.108
  → Must achieve 10.8% better efficiency than historical to meet original budget

Percent Complete:
  Planned: $600K / $1.2M = 50.0%
  Earned:  $480K / $1.2M = 40.0%  (10% behind plan)
  Spent:   $550K / $1.2M = 45.8%  (spending faster than earning)
```

**Interpretation for Project Alpha:**

> The project is **behind schedule** (SPI = 0.80, 20% less work done than planned) and **over budget** (CPI = 0.873, each dollar of work costs $1.15 instead of $1.00). If current trends continue, the project will cost approximately **$1.37M** against a **$1.2M budget** -- a **$175K overrun (14.5%)**. The team would need to improve efficiency by 11% for the remainder to bring costs back to the original budget, which is achievable but challenging. Recommend immediate review of high-cost work packages and schedule recovery options.

---

## Confidence Ranges for EAC

```
Optimistic EAC  = AC + (BAC - EV) / CPI_best
Most Likely EAC = BAC / CPI_cumulative
Pessimistic EAC = AC + (BAC - EV) / CPI_worst

Where:
  CPI_best  = highest CPI from any rolling 3-period window
  CPI_worst = lowest CPI from any rolling 3-period window
  CPI_cumulative = overall CPI from project start
```

This provides a **three-point estimate** for final project cost. Always present the range, not just a single number.

---

## Division-by-Zero Guard Summary

| Formula | Denominator | Guard Condition | Report |
|---------|-------------|-----------------|--------|
| SPI = EV/PV | PV | PV = 0 | "N/A -- no planned value recorded yet" |
| CPI = EV/AC | AC | AC = 0 | "N/A -- no actual cost recorded yet" |
| EAC = BAC/CPI | CPI | CPI = 0 | "N/A -- cannot forecast (CPI is zero)" |
| EAC = .../CPI*SPI | CPI*SPI | CPI*SPI = 0 | "N/A -- cannot forecast (insufficient data)" |
| TCPI_bac | BAC-AC | BAC = AC | "N/A -- entire budget has been spent" |
| TCPI_eac | EAC-AC | EAC = AC | "N/A -- revised estimate equals actual" |
| % Complete | BAC | BAC = 0 | "N/A -- no budget defined" |

---

## EVM Output Template

When presenting EVM results, use this structure:

```markdown
## Earned Value Analysis -- [Project Name] -- [Date]

### Key Inputs
| Metric | Value |
|--------|-------|
| BAC (Budget at Completion) | $X |
| PV (Planned Value to date) | $X |
| EV (Earned Value to date) | $X |
| AC (Actual Cost to date) | $X |

### Schedule Performance
| Metric | Value | Status |
|--------|-------|--------|
| SV (Schedule Variance) | $X | [Ahead/On/Behind] schedule |
| SPI (Schedule Performance Index) | X.XX | [interpretation] |

### Cost Performance
| Metric | Value | Status |
|--------|-------|--------|
| CV (Cost Variance) | $X | [Under/On/Over] budget |
| CPI (Cost Performance Index) | X.XX | [interpretation] |

### Forecasts
| Method | EAC | Overrun/Under | Confidence |
|--------|-----|---------------|------------|
| CPI-based | $X | $X (X%) | [note] |
| No further variance | $X | $X (X%) | [note] |
| Combined CPI*SPI | $X | $X (X%) | [note] |

ETC (Estimate to Complete): $X
VAC (Variance at Completion): $X
TCPI (To-Complete PI): X.XX -- [interpretation]

### Interpretation
[2-4 sentences in plain English explaining what these numbers mean
for the project, what risks they indicate, and what actions to consider]

### Assumptions
- [List any assumptions made about the input data]
- [Note if % complete is self-reported vs deliverable-based]
```
