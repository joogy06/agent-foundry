# Alt text audit rubric

## Contents

- What to audit: the rendered page
- Findings, detection and severity
- Scoring a page and a site
- Report row format
- What the rubric cannot decide alone

## What to audit: the rendered page

Audit the HTML a browser receives, not the database. Templates, block markup, page builders, lazy-load
scripts and plugins can each replace, copy or drop alt. Where scripts insert images after load (sliders,
infinite scroll, lazy-loaded galleries), read the DOM after rendering, not the raw HTML. Record for each
image: page URL, image URL, rendered alt, whether it is inside a link or button, adjacent text (caption,
heading, link text), and, where known, the stored alt and the attachment id.

## Findings, detection and severity

| Code | Finding | Mechanical detection | Needs judgement | Severity |
|---|---|---|---|---|
| A1 | Missing alt | No `alt` attribute on `<img>`; `<input type=image>` without alt; `role=img` without a name; `<area href>` in an image map without alt | - | High |
| A2 | Unnamed control | `alt=""` image is the only content of a link or button **and** the control's computed accessible name is empty (no `aria-label`, `aria-labelledby` or text) | - | High |
| A3 | Empty but informative | `alt=""` on an image that carries information | Yes | High |
| A4 | File name as alt | Alt matches the file's base name, or patterns `IMG_\d+`, `DSC\w*\d+`, `PXL_`, `Screenshot[ _-]?\d`, `\.(jpe?g|png|webp|gif|avif)$`, `-scaled`, `-\d+x\d+`, long hex or digit runs. A match nominates a candidate; it does not prove a machine wrote it ("Screenshot of the order page" is valid alt) | - | High |
| A5 | Placeholder | Alt is one of: image, photo, picture, img, banner, slider, logo, icon, product, product image, thumbnail, untitled, placeholder, default | - | Medium |
| A6 | Boilerplate | The same alt on a large share of a site's distinct images (site name, a slogan) | Threshold per site | Medium |
| A7 | Duplicate within page | Two or more different image files on one page share one alt | Gallery context | Medium |
| A8 | Repeats adjacent text | Alt equals (case- and punctuation-insensitive) the caption, link text or heading beside it | - | Low |
| A9 | Too long | Over about 150 characters, or more than one sentence | Complex images exempt if they carry a long description | Low |
| A10 | Keyword stuffed | A term repeated, comma-lists of keywords, appended place names or "buy cheap" phrases | Yes | Medium |
| A11 | Redundant prefix | Starts with image of, picture of, photo of, graphic of | - | Low |
| A12 | Unverifiable claim | Model numbers, specs, prices or quality claims not visible and not in catalogue data | Yes, against data | High |
| A13 | Decorative given words | Spacer, divider, texture, icon beside its own label with descriptive alt | Yes | Low |
| A14 | CSS-only information | Text or product content delivered only as a CSS background | Yes | High |
| A15 | Wrong language | Alt language differs from the page `lang` | - | Medium |
| A16 | Stored and rendered differ unexpectedly | Rendered alt is not the stored alt and no render rule explains it | - | Medium |

## Scoring a page and a site

- Page: count findings by severity; a page with any High finding fails.
- Site: report the share of images (by distinct image file, and separately by rendered occurrence) with
  no finding, and the top pages by High findings. Weight by use count: one shared attachment with a bad
  alt can account for thousands of occurrences.
- Track the trend over audits, not one score; templates regress.

## Report row format

`page_url | image_url | attachment_id | rendered_alt | stored_alt | finding_codes | severity | suggested_fix | needs_review`

The suggested fix is a draft until a person or the pipeline's guards accept it.

## What the rubric cannot decide alone

Whether an image is informative or decorative, and whether a claim is true, depend on context and data.
Mechanical checks (A1, A2, A4, A5, A7, A8, A9, A11, A15) can run unattended. Judgement checks (A3, A10,
A12, A13, A14) go to a review queue with the page context attached.
