---
name: business-edge
description: Use when a business needs end-to-end analysis and a strategy, not a single-domain fix — "how do we grow", "audit my business", "why aren't we selling", "what should we do next", "review our website and marketing", "find our gaps". Runs a phased engagement — scope, scan, diagnose, position, plan, dispatch, measure — that analyses a business across all dimensions, proposes strategy, produces a costed action list, and routes each action to the right specialist skill (SEO, UX, web design, CRO, content, lifecycle, platform). Works for any business, product, brand or person. Designed for operators who cannot outspend incumbents, so it prefers asymmetric methods over commodity best-practice.
---

# Business Edge

The analyst-and-mentor layer. It **diagnoses a business, decides what matters, and hands specific
work to specialists.** It does not do the specialist work itself.

> **Boundary.** This skill produces *analysis, strategy and a dispatched action list*. The actual
> changes are made by the specialist skills in §6 and executed by `bob`. If you find yourself
> writing schema markup or CSS here, you have left your lane.

<HARD-RULE>
NEVER report absence from a failed probe. Every finding carries a probe status
(`FOUND / SEARCHED_NOT_FOUND / BLOCKED / CAPTCHA / FAILED / NOT_PROBED`). A blocked or failed
search is NOT evidence of absence, and a report containing any BLOCKED/FAILED/CAPTCHA must say so
on its face. This rule exists because a consumer search API once returned "no presence found" for a
brand whose entire AI reputation was built on the threads it failed to retrieve.
</HARD-RULE>

<HARD-RULE>
CAPTURE THE PROFIT MODEL BEFORE ANY OTHER ANALYSIS (P0). Revenue-denominated advice is actively
harmful under some fee structures. A business earning a FIXED FEE PER UNIT gains nothing from AOV
lifts or premium positioning — a £3,000 sale earns the same as a £1,200 one. Never recommend an
AOV, premium-mix or "recover £X of lost revenue" action until §2.1 is answered in PROFIT terms.
</HARD-RULE>

<HARD-RULE>
NO METHOD IS PROMOTED FROM n=1. Every proposed action carries an evidence grade
(`conjecture / single-entity signal / replicated / cross-category`). Conjectures may be TESTED but
never presented as best practice. Prefer the cheapest experiment that could falsify a conjecture
over any amount of further deliberation.
</HARD-RULE>

---

## 1. The engagement

```
P0 SCOPE ─► P1 SCAN ─► P2 DIAGNOSE ─► P3 POSITION ─► P4 PLAN ─► P5 DISPATCH ─► P6 MEASURE ─► P7 LEDGER
```

Each phase has a required output. **Do not skip forward** — P3 without P2 produces generic advice,
which is the failure this skill exists to prevent.

Roles are **data**, not skills: `roster/*.yaml`. Load the relevant role's card when working its
phase. Seven roles, zero additional SKILL.md files.

---

## 2. P0 — SCOPE

Establish what the business is and how it makes money. **Fifteen minutes here prevents a whole
engagement of wrong-denominated advice.**

### 2.1 The profit model — ask before anything else

| Question | Why it changes everything |
|---|---|
| **How is profit earned per sale?** % margin · **fixed fee per unit** · subscription · blended | A fixed fee **detaches profit from price** — AOV becomes a vanity metric and premium-mix advice becomes worthless |
| Gross profit per order, in currency | The only number that prices any proposed action |
| Channel fee load (marketplace %, payment %, financing %) | A 12.8% marketplace fee on a high-ticket item can **exceed** a fixed per-unit profit — making those sales value-destroying |
| Orders per month | Decides whether experiments are statistically possible at all (§7.1) |
| Category paid CAC (estimate is fine) | **Affordability ratio = GP-per-order ÷ CAC.** Below ~1.5 the paid auction is foreclosed and non-auction distribution is the *only* distribution |

Record every figure as measured / operator-stated / estimated. **State assumptions inline and flag
the most load-bearing one.**

**Flagging an assumption does not license concluding from it (S074).** Before stating any
directional recommendation, re-run it at the plausible range of every *assumed* input. **If the
direction flips anywhere in that range, you do not have a recommendation — you have an open
question, and it must be reported as one.**

This is not hypothetical. A real engagement assumed a 15% gross margin, correctly flagged it as the
single most load-bearing assumption, and still concluded *"paid advertising is arithmetically
foreclosed"* — a conclusion that **reverses at 25%**. The assumption was labelled and the
conclusion was stated anyway, which is how a flag becomes decoration.

    UNGROUNDED — direction depends on an assumed input
      claim:      paid acquisition is foreclosed
      hinges on:  gross margin (ASSUMED 15%, never measured)
      flips at:   ~20%
      to resolve: one COGS figure from the operator

Report it in that shape. `UNGROUNDED` is a first-class outcome, never a weaker `PASS`: it names the
one number that would settle the question, which is far more useful to an operator than a confident
answer derived from a guess. Only an input recorded as **measured** can carry a directional claim on
its own.

### 2.2 Also capture
Goal and time horizon · constraints (budget, operator hours/week, technical capability) · what has
already been tried · the competitor set · what the operator believes is true (to be tested, not
assumed).

---

## 3. P1 — SCAN (all dimensions, no false negatives)

**Spawn the `scout` agent** for the off-site half — it owns surface intelligence and enforces the
probe rules. Browser-first; APIs are a fallback, never the sole source. Record probe status on every
probe via `scripts/probe_ledger.py`, and run `probe_ledger.py coverage` before writing any finding.
Full method: [`references/probe-protocol.md`](references/probe-protocol.md).

> `scout` reports what exists and what could not be seen. **It does not diagnose or recommend** —
> it hands the surface map back here, where P2 owns diagnosis.

**Dimensions — sweep all, mark `NOT_PROBED` explicitly where skipped:**

| | Dimension | Look for |
|---|---|---|
| 1 | Offer & positioning | What is sold, to whom, at what price, vs whom |
| 2 | Catalogue integrity | Wrong/missing category-defining attributes, unclear variants, comparability |
| 3 | Pricing & fee load | §2.1 |
| 4 | **Discovery** | Organic, AI answers (ChatGPT/Gemini/Perplexity/Copilot/AIO), communities, marketplaces, social, referral |
| 5 | **Selection** | Comparison support, spec clarity, configurator, **the verification path** (§5.3) |
| 6 | **Purchase** | Checkout, payment methods, wallets, financing, failure/decline rates |
| 7 | **After-sales** | Delivery, support, warranty, returns, review capture, repeat/referral |
| 8 | Content & presence | What exists, what gets read, what gets cited |
| 9 | Brand/entity footprint | Third-party corroboration, review platforms, marketplace history |
| 10 | Technical site health | Speed, mobile, crawlability, structured data |
| 11 | Measurement | Attribution coverage, unattributed share, instrumentation gaps |
| 12 | Compliance | Regulatory exposure for the category |

**Also scan what AI says about the business.** Ask the major assistants the buying questions a real
customer would, and record the answer *and its cited sources*. The AI's brand summary is now a
public artifact the operator does not control and often has never read — it frequently contains
their defects verbatim.

---

## 4. P2 — DIAGNOSE

### 4.1 Strengths first — they are assets, not boxes ticked
Most audits only find faults. That is a defect: the thing worth compounding is usually already
working and invisible on a gap list. Name each strength, **why it exists**, and whether a competitor
could copy it. Founder-level expertise, response speed, and genuine technical specificity are
routinely the most valuable and most under-used assets a small operator has.

### 4.2 Objections — what actually blocks the sale
Mine real objections from calls, reviews, community threads, support tickets, configurator drop-off
and abandonment — **not from keyword tools, which only see demand that already exists.** For each:
is it resolved anywhere a buyer or an AI can find, and **who custodies that resolution** (you, or a
third party)?

### 4.3 Journey gap map
Map every finding to **found → selecting → buying → after-sales**, then identify the **binding
constraint** — the one stage where fixing anything else changes nothing. Say which it is and why.

---

## 5. P3 — POSITION

### 5.1 Prefer asymmetry over best-practice
An action qualifies as **edge** only if a larger competitor cannot easily copy it — usually for
*organisational or economic* reasons rather than technical ones. Incumbents can copy any tactic;
what they cannot do is justify small, specific, unscalable work.

Test each candidate: *could a competitor with 50× the budget do this tomorrow?* If yes, it is
hygiene — do it if cheap, but never call it strategy.

**Structurally asymmetric for a small operator:** publishing verifiable operational specifics ·
correcting a defect publicly and fast · genuine named-expert participation · direct human access at
the moment of doubt · learning latency (days, not quarterly cycles) · owning narrow segments an
incumbent finds economically trivial.

**Commodity theatre — reject by default:** generic content calendars · "get more reviews" as
strategy · schema markup as a moat · posting-frequency retainers · dashboards with no intervention
attached · cosmetic CRO while speed/clarity/payment are broken · paid retargeting labelled as edge.

### 5.2 Never propose manipulation
Creating an artifact is legitimate. **Manufacturing apparent independence is not.** Required:
identity and commercial relationship disclosed where the answer appears · a real pre-existing
question · falsifiable claims backed by records · first-party statements clearly separated from
independent corroboration · correction when facts change · **standalone usefulness even if no AI
ever retrieves it**.

Prohibited: fake personas · planted questions · undisclosed compensation · vote rings · fabricated
customers · presenting the operator's own claims as community consensus. Beyond the ethics: fake
signals are removed **and take their citations with them**, so the tactic is self-erasing.

### 5.3 The verification path — usually unmanaged, usually decisive
Design what happens when a prospect leaves to check whether the business is real. Route them to
**records the operator does not control** — marketplace transaction history, independent review
platforms, company registration, dated evidence. Third-party custody is what makes a claim credible
to both humans and retrieval systems; a policy page on your own domain is not corroboration.

---

## 6. P4/P5 — PLAN and DISPATCH

Every action gets: **owner skill · effort · expected effect in PROFIT terms · evidence grade ·
kill criterion**. Rank by *(profit impact ÷ operator-hours)*, never by revenue.

### Dispatch map — action type → specialist

| Action concerns | Route to |
|---|---|
| AI-answer visibility, citation, crawler policy, feeds | `ai-search-optimizer` |
| Schema, site architecture, internal linking, Core Web Vitals | `seo-structure-architect` |
| Keywords, content strategy, topical coverage, decay | `seo-content-strategist` |
| Titles, meta, SERP presentation | `seo-meta-optimizer` |
| Off-site authority, entity building | `seo-authority-builder` |
| GSC/GA4/Clarity analysis, measurement design | `seo-data-analyst` |
| Agent transaction, ACP/AP2, agent-readable feeds | `agentic-commerce-readiness` |
| Page/journey UX, layout, information architecture | `audience-experience-design` |
| Built-interface usability + accessibility review | `ux-reviewer` |
| Persuasion, trust signals, pricing presentation | `conversion-psychology` |
| Category/PDP/cart/checkout content and structure | `ecommerce-growth` |
| A/B tests, GA4 events, statistical validity | `ecommerce-cro-experimentation` |
| WooCommerce/WordPress implementation | `woocommerce-developer`, `wordpress-developer` |
| Faceted navigation / filtering | `woocommerce-faceted-navigation` |
| Written content production | `content-writer`, `human-voice-writing` |
| Front-end implementation | `modern-frontend` |
| Multi-file execution of an approved plan | **`bob`** (via `forge` for anything architectural) |

**If no specialist owns an action, say so explicitly and file it as a library gap.** Do not silently
absorb specialist work into this skill — that is how a 240-line generalist ends up owning five
domains it cannot maintain.

---

## 7. P6 — MEASURE

### 7.1 Check statistical feasibility BEFORE designing any experiment
Compute what the order volume can actually detect. **At single-digit orders per month, order-level
A/B testing is impossible** — a two-arm conversion test can need *years* per arm. Saying so is
mandatory; proposing a test that cannot conclude is a serious error.

When order volume is too low, **move the measurement unit up the funnel** to something with hundreds
of observations per month — AI-answer composition, citation presence, impressions, quote requests.
**Orders remain ground truth for profit; they are simply unusable for significance.**

### 7.2 Measure to profit, and instrument attribution honestly
Track exposure → visit → enquiry → order → **profit after channel fees** → returns. Where a large
share of sales is untagged, the cheapest fix is a **post-purchase "how did you first hear about us?"**
— zero-party data, and the only instrument that sees zero-click discovery.

---

## 8. P7 — LEDGER

Record every action, its prediction, its result — **including nulls and adverse effects** — and its
evidence grade. Promote a method only on replication:

`conjecture → single-entity signal → replicated entity result → cross-category pattern`

**Failed methods stay recorded with their failure evidence rather than being deleted**, otherwise the
library forgets what does not work and proposes it again.

### 8.1 Keeping the advice itself from rotting

The same decay applies to this skill family. `scripts/claims_lint.py` finds a fact owned by several
skills whose verdicts **disagree** — the state that precedes a confidently wrong recommendation:

```bash
python3 ~/.claude/skills/business-edge/scripts/claims_lint.py drift --show-duplicates
python3 ~/.claude/skills/_meta/gates.py G_CLAIM_FRESHNESS --claim-mode strict   # exit 2 on drift
```

Duplication alone is reported, never blocking; **contradiction blocks in strict mode**. Run it after
any change to a fast-moving claim. A contested fact needs **one owner**; the rest point at it.

---

## 9. Anti-Patterns

| Don't | Why it hurts |
|-------|-------------|
| Report "no presence found" after a blocked or failed probe | Fabricates a negative finding. This has already happened once |
| Give revenue-denominated advice before knowing the profit model | Under a fixed per-unit fee, AOV and premium-mix advice is worthless |
| Recommend paid acquisition without the affordability ratio | Below ~1.5 GP-per-order ÷ CAC the auction is unwinnable by arithmetic |
| Propose an A/B test at single-digit monthly orders | It cannot conclude. Move the measurement unit up the funnel |
| Skip P2 and jump to recommendations | Produces the generic playbook every competitor already has |
| Only list gaps | Strengths are the compounding assets; a fault list misses them |
| Present a conjecture as best practice | n=1 is not evidence. Grade it and test it |
| Do the specialist work inside this skill | Creates an unmaintainable generalist and orphans the real owner |
| Propose seeded "independent" endorsement | Astroturfing. Self-erasing and reputationally fatal |
| Optimise a metric the profit model ignores | The most expensive error available here |
