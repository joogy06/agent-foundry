# Financial Chart Patterns Reference

matplotlib code patterns for standard project finance charts. All charts follow consistent styling and include insight titles, source lines, and accessible colour palettes.

---

## Common Setup

```python
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for file output
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import os

# Consistent styling
COLORS = {
    'budget': '#2563EB',       # Blue
    'actual': '#DC2626',       # Red
    'earned': '#16A34A',       # Green
    'forecast': '#9333EA',     # Purple
    'under_budget': '#16A34A', # Green
    'over_budget': '#DC2626',  # Red
    'on_budget': '#6B7280',    # Grey
    'highlight': '#F59E0B',    # Amber
    'grid': '#E5E7EB',         # Light grey
    'text': '#374151',         # Dark grey
}

def setup_chart(figsize=(10, 6)):
    """Standard chart setup with consistent styling."""
    fig, ax = plt.subplots(figsize=figsize)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(axis='y', alpha=0.3, color=COLORS['grid'])
    ax.tick_params(colors=COLORS['text'])
    return fig, ax

def save_chart(fig, filename, output_dir='${PF_WORK}/charts'):
    """Save chart to file. Create directory if needed."""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    fig.savefig(filepath, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return filepath

def format_currency(value, pos=None):
    """Format large numbers as $1.2M, $500K, etc."""
    if abs(value) >= 1_000_000:
        return f'${value/1_000_000:.1f}M'
    elif abs(value) >= 1_000:
        return f'${value/1_000:.0f}K'
    else:
        return f'${value:.0f}'
```

---

## Chart 1: S-Curve (Cumulative Spend vs Plan)

Shows cumulative planned spend vs actual spend over time. The classic project financial tracking chart.

```python
def s_curve(periods, planned_cumulative, actual_cumulative,
            forecast_cumulative=None, project_name='', output_dir=None):
    """
    S-Curve: cumulative spend vs plan over time.

    Args:
        periods: list of period labels (e.g., ['Jan', 'Feb', 'Mar', ...])
        planned_cumulative: list of cumulative planned values
        actual_cumulative: list of cumulative actual values
        forecast_cumulative: optional list extending actual with forecast
        project_name: for the chart title
        output_dir: override default output directory
    """
    fig, ax = setup_chart(figsize=(12, 6))

    x = np.arange(len(periods))

    # Planned (full line)
    ax.plot(x, planned_cumulative, color=COLORS['budget'],
            linewidth=2, label='Planned (BAC)', marker='o', markersize=4)

    # Actual (up to current period)
    n_actual = len(actual_cumulative)
    ax.plot(x[:n_actual], actual_cumulative, color=COLORS['actual'],
            linewidth=2.5, label='Actual (AC)', marker='s', markersize=5)

    # Shaded area between planned and actual (variance visualization)
    min_len = min(len(planned_cumulative), n_actual)
    ax.fill_between(x[:min_len], planned_cumulative[:min_len],
                    actual_cumulative[:min_len],
                    alpha=0.1, color=COLORS['actual'])

    # Forecast extension (dashed)
    if forecast_cumulative and len(forecast_cumulative) > n_actual:
        ax.plot(x[n_actual-1:len(forecast_cumulative)],
                forecast_cumulative[n_actual-1:],
                color=COLORS['forecast'], linewidth=2, linestyle='--',
                label='Forecast', marker='^', markersize=4)

    # Formatting
    ax.set_xticks(x)
    ax.set_xticklabels(periods, rotation=45, ha='right')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(format_currency))
    ax.set_title(f'{project_name} -- Cumulative Spend vs Plan',
                 fontsize=14, fontweight='bold', color=COLORS['text'], pad=15)
    ax.set_ylabel('Cumulative Cost')
    ax.legend(loc='upper left', framealpha=0.9)

    # Source line
    fig.text(0.99, 0.01, 'Source: project-finance analysis',
             ha='right', fontsize=8, color=COLORS['text'], alpha=0.5)

    out = output_dir or '${PF_WORK}/charts'
    return save_chart(fig, 's_curve.png', out)
```

---

## Chart 2: Budget Variance Bar Chart

Horizontal diverging bar chart showing over/under budget by category.

```python
def variance_bar(categories, variances, variance_pcts,
                 project_name='', output_dir=None):
    """
    Diverging horizontal bar chart for budget variance by category.

    Args:
        categories: list of category names
        variances: list of variance values (positive = under budget)
        variance_pcts: list of variance percentages
        project_name: for the chart title
    """
    fig, ax = setup_chart(figsize=(10, max(4, len(categories) * 0.6)))

    # Sort by variance
    sorted_indices = np.argsort(variances)
    categories = [categories[i] for i in sorted_indices]
    variances = [variances[i] for i in sorted_indices]
    variance_pcts = [variance_pcts[i] for i in sorted_indices]

    y = np.arange(len(categories))
    colors = [COLORS['under_budget'] if v >= 0 else COLORS['over_budget']
              for v in variances]

    bars = ax.barh(y, variances, color=colors, height=0.6, edgecolor='white')

    # Value labels
    for i, (bar, v, pct) in enumerate(zip(bars, variances, variance_pcts)):
        label = f'{format_currency(abs(v))} ({abs(pct):.1f}%)'
        x_pos = bar.get_width()
        ha = 'left' if v >= 0 else 'right'
        offset = 5 if v >= 0 else -5
        ax.annotate(label, (x_pos, bar.get_y() + bar.get_height()/2),
                    xytext=(offset, 0), textcoords='offset points',
                    ha=ha, va='center', fontsize=9, color=COLORS['text'])

    # Zero line
    ax.axvline(x=0, color=COLORS['text'], linewidth=0.8)

    ax.set_yticks(y)
    ax.set_yticklabels(categories)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(format_currency))
    ax.set_title(f'{project_name} -- Budget Variance by Category',
                 fontsize=14, fontweight='bold', color=COLORS['text'], pad=15)
    ax.set_xlabel('Variance (positive = under budget)')

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=COLORS['under_budget'], label='Under budget'),
        Patch(facecolor=COLORS['over_budget'], label='Over budget'),
    ]
    ax.legend(handles=legend_elements, loc='lower right', framealpha=0.9)

    fig.text(0.99, 0.01, 'Source: project-finance analysis',
             ha='right', fontsize=8, color=COLORS['text'], alpha=0.5)

    out = output_dir or '${PF_WORK}/charts'
    return save_chart(fig, 'variance_bar.png', out)
```

---

## Chart 3: EVM Dashboard (2x2 Small Multiples)

Four-panel dashboard: SPI gauge, CPI gauge, EAC comparison, % complete comparison.

```python
def evm_dashboard(bac, pv, ev, ac, project_name='', output_dir=None):
    """
    2x2 EVM dashboard with key metrics.

    Args:
        bac, pv, ev, ac: Core EVM values
        project_name: for the chart title
    """
    # Calculate metrics
    spi = ev / pv if pv != 0 else None
    cpi = ev / ac if ac != 0 else None
    eac_cpi = bac / cpi if cpi and cpi != 0 else None
    eac_novar = ac + (bac - ev)
    pct_planned = pv / bac * 100 if bac else 0
    pct_earned = ev / bac * 100 if bac else 0
    pct_spent = ac / bac * 100 if bac else 0

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    fig.suptitle(f'{project_name} -- EVM Dashboard',
                 fontsize=16, fontweight='bold', color=COLORS['text'], y=0.98)

    # Panel 1: SPI indicator
    ax1 = axes[0, 0]
    if spi is not None:
        color = COLORS['under_budget'] if spi >= 1.0 else COLORS['over_budget']
        ax1.barh([0], [spi], color=color, height=0.4)
        ax1.axvline(x=1.0, color=COLORS['text'], linewidth=2, linestyle='--')
        ax1.set_xlim(0, max(1.5, spi + 0.2))
        ax1.set_title('Schedule Performance Index (SPI)', fontweight='bold')
        ax1.text(spi, 0, f'  {spi:.2f}', va='center', fontweight='bold', fontsize=14)
        status = 'Ahead' if spi > 1 else 'Behind' if spi < 1 else 'On track'
        ax1.text(0.5, -0.5, status, transform=ax1.transData, ha='center',
                 fontsize=11, color=color)
    ax1.set_yticks([])
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)

    # Panel 2: CPI indicator
    ax2 = axes[0, 1]
    if cpi is not None:
        color = COLORS['under_budget'] if cpi >= 1.0 else COLORS['over_budget']
        ax2.barh([0], [cpi], color=color, height=0.4)
        ax2.axvline(x=1.0, color=COLORS['text'], linewidth=2, linestyle='--')
        ax2.set_xlim(0, max(1.5, cpi + 0.2))
        ax2.set_title('Cost Performance Index (CPI)', fontweight='bold')
        ax2.text(cpi, 0, f'  {cpi:.2f}', va='center', fontweight='bold', fontsize=14)
        status = 'Under budget' if cpi > 1 else 'Over budget' if cpi < 1 else 'On budget'
        ax2.text(0.5, -0.5, status, transform=ax2.transData, ha='center',
                 fontsize=11, color=color)
    ax2.set_yticks([])
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)

    # Panel 3: EAC comparison
    ax3 = axes[1, 0]
    eac_labels = ['BAC\n(Budget)']
    eac_values = [bac]
    eac_colors = [COLORS['budget']]
    if eac_cpi:
        eac_labels.append('EAC\n(CPI-based)')
        eac_values.append(eac_cpi)
        eac_colors.append(COLORS['forecast'])
    eac_labels.append('EAC\n(No variance)')
    eac_values.append(eac_novar)
    eac_colors.append(COLORS['highlight'])

    bars = ax3.bar(eac_labels, eac_values, color=eac_colors, width=0.5)
    for bar, val in zip(bars, eac_values):
        ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                 format_currency(val), ha='center', va='bottom',
                 fontweight='bold', fontsize=10)
    ax3.set_title('Estimate at Completion', fontweight='bold')
    ax3.yaxis.set_major_formatter(mticker.FuncFormatter(format_currency))
    ax3.spines['top'].set_visible(False)
    ax3.spines['right'].set_visible(False)

    # Panel 4: % Complete comparison
    ax4 = axes[1, 1]
    pct_labels = ['Planned', 'Earned', 'Spent']
    pct_values = [pct_planned, pct_earned, pct_spent]
    pct_colors = [COLORS['budget'], COLORS['earned'], COLORS['actual']]
    bars = ax4.bar(pct_labels, pct_values, color=pct_colors, width=0.5)
    for bar, val in zip(bars, pct_values):
        ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                 f'{val:.1f}%', ha='center', va='bottom',
                 fontweight='bold', fontsize=11)
    ax4.set_title('% Complete Comparison', fontweight='bold')
    ax4.set_ylim(0, max(pct_values) * 1.2)
    ax4.set_ylabel('%')
    ax4.spines['top'].set_visible(False)
    ax4.spines['right'].set_visible(False)

    plt.tight_layout(rect=[0, 0.02, 1, 0.96])

    fig.text(0.99, 0.01, 'Source: project-finance analysis',
             ha='right', fontsize=8, color=COLORS['text'], alpha=0.5)

    out = output_dir or '${PF_WORK}/charts'
    return save_chart(fig, 'evm_dashboard.png', out)
```

---

## Chart 4: Burn Rate Trend

Period-over-period spend as bars with a trend line overlay.

```python
def burn_rate_chart(periods, periodic_spend, budget_per_period=None,
                    project_name='', output_dir=None):
    """
    Bar chart of period-over-period spend with trend line.

    Args:
        periods: list of period labels
        periodic_spend: list of spend amounts per period
        budget_per_period: optional planned spend per period for comparison
        project_name: for the chart title
    """
    fig, ax = setup_chart(figsize=(12, 6))
    x = np.arange(len(periods))
    width = 0.35

    # Actual spend bars
    if budget_per_period:
        ax.bar(x - width/2, budget_per_period, width, color=COLORS['budget'],
               alpha=0.6, label='Planned spend')
        ax.bar(x + width/2, periodic_spend, width, color=COLORS['actual'],
               label='Actual spend')
    else:
        ax.bar(x, periodic_spend, width*2, color=COLORS['actual'],
               label='Actual spend')

    # Trend line
    if len(periodic_spend) >= 2:
        z = np.polyfit(x, periodic_spend, 1)
        trend = np.polyval(z, x)
        ax.plot(x, trend, color=COLORS['forecast'], linewidth=2,
                linestyle='--', label=f'Trend (slope: {format_currency(z[0])}/period)')

    # Average line
    avg = np.mean(periodic_spend)
    ax.axhline(y=avg, color=COLORS['highlight'], linewidth=1.5,
               linestyle=':', label=f'Average: {format_currency(avg)}')

    ax.set_xticks(x)
    ax.set_xticklabels(periods, rotation=45, ha='right')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(format_currency))
    ax.set_title(f'{project_name} -- Burn Rate by Period',
                 fontsize=14, fontweight='bold', color=COLORS['text'], pad=15)
    ax.set_ylabel('Spend per Period')
    ax.legend(loc='upper left', framealpha=0.9)

    fig.text(0.99, 0.01, 'Source: project-finance analysis',
             ha='right', fontsize=8, color=COLORS['text'], alpha=0.5)

    out = output_dir or '${PF_WORK}/charts'
    return save_chart(fig, 'burn_rate.png', out)
```

---

## Chart 5: Cost Breakdown (Horizontal Bar)

Horizontal bar chart showing where money is being spent, sorted by magnitude.

```python
def cost_breakdown_chart(categories, amounts, project_name='',
                         top_n=10, output_dir=None):
    """
    Horizontal bar chart of cost by category, sorted by magnitude.

    Args:
        categories: list of category names
        amounts: list of cost amounts
        top_n: show only the top N categories (rest grouped as "Other")
        project_name: for the chart title
    """
    # Sort and limit to top N
    sorted_pairs = sorted(zip(amounts, categories), reverse=True)
    if len(sorted_pairs) > top_n:
        top = sorted_pairs[:top_n]
        other_total = sum(a for a, _ in sorted_pairs[top_n:])
        top.append((other_total, f'Other ({len(sorted_pairs)-top_n} categories)'))
        sorted_pairs = top

    amounts_sorted = [a for a, _ in sorted_pairs]
    cats_sorted = [c for _, c in sorted_pairs]
    total = sum(amounts_sorted)

    fig, ax = setup_chart(figsize=(10, max(4, len(cats_sorted) * 0.5)))

    # Reverse for bottom-to-top display
    y = np.arange(len(cats_sorted))
    cats_sorted.reverse()
    amounts_sorted.reverse()

    # Colour gradient (darker for higher amounts)
    max_amt = max(amounts_sorted) if amounts_sorted else 1
    colors = [plt.cm.Blues(0.3 + 0.6 * (a / max_amt)) for a in amounts_sorted]

    bars = ax.barh(y, amounts_sorted, color=colors, height=0.6, edgecolor='white')

    # Value and percentage labels
    for bar, amt in zip(bars, amounts_sorted):
        pct = amt / total * 100 if total else 0
        label = f'{format_currency(amt)}  ({pct:.1f}%)'
        ax.text(bar.get_width() + max_amt * 0.01,
                bar.get_y() + bar.get_height()/2,
                label, va='center', fontsize=9, color=COLORS['text'])

    ax.set_yticks(y)
    ax.set_yticklabels(cats_sorted)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(format_currency))
    ax.set_title(f'{project_name} -- Cost Breakdown',
                 fontsize=14, fontweight='bold', color=COLORS['text'], pad=15)
    ax.set_xlabel(f'Total: {format_currency(total)}')

    fig.text(0.99, 0.01, 'Source: project-finance analysis',
             ha='right', fontsize=8, color=COLORS['text'], alpha=0.5)

    out = output_dir or '${PF_WORK}/charts'
    return save_chart(fig, 'cost_breakdown.png', out)
```

---

## Chart 6: Forecast Cone

Projected spend range showing optimistic, likely, and pessimistic scenarios.

```python
def forecast_cone(periods, actuals, forecast_periods,
                  optimistic, most_likely, pessimistic,
                  bac=None, project_name='', output_dir=None):
    """
    Forecast cone chart with confidence bands.

    Args:
        periods: list of all period labels (historical + future)
        actuals: list of actual cumulative values (historical only)
        forecast_periods: indices where forecast begins
        optimistic: cumulative forecast values (optimistic)
        most_likely: cumulative forecast values (most likely)
        pessimistic: cumulative forecast values (pessimistic)
        bac: original budget (shown as horizontal line)
        project_name: for chart title
    """
    fig, ax = setup_chart(figsize=(12, 6))

    n_actual = len(actuals)
    x_all = np.arange(len(periods))

    # Actual line (solid)
    ax.plot(x_all[:n_actual], actuals, color=COLORS['actual'],
            linewidth=2.5, label='Actual', marker='s', markersize=5)

    # Forecast lines (dashed)
    x_forecast = x_all[n_actual-1:]
    ax.plot(x_forecast, most_likely, color=COLORS['forecast'],
            linewidth=2, linestyle='--', label='Most likely', marker='^', markersize=4)
    ax.plot(x_forecast, optimistic, color=COLORS['under_budget'],
            linewidth=1, linestyle=':', label='Optimistic', alpha=0.7)
    ax.plot(x_forecast, pessimistic, color=COLORS['over_budget'],
            linewidth=1, linestyle=':', label='Pessimistic', alpha=0.7)

    # Confidence band
    ax.fill_between(x_forecast, optimistic, pessimistic,
                    alpha=0.1, color=COLORS['forecast'], label='Forecast range')

    # BAC line
    if bac:
        ax.axhline(y=bac, color=COLORS['budget'], linewidth=1.5,
                   linestyle='-.', label=f'BAC: {format_currency(bac)}')

    # Current period marker
    ax.axvline(x=n_actual-1, color=COLORS['highlight'], linewidth=1,
               linestyle='--', alpha=0.5, label='Current period')

    ax.set_xticks(x_all)
    ax.set_xticklabels(periods, rotation=45, ha='right')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(format_currency))
    ax.set_title(f'{project_name} -- Financial Forecast',
                 fontsize=14, fontweight='bold', color=COLORS['text'], pad=15)
    ax.set_ylabel('Cumulative Cost')
    ax.legend(loc='upper left', framealpha=0.9, fontsize=9)

    # Note
    fig.text(0.5, 0.01,
             'Projection based on historical trend. Not a prediction. Actual results may vary.',
             ha='center', fontsize=8, color=COLORS['text'], alpha=0.6, style='italic')

    out = output_dir or '${PF_WORK}/charts'
    return save_chart(fig, 'forecast_cone.png', out)
```

---

## Output Locations

| Context | Chart Output Directory |
|---------|----------------------|
| Default (no project) | `${PF_WORK}/charts/` |
| Project context available | `<project>/.project-finance/charts/` |
| Presentation chain | `<project>/.presentations/output/assets/` |

When generating charts for the `presentation-builder` chain, follow `presentation-datavis` patterns:
- Use insight titles (the takeaway, not the topic)
- Include source line at bottom
- Use the project's accent colours if defined in `.presentations/palettes/`
- Save to the assets directory for the renderer to pick up

---

## Accessibility Notes

- All charts use colour-blind-safe palette (blue/red with sufficient contrast)
- All data is also available in markdown table format (charts supplement, not replace, tables)
- All charts include value labels so they are readable without relying on colour alone
- Use patterns (solid vs dashed vs dotted lines) in addition to colour for line differentiation
