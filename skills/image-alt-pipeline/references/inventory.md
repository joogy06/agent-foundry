# Inventory, dedupe, classification and re-runs

## Contents

- Sources of image use
- The in-use test: three sources that agree
- Images loaded by script
- Assets to skip
- Theme-file images
- The inventory row
- Size files are not images
- Dedupe: by id, then by content
- Duplicate re-uploads
- Classifying current alt
- Use counts and priority
- Incremental re-runs

## Sources of image use

An image matters if a visitor can see it. Build the inventory from where images are used, not from what
was uploaded: a media library holds unused files and misses template assets.

| Source | How it is found | Alt lives in | Fixable by stored alt? |
|---|---|---|---|
| Media library (attachments, assets) | Platform API or database listing | Attachment record | Yes |
| Featured / primary image of a post or product | Relationship field on the item | Attachment record, unless the template overrides | Yes |
| Product gallery images | Gallery list on the product | Attachment record, unless the template overrides | Yes |
| Variant images | Variant records | Attachment record | Yes |
| Inline images in content | Parse the stored content HTML (`<img>`, image blocks, builder JSON) | Usually a copy inside the content HTML, written at insert time | No: the inline copy needs its own edit |
| Theme and template assets (logo, icons, badges, banners) | Template files, theme settings, widget and menu settings | Template code or a theme setting | Only through the template or setting |
| Plugin-rendered images (sliders, mega menus, review widgets, page builders) | Plugin settings and data | Plugin data | Per plugin |
| CSS backgrounds | Stylesheets and inline `style` attributes with `background-image` | Nowhere: CSS images have no alt | No: flag for text or `<img>` |
| Externally hosted images (CDN, marketplace feeds) | Rendered page crawl | Where the HTML is produced | Depends |

Cross-check the database inventory with a crawl of rendered pages. Images seen only in the crawl reveal
sources the listing missed.

## Images loaded by script

A crawl that reads only `<img src>` misses carousels, pop-up galleries and lazy loaders. Also parse
`srcset` and every `data-*` attribute that holds image URLs (`data-src`, `data-lazy-src`,
`data-gallery`, JSON in attributes such as `data-images`), and resolve each URL back to its asset. In one
field run (2026-10-26) a single home-page carousel held 188 pop-up gallery photos in one JSON attribute
that a plain crawl never saw. Request every URL found and record failures: the same check found three
of those photos returning 404.

## Assets to skip

Some assets are in use but must not get stored alt from the pipeline: the **site icon** (favicon; shown
by browsers, not in page content) and the shop's **placeholder image** (shown when a product has none;
the platform supplies its own alt). Exclude them from drafting and write-back, and say so in the plan.

## The in-use test: three sources that agree

Whether an image is in use is decided by three sources, and they must agree:

1. **Content references in the database**: main and gallery images of items (counting published and
   draft items separately: an image used only by drafts is not visible), images inline in content (by
   asset id and by file path), site-wide settings (site icon, logo, the shop's placeholder image),
   category and term thumbnails.
2. **A search of the theme and template code** for hard-coded upload paths. A home-page hero or banner
   is often referenced only from template code, with no database link at all.
3. **A rendered crawl.** Seed it from the platform's own sitemap and crawl one page per distinct image
   (one item page per main or gallery picture), not every page; add the home page, category pages and
   templates that show site-wide images.

An asset with no database reference is a **candidate** for "unused", never "unused": in one catalogue a
quarter of all image attachments had no database reference, and at least one of them was the live
home-page hero, used only from theme code. Only all three sources agreeing makes an asset unused.

## Theme-file images

Banners, logos and icons are often files in the theme, not assets in the media library. There is no
stored alt to write: the pipeline drafts their alt the same way, then **hands the drafts to whoever owns
the theme code** (a separate repository or team, often) as a change request, and never writes them
itself.

## The inventory row

`attachment_id | file_url | sha256 | width | height | mime | current_alt | alt_source (human|machine|unknown|empty) | uses (count) | use_sites (page ids or URLs, capped) | use_roles (featured|gallery|inline|template|link|css) | in_link | product_ids | last_modified`

`use_roles` matters for drafting: an image that appears inside a link needs functional alt, a gallery
image needs the shot-specific pattern, an inline copy needs a content edit, not an attachment edit.

## Size files are not images

A platform generates several size files per uploaded image (thumbnails, medium, large, a scaled
original), listed in the asset's own metadata. They are renditions of one asset, with one stored alt.
**In-use is decided per asset, never per size file**: "is this the same image at different sizes?" is
answered by the asset's metadata. Size files on disk that no asset lists are orphans; finding them is a
disk-versus-metadata comparison and a storage clean-up concern, not an alt concern.

## Dedupe: by id, then by content

1. **By attachment id.** All uses of one attachment collapse to one row for *analysis*: the image is
   described once. Keep every use (occurrence) with its own context: role, link, adjacent text, language.
   The stored alt is one value, so it is written for the attachment's main content use; uses that need
   something else (decorative, functional, another language) are queued as template or content edits,
   not forced into the stored alt.
2. **By content hash.** Hash the original file bytes (SHA-256). Different ids with the same hash are
   the same picture uploaded more than once. Analyse once; reuse an accepted alt only on ids whose uses
   are equivalent (same role, same language, no conflicting adjacent text). Report the duplicates to the
   owner as clean-up candidates.
3. **Near duplicates** (same photo, recompressed or resized). After the exact hash, run a cheap
   perceptual check: scale both images to 48 px, convert to greyscale, and compare the mean absolute
   pixel difference. Under about 0.3 on a 0 to 255 scale is the same photo (field measure 2026-10-26:
   same-name re-uploads with different bytes were recompressions at this level), with no
   perceptual-hash library needed. Above it, treat a match as a suggestion for review, never as
   automatic reuse.

Hash the original upload, not generated thumbnails: platforms create several sizes per upload, and each
size has different bytes.

## Duplicate re-uploads

On catalogue sites, the same picture uploaded again and again (once per import batch, once per product)
is often most of the library: one catalogue had 789 attachments referenced by published products but
only about 110 distinct pictures.

1. **Group candidates by name**: strip the platform's de-duplication suffixes (a trailing `-1`, `-2`
   ...), the scaled-original suffix and size suffixes (`-1024x1024`) from the original file name.
2. **Confirm by hash** of the original file's bytes. Only a hash match makes two assets the same picture.
3. **Never merge on name alone.** Same name, different bytes happens: re-exports at the same pixel size
   with a different file size, or uploads made under different settings that even produced different
   size sets. A name group with several hashes is several pictures.

## Classifying current alt

| Class | Test | Action |
|---|---|---|
| Human | Non-empty, not a machine pattern, not written by this pipeline | Keep. Never queued for rewrite; may be audited and flagged for a person |
| Machine: ours | Provenance shows an earlier run of this pipeline | Re-draft only if the house style or model changed and the owner asks |
| Candidate: file name | Equals the file's base name or matches camera patterns (rubric A4 in `image-alt-text`) | Review candidate |
| Candidate: placeholder / boilerplate | Rubric A5, A6 | Review candidate |
| Missing | No alt value stored | Queue |
| Empty | `""` stored | Queue unless a recorded human decision says decorative; the draft may also conclude decorative and keep `""` |

Patterns only **nominate** candidates; they never prove machine provenance. A candidate is replaced
only when the owner approves its class in the plan (for example, "every alt that equals the file name
exactly") or provenance records show a machine wrote it; any other non-empty alt is human. A false
"human" costs a missed fix; a false "machine" destroys someone's work. A recorded human decision to use
`alt=""` is human alt too.

## Use counts and priority

Sort the queue by visible impact:

1. Images inside links and buttons with empty or file-name alt (functional failures).
2. Highest rendered-occurrence count (a shared badge on every product page).
3. Product main images, then galleries, then content images.
4. Everything else.

High-use images also go to human review regardless of confidence (see the review queue rules), because
one wrong stored alt is heard on every page that uses it.

## Incremental re-runs

- Keep a watermark: the run id and the latest `last_modified` time processed, plus the set of
  attachment ids written.
- Store a context fingerprint per attachment: the hash of its file bytes plus its set of uses (page,
  role, link, product ids, adjacent text, language).
- A re-run processes attachments created or modified after the watermark, attachments whose
  fingerprint changed (new use, new role, changed nearby text or language, replaced file), and rows that
  were deferred to review and since approved.
- Reconcile in full periodically (monthly, or after a theme or template change), because some context
  changes leave no trace on the attachment itself.
- Never re-draft an attachment whose current alt a person changed after the pipeline wrote it; the
  change makes it human.
