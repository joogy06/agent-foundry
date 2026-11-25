---
name: image-alt-text
description: "Image alt text standard and image-* family router: WCAG 2.2 alt decision tree, decorative alt=\"\", linked images, product photos, reused images, banners with text, logos, and an alt audit rubric. Use when writing, judging or auditing alt text."
license: MIT
metadata:
  version: "1.0.0"
  family: "image"
  family_role: "parent"
---

# image-alt-text

<!-- FRESHNESS:v1
volatility: low
anchors:
  - kind: external_fact
    subject: wai-alt-decision-tree
    source_url: https://www.w3.org/WAI/tutorials/images/decision-tree/
    verified_on: 2026-10-25
    review_by: 2027-10-25
    claim: "Ordered questions: text in the image, functional (link or button), informative, purely decorative, other purpose; outcomes alt as text, alt as purpose or destination, short alt with long description, null alt."
  - kind: external_fact
    subject: wcag-22-sc-1-1-1
    source_url: https://www.w3.org/TR/WCAG22/#non-text-content
    verified_on: 2026-10-25
    review_by: 2027-10-25
    claim: "WCAG 2.2 (this version 2024-12-12) is the current W3C Recommendation; WCAG 3.0 is still a Working Draft (2026-09-10). SC 1.1.1 Non-text Content (A): a text alternative that serves the equivalent purpose; SC 1.4.5 Images of Text (AA). HTML spec: no alt length limit; do not say image of; logo alt must not contain the word logo."
-->

## Overview

Alt text is the words a person hears or reads in place of an image. It says what the image is **for on
this page**, not everything that is in it. This skill is the authoring standard and the router of the
`image-*` family; it is platform-neutral. Adapters for particular platforms live in the pipeline skill.

| Family member | Owns |
|---|---|
| `image-alt-text` (this skill) | What good alt text is: the decision tree, wording rules, special cases, the audit rubric |
| `image-alt-pipeline` | Producing and writing alt text at scale: inventory, dedupe, model drafts, guards, review queue, dry-run, apply, rollback, verification |
| `image-seo` | How images are found and ranked: filenames, alt as a signal, captions, context, structured data, image sitemaps, product-feed image rules |

Route: one image or a style question stays here. More than a page of images, or any write to a live
site, goes to `image-alt-pipeline`. Ranking, indexing or a feed disapproval goes to `image-seo`.

## When to Use

- Writing alt text for an image, a page, a product, a template or a component.
- Deciding whether an image is decorative (`alt=""`) or needs words.
- Reviewing a draft from a person or a model before it is published.
- Auditing a page or a site's alt text, or setting a house style for alt text.

Not for: captions as editorial copy (`content-writer`), colour contrast and keyboard access
(`ux-reviewer`, `modern-frontend`), image generation (`vertex-banana`).

## Ask before generating (ambiguity gate)

Alt text depends on context the image alone does not give. When any of these is missing and would
change the words, ask ONE compact question that covers all of them, then write:

1. **Where the image appears and what it does there** - inside a link or a button, next to a caption
   or product title that already names it, on its own as content, or as decoration.
2. **What the surrounding text already says** - the product name, heading or caption beside it.
3. **The facts that may be stated** - brand, model, colour, quantity, and whether they are visible in
   the image or confirmed by catalogue data (never guess a specification from a photo).
4. **House style** - language and spelling (default UK English), any length limit the platform imposes.

If the asker says "just write it", state the assumption you made in one line beside the alt text.

## The decision tree

Run these in order; the first "yes" decides, but **empty alt is never chosen while a function or a unique
piece of information would be lost**. Source: the W3C WAI alt decision tree (anchor above).

| # | Question | If yes | Alt text |
|---|---|---|---|
| 0 | Is it a CAPTCHA, or a test the text would give away? | Exception (SC 1.1.1) | Say what it is and what it is for (`Security check: type the characters shown`); for a CAPTCHA also offer another way in. Never transcribe it, and keep these out of automatic drafting |
| 1 | Is the image the only content of a link or a button (no other accessible name)? | Functional | Where the link goes or what the button does ("Basket", "Search", "Acme Ltd home"), including any text drawn in the image, not what the picture looks like |
| 2 | Does the image contain text that matters? | Image of text | The same words as the text. Only if those exact words are also real text next to it, and the image adds nothing else, use `alt=""` |
| 3 | Does it add information the page does not give in text? | Informative | A short description of that information |
| 3a | Is that information complex (chart, diagram, map, infographic)? | Complex | Short alt naming it and its gist, plus a full text description on the page or linked beside it |
| 4 | Is it purely decorative, or does nearby text already say everything it shows? | Decorative | `alt=""` (empty, present). Never omit the attribute |
| 5 | None of the above | Unclear purpose | Ask what it is for; the answer decides the alt |

(WAI asks the text question first; asking the link question first here keeps a linked image of text from
being emptied because its words appear elsewhere on the page.)

Rules that hold for every branch:

- `alt` is **always present** on an `<img>`. Missing `alt` makes many screen readers read the file name.
  `alt=""` tells them to skip the image; a space (`alt=" "`) is not empty. Where a template can,
  decorative images are better as CSS backgrounds (WAI).
- An image with `alt=""` has no `title` either. An image inside a link that has its own text is
  decorative **unless** it adds something the text lacks (a PDF or external-link icon, a rating): then
  that addition belongs in the link's name.
- A control named another way (`aria-label` on the button, visible text) can hold an `alt=""` icon;
  judge the control's computed accessible name, not the image alone.
- WCAG 2.2 SC 1.4.5 Images of Text (AA) allows images of text only when the text can be visually
  customised or the presentation is essential (logos count as essential). House policy here is stricter:
  important text in an image is also given as real text.
- CSS background images cannot carry alt. If one carries information, give the information as real
  text in the page, or use an `<img>` instead (WCAG failure F3).

Per-case patterns (logos, icons, sliders, heroes with baked-in text, groups, image maps, charts, SVG):
[references/cases.md](references/cases.md).

## Wording rules

- **Purpose first, one sentence**: `Red waterproof jacket, hood up`, not `A photograph showing a red jacket`.
- **No "image of", "picture of", "photo of"**, and no word "logo" in a logo's alt (the screen reader
  already says "image"; the HTML spec discourages both). Name the medium only when it matters:
  `Screenshot of the order confirmation page`.
- **Short**: aim under about 125 characters, key words first; complex detail goes to a long
  description. The HTML spec sets no limit; "125" traces to old screen-reader behaviour with no primary
  source, so it is a house guide, not a rule.
- **Do not repeat adjacent text**: alt identical to the caption or title beside it is heard twice; add
  only what the text lacks, or use `""`.
- **Facts only**: brand, model, size and numbers only when visible in the image or confirmed by data.
  No "fast", "premium", "best-selling".
- **Keywords only where true and natural**: `Oak dining table, extended, seats eight`, never a keyword
  list (Google names stuffing as spam).
- **Language**: the page's language; UK English by default; sentence case; a full stop only after a
  sentence.

## E-commerce product photos and reused images

- Alt identifies the product once and adds **what this photo shows** (angle, variant, detail, scale, in
  use). The same name on every gallery image teaches a blind shopper nothing.
- Alt is usually stored **once per uploaded image**, not per use: a catalogue of about 18,000 products
  reusing a few hundred photos has one alt per photo, heard everywhere. A shared photo gets
  **generic-but-true** alt (`Black mid-tower PC case with tempered glass side panel`), never one
  product's name; per-page context comes from a render-time template rule, and audits then read the
  rendered page.
- Editors may copy alt into content at insert time; those copies do not follow later edits.

Shot patterns, grids, variants, the stored-versus-render-time table and a house-style template:
[references/ecommerce-and-reuse.md](references/ecommerce-and-reuse.md).

## Audit rubric (summary)

Audit the **rendered** page. Highest severity: missing alt, an unnamed link or button, empty alt on an
informative image, file name as alt, unverifiable claims, information only in CSS. Codes A1 to A16,
patterns, severities, scoring and the report row:
[references/audit-rubric.md](references/audit-rubric.md).

## Anti-patterns

| Don't | Why |
|---|---|
| Omit `alt` to mean "decorative" | Screen readers then read the file name; decorative is `alt=""` |
| Describe the pixels of a linked image | A link's alt is its destination |
| Empty an image's alt because its words appear elsewhere, when it is a link's only content | The link loses its name |
| Copy the product title into every gallery image | The listener hears one name six times and learns nothing |
| Write one product's name into a shared attachment | The stored alt becomes false on every other page using the photo |
| Guess model numbers or specs from the photo | Wrong alt is worse than generic alt that is true |
| Stuff keywords or start with "image of" | Noise for listeners; Google treats stuffing as spam |
| Put essential text only in a banner image or CSS background | People who cannot see it, and search engines, lose it |
| Treat "under 125 characters" as a standard | It is a rule of thumb; complex images need a long description |
| Audit the database only | Templates, blocks and plugins override stored alt; audit the rendered page |
