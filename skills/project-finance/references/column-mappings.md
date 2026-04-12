# Column Mapping Reference

Synonym dictionary, detection heuristics, and cache schema for the project-finance column mapping engine.

---

## Concept Synonym Dictionary

Each financial concept maps to a list of known column name synonyms. Matching is case-insensitive.

### Budget / Planned Value (PV)

```
Exact matches:
  Budget, Planned Cost, Allocated, PV, BAC, Plan, Planned Budget,
  Budgeted Amount, Original Budget, Approved Budget, Baseline Budget,
  Planned Value, BCWS, Budget at Completion, Total Budget,
  Allocated Budget, Planned Spend, Forecast Budget

Contains matches:
  *budget*, *planned*, *allocated*, *baseline*
```

### Actual Cost (AC)

```
Exact matches:
  Actual, Spend, Actual Cost, AC, Actual Spend, Expenditure,
  Cost to Date, Incurred, ACWP, Actual Expenditure, Real Cost,
  Spent, Total Spend, Cumulative Spend, YTD Spend, Costs Incurred,
  Actual to Date, Running Cost

Contains matches:
  *actual*, *spend*, *incurred*, *expenditure*, *cost_to_date*
```

### Earned Value (EV)

```
Exact matches:
  EV, Earned Value, BCWP, Completed Value, Work Performed,
  Value Earned, Earned, Progress Value

Contains matches:
  *earned*, *bcwp*, *completed_value*

Derived:
  If not found as a column, can be computed as: % Complete * Budget
  (flag this derivation to the user)
```

### Percent Complete

```
Exact matches:
  % Complete, Percent Complete, Completion, Progress, PCT Complete,
  Pct, Complete %, % Done, Progress %, Completion Rate

Contains matches:
  *complete*, *progress*, *pct*, *percent*

Note: Verify whether this is self-reported or based on deliverable inspection.
Include warning in output when EV is derived from % complete.
```

### Task / Activity / Category

```
Exact matches:
  Task, Activity, Work Package, WBS, Line Item, Cost Element,
  Category, Description, Item, Component, Deliverable, Phase,
  Work Stream, Sub-Project, Cost Category, Account, GL Code,
  Cost Center, Department

Contains matches:
  *task*, *activity*, *category*, *element*, *item*, *package*, *wbs*
```

### Period / Date

```
Exact matches:
  Date, Period, Month, Week, Sprint, Phase, Reporting Period,
  As Of, Report Date, Period End, Cut-Off Date, Snapshot Date,
  Fiscal Period, Calendar Month, Reporting Month, Pay Period,
  Time Period, Quarter, FY

Contains matches:
  *date*, *period*, *month*, *week*, *quarter*, *sprint*

Date format detection:
  - ISO: 2026-03-30
  - US: 03/30/2026 or Mar 30, 2026
  - UK: 30/03/2026 or 30 Mar 2026
  - Fiscal: FY26-Q1, P03-2026
  - Named: January, Jan, Q1, Sprint 5
```

### Forecast / Estimate at Completion

```
Exact matches:
  Forecast, EAC, Estimated Cost, Projected, Expected Final,
  Estimate at Completion, Revised Budget, Current Estimate,
  Latest Forecast, Forecast to Complete, FTC, Revised Estimate

Contains matches:
  *forecast*, *eac*, *estimated*, *projected*, *revised*
```

### Variance

```
Exact matches:
  Variance, Delta, Diff, Over/Under, Gap, Deviation,
  Budget Variance, Cost Variance, Schedule Variance,
  Favourable, Unfavourable, Over Budget, Under Budget

Contains matches:
  *variance*, *delta*, *diff*, *gap*, *deviation*

Note: If variance column exists in the source data, verify its sign
convention matches ours (Budget - Actual = positive means under budget).
```

### Owner / Resource

```
Exact matches:
  Owner, Resource, Assigned To, Team, Department, Cost Center,
  Manager, Responsible, Lead, PM, Project Manager, Resource Name

Contains matches:
  *owner*, *resource*, *assigned*, *team*, *department*, *manager*
```

---

## Three-Layer Resolution Algorithm

### Layer 1: Exact Match

1. Normalize the column name: lowercase, strip whitespace, remove underscores and hyphens
2. Compare against all synonyms (also normalized) in the dictionary above
3. If exactly one concept matches, confidence = HIGH
4. If multiple concepts match the same column, confidence = LOW (ambiguous)

### Layer 2: Fuzzy Match

Applied when Layer 1 produces no match:

1. **Contains match**: Check if the normalized column name contains any keyword from the concept dictionaries. Example: "Total_Budget_Amount" contains "budget" --> maps to Budget concept.
2. **Abbreviation expansion**: Expand known abbreviations (PV, AC, EV, BAC, EAC, ETC, SV, CV, CPI, SPI, TCPI, BCWS, BCWP, ACWP, CBS, WBS).
3. **Common prefix/suffix stripping**: Remove prefixes like "total_", "sum_", "cum_", "ytd_" and suffixes like "_amount", "_value", "_total", "_ytd", "_q1" through "_q4", "_jan" through "_dec".
4. **Partial match scoring**: If the stripped name matches a synonym, confidence = MEDIUM.
5. If multiple concepts match, confidence = LOW.

### Layer 3: User Confirmation

Applied when Layer 1 and Layer 2 produce LOW or NONE confidence:

1. Present all unmapped columns to the user
2. Show sample values (first 3 non-null values) to help the user identify the column
3. List the financial concepts still needing a column assignment
4. Ask the user to map each unmapped column or confirm it should be skipped
5. Cache the confirmed mapping for reuse

---

## Mapping Presentation Format

Always present mappings to the user in this format, regardless of confidence level:

```
## Column Mapping Results

| Your Column | Mapped To | Confidence | Sample Values |
|-------------|-----------|------------|---------------|
| Allocated Amount | Budget (PV) | HIGH | $500,000 / $1,200,000 / $300,000 |
| Spend to Date | Actual Cost (AC) | HIGH | $480,000 / $1,350,000 / $280,000 |
| Cost Element | Task/Category | HIGH | Infrastructure / Development / Testing |
| Reporting Month | Period/Date | HIGH | Jan-2026 / Feb-2026 / Mar-2026 |
| Proj_Est_Final | Forecast (EAC) | MEDIUM | $510,000 / $1,400,000 / $295,000 |
| Misc_Field_1 | ??? | NONE | ABC / DEF / GHI |

**Confirmed (HIGH):** 4 columns mapped automatically
**Needs confirmation (MEDIUM):** 1 column — please verify
**Needs your input (NONE):** 1 column — what does this represent?
```

---

## Cache Schema

Store confirmed mappings in `<project>/.project-finance/column-mappings.json`:

```json
{
  "version": 1,
  "mappings": [
    {
      "file_pattern": "monthly_budget_*.csv",
      "column_map": {
        "budget": "Allocated Amount",
        "actual": "Spend to Date",
        "task": "Cost Element",
        "period": "Reporting Month",
        "forecast": "Proj_Est_Final"
      },
      "skipped_columns": ["Misc_Field_1", "Internal_Ref"],
      "confirmed_by_user": true,
      "last_used": "2026-03-30",
      "notes": "Monthly budget report from SAP export"
    }
  ]
}
```

**Cache lookup logic:**
1. Check if `<project>/.project-finance/column-mappings.json` exists
2. Match current filename against stored `file_pattern` entries (glob match)
3. If match found, verify that the cached column names still exist in the file
4. If all columns present, offer to reuse: "Found a saved mapping for files matching this pattern. Reuse it?"
5. If some columns missing or new columns found, show the diff and ask user to update

---

## Special Cases

### Multi-Level Headers (Excel)

Some Excel files have merged cells creating multi-level headers (e.g., "Q1 2026" spanning Jan/Feb/Mar columns). Detection:
- Read with `header=[0,1]` to capture both rows
- If first header row has many empty cells between values, likely merged
- Offer to flatten: "Q1 2026 | January" becomes "Q1_2026_January"
- Or ask user which row is the real header

### Pivot Table Format

Some files have periods as columns instead of rows (wide format):

```
Task,     Jan-2026, Feb-2026, Mar-2026
Infra,    $50K,     $55K,     $60K
Dev,      $100K,    $110K,    $120K
```

Detection: column names look like date/period values.
Action: offer to unpivot (melt) into long format for analysis.

```python
df_long = df.melt(id_vars=['Task'], var_name='Period', value_name='Amount')
```

### Currency Symbol Handling

Strip currency symbols and thousand separators before numeric conversion:
- "$1,234.56" --> 1234.56
- "EUR 1.234,56" --> 1234.56 (European format)
- "1,234" --> 1234 (not 1.234)

Detect mixed currencies: if both "$" and "EUR" appear in the same column, flag for user resolution. Do not aggregate across currencies.
