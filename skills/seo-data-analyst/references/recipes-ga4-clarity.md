# Recipes 4-7: funnels, blog attribution, UX frustration, GSC + GA4 joins

Owned by `seo-data-analyst`; moved out of SKILL.md to keep it short.

### 4. Purchase Funnel Analysis

**Data source:** GA4 Data API (runFunnelReport — v1alpha)

GA4 tracks the e-commerce funnel:
`view_item` → `add_to_cart` → `view_cart` → `begin_checkout` → `add_shipping_info` → `add_payment_info` → `purchase`

**Calculate drop-offs:**
- Cart rate = add_to_cart / view_item
- Checkout rate = begin_checkout / add_to_cart
- Purchase rate = purchase / begin_checkout

Break down by `deviceCategory` and `sessionSource` to find device/source-specific friction.

### 5. Blog-to-Conversion Attribution

**Data source:** GA4 Data API

```
Dimensions: ["landingPage"]
Filter: pagePath BEGINS_WITH "/blog/"
Metrics: conversions, purchaseRevenue, sessions, engagementRate
```

Identifies which blog posts drive the most revenue — prioritize these for refresh.

### 6. UX Frustration Analysis

**Data source:** Clarity API or MCP server

```
Dimension: URL
Metrics: Dead Click Count, Rage Click Count, Quickback Click, Excessive Scroll
```

**Cross-reference:** Pages with high frustration signals + declining GSC metrics = highest-priority fixes.

### 7. Combined GSC + GA4 Analysis

**Join key:** URL path (strip domain from GSC URLs to match GA4 pagePath).

| Analysis | GA4 Data | GSC Data | Insight |
|----------|---------|---------|---------|
| Content gap | High bounce rate | Low impressions | Content doesn't match intent |
| SEO wins | High conversion pages | Low position | Improve ranking for converting pages |
| CTR optimization | High engagement | Low CTR | Meta descriptions need work |
| Keyword intent | Conversion rates | Search queries | Match content to buyer intent |
