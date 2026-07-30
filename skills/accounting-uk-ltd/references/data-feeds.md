# Data feeds — getting every source into the books

<!-- REVIEW-BY: 2027-01-31 -->
**REVIEW-BY: 2027-01-31** · researched 2026-07-29. Access gates and pricing move; re-verify before
committing to a route.

The routes for each feed a small VAT-registered Ltd needs, and — more usefully — **which gate stands
in front of each one**. Nearly every route has an approval, a licence or a plan tier behind it, and
knowing which is a two-minute question versus a six-week one decides the build order.

## The gate map — read this first

| Feed | Route | Gate | Effort |
|---|---|---|---|
| **QuickBooks** | Intuit first-party MCP | App assessment (status ~immediate) | see `quickbooks-api` |
| **Bank** | Open Banking via an aggregator | **Aggregator's FCA licence — not your own** | Low–medium |
| **Email invoices** | Gmail API | Google Cloud project + OAuth consent | Low |
| **WooCommerce** | REST API keys | **Self-service in wp-admin** | **Lowest** |
| **PayPal** | REST API or CSV export | Developer app | Low |
| **Worldpay** | API or portal export | Merchant account + API creds | Medium |
| **Klarna** | Merchant portal / API | Merchant credentials | Medium |

**Start with WooCommerce.** It is the only one with no external approval, and for a webstore it is
usually the largest single source of transactions.

## Banking — Open Banking, and the licence question

**You do not need your own AISP authorisation.** An Account Information Service Provider needs FCA
permission for read-only access to bank transaction data — but **aggregators let you operate under
their licence**, which is the normal route and removes the regulatory gate entirely.

UK providers: **GoCardless Bank Account Data** (the former Nordigen — historically the
cost-effective option for account data), **TrueLayer** (UK/EU specialist), **Yapily** (infrastructure
only, white-label), **Tink** (Visa-owned), **Plaid**, **Moneyhub**, **Salt Edge** (multi-region).

Things that decide the choice for a single small company:

- **Cost at one-company scale.** Same trap as the accounting aggregators in `quickbooks-api` §2:
  platforms priced for fintechs connecting thousands of users are poor value for one set of books.
  Check whether a free or low tier covers a handful of accounts.
- **Consent expiry.** Open Banking access consent typically lapses after a bounded period (commonly
  ~90 days) and needs re-authorisation. **Put it in the tracker** — a bank feed that silently stops
  is discovered at a VAT deadline.
- **Coverage of your actual bank**, including business accounts, which sometimes lag personal ones.
- **Read-only is what you want.** AIS (account information), not PIS (payment initiation). Nothing
  here should be able to move money.

**Fallback that always works: CSV export from online banking.** Slower, no gate, and
`financial-document-ingestion` prefers it over a PDF anyway. Do not block the build waiting for API
access.

## Email invoices — Gmail API

Purchase invoices arrive as email attachments; this is how they get captured instead of being
re-typed.

- **Route:** Google Cloud project → enable Gmail API → OAuth 2.0 → `gmail.readonly` scope.
- **Scope discipline:** `gmail.readonly` is enough to find and download attachments. Do not request
  send or modify permissions the workflow does not need.
- **Consent screen:** an internal/testing app is fine for one operator; external use needs
  verification.
- **Practical pattern:** a dedicated label or filter (e.g. `invoices/`) applied by a Gmail filter,
  then fetch only that label. Far more reliable than searching the whole mailbox heuristically.
- **The attachment is the evidence.** Store the original PDF and hash it (§ document store) —
  the email body is not a VAT invoice.

Full auth model, scope choice, pagination and token lifecycle: **`google-workspace-python`**. The
trap it exists to stop — a service account **cannot** read a personal Gmail mailbox without Workspace
domain-wide delegation, so OAuth user credentials are the correct route here, not a compromise.

An MCP Gmail connector may already be available in this environment; check before building a client.

## WooCommerce — start here

- **Route:** WooCommerce → Settings → Advanced → REST API → generate a **read-only** key pair.
  No approval, no review.
- **Auth:** consumer key/secret over HTTPS.
- **What to pull:** orders (with line items, tax lines and refunds), not just totals.
- **The trap that misstates VAT and turnover:** pull **gross order data plus fees**, never the net
  payout. Posting only what the processor deposited understates turnover *and* costs simultaneously —
  see `bookkeeping-double-entry` §5 and `financial-document-ingestion` §6.
- **Refunds are negative income**, not an expense. Capture them as refunds.
- `woocommerce-developer` covers the API surface in depth.

## Payment providers

The pattern is the same for all three, and it is the single most important thing on this page:

> **A payment processor's payout is not a sale.** One payout is many orders, minus fees, sometimes
> minus refunds and chargebacks, and it usually straddles a period boundary. It reconciles a
> **clearing account** — it is never the revenue entry.

| Provider | API | Export fallback |
|---|---|---|
| **PayPal** | REST API (developer app, sandbox available); Transaction Search API for settlement detail | CSV from the merchant dashboard |
| **Worldpay** | Merchant API — needs a merchant account and issued credentials | Portal statement/settlement export |
| **Klarna** | Merchant API / settlements endpoint | Merchant portal settlement reports |

For all three, what you actually need is the **settlement report**: gross, fees, refunds, net, and the
transaction ids that tie back to orders. The bank line alone tells you the net and nothing else.

**Manual export is a legitimate v1.** A monthly CSV download that is *correctly posted* beats an API
integration that is postponed. Automate the highest-volume source first.

## Recommended build order

1. **WooCommerce** — no gate, highest volume
2. **Bank CSV export** — no gate, proves the reconciliation loop end to end
3. **Gmail** — low gate, removes manual invoice entry
4. **Payment settlements** — manual export first, API once the posting pattern is proven
5. **Open Banking** — replaces step 2 when the aggregator is chosen
6. **QuickBooks** — in parallel from day one, since its assessment is the only external dependency

Each step should reconcile before the next is added. A feed that lands data nobody has proved is
worse than no feed: it looks like coverage.

**"Proven" now has a command.** Step 4 says *manual export first, API once the posting pattern is
proven* — this is how you prove it, and it needs no credentials and no API:

```bash
S=~/.claude/skills/financial-document-ingestion/scripts/settlement_reconcile.py
python3 $S --settlement paypal-2026-07.csv check \
    --orders woo-orders-2026-07.csv --payout 4103.22 \
    --period-start 2026-07-01 --period-end 2026-07-31
python3 $S --settlement paypal-2026-07.csv postings     # the clearing-account journal shape
```

It proves `sum(orders) − fees − refunds == payout` to the penny, names the orders that disagree,
the settlement lines with no order, and the ones **ordered in a different period from the one they
were paid out in** — which is the VAT trap, because the tax point is the supply and not the
settlement. **Run it against one month of a manual export before automating anything.** If a hand
-downloaded CSV does not reconcile, an API delivering the same data faster will not either.

## Sources

- [What AISP and PISP mean](https://truelayer.com/blog/product/what-does-aisp-pisp-mean/) ·
  [UK Open Banking regulation](https://truelayer.com/openbanking/open-banking-regulation-in-the-uk)
- [UK Open Banking API providers compared](https://openbankingtracker.com/open-banking-apis-uk)
- [Gmail API](https://developers.google.com/gmail/api/guides) ·
  [WooCommerce REST API](https://woocommerce.github.io/woocommerce-rest-api-docs/)
