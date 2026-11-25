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
