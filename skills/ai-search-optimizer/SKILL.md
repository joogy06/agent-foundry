---
name: ai-search-optimizer
description: Use when creating content, updating schema markup, configuring product feeds, managing AI crawler access, or optimizing pages for AI-powered search visibility (ChatGPT, Gemini, Perplexity, Google AI Overviews, Copilot).
---

# AI Search Optimizer

## Overview

Be the answer AI gives, not just a result it lists. AI search platforms synthesise answers and cite sources — your content must be crawlable, extractable, authoritative, and fresh. This skill covers **HOW** AI finds and recommends your products. It does NOT cover human conversion psychology (see `conversion-psychology`) or page structure (see `ecommerce-growth`).

> **Boundary:** product / page AI visibility → here; a *person's* AI findability (how ChatGPT/Perplexity/Gemini answer "who is <name>") → `career-online-presence`.

## Top 5 Essentials

1. **Allow AI search bots, block AI training bots** in robots.txt
2. **Complete Product schema** on every product page (empty schema = 18% citation penalty)
3. **Answer capsule** — first 40-60 words of key pages must directly answer the primary query
4. **FAQ sections** with FAQPage schema on product and category pages
5. **Google Merchant Center feed** — kept current with real stock/pricing

---

## How AI Platforms Find Products

| Platform | Discovery Method | Commerce | Key Action |
|----------|-----------------|----------|------------|
| **ChatGPT Shopping** | Crawls web + structured data. Shopify auto-indexed, WooCommerce via ACP plugin | Instant Checkout (expanding) | Product schema, real reviews, fast pages |
| **Google AI Overviews** | 15-48% of searches (varies by query type/month; shopping ~3%). 38-54% of cited sources come from top 10 organic (declining) | Links to merchant sites | Complete GMC feed, structured product data |
| **Perplexity** | Real-time web crawl. Free Merchant Program | Buy with Pro (PayPal) | Allow PerplexityBot, join Merchant Program |
| **Google AI Mode** | Conversational search with Gemini. New Q&A product attributes | Agentic checkout coming | GMC conversational attributes (5-10 Q&A per product) |
| **Copilot** | Bing-powered. 53% more purchases within 30 min vs non-Copilot | Copilot Checkout | Bing Merchant Center feed |

---

## Answer Engine Optimization (AEO)

### The Answer Capsule

Every key page needs a direct answer in the first 40-60 words after the H1:

```
BAD: "Welcome to GamingBuilds! We offer a wide range of gaming PCs..."
GOOD: "The best gaming PC for Fortnite under £1,000 is the Titan X,
featuring an RTX 5060, Ryzen 5 9600X, and 32GB DDR5. It delivers
144+ FPS at 1080p on competitive settings with a 1TB NVMe SSD."
```

### Content Formats AI Prefers

| Format | Citation Impact |
|--------|----------------|
| Comparison tables | HIGH — "X vs Y" queries |
| Bullet/numbered lists | HIGH — 35% of product citations |
| Q&A / FAQ format | HIGH — matches conversational queries |
| Callout/highlight boxes | 2.3x citation rate |
| H2/H3 + bullet structure | 40% more likely cited |
| Long unstructured paragraphs | LOW — avoid for product info |

### Formatting Rules
- Clear H2/H3 headings with descriptive text
- Most important answer FIRST (inverted pyramid)
- Consistent data formats (always GBP, always "X cores / Y threads")
- Original data: benchmarks, FPS figures, test results
- Content must render in initial HTML (AI crawlers don't execute JS)

---

## Conversational Query Strategy

| Traditional Search | AI Conversational Search |
|-------------------|-------------------------|
| "gaming PC fortnite" | "What gaming PC should I buy for my son who plays Fortnite?" |
| "RTX 5070 vs 5060" | "Is it worth spending extra on the RTX 5070 for 1440p gaming?" |
| "gaming PC Rotherham" | "Where can I buy a gaming PC near Rotherham with good support?" |

**Content strategy**: Build Q&A content around natural questions. Target "best gaming PC for [game] under [budget]" pages, GPU comparison tables, and buyer's guides with FAQ schema.

---

## Schema Checklist

| Schema | Where | Priority |
|--------|-------|----------|
| `Product` + `Offer` | Every product page | CRITICAL |
| `FAQPage` | Product, category, guide pages | CRITICAL |
| `Organization` | Site-wide (once) | CRITICAL |
| `LocalBusiness` / `ComputerStore` | Site-wide (once) | HIGH |
| `BreadcrumbList` | All pages | HIGH |
| `AggregateRating` | Product pages | HIGH |

### Schema Rules
- **Never implement empty schema** — 18% citation penalty vs no schema
- Populate ALL relevant attributes before adding
- JSON-LD format (preferred by Google and AI systems)
- Validate with Google Rich Results Test

### GTIN/MPN for Custom PCs
Custom-built PCs don't have GTINs. Use `mpn` (Manufacturer Part Number) with your own SKU system. Set `identifier_exists: false` in product feeds. Google and AI systems accept MPN as alternative for custom/assembled products.

---

## AI Crawler Management

### robots.txt — Allow Search, Block Training

```
# AI SEARCH bots (ALLOW — these power search results)
User-agent: ChatGPT-User
Allow: /
User-agent: OAI-SearchBot
Allow: /
User-agent: PerplexityBot
Allow: /
User-agent: Google-Extended
Allow: /
User-agent: Claude-SearchBot
Allow: /

# AI TRAINING bots (BLOCK — no search benefit)
User-agent: GPTBot
Disallow: /
User-agent: ClaudeBot
Disallow: /
User-agent: CCBot
Disallow: /
User-agent: Meta-ExternalAgent
Disallow: /
```

**Key distinction**: Search bots power real-time results users see. Training bots collect data for model training — blocking them doesn't affect your search visibility.

---

## Product Feed Priority

1. **Google Merchant Center** (Priority 1) — WooCommerce feed plugin, maximise attributes, keep stock current
2. **Perplexity Merchant Program** (Priority 2) — Free, apply at perplexity.ai
3. **Bing Merchant Center** (Priority 3) — Powers Copilot shopping
4. **ChatGPT feed** (Priority 4) — ACP plugin for WooCommerce (verify current enrollment process)

**Small team minimum viable**: Start with GMC only. Add others when capacity allows. Stale feeds actively harm your brand.

---

## Entity Building (Brand Authority)

AI checks multiple independent sources before recommending ("consensus signal"):

| Action | Impact |
|--------|--------|
| Consistent NAP everywhere | Entity recognition |
| Google Business Profile (complete) | Local entity authority |
| `sameAs` links in Organization schema | Entity connections |
| Active social profiles | Entity signals |
| Review presence (Trustpilot, Google) | Trust signals |
| Reddit/forum helpful participation | Consensus signal |
| YouTube content | Cited 200x more than other video platforms |

---

## Monitoring AI Visibility

**Manual testing (free)**: Ask each platform product questions and check citations:
- "Best gaming PC shop near Rotherham"
- "Best pre-built gaming PC under £1000 UK"

**Analytics tracking**: Monitor referrals from `chat.openai.com`, `perplexity.ai`, `copilot.microsoft.com`

---

## Anti-Patterns

| Don't | Why It Hurts |
|-------|-------------|
| Block AI search crawlers | Invisible regardless of content quality |
| Empty/partial schema | 18% citation penalty vs no schema |
| JavaScript-only content | AI crawlers don't execute JS |
| Thin/generic product descriptions | Nothing unique to cite — AI extracts facts, ignores hype |
| No FAQ sections | Misses conversational query matches |
| Stale product feeds | AI deprioritises outdated data |
| No entity presence beyond own site | Weak consensus signal |
| Overoptimising for AI at expense of humans | Pages must read naturally for visitors too |
