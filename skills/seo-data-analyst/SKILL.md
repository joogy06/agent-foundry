---
name: seo-data-analyst
description: SEO data analysis with Google Search Console, Google Analytics 4, Bing Webmaster Tools and Microsoft Clarity - API endpoints, service-account auth, rate limits, BigQuery export and agent recipes for content decay, cannibalisation, striking-distance keywords, funnels and UX frustration. Use when querying search or analytics data for SEO; AI-assistant referral and revenue attribution is ai-assistant-referrals.
family: seo
---

# SEO Data Analyst

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: gsc-generative-ai-report
    source_url: https://support.google.com/webmasters/answer/16984139
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "Search Console Generative AI performance report: impressions only (no clicks, no queries), page/country/device/date; worldwide 2026-08-31; API exposure unverified."
  - kind: external_fact
    subject: ga4-ai-assistant-channel
    source_url: https://support.google.com/analytics/answer/9756891
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "GA4 AI Assistant default channel from 2026-05-13; AI Overviews and AI Mode stay in Organic."
  - kind: external_fact
    subject: bing-webmaster-ai-performance
    source_url: https://blogs.bing.com/webmaster/February-2026/Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "Bing Webmaster Tools AI Performance (public preview 2026-02-10): Copilot/Bing AI citations, grounding queries, per-page citations, no clicks."
  - kind: date_review
    subject: api-quotas
    review_by: 2026-12-26
-->

## Verify before you assert

Dated facts here carry a FRESHNESS anchor: past its `review_by`, fetch the `source_url` live before
stating it. The full rules: `ai-search-optimizer` → "Verify before you assert".


## Overview

Data-driven SEO requires querying three platforms: **GSC** (search performance), **GA4** (user behavior), and **Clarity** (behavioral/UX signals). This skill covers what an AI agent can access programmatically, rate limits, and practical workflow recipes.

**AI-assistant traffic and sales** (GA4 AI Assistant channel, `utm_source=chatgpt.com`, WooCommerce
Order Attribution, citation reports, UK analytics consent) are owned by `ai-assistant-referrals`; this
skill supplies the API mechanics it uses.

This skill is the **READ** side — pulling and analysing existing data. To DESIGN and RUN experiments against it (A/B tests, sample-size and statistical-validity guards, cache-safe variation delivery, readout rules), see `ecommerce-cro-experimentation`.

## Platform Summary

| Platform | What It Provides | Auth Method | Rate Limit | Cost |
|----------|-----------------|-------------|------------|------|
| **GSC** | Keywords, impressions, clicks, CTR, position, indexing status | Service account | 1,200 QPM / 50K rows/day | Free |
| **GA4** | Sessions, engagement, conversions, funnels, e-commerce | Service account | 200K tokens/day | Free |
| **Clarity** | Heatmaps, rage clicks, dead clicks, scroll depth, session recordings | Bearer token | **10 requests/day** | Free |
| **Bing Webmaster Tools** | Bing clicks and impressions; **AI Performance** (public preview 2026-02-10): Copilot/Bing AI citations, grounding queries, per-page citations, no clicks [V, anchor] | API key | not re-checked | Free |

Quotas above were **not re-checked on 2026-09-27**; confirm on the vendor page before planning around them.
Bing matters in the UK: its search and Copilot shares are rows in
`ai-search-optimizer/data/surfaces.v1.json`.

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
- Clicks down 20%+ AND position dropped 2+ = **competitive loss → refresh content** (heuristic thresholds)
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

### 4-7. Funnels, blog-to-revenue, UX frustration, GSC + GA4 joins

In [references/recipes-ga4-clarity.md](references/recipes-ga4-clarity.md).

## Key Limitations

| Platform | Limitation | Workaround |
|----------|-----------|------------|
| GSC | 50K rows/day per site per search type | BigQuery bulk export (free, unlimited) |
| GSC | A large share of queries is anonymised | BigQuery reveals slightly more |
| GSC | 2-4 day data delay | Use `dataState: "all"` for preliminary data |
| GSC | 16 months retention | BigQuery export (indefinite retention) |
| GSC | AI Overview / AI Mode clicks are mixed into Performance ("Web"); the **Generative AI report** gives impressions only, no clicks or queries; API exposure unverified [V, anchor] | Method in `ai-assistant-referrals` |
| GA4 | Sampling above ~10M events | BigQuery export (unsampled) |
| GA4 | Segments not available via API | Use audiences instead |
| GA4 | Path exploration not in API | BigQuery for sequence analysis |
| GA4 | Predictive metrics need 1K+ qualifying users | May not activate for small stores |
| GA4 | Data loss where consent is refused; UK rules changed with the DUAA 2025 analytics exception (2026-02-05) | Consent Mode v2; UK conditions in `ai-assistant-referrals` |
| GA4 | AI Assistant channel (2026-05-13) excludes AI Overviews and AI Mode [V, anchor] | `ai-assistant-referrals` |
| Clarity | **10 requests/day per project** | CSV export for deeper analysis |
| Clarity | 1,000 row max, no pagination | Filter to specific segments |
| Clarity | No heatmap image API | Manual dashboard review |
| Clarity | Copilot AI insights not in API | Raw data only via API/MCP |

## BigQuery and Google Trends

Unsampled, unlimited exports and keyword-trend options: [references/bigquery-and-trends.md](references/bigquery-and-trends.md).

**Third-party data** (keyword volume, backlinks, competitors; paid, owner's decision): [references/third-party-seo-data.md](references/third-party-seo-data.md).

## Anti-patterns

| Don't | Why |
|-------|-----|
| Rely solely on search volume from tools | Tool volumes are estimates; use GSC impressions as a proxy |
| Ignore anonymised queries | A large share of click data has hidden query strings |
| Report AI Overview citations as clicks | The Generative AI report has impressions only |
| Pull Clarity data more than needed | 10 requests/day — be strategic |
| Skip BigQuery for large sites | API has 50K row cap; BQ is unlimited and free |
| Use GA4 data retention default (2 months) | Change to 14 months; API not affected but Explorations are |
| Diagnose decay on content < 3 months old | Too fresh — wait for data to stabilize |
