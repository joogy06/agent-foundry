---
name: ecommerce-growth
description: E-commerce storefront growth for WooCommerce - page-by-page checklists (homepage, category, product, cart, checkout), cart recovery and email campaigns, cross-sell and upsell, navigation and performance targets. Use when building or auditing customer-facing pages or planning growth levers for an online store.
disambiguation: WHAT goes on each customer-facing page and the growth levers across the store — page checklists, cart recovery, cross-sell, campaigns. The filtering and faceted-navigation layer specifically is woocommerce-faceted-navigation; experiment design is ecommerce-cro-experimentation; persuasion mechanics are conversion-psychology.
---

# E-Commerce Growth

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: date_review
    subject: ecommerce-growth-search-parts
    review_by: 2027-03-26
  - kind: external_fact
    subject: core-web-vitals-thresholds
    source_url: https://web.dev/articles/vitals
    verified_on: 2026-09-27
    review_by: 2027-03-26
    claim: "LCP <= 2.5 s good at p75 (the LCP benchmark in Performance Targets); unchanged."
-->

## Verify before you assert

Dated facts here carry a FRESHNESS anchor: past its `review_by`, fetch the `source_url` live before
stating it. The full rules: `ai-search-optimizer` → "Verify before you assert".


## Overview

Every page is a conversion opportunity. This skill covers **WHAT** to build on each page and how to structure the sales funnel — from first impression to post-purchase retention. For the psychology behind WHY tactics work, see `conversion-psychology`. For AI search visibility, see `ai-search-optimizer`; for traffic and sales arriving from AI assistants (which often land deep on product pages), see `ai-assistant-referrals`.

## Top 5 Essentials

1. **Guest checkout** — forced account creation is a leading abandonment reason (Baymard checkout research) [I]
2. **Instalment pricing on product pages** — show your BNPL provider's monthly price (e.g. PayPal Pay in 3). In the UK, BNPL "Deferred Payment Credit" became FCA-regulated on 2026-07-15 [I]: follow the provider's approved wording for financial promotions
3. **Express checkout buttons** at top of checkout
4. **Abandoned cart 3-email sequence** — measure your own recovery rate
5. **Page speed** — slower pages convert worse; measure your own field data

---

## Sales Funnel (Gaming PCs)

| Stage | Visitor Mindset | Key Content | Metric |
|-------|----------------|-------------|--------|
| **Awareness** | "I want a gaming PC" | SEO pages, buying guides, social | Traffic |
| **Interest** | "What specs do I need?" | Quiz, filters, comparison tools | Pages/session |
| **Desire** | "This PC looks right" | Product pages, benchmarks, reviews | Add-to-cart rate |
| **Action** | "I'm buying this" | Streamlined checkout, express pay | Conversion rate |
| **Retention** | "Should I come back?" | Post-purchase emails, upgrade offers | Repeat rate |

**Usually the biggest drop-offs** (measure your own funnel in GA4 before prioritising):
- Product page → Add to cart — fix with spec clarity, trust, payment framing
- Category → Product — fix with better cards, clearer differentiation

---

## Page-by-Page Guide

### Homepage
**Goal**: Establish trust, communicate value, route visitors within 5 seconds.

- Single compelling headline + one primary CTA
- Trust bar below hero: "Free Shipping | 2-Year Warranty | Pay in 3 | 4.5 Stars" (only claims you can prove)
- 3-4 category cards (not more)
- Social proof within first scroll
- No rotating carousels (ignored by users, slow LCP)

### Category Pages
**Goal**: Help visitors find the right product quickly.

- Faceted filters: price range, GPU, CPU, RAM, use case
- Product count per filter option (never zero-result filters)
- Sort: Best Selling, Price, Newest, Rating
- Product cards: image, name, GPU+CPU, price, monthly price, rating
- 100-200 words descriptive content for SEO
- Mobile: filters in drawer, two-column grid, "Load More" not pagination
- Filter/facet mechanics (AJAX vs reload, applied-filter chips, and which filter URLs to index vs noindex) → see `woocommerce-faceted-navigation` for the HOW and crawl-control layer

### Product Pages
**Goal**: Convince this specific PC is worth buying. Highest-leverage page.

**Above fold**:
- Image gallery (4-6 images, zoomable)
- Clear title with key specs
- Price large + BNPL monthly price (your provider's approved wording)
- Star rating with review count
- Key specs as 4-6 bullet points
- "Add to Cart" button (magenta, sticky on mobile)
- Stock + delivery info

**Below fold**:
- Full specs table (accordion sections)
- FPS benchmarks for popular games (major differentiator — no local competitor does this)
- Customer reviews
- Cross-sell: "Complete Your Setup" (monitor, peripherals)
- FAQ section

**Variation & comparison patterns**:
- **Variation swatches**: image/colour swatches beat dropdowns for visual attributes (colour, finish); keep dropdowns for non-visual ones (size). Show disabled/out-of-stock combinations rather than hiding them, and sync the selected swatch to the gallery image.
- **Tabs vs long-form**: few complex products → long-form single column (easier mobile scroll, better AI parsing); large catalogue or comparison shoppers → tabbed/accordion specs to keep the page scannable.
- **PDP trust badges**: put payment icons and returns/warranty near the price and Add-to-Cart, not only in the footer (see `conversion-psychology` trust architecture).
- **Product comparison**: offer a compare table for 2-4 similar SKUs (spec-by-spec rows) so shoppers self-serve differentiation instead of bouncing to search.

**Targets** (heuristic starting points, measure your own): electronics CVR 1.4-1.8% typical, 2.5%+ strong; add-to-cart 8-12%.

### Cart Page
- Clear product summary with image, name, spec, price
- Running total with shipping visible (no surprises)
- Express checkout buttons (e.g. PayPal, Apple Pay, Google Pay)
- 2-4 cross-sell suggestions max
- Persistent cart across sessions

### Checkout
- Single page preferred
- Express pay buttons at TOP (before form fields)
- Guest checkout always available
- Postcode lookup for address
- Max 7 form fields (average is 14.88)
- Order summary always visible
- Trust badges near payment fields

---

## Cart recovery, cross-sell, email capture and post-purchase

The 3-email cart-recovery sequence, cross-sell and upsell placements, email-capture tactics and the
post-purchase sequence:
[references/campaigns.md](references/campaigns.md).

**Reviews: no incentive by default.** Paying or discounting for reviews is legally risky in the UK
(DMCCA 2024 Sch. 20 para 13, in force 2025-04-06) and against Google's review guidance. If an incentive is
used at all it must be unconditional on sentiment, disclosed on the review itself, and never offered for
Google reviews. Rules and sources: `seo-authority-builder`.

---

## Performance Targets

Heuristic starting points (electronics), not sourced benchmarks: set targets from your own baseline.

| Metric | Typical (heuristic) | Target (heuristic) |
|--------|------------------------|--------|
| Conversion rate | 1.4-1.8% (heuristic) | > 2% (heuristic) |
| Cart abandonment | 74-76% (heuristic) | < 70% (heuristic) |
| Add-to-cart rate | 5-10% (heuristic) | > 8% (heuristic) |
| Bounce rate | 40-60% (heuristic) | < 50% (heuristic) |
| LCP | < 2.5s | < 2.0s |
| Pages/session | 3-5 | > 4 |

*To confirm a change actually moves these metrics (rather than random noise), run a controlled experiment with proper sample-size and validity guards — see `ecommerce-cro-experimentation`.*

### Speed Quick Wins
- Lazy load images below fold
- Optimise LCP element (hero image)
- Disable cart fragments AJAX on non-cart pages (test first) — see `woocommerce-developer` for the `get_refreshed_fragments` dequeue recipe
- Limit related products to 4
- Use CDN for static assets

---

## Anti-patterns

| Don't | Impact |
|-------|--------|
| Surprise shipping costs at checkout | The top abandonment reason in Baymard's survey [I] |
| Force account creation | A leading abandonment reason [I] |
| Rotating hero carousels | Users ignore, slows LCP |
| No filters on 12k product catalog | Visitors can't find anything |
| Generic product descriptions | No differentiation, poor SEO |
| Multi-page checkout (5+ steps) | Each step loses customers |
| Cross-selling during payment | Distracts at critical moment |
| No mobile optimization | Most shoppers browse on mobile; check your own device split |
| Pagination that resets scroll | Frustrating UX |
| No delivery timeframe shown | Increases purchase anxiety |
