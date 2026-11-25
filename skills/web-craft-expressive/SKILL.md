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
authored motion sequence. Its rival is `web-craft-restrained`. The two fill the same axis table with opposed
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
| A page in a quiet, precise register | `web-craft-restrained` |
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
