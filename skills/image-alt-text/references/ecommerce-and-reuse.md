# E-commerce alt text and reused images

## Contents

- Alt is not the product title
- A pattern for product photo alt
- What may be stated: the fact rule
- Variants, bundles and configurable products
- Category and listing grids
- Reused images: the storage model
- Choosing stored alt versus render-time alt
- House-style template

## Alt is not the product title

The title sits next to the image as text. Alt that copies it is heard twice and adds nothing. Use the
title to identify the product once (usually on the main image) and spend the rest of the alt on what
this particular photo shows.

| Element | Job |
|---|---|
| Product title | Names the product for everyone |
| Main image alt | Identifies the product and the view or variant |
| Gallery image alt | What each shot adds: angle, detail, scale, in-use, inside, ports, packaging |
| Caption (if any) | Editorial or extra fact; alt should not repeat it |

## A pattern for product photo alt

`[identity, if not already said nearby] [variant or colour] [what this shot shows]`

| Shot | Alt |
|---|---|
| Main | `Acme X200 office chair, black, three-quarter front view` |
| Back | `Acme X200 mesh back and lumbar support` |
| Detail | `Close-up of the armrest height lever` |
| Scale | `Acme X200 beside a 120 cm desk for scale` |
| Inside a built product | `Inside view: graphics card, cooler and cable routing` |
| Ports | `Rear ports: four USB-A, two USB-C, HDMI and DisplayPort` |
| Packaging | `Retail box with accessories laid out` |

Once the product is named on the main image, gallery alt may omit the name when the gallery is
clearly scoped to that product.

## What may be stated: the fact rule

State a brand, model number, specification, quantity, colour name or measurement only when it is:

1. **Visible** in the image (legible text, an unambiguous feature), or
2. **Confirmed** by catalogue data for this exact product or attachment.

Never infer a specification from appearance ("RTX 4090" from a graphics card's shape, "1,000 W" from a
power supply's size). A false spec in alt is a misdescription a customer can rely on, and a consumer
protection exposure as well as an accessibility defect. When unsure, describe what is seen (`graphics
card with three fans`) and leave the model to the title.

Marketing claims (best, premium, fastest, award-winning) never belong in alt.

## Variants, bundles and configurable products

- A variant image's alt names the variant attribute shown (`in white`, `32 GB kit`).
- A bundle photo lists what is visibly in the bundle, not the bundle's price or saving.
- A configurable product with one photo for every configuration (a build shown once, sold in many
  specs): the stored alt describes what the photo shows and nothing configuration-specific; the page
  text states the configuration.

## Category and listing grids

- The thumbnail usually sits in a link with the product name as text: give the thumbnail `alt=""` if it
  shares the link, or the product name if it is a separate link.
- Hover-swap second images are decorative only if they add nothing; a second image showing the back,
  the fit or the material adds purchase information, which then needs an accessible equivalent (in the
  product page gallery, or the card's text).
- Colour or material swatches are buttons: the alt or name is the choice they make (`Black`,
  `Grey mesh`), not a description of the swatch.
- Never put price, stock or offer text only in a thumbnail overlay image.

## Reused images: the storage model

Most content systems store one alt per uploaded file (the attachment or asset). Every template that
shows the file reads that one value unless the template sets alt itself. Consequences:

- Editing the stored alt changes it everywhere the file appears, including places nobody checked.
- Content editors (block editors, page builders) may copy the alt into the page's own HTML at insert
  time. Those copies do **not** change when the stored alt changes; they need their own fix.
- Themes and plugins can replace the stored alt at render time (for example, fall back to the product
  title when alt is empty). What the user hears may be neither the stored value nor what you wrote.

So there are three alts to know for any image: **stored**, **inline copy** (if any), **rendered**.

## Choosing stored alt versus render-time alt

| Use count and content | Stored alt | Render-time |
|---|---|---|
| 1 use, specific content | Specific | None |
| Many uses, photo shows the same thing everywhere (one case model used by every build in that case) | Generic-but-true: describe the object, not the product it sits in | Optional: template prepends the product name |
| Many uses, photo is generic stock or lifestyle | Generic-but-true, short | None; often decorative in context, set `alt=""` there |
| Many uses, image is a brand or trust badge | The badge's meaning (`Trustpilot rating 4.8 out of 5` only if the image shows it) | None |
| Many uses, content in some, decoration in others | Content alt | Decorative uses set `alt=""` in that template |

Render-time contextual alt is a template decision with an owner, a rule (which data field it reads),
and a test (render a page and check). It is not a reason to leave stored alt empty: the media library, other
templates, search engines reading other pages, and the next theme all read the stored value. (Product
feeds do not: alt is not a feed field, though the landing page's alt still matters.)

## House-style template

A site's alt style sheet should fix, in one page:

- Language and spelling (default UK English), sentence case, no trailing full stop unless a sentence.
- The product-photo pattern above, and which shots name the product.
- Words never used (image of, picture of, marketing adjectives, the site name on every image).
- The length guide (aim under about 125 characters; complex images get long descriptions).
- The decorative list for this site's templates (dividers, badges beside text, hover images).
- Who may change shared attachments, and that one product's name never goes on a shared image.
