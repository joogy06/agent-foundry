---
name: seo-authority-builder
description: Brand authority and E-E-A-T - entity and Knowledge Panel building, brand mentions vs backlinks, reviews and the UK fake-review law (DMCCA), Google's review-snippet guideline, preferred sources, author entities, social signals and digital PR. Use when building trust and authority signals for a business or brand, or managing reviews and reputation; a person's findability is career-online-presence.
family: seo
---

# SEO Authority Builder

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: date_review
    subject: seo-authority-builder-review
    review_by: 2027-03-26
  - kind: external_fact
    subject: dmcca-fake-reviews
    source_url: https://www.legislation.gov.uk/ukpga/2024/13/schedule/20
    verified_on: 2026-09-27
    review_by: 2027-03-26
    claim: "DMCCA 2024 Sch. 20 para 13: submitting or commissioning fake or concealed-incentive reviews is always unfair; in force 2025-04-06."
  - kind: external_fact
    subject: google-review-snippet-guideline
    source_url: https://developers.google.com/search/updates
    verified_on: 2026-09-27
    review_by: 2027-03-26
    claim: "Review-snippet guideline on fake and incentivised reviews added 2026-07-24; preferred sources extended to AI Overviews and AI Mode 2026-05-27; 2026 core updates in March and May."
-->

## Verify before you assert

Dated facts here carry a FRESHNESS anchor: past its `review_by`, fetch the `source_url` live before
stating it. The full rules: `ai-search-optimizer` → "Verify before you assert".


## Overview

Authority is how Google and AI systems decide whether to trust and cite your content. Trust is the most important E-E-A-T pillar (Google's own words). Brand web mentions correlate more strongly with AI visibility than backlinks do (Ahrefs 75K-brand study, directional). Build entity authority, not just links.

> **Boundary:** company/brand entity authority → here; an individual professional's findability (personal site, GitHub, social, AI people-search) → `career-online-presence`.

## E-E-A-T Framework (2026)

E-E-A-T is **not a direct ranking factor** — it's a framework that shapes the algorithms, and it applies to all content categories, not just YMYL. Core updates since (December 2025, March 2026, May 2026 [V https://status.search.google.com/products/rGHU1u87FJnkP6W2GwMi/history]) keep rewarding demonstrated experience.

### Experience

Google detects experience through: personal pronouns indicating direct involvement, specific data points only from implementation, original photos with EXIF data, documented testing methodology, named models/versions.

**For e-commerce**: Staff-written descriptions showing product knowledge, real benchmark data, hands-on photos, comparison insights from actual use.

### Expertise

Deep understanding shown through structure, explanation, and contextualisation — not just credentials. Cited sources, sourced statistics and expert quotations help AI systems as well as readers.

### Authority

Brand mentions (linked AND unlinked), backlinks from reputable sources, direct brand searches. **Topical authority matters more than domain authority** for informational queries — small sites outrank high-DA with better topic coverage.

### Trust (Most Important)

User reviews, social proof, transparent sourcing. SSL, clear contact details, return policy (with MerchantReturnPolicy schema), privacy policy, cookie consent.

## Brand Entity Building

### Knowledge Graph

Google's Knowledge Graph: **54+ billion entities, 1.6+ trillion facts** (May 2024, post-cleanup removing 3B+ low-quality entities).

### Knowledge Panel Optimization

- **Not dependent on Wikipedia** — Google draws from 209,966+ trusted sources (Wikidata, Google Business Profile, Crunchbase, LinkedIn, social profiles, government databases)
- Create an **"Entity Home"** — one authoritative page (About page) that serves as Google's reference point
- Corroborate entity facts across **3+ independent authoritative sources**
- Timeline: 6-12 months for new brands, 2-4 months for established brands
- Claim your Knowledge Panel when it appears

### sameAs Schema

Link to ALL official profiles: LinkedIn, Facebook, Instagram, Trustpilot, Google Maps, Companies House, Wikidata. **sameAs URLs must be valid and accessible** — 404s hurt entity recognition.

## Brand Mentions vs Backlinks

| Signal | AI Overview correlation (Ahrefs, 75K brands; study date not recorded, directional) |
|--------|------------------------|
| YouTube mentions | 0.737 (strongest) |
| Brand web mentions | 0.664 |
| Brand search volume | 0.392 |
| Backlinks | 0.218 |

Correlation, not cause: brands with more mentions are also bigger. Re-check the study before quoting it.

**Unlinked mentions count**: John Mueller confirmed Google "picks up mentions on another website." Not the same as PageRank links, but counts for entity authority.

## Social signals

Not a direct Google ranking factor; indirect through traffic, branded search and mentions. Platform-by-platform notes: [references/social-signals.md](references/social-signals.md). Never buy social signals.

## Reviews and Trust Signals

- Most buyers check reviews before a considered purchase; show them near the price
- Consistent NAP everywhere; inconsistency reads as untrustworthy
- A complete Google Business Profile and star ratings in results both lift trust

### Fake reviews are illegal in the UK, and Google penalises them

- **DMCCA 2024 Sch. 20 para 13** makes it always unfair to submit or commission a fake consumer
  review, or one that hides that it was incentivised, and to publish reviews misleadingly; in force
  **2025-04-06** [V https://www.legislation.gov.uk/ukpga/2024/13/schedule/20].
- Google added a review-snippet guideline on fake and incentivised reviews on **2026-07-24** [V
  https://developers.google.com/search/updates].
- A discount or gift for a review is an incentive: disclose it on the review, or do not offer it.

### Review Strategy

- Aggregate reviews from third-party platforms (Trustpilot, Google Reviews) with AggregateRating schema
- Encourage verified purchase reviews with photos and specific details
- **Never fabricate reviews or hide incentives** — illegal in the UK (above) and against Google's guideline
- Google Reviews velocity is the **3rd most important local ranking factor** (2026 Whitespark)

### Preferred sources

Google lets users mark preferred sources, and since 2026-05-27 that applies in AI Overviews and AI
Mode [V https://developers.google.com/search/updates]. Ask loyal readers and customers to add you:
it is an earned, brand-level signal.

## Author Entity Building

Google now treats authors as entities separate from their sites. A recognized expert can lift rankings on any site they contribute to.

**Rules:**
- Every content page needs a real, verifiable author with byline linking to author page
- Author page must contain: professional photo, bio, qualifications, social profile links, evidence of experience
- **Never fabricate author credentials** — Google specifically targets fake E-E-A-T signals (January 2025 guidelines)
- Maintain consistent name across platforms for entity recognition

## Digital PR and Link Building

| Strategy | Status (2026) |
|----------|---------------|
| Original research/proprietary data | Strongest link-earning tactic |
| Digital PR (newsworthy content) | Effective — editorial links + brand awareness |
| Podcast appearances | Builds backlinks, brand mentions, authority |
| Community participation (Reddit, forums) | Genuine helpfulness builds authority |
| Mass guest posting | **Dead** — classified as manipulative |
| Buying links from high-DR sites | **Detectable and penalized** |
| HARO/Featured.com | Reopened April 2025, quality declined. Alternatives: Qwoted, PressLinker |

## Anti-patterns

| Don't | Why |
|-------|-----|
| Fabricate author bios or credentials | Google targets fake E-E-A-T since Jan 2025 |
| Treat domain authority as key metric | Topical authority outranks DA for informational queries |
| Buy social signals (likes, shares) | Zero SEO impact, detectable, waste of money |
| Mass guest post for links | Dead strategy, penalized |
| Ignore unlinked brand mentions | Mentions correlate with AI visibility — monitor and convert to links |
| Skip YouTube | Strongest correlate of AI visibility in the Ahrefs study |
| Neglect Google Business Profile | Primary local ranking factor |
| Fabricate reviews or hide incentives | Illegal in the UK since 2025-04-06; against Google's guideline |
