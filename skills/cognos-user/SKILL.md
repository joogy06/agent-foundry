---
name: cognos-user
description: Use when consuming, creating, or customizing reports and dashboards in IBM Cognos Analytics as an end user — navigating the Cognos portal, running and scheduling reports, creating dashboards (drag-and-drop), self-service report authoring (Cognos Analytics Reporting), data exploration, prompted reports (value/date/search prompts), exporting (PDF/Excel/CSV), personal folders, subscriptions and bursts, data modules (self-service data prep), and collaboration features. Complements cognos-admin with user-role focus. Part of the cognos-* skill family.
disambiguation: Uses the Cognos FRONT END — running, authoring and customising reports and dashboards. Server install, security and administration is cognos-admin.
---

# IBM Cognos Analytics — End User & Report Consumer

Companion skill to `cognos-admin` (server administration, security, Framework Manager, REST API, deployment). This skill focuses on the day-to-day tasks of report consumers, dashboard creators, and self-service authors working within the Cognos Analytics web portal.

<HARD-RULE>
Always use prompted reports with date/filter parameters instead of running full unfiltered reports — unfiltered reports against large datasets cause server performance issues for all users.
</HARD-RULE>

<HARD-RULE>
Never share personal saved prompts or output versions that contain sensitive data — personal content inherits your access level but shared links may expose data to unauthorized users.
</HARD-RULE>

<HARD-RULE>
Always verify data refresh dates before using report outputs for business decisions — scheduled reports may show stale data from the last successful run.
</HARD-RULE>

<HARD-RULE>
Never upload sensitive data (PII, financial) into personal data modules without IT approval — uploaded data bypasses enterprise data governance controls.
</HARD-RULE>

---

## 1. Portal Navigation

### Cognos Analytics Home Page

The home page is the landing screen after login. Key areas:

```
┌──────────────────────────────────────────────────────────┐
│  Navigation bar (top)                                    │
│  ┌──────┬──────────┬─────────┬──────────┬──────────────┐ │
│  │ Home │ Content  │ Recent  │ New (+)  │ Search (🔍)  │ │
│  └──────┴──────────┴─────────┴──────────┴──────────────┘ │
│                                                          │
│  Welcome panel — recently viewed, pinned, and suggested  │
│                                                          │
│  Quick launch cards — Dashboards, Reports, Explorations  │
│                                                          │
│  Activity stream — recent runs, shared content           │
└──────────────────────────────────────────────────────────┘
```

### Content Pane

```
Content (hamburger menu or sidebar):
├── Team content — shared organizational reports and dashboards
│   ├── Published packages (data sources for reports)
│   ├── Departmental folders (Finance, Sales, HR, etc.)
│   └── Shared dashboards and reports
├── My content — personal workspace (visible only to you)
│   ├── My reports
│   ├── My dashboards
│   ├── Saved output versions
│   └── Uploaded data files
└── Recent — last accessed content (sorted by timestamp)
```

### Navigation Tips

- **Search** — Global search bar at the top; searches report names, descriptions, and content metadata. Use quotes for exact phrases (`"Sales Q1 2026"`).
- **Favorites** — Star/pin any report, dashboard, or folder for quick access from the home page.
- **Recent items** — Automatically tracks your last viewed items (reports, dashboards, explorations).
- **Breadcrumb trail** — Navigate folder hierarchy; click any breadcrumb segment to jump up.
- **Set home page** — Customize your landing page: Home > Profile > Set a specific dashboard or folder as default.
- **Personal folders** — Create folders under My Content to organize personal work by project, time period, or data domain.

---

## 2. Running Reports

### Opening and Running Existing Reports

```
Navigate to report in Team Content or My Content:
  1. Single-click to open in interactive viewer (HTML)
  2. Right-click (or "..." menu) for run options:
     ├── Run as — choose output format
     │   ├── HTML (interactive, default)
     │   ├── PDF (print-ready, paginated)
     │   ├── Excel (XLSX — formatted spreadsheet)
     │   ├── CSV (raw data, no formatting)
     │   └── XML (structured data exchange)
     ├── Run in background — queues report, notifies when done
     └── View output versions — see previously generated outputs
```

### Prompt Handling

Prompted reports present parameter selections before running. Common prompt types:

**Value prompt (dropdown / list):**
```
Select Region: [dropdown]
  ☐ EMEA
  ☑ APAC
  ☑ Americas
  ☐ Global

Tips:
  - Use the search box within the prompt to filter long lists
  - Ctrl+click or checkboxes for multi-select
  - "Select all" / "Deselect all" buttons for bulk selection
```

**Date prompt (calendar picker):**
```
Report Date Range:
  From: [2025-01-01]  (calendar icon to pick)
  To:   [2025-12-31]  (calendar icon to pick)

Tips:
  - Type dates directly in YYYY-MM-DD format for speed
  - Some reports accept relative dates ("current month", "last quarter")
  - Check if the report has default date values pre-filled
```

**Search prompt (type-ahead):**
```
Customer Name: [type to search...]
  Results update as you type
  Select one or more matching values

Tips:
  - Type at least 3 characters to trigger search
  - Wildcards may be supported (depends on report design)
```

**Cascading prompts:**
```
Step 1: Select Country → [United Kingdom]
Step 2: Select City → [London, Manchester, Birmingham]
         (city list filters based on country selection)
Step 3: Select Branch → [filtered by city]

Tips:
  - Always complete parent prompts before child prompts
  - If child prompt is empty, verify parent selection
  - Use "Reprompt" button to change selections and re-run
```

### Run Options

```
Run in background:
  - Report queues on the server; you can close the browser
  - Check status: My Content > My Schedules and Subscriptions
  - Or: Recent > look for the completed output
  - Notification appears when output is ready

View output versions:
  - Report Properties > Versions tab
  - Lists all previously saved outputs with timestamps
  - Download or view any historical version
  - Admins control how many versions are retained per report
```

---

## 3. Report Viewing

### Interactive Viewer Features

When viewing a report in HTML format, the interactive viewer provides:

**Drill actions:**
```
Drill up     — aggregate to higher level (City → Region → Country)
Drill down   — expand to finer detail (Year → Quarter → Month → Day)
Drill through — jump to a related detail report (passing context values)

Right-click a data cell or chart element to access drill options.
Drill-through targets are configured by the report author.
```

**Sorting and filtering in viewer:**
```
Column header click — sort ascending/descending (toggle)
Right-click column → Filter:
  ├── Keep only this value
  ├── Exclude this value
  ├── Top N / Bottom N
  └── Custom filter (comparison operators)

These are viewer-level filters — they do NOT modify the report definition.
Filters reset when you close the viewer unless you save as a view.
```

**Chart interactions:**
```
Hover    — tooltip shows exact values and labels
Click    — select a data point (highlights related data)
Lasso    — drag to select multiple data points
Exclude  — right-click selected points → Exclude
Zoom     — scroll wheel on chart area (where supported)
Legend   — click legend items to show/hide series
```

**Other viewer features:**
```
Bookmarks       — save current viewer state (filters, drill position) for quick return
Conditional highlighting — pre-set by report author (e.g., red = negative, green = above target)
Page navigation — for multi-page reports, use page controls at bottom
Find on page    — Ctrl+F to search text within the rendered report
```

---

## 4. Scheduling & Subscriptions

### Scheduling a Report for Recurring Delivery

```
Report > Properties > Schedule tab > Create Schedule:

Frequency options:
  ├── Daily      — every N days, or every weekday
  ├── Weekly     — select days of the week (Mon, Wed, Fri)
  ├── Monthly    — day of month (e.g., 1st, 15th) or ordinal (first Monday)
  ├── Yearly     — specific date each year
  └── Custom     — cron-style expression for complex patterns

Additional options:
  ├── Start date / End date — bounded schedule window
  ├── Time zone — ensure correct execution time for your region
  ├── Priority — Normal / High (High runs before Normal in queue)
  ├── Output format — HTML, PDF, Excel, CSV
  └── Prompt values — set fixed values for prompted reports
```

### Delivery Targets

```
Delivery options for scheduled reports:
  ├── Save to portal — output stored in Content Store (view via Versions tab)
  ├── Email delivery — send output as attachment or inline link
  │   ├── To / CC / BCC recipients
  │   ├── Subject line (can include report name, date)
  │   ├── Attach output or include link to portal
  │   └── Email body text
  ├── Burst by recipient — personalized output per recipient
  │   ├── Each recipient gets only their data slice
  │   ├── Burst key = data column (e.g., Region, Department)
  │   └── Distribution list maps burst key values to email addresses
  └── Save to file system — write output to a server-side path (admin-configured)
```

### Managing Your Schedules

```
My Content > My Schedules and Subscriptions:
  - View all your active schedules
  - Enable / disable individual schedules
  - Edit schedule frequency, format, or delivery
  - View run history (success/failure, timestamps, duration)
  - Delete schedules you no longer need

Tips:
  - Schedule during off-peak hours (early morning, weekends) to reduce server load
  - Check run history periodically — failed schedules may indicate expired credentials
    or data source issues
  - Disabled schedules retain their configuration — re-enable without reconfiguring
```

---

## 5. Dashboard Creation

### Dashboard Authoring (Drag-and-Drop)

```
New (+) > Dashboard:
  1. Select a template layout (freeform, 2-column, 3-panel, tabbed, etc.)
  2. Add a data source:
     ├── Published package (from Team Content)
     ├── Data module (self-service or published)
     └── Uploaded file (CSV/Excel in My Content)
  3. Drag data items from the source panel onto the canvas
  4. Cognos auto-suggests a visualization type based on the data
  5. Customize the visualization, filters, and layout
  6. Save to My Content or Team Content
```

### Widget Types

```
Available widgets:
  ├── Visualization — chart/graph (see visualization types below)
  ├── List          — tabular data display with sorting
  ├── Crosstab      — pivot-table-style summary
  ├── Text          — static or dynamic text (can reference data items)
  ├── Image         — upload or URL-linked image
  ├── Shape         — rectangles, circles for design elements
  ├── Web page      — embedded iframe (URL, internal or external)
  ├── Media         — embedded video
  └── Summary       — KPI summary number with comparison (up/down indicator)
```

### Visualization Types

```
Charts and graphs:
  ├── Bar (vertical/horizontal, stacked, clustered)
  ├── Line (with/without points, area fill)
  ├── Pie / Donut
  ├── Scatter / Bubble
  ├── Map (filled region, point, heat map — requires location data)
  ├── Treemap (hierarchical proportional areas)
  ├── Heat map (matrix with color intensity)
  ├── Waterfall (cumulative positive/negative values)
  ├── Box plot (statistical distribution)
  ├── Radar / Spider
  ├── Word cloud
  ├── KPI / Summary number
  ├── Gauge (radial or linear)
  └── Infographic (icon-based proportional display)

Choosing the right visualization:
  Comparison across categories → Bar chart
  Trend over time              → Line chart
  Part of whole                → Pie/Donut or Treemap
  Correlation between measures → Scatter/Bubble
  Geographic distribution      → Map
  Matrix of two dimensions     → Heat map
  Single KPI with target       → Gauge or Summary
```

### Filtering in Dashboards

```
Filter levels:
  ├── Local filter    — applies to a single widget only
  │   (drag a data item to the filter shelf of the widget)
  ├── Page filter     — applies to all widgets on the current tab/page
  │   (use the page-level filter bar at the top)
  └── Dashboard filter — applies to all tabs/pages in the dashboard
      (use the dashboard-level filter icon)

Filter types:
  ├── Value selection (include/exclude specific values)
  ├── Range (between, greater than, less than)
  ├── Top N / Bottom N
  ├── Condition (e.g., Revenue > 100000)
  └── Relative date (last 30 days, current quarter, YTD)

Widget-to-widget filtering:
  - Click a bar/slice/point in one widget to filter other widgets on the same page
  - This is enabled by default when widgets share the same data source
  - Disable per widget via Properties > "Use as filter" toggle
```

### Calculations in Dashboards

```
Add calculated fields directly in the dashboard:
  1. Data panel > right-click data source > Create Calculation
  2. Build expression using available functions:
     ├── Arithmetic: +, -, *, /
     ├── Aggregation: sum, avg, min, max, count
     ├── String: concat, substring, upper, lower
     ├── Date: _days_between, _add_days, _year, _month
     └── Conditional: if-then-else, case

Example calculations:
  [Profit %] = ([Revenue] - [Cost]) / [Revenue] * 100
  [YoY Growth] = ([This Year Revenue] - [Last Year Revenue]) / [Last Year Revenue] * 100
  [Status] = If ([Actual] >= [Target]) Then ('On Track') Else ('Behind')
```

### Dashboard Tabs

```
Add multiple tabs to organize dashboard views:
  - Click "+" next to existing tabs to add a new tab
  - Each tab can have its own layout and widgets
  - Dashboard-level filters persist across tabs
  - Page-level filters are tab-specific
  - Rename tabs by double-clicking the tab label
  - Reorder tabs by dragging

Common tab patterns:
  Tab 1: Executive Summary (KPIs and trends)
  Tab 2: Regional Breakdown (maps and comparisons)
  Tab 3: Detailed Data (lists and crosstabs)
```

---

## 6. Self-Service Reporting

### Cognos Analytics Reporting (Web-Based Authoring)

For users with authoring permissions (Authors role), the web-based report editor provides more control than dashboards:

```
New (+) > Report:
  1. Select data source (package or data module)
  2. Choose initial layout:
     ├── List        — row-by-row detail report
     ├── Crosstab    — pivot table (rows × columns × measures)
     ├── Chart       — standalone visualization
     ├── Blank       — freeform layout with manual placement
     └── Template    — pre-built layout with placeholders
  3. Drag data items onto the report canvas
  4. Configure properties, filters, and formatting
  5. Preview (Run > View Report)
  6. Save to My Content or Team Content
```

### Adding Data Items

```
Source panel (left) shows available data items organized by:
  ├── Query subjects / tables
  ├── Dimensions and hierarchies
  └── Measures

Drag items to:
  ├── Column headers (List report)
  ├── Row/Column/Measure drop zones (Crosstab)
  ├── Axis areas (Chart)
  └── Detail filters area
```

### Filters in Reports

```
Detail filter (applied before aggregation):
  [Order Date] between ?StartDate? and ?EndDate?
  [Region] in (?SelectedRegions?)

Summary filter (applied after aggregation):
  [Total Revenue] > 50000

Prompt-based filters (interactive at run time):
  Create a prompt page with value/date/search prompts
  Link prompts to filter expressions using parameter references
  Users select values before the report executes
```

### Grouping and Aggregation

```
Grouping:
  - Select a column > Group/Ungroup to add group headers and footers
  - Grouped columns become section breaks
  - Nest groups: Region > Country > City

Aggregation:
  - Summary row automatically added to group footers
  - Default: Sum for numeric, Count for non-numeric
  - Change via: Data Item Properties > Aggregate Function
  - Options: Sum, Average, Count, Min, Max, Median, Standard Deviation,
             Percentage, Running Total, Custom expression

Section headers and footers:
  - Add text, images, or calculated values to group headers
  - Repeat group headers on each page for multi-page reports
```

### Conditional Formatting

```
Select data item or cell > Conditional Style:
  1. New Condition:
     If [Profit Margin] < 0  → Red background, white text, bold
     If [Profit Margin] < 15 → Yellow background
     If [Profit Margin] >= 15 → Green background

  2. Condition types:
     ├── Value-based (numeric thresholds)
     ├── String match (equals, contains, starts with)
     ├── Date comparison (before, after, between)
     └── Top/Bottom N (percentile or count)

  3. Style options:
     ├── Background color
     ├── Font color, size, weight
     ├── Borders
     ├── Data format (number of decimals, currency symbol)
     └── Icon (checkmark, arrow, traffic light)
```

### Calculated Fields in Reports

```
Query > Data Items > Add Calculated Field:

Expression examples:
  [Profit]          = [Revenue] - [Cost]
  [Margin %]        = [Profit] / [Revenue] * 100
  [Full Name]       = [First Name] || ' ' || [Last Name]
  [Fiscal Quarter]  = 'Q' || cast(ceiling(extract(month, [Order Date]) / 3.0), varchar(1))
  [Days Outstanding]= _days_between([Due Date], current_date)
  [Status Flag]     = CASE WHEN [Amount] > [Budget] THEN 'Over' ELSE 'Under' END
```

### Headers, Footers, and Page Breaks

```
Report layout elements:
  ├── Page header  — appears at top of every page (logo, title, date)
  ├── Page footer  — appears at bottom (page number, confidentiality notice)
  ├── Report header — appears once at the beginning
  ├── Report footer — appears once at the end
  └── Page breaks  — force new page after group sections

Inserting dynamic text:
  Page footer example: "Page &npages; of &tpages; | Generated: &current_timestamp&"

Tip: Use headers/footers for PDF and print output — they are less relevant in HTML.
```

---

## 7. Data Modules

### Creating Data Modules

Data modules provide self-service data preparation for dashboards and reports:

```
New (+) > Data Module:
  Source options:
  ├── Uploaded file — CSV, Excel (.xlsx), or text file
  │   (file stored in My Content, size limits apply)
  ├── Existing package — published Framework Manager package
  ├── Data server connection — direct connection (if permissions allow)
  └── Other data module — build on top of existing modules

Steps:
  1. Select source(s) — can combine multiple sources
  2. Preview data — verify columns, data types, row counts
  3. Clean and shape — rename, filter, calculate, join
  4. Save — to My Content (personal) or Team Content (shared)
```

### Join and Blend Data Sources

```
Combining multiple tables or files:
  1. Add multiple sources to the data module
  2. Cognos auto-detects relationships based on matching column names
  3. Manually define joins if auto-detect misses:
     ├── Inner join — only matching rows from both sources
     ├── Left outer — all rows from left + matching from right
     ├── Right outer — all rows from right + matching from left
     └── Full outer — all rows from both sources
  4. Set join condition: [Table1.CustomerID] = [Table2.CustID]

Blending (for sources without direct relationships):
  - Cognos stitches results at the report level using shared dimension values
  - Less precise than explicit joins — verify results carefully
```

### Data Module Operations

```
Column operations:
  ├── Rename     — give business-friendly names (e.g., "cust_id" → "Customer ID")
  ├── Hide       — keep in module but hide from report authors
  ├── Data type  — change type (string, number, date, time, timestamp)
  ├── Format     — set display format (currency, percentage, date pattern)
  └── Calculate  — add computed columns (same expressions as report calculations)

Row operations:
  ├── Filter     — exclude rows (e.g., [Status] != 'Cancelled')
  ├── Sort       — default sort order
  └── Aggregate  — pre-aggregate (sum, count) for performance

Table operations:
  ├── Union      — stack tables with same columns vertically
  ├── Pivot      — convert columns to rows (unpivot) or rows to columns
  └── Navigation path — define drill hierarchies (Country > Region > City)
```

### Publishing Data Modules

```
Sharing a data module for team use:
  1. Save to Team Content (requires Write permission on target folder)
  2. Set permissions: right-click > Properties > Permissions
     ├── Traverse — users can see the module in folder listings
     ├── Read     — users can use the module as a data source
     ├── Write    — users can modify the module definition
     └── Execute  — users can refresh/run queries against it
  3. Other users can now select your data module when creating dashboards or reports

Tips:
  - Include clear descriptions when saving (Properties > Description)
  - Test with a sample dashboard before publishing
  - Coordinate with IT if the module will be used widely — they may want to
    review data governance and performance implications
```

---

## 8. Data Exploration

### Explore (AI-Assisted Data Discovery)

Cognos Analytics Explore uses AI to help discover insights without manual report building:

```
New (+) > Exploration:
  1. Select a data source (package, data module, or uploaded file)
  2. Cognos displays an initial overview:
     ├── Key metrics summary
     ├── Distribution of categorical fields
     ├── Time-based trends (if date fields exist)
     └── Notable outliers or patterns

AI-assisted features:
  ├── Natural language questions — type in plain English:
  │   "What is the total revenue by region for 2025?"
  │   "Show me the trend of customer count over time"
  │   "Which products have declining sales?"
  │   "Compare profit margin across departments"
  │
  ├── Suggested visualizations — Cognos recommends charts based on:
  │   - Data types (categorical, numeric, temporal)
  │   - Relationships between columns
  │   - Common analytical patterns
  │
  ├── Pattern detection — automatic identification of:
  │   - Trends (upward, downward, seasonal)
  │   - Clusters (natural groupings in the data)
  │   - Correlations (which measures move together)
  │
  ├── Anomaly detection — flags unusual values:
  │   - Outliers in numeric data
  │   - Unexpected spikes or drops in trends
  │   - Values outside normal distribution
  │
  └── Driver analysis — answers "what influences this metric?":
      - Select a target measure (e.g., Revenue)
      - Cognos identifies top contributing factors
      - Ranks dimensions by their influence on the target
      - Shows how each factor value impacts the metric
```

### Working with Explorations

```
Actions within an exploration:
  ├── Refine — drag additional fields to modify the analysis
  ├── Filter — narrow the exploration to a subset of data
  ├── Pin — pin a specific visualization to keep it visible
  ├── Convert — promote an exploration visualization to a dashboard widget
  ├── Share — save to Team Content or export results
  └── Ask again — rephrase your question for different results

Tips:
  - Start broad ("show me an overview of sales") then narrow down
  - Use Explore for initial discovery, then build a proper dashboard for ongoing use
  - Exploration results depend on data quality — verify against known reports
  - Natural language works best with well-named columns ("Revenue" vs "AMT_01")
```

---

## 9. Exporting & Sharing

### Export Options

```
From report viewer or dashboard:
  ├── Export to PDF  — full report with formatting, charts, and pagination
  ├── Export to Excel (XLSX) — formatted spreadsheet, formulas preserved where possible
  ├── Export to CSV  — raw data, comma-separated (best for data analysis tools)
  ├── Export to XML  — structured data (for system integrations)
  └── Print         — browser print dialog (Ctrl+P)

Tips:
  - PDF is best for sharing with non-Cognos users (no login needed to read)
  - Excel preserves most formatting; crosstabs export well as pivot-ready data
  - CSV strips all formatting — use for loading data into other systems
  - Large exports may time out — use "Run in Background" for big reports
```

### Sharing Content

```
Share options (right-click content > Share):
  ├── Copy link / URL — direct URL to the report or dashboard
  │   Recipients need Cognos login and appropriate permissions
  │
  ├── Email — send link or attachment via Cognos email integration
  │   (requires SMTP configuration by admin)
  │
  ├── Create shortcut — place a shortcut in another folder
  │   Shortcut points to the original; updates propagate automatically
  │
  └── Embed — generate embed code for intranet portals or web pages
      (requires admin to enable embedding and configure allowed domains)
```

### Permissions on Personal Content

```
Sharing content from My Content:
  1. Move or copy the content to a Team Content folder (recommended)
     - Or -
  2. Set permissions directly on the My Content item:
     Right-click > Properties > Permissions
     Add specific users or groups with Read access

Warning: Sharing from My Content can be fragile — if your account is
deactivated, your My Content becomes inaccessible to everyone.
Always publish important content to Team Content.
```

### Collaboration Features

```
Annotations and comments:
  ├── Add comments to a report or dashboard (Properties > Comments)
  ├── Tag colleagues with @mentions (if directory integration is configured)
  ├── Comment threads — reply and discuss within the context of the report
  └── Comments are stored in the content store and visible to users with Read access

Notifications:
  ├── Subscribe to content changes — get notified when a report is updated
  ├── Schedule completion alerts — know when your scheduled output is ready
  └── Manage notifications: Profile > Notification preferences
```

---

## 10. Best Practices for Users

### Prompt-Friendly Report Requests

When asking IT or report authors to build or modify reports:

```
Good request:
  "I need a monthly sales summary by region with prompts for:
   - Date range (default: current month)
   - Region (multi-select, default: my region)
   - Product category (optional, default: all)
   Output: PDF for email distribution, Excel for ad-hoc analysis"

Bad request:
  "I need all sales data" (too broad — will produce a massive, slow report)
```

### When to Use Dashboard vs Report

```
Use a Dashboard when:
  ├── You need interactive, visual exploration
  ├── Multiple KPIs need to appear on one screen
  ├── Users will filter and drill at run time
  ├── Data needs to be current (live connection)
  └── Audience is executives or analysts who want self-service

Use a Report when:
  ├── Output needs exact formatting (pixel-perfect for print/PDF)
  ├── Data is tabular with many columns
  ├── Output is distributed via schedule or burst
  ├── Regulatory or compliance formatting requirements exist
  └── Active Report (offline interactive) is needed
```

### Performance Tips for Report Consumers

```
1. Always supply prompt values — never leave prompts blank if "all values"
   would return millions of rows
2. Use date ranges — limit to the period you actually need
3. Avoid "Select All" on large multi-select prompts — pick specific values
4. Run large reports in background — do not wait in the browser
5. Use saved output versions — re-view existing outputs instead of re-running
6. Check if a pre-built dashboard exists — before requesting a new report
7. Limit Excel exports to necessary data — exporting 100K+ rows to Excel
   is slow and may fail; use CSV for large extracts
8. Close browser tabs for completed reports — each open report consumes
   server session resources
```

### Organizing Personal Content

```
Recommended My Content folder structure:
  My Content/
  ├── Current Projects/
  │   ├── Q1 Budget Review/
  │   └── Product Launch Analysis/
  ├── Saved Outputs/
  │   ├── Monthly Reports/
  │   └── Ad-hoc Extracts/
  ├── My Dashboards/
  ├── My Data Modules/
  └── Archive/

Tips:
  - Clean up old outputs periodically — they consume content store space
  - Move finalized work to Team Content for team access and durability
  - Use descriptive names with dates: "Sales_Summary_2026-Q1_EMEA"
  - Delete draft/test content you no longer need
```

### Working with IT and Admin Team

```
When to contact your Cognos administrator:
  ├── Need access to a new data source or package
  ├── Need access to a Team Content folder
  ├── Report runs slowly or times out consistently
  ├── Scheduled report fails repeatedly
  ├── Data appears incorrect (may be a security filter or data source issue)
  ├── Need to upload large datasets (admin may need to adjust limits)
  └── Need to share content externally (requires admin approval and configuration)

Information to provide when reporting issues:
  ├── Report name and location (full path in Team Content)
  ├── Prompt values used when the issue occurred
  ├── Time of occurrence (for admin to check server logs)
  ├── Expected result vs actual result
  ├── Screenshot of error message (if any)
  └── Browser type and version
```

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Creating reports with SELECT * or dragging all columns | Slow execution, excessive memory use, and confusing output for consumers | Select only the columns needed; start with the business question, not the data model |
| Building complex reports without using prompt pages | Users run unfiltered reports against millions of rows, overwhelming the server | Add mandatory prompt pages for date range and key dimensions; use cascading prompts to narrow data before execution |
| Duplicating reports instead of using parameterized prompts | Report sprawl — 50 copies of the same report with slight filter differences becomes unmaintainable | Use prompt parameters and conditional formatting to serve multiple use cases from one report |
| Ignoring the difference between detail and summary filters | Detail filters exclude rows before aggregation; summary filters exclude after — wrong choice produces incorrect totals | Use detail filters for row-level exclusion, summary filters for aggregate thresholds; verify totals match source system |
| Scheduling reports without setting burst keys or output limits | A single report generates a 500MB PDF that fills the content store and overwhelms email delivery | Use burst keys to split output by dimension; set row limits; deliver to a folder or file system, not email |

---

## Related Skills

| Domain | Skill |
|---|---|
| Cognos server administration, security, API, Framework Manager | `cognos-admin` |
| Data warehouse design (star/snowflake schemas for reports) | `data-warehouse` |
| Data mart design (departmental reporting data) | `data-mart` |
| DataStage ETL (data pipelines feeding Cognos) | `datastage-developer` |
| DB2 database administration (common Cognos backend) | `db2-rhel`, `db2-mainframe` |
| Presentation building from Cognos data | `presentation-builder` |
