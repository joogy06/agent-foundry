# Maker brief: seat `visual-b`

**Goal:** make a website page for the brief below, under the doctrine inlined in this brief, so that a critic who is not told who made it can judge it against your own direction contract.

**Context:**

- Run directory: `<run directory>`
- Your directory: `variants/variant-2/` (write here and nowhere else)
- Read `constraints.md` in the run directory first. It and the brief outrank your doctrine.
- Your doctrine is inlined below, whole. You need no other skill for the look of the piece.

## The brief

- **subject:** A landing page for a small workshop that repairs mechanical watches by post.
- **visitor:** Someone with one watch that has stopped, comparing two or three repairers before sending it away.
- **action:** Request a prepaid postal box.
- **proof:**
  - the turnaround time
  - a named watchmaker
  - what happens when a repair is not possible

## What to write

1. `variants/variant-2/direction-contract.md`, BEFORE you build: the table below with one value per axis, each from your doctrine's Value or Also allowed column, and the three lines your doctrine's process names.
2. `variants/variant-2/index.html` and the local files it needs.

Write the contract in plain terms of the piece. Do not name your doctrine, its family or any skill in the contract or in the piece: the critic reads both unlabelled.

### The direction contract to fill

## Axis table

| Axis | Value | Why this value serves the brief |
|---|---|---|
| `type` |  |  |
| `colour` |  |  |
| `density` |  |  |
| `motion` |  |  |
| `layout` |  |  |
| `imagery` |  |  |
| `ornament` |  |  |

## Three lines

1. 
2. 
3. 

## How the page is captured

The page is rendered offline in a sandboxed browser at 390, 768 and 1280 wide, with reduced motion requested, and judged from those still tiles first. A request for anything outside your directory fails the capture. Images are CSS, inline SVG, files inside your directory, or labelled placeholders. A fact you do not have is a labelled placeholder (`[FACT NEEDED: ...]`), never invented.

<!-- reference:start file=creative-studio/assets/font-kit/README.md -->
# Font kit

A variant page is captured offline. It can use the fonts the host already has, and font files its maker
placed inside the variant directory. Nothing else: a page that asks for a font at any address outside its own
directory fails the capture, and the address is listed.

This kit holds no font files. It is a set of stacks and the rule for using them.

## The rule for makers

| Allowed | Not allowed |
|---|---|
| A stack of local family names, ending in a generic family | A stylesheet or font file at an `http:` or `https:` address |
| `@font-face` with `src: url(...)` pointing at a file inside the variant directory | A path that leaves the directory through `..`, an absolute path or a symlink |
| `@font-face` with `src: local("Family Name")` | A font loaded by script from anywhere else |

A font file a maker adds must be one they may redistribute; its licence file goes beside it in the variant
directory. The file counts toward the `page-weight` floor row.

## Which families a host has

Where fontconfig is present, the host lists them:

```bash
fc-list : family | sort -u          # every installed family
fc-match "Georgia"                  # what a name actually resolves to here
fc-match -s serif | head -5         # the order the generic serif falls back through
```

A name the host does not have is not an error: the browser moves down the stack. That is why the first name of
a stack is a wish and the last one is a guarantee. Check with `fc-match` before leaning on a face for the
character of a page.

On a host without fontconfig, write the stack anyway and read what the capture reports.

## Stacks

Each stack names faces common to the three desktop systems and ends in a generic family. Pick by role, then
check what rendered.

| Role | Stack |
|---|---|
| Interface sans | `system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", "Liberation Sans", Arial, sans-serif` |
| Humanist sans | `"Gill Sans", "Gill Sans MT", Calibri, "Trebuchet MS", "DejaVu Sans", "Noto Sans", sans-serif` |
| Geometric sans | `Futura, "Century Gothic", "URW Gothic", "Avenir Next", "Noto Sans", sans-serif` |
| Book serif | `"Iowan Old Style", "Palatino Linotype", Palatino, "URW Palladio L", "Book Antiqua", Georgia, serif` |
| Transitional serif | `Charter, "Bitstream Charter", "Sitka Text", Cambria, "Liberation Serif", "DejaVu Serif", serif` |
| Display serif | `Didot, "Bodoni MT", "Playfair Display", "Noto Serif Display", "DejaVu Serif", serif` |
| Slab | `Rockwell, "Rockwell Nova", "Roboto Slab", "DejaVu Serif", serif` |
| Monospace | `ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", "DejaVu Sans Mono", monospace` |

The same stack renders as different faces on different hosts. A direction that depends on one exact face
carries that face as a file inside the variant directory.

## What the capture records

| Field of the evidence set | Holds |
|---|---|
| `fonts_rendered` | The host families that actually drew text on the page, with glyph counts, most used first |
| `variant_fonts` | How many families came from files inside the variant directory, and their glyph count |
| `requests.inside` | The files the page loaded from its own directory, font files included |
| `requests.outside` | Every address the page asked for outside its directory. Any entry here fails the capture |

A family that came from a file in the variant directory is counted and not named: the name inside a font file
is chosen by whoever made the file, and the evidence set carries no text a page supplied.

If `fonts_rendered` shows the last, generic entry of a stack where a named face was expected, the host does not
have that face. Choose another stack, or bring the face as a file.

## Limits of a page opened from a file

The capture opens `index.html` from disk, not from a server. Styles, images, classic scripts and font files
load from the variant directory by relative path. `fetch()` of a local file and `<script type="module">` with
an import do not work from a file address in Chrome; keep scripts classic and data inline.
<!-- reference:end -->

## Your doctrine

<!-- doctrine:start file=web-craft-expressive/SKILL.md sha256=da475e8940fbdb46db15d6ec08ec4f7c20354da9417f14317eec0efcb5933d7e -->
---
name: web-craft-expressive
description: "Expressive web page craft: a visual house that commits to one stated idea through display type, colour fields, a broken grid and authored motion, with an axis table and a refuse list. Use when a maker seat builds a page under the expressive house."
family: visual-craft-expressive
---

# web-craft-expressive

## Overview

One of two rival visual houses a studio maker can build a web page under. This house holds that a page is
remembered when it commits: one visual idea, stated in a sentence before anything is built, then carried at
full strength through display type, colour that owns whole regions, a grid that is broken on purpose and one
authored motion sequence. Its rival is another house of this studio. The two fill the same axis table with opposed
values, so two makers who load different houses make different pages.

The house competes on taste only. What the visitor must be able to do, the order of information, the states a
page needs and the accessibility floor come from the brief, from `constraints.md` and from the neutral floor of
`design-critique`. They bind both houses equally and are no part of what makes this one different.

## When to Use

- A studio profile gives a maker seat the family `visual-craft-expressive`.
- A page should be unmistakably itself and the brief does not pin a look of its own.

Not for:

| Case | Use instead |
|---|---|
| A page in a quiet, precise register | another house of this studio |
| Judging two finished variants | `design-critique` |
| Deciding what the visitor needs and in what order | `audience-experience-design` |
| Framework and build decisions | `modern-frontend` |
| The words on the page | the copy seats of `creative-studio` |

## How a maker works under this house

1. Read the brief and `constraints.md`. They outrank this house: a look the brief pins is kept even where the
   house would choose otherwise.
2. State the idea in one sentence. It names something of the subject (a material, a motion, a shape, a place)
   and what the page does with it. "Bold and modern" is not an idea.
3. Fill the direction contract before building: one value per axis of the axis table, chosen from what this
   house permits, each tied to the idea.
4. Build the still page first, at full strength. Then author the one motion sequence on top of it.
5. Check the built page against the refuse list and against the contract, at 390, 768 and 1280 wide.
6. Hand over the page with the contract. A critic judges the page against that contract, not against this
   house and not against the rival's.

The axis table, the meaning of each value, the working numbers, the refuse list and the dated reference list
are in `references/doctrine.md`. A maker's brief carries that file inline.

## Where this house comes from

This house is this library's own. A public component catalogue is named in the doctrine as a reference for
kinds of effect; no code, markup or style is taken from it, and it is not installed.

## Anti-Patterns

| Don't | Why |
|---|---|
| Start building before the idea is one sentence | Without it every choice falls back to a default |
| Turn every axis up at once | Commitment is one idea at full strength, not seven effects |
| Let the motion carry what the still page lacks | The judged baseline is captured still; a page that needs its animation to make sense has not been designed |
| Take an effect from a catalogue with its default settings | It arrives carrying someone else's idea |
| Move an axis outside what the table permits | The page stops being this house's, and the two rivals drift together |
| Claim the accessibility floor as a cost this house may skip | Both houses meet it; it is not a matter of taste |
<!-- doctrine:end file=web-craft-expressive/SKILL.md -->

<!-- doctrine:start file=web-craft-expressive/references/doctrine.md sha256=d10b576f3169119bf5031e030400976751e2f3b462133349b90f7feee1deb6a8 -->
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
<!-- doctrine:end file=web-craft-expressive/references/doctrine.md -->

**Non-goals:** anything outside your directory; another look than your doctrine's; a build system, a framework or a network resource.

**Open questions:** none may be asked. Where the brief is silent, decide, and write the assumption as a line under the contract.

**Done when:** the contract fills every axis from what your doctrine permits, `index.html` exists, and you have checked the piece against your contract and your doctrine's refuse list.

**Stop when:** done-when holds, or you are blocked (say by what).

**Report:** the two paths, the assumptions you made, and anything the brief needed and you could not give.
