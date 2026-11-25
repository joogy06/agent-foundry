# Third-party SEO data: keyword volume, backlinks, competitors

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: openseo-pricing
    source_url: https://openseo.so/pricing
    verified_on: 2026-10-29
    review_by: 2027-01-27
    claim: "OpenSEO hosted: $10/mo incl. $10 usage (Pro $30 incl. $36, Agency $200 incl. $240); data cost +28%; $0.50 trial credit; keyword search about $0.05, backlink domain overview about $0.08."
  - kind: external_fact
    subject: openseo-licence-and-data-source
    source_url: https://github.com/every-app/open-seo
    verified_on: 2026-10-29
    review_by: 2027-01-27
    claim: "OpenSEO is MIT, backed by DataForSEO (self-host pays DataForSEO directly), ships an MCP server and agent skills."
-->

Owned by `seo-data-analyst`. The rest of this skill reads **first-party** data: what Search Console,
GA4, Bing Webmaster Tools and Clarity record about your own site. This reference covers the data you
cannot get that way and have to buy. Prices were read on 2026-10-29; past `review_by`, re-read the
source before quoting them.

Contents: [When first-party data is not enough](#when-first-party-data-is-not-enough) ·
[Provider landscape](#provider-landscape-by-trait-not-by-brand) ·
[Cost model](#cost-model-and-who-decides) · [Caveats](#caveats-modelled-not-measured) ·
[Combining with the recipes](#combining-with-the-first-party-recipes) · [MCP use](#mcp-use-is-advisory)

## When first-party data is not enough

| Question | Why GSC/GA4 cannot answer it |
|---|---|
| How much demand is there for a query we do not rank for? | GSC only reports queries where you were shown |
| Which queries do competitors rank for that we do not? (content gap) | GSC has no view of other sites |
| Who links to us, and to competitors? | GSC "Links" is a sample of your own backlinks only; nothing for competitors |
| How hard is this query to win? | Difficulty scores are modelled from other sites' link profiles |
| Which competitor pages gain or lose traffic? | Requires a third party's crawl and ranking panel |

If the question is about pages you already rank for, stay with GSC: it is measured and free.

## Provider landscape (by trait, not by brand)

| Type | Example | What you get | Cost shape |
|---|---|---|---|
| **Data broker (raw API)** | DataForSEO | Keyword, SERP, backlink and competitor endpoints; you build the queries and the UI | Pay per request, no seat fee |
| **Suite** | Ahrefs, Semrush | Own crawl and link index, polished UI, history, reports | Monthly seat subscription (OpenSEO's site frames these as "$100-plus") |
| **Open-source front end over a broker** | OpenSEO | A UI, MCP server and agent skills on top of a broker's API | Broker cost, plus a markup if hosted |

Choose by question volume. A few questions a month favour per-request pricing; daily multi-site
monitoring favours a suite. Suites and brokers use different indexes, so their numbers will disagree.

### Worked option: OpenSEO

- MIT licence, repository github.com/every-app/open-seo; data comes from DataForSEO.
- **Self-host:** the app is free; you open a DataForSEO account and pay DataForSEO directly.
- **Hosted (openseo.so, read 2026-10-29):** $10/month includes $10 of usage (Pro $30 incl. $36,
  Agency $200 incl. $240). Each action costs the data cost plus 28%. About **$0.05 per keyword
  search** and about $0.08 per backlink domain overview, by the vendor's own estimate.
- **No free tier.** The trial is $0.50 of credit; after that, every query costs money.
- Ships an **MCP server** and agent skills, so an agent can query it directly (see the MCP rules below).
- Status in foundry: `assess` ring. The full entry, with sources and the trial plan, is
  `skills/tool-radar/entries/openseo.md`.

## Cost model and who decides

Estimate before you query: `questions x queries per question x cost per query`. A 50-keyword
volume check is about 50 x $0.05 = $2.50 at the hosted rate; a competitor-gap sweep across five
domains with backlink overviews is tens of dollars. Every option above is paid, with no free tier.

**Spending is the owner's decision.** An agent may estimate the cost and propose the query; it does
not open accounts, add credit, choose a paid plan or run paid queries without the owner's approval of
that budget. Record the actual cost per question afterwards (the radar entry asks for it).

## Caveats: modelled, not measured

- Third-party volume, traffic and difficulty figures are **modelled estimates** from clickstream
  panels and rank-times-CTR curves. They are not measurements, and they often overstate; treat them
  as directional, as `seo-keyword-strategist` already says.
- **Do not mix them with GSC impressions as if they were the same quantity.** Tool "volume" is an
  estimated monthly searches figure; GSC impressions count times your result was shown, at your
  position, in your market. Report them in separate columns and never add, average or ratio them
  across sources without saying so.
- Backlink counts depend on each provider's crawl; two providers will give two different totals.
  Compare like with like (one provider, over time).
- Check the country and language settings match your market (UK vs US volumes differ widely).

## Combining with the first-party recipes

| Recipe (SKILL.md) | Third-party data adds | Rule |
|---|---|---|
| **Striking distance** (positions 4-20) | Estimated volume and difficulty to rank the GSC list | GSC picks the candidates; third-party data only orders them |
| **Cannibalisation** | Competitor SERP snapshot for the contested query | The diagnosis still comes from GSC query-page rows |
| **Content gaps** | Queries competitors rank for and you do not | Shortlist, then check intent by hand before planning content (`seo-content-strategist`) |
| **Authority** | Referring domains, yours vs competitors | Feeds `seo-authority-builder`; never buy links on its evidence |

Start from first-party data, use third-party data to fill the blind spots, and label every number
with its source.

## MCP use is advisory

- **Read-only queries only.** The agent asks for data; it does not change account settings, buy
  credit or create paid projects through the MCP server.
- **Budget cap per session.** Agree a cap with the owner up front (for example $2), keep a running
  cost estimate, and stop at the cap rather than continuing.
- Prefer narrow queries (one domain, one keyword list, sensible result limits) over broad sweeps.
- Keep the API key in `~/.secrets/<project>.env` per `secret-scanning`, never in the repo or a prompt.
