---
name: seo-structure-architect
description: Use when implementing schema markup, optimizing header hierarchy, building internal linking structures, planning site architecture, or checking Core Web Vitals. Covers JSON-LD schema, topic clusters, breadcrumbs, sitemaps, and page structure for both traditional and AI search.
---

# SEO Structure Architect

## Overview

Structure is how search engines and AI systems parse your content. Clear hierarchy, complete schema, and logical internal linking determine whether your content gets indexed, cited, and ranked. 65% of pages cited by Google AI Mode include structured data.

## Schema Markup

**Always use JSON-LD** (in `<head>`). Google recommends it, new features ship to JSON-LD first, and it has the lowest error rate.

### Priority Schema Types (2026)

| Schema | Where | Impact | Notes |
|--------|-------|--------|-------|
| `Product` + `Offer` | Every product page | CRITICAL | Include: name, image, description, brand, SKU, price, availability, reviews. Products with complete schema are preferentially cited by AI shopping |
| `Organization` | Site-wide (once) | CRITICAL | sameAs to all official profiles. Entity foundation |
| `LocalBusiness`/`ComputerStore` | Site-wide (once) | HIGH | NAP, geo, areaServed, openingHours |
| `BreadcrumbList` | All pages | HIGH | Up to 30% CTR boost on desktop (removed from mobile SERPs Jan 2025) |
| `WebSite` | Site-wide (once) | HIGH | Controls site name display in SERPs |
| `AggregateRating` | Product pages | HIGH | Star ratings boost CTR 20-35% |
| `FAQPage` | Product/category/guide pages | MEDIUM | Rich results restricted to gov/health only, BUT still valuable for AI parsing |
| `MerchantReturnPolicy` | Site-wide | MEDIUM | Requires returnPolicyCountry. Trust signal |

### Deprecated — Do NOT Implement for Rich Results

| Schema | Status |
|--------|--------|
| `HowTo` | Fully deprecated (all sites) |
| `FAQPage` | Rich results: gov/health only. Still implement for AI parsing |
| `Q&A` | Deprecated Jan 2026 |
| `SitelinksSearchBox` | Deprecated Jan 2026 |
| `Dataset` (for search) | Deprecated Jan 2026 |
| `SpecialAnnouncement` | Deprecated Jan 2026 |
| `PracticeProblem` | Deprecated Jan 2026 |

### Schema Rules

- **Never implement empty schema** — worse than no schema at all
- Populate ALL relevant properties before adding
- Validate with Google Rich Results Test before deployment
- `sameAs` URLs must be valid and accessible — 404s hurt entity recognition
- For custom-built PCs without GTINs: use `mpn` with your SKU system, set `identifier_exists: false`

## Header Hierarchy

- **One H1 per page** matching the primary topic/entity
- **H2s for main sections** — question-format headings boost AI extraction and PAA eligibility
- **H3s for subsections** with related terms
- **Never skip levels** (H1 → H3 directly)
- AI systems parse content into chunks using headings — logical hierarchy = better AI citation

## Internal Linking

**Topic clusters remain the gold standard.** Zyppy's 23M internal link study shows pages with 40-44 internal links get ~4x more traffic than pages with 0-4.

### Hub-and-Spoke Model

- 1 pillar page (hub) links to 6-12 spoke pages
- Each spoke links back to hub + cross-links to 2-3 related spokes
- Each spoke should have 3-6 internal links total
- Fewer than 6 spokes = lacks coverage breadth; more than 12 = dilutes focus

### Linking Rules

- Contextual links in body content carry more weight than nav/footer links
- Descriptive anchor text (never "click here" or "learn more")
- Diversify anchor text pointing to same page
- 2-5 contextual links per 1,000 words
- Total links per page under 150

## Site Architecture

- **3-click max** from homepage to any important page
- Homepage → Category → Subcategory → Product
- Click depth directly correlates with crawl efficiency — pages beyond 3 clicks see reduced crawl rates
- Flat URLs (`/product-name`) are flexible; moderate hierarchy (`/category/product-name`) is practical for e-commerce

## Core Web Vitals

| Metric | Good | Needs Improvement | Poor |
|--------|------|-------------------|------|
| **LCP** (Largest Contentful Paint) | < 2.5s | 2.5-4.0s | > 4.0s |
| **INP** (Interaction to Next Paint) | < 200ms | 200-500ms | > 500ms |
| **CLS** (Cumulative Layout Shift) | < 0.1 | 0.1-0.25 | > 0.25 |

- INP replaced FID in March 2024 — measures full interaction responsiveness, not just input delay
- CWV is a **tiebreaker** in competitive niches, not a primary factor
- Pages at position 1 are 10% more likely to pass CWV thresholds than position 9
- Every 100ms of latency costs ~1% in sales; 53% of mobile users abandon pages >3 seconds
- LCP >3s = 23% more traffic loss in December 2025 core update

## XML Sitemaps

- Max 50,000 URLs per file, 50MB uncompressed. Use sitemap index for larger sites
- **Google ignores `<priority>` and `<changefreq>`** completely — only `<lastmod>` matters
- `<lastmod>` must accurately reflect genuine content changes — fake dates hurt
- Only include indexable, canonical, 200-status URLs

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Use Microdata/RDFa for new implementations | JSON-LD is simpler, lower error rate |
| Implement HowTo schema expecting rich results | Fully deprecated |
| Implement FAQ schema expecting rich results | Restricted to gov/health only |
| Build deep architecture (4+ clicks) | Kills crawlability |
| Set `<priority>`/`<changefreq>` in sitemaps | Google ignores them completely |
| Use strict silos with zero cross-linking | Outdated; contextual cross-links between related topics are beneficial |
| Have thin content anywhere on site | Helpful Content is site-wide — weak sections hurt everything |
