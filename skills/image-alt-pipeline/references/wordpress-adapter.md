# Reference adapter: WordPress with WooCommerce

## Contents

- The adapter contract (any platform)
- Where alt lives in WordPress
- What overrides alt at render time
- Inventory sources
- Snapshot
- Dry-run and apply over the REST API
- Dry-run and apply over WP-CLI
- Direct database write (when no Application Password exists)
- Inline block copies
- Rollback
- Cache purge and rendered-page verification
- Provenance

This is one platform's way of supplying what the pipeline stages need. Every fact was read on 2026-10-25
from the cited page. Test every command against a staging copy, never against the live site first.

## The adapter contract (any platform)

| Need | Example (WordPress) |
|---|---|
| List image assets with id, URL, modified time, current stored alt | REST `/wp/v2/media`, WP-CLI `wp post list` |
| Where each asset is used, and in which role | Featured and gallery fields, content parsing, crawl |
| Read and write one asset's stored alt | REST `alt_text`, post meta `_wp_attachment_image_alt` |
| Where alt is copied (inline content) and what overrides it at render time | Image block markup; theme, plugin and shop filters |
| Snapshot and restore of the values written | Targeted CSV plus a database export |
| Cache purge | Host, cache plugin and CDN purge |

A platform that cannot answer one of these rows is not ready for apply; run inventory and audit only.

## Where alt lives in WordPress

| Place | Storage | Source |
|---|---|---|
| Attachment alt | Post meta `_wp_attachment_image_alt` on the attachment post; `wp_get_attachment_image()` reads it with `trim(strip_tags(get_post_meta(...)))` | https://developer.wordpress.org/reference/functions/wp_get_attachment_image/ |
| Block editor Image block | The `alt` attribute is sourced from the `<img>` inside the saved `post_content` (default `""`). It is a copy made at insert time: **editing the attachment alt does not change existing Image blocks** | Gutenberg `packages/block-library/src/image/block.json` |
| Classic editor images | Plain `<img alt>` in `post_content`, also a copy | - |
| Theme and plugin images | Template code, theme settings, plugin data | - |

On upload WordPress sets the title from the file name, not the alt. WordPress 7.0 added
`wp_get_image_alttext()`, which fills alt from the image's embedded IPTC/XMP accessibility alt text when
present (https://developer.wordpress.org/reference/functions/wp_get_image_alttext/); otherwise alt
starts empty (https://developer.wordpress.org/reference/functions/media_handle_upload/). So a
file-name alt on a WordPress site was written by a person, an importer or a plugin.

## What overrides alt at render time

| Hook or behaviour | Effect | Source |
|---|---|---|
| `wp_get_attachment_image_attributes` filter, args `($attr, $attachment, $size)`, since 2.8.0 | Any theme or plugin can replace alt for every image rendered through `wp_get_attachment_image()`. This is also the place to add contextual alt at render time | https://developer.wordpress.org/reference/hooks/wp_get_attachment_image_attributes/ |
| `render_block_core/image` (`render_block_{$name}`), since 5.7.0; args `($block_content, $block)`, plus `$instance` since 5.9.0 | Can rewrite Image block HTML, including alt | https://developer.wordpress.org/reference/hooks/render_block_this-name/ |
| WooCommerce `wc_get_gallery_image_html()` | **Empty attachment alt falls back to the product name**, or "Product name - Image N" for later gallery images (`woocommerce_get_alt_from_product_title_and_position()`, since 9.3.3). So an empty stored alt does not render empty on product galleries | `plugins/woocommerce/includes/wc-template-functions.php` (trunk) |
| WooCommerce `woocommerce_gallery_image_html_attachment_image_params` filter, args `($params, $attachment_id, $image_size, $main_image)` | Changes the attributes, including alt, passed to `wp_get_attachment_image()` for gallery images | same |
| WooCommerce `woocommerce_single_product_image_thumbnail_html` filter, args `($html, $attachment_id)` | Final HTML of each single-product gallery image | `templates/single-product/product-image.php` |
| WooCommerce `WC_Product::get_image()` | Uses the stored alt, else the product name (loop and grid thumbnails) | `includes/abstracts/abstract-wc-product.php` |
| WooCommerce placeholder | Alt "Awaiting product image" | same templates |

Consequences for the pipeline:

- Audit on rendered pages: a WooCommerce product with empty stored alt shows the product name, so a DB
  audit over-reports missing alt and under-reports duplicates (every gallery image on that product
  gets the same name or "name - Image N").
- A shared attachment with generic-but-true alt plus WooCommerce's product context gives a reasonable
  result only if the stored alt is set; WooCommerce's fallback applies only when it is empty.
- Contextual render-time alt belongs in a small, tested filter on `wp_get_attachment_image_attributes`
  or the WooCommerce gallery filter, owned in the theme or a site plugin, not in the pipeline.

## Inventory sources

| Need | Read-only command or request |
|---|---|
| All image attachments | `wp post list --post_type=attachment --post_mime_type=image --fields=ID,post_title,guid,post_modified --format=csv` (https://developer.wordpress.org/cli/commands/post/list/) |
| Current alt | `wp post meta get <id> _wp_attachment_image_alt`, or REST `GET /wp-json/wp/v2/media?media_type=image&per_page=100&page=N&context=edit&_fields=id,alt_text,source_url,modified,post` |
| Size files of one attachment | Attachment meta `_wp_attachment_metadata` (`file`, `sizes`; the `-scaled` original keeps `original_image`). In-use is per attachment; size files on disk missing from this meta are orphans |
| Featured images | Post meta `_thumbnail_id` on posts and products |
| Woo galleries | Product meta `_product_image_gallery` (comma-separated attachment ids); count `publish` and `draft` products separately |
| Inline images | Parse `post_content` for `wp-image-<id>` classes (which link an inline copy to its attachment) and for `wp-content/uploads/` paths |
| Site-wide images | Options `site_icon`, theme mod `custom_logo`, WooCommerce option `woocommerce_placeholder_image` |
| Term thumbnails | Term meta `thumbnail_id` (product category images) |
| Theme code | Search the theme (and child theme) for hard-coded `wp-content/uploads/` paths and bundled image files: these are theme-file images with no attachment to write |
| Duplicate uploads | WordPress appends `-1`, `-2` ... to a repeated file name and `-scaled` to large originals; size files carry `-WxH`. Strip these to group, then hash the original file |
| Assets to skip | Option `site_icon` and WooCommerce option `woocommerce_placeholder_image` name attachments that get no pipeline alt |
| Rendered truth | Seed the crawl from the core sitemap `wp-sitemap.xml` (or the SEO plugin's sitemap); one product page per distinct main or gallery image covers product imagery |

## Snapshot

Before any apply: export what will change and test that it restores.

- Targeted: write a CSV of `attachment_id, current_alt` for every row in the approved plan (the
  dry-run already holds this; re-read it at apply time).
- Whole: `wp db export <file> --tables=<prefix>postmeta,<prefix>posts` (https://developer.wordpress.org/cli/commands/db/export/),
  plus the host's own backup. Store it off the web root.
- Restore-test the targeted snapshot on staging before the first production apply.

## Dry-run and apply over the REST API

- Auth: Application Passwords (core since 5.6), HTTP Basic over HTTPS only, for a user with rights to
  edit media (https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/). Read the
  credentials from the environment; never put them in the plan, prompts or logs.
- Dry-run: `GET /wp-json/wp/v2/media/<id>?context=edit&_fields=id,alt_text,modified` for each plan row;
  write the current value and the proposed value to the plan; send nothing.
- Apply: for each approved row, re-read `alt_text` (and the file's `modified` time); if either differs
  from the dry-run, skip and log `changed_since_dry_run`. Otherwise `POST /wp-json/wp/v2/media/<id>`
  with JSON `{"alt_text": "<approved alt>"}` (https://developer.wordpress.org/rest-api/reference/media/).
  Log the response's `alt_text`.
- The REST update writes the meta unconditionally: there is no compare-and-set. Agree an editing freeze
  on media with the owner for the apply window, keep the window short (chunks), and after the run compare
  every row's current alt with the log; a mismatch is a collision for a person.
- Pace requests (a few per second) and stop on the first unexpected 4xx or 5xx.

## Dry-run and apply over WP-CLI

- Dry-run: `wp post meta get <id> _wp_attachment_image_alt` per row, compare, write the plan.
- Apply: `wp post meta update <id> _wp_attachment_image_alt "<approved alt>"`
  (https://developer.wordpress.org/cli/commands/post/meta/update/). Quote and escape the value; pass it
  through a file or stdin when it contains quotes.
- WP-CLI runs as a shell on the server and bypasses REST permissions; use it only where the owner
  already grants shell access, and with the same re-read-before-write check.

## Direct database write (when no Application Password exists)

WooCommerce REST keys (consumer key and secret) do not authorise the core media endpoint. Where they are
the only credential and WP-CLI is not available, alt can be written to `wp_postmeta`
(`meta_key = '_wp_attachment_image_alt'`) directly. Same safety, stricter conditions:

- **Owner's explicit approval** for a production database write, separate from approving the alt text.
- **Prove it first on a local or staging copy**: write, roll back and re-apply the full plan there,
  and compare row counts each time.
- Per row, inside one transaction: `SELECT meta_value ... FOR UPDATE` on the attachment's row, compare
  with the dry-run value, skip on difference, then `UPDATE` (or `INSERT` when the row is absent); write a
  provenance meta row (for example `_alt_pipeline_run`) in the same transaction.
- Targeted snapshot before the run; rollback restores only rows still holding the pipeline's text.
- It **bypasses WordPress hooks and the object cache**: plugins that react to meta changes do not run,
  and a persistent object cache keeps serving the old value. Flush the object cache and the page and
  CDN caches afterwards, then verify on rendered pages.

## Inline block copies

Fixing the attachment does not fix Image blocks already placed in content. Either:

1. Leave inline copies alone and report them (the safe default), or
2. As a separate, separately approved plan, rewrite the `alt` inside the stored block markup for blocks
   whose `id` matches the attachment and whose inline alt is empty or a machine pattern. Edit through the
   editor or the posts REST endpoint so revisions are kept; never by SQL string replacement.

## Rollback

Restore a written row's previous value from the targeted snapshot only if its current alt still equals
the value the pipeline logged as written; a row edited since is a conflict, listed for a person and not
touched. Use the same path used to apply (REST or WP-CLI), then purge caches and re-verify. Restoring the
database export is a separate recovery, decided by the owner, because it also reverts every other change
made to those tables since the export.

## Cache purge and rendered-page verification

1. Purge the page cache, the object cache if a persistent one is used, and the CDN for the affected
   pages (with LiteSpeed, Cloudflare or a host panel, use its documented purge; see `hostinger-hosting`
   for one host's tools).
2. Crawl every page in the written rows' `use_sites` (cap per attachment for huge use counts and sample
   the rest).
3. For each image, compare the rendered alt with the written alt. A mismatch means a filter, a block
   copy or a plugin is overriding it: record which, and route to review.
4. Re-run the `image-alt-text` audit rubric on the crawl to confirm findings went down.

## Provenance

Record every pipeline write so later runs can tell machine from human alt: a log file of
`run_id, attachment_id, previous_alt, written_alt, model, approved_by, time`, and optionally an
attachment meta key such as `_alt_pipeline_run` set at apply time. A later human edit leaves the meta
in place but changes the alt; compare the alt with the logged `written_alt` to detect it.
