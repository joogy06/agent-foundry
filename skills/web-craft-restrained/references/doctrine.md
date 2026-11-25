# The restrained house: doctrine

This file is what a maker under the family `visual-craft-restrained` builds to. A studio run places it inline
in that maker's brief. It is adapted guidance in this library's own words; the source and the changes are in
`ATTRIBUTION.md` beside this file.

**Contents:** The position · What both houses share · Axis vocabulary · Axis table · Process · Numbers this house works to · Refuse list · Dated lists · Sources

<!-- FRESHNESS:v1
anchors:
  - kind: date_review
    subject: restrained-house-refuse-list-and-font-stacks
    review_by: "2027-04-12"
-->

## The position

A page is trusted when every part of it was chosen and nothing was added to fill space. This house sets one
type family with care, keeps surfaces neutral, spends one accent colour on the thing that matters, holds an
even grid, and lets motion answer the visitor and do nothing else. The work is in the precision: quiet with no
decision behind it is only a template, and this house refuses that as firmly as it refuses noise.

## What both houses share

The brief and `constraints.md` say what the visitor came to do, the order the information arrives in, the
states the page needs and the action it leads to. The neutral floor of `design-critique` holds the measured
rows every variant must pass. Both houses work inside all of that. None of it is this house's own ground, and
nothing in the axis table or the refuse list below is about it. The two houses differ on taste alone.

A look the brief pins outranks this house. Where the brief names a typeface, a palette or a period, the maker
keeps it and records in the direction contract which axis it moved.

## Axis vocabulary

Every visual doctrine and every direction contract fills the same seven axes from the same values.

| Axis | Values, quietest first |
|---|---|
| `type` | `one-family`, `two-roles`, `display-led` |
| `colour` | `neutral-accent`, `tonal`, `colour-field` |
| `density` | `airy`, `compact`, `clustered` |
| `motion` | `still`, `feedback`, `authored` |
| `layout` | `single-column`, `column-grid`, `broken-grid` |
| `imagery` | `content-only`, `supporting`, `art-directed` |
| `ornament` | `none`, `structural`, `thematic` |

## Axis table

The value is where this house stands. "Also allowed" is where a maker may move when the brief asks for it; a
value in neither column is outside the house.

| Axis | Value | Also allowed | In practice |
|---|---|---|---|
| `type` | `one-family` | `two-roles` | One family carries headings, body and labels through two or three weights. A second family arrives only for a kind of text the first cannot set: code, tabular figures, a long quotation. |
| `colour` | `neutral-accent` | `tonal` | Neutral surfaces and text, and one accent hue kept for the primary action and the current state. `tonal` is one hue in several lightness steps with no separate accent. |
| `density` | `airy` | `compact` | Generous, even intervals from one spacing scale. `compact` tightens the same scale for a page that is scanned, not read; the intervals stay even. |
| `motion` | `feedback` | `still` | Motion acknowledges what the visitor did: a press, a change of state, a panel opening. Nothing moves when the page loads and nothing moves because the visitor scrolled. |
| `layout` | `column-grid` | `single-column` | Every edge sits on a column grid, and the grid is the same from the top of the page to the bottom. A reading page narrows to one column. |
| `imagery` | `content-only` | none | An image is on the page because it is the content: the product, the diagram, the screenshot, the portrait. No image sets a mood. |
| `ornament` | `structural` | `none` | Hairline rules and plain borders that separate or group. A mark that neither separates nor groups is removed. |

## Process

1. **Read first.** The brief, `constraints.md`, then this file.
2. **Fill the direction contract before any markup.** One value per axis, each from the Value or the Also
   allowed column, written as an axis table of its own. Add three lines: the single thing the page gives most
   weight to; what was left out on purpose; the accent colour and the one job it has.
3. **Set the system.** Choose the type family and its two or three weights, the spacing scale, the grid and
   the neutral ramp before composing any section. Write them as custom properties at the root of the page so
   the system can be read in one place.
4. **Compose in greys.** Lay out the whole page in neutrals. Add the accent last, to one role.
5. **Subtract.** Go through the page and remove each border, shadow, background, label and icon whose removal
   loses nothing. Stop when a removal would cost the visitor something.
6. **Check against the contract.** At 390, 768 and 1280 wide, read each axis value back off the built page.
   Then read the refuse list against it.
7. **Hand over** the page and the contract together.

## Numbers this house works to

These are the house's own working numbers. They are choices of taste and are tighter than any floor. The
measured floor rows (contrast, body size, sideways overflow, reduced motion, page weight, line length) are not
repeated here: they belong to `design-critique` and bind every house the same way.

| What | Number | Note |
|---|---|---|
| Type families | 1, or 2 under `two-roles` | the second only with a named job |
| Text sizes on a page | at most 5 | each step visibly apart from the next |
| Ratio between neighbouring sizes | 1.2 to 1.333 | one ratio for the whole page |
| Largest heading at 1280 wide | at most 3.5rem | scale comes from space around it, not from size |
| Heading letter-spacing | no tighter than -0.02em | |
| Prose measure | 45 to 75 characters | set with the `ch` unit; the range is the long-standing book convention (see Sources) |
| Body line height | 1.45 to 1.65 | wider lines take the higher end |
| Spacing scale | steps on a 4px base | no value off the scale |
| Space above a heading against space below it | at least 1.5 to 1 | the heading belongs to what follows |
| Accent hues | 1 | |
| Share of any one screen in the accent | about one tenth or less | rarity is what gives it force |
| Corner radius | at most 8px on boxes | one radius for the whole page |
| Elevation | a border or a shadow, never both | at most two shadow levels |
| Feedback motion | 100 to 200 ms | for a press or a change of state |
| A panel or layer opening | 200 to 300 ms | closing is faster than opening |

Colour is specified in `oklch()` so lightness steps are even to the eye. Neutral greys take a small tint
from the accent hue. Text that sits on a tinted surface takes its colour from that surface's hue, darkened or
lightened; flat grey on a tinted surface looks washed out.

## Refuse list

What this house will not put on a page. Each row is a habit that makes a page look machine-assembled, as seen
in generated pages up to the date in the freshness anchor below. A brief that names one of these outright
earns it back; a free choice never lands on one.

| Refused | Why | What this house does instead |
|---|---|---|
| A grid of equal cards, each an icon over a heading over two lines, used as the skeleton of the page | It gives every point the same weight, so the page has no order | Let the most important point take the most room; set the rest as plain text in columns |
| A card placed inside another card | Two frames around one thing say nothing twice | One level of grouping, made by space |
| A giant statistic with a small caption standing in as the hero | It is a template the visitor has seen on a hundred pages | Open with the sentence that states the offer |
| A small uppercase label sitting over every section heading | The heading already names the section | Remove the label; let the heading stand alone |
| Section numbers where the order tells the reader nothing | They borrow the look of a sequence the content does not have | Number only steps that must be done in order |
| Headline text filled with a gradient | Emphasis by effect, not by hierarchy | Weight and size carry emphasis |
| Frosted translucent panels as the surface style | Blur as a look, with nothing behind it that needs to show through | Opaque surfaces from the neutral ramp |
| A thick coloured stripe down one side of a box | A callout marker used as decoration | A hairline border all round, or space alone |
| A coloured glow around a box in place of a shadow | It lights nothing and separates nothing | A border, or one soft shadow with an offset |
| A purple to blue gradient backdrop chosen with no reason from the brief | It is the most common machine default | A neutral surface; colour comes from the accent role |
| Monospace type worn as a costume for technical subjects | Monospace is for code, data and measurement | The page's one family, in a lighter weight for secondary text |
| Emoji or text symbols standing in for an icon set | Each system draws them differently and none match the type | Drawn icons in one stroke weight, or no icons |
| The same fade and rise entrance on every section | Motion that answers nothing the visitor did | Sections are simply there |
| Hand-drawn style doodles posing as illustration | They imitate a picture nobody made | A real image that is content, or none |
| Striped or squared-paper backgrounds with no chart, map or drawing on them | Texture borrowed from a tool the page is not | A plain surface |
| A second typeface with no job that only it can do | Variety with no role | One family, more weights |
| Corners rounded until boxes turn into pills | Softness as a default, applied to everything | One small radius, kept for the whole page |

## Dated lists

**Faces this house reaches for.** The capture is offline, so a page uses the stacks of
`creative-studio`'s font kit or carries a font file in its own directory. Of those stacks this house uses the
interface sans, the humanist sans, the book serif and the transitional serif, and leaves the display serif,
the slab and the geometric sans to others. A page under `two-roles` may add the monospace stack for code or
figures.

**The refuse list above** is a list of habits observed in generated pages. Habits move: a pattern becomes
common, is refused everywhere, and a new default takes its place.

**Freshness anchor.** Checked 2026-10-12 against the adapted source at the commit recorded in
`ATTRIBUTION.md` and against the font-kit stacks of this library. Re-check by 2027-04-12, or sooner when
generated pages show a new common default: which refuse rows are still habits, which new ones belong, and
whether the font-kit stacks named here still exist under those names.

## Sources

Facts in this file rest on primary sources, not on the adapted project. The full list with addresses is in
`ATTRIBUTION.md`: WCAG 2.2 for the contrast ratios the neutral floor uses, CSS Values and Units for the `ch`
unit, CSS Color for `oklch()`, Media Queries for the reduced-motion preference, and Bringhurst for the 45 to
75 character measure.
