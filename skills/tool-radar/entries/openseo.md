```radar
name: OpenSEO
slug: openseo
category: seo-data
alternative_to: Ahrefs, Semrush (keyword, backlink and competitor data)
homepage: https://openseo.so
repo: https://github.com/every-app/open-seo
licence_code: MIT
licence_other: n/a (data comes from DataForSEO under its own terms)
cost: self-host free but DataForSEO usage is paid by you; hosted $10/mo incl. $10 usage, data at cost +28%; $0.50 trial, no free tier
maturity: active (release date not recorded in #369)
mcp: server
ring: assess
reviewed: 2026-10-29
review_by: 2027-01-27
suggested_by: owner (shared video, task #369)
related_skills: [seo-data-analyst, seo-keyword-strategist]
tags: [seo, keywords, backlinks, competitor-research, dataforseo, ahrefs-alternative, semrush-alternative, mcp, agent-skills]
verdict: Fills the third-party SEO data gap (keywords, backlinks, competitors); usage is paid. Trial if the owner funds DataForSEO.
origin: #369, docs/reviews/2026-10-29-video-tools-369.md
```

## What it is

An open-source SEO research app (keywords, backlinks, competitor pages) that reads its data from the paid DataForSEO API. It ships an MCP server and agent skills.

## Verified facts

- VERIFIED: MIT licence, repository github.com/every-app/open-seo. Source: https://github.com/every-app/open-seo (via #369, 2026-10-29).
- VERIFIED: data is backed by DataForSEO. Self-hosting the app is free, but you pay DataForSEO yourself. Source: https://github.com/every-app/open-seo (via #369, 2026-10-29).
- VERIFIED: hosted plan $10/month including $10 of usage, data charged at DataForSEO cost +28%; a $0.50 trial, no free tier. Source: https://openseo.so (via #369, 2026-10-29).
- VERIFIED: further tiers Pro $30/month including $36 of usage and Agency $200/month including $240; about $0.05 per keyword search and about $0.08 per backlink domain overview at typical result limits (the vendor estimator shows 100 searches as $5.40). Source: https://openseo.so/pricing (read 2026-10-29).
- VERIFIED: ships an MCP server and agent skills. Source: https://github.com/every-app/open-seo (via #369, 2026-10-29).

## Claims that are false or overstated

- "Free": the code is free; the data is not. There is no free tier, only a $0.50 trial.

## Foundry fit

- `seo-data-analyst` covers first-party data only (Search Console, GA4, Bing Webmaster, Clarity). Nothing in foundry supplies third-party keyword volume, backlink or competitor data; this is the gap OpenSEO fills.
- Proposed follow-up from #369: a short third-party-data reference in `seo-data-analyst`. Not done; awaits the owner.
- Paid usage: spending is the owner's decision.

## Decision and next step

Assess. Trial if the owner funds DataForSEO: then try it on one real keyword or competitor question and record cost per question here.

## Sources

- https://github.com/every-app/open-seo (via #369, 2026-10-29)
- https://openseo.so (via #369, 2026-10-29)
- Foundry review: docs/reviews/2026-10-29-video-tools-369.md (task #369), which checked each claim against primary sources on 2026-10-29. The review keeps its conclusions, not per-fact read receipts: facts marked "via #369" are inherited from it, and the URL beside each is the primary page for that fact (repo URLs from the review or the video's resource page), not a fresh re-read.
