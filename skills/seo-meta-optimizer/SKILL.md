---
name: seo-meta-optimizer
description: Use when creating or optimizing title tags, meta descriptions, Open Graph tags, Twitter Cards, URL structures, or any SERP-facing metadata. Covers character limits, pixel widths, CTR optimization, and AI Overview impact on click-through rates.
---

# SEO Meta Optimizer

## Overview

Meta optimization is about controlling what users see in search results and social shares. Google rewrites 76% of title tags — but well-crafted titles within limits get rewritten less often and earn higher CTR. With AI Overviews reducing organic CTR by 40-61%, every click matters more.

## Title Tags

### Limits

| Context | Character Limit | Pixel Width |
|---------|----------------|-------------|
| Desktop | ~60 characters | ~600px |
| Mobile | ~50 characters | ~500px |
| Sweet spot (lowest rewrite rate) | **51-60 characters** | **< 580px** |

- Google rewrites 76% of titles (McAlpin Q1 2025), but 63% of rewrites are just brand name changes (cosmetic)
- Titles 40-60 chars have 33.3% higher CTR than those outside this range
- Bold keywords add 15-20% more pixels — titles that normally fit can get truncated when Google bolds query matches

### Title Formula

**Homepage:** `Brand Name | Primary Value Proposition`
**All other pages:** `Primary Keyword - Compelling Hook | Brand` (keyword first, brand last)

### CTR Optimization (Data-Backed)

| Tactic | Impact | Source |
|--------|--------|--------|
| Positive/emotional sentiment | **+7.3% CTR** | Backlinko, 4M results |
| Power words (FREE! AMAZING! ULTIMATE!) | **-13.9% CTR** | Backlinko, 4M results |
| Title case | Up to +37% CTR | Multiple studies |
| Numbers in title | Positive correlation | Multiple studies |
| URL containing query terms | +45% CTR | Backlinko |

**Sacred cow killed:** Power words DECREASE CTR. They signal clickbait. Use positive sentiment instead.

## Meta Descriptions

- Google ignores provided descriptions **~72% of the time** — generates its own from page content
- BUT pages with meta descriptions have **5.8% higher CTR** than pages without
- **Always write them** — the 28% usage rate still drives significant value, and they control social sharing previews

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

- **Under 60 characters** — shorter URLs improve CTR by up to 15%
- Lowercase, hyphens, descriptive keywords
- No parameters, session IDs, or unnecessary depth
- E-commerce: `domain.com/category/product-name` is the practical middle ground
- Use canonical tags for product variants to prevent duplicate content
- **Keep URLs stable** — changing URLs loses accumulated authority

## AI Overview Impact on Meta Strategy

| Metric | Value |
|--------|-------|
| AI Overview appearance rate | 15-48% (varies by query type and month) |
| CTR drop when AI Overview present | 40-61% |
| Zero-click rate with AI Overviews | 83% |
| Users who click AI Overview sources | ~1% (Pew Research) |
| Cited brand organic CTR boost | +35% vs non-cited |

**Strategy shift:** Meta content must serve dual purpose — compelling for human clicks AND clear/factual/entity-rich for AI citation. Being cited in an AI Overview gives a +35% halo effect on organic CTR even though only 1% click within the AIO itself.

## Robots Meta (2025-2026)

- `max-snippet` and `nosnippet` directives now **extend to AI Overviews** — publishers can control AI snippet usage
- `indexifembedded` allows indexing of embedded content despite noindex
- No official `noai` directive exists — control via existing `nosnippet`/`max-snippet`

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Use power words in titles | Data shows -13.9% CTR decrease |
| Optimize for character count alone | Pixel width is the actual measurement |
| Skip meta descriptions ("Google rewrites anyway") | 5.8% CTR boost when present |
| Put brand name first on non-homepage pages | Keyword-first performs better |
| Write meta descriptions under 70 characters | Too short triggers auto-generation |
| Use relative URLs in OG tags | Break when content is shared |
| Change URLs during refresh | Loses accumulated authority; keep same URL |
