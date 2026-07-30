---
name: seo-data-analyst
description: Use when querying Google Search Console, Google Analytics 4, or Microsoft Clarity data for SEO analysis. Covers API endpoints, authentication, rate limits, and agent workflow recipes for content decay detection, cannibalization analysis, funnel optimization, and behavioral insights.
family: seo
---

# SEO Data Analyst

## Overview

Data-driven SEO requires querying three platforms: **GSC** (search performance), **GA4** (user behavior), and **Clarity** (behavioral/UX signals). This skill covers what an AI agent can access programmatically, rate limits, and practical workflow recipes.

This skill is the **READ** side — pulling and analysing existing data. To DESIGN and RUN experiments against it (A/B tests, sample-size and statistical-validity guards, cache-safe variation delivery, readout rules), see `ecommerce-cro-experimentation`.

## Platform Summary

| Platform | What It Provides | Auth Method | Rate Limit | Cost |
|----------|-----------------|-------------|------------|------|
| **GSC** | Keywords, impressions, clicks, CTR, position, indexing status | Service account | 1,200 QPM / 50K rows/day | Free |
| **GA4** | Sessions, engagement, conversions, funnels, e-commerce | Service account | 200K tokens/day | Free |
| **Clarity** | Heatmaps, rage clicks, dead clicks, scroll depth, session recordings | Bearer token | **10 requests/day** | Free |

**All three use service accounts or tokens for headless access — no browser required.**

## Authentication (Headless Setup)

### GSC & GA4 (Google Service Account)
1. Create GCP project, enable "Search Console API" and "Google Analytics Data API"
2. Create service account, download JSON key
3. Add service account email as user in GSC (Settings → Users) and GA4 (Admin → Property Access)
4. Set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json`

### Clarity (Bearer Token)
1. Clarity Dashboard → Settings → Data Export → Generate API token
2. Pass as `Authorization: Bearer TOKEN` header

### MCP Servers (Direct AI Agent Access)
| Tool | Package | Platform |
|------|---------|----------|
| **mcp-gsc** | `github.com/AminForou/mcp-gsc` | GSC |
| **Clarity MCP** | `@microsoft/clarity-mcp-server` | Clarity |
| **SEO MCP** | `seomcp.dev` | GSC + GA4 + 39 tools |

## Agent Workflow Recipes

### 1. Content Decay Detection

**Data source:** GSC Search Analytics API

**Method:** Compare two 28-day periods, per-page metrics.

```
Period A: last 28 days    → dimensions: ["page"], metrics: clicks, impressions, position
Period B: previous 28 days → same query
```

**Alert thresholds:**
- Clicks down 20%+ AND position dropped 2+ = **competitive loss → refresh content**
- Clicks down, position stable = **SERP feature crowding → refresh meta/title**
- Impressions down, everything stable = **demand shift → new angle or consolidation**

Content published < 3 months ago is too fresh to diagnose.

### 2. Keyword Cannibalization

**Data source:** GSC Search Analytics API

```
Dimensions: ["query", "page"] → paginate to 50K rows
Group by query → filter where count(distinct page) > 1
Flag: queries where different pages have similar positions (both competing)
```

**Resolution:** See `seo-keyword-strategist` skill for decision framework.

### 3. Striking Distance Keywords (Positions 4-20)

**Data source:** GSC Search Analytics API

```
Dimensions: ["query", "page"]
Filter: exclude branded queries (regex)
Post-filter: position >= 4 AND position <= 20 AND impressions > 50
Sort: impressions descending
```

These are your highest-opportunity keywords — close to page 1, worth optimizing.

### 4. Purchase Funnel Analysis

**Data source:** GA4 Data API (runFunnelReport — v1alpha)

GA4 tracks the e-commerce funnel:
`view_item` → `add_to_cart` → `view_cart` → `begin_checkout` → `add_shipping_info` → `add_payment_info` → `purchase`

**Calculate drop-offs:**
- Cart rate = add_to_cart / view_item
- Checkout rate = begin_checkout / add_to_cart
- Purchase rate = purchase / begin_checkout

Break down by `deviceCategory` and `sessionSource` to find device/source-specific friction.

### 5. Blog-to-Conversion Attribution

**Data source:** GA4 Data API

```
Dimensions: ["landingPage"]
Filter: pagePath BEGINS_WITH "/blog/"
Metrics: conversions, purchaseRevenue, sessions, engagementRate
```

Identifies which blog posts drive the most revenue — prioritize these for refresh.

### 6. UX Frustration Analysis

**Data source:** Clarity API or MCP server

```
Dimension: URL
Metrics: Dead Click Count, Rage Click Count, Quickback Click, Excessive Scroll
```

**Cross-reference:** Pages with high frustration signals + declining GSC metrics = highest-priority fixes.

### 7. Combined GSC + GA4 Analysis

**Join key:** URL path (strip domain from GSC URLs to match GA4 pagePath).

| Analysis | GA4 Data | GSC Data | Insight |
|----------|---------|---------|---------|
| Content gap | High bounce rate | Low impressions | Content doesn't match intent |
| SEO wins | High conversion pages | Low position | Improve ranking for converting pages |
| CTR optimization | High engagement | Low CTR | Meta descriptions need work |
| Keyword intent | Conversion rates | Search queries | Match content to buyer intent |

## Key Limitations

| Platform | Limitation | Workaround |
|----------|-----------|------------|
| GSC | 50K rows/day per site per search type | BigQuery bulk export (free, unlimited) |
| GSC | ~47% of queries anonymized | BigQuery reveals slightly more |
| GSC | 2-4 day data delay | Use `dataState: "all"` for preliminary data |
| GSC | 16 months retention | BigQuery export (indefinite retention) |
| GSC | No AI Overview/AI Mode data in API | Monitor Google announcements |
| GA4 | Sampling above ~10M events | BigQuery export (unsampled) |
| GA4 | Segments not available via API | Use audiences instead |
| GA4 | Path exploration not in API | BigQuery for sequence analysis |
| GA4 | Predictive metrics need 1K+ qualifying users | May not activate for small stores |
| GA4 | 20-60% data loss in EU without advanced consent mode | Enable Consent Mode v2 advanced |
| Clarity | **10 requests/day per project** | CSV export for deeper analysis |
| Clarity | 1,000 row max, no pagination | Filter to specific segments |
| Clarity | No heatmap image API | Manual dashboard review |
| Clarity | Copilot AI insights not in API | Raw data only via API/MCP |

## BigQuery (Power Tool)

Both GSC and GA4 can export to BigQuery for unlimited, unsampled data access.

| Feature | GSC Export | GA4 Export |
|---------|-----------|------------|
| Data | Site/URL impression tables | Raw event-level data |
| Granularity | Aggregated (like API) | Every event with all parameters |
| Sampling | None | None |
| Cost (small store) | ~$0/month (free tier) | ~$0-5/month |
| Setup | GSC Settings → Bulk data export | GA4 Admin → BigQuery Links |

**For small e-commerce:** BigQuery free tier (10 GB storage, 1 TB queries/month) is likely sufficient.

## Google Trends (Keyword Research)

No official stable API. Options:
- **pytrends** (Python): Free but unreliable, may break
- **SerpAPI Google Trends**: $75-275/month, reliable
- **Manual**: trends.google.com — compare keywords, identify seasonality, geographic demand

Use Google Trends for: seasonal trend identification, geographic demand analysis, comparing keyword popularity, identifying rising topics for content planning.

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Rely solely on search volume from tools | 54% overestimated; use GSC actual impressions as proxy |
| Ignore anonymized queries (~47%) | Nearly half of click data has hidden query strings |
| Pull Clarity data more than needed | 10 requests/day — be strategic |
| Skip BigQuery for large sites | API has 50K row cap; BQ is unlimited and free |
| Use GA4 data retention default (2 months) | Change to 14 months; API not affected but Explorations are |
| Diagnose decay on content < 3 months old | Too fresh — wait for data to stabilize |
