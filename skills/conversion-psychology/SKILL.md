---
name: conversion-psychology
description: Use when writing copy, designing CTAs, framing prices, adding trust signals, or reviewing any customer-facing page for persuasion effectiveness. Covers buying psychology, cognitive biases, and ethical urgency for e-commerce.
---

# Conversion Psychology

## Overview

People buy on emotion and justify with logic. This skill covers **WHY** people buy — the psychological principles, cognitive biases, and emotional triggers that turn browsers into buyers. It does NOT cover what to build (see `ecommerce-growth`) or how AI finds you (see `ai-search-optimizer`).

## Cognitive Load Budget

**Max 3-4 persuasion elements per page section.** Applying every principle at once creates an infomercial. Pick the highest-impact tactics for each context.

## Top 5 Essentials (If You Do Nothing Else)

1. **Show social proof above the fold** — reviews, star rating, or customer count
2. **Frame price with monthly payment** — "From £34/mo with Klarna" next to full price
3. **One clear CTA per section** — competing actions cause decision paralysis
4. **Address the #1 fear on the page** — spec confusion on product pages, security at checkout
5. **Real urgency only** — stock levels from WooCommerce, genuine sale end dates

---

## Cialdini's 7 Principles

| Principle | E-commerce Application |
|-----------|----------------------|
| **Reciprocity** | Give first: free buying guide, spec-check tool, benchmark data |
| **Commitment** | Small yeses lead to big yeses: quiz → recommendation → add to cart |
| **Social Proof** | Reviews, star ratings, "Most Popular" badges, Trustpilot widget |
| **Authority** | Partner logos (Intel/NVIDIA/AMD), benchmark scores, "Est. 2020" |
| **Liking** | Local identity ("Built in Rotherham"), gaming culture tone, founder story |
| **Scarcity** | Real stock levels, genuine seasonal sales, limited GPU allocations |
| **Unity** | Shared identity: "South Yorkshire gamers", community language |

---

## Cognitive Biases

### Anchoring
First number seen becomes the reference. Show higher price first.
- ~~£1,299~~ **£1,099** (crossed-out anchor)
- "Components worth £1,450 separately — yours for £1,099"

### Loss Aversion
Pain of losing is 2x stronger than pleasure of gaining.
- "Your saved build expires in 48 hours"
- "Without 32GB RAM, expect stuttering in Cyberpunk 2077"

### Decoy Effect
If 3+ products exist in a category, position the target as best value:
- **Value** £699 — functional | **Most Popular** £999 — best value (highlighted) | **Premium** £1,499 — aspirational anchor

### Choice Overload
Max 3-5 options per category. Use quiz to narrow. Default selections in configurators.

### Bandwagon Effect
"Most Popular" badges, real purchase counts from WooCommerce order data. Never use fabricated numbers.

---

## Trust Architecture (4 Layers)

| Layer | Elements |
|-------|----------|
| **Authority** | Partner logos, certifications, years in business |
| **Evidence** | Trustpilot widget, Google reviews, customer photos, benchmarks |
| **Assurance** | 2-year warranty, 14-day returns, lifetime tech support |
| **Transparency** | Physical address in footer, phone in header, build process photos |

**Key insight**: Mixed ratings (4.2-4.7) convert better than perfect 5.0 — they appear authentic. Respond professionally to negative reviews.

---

## Purchase Anxiety (£500-£1,500 PCs)

| Fear | On-Page Solution |
|------|-----------------|
| "Is this the right spec?" | "Plays Fortnite at 144fps on High" — translate specs to performance |
| "Will it work?" | "Every PC tested 24 hours before shipping" |
| "What if it breaks?" | Warranty + support info on every product page, not hidden in FAQ |
| "Is this site legit?" | Trustpilot, address, phone number, SSL badge |
| "Can I afford it?" | Klarna monthly framing prominent next to full price |
| "Am I getting ripped off?" | Component-level value breakdown |
| "Will it arrive safely?" | "Foam-packed in custom PC packaging", delivery tracking |

---

## Price Psychology

| Tactic | Example |
|--------|---------|
| **Charm pricing** | £999 not £1,000 (left-digit effect) |
| **Monthly framing** | "From £34/mo" prominent, full price secondary |
| **Anchor pricing** | ~~£1,299~~ **£1,099** |
| **Component value** | "Parts worth £1,450 separately" |
| **Bundle pricing** | "PC + Monitor: Save £150" |
| **Free shipping threshold** | Set 15-25% above AOV to drive add-ons |

---

## Ethical Urgency

| Ethical | Dark Pattern (Never Do) |
|---------|------------------------|
| Real stock from WooCommerce inventory | Hard-coded "Only 2 left!" |
| Genuine sale with real end date | Countdown timer that resets on refresh |
| Real viewer count (if tracked) | Fabricated "4 people viewing" |
| Limited GPU allocation (genuine) | Perpetual "SALE" that never ends |

**UK CMA actively investigates fake urgency. If not backed by real data, don't show it.**

---

## Quick Reference by Page

### Product Page (max 4 persuasion elements above fold)
- Price with anchor + monthly framing
- Star rating + review count
- "Most Popular" / "Best Value" badge if applicable
- Stock level (only when genuinely < 10)

### Checkout (trust-focused, not sales-focused)
- Trust badges near payment form (SSL, payment logos)
- Return policy reminder
- "Rated Excellent on Trustpilot" badge
- Order summary always visible

### Quiz Results
- "Your Perfect Gaming PC" language (endowment/ownership)
- Performance framing: "Runs Fortnite at High, 144fps"
- One clear recommendation with alternatives secondary

---

## Anti-Patterns

| Don't | Do Instead |
|-------|-----------|
| Fake countdown timers | Real sale dates with genuine end times |
| "Only 1 left!" when it's not true | Real WooCommerce inventory data |
| Popup immediately on page load | Exit-intent after 30+ seconds |
| Hiding shipping costs until checkout | Show delivery cost on product page |
| Perfect 5.0 star ratings | Allow and respond to negative reviews |
| "Buy Now" on £1,000+ items | "Add to Cart" — softer first step |
| Applying every principle at once | Pick 3-4 per section (cognitive load budget) |

---

## Red Flags for Review

1. No social proof visible above the fold
2. Raw price with no framing (anchor, monthly, or value comparison)
3. Fake or inflated metrics (regulatory risk + trust destruction)
4. Multiple competing CTAs of equal visual weight
5. No contact information visible (phone, address)
