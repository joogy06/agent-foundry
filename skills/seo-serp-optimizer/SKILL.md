---
name: seo-serp-optimizer
description: SERP features - featured snippets, People Also Ask, the rich results inventory, and choosing per query between snippet and AI Overview targeting, with the ads that now compete for the same space. Use when optimising content or markup to win a search-results feature; AI citation tactics are ai-search-optimizer and brand-trust levers are seo-authority-builder.
family: seo
---

# SEO SERP Optimizer

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: date_review
    subject: seo-serp-optimizer-review
    review_by: 2027-03-26
  - kind: external_fact
    subject: ai-mode-ad-formats
    source_url: https://blog.google/products/ads-commerce/google-marketing-live-search-ads/
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "AI Mode ad formats (Conversational Discovery ads, Highlighted Answers, Direct Offers) beta; UK not stated."
-->

## Verify before you assert

Dated facts here carry a FRESHNESS anchor: past its `review_by`, fetch the `source_url` live before
stating it. The full rules: `ai-search-optimizer` → "Verify before you assert".


## Overview

SERP features decide how a result appears. Featured snippets still win clicks where they appear, but
AI Overviews and AI Mode have replaced them on many queries, and ads now sit inside and around those
answers. Target each query for the feature it actually shows.

## Featured Snippet Optimization

### Snippet Types (2026)

| Type | Optimal Format |
|------|---------------|
| **Paragraph** (the most common) | 40-60 words. Question as H2, answer in first 2-3 sentences. Definition format |
| **List (ordered)** | `<ol>` + `<li>`. 5-8 items, action verbs, uniform descriptions |
| **List (unordered)** | `<ul>` + `<li>`. Collections, features, examples. Header with "types of" or "examples of" |
| **Table** | `<table>` HTML. 3-5 columns, 4-8 rows. Comparisons, specs, pricing. Less contested |

### Key Rule

**Check if the target query triggers an AI Overview before optimising for a featured snippet.** Snippets appear far less often on AI Overview results, so the strategies differ.

- Query WITHOUT AI Overview → optimize for featured snippet (high CTR value)
- Query WITH AI Overview → optimize for AI Overview citation instead

### Snippet Volatility

Snippets are highly volatile and can change hands weekly during algorithm updates. Ongoing monitoring and content freshness are essential to maintain snippet positions. "Position zero" is outdated terminology — since January 2020, the snippet URL IS position 1 (de-duplicated).

## People Also Ask (PAA)

PAA boxes appear on a large share of queries, with several slots per results page, and most interactions are on mobile.

### Optimization

1. Use PAA questions as **H2/H3 subheadings** (exact question format)
2. Answer in **2-3 sentences immediately** after the heading (for snippet extraction)
3. Follow with deeper explanation
4. Check PAA for every target keyword — reveals content gaps and subtopics Google expects
5. FAQ schema on pages with PAA-targeted Q&A sections (boosts eligibility even without rich results)

## AI Overview and AI Mode citation

- **Answer capsules, formats assistants extract well, and what gets cited** are owned by
  `ai-search-optimizer` (AEO section); this skill does not keep a second copy.
- Brand levers such as preferred sources: `seo-authority-builder`.
- **Measure it:** Search Console's Generative AI report gives AI-feature impressions per page, no
  clicks and no queries [V https://support.google.com/webmasters/answer/16984139]. Method:
  `ai-assistant-referrals`.
- **Ads compete for the same space.** AI Mode ad formats (Conversational Discovery ads, Highlighted
  Answers, Direct Offers) are in beta [V, anchor]. Paid placement is not a citation. Each
  format's market status is a registry row (`ai-search-optimizer/data/surfaces.v1.json`, `channel: paid`).

## Rich Results Inventory (2026)

### Active — Still Generating Rich Results

| Schema | Rich Result | CTR Impact |
|--------|------------|------------|
| `Product` + `Offer` | Price, availability, merchant listings | Essential for e-commerce |
| `AggregateRating` / `Review` | Star ratings in SERP | Higher CTR; follow the 2026-07-24 fake-review guideline |
| `BreadcrumbList` | Breadcrumb path (desktop only since Jan 2025) | Context in the result |
| `QAPage` / `DiscussionForumPosting` | Q&A and forum results (still supported) | UGC queries |
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

## Anti-patterns

| Don't | Why |
|-------|-----|
| Target featured snippets on AI Overview queries | Snippet may not appear; optimize for AI citation instead |
| Write 200+ word snippet bait paragraphs | Optimal is 40-60 words for paragraph snippets |
| Implement HowTo schema for rich results | Fully deprecated |
| Assume snippet ownership is permanent | High volatility; monitor and refresh |
| Ignore table format | Tables are less contested |
| Ignore PAA optimisation | Several slots on many results pages |
| Copy AEO tables from `ai-search-optimizer` | Two copies drift; link instead |
| Count AI Mode ads as citations | Paid placement, not earned |
