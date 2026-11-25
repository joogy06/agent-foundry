# Special cases

## Contents

- Logos
- Icons and icon buttons
- Banners and heroes with baked-in text
- Sliders and carousels
- CSS background images
- Groups of images
- Image maps
- Complex images: charts, diagrams, maps, infographics
- SVG
- Images inside links that also have text
- Decorative images: how to tell

Sources: W3C WAI Images tutorial (https://www.w3.org/WAI/tutorials/images/), WAI Carousels tutorial
(https://www.w3.org/WAI/tutorials/carousels/), WCAG 2.2 Technique F3, all read 2026-10-25.

## Logos

| Use | Alt |
|---|---|
| Site logo linking to the home page | The organisation name, and the destination if it is not obvious: `Acme Ltd home`, or `Acme Ltd` when the logo link is universally understood as home |
| Logo as content (a "brands we stock" strip, a partner logo) | The organisation name: `Corsair`. If each logo links to a brand page, the brand page is the purpose: `Corsair products` |
| Logo repeated in the footer beside the company name as text | `""` |
| Logo with a strapline baked in | The name plus the strapline only if the strapline carries meaning the page lacks |

Do not put the word "logo" in a logo's alt: the HTML spec says logo alt must not contain it, and WAI
says there is no need to mention that it is a logo. WCAG exempts logo text from SC 1.4.5, not from SC 1.1.1.

## Icons and icon buttons

| Icon | Alt or accessible name |
|---|---|
| Icon alone inside a button or link | The action: `Search`, `Close`, `Add to basket`, `Next slide` |
| Icon beside a text label | `""` (or `aria-hidden="true"` on an inline SVG); the label carries the meaning |
| Status icon with meaning and no text (a tick in a table) | The meaning: `In stock`, `Included` |
| Social icons in a footer | The destination: `Acme on Instagram` |

## Banners and heroes with baked-in text

A banner with text drawn into the image is an image of text.

1. Best: move the text out of the image into real HTML over the image; the image becomes decorative or
   gets a short alt for its picture content.
2. If the text must stay in the image: alt repeats the text that matters, in the same order, including
   the offer and the call to action wording (`Autumn sale: 20% off all gaming PCs. Shop now`).
3. If the banner is a link, the alt must also make the destination clear; the baked-in call to action
   usually does this.
4. Dates, prices and offer terms in a banner must also be in real text somewhere the user meets them.
   Merchant Center and search engines do not read them reliably from pixels either (see `image-seo`).

## Sliders and carousels

- Each slide's image follows the decision tree on its own; a slide that is a link is functional.
- Slide controls are functional icons: `Previous slide`, `Next slide`, `Show slide 3`, `Stop rotation`.
  WAI's ARIA carousel pattern puts the rotation control first in tab order and stops rotation on focus
  or hover (https://www.w3.org/WAI/ARIA/apg/patterns/carousel/).
- Do not put the only copy of an offer in a slide that auto-advances; WAI requires a pause control for
  moving content (WCAG 2.2 SC 2.2.2) and the alt is read only when a screen-reader user reaches it.
- Duplicated slides (clones used for infinite loops) should be hidden from assistive technology, or
  every alt is heard twice.

## CSS background images

- CSS images have no alt. A screen reader and Google Images both ignore them.
- Decorative backgrounds: fine as CSS.
- If a background carries information (a product shot, a banner's offer text): use an `<img>` with alt,
  or put the information in real text and keep the background decorative. Information carried only by a
  CSS image is the WCAG failure F3.
- An inventory of a site must flag CSS backgrounds separately, because no alt field exists to fix.

## Groups of images

When several images together convey one thing (a five-star rating made of five star images, a
before-and-after pair), give the alt to one image (`Rated 4 out of 5`) and `alt=""` to the rest.

## Image maps

A client-side image map needs alt on the parent `<img>` (what the whole image is) and on every
`<area href>` (where that hotspot goes). Audit each `<area>` as a functional image
(https://www.w3.org/WAI/tutorials/images/imagemap/).

## Complex images: charts, diagrams, maps, infographics

- Short alt: what it is and the one-line gist: `Bar chart of monthly orders, 2025: peak in November`.
- Long description: the data or the full explanation as real text next to the image, in a linked page,
  or in a `<figure>` with a `<figcaption>`, associated with `aria-describedby` when it is not adjacent.
- A data table beside a chart is the best long description.

## SVG

- Inline `<svg>` that carries meaning: `role="img"` and a `<title>` (or `aria-label`) as the alt.
- Inline decorative SVG: `aria-hidden="true"` and `focusable="false"`.
- `<img src="x.svg">`: same `alt` rules as any image.

## Images inside links that also have text

A card where image and title both link to the same page: put both in one link and give the image
`alt=""`, so the link name is the title alone. Two adjacent links to the same URL (image link, then text
link) should be merged into one. If the template cannot be changed, the image link still needs a name
(the destination), because an empty-alt image as a link's only content leaves the link unnamed (A2 in
`references/audit-rubric.md`'s terms).

## Decorative images: how to tell

Decorative when removing the image loses no information or function: spacers, dividers, background
textures, a stock photo whose subject the heading already states, an icon beside its own label, an
image whose content the adjacent text describes in full. Not decorative: anything a sighted shopper
uses to decide (a product angle, a colour, a size chart), anything inside a link with no other text.
