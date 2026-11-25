# Implementation, caching and verification

Owned by `markdown-for-agents`. The facts that date are anchored in `SKILL.md`.

## `/llms.txt`: what a correct one looks like

Root-level markdown. An **index and orientation file**, not a dump.

```markdown
# <Site name>

> One paragraph an agent can quote: what you sell, to whom, the honest price
> range, and the single thing that distinguishes you.

## What we sell
- [Category](https://example.com/cat/) - what it is, real price range

## How to buy
- Build/lead time, delivery, returns window, warranty terms

## Key pages
- [Page](https://example.com/page) - one line on why it matters
```

| Do | Don't |
|---|---|
| Keep it **small**, a few KB | Enumerate every URL (that is `sitemap.xml`) |
| Use **absolute** URLs | Use relative links; they resolve against the consumer's base and 404 |
| Describe the **distribution** of your prices | Lead with an unrepresentative cheapest item |
| Group by how a buyer chooses | Group by database structure |
| Link content pages | List `/cart/`, `/checkout/`, `/my-account/`, `/wp-admin/` |
| Regenerate from the **same query** that feeds your pages | Hand-maintain it and let it drift |

`llms-full.txt` (the whole site inlined) is usually not worth it: it duplicates per-page markdown,
cannot be cached per page and is stale on the next change.

## WordPress / WooCommerce

Render from the data layer, not from the theme output.

```php
// 1) Register the .md representation on the same rewrite as the page.
add_action('init', function () {
    add_rewrite_endpoint('md', EP_PERMALINK | EP_PAGES);
});

// 2) Emit markdown built from post/product data - the same source the template uses.
add_action('template_redirect', function () {
    if (!isset($GLOBALS['wp_query']->query_vars['md'])) return;

    $post = get_queried_object();
    if (!$post instanceof WP_Post) return;

    nocache_headers();
    header('Content-Type: text/markdown; charset=utf-8');
    header('X-Robots-Tag: noindex');            // the HTML page is the indexable one
    echo tch_render_markdown($post);            // pure function: post -> markdown
    exit;
});
```

- `tch_render_markdown()` must be a **pure function** of the post or product, unit-testable without
  a web server.
- For products read `wc_get_product()`: `get_price_html()` for the displayed price, attributes for
  the spec table, `get_description()` for prose. **Do not scrape your own HTML.**
- `X-Robots-Tag: noindex`, `<link rel="canonical">` to the HTML page, and keep `.md` URLs out of
  `sitemap.xml`.
- Flush rewrite rules once on activation, never per request.

## Edge / CDN

On Cloudflare, **Markdown for Agents** converts HTML to markdown at the edge on
`Accept: text/markdown` with no origin change (Pro plan and above). It converts *rendered HTML*, so
template defects travel into the markdown, and **it emits `content-signal: ai-train=yes,
search=yes, ai-input=yes` unless the origin sets its own**, and the origin header takes precedence
(Cloudflare docs, checked live 2026-09-27). Send the owner's own signal from the origin before
enabling it. `ai-train` is the owner's answer to the training question (yes / no; "yes" is recommended, the owner decides;
policy: `ai-search-optimizer/references/crawlers.md`, "One training policy"). The "no" form:

```php
// Every response, HTML and markdown alike. ai-train is the owner's answer: no here, yes for a "yes".
add_action('send_headers', function () {
    header('Content-Signal: search=yes, ai-input=yes, ai-train=no');
});
```

and in robots.txt, on any host: `Content-Signal: search=yes, ai-input=yes, ai-train=no` in the
`User-agent: *` group (`ai-train=yes` for a "yes"; the robots file and the header always agree). Rendering from the data layer is better than edge conversion where you can.

## Caching

- Suffix routing: cache `.md` like the HTML page and **purge both on the same event**.
- Negotiation: `Vary: Accept` on every negotiated response, and prove it survives the CDN through
  the public hostname.
- Whatever purges the page cache after a deploy must purge the markdown too. Automate a manual
  purge before shipping the markdown.

## Verifying it works

```bash
# 1) The .md representation exists and is markdown, not an HTML error page
curl -sSI https://example.com/product/thing.md | grep -i '^content-type'
# 2) Content negotiation, if implemented
curl -sS -H 'Accept: text/markdown' https://example.com/product/thing | head -20
# 3) Vary is present AND survives the CDN (public hostname)
curl -sSI -H 'Accept: text/markdown' https://example.com/product/thing | grep -i '^vary'
# 4) The number that justifies the work
curl -sS https://example.com/product/thing    | wc -c
curl -sS https://example.com/product/thing.md | wc -c
# 5) The content signal you actually send (edge conversion adds one if you do not)
curl -sSI -H 'Accept: text/markdown' https://example.com/product/thing | grep -i '^content-signal'
```

**Automate a divergence test:** fetch both representations and assert price, availability and title
match. Run it in CI and after every deploy.

**Measure token reduction, not rankings.** Byte and token counts are attributable to this work;
citation counts are not.
