---
name: seo-meta-optimizer
description: SERP and social metadata - title tags, meta descriptions, Open Graph and X cards, URL structure, pixel widths, rewrite behaviour, and the syntax of robots meta and snippet tags (nosnippet, max-snippet, data-nosnippet, Bing noarchive). Use when writing or auditing titles, descriptions, social tags or snippet-tag markup; whether to opt out of AI features is ai-search-optimizer.
family: seo
---

# SEO Meta Optimizer

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: date_review
    subject: seo-meta-optimizer-review
    review_by: 2027-03-26
  - kind: external_fact
    subject: ai-snippet-controls
    source_url: https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "nosnippet, max-snippet, data-nosnippet and noindex govern AI Overview and AI Mode input; no AI-specific robots meta directive; Search Console generative-AI setting per property."
-->

## Verify before you assert

Dated facts here carry a FRESHNESS anchor: past its `review_by`, fetch the `source_url` live before
stating it. The full rules: `ai-search-optimizer` → "Verify before you assert".


## Overview

Meta optimisation controls what people see in search results and social shares. Google often
rewrites titles and descriptions, but titles within limits that match the page get rewritten less.
AI Overviews take clicks on many queries, so every remaining click matters more; measure the effect
on your own pages (Search Console) rather than quoting industry averages.

## Title Tags

### Limits

| Context | Character Limit | Pixel Width |
|---------|----------------|-------------|
| Desktop | ~60 characters | ~600px |
| Mobile | ~50 characters | ~500px |
| Sweet spot (lowest rewrite rate) | **51-60 characters** | **< 580px** |

- Google rewrites a large share of titles, many of them only to change the brand name (McAlpin, Q1 2025 study: directional)
- Keep titles near the sweet spot above; very short and very long titles underperform
- Bolded query matches widen the title in pixels, so a title that normally fits can be truncated

### Title Formula

**Homepage:** `Brand Name | Primary Value Proposition`
**All other pages:** `Primary Keyword - Compelling Hook | Brand` (keyword first, brand last)

### CTR Optimization (Data-Backed)

| Tactic | Direction (Backlinko large-sample CTR study; undated here, so directional only) |
|--------|--------|
| Positive/emotional sentiment | Higher CTR |
| Power words (FREE! AMAZING! ULTIMATE!) | **Lower** CTR: they read as clickbait |
| Numbers in title | Positive correlation |
| URL containing query terms | Higher CTR |

Test on your own pages (Search Console CTR by page) before generalising; see `ecommerce-cro-experimentation`.

## Meta Descriptions

- Google often ignores a provided description and generates its own from page content
- **Always write them**: they are used when they match the query, and they drive social sharing previews

### Rules

| Rule | Detail |
|------|--------|
| Length | 150-160 characters optimal. Minimum 70 chars (shorter triggers auto-generation) |
| Content | Include primary keyword, clear value proposition, call to action |
| Unique | Every page needs a unique description — no duplicates |
| Honest | Must accurately reflect page content (prevents pogo-sticking) |

## Open Graph & Social

**OG tags are the universal standard** — used by Facebook, LinkedIn, Pinterest, Slack, and X/Twitter as fallback.

### Required Tags

```html
<meta property="og:title" content="Page Title">
<meta property="og:description" content="100-200 character description">
<meta property="og:image" content="https://example.com/image.jpg">
<meta property="og:url" content="https://example.com/canonical-url">
<meta property="og:type" content="website">
```

### Image Specs

| Spec | Value |
|------|-------|
| Minimum size | 1200x630px |
| Aspect ratio | 1.91:1 |
| Format | JPG or PNG |
| URLs | **Always absolute** (relative URLs break on share) |

X/Twitter-specific tags (`twitter:card`, etc.) are optional — X falls back to OG tags if absent.

## URL Structure

- **Under 60 characters**, short and readable
- Lowercase, hyphens, descriptive keywords
- No parameters, session IDs, or unnecessary depth
- E-commerce: `domain.com/category/product-name` is the practical middle ground
- Use canonical tags for product variants to prevent duplicate content
- **Keep URLs stable** — changing URLs loses accumulated authority

## AI Overviews and meta strategy

Metadata now serves two readers: people choosing a result, and AI features choosing a source. Keep
titles and descriptions factual and entity-rich. Pew Research (Jul 2025) found users rarely click a
link inside an AI summary [I]. Measure your own: Search Console's Generative AI report shows AI
impressions per page (no clicks) [V https://support.google.com/webmasters/answer/16984139]; method in
`ai-assistant-referrals`.

## Robots meta and snippet-control syntax

This skill owns the **syntax**; what each control does to AI features, and whether to opt out, is
the one controls table, `ai-search-optimizer/references/controls.md`.

```html
<!-- page level: no snippet, or a capped one (also limits AI Overview / AI Mode input) -->
<meta name="robots" content="max-snippet:160, max-image-preview:large">
<meta name="robots" content="nosnippet">
<!-- Bing only: keep in search, out of Copilot answers and training -->
<meta name="bingbot" content="noarchive">
<!-- one block of text kept out of snippets (Google and Bing) -->
<p data-nosnippet>Trade prices are for account holders only.</p>
<!-- allow indexing of embedded content despite a noindex -->
<meta name="googlebot" content="noindex, indexifembedded">
```

There is no `noai` directive. The Search Console "Search generative AI" setting is a property
setting, not a tag.

## Anti-patterns

| Don't | Why |
|-------|-----|
| Use power words in titles | They read as clickbait and lower CTR |
| Optimize for character count alone | Pixel width is the actual measurement |
| Skip meta descriptions ("Google rewrites anyway") | Used when they match, and they drive social previews |
| Put brand name first on non-homepage pages | Keyword-first front-loads relevance |
| Use a `noai` meta tag | No such directive; it does nothing |
| Write meta descriptions under 70 characters | Too short triggers auto-generation |
| Use relative URLs in OG tags | Break when content is shared |
| Change URLs during refresh | Loses accumulated authority; keep same URL |
