# Entry template

Copy everything below the line to `entries/<slug>.md`, fill every field, then run `scripts/radar.py index` and `scripts/radar.py lint`.

---

```radar
name: Tool Name
slug: tool-name
category: other
alternative_to: what it replaces or competes with
homepage: https://example.org
repo: https://example.org/repo
licence_code: SPDX id of the code licence
licence_other: weights, data or engine licence, or n/a
cost: who pays for what (include data or API usage)
maturity: vX.Y.Z (YYYY-MM-DD), alpha / beta / stable
mcp: unknown
ring: assess
reviewed: YYYY-MM-DD
review_by: YYYY-MM-DD
suggested_by: role of the requester
related_skills: []
tags: [tag-one, tag-two]
verdict: One line: what it is and the decision.
origin: task id and review doc, if any
```

## What it is

Two or three sentences, in your words, not the vendor's.

## Verified facts

- VERIFIED: fact. Source: URL (read YYYY-MM-DD).
- LIKELY: fact. Source: URL (read YYYY-MM-DD).
- UNCERTAIN: what was not checked or conflicts.

## Claims that are false or overstated

- "Claim": what the primary source actually says.

## Foundry fit

- Skills it touches, the gap it fills, and conflicts with harness rules.

## Decision and next step

Ring and why. For hold, write "Hold because ...". Name the trigger or task that would change the ring.

## Sources

- https://example.org/primary-source (read YYYY-MM-DD)
