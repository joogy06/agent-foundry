# Product feeds for AI surfaces

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: content-api-for-shopping-sunset
    source_url: https://developers.google.com/shopping-content/guides/rel-notes
    verified_on: 2026-09-27
    review_by: 2027-03-26
    claim: "Content API for Shopping sunset 2026-08-18; progressive errors since 2026-09-01; an extension form exists."
  - kind: external_fact
    subject: merchant-center-conversational-attributes
    source_url: https://support.google.com/merchants/answer/17085370
    verified_on: 2026-09-27
    review_by: 2027-03-26
    claim: "Six conversational attributes used by AI Mode, sent via primary or supplemental source, Merchant API or TSV."
  - kind: external_fact
    subject: indexnow-consumers
    source_url: https://www.indexnow.org/searchengines.json
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "Bing, Yandex, Seznam, Naver, Yep, Internet Archive and AmazonBot consume IndexNow; Google does not."
-->

Owned by `ai-search-optimizer`. Which surfaces a feed reaches, and each one's GB
status, is in the registry (`data/surfaces.v1.json`); this file is the HOW. V = vendor page
fetched 2026-09-27; I = inferred.

## 1. Google Merchant Center: check the feed path first

**The Content API for Shopping was sunset on 2026-08-18, and progressive errors have been returned
since 2026-09-01.** An extension form exists [V https://developers.google.com/shopping-content/guides/rel-notes].
Reported extension end dates of 15 Oct or 31 Dec 2026 are unverified [I, feed-vendor blogs].

A store whose feed plugin still calls the Content API can be losing products from Shopping, AI Mode
and every surface built on the Shopping Graph without any visible error on the site. Check:

1. Which API your feed plugin or feed service uses. It must be the **Merchant API**.
2. Merchant Center diagnostics for API errors dated from 2026-09-01.
3. That product counts in Merchant Center match the catalogue.

If the plugin cannot say which API it uses, treat that as a finding and ask the vendor.

## 2. Conversational attributes (AI Mode input)

Six attributes, sendable through a primary or supplemental source, the Merchant API or TSV
[V https://support.google.com/merchants/answer/17085370; that they are live in every country: I]:

| Attribute | Use it for |
|---|---|
| `question_and_answer` | Real buyer questions with factual answers (compatibility, what is in the box) |
| `document_link` | Manuals, spec sheets, warranty documents |
| `related_product` | Accessories and compatible parts |
| `item_group_title` | The family name shared by variants |
| `variant_option` | What distinguishes this variant |
| `popularity_rank` | Your own sales rank |

Supplemental sources let you add these without touching the primary feed. Answers must match the
product page and the markup; Merchant Center settings beat on-page markup where they conflict (see
`seo-structure-architect`, shipping and returns precedence).

## 3. Microsoft Merchant Center and IndexNow

- A Microsoft Merchant Center feed informs **organic** Copilot shopping results [V
  https://about.ads.microsoft.com/en/blog/post/january-2026/conversations-that-convert-copilot-checkout-and-brand-agents].
- UCP feeds are generally available in Microsoft Merchant Center (markets: registry row
  `copilot-checkout`), and Brand Agents now support WooCommerce [V
  https://about.ads.microsoft.com/en/blog/post/april-2026/win-across-all-three-eras-of-the-web].
- **IndexNow** pushes changed URLs to Bing, Yandex, Seznam, Naver, Yep, the Internet Archive and
  AmazonBot. **Google is not a consumer** [V https://www.indexnow.org/searchengines.json]. Ping it on
  price and stock changes.

## 4. OpenAI product feeds

- ACP was extended to **discovery** on 2026-03-24: merchant feeds and promotions, also delivered via
  Salesforce or Stripe [V https://openai.com/index/powering-product-discovery-in-chatgpt/].
- The Product Feed Spec onboards "approved partners" through an application form, with no country
  list published [V https://developers.openai.com/commerce/guides/get-started]. Whether it accepts
  UK/GBP merchants **could not be verified**: apply, and do not promise a result.
- There is **no official WooCommerce ACP plugin**; WooCommerce lists ACP as "Coming soon" [V
  https://woocommerce.com/agentic-commerce]. Third-party plugins exist [I].

## 5. Feed priority for a UK merchant (as of 2026-09-27)

1. **Google Merchant Center** via the Merchant API, with the conversational attributes.
2. **Microsoft Merchant Center**, plus IndexNow.
3. **OpenAI direct feed application**, as an option with an unknown GB outcome.
4. Other assistant programmes: only where the registry row for your market is live or beta:
   `python3 ~/.claude/skills/ai-search-optimizer/scripts/surfaces.py show --type shopping`.

Small team minimum: Merchant Center only, kept current. A stale feed is worse than none, because an
assistant quotes it.

## 6. Protocols

Checkout protocols (ACP, UCP, AP2, card-network agent protocols) and whether to build for them are
owned by `agentic-commerce-readiness`. The feed work above pays whatever that verdict is.
