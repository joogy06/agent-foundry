---
name: seo-serp-optimizer
description: Use when optimizing content for featured snippets, People Also Ask, AI Overview citations, rich results, or any SERP feature. Covers snippet formats, PAA optimization, AI citation strategy, and the current rich results inventory.
family: seo
---

# SEO SERP Optimizer

## Overview

SERP features determine how your content appears in search results. Featured snippets get 42.9% CTR (vs 39.8% for standard #1). But AI Overviews are replacing snippets on many queries — strategy must target both. PAA boxes appear on 80%+ of queries with multiple slots available per SERP.

## Featured Snippet Optimization

### Snippet Types (2026)

| Type | Share | Optimal Format |
|------|-------|---------------|
| **Paragraph** | 70% | 40-60 words. Question as H2, answer in first 2-3 sentences. Definition format |
| **List (ordered)** | ~18% | `<ol>` + `<li>`. 5-8 items, action verbs, uniform descriptions |
| **List (unordered)** | ~5% | `<ul>` + `<li>`. Collections, features, examples. Header with "types of" or "examples of" |
| **Table** | 7.3% | `<table>` HTML. 3-5 columns, 4-8 rows. Comparisons, specs, pricing. **Low competition** |

### Key Rule

**Check if target query triggers AI Overview before optimizing for featured snippet.** Featured snippets dropped from 34% to 18% on AI Overview SERPs. Different strategies needed.

- Query WITHOUT AI Overview → optimize for featured snippet (high CTR value)
- Query WITH AI Overview → optimize for AI Overview citation instead

### Snippet Volatility

Snippets are highly volatile and can change hands weekly during algorithm updates. Ongoing monitoring and content freshness are essential to maintain snippet positions. "Position zero" is outdated terminology — since January 2020, the snippet URL IS position 1 (de-duplicated).

## People Also Ask (PAA)

**80%+ of queries show PAA boxes** — massive opportunity with multiple slots per SERP. 63% of interactions happen on mobile.

### Optimization

1. Use PAA questions as **H2/H3 subheadings** (exact question format)
2. Answer in **2-3 sentences immediately** after the heading (for snippet extraction)
3. Follow with deeper explanation
4. Check PAA for every target keyword — reveals content gaps and subtopics Google expects
5. FAQ schema on pages with PAA-targeted Q&A sections (boosts eligibility even without rich results)

## AI Overview Citation Strategy

AI Overviews appear on 15-48% of searches (varies by query type and month). Only ~1% of users click AI Overview sources, but cited brands get +35% organic CTR (halo effect).

### What Gets Cited

| Factor | Impact |
|--------|--------|
| Structured data present | 65% of AI Mode cited pages include schema |
| Statistics in content | +22% AI visibility |
| Quotations in content | +37% AI visibility |
| Content freshness (< 3 months) | Average 6 citations vs 3.6 for older |
| 2,900+ word articles | 5.1 citations vs 3.2 for < 800 words |
| Top-10 organic ranking | 38-54% of citations (declining — AI increasingly cites outside top 10) |

### Answer Capsule

Every key page needs a **direct answer in the first 40-60 words** after the H1:

```
BAD: "Welcome to our store! We offer a wide range of..."
GOOD: "The best gaming PC for Fortnite under £1,000 is the Titan X,
featuring an RTX 5060, Ryzen 5 9600X, and 32GB DDR5. It delivers
144+ FPS at 1080p on competitive settings."
```

### Content Formats AI Prefers

| Format | Citation Impact |
|--------|----------------|
| Comparison tables | HIGH — "X vs Y" queries |
| Bullet/numbered lists | HIGH — 35% of product citations |
| Q&A / FAQ format | HIGH — matches conversational queries |
| H2/H3 + bullet structure | 40% more likely cited |
| 120-180 words between headings | 70% more ChatGPT citations vs < 50 words |
| Long unstructured paragraphs | LOW — avoid for product info |

## Rich Results Inventory (2026)

### Active — Still Generating Rich Results

| Schema | Rich Result | CTR Impact |
|--------|------------|------------|
| `Product` + `Offer` | Price, availability, merchant listings | Essential for e-commerce |
| `AggregateRating` / `Review` | Star ratings in SERP | +20-35% CTR |
| `BreadcrumbList` | Breadcrumb path (desktop only since Jan 2025) | Up to +30% CTR |
| `VideoObject` | Video carousels, key moments | Video-specific SERPs |
| `Article` | Article rich results | News/blog content |
| `Event` | Event listings | Date/location display |
| `Organization` | Knowledge Panel influence | Brand queries |
| `LocalBusiness` | Local Pack | Local queries |
| `WebSite` | Site name in SERP, sitelinks | All queries |

### Deprecated/Restricted — Do NOT Expect Rich Results

> **Canonical list: `seo-structure-architect` → "Deprecated — Do NOT Implement for Rich
> Results".** It is the single owner of schema status; this file previously carried a
> partial copy (4 of 7 entries) that **went stale and contradicted the others** — it still
> described `FAQPage` as "gov/health only" nine months after Google removed the rich result
> entirely. Do not restate schema status here; **link, and the fact stays true by construction.**

**What this skill owns instead:** which SERP *feature* each schema can still win, and how
to present for it. For whether a schema is alive at all, follow the link above.

Rich results capture 58% of clicks when present (vs 41% for standard listings).

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Target featured snippets on AI Overview queries | Snippet may not appear; optimize for AI citation instead |
| Write 200+ word snippet bait paragraphs | Optimal is 40-60 words for paragraph snippets |
| Implement HowTo schema for rich results | Fully deprecated |
| Assume snippet ownership is permanent | High volatility; monitor and refresh |
| Ignore table format | Only 7.3% of snippets = lower competition |
| Ignore PAA optimization | 80%+ of queries, multiple slots — biggest opportunity |
| Skip answer capsule on key pages | First 40-60 words determine AI citation eligibility |
