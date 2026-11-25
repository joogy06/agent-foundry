# Internal linking, site architecture and sitemaps

Owned by `seo-structure-architect`; moved out of SKILL.md to keep it short.

## Internal Linking

**Topic clusters remain the standard.** Pages with more contextual internal links tend to get more traffic (Zyppy internal-link study; treat as directional, no date recorded).

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
- Faceted/filter URLs need explicit crawl control — parameter combinations can explode crawl paths and create thin duplicates. See `woocommerce-faceted-navigation` for the index-worthy-vs-thin allowlist and the canonical/noindex/robots decision matrix.

## XML Sitemaps

- Max 50,000 URLs per file, 50MB uncompressed. Use sitemap index for larger sites
- **Google ignores `<priority>` and `<changefreq>`** completely — only `<lastmod>` matters
- `<lastmod>` must accurately reflect genuine content changes — fake dates hurt
- Only include indexable, canonical, 200-status URLs
