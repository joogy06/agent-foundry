---
name: woocommerce-faceted-navigation
description: Use when building, reviewing, or fixing faceted/layered navigation and product filters on a WooCommerce store — filter UX (AJAX vs reload, mobile filter drawer, applied-filter chips, sort logic), facet indexability strategy (index-worthy facet landing pages vs thin parameter combinations, canonical/noindex/robots decision matrix), crawl-budget and origin-load protection (parameter normalization, cache-key design, allowlisted exposure), and Woo query/DB performance for high-cardinality attributes (attribute lookup tables, external index offload boundary). Trigger on - product filters, layered nav, faceted navigation, filter SEO, crawl trap, filter URLs indexed, AJAX filters slow. Category-page content checklists live in ecommerce-growth; generic schema and site architecture live in seo-structure-architect; Woo code security patterns live in woocommerce-developer.
disambiguation: The FILTER and faceted-navigation layer only — filter UX, facet indexability, crawl control, and the SEO consequences of filtered URLs. Whole-page content and store-wide growth levers are ecommerce-growth.
---

# WooCommerce Faceted Navigation

## Overview

Faceted (layered) navigation lets shoppers narrow a catalogue by attribute — price, brand, colour, size, spec. Done well it is the single biggest discovery win on a large store; done badly it is a crawl trap, a duplicate-content generator, and an origin-load DDoS you inflicted on yourself. This skill is the **HOW + crawl-control** layer.

| Need | Go to |
|------|-------|
| WHAT to put on a category page (facet list, counts, sort, drawer) | `ecommerce-growth` §Category Pages — the checklist; reference it, don't duplicate |
| Woo PHP code, security, HPOS query rules, external-search offload | `woocommerce-developer` |
| Schema, site architecture (3-click), sitemaps, CWV | `seo-structure-architect` |

**Four independent controls — never conflate them:** UX state (what the shopper sees), **crawlability** (can a bot fetch the URL), **indexability** (may it appear in search), and **cacheability** (can the response be served from cache). A URL can be cacheable yet non-indexable, or crawlable yet noindexed. Design each deliberately.

## Facet Taxonomy & Filter UX

- **Choose facets by demand,** not by "every attribute we store." Expose the handful shoppers actually filter on; bury the long tail.
- **Show option counts** and prevent zero-result states — disable or hide options that would return nothing for the current selection (see `ecommerce-growth`). A directly-requested **invalid, duplicate, or zero-result** filter URL should return **`404`**, not a `200` empty page (per Google's faceted-navigation guidance) — that lets crawlers drop it.
- **AJAX vs full reload:**

| | AJAX filtering | Full page reload |
|--|---------------|------------------|
| UX | Fast, no scroll reset | Slower, scroll resets |
| SEO | Filtered state often invisible to crawlers unless URLs update | Server-rendered, crawlable by default |
| Cache | AJAX endpoint responses need their own caching strategy | Uses normal page cache |
| Best for | Interactive refinement on already-landed users | States you WANT indexed as landing pages |

  Pattern that gets both: AJAX-update the results **and** push a clean, normalized URL via the History API so the state is shareable and (if allowlisted) crawlable.
- **Mobile:** filters in a slide-in drawer with an "Apply" action, not inline; show the applied-count on the trigger.
- **Applied-filter chips** above results (each removable) so shoppers can see and undo selections; include a "clear all."
- **Sort** (best-selling / price / newest / rating) is a *display* control — keep sort in a parameter you can strip from the canonical, never a separately indexable URL.
- **Pagination:** prefer numbered, crawlable pages over infinite scroll for indexable listings; "load more" is fine for UX but ensure the paginated set is still reachable via `<a href>` links for crawlers. Self-referencing canonicals per page (do NOT canonical page 2+ to page 1 — that hides deeper products).

## URL & State Strategy

- **Query parameters** (`?brand=acme&color=black`) are the pragmatic default in WooCommerce; **pretty paths** (`/shop/acme/black/`) look cleaner but are a double-edged sword (see caveat 5 below).
- **Normalize aggressively** so one logical state has exactly one URL:
  - Fix parameter **order** (alphabetical) and value case; collapse duplicates.
  - Drop empty/default params; strip tracking params from the canonical.
  - Decide a single delimiter for multi-select and stick to it.
- Preserve **history/back-button** behaviour via `pushState`/`replaceState`; make filter states **shareable** (the URL fully reconstructs the view).

## Indexability Allowlist (core)

Treat facet URLs as **allowlist, not blocklist**: index a small, curated set of demand-backed combinations as **landing pages**; everything else is thin and should stay out of the index.

- **Index-worthy** — single facets or proven double-facet combos with real search demand and unique, useful content (e.g. `/gaming-pcs/rtx-5070/`). Give them a self-referencing canonical, a tailored title/H1, and intro copy.
- **Thin / infinite** — 3+ stacked facets, sort orders, price sliders, near-empty combinations. Keep these out of the index.

**Decision matrix:**

| Combination | Internal links | Canonical | Meta robots | robots.txt |
|-------------|---------------|-----------|-------------|-----------|
| Curated landing facet | Yes (crawlable `<a>`) | Self | index,follow | Allow |
| Non-curated but low-volume | No | (n/a) | noindex,follow | Allow (so the noindex is seen) |
| Combinatorial explosion / sort / session params | No | — | — | Disallow the parameter pattern |

**NC4 caveats — non-negotiable, because each is a common way teams break their own site:**

1. **noindex requires the page to be crawlable to be seen** — Googlebot only honours a `noindex` if it can fetch the page and read the tag/header. A URL you both `Disallow` in robots.txt and mark `noindex` will keep the `noindex` **unread**.
2. **robots.txt disallow hides the noindex tag** — the two directives conflict. Disallowed URLs can still be indexed (URL-only, from links) precisely because the crawler never sees the `noindex`. Pick one mechanism per URL.
3. **canonical is only a hint** — `rel=canonical` is a suggestion Google may ignore; it consolidates signals, it does **not** guarantee the alternate is dropped, and it never stops crawling or serving of the variant.
4. **none of noindex/canonical/robots alone prevents origin load** — `noindex` and `canonical` still get crawled (they must be, to be read); `robots.txt` stops *Googlebot* fetching but not users, other bots, or your own AJAX calls. Controlling **crawl and cost** is a separate job from controlling **indexing** (next section).
5. **naive pretty-URL rewrites can make facets MORE crawlable** — rewriting `?brand=x&color=y` into `/brand-x/color-y/` turns parameter noise into clean, linkable, crawlable paths, multiplying the crawl surface. Pretty URLs are a *commitment to index*; use them only for the allowlisted set, never as a blanket rewrite.

## Crawl-Budget & Origin-Load Protection

Indexability keeps junk out of search; this keeps junk off your **server**. Co-design them — cacheability is not indexability.

- **GET-parameter normalization** (from URL & State): fewer distinct URLs = fewer crawl paths and higher cache hit-rate. Canonicalize order/case at the edge or in the app.
- **Cache-key design:** decide which parameters vary the cache. Ignore/normalize params that don't change output so `?color=black` and `?color=black&utm=x` hit one cached object — but only ignore params **proven** inert; dropping a real facet, currency, or customer-segment param serves wrong content or enables **cache poisoning**. Cloudflare "Cache Rules" + "Query String Sort" (normalize param order), Varnish's default hash on full `req.url` (normalize in VCL), and LiteSpeed's per-query-string copies ("Drop Query String" only for inert params) all need explicit configuration — the defaults over- or under-cache facets. Verify real `HIT/MISS/BYPASS` headers.
- **AJAX response caching:** filter AJAX endpoints bypass the page cache by default. Cache their JSON responses (object cache / transient / edge) keyed on the *normalized* facet set, or they become an uncached origin hit per interaction.
- **Internal-link discipline:** only allowlisted combinations get crawlable `<a href>` links. Render non-indexable filters as buttons/JS controls (not anchors) so you are not *advertising* crawl paths you then try to suppress.
- **Monitor:** watch GSC Crawl Stats and server logs for crawler time spent on parameter URLs; a spike there is the early signal of a crawl trap.

## Woo Query & DB Performance

High-cardinality attribute filtering is where WooCommerce falls over at the database.

- **`meta_query` is the trap.** Filtering on product attributes stored as post meta forces expensive `wp_postmeta` self-joins that scale badly with catalogue size and attribute count.
- **Use the attribute lookup table.** WooCommerce maintains **`wc_product_attributes_lookup`** — a flat, indexed table purpose-built for fast attribute filtering. (Version history, since it is widely misremembered: WC **3.6** introduced `wc_product_meta_lookup`; the **attribute** lookup table `wc_product_attributes_lookup` arrived experimentally in **WC 5.6** and became the default in **WC 6.3**. It is standard in WC 9.x/10.x.) Keep it regenerated (WooCommerce → Status → Tools) after bulk imports.
- **Cache expensive aggregations** (facet counts, price ranges) in transients / a persistent object cache (Redis/Memcached); recompute on product save, not per request.
- **When to offload:** past a few thousand products, or with many high-cardinality attributes and free-text search, move filtering/search to an external index — **ElasticPress** (Elasticsearch/OpenSearch) or **Algolia**. Keep **WooCommerce as the source of truth** and treat the index as a rebuildable projection. The mechanics of that offload (sync, keys, security) live in `woocommerce-developer` §Performance → Search Offload — do not duplicate them here.

## Build vs Plugin

| Option | When it fits | Watch for |
|--------|-------------|-----------|
| **FacetWP-class plugin** | You need fast time-to-value and it exposes the controls below | Verify it lets you control indexability + cache behaviour |
| **Custom build** | You need exact crawl-control / cache-key / index semantics | More engineering; you own the query strategy |

Evaluate any filter plugin against: (1) does it emit clean, normalizable URLs; (2) can you set canonical/noindex per facet state; (3) does it use the attribute lookup table (not raw `meta_query`); (4) how do its AJAX endpoints interact with your page cache and CDN; (5) does it let you withhold internal links from non-allowlisted combos.

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Expose every filter combination as a crawlable `<a href>` | Crawl trap + thin duplicates; only allowlisted combos get links |
| `Disallow` a URL in robots.txt AND rely on its `noindex` | The crawler never sees the `noindex` — the page can still get indexed |
| Blanket-rewrite `?params` into pretty paths | Multiplies the crawlable surface (caveat 5) |
| Canonical page 2+ back to page 1 | Hides deeper products from indexing |
| Trust `canonical`/`noindex` to cut server load | They must be crawled to work; crawl/cost control is separate |
| Filter high-cardinality attributes via raw `meta_query` | `wp_postmeta` self-joins melt at scale — use `wc_product_attributes_lookup` |
| Leave filter AJAX endpoints uncached | One uncached origin hit per interaction |
| Return a 200 empty page for an invalid/zero-result combo | Return `404` so crawlers drop it (Google faceted-nav guidance) |
| Duplicate the search-offload recipe here | It lives in `woocommerce-developer` — reference it |
