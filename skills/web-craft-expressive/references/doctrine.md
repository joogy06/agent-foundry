# The expressive house: doctrine

This file is what a maker under the family `visual-craft-expressive` builds to. A studio run places it inline
in that maker's brief. The house is this library's own.

**Contents:** The position · What both houses share · Axis vocabulary · Axis table · Process · Numbers this house works to · Refuse list · Reference catalogue · Sources

<!-- FRESHNESS:v1
anchors:
  - kind: date_review
    subject: expressive-house-catalogue-kinds-and-font-stacks
    review_by: "2027-04-12"
-->

## The position

A page is remembered when it commits to one idea and carries it all the way. This house states the idea in a
sentence before anything is built, then spends the whole page on it: a display face that has a voice, colour
that owns regions instead of dotting them, tight clusters set against open space, a grid that is broken where
the idea needs it, an image made for this page, and one motion sequence that was planned. The discipline is
in the "one": seven effects at once is as timid as none, because nothing was chosen.

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
| `type` | `display-led` | `two-roles` | A display face with a character of its own sets the headings at a size that makes them the picture; a plain text face carries the body. Under `two-roles` the pairing stays and the display size comes down. |
| `colour` | `colour-field` | `tonal` | At least one colour owns a whole region of the page: a full-width band, a full screen, the page ground itself. `tonal` keeps one hue and pushes its lightness range to both ends. |
| `density` | `clustered` | none | Tight clusters against open space. Neighbouring regions never share one interval; the page has a loud bar and a rest. |
| `motion` | `authored` | none | One sequence, planned as a sequence with a beginning and an end, tied to the idea. Everything else that moves is plain feedback. The still page comes first and stands without it. |
| `layout` | `broken-grid` | `column-grid` | A grid exists so that leaving it means something. One or two elements per screen cross a column line, overlap a neighbour or run off the edge. |
| `imagery` | `art-directed` | `supporting` | A graphic or image made for this page leads at least one screen. It is drawn in CSS or SVG, or stands as a labelled placeholder that says exactly what the picture will be. |
| `ornament` | `thematic` | none | Decorative devices are allowed and every one traces to the stated idea: a shape, a texture or a rule taken from the subject's own world. |

## Process

1. **Read first.** The brief, `constraints.md`, then this file.
2. **State the idea.** One sentence that names something of the subject (a material, a movement, a shape, a
   place, a sound) and what the page does with it. Test it: could the sentence be put on a different product
   unchanged? If so it is a mood, not an idea; write it again.
3. **Fill the direction contract before any markup.** One value per axis, each from the Value or the Also
   allowed column, written as an axis table of its own, with the idea in its "In practice" cell. Add three
   lines: the idea; the one screen that carries it hardest; what the motion sequence is and where it starts
   and ends.
4. **Build the still page at full strength.** Type scale, colour fields, the broken grid and the lead graphic
   are all there with nothing moving. The judged baseline is captured this way.
5. **Author the sequence.** One, on top of the finished still page. Write it down as beats before coding it.
   With reduced motion requested the page shows the sequence's end state.
6. **Cut what is not the idea.** Go through every decorative device and effect and ask which words of the
   idea sentence it comes from. One with no answer goes.
7. **Check against the contract.** At 390, 768 and 1280 wide, read each axis value back off the built page.
   The idea must survive at 390: it is re-composed for the narrow screen, not shrunk. Then read the refuse
   list against the page.
8. **Hand over** the page and the contract together.

## Numbers this house works to

These are the house's own working numbers. They are choices of taste. The measured floor rows (contrast, body
size, sideways overflow, reduced motion, page weight, line length) are not repeated here: they belong to
`design-critique` and bind every house the same way.

| What | Number | Note |
|---|---|---|
| Type families | 2 | one display face, one text face, each with its own job |
| Largest heading at 1280 wide | at least 5rem | set with `clamp()` so it re-composes at 390 instead of overflowing |
| Largest heading against body size | at least 5 to 1 | there is one clearly largest thing on the page |
| Ratio between neighbouring sizes | 1.333 to 1.618 | the steps are meant to be seen |
| Colour fields | at least 1 region the full width of the page | in a colour that is not a neutral |
| Hues | at most 3 | a field, its counter-colour, one neutral family |
| Neighbouring vertical intervals | differ by at least 2 to 1 | no run of three equal gaps down the page |
| Grid breaks | 1 or 2 per screen | more than that and there is no grid left to break |
| Authored sequences | exactly 1 | |
| Length of the sequence | 600 to 1400 ms from first beat to last | long enough to read as composed, short enough to wait for once |
| Feedback motion | 100 to 200 ms | plain and fast, so the sequence stays the only event |
| Decorative devices | each used at least twice | a device seen once looks like a mistake |

Colour is specified in `oklch()` so a field and the text on it can be tuned by lightness alone. A motion
sequence is built on properties that do not force the page to be laid out again, so that it stays
smooth on a modest machine.

## Refuse list

What this house will not put on a page. Each row is a way a page fails to commit.

| Refused | Why | What this house does instead |
|---|---|---|
| A page built with no idea sentence written down | Every later choice has nothing to answer to and falls back to a default | Write the sentence first; rewrite it until it fits no other subject |
| A decorative device that traces to no word of the stated idea | It is filler dressed as style | Remove it, or replace it with a device taken from the subject |
| A hero that could be moved onto any other product unchanged | The page has not said what it is | Lead with the one thing only this subject has |
| Type sized so that nothing is clearly the largest thing on the page | A hierarchy with no top | Pick the one line that leads and give it the scale |
| A grey and blue palette picked because it offends nobody | A choice made to avoid choosing | Take the field colour from the subject's own world |
| Motion spread thinly over every section in place of one planned sequence | Many small movements add up to restlessness, not to an event | One authored sequence; the rest is plain feedback |
| A catalogue effect dropped in with its default settings | It carries the idea of whoever made the catalogue | Rebuild the effect for this idea, or leave it out |
| Symmetry kept only because the grid offered it | The grid decided, not the maker | Break the grid where the idea pulls |
| Stock-style imagery that says nothing about the subject | A picture of nothing in particular | A graphic made for the page, or a placeholder that names the real picture |
| Three ideas at half strength where one at full strength was possible | Hedging reads as a committee | Keep the strongest; cut the other two |
| A bold desktop page that turns into a plain stacked list on a phone | The idea was only ever a wide-screen layout | Re-compose the idea for the narrow screen |
| An effect added because it was impressive to build | Craft pointed at the maker, not at the subject | Keep only what the idea sentence asks for |

## Reference catalogue

**Magic UI** (`magicui`, <https://github.com/magicuidesign/magicui>, MIT licence), read at commit
`85f97fd27b053339af74ba9dd4ca428ee25989fb`. It is named here as a REFERENCE ONLY: a place to see what kinds of
animated component are in common use. It was scanned at intake with the verdict block, so it is not installed,
none of its code, markup or styles is in this library, and a maker under this house does not fetch it (the
capture is offline in any case). A maker who wants one of these kinds builds it from nothing, for the stated
idea, with settings of their own.

Kinds of effect the catalogue shows, named as ideas:

- a row of items that scrolls sideways without end
- a mosaic of unequal tiles holding different kinds of content
- a line of light travelling along a path that joins two things
- a number that counts up to its value
- text that appears a word or a letter at a time
- a light that sweeps round the edge of a box
- a field of drifting points or a dotted ground behind content
- items that circle a centre
- a row of icons that swell under the pointer
- a burst of particles to mark a success

Each of these is common enough to be a default by now. Taking one as it comes is the refuse-list row about
catalogue effects; the list is here so a maker can recognise a default when reaching for one.

**Faces this house reaches for.** The capture is offline, so a page uses the stacks of `creative-studio`'s font
kit or carries a font file in its own directory. For the display role this house uses the display serif, the
slab or the geometric sans stack; for text, the humanist sans or the transitional serif. A direction that
depends on one exact display face carries that face as a file, with its licence beside it.

**Freshness anchor.** Checked 2026-10-12 against the catalogue at the commit above and against the font-kit
stacks of this library. Re-check by 2027-04-12: whether the kinds listed are still the common ones, which new
kinds have become defaults, and whether the font-kit stacks named here still exist under those names.

## Sources

Facts in this file rest on primary sources: CSS Color Module Level 4 for `oklch()`
(<https://www.w3.org/TR/css-color-4/#ok-lab>), CSS Values and Units Module Level 4 for `clamp()`
(<https://www.w3.org/TR/css-values-4/#comp-func>), and Media Queries Level 5 for the reduced-motion preference
(<https://www.w3.org/TR/mediaqueries-5/#prefers-reduced-motion>).
