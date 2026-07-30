---
name: ecommerce-cro-experimentation
description: Use when designing, instrumenting, or running conversion experiments on an e-commerce storefront (WooCommerce/WordPress focus) — A/B test design, sample-size and statistical-validity guards, traffic-power eligibility check, GA4 e-commerce event instrumentation via GTM/dataLayer, cache-safe variation delivery that protects INP/LCP and page caching, heatmap/session-replay analysis, QA, rollout, and readout. Trigger on - A/B test, split test, CRO experiment, GA4 ecommerce events, dataLayer setup, test significance, low traffic testing. Reading GA4/GSC/Clarity data lives in seo-data-analyst; persuasion tactics live in conversion-psychology; page-content checklists live in ecommerce-growth.
---

# E-Commerce CRO Experimentation

## Overview

This skill covers **how to run a valid conversion experiment end-to-end** on a WooCommerce/WordPress store — from deciding whether a test can even reach significance, through design, instrumentation, cache-safe delivery, and readout. It is the HOW-to-test layer; the surrounding skills own the other layers.

| Need | Go to |
|------|-------|
| READ GSC/GA4/Clarity data (query, funnels, decay) | `seo-data-analyst` |
| WHY a tactic persuades (biases, trust, price framing) | `conversion-psychology` |
| WHAT to put on each page (page-by-page checklists) | `ecommerce-growth` |
| Woo code + the GA4 event-mapping table + security | `woocommerce-developer` |
| Schema, site architecture, Core Web Vitals thresholds | `seo-structure-architect` |

This skill is a **thin adapter** onto `woocommerce-developer`'s GA4 event-mapping table — it references that table, it never reproduces it.

## Traffic-Power Gate — run this FIRST

Before designing anything, decide whether a classical A/B test can reach significance inside a window your store can hold stable. **Do not default to a fixed-horizon A/B test for a low-volume store.**

**Inputs:** baseline conversion `p`; weekly *eligible units* (unique visitors or accounts — **not** sessions); relative MDE `r` (the smallest lift worth shipping).

**Planning approximation** (equal arms, α = 0.05 two-sided, 80% power):
`n_arm ≈ 15.7 × (1 − p) / (p × r²)`, total ≈ 2 × `n_arm`. Sample grows ~`1/r²` — halving the MDE needs about **4×** the traffic. `weeks ≈ total eligible units ÷ weekly eligible units`.

**Time-to-significance (worked examples):**

| Baseline `p` | Relative MDE `r` | Approx total (both arms) | @ 1k units/wk | @ 5k units/wk |
|---:|---:|---:|---:|---:|
| 2% | 20% (→ 2.4%) | ~42k | ~42 weeks | ~8.4 weeks |
| 2% | 10% (→ 2.2%) | ~161k | ~161 weeks | ~32 weeks |
| 5% | 20% (→ 6.0%) | ~16k | ~16 weeks | ~3.3 weeks |

**Decision branch:**

- **Powered** — horizon fits an 8-12 week window in which traffic mix, implementation, and promotions stay stable → run a classical **fixed-horizon** test (see Experiment Design).
- **Under-powered** — horizon exceeds that window → do **not** run a fixed-horizon A/B. Pick a named fallback:
  1. **Sequential or Bayesian** design (alpha-spending / confidence sequences / mSPRT, or a posterior-loss rule) — the prior, threshold, and stopping rule must be set in advance; neither method manufactures information from thin traffic.
  2. **Test a bigger change / larger MDE**, or switch the primary to a **higher-frequency proximal metric** (add-to-cart rate) with revenue guardrails.
  3. **Pre/post with guardrail metrics** — a weaker causal claim; control for seasonality and confounds.
  4. **Adopt a well-evidenced best practice without testing** (from `ecommerce-growth` / `conversion-psychology`) and monitor guardrails.
  5. **Time-boxed readout — work with the data actually available.** Run for the window the operator
     *has*, then report what that data supports, at the confidence it supports, and state what a
     longer window would add. This is the default when the operator needs a decision now; the others
     are refinements on it.

**Under-powered never means "no answer".** A horizon that does not fit is a statement about
*certainty*, not about *usefulness* — the operator still has to decide something this quarter, and
"come back in 49 months" is not a decision aid. Always deliver the best available read, labelled:

```
DIRECTIONAL (under-powered) — 6 weeks, n≈1,180 units/arm
  observed:     +14% add-to-cart (95% CI −3% to +31%)
  supports:     ship it if the change is cheap and guardrails hold — the downside case is small
  does NOT support: a revenue-per-visitor claim, or attributing a specific lift figure
  a further 10 weeks would: narrow the CI to roughly ±8% and separate +14% from zero
```

State the direction, the interval, what it does and does not license, and the cost of more
certainty. Then let the operator choose. An honest wide interval is worth more than silence, and far
more than a confident number the data cannot carry.

**Still never run a classical fixed-horizon test whose computed horizon exceeds ~8-12 weeks** — the
store will have changed underneath it before it concludes. That is a constraint on the *test design*,
not permission to withhold the analysis.

## Hypothesis Framing

- **Evidence sources:** heatmaps and session replays (Clarity — rage/dead clicks, scroll depth), funnel drop-offs (GA4 — see `seo-data-analyst` recipes), reviews and support tickets.
- **Template:** *Observation → Change → Predicted effect → Metric.* e.g. "Users rage-click the spec tabs (obs) → surface key specs as bullets above the fold (change) → add-to-cart rate rises (predicted) → `add_to_cart / view_item` (metric)."
- **Prioritize** with ICE (Impact, Confidence, Ease) or PIE (Potential, Importance, Ease). One hypothesis per test.

## Experiment Design

- **One primary metric + guardrails.** Predefine guardrails: revenue/visitor, AOV, margin, refunds/cancellations, checkout errors, payment success rate, and Core Web Vitals.
- **Sample size** comes from the Traffic-Power Gate. Pre-register MDE, α, power, duration, and the primary metric before launch.
- **Conventions:** two-sided **α = 0.05** (95%), **80% power** (β = 0.20); use 90% power or a stricter α when a wrong decision is expensive.
- **Anti-peeking:** a fixed-horizon test is read **once**, at the planned horizon. To look early or stop early you **must** use a sequential design — repeatedly stopping when `p < .05` inflates the Type-I error rate. Watching for operational breakage is fine; making the *efficacy* call early is not.
- **Duration:** run whole weeks / whole business cycles; never stop mid-week. Cover weekday + weekend, paydays, and promo cycles.
- **Discipline:** one change per variant (or a deliberate factorial design). Check **sample-ratio mismatch (SRM)**. Randomize on visitor/account, never session. Avoid post-hoc segmentation (it is a multiple-comparisons trap).

## Instrumentation — GA4 via GTM/dataLayer on Woo

`woocommerce-developer` §Analytics Integration owns the **Woo-action → GA4-event mapping table** — use it; do not copy it here. This section adds the *procedure* around it:

- **One data contract:** stable `item_id`, numeric price/quantity, currency, and a unique `transaction_id`; decide the randomization/analysis unit (visitor / account / session) up front.
- **Push, don't scrape.** Initialize `window.dataLayer` before the GTM container. Push atomic objects carrying the exact event name plus its `ecommerce` object — never read values from rendered HTML. Clear the previous `ecommerce` object before each push (GTM's data model persists).
- **Fire at the real state transition.** For AJAX/block carts, push **after** WooCommerce confirms success, not on the click.
- **Purchase from truth.** Emit `purchase` from the authoritative completed-order state; send refunds against the original `transaction_id`. Stamp `experiment_id` + variant onto **both** exposure and outcome events so arms can be analyzed independently.
- **QA:** GTM Preview / Tag Assistant (push order, consent state, fired vs blocked tags, outgoing hits) → then GA4 **DebugView** for event- and item-level parameters.
- **De-duplicate at source:** use GTM *or* direct `gtag.js`, not both; bind each interaction once; guard confirmation-page refreshes; keep `transaction_id`s unique. GA4 ignores a repeated `transaction_id`, but ordinary funnel events have **no** equivalent auto-dedup.
- **Consent Mode v2:** set denied-by-default consent (`ad_storage`, `analytics_storage`, `ad_user_data`, `ad_personalization`) before other tags — normally a CMP template on GTM's Consent Initialization trigger — then update after the visitor's choice. EEA advertising enforcement began **early March 2024**. Consent Mode signals a choice; it is not a CMP and not legal advice.
- **Express wallets bypass the funnel — segment before you read it.** Apple Pay / Google Pay / Shop Pay / PayPal express purchases launched from the PDP or cart **never fire `begin_checkout`**, and wallets are ~65% of mobile conversions. Before running any checkout experiment: confirm `checkout_type` (`classic` \| `express_wallet`) is stamped on checkout and purchase events, and **analyse the two funnels separately**. A blended checkout-completion rate on a wallet-enabled store is wrong for most mobile orders, and it will make a checkout-page variant look like it moved a metric it never touched. Implementation detail: `woocommerce-developer` §Analytics Integration.
- **Qualitative layer:** Clarity/heatmaps explain the WHY behind a win or a flat result — see `seo-data-analyst`.

## Cache-Safe Variation Delivery

Three delivery models on a cached WordPress site — pick per the change and the store's caching stack:

| Model | How it works | Main risk |
|-------|--------------|-----------|
| **Client-side (C)** | One cacheable control document for everyone; JS assigns the bucket and mutates the DOM | Flicker + added INP/LCP cost |
| **Server / PHP (S)** | Cookie-selected response rendered server-side | Cache-key leakage (see below) |
| **Edge (E)** | Assign at the CDN before cache lookup, rewrite to a bucket path or vary the cache key | Cache-cardinality blow-up if misused |

- **Server-side is safe only if the full-page cache key also varies on a small-valued experiment cookie.** Without that vary, the first cached A *or* B response is served to everyone.
- **Edge:** assign before the cache lookup, store a stable first-party A/B cookie, and rewrite to `/control/...` | `/test/...` or add the bucket to the cache key. Keep cardinality to A/B — never a user ID — and never cache a personalized `Set-Cookie` object as the shared page.
- **Anti-flicker vs performance:** hiding content until assignment cuts the control-to-variant flash and CLS but adds a blank interval and can worsen LCP; a synchronous snippet cuts flicker but delays parsing; async/defer isolates failure but risks flash. Always use a short **fail-open timeout**. Measure RUM + Web Vitals **by arm** (include the variant's own images/fonts/layout). CWV thresholds live in `seo-structure-architect`.
- **WooCommerce cache specifics:** `DONOTCACHEPAGE=true` bypasses the page cache (runs PHP → no variant leakage) but forfeits cache performance and does **not** control an upstream CDN/host cache. **WP Rocket** auto-uncaches Cart/Checkout/My-Account/Woo-REST while still caching product/category/home — "Never Cache Cookies" bypasses caching, it does not create one cached object per variant. **LiteSpeed Cache (LSCache 6.0+)** "Vary Cookies" *can* create per-variant cached objects and propagate the vary to QUIC.cloud (never vary on a unique visitor ID). Purge WP + host + CDN caches on every test start/stop/change, and exclude the experiment loader from JS combine/defer/delay unless the vendor supports it.

**2026 tool landscape** (Google Optimize sunset **30 Sep 2023**): WP-native / Woo-aware options include **Nelio A/B Testing** (v8.x, Woo product/order goals), **Convert** (WP plugin + Woo revenue), **VWO** (official WP plugin tracks Woo events), and **Thrive Optimize** (landing pages). Developer/full-stack + edge options include **GrowthBook** (PHP + Cloudflare/Fastly/Lambda@Edge SDKs), **Optimizely**, **AB Tasty/Flagship**, **Statsig**, **PostHog**, and **Harness FME** (formerly Split). Generic client-side tools install easily via `<head>`/GTM, but Woo-event measurement is a separate integration.

## QA, Rollout & Readout

**Pre-launch QA checklist:**
- Both arms render correctly on mobile + desktop, logged-in + guest, with caches warm.
- Instrumentation fires once per interaction in both arms (confirm in DebugView); SRM check is green; guardrails are wired.
- Consent state is correct; no console errors; the fail-open timeout works.

**Ramp:** start at a small traffic share to catch breakage, then move to full allocation and keep it fixed.

**Readout decision rules** (only after the pre-registered horizon or sequential boundary):
- **Ship** — primary metric wins with significance **and** no guardrail regressed.
- **Iterate** — flat/ambiguous but directional and cheap to refine.
- **Kill** — it loses or breaks a guardrail. A flat result is a valid, informative outcome, not a failure.

**Log every experiment** (hypothesis, dates, allocation, primary + guardrail results, decision). The log is your institutional memory and prevents re-running settled questions.

## Ethics Guardrails

- **No dark-pattern variants:** fake scarcity/urgency, confirm-shaming, hidden costs, or pre-ticked add-ons are out of bounds even if they "win". See `conversion-psychology` ethical-urgency rules; back urgency/social-proof with real data (the UK CMA actively investigates fake urgency).
- Do not test consent flows into non-compliance, and keep **accessibility parity** across arms.

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Default to a fixed-horizon A/B on a low-traffic store | Horizon exceeds the stable window — use the Traffic-Power Gate fallbacks |
| Peek and stop at the first `p < .05` | Inflates Type-I error; use a sequential design to stop early |
| Change more than one thing per variant | You cannot attribute the result |
| Ship a render-blocking A/B snippet with no timeout | Tanks LCP/INP and is a single point of failure |
| Serve a cookie-selected variant without varying the cache key | The first cached A or B leaks to every visitor |
| Reproduce the GA4 event-mapping table here | It lives in `woocommerce-developer` — reference it |
| Stop mid-week or mid-promo | Day-of-week and promo effects bias the result |
| Randomize on session | Splits one visitor across arms; observations aren't independent |
| Decide on a segment discovered after the fact | Multiple comparisons manufacture false positives |
