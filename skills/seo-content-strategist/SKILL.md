---
name: seo-content-strategist
description: SEO content strategy - planning topic clusters, writing helpful content, auditing quality, detecting content decay, and the refresh, consolidate or delete decision, with Google's helpful-content and AI-content rules. Use when planning, writing, auditing or refreshing site content for search.
family: seo
---

# SEO Content Strategist

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: date_review
    subject: seo-content-strategist-review
    review_by: 2027-03-26
  - kind: external_fact
    subject: google-2026-updates
    source_url: https://status.search.google.com/products/rGHU1u87FJnkP6W2GwMi/history
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "2026: Mar core (03-27), May core (05-21), spam updates Mar/Jun/Aug and Sep (rolling from 2026-09-24)."
-->

## Verify before you assert

Dated facts here carry a FRESHNESS anchor: past its `review_by`, fetch the `source_url` live before
stating it. The full rules: `ai-search-optimizer` → "Verify before you assert".


## Overview

Unified content workflow: plan → write → audit → refresh. Google's Helpful Content system is now embedded in core ranking (March 2024) — not a separate signal. Weak content anywhere on the site hurts everything. Topic clusters beat standalone articles for coverage and internal linking. Google's 2026 core updates (March and May) and the September 2026 spam update (rolling from 2026-09-24) are listed on the Search status dashboard [V https://status.search.google.com/products/rGHU1u87FJnkP6W2GwMi/history]; read a traffic change against those dates first.

## Content Planning

### Topic Clusters

- 1 pillar page + **8-22 cluster articles** (optimal range)
- Bi-directional linking: pillar links to every cluster, every cluster links back
- Fewer than 8 clusters = lacks coverage breadth
- More than 22 = dilutes focus
- Google formally uses **"topic authority"** as a ranking factor

### Prioritization

- Topical relevance to core expertise > search volume
- **HubSpot warning**: its blog lost much of its traffic after years of off-topic content (celebrity quotes, resignation letters). Multi-factor (algorithm + AI Overviews + off-topic), but the lesson stands: stay in your lane
- Target commercial intent keywords first (a small share of searches, the highest conversion potential, least absorbed by AI answers)
- Include content updates in the calendar — not just new content

### Timelines and cadence

ROI timelines and refresh cadence by content type (heuristics): [references/timelines-and-cadence.md](references/timelines-and-cadence.md).

### Programmatic SEO (Use With Caution)

- Best for: large datasets, 10K+ long-tail variations, unique data
- Minimum (heuristic): **500 unique words per page** and a clearly different body on every page
- Many implementations fail, often with a traffic cliff months later when thin pages are reassessed
- Progressive rollout: start small, monitor weekly, prune monthly

## Content Writing

### What Makes Content "Helpful" (Google's Standard)

- Created for humans, not search engines
- Demonstrates real-world experience and expert insight
- Specificity: data-backed statements, test results, benchmarks, observed outcomes
- AI-generated content that only contains commonly known facts = "lowest quality" rating

### AI Content Rules

- Google does **not** penalize AI content automatically — quality matters
- The March 2024 update deindexed hundreds of sites, largely mass AI-content sites
- Many top-ranking pages use some AI, with heavy human editing
- Rule: AI drafting + human expertise, original data, first-person experience = OK. AI-only paraphrase of existing sources = penalized

### Content Length by Intent

| Intent/Competition | Target Length |
|-------------------|-------------|
| High competition | 2,500-3,500 words |
| Medium competition | 2,000-2,500 words |
| Low competition | 1,200-1,800 words |
| Long-tail / problem-solving | 800-1,500 words |
| For AI citations | 2,900+ words (5.1 citations vs 3.2 for <800) |

**No single word count is a ranking factor.** A short article that directly answers intent can outrank a long rambling one.

### E-E-A-T Signals to Embed

- **Experience**: Original photos, specific dates/testing methodology, "we tested this and got..."
- **Expertise**: Specific data/benchmarks, cited sources, technical depth
- **Authority**: Link to authoritative sources, include expert quotes
- **Trust**: Author byline with credentials, transparent business info, reviews

### Readability

- Flesch Reading Ease: **60-80** (grade 8, fairly easy)
- Short paragraphs: 2-4 sentences
- 2-5 contextual internal links per 1,000 words
- Question-based H2/H3 headings for AI extraction
- Sections of a few short paragraphs between headings: neither one-liners nor walls of text

## Content Auditing

### Audit Checklist (Priority Order)

1. **Indexation health** — GSC for not-indexed pages, crawl errors
2. **Content decay** — Pages losing >20% traffic over 3-6 months (heuristic threshold)
3. **Thin content** — Pages <500 words with nothing unique
4. **Cannibalization** — Multiple pages competing for same terms
5. **E-E-A-T gaps** — Missing author attribution, uncited sources
6. **Off-topic content** — Flag content outside core expertise
7. **AI visibility** — Check presence in AI Overviews for target queries
8. **Freshness** — Pages not updated in 12+ months with time-sensitive content
9. **Orphan pages** — Pages with no internal links pointing to them

### Audit Frequency

| Site Size | Frequency |
|-----------|-----------|
| Small (<100 pages) | Every 6 months |
| Medium (100-1K pages) | Quarterly for top performers (heuristic: top 20%); annual full audit |
| E-commerce / high-traffic | Quarterly minimum; monthly top-performer checks |

## Content Refresh & Decay

### Detecting Decay (GSC Method)

Compare 3-month periods year-over-year. Flag pages with:
- Clicks down 20%+ AND position dropped 2+ spots = **competitive loss → substantive refresh** (heuristic thresholds)
- Clicks down, position stable = **SERP feature crowding → refresh meta/title**
- Impressions down, everything stable = **demand shift → consider new angle or consolidation**

Content published within 3 months is too fresh to diagnose for decay.

### Refresh Decision Framework

| Signal | Action |
|--------|--------|
| 50+ monthly visits, declining trend | **REFRESH** — update content, stats, title |
| 0 visits, 0 backlinks, 12+ months | **DELETE** — 410 or redirect to nearest relevant page |
| Multiple pages on same topic, underperforming | **CONSOLIDATE** — merge into one, 301 redirect others |
| Fundamentally wrong intent | **REWRITE** — new angle, keep same URL |
| Ranking top 3, stable | **PROTECT** — minor annual refresh to maintain |

### Refresh Rules

- Make a **substantive** change (new facts, sections, data), not a cosmetic edit
- **Never just change the date** — Google detects this and may demote
- Display only **one date visibly** (most recent update); two dates can confuse readers and the snippet (single study, directional)
- Keep schema `dateModified` accurate
- **Always keep the same URL** — changing URLs loses accumulated authority
- Submit to Search Console for re-indexing after substantial refresh
- Expect 2-5 weeks for Google to re-evaluate after refresh

### Refresh ROI

- Published case studies (HubSpot, GoInflow) report large organic gains from refreshing existing pages; treat them as directional and measure your own before/after in Search Console

## Anti-patterns

| Don't | Why |
|-------|-----|
| Publish off-topic content for traffic | Google rewards topical focus; HubSpot's losses are the cautionary tale |
| Output pure AI content without human expertise | Mass AI content was the pattern in the March 2024 deindexing |
| Hit arbitrary word count targets | Intent match > length. Short can outrank long |
| Update dates without substantive changes | Google detects fake freshness; may demote |
| Delete underperforming pages without checking | Check backlinks, consolidation potential first |
| Audit only annually for active sites | Quarterly minimum for e-commerce |
| Publish velocity over quality | Dilutes site authority post-December 2025 update |
