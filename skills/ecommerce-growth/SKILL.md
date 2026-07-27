---
name: ecommerce-growth
description: Use when building or auditing customer-facing pages (homepage, category, product, cart, checkout), planning cart recovery or email campaigns, implementing cross-sell/upsell, or optimizing site performance and navigation for a WooCommerce store.
---

# E-Commerce Growth

## Overview

Every page is a conversion opportunity. This skill covers **WHAT** to build on each page and how to structure the sales funnel — from first impression to post-purchase retention. For the psychology behind WHY tactics work, see `conversion-psychology`. For AI search visibility, see `ai-search-optimizer`.

## Top 5 Essentials

1. **Guest checkout** — 63% abandon if forced to create account
2. **BNPL pricing on product pages** — Klarna/PayPal monthly price increases AOV 30-50%
3. **Express checkout buttons** at top of checkout (PayPal = 89% completion rate)
4. **Abandoned cart 3-email sequence** — recovers 15-30% of abandoned carts
5. **Page speed** — every 100ms delay = ~7% conversion drop

---

## Sales Funnel (Gaming PCs)

| Stage | Visitor Mindset | Key Content | Metric |
|-------|----------------|-------------|--------|
| **Awareness** | "I want a gaming PC" | SEO pages, buying guides, social | Traffic |
| **Interest** | "What specs do I need?" | Quiz, filters, comparison tools | Pages/session |
| **Desire** | "This PC looks right" | Product pages, benchmarks, reviews | Add-to-cart rate |
| **Action** | "I'm buying this" | Streamlined checkout, express pay | Conversion rate |
| **Retention** | "Should I come back?" | Post-purchase emails, upgrade offers | Repeat rate |

**Biggest drop-offs** (industry estimate):
- Product page → Add to cart: ~66% drop — fix with spec clarity, trust, payment framing
- Category → Product: ~42% drop — fix with better cards, clearer differentiation

---

## Page-by-Page Guide

### Homepage
**Goal**: Establish trust, communicate value, route visitors within 5 seconds.

- Single compelling headline + one primary CTA
- Trust bar below hero: "Free Shipping | 2-Year Warranty | Klarna | 4.5 Stars"
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
- Price large + Klarna monthly price
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

**Benchmarks**: Electronics CVR 1.4-1.8% normal, 2.5%+ excellent. Add-to-cart target: 8-12%.

### Cart Page
- Clear product summary with image, name, spec, price
- Running total with shipping visible (no surprises)
- Express checkout buttons (Klarna, PayPal)
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

## Cart Abandonment Recovery

**Rates**: Electronics 74-76%, Gaming ~67%, Mobile 73-75%

### 3-Email Sequence

| Email | Timing | Content | Discount |
|-------|--------|---------|----------|
| **Helpful nudge** | 1-2 hours | Product image + direct cart link | None |
| **Social proof** | 24 hours | Reviews, stock urgency | None |
| **Final incentive** | 48-72 hours | Small discount or free accessory | 5% off |

**Recovery benchmark**: 15-30% of abandoned carts across the sequence. ROI: ~£25 return per £1 invested.

---

## Cross-Sell & Upsell

### Cross-Sell (what goes with it)
| With PC | Suggest | Where |
|---------|---------|-------|
| Any gaming PC | Monitor, keyboard, mouse, headset | Product page: "Complete Your Setup" |
| Any gaming PC | Gaming chair, desk | Cart: "Customers Also Bought" |
| Any gaming PC | Extended warranty | Cart or checkout |

### Upsell (upgrade path)
- GPU upgrade: "RTX 5070 for +£150 (+35% FPS)" — on product page
- RAM upgrade: "+16GB for +£45" — on product page
- Storage: "2TB NVMe for +£60" — on product page

**Rules**: Max 4 suggestions per placement. Never push during payment step. Show price + thumbnail for every suggestion.

---

## Email Capture

| Tactic | Timing | Offer | Capture Rate |
|--------|--------|-------|-------------|
| Exit-intent popup | Cursor leaves page | Free buying guide PDF | 4-7% |
| Cart exit-intent | Leaving cart page | "Save your cart" | 12-17% |
| Post-purchase | Order confirmation page | "Get build tips & deals" | 15-20% |
| Embedded footer form | Always visible | Newsletter | 1-2% |

**Lead magnets**: Gaming PC Buying Guide PDF, FPS Benchmarks Cheat Sheet, Build Comparison Chart.

### Post-Purchase Sequence

| Email | When | Content |
|-------|------|---------|
| Setup guide | 3 days post-delivery | Windows optimization, driver updates |
| Review request | 7-14 days | "How's your PC? 10% off peripherals for a review" |
| Cross-sell | 30 days | "Complete your setup" accessories |
| Upgrade notification | 12 months | New GPU/component upgrade offers |

---

## Performance Targets

| Metric | Benchmark (Electronics) | Target |
|--------|------------------------|--------|
| Conversion rate | 1.4-1.8% | > 2% |
| Cart abandonment | 74-76% | < 70% |
| Add-to-cart rate | 5-10% | > 8% |
| Bounce rate | 40-60% | < 50% |
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

## Quick Wins (High Impact, Low Effort)

1. Show Klarna monthly pricing on product pages
2. Enable guest checkout
3. Express checkout buttons at top of checkout
4. Abandoned cart email sequence (3 emails)
5. Exit-intent email capture popup
6. Sticky "Add to Cart" on mobile
7. FPS benchmark data on product pages
8. Product count on filter options
9. Persistent cart across sessions
10. Post-purchase review request email

---

## Anti-Patterns

| Don't | Impact |
|-------|--------|
| Surprise shipping costs at checkout | #1 abandonment reason (48%) |
| Force account creation | 63% abandon |
| Rotating hero carousels | Users ignore, slows LCP |
| No filters on 12k product catalog | Visitors can't find anything |
| Generic product descriptions | No differentiation, poor SEO |
| Multi-page checkout (5+ steps) | Each step loses customers |
| Cross-selling during payment | Distracts at critical moment |
| No mobile optimization | 60%+ traffic is mobile |
| Pagination that resets scroll | Frustrating UX |
| No delivery timeframe shown | Increases purchase anxiety |
