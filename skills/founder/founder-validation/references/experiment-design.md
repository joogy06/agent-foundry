# Experiment Design

Methods matrix for validation experiments. Each method has a specific use case, minimum sample
size, timeline, cost estimate, and output format.

---

## Methods Matrix

| Method | Best for | Minimum sample | Timeline | Cost | Evidence strength |
|---|---|---|---|---|---|
| Interview (Mom Test) | Problem/need assumptions | 5-10 interviews | 1-2 weeks | $0 (your time) | Strong (behavioral) |
| Landing page (fake door) | Demand/positioning assumptions | 200+ unique visitors | 2-4 weeks | $50-200 (ads + domain) | Medium (click/signup) |
| Concierge | Solution assumptions | 3-5 customers | 2-4 weeks | $0-100 (your time + tools) | Strong (usage behavior) |
| Pre-order | Willingness-to-pay assumptions | 10+ orders | 2-4 weeks | $50-200 (page + payment) | Very strong (money) |
| Ad test | Channel/audience assumptions | 1000+ impressions | 3-7 days | $50-500 (ad spend) | Medium (engagement) |
| Survey | Preference/demographic assumptions | 50+ responses | 1-2 weeks | $0-100 (survey tool) | Weak (stated preference) |

---

## Method Details

### Interview (Mom Test)

**When to use:** Testing whether the problem exists and is severe enough to motivate action.
First method to use for any new assumption.

**Protocol:** See `interview-scripts-mom-test.md` for the full Mom Test protocol.

**Success criteria template:**
- "X out of Y interviewees described the problem unprompted"
- "X out of Y interviewees have built a workaround"
- "X out of Y interviewees would take a concrete next step (demo, beta signup, intro)"

**Kill criteria template:**
- "Fewer than 2 out of 10 interviewees recognize the problem"
- "No interviewee has built a workaround or switched tools because of this pain"
- "Interviewees describe the problem but rank it below 3 other priorities"

**Steps:**
1. Identify 10-15 potential interviewees from target persona
2. Reach out with a warm intro or cold outreach (keep it casual, not "market research")
3. Schedule 20-minute conversations
4. Use the Mom Test script from `interview-scripts-mom-test.md`
5. Take notes immediately after each conversation
6. Report evidence via `capture_evidence` after each batch of 3-5 interviews

### Landing Page (Fake Door)

**When to use:** Testing whether the positioning/messaging resonates and people will take action.
Use AFTER interviews confirm the problem exists.

**Success criteria template:**
- "Signup/email capture rate > X% of unique visitors"
- "CTA click rate > X% of page views"
- "Time on page > X seconds average"

**Kill criteria template:**
- "Signup rate < 2% after 500+ unique visitors"
- "Bounce rate > 85% from targeted traffic"
- "Zero email signups after 1 week of targeted ads"

**Steps:**
1. Build a single landing page (Carrd, Webflow, or static HTML)
2. Write copy focused on the validated problem, not features
3. Add a clear CTA: email signup, waitlist, or "notify me"
4. Drive 200+ targeted visitors via ads or direct outreach
5. Measure: signups, bounce rate, time on page, scroll depth
6. Report evidence via `capture_evidence`

### Concierge

**When to use:** Testing whether the proposed solution actually solves the problem. You manually
deliver the service to 3-5 customers.

**Success criteria template:**
- "X out of Y customers continued using the service after the trial period"
- "X out of Y customers referred someone else"
- "X out of Y customers expressed willingness to pay at the proposed price"

**Kill criteria template:**
- "Fewer than 1 out of 5 customers completed the full workflow"
- "No customer returned for a second session"
- "All customers found a simpler alternative during the trial"

**Steps:**
1. Recruit 3-5 customers from interview pool (people who described the problem)
2. Manually deliver the solution (you are the product)
3. Track: completion rate, time spent, user questions, friction points
4. After 2-4 weeks, ask: would you pay $X/month for this? (watch for behavioral signals)
5. Report evidence via `capture_evidence`

### Pre-order

**When to use:** Testing willingness to pay with real money. The strongest signal.

**Success criteria template:**
- "X pre-orders at $Y price point within Z days"
- "Conversion rate from landing page to pre-order > X%"

**Kill criteria template:**
- "Zero pre-orders after 2 weeks of targeted traffic"
- "Conversion rate < 0.5% after 1000+ page views"

**Steps:**
1. Build a pre-order page with payment processing (Stripe, Gumroad, etc.)
2. Set the proposed price (use the price from `founder-business-model` if available)
3. Make clear: "pre-order — product ships in [timeline]"
4. Drive traffic from validated channels
5. Track: orders, revenue, refund requests
6. Report evidence via `capture_evidence`

### Ad Test

**When to use:** Testing whether the target audience can be reached cost-effectively via a
specific channel.

**Success criteria template:**
- "CTR > X% on [platform]"
- "CPC < $X on [platform]"
- "CPM < $X on [platform]"
- "Landing page visits from ads > X in Y days"

**Kill criteria template:**
- "CTR < 0.5% after 5000+ impressions"
- "CPC > $X ceiling (making unit economics negative)"
- "Zero conversions from 1000+ ad clicks"

**Steps:**
1. Create 3-5 ad variants testing different messages
2. Set a budget ($50-500 depending on platform)
3. Target the specific persona from venture-brief.intake
4. Run for 3-7 days minimum
5. Track: impressions, clicks, CTR, CPC, conversions
6. Report evidence via `capture_evidence`

### Survey

**When to use:** Last resort for preference/demographic data. WARNING: surveys are the weakest
evidence type. Never use alone to confirm an assumption.

**Success criteria template:**
- "X% of respondents selected [option] (n > 50)"
- "Net Promoter Score > X from target persona"
- NOTE: survey success criteria are INDICATIVE, not confirmatory

**Kill criteria template:**
- "< 10% of respondents recognize the problem"
- "Response rate < 5% from target list"

**Limitations (always surface these):**
- Stated preference != revealed preference (people say they'd buy; they don't)
- Social desirability bias (people answer how they think they should)
- Question framing heavily influences results
- Cannot mark `confirmed` from survey alone — always follow up with behavioral method

---

## Experiment Design Template

Every experiment design follows this structure:

```yaml
experiment:
  id: <generated uuid>
  assumption_id: <uuid from assumptions[]>
  method: enum                   # interview | landing_page | concierge | pre_order | ad_test | survey
  hypothesis: string             # "If [assumption] is true, then [observable outcome]"
  success_criteria: string       # quantitative threshold that confirms
  kill_criteria: string          # quantitative threshold that falsifies
  minimum_sample_size: int       # from the methods matrix above
  timeline: string               # "2 weeks" / "1 month" / etc.
  steps: list[string]            # 5-8 concrete steps
  tools_needed: list[string]     # Calendly, Typeform, Carrd, Stripe, etc.
  cost_estimate: string          # $0 / <$50 / <$200 / <$500
  risks: list[string]            # what could go wrong
  designed_at: timestamp
  designed_by: "founder-validation"
  status: planned                # planned -> running -> completed -> abandoned
```
