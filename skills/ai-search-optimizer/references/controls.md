# AI controls, vendor reporting and UK regulation

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: search-console-generative-ai-control
    source_url: https://support.google.com/webmasters/answer/16908024
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "Search Console 'Search generative AI' setting (include/exclude/inherit), per property, worldwide from 2026-08-31."
  - kind: external_fact
    subject: bing-ai-meta-controls
    source_url: https://blogs.bing.com/webmaster/september-2023/Announcing-new-options-for-webmasters-to-control-usage-of-their-content-in-Bing-Chat
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "NOARCHIVE removes a page from Copilot answers and training while keeping it in search; NOCACHE limits use to URL, title and snippet."
  - kind: external_fact
    subject: cma-google-sms-conduct-requirements
    source_url: https://www.gov.uk/cma-cases/googles-general-search-and-search-advertising-services
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "SMS designation 2025-10-10; publisher conduct requirement 2026-06-03 (9 months to implement); fair ranking and portability 2026-06-17; choice-screen consultation 2026-09-23."
  - kind: external_fact
    subject: apple-applebot-extended
    source_url: https://support.apple.com/en-us/119829
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "Applebot-Extended controls training only; disallowed pages still appear in Safari, Spotlight and Siri."
-->

Owned by `ai-search-optimizer`. V = vendor or government page fetched 2026-09-27; I = inferred.

## Google

| Control | What it does | Source |
|---|---|---|
| **Search Console "Search generative AI" setting** (Settings; include / exclude / inherit) | Excluding removes the site from AI Overviews, AI Mode and Discover AI features, as links and as grounding. **Per property**, not a ranking signal, separate from `Google-Extended`. UK test from 2026-06-03, worldwide 2026-08-31 | [V https://support.google.com/webmasters/answer/16908024] |
| `nosnippet`, `max-snippet`, `data-nosnippet`, `noindex` | Govern AI Overview and AI Mode input. There is no AI-specific robots meta directive | [V https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag] |
| `Google-Extended` robots token | Gemini training **and** grounding in Gemini Apps and Grounding with Google Search on Vertex AI; not Search inclusion, ranking or AI Overviews. Allowed or refused with the other training tokens, by the owner's answer to the training question; refusing it costs that grounding (the one exception: [crawlers.md](crawlers.md)) | [V https://developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers] |
| Preferred sources | Users can prefer a source; extended to AI Overviews and AI Mode on 2026-05-27 | [V https://developers.google.com/search/updates] |
| Bing `NOARCHIVE` (meta) | Removes a page from Copilot answers and training, keeps it in Bing search | [V https://blogs.bing.com/webmaster/september-2023/Announcing-new-options-for-webmasters-to-control-usage-of-their-content-in-Bing-Chat] |
| Bing `NOCACHE` (meta) | Limits Copilot use to URL, title and snippet | [V, same] |
| Bing `data-nosnippet` | Supported from 2025-10-15 | [V https://blogs.bing.com/webmaster] |
| CMA page- and directory-level AI opt-out for Google | **FORECAST**, due about 2027-03-03 | [I, ppc.land] |

This is the family's **one** AI-controls table. `seo-meta-optimizer` owns the tag and attribute
syntax; this skill owns the decision to opt in or out.

Google: "You don't need to create new machine readable files, AI text files, or markup to appear in
these features" [V https://developers.google.com/search/docs/appearance/ai-features]. Its guide to
generative AI features (2026-05-15) says spam policies apply to AI responses [V
https://developers.google.com/search/blog/2026/05/a-new-resource-for-optimizing].

**Reporting:** the Search Console **Generative AI performance report** gives impressions only (no
clicks, no queries) by page, country, device and date; worldwide from 2026-08-31 [V
https://support.google.com/webmasters/answer/16984139]. AI Overview and AI Mode clicks are counted in
the ordinary Performance report, mixed with organic. Measurement method: `ai-assistant-referrals`.

## Microsoft (Bing, Copilot, Edge)

- Bing's AI meta controls are rows in the Google table above.
- **Bing Webmaster Tools AI Performance** (public preview, 2026-02-10): Copilot and Bing AI
  citations, grounding queries and per-page citations; no clicks [V
  https://blogs.bing.com/webmaster/February-2026/Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview].
  It is the only first-party source of *prompt-like* queries.
- Edge Journeys runs on Edge desktop in en-GB; Copilot Mode in Edge was folded into Edge on
  2026-05-13 [V https://blogs.windows.com/msedgedev/2026/05/13/new-updates-to-edge-across-desktop-and-mobile/].
- NLWeb (MIT, MCP `/ask`) is open source; the last commit was 2026-06-10 [V https://github.com/microsoft/NLWeb].
- UK weight: Bing and Copilot shares are rows in `data/surfaces.v1.json` (`gb_share`).

## Apple

- **Applebot** powers Spotlight, Siri and Safari search and may train Apple models; with no Applebot
  rules it follows the Googlebot rules. **Applebot-Extended controls training only** [V, anchor above].
- **Siri AI** (iOS 27, beta, English) answers from the web and is built with Google's Gemini models
  [V https://www.apple.com/newsroom/2026/09/siri-ai-a-profoundly-more-capable-and-personal-assistant-is-here/].
  GB status: registry row `apple-siri-ai`.
- Safari "Notify Me" (iOS 27) alerts users when a page changes, such as a price drop or restock [V
  https://www.apple.com/newsroom/2026/06/apple-unveils-next-generation-of-apple-intelligence-siri-ai-and-more/].
  It rewards accurate on-page price and stock, and punishes a stale one.
- Business Connect is now **Apple Business** (Maps listing, brand, Maps ads) [V https://business.apple.com/; UK scope: I].

## UK regulation

| Item | Status | Source |
|---|---|---|
| CMA designated Google with Strategic Market Status in general search | 2025-10-10 | [V https://www.gov.uk/cma-cases/googles-general-search-and-search-advertising-services] |
| **Publisher conduct requirement**: opt-out from AI features and fine-tuning, attribution links; 9 months to implement | Imposed 2026-06-03 | [V https://www.gov.uk/government/news/cma-secures-fairer-deal-for-publishers-and-improves-google-search-services-in-uk] |
| Fair-ranking and data-portability requirements | Imposed 2026-06-17 | [V, case page above] |
| Choice-screen consultation | Opened 2026-09-23 (FORECAST outcome) | [V, case page above] |
| Page- and directory-level AI opt-out | **FORECAST**, due about 2027-03-03 | [I, ppc.land] |
| **DMCCA 2024 Sch. 20 para 13**: submitting or commissioning fake or concealed-incentive consumer reviews is always unfair | In force 2025-04-06 | [V https://www.legislation.gov.uk/ukpga/2024/13/schedule/20] |

Analytics consent (DUAA 2025) is measurement law and lives in `ai-assistant-referrals`.

## Paid AI surfaces (kept apart from organic)

Ads are bought placement, **not** organic citation. Report them separately, never add paid AI clicks
to an organic "AI visibility" number, and never cite ad reach as evidence that content work is
working. Which paid surfaces exist and their GB status are registry rows (`channel: paid`):

```bash
python3 ~/.claude/skills/ai-search-optimizer/scripts/surfaces.py show --channel paid
```

Tag every paid AI link with `utm_medium=paid` so `ai-assistant-referrals` can keep it off the
organic line. OAI-AdsBot fetches ChatGPT Ads landing pages (crawler table).
