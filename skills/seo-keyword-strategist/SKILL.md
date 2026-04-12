---
name: seo-keyword-strategist
description: Use when researching keywords, mapping search intent, building topic clusters, detecting keyword cannibalization, or optimizing content for entity-based search. Covers keyword strategy, intent classification, clustering, and cannibalization diagnosis.
---

# SEO Keyword Strategist

## Overview

Keywords are entity pointers, not density targets. Google's Knowledge Graph holds 54+ billion entities and 1.6+ trillion facts. Modern keyword strategy is about mapping content to entities and intent, not counting keyword occurrences.

## Dead Metrics — Stop Using These

| Myth | Reality |
|------|---------|
| **Keyword density 0.5-1.5%** | No correlation with rankings (2026 study, 1,536 results). Google uses NLP, not word counting |
| **LSI keywords** | Confirmed myth. John Mueller: "There's no such thing as LSI keywords." Use "semantically related terms" instead |
| **Content scoring tools predict rankings** | Correlation 0.17-0.30 (weak). Use for gap finding, not score chasing |
| **Search volume is accurate** | Google Keyword Planner overestimates 54% of the time. Use volumes as directional only |

## Intent Classification

| Intent | % of Searches | Content Type | AI Overview Risk |
|--------|--------------|--------------|-----------------|
| **Informational** | 52.65% | Guides, how-tos, explainers | HIGH — AI answers directly |
| **Navigational** | 32.15% | Brand/product pages | LOW — users want specific site |
| **Commercial** | 14.51% | Comparisons, reviews, "best X" | MEDIUM — sweet spot for clicks |
| **Transactional** | 0.69% | Product/checkout pages | LOW — users want to buy |

**Priority**: Target commercial intent keywords — high conversion potential, not fully absorbed by AI Overviews. Informational head terms are increasingly zero-click (58.5% US, 83% when AI Overviews appear).

## Entity-First Keyword Strategy

Google shifted from "strings" to "things." Optimize for entities, not keyword strings.

**Three pillars:**
1. **Precision** — Each page = one canonical entity. Align title, H1, and schema `mainEntityOfPage`
2. **Coverage** — Site collectively covers all subtopics that define your niche (topical authority)
3. **Connectivity** — Internal links mirror Knowledge Graph entity relationships

**Practical steps:**
- Place primary keyword in title, H1, first paragraph, and 1-2 subheadings naturally
- Cover expected subtopics comprehensively (check People Also Ask for gaps)
- Use schema markup to explicitly declare entities (Product, Organization, etc.)
- Write for meaning, not matching — Google's NLP (BERT, MUM, Gemini) understands synonyms and context

## Keyword Clustering

**SERP-based clustering is the gold standard.** If 3+ of the same URLs appear in top 10 for two keywords, they belong in one cluster.

**Rule: One search intent = one keyword cluster = one page.**

**Method:**
1. Collect target keywords
2. Check SERP overlap (same pages ranking = same cluster)
3. Verify intent alignment (informational vs commercial)
4. Assign one cluster per page — never create separate pages for keywords in the same cluster

## Cannibalization Detection

**Not every instance of multiple pages ranking for the same keyword is a problem.** Ahrefs reports 9,700 cases on their own site — almost none need fixing.

**It's a problem when:**
- Pages swap positions 3+ times in 7 days (red flag)
- Rankings drop 5-15 positions when "wrong" page is selected
- CTR is split between pages serving identical intent

**It's NOT a problem when:**
- Both pages rank stably in top positions
- Pages serve different intents (blog post = informational, product page = transactional)
- Total traffic from both exceeds what one page would get

**Detection via GSC API:**
```
Query dimensions: ["query", "page"]
Group by query → count distinct pages
Flag: queries where count(page) > 1 AND positions swap frequently
```

**Resolution decision:**

| Signal | Action |
|--------|--------|
| Position swapping, same intent | **Consolidate** — merge weaker into stronger, 301 redirect. Case studies show +200-466% traffic |
| Different intents, both stable | **Leave it** — keyword diversification is beneficial |
| Same intent, one clearly dominant | **Re-optimize** — change weaker page to target different cluster |

## Zero-Click Strategy

58.5% of US searches result in zero clicks. When AI Overviews appear, 83% zero-click.

- For informational keywords: optimize for AI Overview citation as brand visibility (even without clicks)
- For commercial keywords: these retain higher CTR — prioritize them
- Track CTR alongside rankings — #1 with 0.6% CTR on an AIO query may be less valuable than #5 without AIO

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Target keyword density percentages | Dead metric — no ranking correlation |
| Use "LSI keyword" tools | LSI is a myth; use topical gap analysis instead |
| Chase content scoring tool numbers | 0.17-0.30 correlation; score ≠ ranking |
| Trust search volume precision | 54% overestimated; use as directional only |
| Create separate pages for same-cluster keywords | Causes cannibalization; one cluster = one page |
| Treat all multi-page rankings as cannibalization | Often beneficial; check for actual harm first |
| Ignore zero-click data | 58.5% of searches get no clicks; factor into strategy |
