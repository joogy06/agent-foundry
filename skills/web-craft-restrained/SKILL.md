---
name: web-craft-restrained
description: "Restrained web page craft: a visual house of one type family, neutral colour with a single accent, an even column grid and quiet motion, with an axis table and a refuse list. Use when a maker seat builds a page under the restrained house."
family: visual-craft-restrained
---

# web-craft-restrained

## Overview

One of two rival visual houses a studio maker can build a web page under. This house holds that a page earns
trust by leaving things out: one type family set carefully, neutral surfaces with one accent colour, an even
grid, and motion that only answers the visitor. Its rival is `web-craft-expressive`. The two fill the same
axis table with opposed values, so two makers who load different houses make different pages.

The house competes on taste only. What the visitor must be able to do, the order of information, the states a
page needs and the accessibility floor come from the brief, from `constraints.md` and from the neutral floor of
`design-critique`. They bind both houses equally and are no part of what makes this one different.

## When to Use

- A studio profile gives a maker seat the family `visual-craft-restrained`.
- A page is wanted in a quiet, precise register and the brief does not pin a look of its own.

Not for:

| Case | Use instead |
|---|---|
| A page that should commit to scale, colour and motion | `web-craft-expressive` |
| Judging two finished variants | `design-critique` |
| Deciding what the visitor needs and in what order | `audience-experience-design` |
| Framework and build decisions | `modern-frontend` |
| The words on the page | the copy seats of `creative-studio` |

## How a maker works under this house

1. Read the brief and `constraints.md`. They outrank this house: a look the brief pins is kept even where the
   house would choose otherwise.
2. Fill the direction contract before building: one value per axis of the axis table, chosen from what this
   house permits, plus one sentence saying what the page leaves out and why.
3. Build to the contract, using the numbers the doctrine gives.
4. Check the built page against the refuse list and against the contract, at 390, 768 and 1280 wide.
5. Hand over the page with the contract. A critic judges the page against that contract, not against this
   house and not against the rival's.

The axis table, the meaning of each value, the working numbers, the refuse list and the dated lists are in
`references/doctrine.md`. A maker's brief carries that file inline.

## Where this house comes from

The guidance is adapted from an Apache-2.0 project and re-written in this library's own words; nothing of that
project is installed or run. `references/ATTRIBUTION.md` holds the licence text, the source commit, the intake
verdict, what was changed and the primary sources for the facts the doctrine states.

## Anti-Patterns

| Don't | Why |
|---|---|
| Build first and write the direction contract afterwards | The contract is what the critic holds the page to; written late it only describes an accident |
| Treat quiet as a default look | Quiet without a decision behind each choice reads as a template |
| Move an axis outside what the table permits | The page stops being this house's, and the two rivals drift together |
| Add a second accent "for balance" | One accent carries meaning because it is rare |
| Claim the accessibility floor as this house's strength | Both houses meet it; it is not a matter of taste |
| Copy markup or styles from the adapted project | It was refused at intake; only its ideas were re-expressed |
