---
name: presentation-datavis
description: >
  Use when a presentation needs charts, tables, data visualizations, or data-driven slides —
  tagged [CHART] slides from narrative, "visualize this data", or any data-to-slide conversion.
  Part of the presentation-* skill family.
triggers:
  - data visualization for presentations
  - charts for slides
  - "visualize this data"
  - tagged [CHART] slides from narrative
  - data-driven presentation
  - chart generation
  - slide charts and graphs
family: presentation
disambiguation: QUANTITATIVE visuals — charts, tables, data-driven slides. Architecture, flow and sequence visuals are presentation-diagrams.
---

# Presentation Data Visualization

Child of `presentation-builder`. This skill handles all chart, table, and data visualization generation for presentation slides. It receives tagged `[CHART]` placeholders from the narrative skill and produces embeddable visual assets.

**Siblings:** `presentation-narrative` (story and slide structure), `presentation-renderer` (final output assembly), `presentation-builder` (parent orchestrator).

## When NOT to Use

- **Standalone data analysis** without a presentation context — use general Python data tools instead.
- **Infographics or illustrations** that are not data-driven — use `vertex-banana` for image generation.
- **Simple text tables in markdown** that do not need visual rendering — just write the markdown directly.
- **Dashboard or web app visualizations** — this skill targets static slide assets, not interactive dashboards.
- **Data cleaning or ETL** — handle data preparation before invoking this skill.

---

## 1. Tool Selection

Priority order based on capability and output quality:

| Priority | Tool | Best For |
|----------|------|----------|
| 1 | **matplotlib / seaborn** | Full chart library — bar, line, pie, scatter, waterfall, histogram, heatmap, box plot, small multiples |
| 2 | **mermaid** | Gantt charts, pie charts (limited palette/styling) |
| 3 | **ASCII table fallback** | Text-only tables when no graphical rendering is available |

### Tool Details

- **matplotlib**: bar (vertical/horizontal), line, pie, scatter, waterfall, histogram, heatmap, stacked bar, grouped bar, small multiples, dashboard layouts.
- **seaborn**: statistical visualizations, distribution plots, violin plots, pair plots, regression plots. Use seaborn when the data story is statistical in nature.
- **mermaid**: Gantt charts and simple pie charts only. Limited styling control — use only when the presentation format natively supports mermaid rendering or when a quick timeline is needed.
- **ASCII**: text-based tables rendered with simple alignment. Last resort when Python is unavailable.

---

## 2. Chart Type Selection Guide

| Data Story | Chart Type | Notes |
|---|---|---|
| Compare categories | Bar (vertical or horizontal) | Horizontal if labels are long |
| Trend over time | Line | Add markers for key inflection points |
| Part-to-whole | Stacked bar or pie | Pie: max 5 segments, otherwise use stacked bar |
| Change decomposition | Waterfall | Show starting value, deltas, ending value |
| Correlation | Scatter | Add trend line if relationship is meaningful |
| Distribution | Histogram / box plot | Box plot for comparing distributions across groups |
| Ranking | Horizontal bar | Sort descending, accent color on top item |
| Timeline / schedule | Gantt (mermaid) | Use mermaid syntax for native rendering |
| Multiple KPIs | Dashboard / small multiples | Grid layout with consistent axes |

When in doubt, default to a **horizontal bar chart** — it is the most readable chart type for presentations.

---

## 3. Data Ingestion

### From files (user provides path)
```python
import pandas as pd
df = pd.read_csv(path)      # CSV
df = pd.read_json(path)     # JSON
df = pd.read_excel(path)    # Excel (requires openpyxl)
```

### From inline data (user provides in conversation)
```python
data = {
    "Category": ["A", "B", "C"],
    "Value": [100, 250, 175]
}
df = pd.DataFrame(data)
```

### From project artifacts
- Check `PROJECT.md`, `metrics/`, or any data files referenced in the project.
- Parse structured sections (tables, KPI lists) into DataFrames.

### From [PLACEHOLDER] tags
When no real data is available, generate realistic sample data with clear markers:
```python
# [SAMPLE DATA] — replace with actual figures before final presentation
data = {
    "Region": ["APAC", "EMEA", "Americas"],
    "Revenue_M": [45, 62, 88]  # [SAMPLE DATA]
}
```
Always add `[SAMPLE DATA]` comments in code and `[SAMPLE DATA]` watermark text on the chart itself.

---

## 4. Chart Generation Patterns

### Standard matplotlib Pattern

```python
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import os

# --- Configuration ---
ACCENT_COLOR = "#1a73e8"
NEUTRAL_COLOR = "#bdbdbd"
FONT_FAMILY = "sans-serif"
OUTPUT_DIR = ".presentations/output/assets"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Create chart ---
fig, ax = plt.subplots(figsize=(10, 6))

categories = df["Category"]
values = df["Value"]
key_index = values.idxmax()  # Accent the key data point

colors = [ACCENT_COLOR if i == key_index else NEUTRAL_COLOR for i in range(len(values))]
bars = ax.barh(categories, values, color=colors)

# --- Insight title (not description) ---
ax.set_title("APAC grew 3x faster than other regions", fontsize=16, fontweight="bold", pad=20)

# --- Axis labels with units ---
ax.set_xlabel("Revenue ($M)", fontsize=12)

# --- Source line ---
fig.text(0.1, 0.02, "Source: Internal Finance Report, Q4 2025", fontsize=8, color="#757575")

# --- Clean styling ---
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.tick_params(axis="both", labelsize=11)

plt.tight_layout(rect=[0, 0.05, 1, 1])

# --- Save ---
chart_path = os.path.join(OUTPUT_DIR, "revenue_by_region.png")
fig.savefig(chart_path, dpi=150, bbox_inches="tight", facecolor="white")
plt.close(fig)
```

### Waterfall Chart Pattern

```python
import numpy as np

labels = ["Start", "Product A", "Product B", "Cost Reduction", "FX Impact", "End"]
values = [100, 30, 15, 10, -8, 147]
cumulative = np.cumsum(values)
cumulative = np.insert(cumulative, 0, 0)[:-1]

fig, ax = plt.subplots(figsize=(10, 6))

for i, (label, val) in enumerate(zip(labels, values)):
    color = ACCENT_COLOR if i in (0, len(labels) - 1) else ("#4caf50" if val > 0 else "#f44336")
    bottom = cumulative[i] if i not in (0, len(labels) - 1) else 0
    height = val if i not in (0, len(labels) - 1) else cumulative[i] + val
    ax.bar(label, height if i in (0, len(labels) - 1) else val, bottom=bottom, color=color)

ax.set_title("Revenue bridge: +47% driven by Product A", fontsize=16, fontweight="bold")
fig.text(0.1, 0.02, "Source: Finance, FY2025", fontsize=8, color="#757575")
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
plt.tight_layout(rect=[0, 0.05, 1, 1])
chart_path = os.path.join(OUTPUT_DIR, "revenue_bridge.png")
fig.savefig(chart_path, dpi=150, bbox_inches="tight", facecolor="white")
plt.close(fig)
```

### Consulting-Standard Annotations

- **Insight title**: The chart title states the takeaway, not a description. "APAC grew 3x faster" not "Revenue by Region".
- **Callout boxes**: Use `ax.annotate()` to highlight key data points with a box and arrow.
- **Source line**: Always present at bottom-left in small gray text.
- **Accent color**: One color for the key data point; neutral gray for everything else. Draw the viewer's eye to the insight.

```python
# Callout annotation example
ax.annotate(
    "+47%",
    xy=(key_x, key_y),
    xytext=(key_x + 0.5, key_y + 10),
    fontsize=14, fontweight="bold", color=ACCENT_COLOR,
    arrowprops=dict(arrowstyle="->", color=ACCENT_COLOR, lw=1.5),
    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=ACCENT_COLOR)
)
```

---

## 5. Output Format

### File output
- Save all chart images to `.presentations/output/assets/`.
- Preferred format: **PNG at 150 DPI** for slides, **SVG** when vector output is requested.
- File naming: `{slide_number}_{chart_slug}.png` (e.g., `04_revenue_by_region.png`).

### Return to presentation-renderer
Provide chart metadata for each generated asset:
```python
chart_metadata = {
    "file_path": ".presentations/output/assets/04_revenue_by_region.png",
    "title": "APAC grew 3x faster than other regions",
    "source": "Internal Finance Report, Q4 2025",
    "key_insight": "APAC revenue growth outpaced EMEA and Americas by 3:1",
    "chart_type": "horizontal_bar",
    "slide_number": 4
}
```

### Asset inventory
After generating all charts, produce a summary list:
```
Charts generated:
  [04] revenue_by_region.png — "APAC grew 3x faster than other regions"
  [07] revenue_bridge.png — "Revenue bridge: +47% driven by Product A"
  [09] customer_distribution.png — "Enterprise segment drives 68% of revenue"
```

---

## 6. HARD RULES

These rules are non-negotiable and must be followed for every chart generated:

1. **Chart title = insight, not description.** Write what the data means, not what the chart shows. "APAC grew 3x faster" not "Revenue by Region".

2. **Source line on every chart.** Include data source and date at bottom-left in small gray text. No exceptions.

3. **Accent color for key data point, neutral gray for everything else.** One data point tells the story — make it visually dominant. Everything else recedes.

4. **Never fabricate data.** If real data is unavailable, use clearly marked sample data with `[SAMPLE DATA]` in the chart subtitle and code comments. The viewer must never mistake sample data for real data.

5. **Axis labels always present with units.** Every axis must have a label that includes the unit of measurement (e.g., "Revenue ($M)", "Growth (%)", "Users (thousands)").

6. **Pie charts: max 5 segments.** If more than 5 categories, group the smallest into "Other" or switch to a horizontal bar chart.

7. **Save to the standard output directory.** All assets go to `.presentations/output/assets/` — never scatter chart files across the project.

8. **Return metadata for every chart.** The renderer needs file path, title, source, and key insight to embed charts correctly.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using pie charts for more than 5 categories | Humans cannot accurately compare angles; slices become unreadable past 5 segments | Use horizontal bar chart for comparisons; pie charts only for 2-3 clearly distinct proportions |
| 3D effects on charts | Distorts proportions; back segments appear smaller; adds visual noise without information | Always use flat 2D charts; 3D effects deceive more than they inform |
| Not labeling axes or providing units | Audience guesses at scale; "Revenue" means nothing without currency and time period | Always include axis labels, units, time period, and data source; a chart should be self-explanatory |
| Using rainbow color palettes | Too many colors create visual chaos; colorblind users cannot distinguish many combinations | Use 2-3 brand colors with intensity variation; ensure sufficient contrast; test with colorblind simulator |
| Showing raw data tables when a chart would communicate better | Executives scan for trends and outliers, not individual numbers; tables require too much cognitive effort | Use charts for patterns and trends; tables only for exact reference values or small datasets (under 10 rows) |
