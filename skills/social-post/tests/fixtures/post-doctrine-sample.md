<!-- doctrine:start file=social-post/SKILL.md sha256=a2ddda8d8160e2eee6d0fd6fccbb27ddd6b86901256d73494bba7ae870f7e7a2 -->
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
<!-- doctrine:end file=social-post/SKILL.md -->

<!-- doctrine:start file=social-post/references/platform-formats.md sha256=a9032d395a96a8eed6849bb9435043bc5af0fa1eeb9f69ad3701af9ff4304d0e -->
# Platform formats for a post

What each platform does with the text of a post: how long it may be, how the length is counted, what a link,
a tag and a mention cost, and how much media a post carries. It says where things go and what fits. It says
nothing about how a post sounds: that is the school's. Both schools of a studio run read this same file.

**Contents:** How to read this file · Platforms · X · LinkedIn · Instagram · Threads · Bluesky · Mastodon ·
Facebook · What no platform documents · Re-checking a row

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: social-post-x
    source_url: https://docs.x.com/resources/fundamentals/counting-characters
    verified_on: 2026-10-12
    review_by: 2027-01-12
    claim: "A post holds up to 280 weighted characters; any URL counts as 23; an emoji counts as 2; Chinese, Japanese and Korean glyphs count as 2."
  - kind: external_fact
    subject: social-post-linkedin
    source_url: https://www.linkedin.com/help/linkedin/answer/a528176
    verified_on: 2026-10-12
    review_by: 2027-01-12
    claim: "A post can contain up to 3,000 characters; a longer text is written as an article."
  - kind: external_fact
    subject: social-post-instagram
    source_url: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media
    verified_on: 2026-10-12
    review_by: 2027-01-12
    claim: "Through the publishing API a caption holds at most 2,200 characters, 30 hashtags and 20 @ tags; a carousel holds up to 10 items."
  - kind: external_fact
    subject: social-post-threads
    source_url: https://developers.facebook.com/docs/threads/posts/
    verified_on: 2026-10-12
    review_by: 2027-01-12
    claim: "A text post is limited to 500 characters with emoji counted as UTF-8 bytes; at most 5 links; one topic tag of 1 to 50 characters; a carousel holds 2 to 20 items."
  - kind: external_fact
    subject: social-post-bluesky
    source_url: https://github.com/bluesky-social/atproto/blob/main/lexicons/app/bsky/feed/post.json
    verified_on: 2026-10-12
    review_by: 2027-01-12
    claim: "The post record's text holds at most 300 graphemes and 3,000 bytes; up to 8 additional tags; an images embed holds at most 4 images."
  - kind: external_fact
    subject: social-post-mastodon
    source_url: https://docs.joinmastodon.org/user/posting/
    verified_on: 2026-10-12
    review_by: 2027-01-12
    claim: "The default limit is 500 characters; every link counts as 23; only the username part of a mention counts; up to 4 images, or one video, one animated GIF or one audio file."
  - kind: date_review
    subject: social-post-facebook
    review_by: "2027-01-12"
-->

## How to read this file

- Every figure here was read from the page named as its source on the date in the row. **Confirmed** means
  the page was read on that date and states the figure. **Not confirmed** means no page of the platform was
  read that states it: the row then gives no figure, or says who reports one, and the figure is not to be
  used as fact.
- These numbers age. Each platform has an anchor in the block above with the date it was read and the date
  to read it again. A row whose re-check date has passed is treated as not confirmed until it is read again.
- A limit read from a platform's developer documentation is the limit of its publishing interface. The app
  a person types into can differ; where only the interface was read, the row says so.
- Nothing here is advice on what performs. It is what fits and how it is counted.

## Platforms

One row per platform. The anchor is the `subject` of that platform's entry in the block above.

| Platform | Text limit of one post | Status | Read on | Re-check by | Source | Anchor |
|---|---|---|---|---|---|---|
| X | 280 weighted characters | Confirmed | 2026-10-12 | 2027-01-12 | [X developer documentation, Counting characters](https://docs.x.com/resources/fundamentals/counting-characters) | `social-post-x` |
| LinkedIn | 3,000 characters | Confirmed | 2026-10-12 | 2027-01-12 | [LinkedIn Help, Post and share updates](https://www.linkedin.com/help/linkedin/answer/a528176) | `social-post-linkedin` |
| Instagram | 2,200 characters in a caption (publishing interface) | Confirmed | 2026-10-12 | 2027-01-12 | [Meta for Developers, IG User Media](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media) | `social-post-instagram` |
| Threads | 500 characters | Confirmed | 2026-10-12 | 2027-01-12 | [Meta for Developers, Threads posts](https://developers.facebook.com/docs/threads/posts/) | `social-post-threads` |
| Bluesky | 300 graphemes (and 3,000 bytes) | Confirmed | 2026-10-12 | 2027-01-12 | [AT Protocol lexicon `app.bsky.feed.post`](https://github.com/bluesky-social/atproto/blob/main/lexicons/app/bsky/feed/post.json) | `social-post-bluesky` |
| Mastodon | 500 characters by default | Confirmed | 2026-10-12 | 2027-01-12 | [Mastodon documentation, Posting to your profile](https://docs.joinmastodon.org/user/posting/) | `social-post-mastodon` |
| Facebook | no figure given | Not confirmed | 2026-10-12 (searched, nothing found) | 2027-01-12 | none: no page of the platform was found that states a limit for the text of a post | `social-post-facebook` |

## X

Source for the confirmed rows: [Counting characters](https://docs.x.com/resources/fundamentals/counting-characters),
read 2026-10-12.

| Fact | Value | Status |
|---|---|---|
| Length of a post | Up to 280 characters, counted by weight | Confirmed |
| A link | Any valid URL counts as 23 characters, whatever its real length | Confirmed |
| An emoji | Counts as 2 characters, however it is built | Confirmed |
| Chinese, Japanese and Korean glyphs | Count as 2 each, so 140 fill a post | Confirmed |
| Longer posts for paying subscribers | X Help Center pages are reported to give 25,000 characters. The pages refused a direct read on 2026-10-12, and one of them is reported to still say 4,000 | Not confirmed |
| Mentions in a longer post | Reported: only mentions within the first 280 characters notify the account | Not confirmed |
| Number of tags | No limit was found in the page read | Not confirmed |

Write to the 280 limit unless the brief says the account posts longer texts, and then confirm the figure
first.

## LinkedIn

Source for the confirmed row: [Post and share updates](https://www.linkedin.com/help/linkedin/answer/a528176),
read 2026-10-12.

| Fact | Value | Status |
|---|---|---|
| Length of a post | Up to 3,000 characters | Confirmed |
| A longer text | Written as an article on the platform's publishing tool, not as a post | Confirmed |
| Where the feed cuts a post | No page of the platform states it | Not confirmed |
| How a link, a tag or a mention is counted | Not stated in the page read | Not confirmed |
| Number of tags | Not stated in the page read | Not confirmed |

## Instagram

Source for the confirmed rows: [IG User Media](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media),
read 2026-10-12. These are the limits of the publishing interface.

| Fact | Value | Status |
|---|---|---|
| Length of a caption | At most 2,200 characters | Confirmed (interface) |
| Tags in a caption | At most 30 hashtags | Confirmed (interface) |
| Mentions in a caption | At most 20 @ tags | Confirmed (interface) |
| A carousel | Up to 10 images, videos or a mix; no caption on a single item of it | Confirmed (interface) |
| Tags allowed in the app | Trade press reported in late 2025 that the app caps a post at five hashtags. No page of the platform was read that states it, and it disagrees with the interface figure above | Not confirmed |
| A link in a caption | Whether it is clickable is not stated in the page read | Not confirmed |
| Where the feed cuts a caption | No page of the platform states it | Not confirmed |

Until the app's own tag limit is confirmed, a post that must be safe carries five tags or fewer.

## Threads

Sources for the confirmed rows: [Threads posts](https://developers.facebook.com/docs/threads/posts/), read
2026-10-12, and for the text attachment the announcement
[Attach Text to Your Threads Posts](https://about.fb.com/news/2025/09/attach-text-threads-posts-share-longer-perspectives/)
(published 2025-09-04, updated 2025-10-22), read 2026-10-12.

| Fact | Value | Status |
|---|---|---|
| Length of a text post | 500 characters | Confirmed |
| An emoji | Counted as its number of UTF-8 bytes, so it uses more of the limit than one character | Confirmed |
| Links | 5 or fewer, counted as unique addresses across the text and the link attachment; the interface refuses more | Confirmed |
| Topic tag | One per post: the first valid tag is the post's topic. 1 to 50 characters. A number alone, such as #1, does not become a tag | Confirmed |
| A carousel | 2 to 20 images, videos or a mix | Confirmed |
| Text attachment | Up to 10,000 characters of text can be attached to a post, by the announcement. The developer page read gives no limit for it | Confirmed (announcement) |
| Where the feed cuts a post | No page of the platform states it | Not confirmed |

## Bluesky

Sources for the confirmed rows: the lexicons
[`app.bsky.feed.post`](https://github.com/bluesky-social/atproto/blob/main/lexicons/app/bsky/feed/post.json)
and [`app.bsky.embed.images`](https://github.com/bluesky-social/atproto/blob/main/lexicons/app/bsky/embed/images.json)
on the main branch of the protocol's repository, read 2026-10-12. A lexicon is the record's schema: it is
what the network accepts.

| Fact | Value | Status |
|---|---|---|
| Length of the text | At most 300 graphemes, and at most 3,000 bytes | Confirmed |
| Links, mentions and tags | Annotations on ranges of the text (facets), not markup inside it | Confirmed |
| Additional tags | Up to 8, beside any written in the text | Confirmed |
| Languages declared | Up to 3 | Confirmed |
| Images | At most 4 in one post | Confirmed |
| How the app shows or shortens a long address | The documentation page returned no content on 2026-10-12 | Not confirmed |

A grapheme is what a reader sees as one character: an emoji built from several code points is one.

## Mastodon

Source for the confirmed rows: [Posting to your profile](https://docs.joinmastodon.org/user/posting/), read
2026-10-12.

| Fact | Value | Status |
|---|---|---|
| Length of a post | 500 characters by default | Confirmed |
| A link | Every link counts as 23 characters, whatever its length | Confirmed |
| A mention | Only the username part counts; the server part of an address does not | Confirmed |
| A tag | Letters, digits and underscores; not digits alone | Confirmed |
| A content warning | The text of the post is collapsed behind it, and attached media is marked sensitive | Confirmed |
| Media | Up to 4 images, or one video, one animated GIF or one audio file | Confirmed |
| A limit other than the default on a given server | The page calls 500 the default; what a particular server allows was not read | Not confirmed |
| Length of alternative text | Not stated in the page read | Not confirmed |

## Facebook

No page of the platform was found on 2026-10-12 that states a limit for the text of a post: the search
returned pages on advertising formats and on messaging, which are different things. A figure is widely
repeated elsewhere; it is not given here, because nothing read confirms it.

| Fact | Value | Status |
|---|---|---|
| Length of a post | No figure given | Not confirmed |
| Links, tags and mentions | Not read | Not confirmed |

For a Facebook post the length band is written as an assumption in characters, and the user confirms it.

## What no platform documents

These are stated often and were found in no primary source. A post brief or a constraints file that relies
on one says that it is a belief.

- Where a feed cuts a post and shows the control to read on.
- That a post holding a link, or a given number of tags, is shown to fewer or more people.
- That an hour of the day or a day of the week is better for posting.
- That a given length performs best.

## Re-checking a row

1. Open the source of the row and find the sentence that states the figure.
2. If it still says the same, change `verified_on` and `review_by` of that platform's anchor and the two
   dates of its row in the Platforms table.
3. If it says something else, change the figure in the platform's section, in its Platforms row and in the
   anchor's `claim`, and the dates with it.
4. If the page is gone or no longer states it, set the row to Not confirmed and remove the figure.
5. A row never moves to Confirmed on a figure from a third party: only the platform's own documentation,
   announcement or schema counts.
<!-- doctrine:end file=social-post/references/platform-formats.md -->
