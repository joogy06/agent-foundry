---
name: image-alt-pipeline
description: "Alt text automation at catalogue scale: image inventory, dedupe, vision-model drafts with guards, review queue, dry-run then apply, snapshot and rollback, rendered-page verification. Use when filling or fixing alt text across a site."
license: MIT
metadata:
  version: "1.0.0"
  family: "image"
  family_parent: "image-alt-text"
---

# image-alt-pipeline

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: vision-cost-model
    source_url: https://platform.claude.com/docs/en/about-claude/pricing
    verified_on: 2026-10-25
    review_by: 2027-01-25
    claim: "Cost-per-1k-images table in references/drafting-and-guards.md: Claude, OpenAI and Gemini (Vertex AI) per-token prices, image token rules and 50% batch discounts as read on 2026-10-25; Gemini 3.8 Flash introductory price ends 2026-12-31."
  - kind: external_fact
    subject: wp-rest-media-alt-text
    source_url: https://developer.wordpress.org/rest-api/reference/media/
    verified_on: 2026-10-25
    review_by: 2027-10-25
    claim: "WordPress REST /wp/v2/media exposes alt_text (string, view/edit/embed) and accepts it on POST /wp/v2/media/<id>; Application Passwords in core since 5.6."
  - kind: external_fact
    subject: woocommerce-empty-alt-fallback
    source_url: https://github.com/woocommerce/woocommerce/blob/trunk/plugins/woocommerce/includes/wc-template-functions.php
    verified_on: 2026-10-25
    review_by: 2027-04-25
    claim: "wc_get_gallery_image_html falls back to the product name (or 'name - Image N') when attachment alt is empty, via woocommerce_get_alt_from_product_title_and_position (since 9.3.3)."
  - kind: external_fact
    subject: claude-image-tokens
    source_url: https://platform.claude.com/docs/en/build-with-claude/vision
    verified_on: 2026-10-25
    review_by: 2027-01-25
    claim: "Claude image tokens are ceil(w/28) x ceil(h/28) patches; 1024x1024 = 1,369 tokens."
  - kind: external_fact
    subject: recommended-default-model
    source_url: https://developers.openai.com/api/docs/pricing
    verified_on: 2026-10-26
    review_by: 2027-01-26
    claim: "Recommended default gpt-6-luna at $0.10 / $0.50 per 1M tokens (about $0.20 per 1k images, $0.10 batched, field measure); re-run the sample when models or prices change."
-->

## Overview

A pipeline that drafts, checks and writes alt text for every image a site actually shows, without
overwriting what people wrote and without inventing facts. The wording standard is `image-alt-text`;
this skill is the machinery around it. It is platform-neutral: each stage names what it needs from the
platform, and a reference adapter for WordPress with WooCommerce shows one way to supply it
([references/wordpress-adapter.md](references/wordpress-adapter.md)).

This is a knowledge skill. It ships no executable pipeline. Build the stages in the site's own tooling,
small and tested, and keep each stage's output as a file a person can read.

## When to Use

- A site has hundreds or thousands of images with missing, file-name or boilerplate alt.
- Alt text is to be drafted by a vision model and written back in bulk.
- A previous bulk run needs auditing, re-running for new images, or rolling back.

Not for: wording one image (`image-alt-text`), image ranking and sitemaps (`image-seo`).

## Production rule: plan, dry-run, apply

**No write to a production site without the owner's explicit approval of a dry-run.** The order is
fixed and each step produces a file:

| Step | Output | Gate |
|---|---|---|
| 1 Plan | Scope, sources, model, budget, guard settings, rollback method | Owner reads it |
| 2 Dry-run | `writeback-plan` file: one row per attachment with current alt, proposed alt, file hash, context fingerprint, reason, confidence, action (`write`, `skip`, `review`) | Owner approves this exact file (record its hash) |
| 3 Apply | Writes only the approved rows, after a fresh snapshot, with editing of those assets paused | Refuses if the plan hash changed; skips a row whose current alt, file hash or context fingerprint changed since the dry-run |
| 4 Verify | Rendered-page crawl report | Failures go back to review |

Run steps 2 and 3 against a staging copy first whenever one exists. A test or staging site, never the
live site, is where write paths are first exercised.

## Stages

| # | Stage | Does | Detail |
|---|---|---|---|
| 1 | Inventory | Every image actually used, per asset (size files are renditions): media library, featured and gallery images, inline content images, site-wide settings, theme files, CSS backgrounds (flagged). In use only when database references, a theme-code search and a rendered crawl agree | [references/inventory.md](references/inventory.md) |
| 2 | Use counts and dedupe | One row per attachment id; content hash to find the same file uploaded twice; use count and list of pages per row | [references/inventory.md](references/inventory.md) |
| 3 | Classify | Keep human alt; queue missing, file-name, placeholder and boilerplate alt (the rubric in `image-alt-text`) | [references/inventory.md](references/inventory.md) |
| 4 | Context | For each queued image: product names and attributes from catalogue data, page type, caption, nearby heading, whether it sits in a link | [references/drafting-and-guards.md](references/drafting-and-guards.md) |
| 5 | Draft | Vision model writes alt to the house style with the context; returns alt, decorative flag, confidence, the facts it used | [references/drafting-and-guards.md](references/drafting-and-guards.md) |
| 6 | Guards | Length, banned phrases, unsupported facts, duplicates, language; failures to review | [references/drafting-and-guards.md](references/drafting-and-guards.md) |
| 7 | Review queue | Guard failures, high use count, shared attachments, unconfirmed image facts, judgement findings, plus a random sample of passing drafts (model confidence is not a filter) | [references/drafting-and-guards.md](references/drafting-and-guards.md) |
| 8 | Dry-run | The write-back plan file | this file, above |
| 9 | Apply | Snapshot, re-read, write approved rows, log every write (rules below) | WordPress example: [references/wordpress-adapter.md](references/wordpress-adapter.md) |
| 10 | Verify | Purge page, object and CDN caches; crawl rendered pages; compare rendered alt with written alt | WordPress example: [references/wordpress-adapter.md](references/wordpress-adapter.md) |
| 11 | Re-run | Incremental: only new or changed attachments since the last run's watermark | [references/inventory.md](references/inventory.md) |

## Hard rules

1. **Never overwrite human-set alt.** A non-empty alt that is not a known machine pattern (file name,
   placeholder, an alt this pipeline wrote) is kept. The apply step re-reads the current value and skips
   the row if it changed since the dry-run. Most platforms have no compare-and-set write for alt, so a
   re-read narrows but does not close the race: pause editing of the affected assets during apply, and
   re-read after each write to catch a collision. Record provenance for every written alt (run id, model,
   date) in a field or log the platform keeps, so a later run can tell its own work from a person's.
2. **No hallucinated specifications.** Brand, model, numbers and claims only when visible in the image
   or present in the catalogue data supplied for that image. The draft must list the facts it used and
   where each came from; a fact with no source fails the guard, and a brand, model or number the model
   says it read from the image goes to human review unless a separate check (text recognition, catalogue
   match) confirms it.
3. **Shared images get generic-but-true alt.** An attachment used by more than one product never gets
   one product's name stored on it (`image-alt-text`, reused images).
4. **Snapshot before apply, and test the rollback.** A snapshot that has never been restored is not a
   rollback plan. Rollback restores only rows whose current alt still equals what the pipeline wrote;
   anything edited since is a conflict for a person, never overwritten.
5. **Idempotent.** Running the same approved plan twice writes nothing the second time.
6. **Verify on rendered pages.** A successful API write is not proof; themes and plugins can override it.
7. **No secrets in prompts, plans or logs.** Credentials are read from the environment at apply time.
8. **Theme-file images are drafted, not written.** Banners, logos and icons that live in theme code have
   no stored alt; their drafts go to the theme code's owner as a change request.
9. **Skip the site icon and the shop placeholder image**: they are in use but get no pipeline alt.
10. **"No database reference" means candidate, not unused.** Never report or delete an asset as unused
   until database references, theme code and a rendered crawl all agree.

## Platform adapters

An adapter supplies six things: an asset listing with stored alt, where each asset is used and how, a
read and a write of one asset's alt, where alt is copied or overridden at render time, a snapshot and
restore of written values, and a cache purge. A platform missing one is not ready for apply; run
inventory and audit only. The contract table and the WordPress example:
[references/wordpress-adapter.md](references/wordpress-adapter.md).

## Model choice and cost

Recommended default (2026-10-26): OpenAI `gpt-6-luna`; named alternatives Claude Haiku 5.5 and Gemini
Flash-Lite. Use the cheapest model that passes a labelled sample, and re-run the sample when a model or
a price changes. Draft 50 to 100 representative images with two
candidate models, score them against the rubric, then choose. Batch APIs from both Anthropic and OpenAI
(and Google's on Vertex AI) halve the price for jobs that can wait up to 24 hours, which an alt backlog almost always can. The dated
cost model (per 1,000 images) and the arithmetic: [references/drafting-and-guards.md](references/drafting-and-guards.md).

## Orchestration

Serial by design: each stage reads the previous stage's file. Parallel drafting is a property of the
vendor's batch API, not of agents. A run in any AI CLI can execute the stages in order with no
multi-agent support; nothing here depends on a workflow engine.

## Anti-patterns

| Don't | Why |
|---|---|
| Write to production straight from model output | Plan, dry-run, owner approval, apply is the only path |
| Overwrite existing human alt "to make it consistent" | Human alt carries context the model lacks; overwriting destroys work |
| Let the model infer specs from the photo | Wrong specs are misdescription; facts come from what is visible or catalogue data |
| Draft per page instead of per attachment | The same file is drafted thousands of times, with different answers |
| Store one product's name on a shared image | False on every other page using it |
| Inventory the media library only | Misses theme assets, inline copies in content and CSS backgrounds; includes unused files |
| Skip the snapshot because the API "can be reversed" | Reversal needs the previous values; only a snapshot holds them |
| Verify by reading back the API | Templates and plugins can override; check rendered HTML after cache purge |
| Put every draft in front of a person, or trust model confidence instead | Review cost explodes; confidence was 0.96 to 0.99 on wrong answers too. Route by guards and use count, and sample the rest |
| Re-run the whole library each time | Burns budget and risks rewriting accepted alt; run incrementally |
