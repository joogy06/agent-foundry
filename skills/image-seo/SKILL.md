---
name: image-seo
description: "Image SEO signals: filenames, alt text as a ranking signal, captions and page context, Product and Article image markup, image sitemaps, indexable image markup, Merchant Center image rules. Use when images must rank, index or pass a product feed."
license: MIT
metadata:
  version: "1.0.0"
  family: "image"
  family_parent: "image-alt-text"
---

# image-seo

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: google-image-seo
    source_url: https://developers.google.com/search/docs/appearance/google-images
    verified_on: 2026-10-25
    review_by: 2027-04-25
    claim: "Page updated 2026-03-02: alt useful, information-rich, in context, stuffing may be seen as spam; short descriptive filenames; Google does not index CSS images; img src (srcset and picture need a src fallback); formats BMP, GIF, JPEG, PNG, WebP, SVG, AVIF; same URL for the same image."
  - kind: external_fact
    subject: google-image-sitemaps
    source_url: https://developers.google.com/search/docs/crawling-indexing/sitemaps/image-sitemaps
    verified_on: 2026-10-25
    review_by: 2027-04-25
    claim: "image:image and image:loc only; up to 1,000 images per page URL; caption, title, geo_location and license tags deprecated in 2022."
  - kind: external_fact
    subject: merchant-center-image-link
    source_url: https://support.google.com/merchants/answer/6324350
    verified_on: 2026-10-25
    review_by: 2027-04-25
    claim: "image_link at least 500x500 px for all categories (warnings from 2026-04-14, enforced from 2027-01-31; answer 16989427), about 1500x1500 recommended, at most 64 MP and 16 MB; no overlays, prices, CTAs, watermarks, logos, store names, borders or placeholders; up to 10 additional_image_link."
-->

## Overview

Images are found through the page that shows them. Search engines read the `<img>` element, its alt,
the file name, the text around it and the structured data that names it, then decide whether the image
is worth showing. This skill covers those signals and the image rules of product feeds. It defers to two
siblings for what they own and does not restate them:

| Topic | Owner |
|---|---|
| Whether a schema type earns a rich result (the schema-status table), Product and Organization markup as a whole, XML sitemap rules in general, Core Web Vitals | `seo-structure-architect` |
| Merchant Center feed path (Merchant API), conversational attributes, AI surfaces and AI crawler policy | `ai-search-optimizer` |
| Writing the alt text itself | `image-alt-text` |
| Bulk alt generation and write-back | `image-alt-pipeline` |
| `og:image` and social card specs | `seo-meta-optimizer` |

## When to Use

- Product or article images do not appear in Google Images, or the wrong image shows in results.
- Planning file naming, image markup, captions or an image sitemap for a site.
- Merchant Center disapproves or limits products for image reasons.
- Checking that images a template renders are indexable at all.

## The signals, in order of effect

| Signal | Rule | Source |
|---|---|---|
| Indexable markup | Use `<img src>` (or `<picture>` with an `<img>` fallback). "Google doesn't index CSS images." Lazy-loaded images must get their `src` when they enter the viewport without a scroll or click; do not lazy-load images likely to be visible on first load | Google image SEO guide; Google lazy-loading guide |
| Page context | The image sits near text about the same thing; the page title and headings describe it. A product image belongs on that product's page | Google image SEO guide |
| Alt text | Google uses alt together with computer vision and page content. Useful, information-rich, in context; keyword stuffing harms the page. Write it to the `image-alt-text` standard; that standard already serves search | Google image SEO guide |
| File name | "Short, but descriptive": `acme-x200-office-chair-black.jpg`, not `IMG00023.JPG`. Translate file names of localised images where they use non-Latin or special characters | Google image SEO guide |
| Captions | Text near the image, a `<figcaption>`, is used to understand it | Google image SEO guide |
| Structured data | `image` is required in merchant listing markup and recommended in Article; URLs crawlable and indexable, the image must depict the marked-up item; give several images of at least 50,000 pixels (width x height) in 16x9, 4x3 and 1x1. Which types earn rich results: `seo-structure-architect` | Google merchant listing and Article docs |
| Image sitemap | Helps discovery of images Google might miss (loaded by script, on a CDN). Not a ranking factor | Google image sitemaps doc |
| URL stability | Keep the same URL for the same image; changing it (cache busting, CDN renames) makes Google recrawl and reindex | Google image SEO guide |
| Responsive images | `srcset` and `sizes`, or `<picture>`, with an `<img>` fallback that has `src` and alt | Google image SEO guide |
| Format | BMP, GIF, JPEG, PNG, WebP, SVG and AVIF are supported; the file extension should match the type | Google image SEO guide |
| Preview size | `max-image-preview:large` robots setting allows large previews in Discover and results; syntax lives in `seo-meta-optimizer` | Google robots meta doc |
| Licence metadata | Image metadata markup needs `contentUrl` plus one of `creator`, `creditText`, `copyrightNotice` or `license`; the **Licensable badge requires `license`** (or the IPTC Web Statement of Rights field); markup wins over IPTC on conflict | Google image licence metadata doc |

Bing: its webmaster guidelines could not be read from a primary source on 2026-10-25 (UNCERTAIN); Bing
Webmaster Tools' own help text asks for alt that is "descriptive, specific, and accurate", which the same
standard meets.

Speed matters for the page, not for image indexing: compress and size images for Core Web Vitals
(`seo-structure-architect` owns the thresholds), but a slow image is still indexed.

## Alt text as a search signal

The `image-alt-text` standard is also the search standard: describe what the image shows in the
context of the page, use the product's real name, do not repeat keywords. There is no separate "SEO alt"
to write. Two search-specific points:

- An image inside a link: its alt acts as the link's anchor text.
- Boilerplate alt on every image (the site name) tells search nothing and may read as low-quality.

## Image sitemaps (short form)

```xml
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
  <url>
    <loc>https://example.com/products/acme-x200</loc>
    <image:image><image:loc>https://cdn.example.com/acme-x200-black.jpg</image:loc></image:image>
  </url>
</urlset>
```

Only `image:image` and `image:loc` remain; the 2022 deprecations and limits, plus CDN rules:
[references/sitemaps-and-feeds.md](references/sitemaps-and-feeds.md).

## Product feed image rules

Merchant Center (and similar shopping feeds) judge the image file, not its alt. Key Google rules: a
real photo of the product; no superimposed promotional text, prices, calls to action, watermarks, added
logos or store names, borders or placeholders (branding physically on the product is fine); **at least 500 x 500 pixels for every category, enforced from 2027-01-31** (warnings
since 2026-04-14; the older 100 x 100 and 250 x 250 apparel minimums apply until then); at most 64
megapixels and 16 MB; up to 10 additional images. Disapproval rules, recommended sizes and reuse of one photo across many products:
[references/sitemaps-and-feeds.md](references/sitemaps-and-feeds.md). The feed transport (Merchant API) is `ai-search-optimizer`.

## Anti-patterns

| Don't | Why |
|---|---|
| Put product images in CSS backgrounds | Google does not index CSS images, and they have no alt |
| Lazy-load with `data-src` only | The image never has a crawlable `src` in the rendered DOM |
| Write a separate keyword alt "for SEO" | The accessibility standard is the search standard; stuffing harms the page |
| Rename image URLs on every deploy | Google re-crawls and may drop the indexed image |
| Rely on the image sitemap to rank | It aids discovery only |
| Add `image:caption` or `image:title` to a sitemap | Deprecated in 2022 and ignored |
| Send banners with "SALE" text as the feed image | Promotional elements cause an image disapproval |
| Assume today's small feed images stay valid | 500 x 500 becomes the minimum for every category on 2027-01-31 |
| Restate schema-status or feed-path rules here | They are owned by `seo-structure-architect` and `ai-search-optimizer`; copies drift |
