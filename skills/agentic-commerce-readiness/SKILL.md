---
name: agentic-commerce-readiness
description: Use when evaluating or implementing support for AI agents that transact on a store's behalf — the Agentic Commerce Protocol (ACP), Agent Payments Protocol (AP2), agent-readable product feeds, delegated payment, and deciding whether to invest at all. Covers the standards layer, merchant-side integration, the buy-vs-wait decision, and how agent transaction differs from AI-search discovery. Trigger on - agentic commerce, ACP, AP2, AI agent checkout, agent payments, sell through AI agents, ChatGPT checkout, Stripe Agentic Commerce Suite, agent-readable storefront.
---

# Agentic Commerce Readiness

## Overview

Two different things get called "AI commerce" and conflating them wastes money:

| | **Discovery** | **Transaction** |
|---|---|---|
| What happens | An AI recommends you; the buyer lands on **your** site and checks out normally | An AI agent completes the purchase **without** the buyer visiting your site |
| Owned by | `ai-search-optimizer` | **this skill** |
| Maturity 2026 | Proven, measurable, revenue today | Standards ratified, real adoption thin |
| Investment case | Strong for considered purchases | **Conditional — read §3 before building** |

> **Boundary:** getting cited/recommended by AI → `ai-search-optimizer`. Getting *transacted with*
> by an agent → here. Payment gateway plumbing → `woocommerce-developer`.

---

## 1. The strategic read — the product failed, the protocol standardised

This distinction is the single most common error in 2026 agentic-commerce advice, in both directions.

**What failed:** OpenAI's **ChatGPT Instant Checkout** shut down **March 2026**, ~5 months after
launch. Roughly **12 merchants** ever went live. Users browsed heavily and did not buy. OpenAI
repositioned ChatGPT as a discovery surface and moved toward dedicated retailer **apps**.

**What did not fail — note the dates, all *after* the shutdown:**

| Standard | What it does | Status |
|---|---|---|
| **ACP** — Agentic Commerce Protocol | Commerce/checkout layer: product feeds, checkout, delegated payment | Stable spec **2026-04-17**. Founding maintainers **OpenAI + Stripe**, consensus governance, stated path to a neutral foundation. Adds **MCP** support |
| **AP2** — Agent Payments Protocol | Payment-*consent* layer: cryptographically proves a real user authorised a specific purchase | Google published v0.2, **donated to the FIDO Alliance 2026-04-28**. 60 contributing orgs incl. Mastercard, Amex, PayPal, Adyen, Worldpay, Etsy, Revolut, Salesforce |

**ACP and AP2 are complementary layers, not rivals.** A full agentic purchase uses both: the agent
checks out via ACP and proves authorisation via AP2. Anyone presenting them as competitors has not
read either spec.

Two FIDO working groups now carry this: **Agentic Authentication** (chaired by CVS Health, Google,
OpenAI) and **Payments** (chaired by Mastercard and Visa).

**The honest conclusion:** the *consumer surface* died and the *infrastructure* consolidated into
standards bodies backed by the card networks. That is what an emerging standard normally looks like
after its first product flops — it is neither hype nor a corpse.

---

## 2. What a merchant actually implements

ACP defines a standard API surface so any AI platform can interface with any merchant. Three parts:

| Part | Purpose |
|---|---|
| **Product feed** | Agent-readable catalogue — title, price, availability, attributes |
| **Checkout** | Endpoints an agent calls to build and complete a cart |
| **Delegated payment** | Passes payment credentials from buyer → agent → you **without exposing the underlying credential** |

**Integration is REST *or* MCP** — no mandated stack, works with existing commerce backends and PSPs.

### The realistic path for most stores: through your platform, not by hand

Do **not** hand-roll ACP endpoints. **Stripe's Agentic Commerce Suite** (shipped 2025-12-11) wraps
all three parts behind one integration, built on the Checkout Sessions API, with a hosted ACP
product endpoint that syndicates your catalogue (CSV, API, or SFTP upload).

**WooCommerce is a named rollout platform**, alongside Wix, BigCommerce, Squarespace, and
commercetools. **For a Woo store the correct first action is to check whether your platform/PSP
already offers this, not to write protocol code.**

### What you keep

You remain **merchant of record**. You keep the customer relationship, decide **which products
agents may sell**, own refunds and disputes, and can accept or decline **per agent, per transaction,
or on custom logic**. Agent traffic you cannot govern is a reason to configure the policy — not a
reason to stay out.

---

## 3. Should you invest? — decide before you build

Agent *discovery* pays now. Agent *transaction* is a bet on adoption. Grade honestly:

| Signal | Points |
|---|---|
| Your PSP/platform already ships ACP support (Stripe + Woo/BigCommerce/Wix…) | **+3** — cost collapses to configuration |
| AI-attributed revenue is already material (>5% of revenue) | **+2** |
| Catalogue is standardised, in stock, with clean attributes | **+2** |
| Commodity / repeat / low-consideration products | **+2** |
| High-AOV considered purchase with long research cycle | **−2** — buyers want to *see* it; they use AI to research, then buy on your site |
| Configurable / custom-built / made-to-order products | **−3** — agents transact SKUs, not configurators |
| Feed hygiene is poor (see §4) | **−3** — fix that first regardless |

**≥5 — configure it** via your platform. Low cost, real option value.
**0–4 — prepare, don't build.** Do §4; revisit when your PSP ships it.
**<0 — skip transaction, invest in discovery.** Say so explicitly and move budget to
`ai-search-optimizer`.

> **Worked example — a custom-PC builder at £1,769 AOV.** Configurable builds (−3), high-consideration
> (−2), but ~20% AI-attributed revenue (+2) and Woo+Stripe on the rollout list (+3) = **0**. Verdict:
> **prepare, don't build.** The feed work in §4 is the whole return; agentic *checkout* for a
> configurator is a category error, because there is no fixed SKU for an agent to buy.

---

## 4. Feed hygiene — do this regardless of the §3 verdict

**This is the part that pays either way**, because the same clean feed serves AI discovery,
Merchant Center, and any future agent. If you do nothing else from this skill, do this.

- **Stable identifiers.** Real GTIN/MPN. For custom/assembled goods use `mpn` with your own SKU
  system and set `identifier_exists: false`.
- **Truthful availability and price.** Agents transact against the feed. A stale price is a declined
  or disputed order, not a lost impression.
- **Attributes that survive machine reading** — consistent units, consistent vocabulary.
- **Schema ↔ feed consistency.** On-page structured data must agree with the feed. Divergence is a
  silent penalty (see `ai-search-optimizer`, `seo-structure-architect`).
- **Variants modelled properly** (`ProductGroup`) so variants do not compete with each other.
- **No category-defining attribute missing or wrong.** A "Gaming PC" whose `gpu` attribute reads
  `None or IGPU` is not a data-entry slip — it is the feed telling an agent to sell the wrong thing.

---

## 5. `llms.txt` — ship it, expect nothing from rankings

A `/llms.txt` file (markdown, root) points agents at your canonical pages.

**Honest position:** it is **not** a ranking factor, **no** major search engine has committed to
consuming it, and it will not get you cited. It costs ~15 minutes and helps agents that *do* read it
resolve your site structure. **Ship it as agent ergonomics; anyone selling it as an SEO tactic is
selling hype.**

---

## 6. Anti-Patterns

| Don't | Why it hurts |
|-------|-------------|
| Conclude "agentic commerce is dead" from Instant Checkout | Confuses one consumer product with the standards layer — ACP stabilised **after** the shutdown |
| Conclude it is inevitable and rebuild your checkout for it | ~12 merchants ever ran the flagship product. Adoption is a bet, not a fact |
| Hand-roll ACP endpoints | Your PSP/platform is shipping this. You would maintain protocol code for a moving spec |
| Build agentic checkout for configurable/custom products | Agents transact SKUs. A configurator has no SKU to buy |
| Treat ACP and AP2 as competitors, pick one | Different layers — a full purchase uses both |
| Expose real payment credentials to an agent | The delegated-payment flow exists precisely to avoid this |
| Open the catalogue to all agents by default | You can govern per agent/transaction — decide policy deliberately |
| Invest here while feed hygiene is broken | Every agent reads the feed. Garbage in, declined orders out |
| Judge the channel on session volume | Agent transactions may produce **no session at all** — instrument order-side |
| Sell `llms.txt` as an SEO win | It is not a ranking factor |

---

## 7. Deprecated — Do NOT Implement

*This surface moves fast. Check before acting; add a row the moment something dies.*

| Thing | Status | Instead |
|---|---|---|
| **ChatGPT Instant Checkout** | Shut down **Mar 2026** | Discovery via `ai-search-optimizer`; watch OpenAI's retailer **apps** |
| Bespoke per-platform agent checkout integrations | Superseded by ACP | One ACP integration via your PSP |
| Treating AP2 as Google-proprietary | Donated to **FIDO Alliance 2026-04-28** | Track FIDO's Agentic Authentication + Payments working groups |

---

## Sources

Primary sources only — this area is thick with vendor speculation.

- ACP spec + governance — `github.com/agentic-commerce-protocol/agentic-commerce-protocol`, `agenticcommerce.dev`
- AP2 donation, v0.2, 60-org list, FIDO working groups — FIDO Alliance; Google blog, 2026-04-28
- Stripe Agentic Commerce Suite, platform rollout list — Stripe docs + newsroom
- Instant Checkout shutdown, merchant count — CNBC (2026-03-20), Forbes (2026-03-10)
