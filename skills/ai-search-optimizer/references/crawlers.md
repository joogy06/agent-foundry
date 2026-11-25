# AI crawlers and agents, in three classes

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: status_snapshot
    subject: ai-crawler-table
    verified_against: "Three-class UA table: Google, OpenAI, Anthropic, Perplexity, Meta, Amazon, Apple, DuckDuckGo, Microsoft; robots.txt behaviour per class; IP-JSON URLs"
    verified_on: 2026-09-27
    review_by: 2026-12-26
  - kind: external_fact
    subject: cloudflare-ai-crawl-control-defaults
    source_url: https://developers.cloudflare.com/changelog/post/2026-07-01-ai-traffic-options
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "Search/Agent/Training split on all plans; from 2026-09-15 new domains block Training and Agent bots on pages that show ads by default."
-->

Owned by `ai-search-optimizer`. `ai-assistant-referrals` uses this table for server-log analysis;
it does not restate it. Every row was checked on 2026-09-27. **V** = the vendor page was fetched and
says this; **I** = inferred.

## The three classes

| Class | What it does | Blocking it costs | robots.txt |
|---|---|---|---|
| **Index / search** | Builds the index an answer engine cites from | Citations and links in that engine | Honoured |
| **Training** | Collects data for model training | Nothing in search; refusing Google-Extended also drops Gemini-app/Vertex grounding | Honoured |
| **User-triggered** | Fetches a page because a person asked an assistant to, now | That person's answer, or an agent's task | **Often ignored** (see the table) |

A user-triggered fetcher acts for one person in real time, so several vendors say robots.txt "may
not apply". **robots.txt is therefore not the whole control surface.** For those agents the controls
are `noindex`/`nosnippet`, CDN rules, and signed-agent verification.

## The table

| Vendor | Index / search | Training | User-triggered (robots.txt?) | IP list | Source (V) |
|---|---|---|---|---|---|
| Google | Googlebot, Storebot-Google, Google-InspectionTool, GoogleOther, Google-CloudVertexBot | `Google-Extended` (robots token only, no UA; Gemini training and Gemini grounding) | **Google-Agent**: "generally ignores robots.txt"; experimental Web Bot Auth identity `agent.bot.goog` | `user-triggered-agents.json` | https://developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers · https://developers.google.com/crawling/docs/crawlers-fetchers/google-user-triggered-fetchers |
| OpenAI | OAI-SearchBot; **OAI-AdsBot** (ad landing pages) | GPTBot | **ChatGPT-User**: "robots.txt rules may not apply" | JSON per bot | https://developers.openai.com/api/docs/bots |
| Anthropic | Claude-SearchBot | ClaudeBot | **Claude-User: honours robots.txt** (all three do) | `claude.com/crawling/bots.json` | https://support.claude.com/en/articles/8896518 |
| Perplexity | PerplexityBot (respects robots.txt) | none | **Perplexity-User**: "generally ignores robots.txt" | published | https://docs.perplexity.ai/guides/bots |
| Meta | **meta-webindexer** (Meta AI search) | meta-externalagent | **meta-externalfetcher**: "may bypass robots.txt" | none published | https://developers.facebook.com/docs/sharing/webmasters/web-crawlers |
| Amazon | **Amzn-SearchBot** (Alexa and search, not training) | Amazonbot (may train) | Amzn-User | published | https://developer.amazon.com/amazonbot |
| Apple | Applebot (Spotlight, Siri, Safari; falls back to Googlebot rules) | `Applebot-Extended` (robots token; training only; disallowed pages still appear in Apple search) | none documented | published | https://support.apple.com/en-us/119829 |
| DuckDuckGo | DuckDuckBot | none | **DuckAssistBot/1.2**: real-time, not training, respects robots.txt within 72 h | `duckduckgo.com/duckassistbot.json` | https://duckduckgo.com/duckduckgo-help-pages/results/duckassistbot |
| Microsoft | bingbot (also feeds Copilot) | no separate token yet; a bingbot training opt-out is a **FORECAST** for early 2027 [V, Cloudflare reporting Microsoft: https://blog.cloudflare.com/accountable-mixed-use-ai-crawlers/] | none documented | published | https://blogs.bing.com/webmaster |
| xAI (Grok) | not documented | not documented | reportedly spoofs browser UAs [I, could not verify] | none | none |

`CCBot` (Common Crawl) is a training source for many models, and `Bytespider` (ByteDance) is widely
reported as a training crawler [I, no vendor page fetched]; both belong to the training class.

## robots.txt template: allow search, ask about training

> **Read before copying.** Under RFC 9309 a crawler obeys only the **most specific group that
> names it**, and that group **replaces** `User-agent: *` entirely. A named group holding only
> `Allow: /` therefore lets those bots into every crawl trap the `*` group blocked: cart,
> checkout, account and admin pages and endless `?add-to-cart=` / `?orderby=` / `?filter_`
> parameter URLs. Repeat the site's rules **inside every named group**, exactly: the disallows,
> the `admin-ajax.php` allow and the `Content-Signal` line. A query disallow must cover the
> parameter in **any position**: `/*?add-to-cart=` alone misses
> `/product/x/?utm_source=chatgpt.com&add-to-cart=123`, so the template also carries
> `/*&add-to-cart=` (`/*?*filter_` and `/*?*orderby=` already match any position). The
> WooCommerce set is shown; add your own site's traps to every group.
>
> **The `*` facet disallows change Googlebot's crawl.** Googlebot and bingbot have no named group,
> so they follow `*`, and the `?filter_` and `?orderby=` lines stop them crawling filtered and
> sorted listings. That is usually right, but a store that serves index-worthy facet landing
> pages on those parameters would lose them. Check both lines against the store's facet policy in
> `woocommerce-faceted-navigation` before shipping. Never add a line that matches a product URL.

**Ask the owner one question before writing the file: "Do you want your content used for AI model
training? yes / no".** The recommended answer is **"yes"**: models learn a brand, its products and
its categories from training data, so allowing it is how a store becomes something a model can name
and describe without a live search. Recommend "no" only for a specific reason (licensed, paywalled
or proprietary content, or a legal instruction). Training does not guarantee citation: live citation
comes from the search and answer crawlers, which both variants allow. It is still the owner's call:
do not ship either variant until the question is answered, and record the answer where the policy
is written down ("One training policy", below). The two variants are identical except for the
`ai-train` value and the training group: the cart, checkout and add-to-cart disallows, the
`admin-ajax.php` allow, the `Sitemap:` line and the facet warning above hold in both. The training
tokens, from the table: `GPTBot`, `ClaudeBot`, `CCBot`, `meta-externalagent`, `Amazonbot`,
`Applebot-Extended`, `Bytespider` and `Google-Extended`.

### Variant: training allowed (answer "yes")

Search bots and training bots may read product pages; every named group still repeats the traps.

```
# Everyone else, including Googlebot and bingbot: site traps, plus the training answer
User-agent: *
Content-Signal: search=yes, ai-input=yes, ai-train=yes
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php
Disallow: /cart/
Disallow: /checkout/
Disallow: /my-account/
Disallow: /*?add-to-cart=
Disallow: /*&add-to-cart=
Disallow: /*?*filter_
Disallow: /*?*orderby=

# Index / search (ALLOW, but this group REPLACES *, so it repeats every rule above)
User-agent: OAI-SearchBot
User-agent: Claude-SearchBot
User-agent: PerplexityBot
User-agent: meta-webindexer
User-agent: Amzn-SearchBot
User-agent: DuckAssistBot
Content-Signal: search=yes, ai-input=yes, ai-train=yes
Allow: /
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php
Disallow: /cart/
Disallow: /checkout/
Disallow: /my-account/
Disallow: /*?add-to-cart=
Disallow: /*&add-to-cart=
Disallow: /*?*filter_
Disallow: /*?*orderby=

# Training (ALLOWED: the owner answered yes; this group REPLACES *, so it repeats every rule)
User-agent: GPTBot
User-agent: ClaudeBot
User-agent: CCBot
User-agent: meta-externalagent
User-agent: Amazonbot
User-agent: Applebot-Extended
User-agent: Bytespider
User-agent: Google-Extended
Content-Signal: search=yes, ai-input=yes, ai-train=yes
Allow: /
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php
Disallow: /cart/
Disallow: /checkout/
Disallow: /my-account/
Disallow: /*?add-to-cart=
Disallow: /*&add-to-cart=
Disallow: /*?*filter_
Disallow: /*?*orderby=

Sitemap: https://www.example.co.uk/sitemap_index.xml
```

### Variant: training refused (answer "no")

Search bots may read product pages; the training tokens are refused everywhere.

```
# Everyone else, including Googlebot and bingbot: site traps, plus the training answer
User-agent: *
Content-Signal: search=yes, ai-input=yes, ai-train=no
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php
Disallow: /cart/
Disallow: /checkout/
Disallow: /my-account/
Disallow: /*?add-to-cart=
Disallow: /*&add-to-cart=
Disallow: /*?*filter_
Disallow: /*?*orderby=

# Index / search (ALLOW, but this group REPLACES *, so it repeats every rule above)
User-agent: OAI-SearchBot
User-agent: Claude-SearchBot
User-agent: PerplexityBot
User-agent: meta-webindexer
User-agent: Amzn-SearchBot
User-agent: DuckAssistBot
Content-Signal: search=yes, ai-input=yes, ai-train=no
Allow: /
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php
Disallow: /cart/
Disallow: /checkout/
Disallow: /my-account/
Disallow: /*?add-to-cart=
Disallow: /*&add-to-cart=
Disallow: /*?*filter_
Disallow: /*?*orderby=

# Training (REFUSED: the owner answered no). Google-Extended included: see below
User-agent: GPTBot
User-agent: ClaudeBot
User-agent: CCBot
User-agent: meta-externalagent
User-agent: Amazonbot
User-agent: Applebot-Extended
User-agent: Bytespider
User-agent: Google-Extended
Disallow: /

Sitemap: https://www.example.co.uk/sitemap_index.xml
```

**In the refuse variant, refusing Google-Extended has a cost.** Google documents the token as
controlling use for training Gemini models **and** for grounding in Gemini Apps and in Grounding
with Google Search on Vertex AI; it "does not impact a site's inclusion in Google Search nor is it
used as a ranking signal" [V https://developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers,
fetched 2026-09-27]. Refusing it costs the store its pages as grounding in the Gemini app and
Vertex AI answers. Google Search, AI Overviews and AI Mode are unaffected: they follow Googlebot
and the Search Console setting ([controls.md](controls.md)). In the allow variant there is no such
cost.

**The one permitted exception (refuse variant only).** A store that answered "no" but values
Gemini-app grounding may allow `Google-Extended`, but only as a declared exception: move the token
to its own group that repeats every `*` rule with `Allow: /`, and add the line
`# training-exception: Google-Extended (Gemini grounding kept; Google may train on the site)`
to the file, so a reader and the family's test see a decision, not a contradiction. Record the
same exception wherever the policy is written down. No other token has an exception, and the allow
variant takes none: with `ai-train=yes` every training token is allowed.

User-triggered agents (ChatGPT-User, Perplexity-User, Google-Agent, meta-externalfetcher) are left
out on purpose: several ignore robots.txt, so a line for them only gives a false sense of control.

## One training policy, chosen per business

The family always allows search and AI answers (input). **Training is the owner's answer to the
question above, yes or no; the family recommends "yes" and the owner decides.** Whichever it is, it is expressed three
ways, which must agree:

1. robots.txt: the training group of the matching variant above (allowed for "yes"; disallowed
   for "no", `Google-Extended` included or declared as the one exception).
2. robots.txt: `Content-Signal: search=yes, ai-input=yes, ai-train=yes` (answer "yes") or
   `Content-Signal: search=yes, ai-input=yes, ai-train=no` (answer "no") in the `*` group and
   every allowing named group (any host).
3. HTTP: the same `Content-Signal` header from the origin. It matters most where a CDN rewrites
   responses: Cloudflare Markdown for Agents adds `ai-train=yes` unless the origin already sends a
   signal, and the origin header takes precedence (checked live 2026-09-27). Syntax and the
   WordPress snippet: `markdown-for-agents` → [implementation](../../markdown-for-agents/references/implementation.md).

A store that changes its answer changes all three together, never one.

## Verify identity: never trust a UA string alone

1. Match the UA **and** the source IP against the vendor's published IP JSON.
2. Or verify a signed request: **Web Bot Auth** (IETF `draft-ietf-webbotauth-httpsig-protocol-00`,
   an Internet-Draft; its Apr 2026 milestone was missed) [V https://datatracker.ietf.org/wg/webbotauth/documents/].
   ChatGPT agent reportedly signs with `Signature-Agent: "https://chatgpt.com"` [I].
3. Unverifiable traffic claiming to be an AI agent is treated as an ordinary bot.

## Browser agents render the page

Index crawlers mostly read the initial HTML. **Browser agents render it**: ChatGPT's browsing agent
reads ARIA roles and labels [V https://help.openai.com/en/articles/12627856-publishers-and-developers-faq];
Claude in Chrome and Google-Agent drive a real browser. For them, accessible labelled HTML matters
more than a markdown mirror. ChatGPT Atlas was discontinued on 2026-08-09 [V
https://help.openai.com/en/articles/20001371-evolving-atlas-into-chatgpt-for-browser-based-agentic-work].

## CDN defaults (host-conditional: only if you are on that CDN)

Cloudflare, checked 2026-09-27:

- AI Crawl Control splits bots into **Search / Agent / Training** on all plans. **From 2026-09-15,
  new domains block Training and Agent bots on pages that show ads by default** [V
  https://developers.cloudflare.com/changelog/post/2026-07-01-ai-traffic-options].
- Signed agents count as Verified bots from 2026-07-01, with a Direct vs Intermediary field [V
  https://developers.cloudflare.com/bots/concepts/bot/signed-agents/].
- Pay per crawl is still **closed beta**, evolving into "Pay Per Use"; the Monetization Gateway
  (x402) has a waitlist (FORECAST) [V https://developers.cloudflare.com/ai-crawl-control/features/pay-per-crawl/what-is-pay-per-crawl].
- Content Signals Policy (`search=`, `ai-input=`, `ai-train=`) [V https://blog.cloudflare.com/content-signals-policy].
  The values follow the owner's training answer, set once in "One training policy" above.
- Cloudflare de-listed Perplexity as a verified bot over stealth crawling on 2025-08-04 [V
  https://blog.cloudflare.com/perplexity-is-using-stealth-undeclared-crawlers-to-evade-website-no-crawl-directives/].

On another CDN (a host CDN, for example), check what its bot rules do to each class before assuming
the robots.txt above is what agents see.

## Preference standards (drafts, not rules)

- IETF AIPREF (vocab-08, attach-05) are working-group drafts, not RFCs [V https://datatracker.ietf.org/wg/aipref/documents/].
- RSL 1.0 has publisher and CDN supporters and no AI-company adoption [V https://rslstandard.org].
