---
name: ai-search-optimizer
description: Use when creating content, updating schema markup, configuring product feeds, managing AI crawler access, or optimizing pages for AI-powered search visibility (ChatGPT, Gemini, Perplexity, Google AI Overviews, Copilot).
---

# AI Search Optimizer

## Overview

Be the answer AI gives, not just a result it lists. AI search platforms synthesise answers and cite sources — your content must be crawlable, extractable, authoritative, and fresh. This skill covers **HOW** AI finds and recommends your products. It does NOT cover human conversion psychology (see `conversion-psychology`) or page structure (see `ecommerce-growth`).

> **Boundary:** product / page AI visibility → here; a *person's* AI findability (how ChatGPT/Perplexity/Gemini answer "who is <name>") → `career-online-presence`; an AI agent **transacting** on the buyer's behalf (ACP / AP2 / delegated payment / `llms.txt`) → `agentic-commerce-readiness`.
>
> **Discovery vs transaction:** this skill gets you *recommended*, so the buyer lands on your site and
> checks out normally. That is the proven, measurable half. Agents *completing purchases* without a
> site visit is a separate and far less mature surface — do not fund it from this skill's evidence.

## Top 5 Essentials

1. **Allow AI search bots, block AI training bots** in robots.txt
2. **Complete Product schema** on every product page (empty schema = 18% citation penalty)
3. **Answer capsule** — first 40-60 words of key pages must directly answer the primary query
4. **Q&A / FAQ content** on product and category pages — for AI extraction, *not* for a SERP rich result ([Deprecated](#deprecated--do-not-implement))
5. **Google Merchant Center feed** — kept current with real stock/pricing

---

## How AI Platforms Find Products

| Platform | Discovery Method | Commerce | Key Action |
|----------|-----------------|----------|------------|
| **ChatGPT Shopping** | Crawls web + structured data. Shopify auto-indexed, WooCommerce via ACP plugin | **Discovery only** — Instant Checkout shut down Mar 2026 ([Deprecated](#deprecated--do-not-implement)) | Product schema, real reviews, fast pages |
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

> **Priority here is ranked for AI CITATION, which is not the same ranking as SERP
> presentation.** For schema **status** — whether a type is alive, deprecated, or
> removed — `seo-structure-architect` is the **canonical owner**; this table
> deliberately does not restate it. That split is why `FAQPage` once carried three
> different verdicts across three skills.

> **Deliberately NOT using CRITICAL/HIGH/MEDIUM/LOW.** Those words are
> `seo-structure-architect`'s **SERP-impact** vocabulary. Reusing them for a different
> axis produced three false contradictions the moment this table was written —
> `BreadcrumbList` read MEDIUM here and HIGH there, which is indistinguishable from
> disagreement even though both were correct on their own axis. **When two skills rank
> the same object on different axes, they must not share a verdict vocabulary.**

| Schema | Where | AI tier |
|--------|-------|---------|
| `Product` + `Offer` | Every product page | **AI-1** — empty schema carries an 18% citation penalty |
| `Organization` | Site-wide (once) | **AI-1** — entity foundation; `sameAs` to every official profile |
| `MerchantReturnPolicy` + `shippingDetails` | Product / site-wide | **AI-1** — completes the Offer; AI answers surface returns and delivery at the decision moment |
| `LocalBusiness` / `ComputerStore` | Site-wide (once) | **AI-2** |
| `AggregateRating` | Product pages | **AI-2** |
| `BreadcrumbList` | All pages | **AI-2** — context for extraction |
| `WebSite` | Site-wide (once) | **AI-3** — affects how your name is rendered, not whether you are cited |
| `FAQPage` | Product, category, guide pages | **AI-3** — still parsed by AI crawlers; keep it, expect nothing from the SERP |

`AI-1` = ship before anything else · `AI-2` = ship next · `AI-3` = keep, don't prioritise.
**These tiers rank for citation only and say nothing about SERP value or schema status.**

**Implement the full set from `seo-structure-architect`.** This table ranks; it does not
enumerate. Two types (`MerchantReturnPolicy`, `WebSite`) were missing here entirely until
2026-07-26, so anyone following only this skill shipped an incomplete Offer.

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
# AI SEARCH bots (ALLOW — these power answers users see now)
User-agent: ChatGPT-User
Allow: /
User-agent: OAI-SearchBot
Allow: /
User-agent: PerplexityBot
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

# Google-Extended — NOT a search bot. Judgement call; default ALLOW. See below.
User-agent: Google-Extended
Allow: /
```

**Key distinction**: Search bots power real-time results users see. Training bots collect data for
model training — blocking them doesn't affect your search visibility.

### `Google-Extended` is the exception to that rule — read before copying

`Google-Extended` is **not a crawler and has no user-agent string** — it is a robots.txt *product
token* only. Per [Google's own crawler documentation](https://developers.google.com/search/docs/crawling-indexing/google-common-crawlers)
it **does not affect Google Search inclusion, is not a ranking signal, and does not affect AI
Overviews eligibility**. Filing it under "search bots that power search results" is wrong.

It is the one token where *allow search / block training* conflicts, because it controls **both**:

| Blocking `Google-Extended` costs you | Blocking it does **not** cost you |
|---|---|
| Grounding in **Gemini Apps** and Vertex AI (a real AI-visibility surface) | Google Search inclusion |
| — | Google Search ranking |
| — | **AI Overviews** eligibility |

**Default recommendation: ALLOW** — you keep Gemini-app grounding, and the cost is consenting to
Gemini model training. Block it only if you have a deliberate no-training policy, and know you are
trading away Gemini grounding to get it. Either way, **do not expect any Search or AI Overviews
effect in either direction.**

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

**Analytics tracking**: Monitor referrals from `chatgpt.com`, `perplexity.ai`, `copilot.microsoft.com`, `claude.ai`, `gemini.google.com`

> ⚠️ Use `chatgpt.com` — **not** `chat.openai.com`, which OpenAI retired in 2024. A segment still
> filtering on the old domain returns zero and reads as *"AI sends us no traffic"* rather than as a
> broken filter.

**Judge these segments on CVR and AOV, not session volume.** AI referral volume is small by
construction (zero-click discovery leaves no referrer at all), so sessions understate the channel.
The instrument that actually sees dark/zero-click discovery is a **post-purchase survey** —
*"How did you first hear about us?"* — plus **branded-search lift** in Search Console.

---

## Deprecated — Do NOT Implement

**This surface changes faster than any other in the SEO family. Check this table before acting on
any recommendation in this skill, and add a row the moment something dies — a dead recommendation
left at CRITICAL priority costs more than a missing one.**

| Thing | Status | What to do instead |
|-------|--------|--------------------|
| **ChatGPT Instant Checkout** (the *product*) | **Shut down Mar 2026**, ~5 months after launch. Only ~12 merchants ever went live. Users browsed heavily but did not buy | Treat ChatGPT as a **discovery** channel that sends traffic to your site. OpenAI is moving to dedicated retailer **apps** |
| **`Google-Extended` as a "search bot"** | Never was one — it is a robots.txt token with no user-agent, and no Search/AIO effect | See the Google-Extended section above |
| **`chat.openai.com` referral tracking** | Domain retired 2024 | Use `chatgpt.com` |
| **Deprecated *schema* types** | Owned elsewhere — this skill does not restate schema status | **`seo-structure-architect` → "Deprecated — Do NOT Implement for Rich Results"** is canonical. It is the complete list; the partial copy that used to live here is what let `FAQPage` drift into three different verdicts |

> **Do not read the Instant Checkout row as "agentic commerce is dead" — the product failed, the
> protocol standardised.** ACP's stable spec is dated **2026-04-17** (*after* the shutdown) and AP2
> went to the **FIDO Alliance on 2026-04-28** with 60 organisations. See **`agentic-commerce-readiness`**
> for the standards layer and what a merchant actually implements. What died was one consumer
> surface, not the category.

> **Why this table exists.** Four defects were found in this skill in one review (Jul 2026), all of
> the same kind: correct-when-written guidance that the world moved past. **Recency of authorship is
> not the risk factor — rate of change of the subject is.** Any skill covering a fast-moving surface
> should carry a table like this.

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
