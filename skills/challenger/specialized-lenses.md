# Challenger — Specialized Lenses

Reference file for domain-specific challenge lenses. Load only when reviewing proposals in these domains.

---

## SEO Claims Verification

When proposals include SEO recommendations or cite SEO data:

| Challenge | How to Verify |
|-----------|---------------|
| "This will improve rankings" | What specific mechanism? Which signal does it affect? |
| Statistics cited (e.g., "42% CTR boost") | What's the source? Sample size? Date? Vendor study? |
| "Best practice" claims | Best practice according to whom? Google's documentation or a blog post? |
| Schema markup claims | Check against Google's current rich results support (FAQ/HowTo deprecated) |
| Keyword strategy claims | Is keyword density being used? (Dead metric.) Entity-based approach? |
| "AI Overviews" assumptions | Appearance rates vary 15-48% by query type — which stat is being used? |
| Content length recommendations | Are they intent-matched or arbitrary word counts? |

**Red flags in SEO proposals:**
- Citing keyword density as a target (dead since 2024)
- Referencing "LSI keywords" (confirmed myth)
- Using vendor tool scores as ranking predictors (0.17-0.30 correlation at best)
- Outdated schema expectations (HowTo deprecated, FAQ restricted)
- Stats without dates (SEO data older than 12 months is likely stale)

---

## E-Commerce & Conversion Claims

When proposals make conversion or revenue impact claims:

| Claim Type | Challenge |
|-----------|-----------|
| "This will increase conversions by X%" | Based on what? A/B test data? Industry average? Single case study? |
| "Best practice" for checkout/cart | Is this tested on THIS audience or copied from a generic guide? |
| Urgency/scarcity tactics | Real data (stock levels, time-limited) or fabricated? Fabricated = dark pattern |
| "Customers want X" | Evidence? User research? Analytics data? Or assumption? |
| Price framing claims | Tested with this price range and audience? |
| Cart abandonment stats | Are these industry averages or THIS site's data? |
| Email sequence ROI claims | What's the sample size? Time period? Comparable business? |

**Red flags in e-commerce proposals:**
- Citing generic industry benchmarks as specific predictions
- Fake urgency ("Only 2 left!" without real inventory data)
- No A/B testing plan for conversion changes
- Copying competitor tactics without understanding why they work
- Ignoring mobile experience (60%+ of e-commerce traffic)

---

## Source Reliability & Trustworthiness

**Every claim needs a source. Every source needs vetting.**

| Source Type | Trust Level | Verification |
|-------------|-------------|-------------|
| Official docs (Google, MDN, RFC) | HIGH | Accept, check date |
| Peer-reviewed study | HIGH | Check methodology, sample size |
| Independent research (Ahrefs, Semrush with methodology) | MEDIUM-HIGH | Check if vendor-biased |
| Industry blog (Search Engine Journal, etc.) | MEDIUM | Cross-reference with 2+ sources |
| Vendor marketing / case study | LOW | Assume biased — look for independent confirmation |
| "Everyone knows" / no source | REJECT | Demand evidence or reject the claim |
| AI-generated statistics | LOW | AI hallucinates stats frequently — verify every number |

**Verification checklist:**
- [ ] Claim has a named source (not "studies show")
- [ ] Source is dated (reject undated SEO/tech claims)
- [ ] Source is independent (not the vendor selling the solution)
- [ ] Sample size is adequate (n=1 case studies are anecdotes, not evidence)
- [ ] Methodology is described (correlation does not equal causation)
- [ ] Numbers are plausible (36% conversion rate for all long-tail keywords? Unlikely)

**When in doubt — research it yourself** (see Self-Research in main SKILL.md).

---

## Performance Claims Verification

When proposals make performance claims:

| Claim | Challenge |
|-------|-----------|
| "Fast enough" | Define in numbers. What concurrency? What data volume? |
| "p95 < 200ms" | At what concurrency? Cold or warm cache? |
| "No caching needed" | Read:write ratio? What happens at 10x traffic? |
| "DB handles it" | Show EXPLAIN. Table size? Missing indexes? |
| "Scale horizontally" | Per-instance cost? Is bottleneck CPU/memory/IO? |

---

## Cognitive Biases to Detect

| Bias | Signal | Challenge |
|------|--------|-----------|
| **Anchoring** | First proposal gets most support | "Are we favouring this because it was first?" |
| **Sunk Cost** | "We already built X, so extend it" | "Would we choose this starting fresh?" |
| **Planning Fallacy** | "Should take a day" | "What's the realistic timeline with testing?" |
| **IKEA Effect** | Pride in custom solution | "Could an off-the-shelf tool do this?" |
| **Survivorship Bias** | "Company X does it this way" | "How many companies tried this and failed?" |
| **Groupthink** | Everyone agrees too quickly | "Let me argue the opposite for a moment" |
| **Complexity Bias** | Clever solution over simple one | "90% of the value with 20% of the complexity?" |
| **Confirmation Bias** | Seeking evidence FOR the approach | "What evidence would DISPROVE this works?" |
| **Optimism Bias** | Ignoring risks | "What's our worst realistic scenario?" |
| **Status Quo Bias** | "We've always done it this way" | "Is this habit or the best choice?" |

---

## Pre-Mortem (Gary Klein Method)

For major decisions, run a structured pre-mortem:

1. **Project forward:** "It's 6 months from now. This has failed spectacularly."
2. **Generate causes independently:** Each person (or agent) writes reasons for failure WITHOUT seeing others' lists
3. **Consolidate:** Merge all failure causes
4. **Prioritise:** Rank by likelihood x impact
5. **Mitigate:** For top 3 risks, define specific countermeasures
6. **Monitor:** Define early warning signals for each risk
