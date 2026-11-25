# Agentic commerce standards map

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: acp-stable-version
    source_url: https://github.com/agentic-commerce-protocol/agentic-commerce-protocol
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "ACP latest stable 2026-04-17 (cart, feed, orders, authentication, MCP), maintained by OpenAI and Stripe."
  - kind: external_fact
    subject: ucp-version-and-codevelopers
    source_url: https://ucp.dev
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "UCP co-developed by Google, Shopify, Amazon, Walmart, Target, Microsoft, Meta, Salesforce; 70+ endorsers; REST, JSON-RPC, MCP, A2A, AP2 transports; latest tag v2026-08-25."
  - kind: external_fact
    subject: ap2-fido
    source_url: https://ap2-protocol.org
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "AP2 donated to FIDO (2026-04-28), v0.2 with Human Not Present; beta."
  - kind: external_fact
    subject: stripe-acs-seller-countries
    source_url: https://docs.stripe.com/agentic-commerce/for-sellers
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "Stripe Agentic Commerce Suite lists GB as a seller country (API 2026-08-26.preview)."
  - kind: external_fact
    subject: paypal-agent-ready-platforms
    source_url: https://developer.paypal.com/agentic-commerce-services/about
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "PayPal Agent Ready / Store Sync is a request-only beta; named platforms Wix, BigCommerce, Shopware and Cymbio, not WooCommerce."
  - kind: external_fact
    subject: adyen-agentic-eligibility
    source_url: https://www.adyen.com/press-and-media/adyen-agentic
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "Adyen Agentic (UCP, ACP, AP2) is limited to US enterprise merchants."
  - kind: external_fact
    subject: woocommerce-agentic-status
    source_url: https://woocommerce.com/agentic-commerce
    verified_on: 2026-09-27
    review_by: 2026-12-26
    claim: "WooCommerce ACP and UCP both 'Coming soon'; WooCommerce MCP developer preview (WP 6.9 + WC 10.3)."
-->

Owned by `agentic-commerce-readiness`. V = primary page fetched 2026-09-27; I = inferred. Which
checkout **surfaces** use these protocols, and each one's GB status, is in
`ai-search-optimizer/data/surfaces.v1.json` (rows with `surface_type: checkout`).

## Protocol layers

| Layer | Standard | State | Source |
|---|---|---|---|
| Checkout / catalogue | **ACP** (Agentic Commerce Protocol) | Stable **2026-04-17**: cart, feed, orders, authentication, MCP. Maintained by OpenAI and Stripe; an unreleased branch was active to 2026-07-18. Extended to discovery feeds on 2026-03-24 | [V https://github.com/agentic-commerce-protocol/agentic-commerce-protocol] |
| Checkout / catalogue | **UCP** (Universal Commerce Protocol) | Announced 2026-01-11; cart, catalogue and identity linking added 2026-03-19; latest tag **v2026-08-25**. Co-developers Google, Shopify, Amazon, Walmart, Target, **Microsoft, Meta** and Salesforce, 70+ endorsers. Transports REST, JSON-RPC, MCP, A2A and AP2. **Required for Copilot Checkout** and Google's agentic checkout | [V https://ucp.dev · https://blog.google/products-and-platforms/products/shopping/ucp-updates/] |
| Payment consent | **AP2** (Agent Payments Protocol) | Donated to FIDO (2026-04-28); v0.2 adds "Human Not Present"; Mastercard co-developed Verifiable Intent. First implementation planned in "Gemini Spark" (FORECAST). Beta | [V https://ap2-protocol.org] |
| Card network | **Visa Trusted Agent Protocol** and Intelligent Commerce Connect (accepts TAP, ACP and UCP; Connect is a beta from 2026-04-09) | **Agentic transactions completed in Europe with UK issuers** (Barclays, HSBC UK, Lloyds, NatWest, Nationwide, Revolut) and UK merchants, 2026-07-02, using passkeys | [V visa.co.uk press releases 3457328 and 3442048] |
| Card network | **Mastercard Agent Pay** | First live European agent payment (Santander); beta | [I, press] |
| Merchant tools | **MCP** (WooCommerce MCP; WebMCP in the browser) | WooCommerce MCP is a developer preview (WP 6.9 + WC 10.3). WebMCP is a Chrome 150+ origin trial (FORECAST for production) | [V https://developer.woocommerce.com/docs/features/mcp · https://developer.chrome.com/docs/lighthouse/agentic-browsing] |

These layers **stack**: ACP and UCP are rival *checkout* dialects that PSPs and networks increasingly
accept side by side; AP2 and the card-network protocols prove *authorisation*. "One ACP integration
via your PSP" is no longer enough to reach every surface.

## PSP and platform support (do not assume Stripe)

| PSP / platform | Agentic support, as of 2026-09-27 | Source |
|---|---|---|
| Stripe Agentic Commerce Suite | Lists **GB** as a seller country, as of 2026-09-27 (API `2026-08-26.preview`); re-read the page for your market | [V https://docs.stripe.com/agentic-commerce/for-sellers] |
| WooCommerce | ACP (via Stripe) and UCP are both **"Coming soon"**. No official Automattic plugin; third-party plugins exist [I] | [V https://woocommerce.com/agentic-commerce] |
| PayPal Agent Ready / Store Sync | Request-only beta; named platforms Wix, BigCommerce, Shopware and Cymbio, **not WooCommerce**; UK not stated | [V https://developer.paypal.com/agentic-commerce-services/about] |
| Adyen Agentic (UCP, ACP, AP2) | Beta, limited to **US enterprise merchants** as of 2026-09-27; re-read the page for your market | [V https://www.adyen.com/press-and-media/adyen-agentic] |
| Worldpay | Reported UCP endorsement and a Worldpay MCP; **could not be verified** | [I] |

Score your own PSP from its own page, for your platform **and** your market.

## Agent identity: how to "govern per agent"

- **Web Bot Auth** (IETF Internet-Draft `draft-ietf-webbotauth-httpsig-protocol-00`; its Apr 2026
  milestone was missed) signs agent requests [V https://datatracker.ietf.org/wg/webbotauth/documents/].
- **Cloudflare signed agents** count as Verified bots from 2026-07-01, with a Direct vs Intermediary
  field (host-conditional) [V https://developers.cloudflare.com/bots/concepts/bot/signed-agents/].
- **Google-Agent** is Google's user-triggered agent fetcher, with an IP list and an experimental Web
  Bot Auth identity [V https://developers.google.com/crawling/docs/crawlers-fetchers/google-user-triggered-fetchers].
- **Visa TAP** carries agent signatures on the payment side [V, Visa release above].

Policy options per verified agent: allow browse, allow checkout, require a human step, block. The UA
table is `ai-search-optimizer/references/crawlers.md`.

## Agents that buy on your own site

Amazon **Buy for Me** has an agent check out on the brand's own site; brands "have the choice"
(registry row `amazon-buy-for-me`) [V https://www.aboutamazon.com/news/retail/amazon-shopping-app-buy-for-me-brands].
Decide the policy before it reaches your market: allow, and make checkout agent-safe, or opt out.
