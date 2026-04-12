# Business Domain Template

Master template for business intelligence wikis: companies, markets, products, customer segments, trends, strategies.

**Template version**: business-v1
**Best for**: competitive analysis, market research, B2B sales intelligence, founder/operator knowledge bases.

---

## Directory Structure

```
<wiki-root>/
  WIKI.md
  index.md
  log.md
  raw/
    images/
    <YYYY-MM-DD>-<company-slug>.pdf        # filings, reports, decks
    <YYYY-MM-DD>-<market-slug>.csv          # market data exports
    <YYYY-MM-DD>-<article-slug>.md          # saved articles
  wiki/
    companies/
    markets/
    products/
    customer-segments/
    trends/
    strategies/
    data-sources/
    reports/        # Synthesized analyses
    comparisons/
    signals/        # Leading indicators
  _templates/
    company.md
    market.md
    product.md
    customer-segment.md
    trend.md
    strategy.md
    data-source.md
    report.md
    comparison.md
    signal.md
  _maintenance/
    link-index.md
    tag-registry.md
    lint-history.jsonl
    source-manifest.yaml
```

---

## Page Types

| Type | Purpose | Required Frontmatter | Template |
|------|---------|---------------------|----------|
| `company` | One organization | industry, ticker (if public), hq_country | `company.md` |
| `market` | A market segment or vertical | tam, growth_rate, maturity | `market.md` |
| `product` | A product offering | vendor, pricing_model, category | `product.md` |
| `customer-segment` | Buyer persona or segment | size, willingness_to_pay, pain_points | `customer-segment.md` |
| `trend` | Macro or micro trend | direction, strength, timeline | `trend.md` |
| `strategy` | A strategic play | type (growth/defensive/offensive), status | `strategy.md` |
| `data-source` | Where data comes from | kind (primary/secondary/tertiary), freshness | `data-source.md` |
| `report` | Synthesized analysis | sources (>=2), confidence | `report.md` |
| `comparison` | A vs B companies/products | subjects (>=2), criteria | `comparison.md` |
| `signal` | Leading indicator | signal_type, observed_date, magnitude | `signal.md` |

---

## Frontmatter Schema (Business Extensions)

```yaml
---
# Base fields (always required)
type: company
title: "Acme Corp"
slug: acme-corp
created: 2026-04-07
updated: 2026-04-07
sources:
  - path: raw/2026-04-07-acme-10k-filing.pdf
    pages: [1, 120]
tags: [saas, b2b, us-market]
status: active
confidence: high

# Business extensions
industry: saas
ticker: ACME               # If public
hq_country: US
founded: 2015
employee_count: 1200       # Approximate
ceo: "Jane Smith"
last_funding: "Series D, $120M, 2024-03"
revenue_estimate: "$250M ARR (2025)"
related: [saas-market, competitor-brand-x]
---
```

---

## Cross-Referencing Conventions

- `[[company-slug]]` on first mention of a company in any page
- `[[market-slug]]` when a company or product is in that market
- `[[trend-slug]]` when a company strategy responds to a trend
- Reports list all contributing sources in frontmatter

---

## Naming Conventions

- **Companies**: kebab-case company name (`acme-corp`, `competitor-brand-x`)
- **Markets**: descriptive kebab-case (`b2b-saas-us`, `fintech-apac`)
- **Products**: `<company>-<product-name>` (`acme-cloud-v3`)
- **Trends**: kebab-case with direction hint (`ai-spend-increasing-2026`)
- **Signals**: `<observed-date>-<signal-name>` (`2026-04-01-churn-spike`)

---

## Output Formats

**Citations**: `[Source: raw/2026-04-07-acme-10k-filing.pdf, p.42]` — mandatory for all claims, especially numbers and financial data
**Mermaid defaults**:
- `quadrantChart` — competitive positioning (2x2 matrices)
- `graph TD` — market structure, value chains
- `pie` — market share, segment breakdown
- `timeline` — company history, product launches

---

## Maintenance Workflows

- **Lint frequency**: weekly (business data decays fast)
- **Staleness thresholds**: company pages stale after 90 days; market pages after 180 days; signals after 30 days
- **Archive**: defunct companies -> `status: archived`, `acquired_by: <slug>` if applicable

---

## Obsidian Compatibility Notes

- Dataview: "all SaaS companies with >$100M ARR", "markets with declining growth"
- Graph view useful for visualizing competitive clusters
- Custom CSS callouts for "Signal", "Threat", "Opportunity"

---

## Example Pages

### Example: company

```markdown
---
type: company
title: "Acme Corp"
slug: acme-corp
industry: saas
ticker: ACME
hq_country: US
founded: 2015
employee_count: 1200
revenue_estimate: "$250M ARR (2025)"
sources:
  - path: raw/2026-04-07-acme-10k-filing.pdf
    pages: [1, 120]
tags: [saas, b2b, us-market]
status: active
confidence: high
related: [saas-market, competitor-brand-x, acme-cloud-v3]
---

# Acme Corp

B2B SaaS platform for supply chain visibility, targeting mid-market enterprises [Source: raw/2026-04-07-acme-10k-filing.pdf, p.1].

## Financials

- Revenue: $250M ARR (2025) [Source: raw/2026-04-07-acme-10k-filing.pdf, p.22]
- Gross margin: 78% [Source: raw/2026-04-07-acme-10k-filing.pdf, p.23]
- Customer count: ~4,500 [Source: raw/2026-04-07-acme-10k-filing.pdf, p.15]

## Competitive Position

- Competes with [[competitor-brand-x]] in the mid-market segment
- Differentiated on [[acme-cloud-v3]] AI features

## See Also

- [[saas-market]] — Market context
- [[competitor-brand-x]] — Primary competitor
```

### Example: signal

```markdown
---
type: signal
title: "Acme customer churn spike 2026-04"
slug: 2026-04-01-acme-churn-spike
signal_type: churn
observed_date: 2026-04-01
magnitude: medium
sources:
  - path: raw/2026-04-01-acme-quarterly-call.pdf
    pages: [5, 8]
tags: [acme-corp, churn, warning-signal]
status: active
confidence: medium
related: [acme-corp]
---

# Acme Churn Spike — April 2026

Acme reported 8% quarterly gross churn on the April 2026 earnings call, up from 5% trailing twelve months [Source: raw/2026-04-01-acme-quarterly-call.pdf, p.5].

## Implications

- Mid-market segment may be softening
- Monitor [[acme-corp]] customer health metrics next quarter
```

---

## Anti-Patterns (Business Domain)

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Financial claims without source citations | Numbers are load-bearing; unsourced figures are worthless or misleading | Every dollar figure, percentage, and count gets `[Source: raw/<file>, p.<N>]` |
| Treating blog posts as authoritative | Tertiary sources drift from reality, rumors amplify | Prefer primary (filings, press releases) over tertiary (blogs, tweets); tag confidence accordingly |
| Not updating stale company pages | Business data decays fast — 6-month-old financials are often wrong | Set 90-day staleness threshold for company pages; lint check #6 flags |
| Mixing signals with established facts | Leading indicators get treated as conclusions | Use `signal` type with `signal_type` field, keep separate from `company` pages |
| Missing `confidence` calibration | All claims look equally strong, bad decisions result | Use `confidence: low` for inferred/unsourced; `high` only for primary sources |
