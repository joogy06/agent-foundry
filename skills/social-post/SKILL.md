---
name: social-post
description: "Social media post craft: the post brief, the lines a feed shows before the cut, proof and link placement, length bands, dated platform limits and the hand-over. Use when writing or checking one post for LinkedIn, X, Instagram, Threads or Bluesky."
family: social
---

# social-post

## Overview

One post, for one platform, that asks its reader for one thing. This skill holds what is particular to a post
and to no other written piece: a feed shows the first lines and cuts the rest, every platform counts length
its own way, a link behaves differently from place to place, and the limits change without notice.

It is the member of the family `social`. In a studio run both writers of a post read this file and
`references/platform-formats.md`, and each also writes under one of the two copy schools. This skill says
what the platform does and where things can go. How the post sounds, and which of the permitted places a
writer chooses, belongs to the school.

The limits of each platform are dated facts. They live in `references/platform-formats.md`, each with the
source it was read from and the day it was read. A limit that could not be read from the platform's own
documentation is marked not confirmed there, and is never quoted as fact.

## When to Use

- A post for a named platform is to be written, shortened to fit, or checked before it is published.
- A studio profile gives a seat this skill, or the family `social`.
- A longer piece is to be announced in a post and the post has to stand on its own.

Not for:

| Case | Use instead |
|---|---|
| A posting calendar, cadence, or which platforms a person should be on | `career-online-presence` |
| An article, a guide, or the words of a page | the article and page profiles of `creative-studio` |
| Making an image for the post | `vertex-banana` |
| Paid placements and their formats | not covered here |
| Publishing, scheduling or replying | a person does that; this skill never posts |

## The post brief

A post is written from a brief of four required fields. A brief that lacks one is sent back, not guessed.

| Field | What it holds |
|---|---|
| `platform` | The one platform the post is for, by name. Two platforms are two posts and two briefs. |
| `reader` | Who sees this in their feed, what they already know, and what they were doing a moment before. |
| `action` | The one thing the reader should do after reading. One, not a list. |
| `proof` | The facts the post may rest on, as the brief gives them: a result, a figure with its unit, a named source, a thing that was shipped. |

Optional: `subject` (what the post is about, when the proof alone does not say), `link` (what the link leads
to, as a name, not a URL to invent), `media` (what image or video exists already), `pinned` (wording that
must appear as given), `notes`.

**Facts.** A post states only what the brief gives. A fact the post needs and the brief lacks is a labelled
placeholder, `[FACT NEEDED: what is missing]`, and the words after the colon say what to look up. A
placeholder is not a failure. A figure, a name, a date or a quotation that nobody supplied is.

## The lines before the cut

A feed shows the top of a post and hides the rest behind a control the reader has to press. Where the cut
falls differs by platform, by device and by whether the post carries media, and no platform documents it:
`references/platform-formats.md` records a cut point only when a primary source states one.

So the rule does not depend on the number:

- The first line makes sense alone. A reader who sees nothing else still knows what the post is about.
- The first two short lines are all that can be relied on. Whatever the post most needs the reader to see
  goes there.
- Nothing above the cut is spent on a greeting, on the writer announcing that they are about to say
  something, or on a line that only makes sense after the rest has been read.

What goes in those lines is the writer's choice of opening. In a studio run the school file sets it, and the
direction contract records it on the `opening` axis. This skill only says what the choice costs here: an
opening that holds its point back is asking the reader to press the control before they have a reason to.

## Where the proof can sit

The proof is what makes the claim of the post believable. It can sit in four places, and each has a cost.

| Place | What it gives | What it costs |
|---|---|---|
| Above the cut, with the claim | Every reader who sees the post sees the proof | It takes room from the lines that earn the press |
| In the body, after the reasoning | The proof arrives when the reader is ready for it | Only readers who opened the post see it |
| In the media | A chart, a screenshot or a photograph is seen before any text | It needs alternative text that states the same fact, and it is invisible to a reader who has images off |
| In the first reply | The post stays short | Most readers never open the replies; a proof kept there is close to absent |

A figure is written the way the brief writes it: the same number, the same unit, the same source. In a
studio run the school decides between these places on the `proof-placement` axis.

## The one action and the link

- The action is stated once, in words the reader could follow without the link.
- A link is written as a slot, `[LINK: what the reader gets -> where it leads]`, never as a URL the brief did
  not give. The person who posts puts the address in.
- Where the link goes (in the text, in the first reply, or nowhere) is a choice with a platform side to it:
  how a link is counted, how many a post may hold and whether it is clickable are rows of
  `references/platform-formats.md`. Claims that a platform shows a post with a link to fewer people are
  common and are not documented by any platform; the reference does not state them as fact.
- Tags and mentions follow the platform row. A tag is used when a reader would search for it. A mention is
  used when the person named has agreed to be named or is the source of the proof.

## Length bands

A band is a share of the platform's limit for the text of a post, taken from the reference row for the
platform on the day of writing.

| Band | Share of the limit | Suits |
|---|---|---|
| `brief` | up to a quarter | One claim, one proof, one action. Everything is above the cut. |
| `standard` | a quarter to three fifths | A claim with the reasoning that leads to it, or a short account of what was done. |
| `full` | three fifths to the limit | A piece meant to be read in the feed. Each paragraph has to earn the next. |

The band is settled before the post is written: in a studio run the constraints round writes it into
`constraints.md` in characters, with the limit it was worked from and the date of that row. Where the limit
of the platform is marked not confirmed, the band is written as an assumption for the user to confirm.

A post is counted the way its platform counts it. A link, an emoji and some scripts weigh more than one
character on some platforms: the reference row says how. Leave a margin of a tenth under the limit for the
address the person posting puts in.

## The file a writer hands in

One Markdown file, `post.md`.

```
---
platform: the platform, as the brief names it
link-placement: body, first-reply or none
---

# Post

The text exactly as it is to be pasted, line breaks included.

## First reply

Only when link-placement is first-reply: the text of that reply.

## Media

One line per image or video the post needs: what it shows, and its alternative text.
```

- No Markdown inside `# Post`: platforms do not render it. Emphasis is carried by the words and the line
  breaks.
- Square brackets are kept for placeholders and link slots. Anything else in square brackets is read as an
  unfinished gap.
- Media is described, never attached or generated here.

## The hand-over for a post

Whoever publishes the post receives:

1. the text of the post, and of the first reply when there is one;
2. the platform, the count of the text and the limit it was written to, with the date that limit was read;
3. the link slot and where it was placed;
4. the tags and mentions used, against the platform row;
5. the media the post needs, each with its alternative text;
6. every placeholder still open: a post with one is not ready to publish;
7. what to re-check on the day: the platform row when its re-check date has passed, and any name mentioned.

In a studio run the runner writes the hand-over from the final `post.md`; items 2, 4 and 7 are checked by
the person posting against `constraints.md`.

## Anti-Patterns

| Don't | Why |
|---|---|
| Quote a character limit from memory | Limits change; the reference row carries the source and the date, or says it was not confirmed |
| Write one text for several platforms | Each counts, cuts and links differently; a post that fits all of them suits none |
| Invent a figure, a name or a quotation to make the post land | A post is public and quoted; an unknown fact is a labelled placeholder |
| Put the only proof in the first reply | Most readers never see it |
| Add tags to reach more people | A tag is for the reader who searches for it; the platform row gives the most a post may carry |
| State as fact that a link, a tag or a posting hour changes how many people see a post | No platform documents it; say it is a belief, or leave it out |
| Publish from this skill | It writes and checks; a person posts |
