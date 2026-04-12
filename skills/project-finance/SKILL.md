---
name: project-finance
description: >
  Use when analyzing project financial data — budget vs actual variance, Earned Value
  Management (EVM) metrics (CPI, SPI, EAC, ETC, TCPI), cost breakdown structures,
  spend trends, financial forecasting, or processing CSV/Excel files containing budget,
  cost, or spend data. Shared financial engine for project-manager and delivery-manager.
  Trigger on: budget, actual cost, variance, EVM, earned value, CPI, SPI, EAC, ETC,
  cost breakdown, spend analysis, burn rate, financial forecast, budget vs actual,
  project financials, analyze budget, analyze spend, cost tracking.
---

# Project Finance

Shared financial analysis engine for `project-manager` and `delivery-manager`. Handles data ingestion, column mapping, standard PM financial analyses, and multi-format output.

<HARD-RULE>
Never make autonomous decisions about scope, priorities, resource allocation, or risk responses.
Always present recommendations for user approval. Draft-and-confirm, not decide-and-act.
</HARD-RULE>

<HARD-RULE>
Always state assumptions explicitly. When input data is incomplete, list what's assumed and
what's missing. Never silently fill gaps.
</HARD-RULE>

<HARD-RULE>
Never present financial numbers without showing the calculation method and input data used.
Confidently wrong financial analysis is worse than no analysis.
</HARD-RULE>

<HARD-RULE>
Column mapping is NEVER silent. Even high-confidence exact matches are reported to the user.
Medium/low confidence requires explicit confirmation before proceeding.
</HARD-RULE>

<HARD-RULE>
Always run reconnaissance before analysis. Read file shape (rows, columns, headers, sample data)
before loading. Follows `large-file-analysis` Phase 0 pattern.
</HARD-RULE>

---

## When to Use / When Not

**Use this skill for:**
- Budget vs actual variance analysis
- Earned Value Management (EVM) metrics and interpretation
- Spend trend analysis, burn rate calculation, S-curve tracking
- Cost breakdown structures (CBS)
- Financial forecasting (trend-based, EVM-based, manual)
- Processing CSV/Excel files containing financial data
- Any request from `project-manager` or `delivery-manager` involving financial numbers

**Do NOT use for:**
- Live dashboards or real-time financial monitoring
- Accounting, invoicing, or payroll processing
- Tax calculations or regulatory financial reporting
- General data analysis unrelated to project financials (use `python-data-engineer`)

---

## Operating Mode: Draft-and-Confirm

Claude always produces analysis and artifacts. The user always reviews before acting on them.

- User provides a CSV/Excel file or describes their budget structure
- Skill runs recon, maps columns (with user confirmation), performs analysis
- Output: markdown report with tables, charts, and plain-English interpretation
- Always explains what each metric means and suggests actions to consider
- Always states assumptions and flags data quality issues

---

## Workflow

Follow this seven-step pipeline for every financial analysis request.

### Step 1: Intake

Receive the data source:
- File path (CSV, XLSX, XLS, TSV, JSON)
- Inline data pasted in chat
- Project data files from a known location

Detect file type by extension. If file exceeds 2000 rows, apply patterns from `large-file-analysis`.

### Step 2: Reconnaissance

Before loading the full file, examine its shape:

```bash
# Row and column count
wc -l /path/to/file.csv
head -5 /path/to/file.csv
tail -5 /path/to/file.csv
```

Report to the user:
- Row count, column count, file size
- Sample of first 5 and last 5 rows
- Detected delimiter, encoding, date formats
- Currency format detection ($, EUR, GBP, plain numbers)

### Step 3: Column Mapping

Map file columns to financial concepts using three-layer resolution. Read `references/column-mappings.md` for the synonym dictionary and detection heuristics.

**Confidence levels and actions:**

| Confidence | Action |
|------------|--------|
| HIGH (exact synonym match) | Apply mapping, inform user of all mappings made |
| MEDIUM (fuzzy match, single candidate) | Apply with warning, ask to confirm |
| LOW (multiple candidates or no match) | Present options, require user selection |
| NONE (no plausible match) | Ask user which column maps to which concept |

Check for a cached mapping file at `<project>/.project-finance/column-mappings.json`. If found and file pattern matches, offer to reuse. Always show the mapping to the user regardless of confidence.

### Step 4: Data Validation

Before calculating, run validation checks and report findings:
- Null/empty cell counts per column
- Duplicate row detection
- Mixed currency detection
- Date format consistency
- Negative values where positives expected
- Cumulative vs periodic data detection (monotonically increasing values suggest cumulative)

Present each issue found and require user decision on how to handle it (fill with zero, interpolate, exclude, keep as-is). Never silently resolve data quality issues.

### Step 5: Load and Prepare

Load data using pandas (or bash fallback for basic CSV):

```python
import pandas as pd

# File type detection
df = pd.read_csv(path)           # .csv
df = pd.read_excel(path)         # .xlsx (requires openpyxl)
df = pd.read_csv(path, sep='\t') # .tsv
```

Parse dates, convert currencies to numeric, handle encoding (try utf-8, then latin-1, then cp1252).

**Required Python libraries:**

| Library | Purpose | Required? |
|---------|---------|-----------|
| pandas | Core data manipulation | Yes |
| openpyxl | Read/write .xlsx | Yes (for Excel) |
| matplotlib | Chart generation | Recommended |
| numpy | Numerical calculations | Yes (for forecasting) |

Auto-detect availability and offer to install if missing. Never install without asking. Provide bash fallback for basic CSV analysis using awk/sort.

### Step 6: Analyze

Select analysis type based on available columns or user request. Read `references/analysis-templates.md` for template details and `references/evm-formulas.md` for EVM calculations.

**Analysis type routing:**

| Available Data | Suggested Analysis |
|---------------|--------------------|
| Budget + Actual columns | Budget vs Actual variance |
| EV + PV + AC + BAC columns | Full EVM analysis |
| Actual cost by period | Spend trend / burn rate |
| Cost data with categories | Cost Breakdown Structure |
| Historical actuals + total budget | Financial forecasting |

Auto-detect available analyses from mapped columns, present options, let user choose.

**Five built-in analysis types:**

1. **Budget vs Actual** -- variance in $ and %, RAG status thresholds (configurable)
2. **EVM** -- full suite: SV, SPI, CV, CPI, EAC (4 variants), ETC, VAC, TCPI (2 variants). All divisions guarded against zero. Read `references/evm-formulas.md` for formulas and interpretation.
3. **Spend Trend** -- S-curve, burn rate, burn rate trend, budget exhaustion projection
4. **Cost Breakdown Structure** -- hierarchical cost decomposition with % of total, top-N cost drivers
5. **Financial Forecasting** -- trend-based (linear regression), EVM-based (BAC/CPI), manual. Confidence tags: LOW (<3 data points), MEDIUM (3-5), HIGH (6+). Always include "projection, not prediction" caveat.

### Step 7: Output and Interpret

**Output formats:**

- **Markdown tables** (always produced) -- used in reports, status updates, chat responses
- **Charts** (if matplotlib available) -- read `references/chart-patterns.md` for standard financial charts. Create session temp dir: `PF_WORK=$(mktemp -d /tmp/pf-XXXXXXXXXX)`. Save to `${PF_WORK}/charts/`, or `<project>/.project-finance/charts/` if project context available
- **CSV export** (if requested) -- for users who want to take data into Excel
- **Slide-ready data** (if invoked via `presentation-builder` chain) -- follow `presentation-datavis` patterns

**Interpretation (always included):**
- Add plain-English interpretation of each metric
- Flag items needing attention (over budget, behind schedule, trend worsening)
- Suggest actions to consider based on metric values
- Present all as draft recommendations for user review

---

## Mapping Cache

Store confirmed column mappings for reuse:

```
<project>/.project-finance/
  column-mappings.json      # Cached mappings per file pattern
  charts/                   # Generated chart images
```

Cache schema:

```json
{
  "file_pattern": "monthly_budget_*.csv",
  "mappings": {
    "budget": "Allocated Amount",
    "actual": "Spend to Date",
    "task": "Cost Element",
    "period": "Reporting Month"
  },
  "confirmed_by_user": true,
  "last_used": "2026-03-30"
}
```

---

## Integration Points

- **project-manager** -- routes budget, variance, EVM, spend requests here. PM provides project context (name, period, governance level); this skill returns analysis, charts, interpretation.
- **delivery-manager** -- routes delivery cost analysis here. DM provides delivery context; this skill returns financial metrics.
- **presentation-builder** -- for chart generation in slide decks. Follow `presentation-datavis` patterns (insight titles, accent colors, source lines). Save to `.presentations/output/assets/`.
- **large-file-analysis** -- apply chunked reading patterns for files exceeding 2000 rows. Pre-process with bash to reduce dataset before pandas load.

---

## Anti-Patterns

| Anti-Pattern | Why It's Wrong | Do This Instead |
|-------------|----------------|-----------------|
| Loading file without recon | Wrong assumptions about structure, wasted effort | Always run Phase 0 reconnaissance first |
| Silent column mapping | User trusts wrong mapping, analysis is meaningless | Report ALL mappings, confirm medium/low confidence |
| Silently filling null values | Hides data quality issues, corrupts analysis | Report nulls, ask user how to handle each |
| Division by zero in EVM | Crash or misleading infinity values | Guard all divisions, report "N/A -- no data yet" |
| Forecast from <3 data points | Unreliable trend line presented as fact | Tag confidence as LOW, add explicit warning |
| Presenting numbers without method | User cannot verify or challenge results | Always show formula and input values used |
| Treating cumulative as periodic | Double-counting inflates totals | Detect monotonic increase, ask user to confirm |
| Ignoring mixed currencies | Meaningless aggregations across currencies | Detect multiple symbols, require user resolution |

---

## Reference Files

Read these on demand when performing specific analysis types:

- `~/.claude/skills/project-finance/references/column-mappings.md` -- synonym dictionary, detection heuristics, cache schema
- `~/.claude/skills/project-finance/references/evm-formulas.md` -- all EVM formulas with worked examples and interpretation
- `~/.claude/skills/project-finance/references/analysis-templates.md` -- budget vs actual, spend trend, CBS, forecasting templates
- `~/.claude/skills/project-finance/references/chart-patterns.md` -- matplotlib code for S-curve, variance bar, EVM dashboard
