# Evidence Capture Protocol

How `founder-validation` structures user-reported evidence, assigns verdicts, and scores
confidence. This protocol ensures that validation decisions are grounded in real data, not
optimistic interpretation.

---

## Evidence Artifact Schema

Every piece of evidence follows this structure:

```yaml
evidence_artifact:
  type: enum           # interview | landing_page | ad_test | survey | concierge | other
  date: date           # when the evidence was collected
  assumption_id: uuid  # links to venture-brief assumption being tested
  method: string       # "Mom Test interview" / "fake door landing page" / etc.
  raw_data:            # user-reported — must include quantitative data (HR-V5)
    interviews_completed: int       # number of interviews done
    replies_received: int           # responses to outreach
    objections_heard: list[string]  # specific objections, not "some concerns"
    prepay_asks_made: int           # how many times user asked for pre-payment
    conversion_events: int          # signups, purchases, downloads, etc.
    qualitative_notes: string       # free-text observations
  verdict: enum        # confirmed | falsified | inconclusive
  confidence: enum     # high | medium | low
  verdict_rationale: string  # why this verdict, citing specific data points
```

---

## Validation Rules (HR-V5 Enforcement)

Before accepting an evidence artifact, validate:

1. **At least one quantitative field must have a meaningful value:**
   - `interviews_completed > 0`, OR
   - `replies_received > 0`, OR
   - `conversion_events > 0`, OR
   - `prepay_asks_made > 0`
   - Exception: if the user explicitly reports "0 conversions out of 50 visitors" — that IS
     quantitative data (zero is a number, "it went well" is not)

2. **Reject vague evidence:**
   - "Good feedback" -- REJECTED. Ask: "How many interviews? What did they say specifically?"
   - "People are interested" -- REJECTED. Ask: "How many people? What action did they take?"
   - "It went well" -- REJECTED. Ask: "What specific outcomes? Numbers?"
   - "They said they'd buy it" -- ACCEPTED as evidence but NOT sufficient for `confirmed` (HR-V1)

3. **Objections must be specific:**
   - "Some concerns" -- REJECTED. Ask: "What specific objections? Quote them."
   - "Price is too high" -- ACCEPTED (specific objection)
   - "Not sure about the integration with Xero" -- ACCEPTED (specific objection)

---

## Verdict Logic

### `confirmed` — Behavioral Evidence Required (HR-V1)

An assumption can ONLY be marked `confirmed` when there is behavioral evidence. Verbal intent
("I would buy it") does NOT count. The table below defines what qualifies:

| Evidence type | Confirmed requires |
|---|---|
| Interview | Subject described building a workaround, switched from a competitor, committed time or money, offered unprompted referral |
| Landing page | Signup/email capture rate exceeds success criteria after minimum traffic |
| Ad test | CTR exceeds success criteria after minimum impressions; downstream conversion measured |
| Pre-order | At least 1 pre-order with real payment method |
| Concierge | Repeat usage, referral, or explicit willingness to pay after trial |
| Survey | NEVER confirm from survey alone. Survey can support other evidence but is never sufficient. |

### `falsified` — Kill Criteria Met

An assumption is marked `falsified` when experiment results fall below the kill criteria defined
in the experiment design:

| Evidence type | Falsified requires |
|---|---|
| Interview | Subjects cannot describe the problem, have no workaround, express indifference |
| Landing page | Signup rate below kill criteria after minimum traffic (200+ visitors) |
| Ad test | CTR below kill criteria after minimum impressions (1000+) |
| Pre-order | Zero pre-orders after adequate exposure and time |
| Concierge | Customer dropped after first session, found simpler alternative |
| Survey | Strong negative signal (< 10% recognize the problem) — can falsify |

### `inconclusive` — Between Success and Kill

Experiment ran but results don't clearly confirm or falsify:
- Sample size too small to conclude
- Results between success and kill criteria thresholds
- Contradictory signals within the same experiment
- External factors contaminated the results

**Default to `inconclusive` when in doubt.** It is better to say "we don't know yet" than to
force a premature verdict.

---

## Confidence Scoring

| Level | Criteria |
|---|---|
| high | Large sample (10+ interviews, 500+ page visitors, 5+ concierge customers), clear signal, consistent across data points |
| medium | Adequate sample (5-10 interviews, 200+ visitors), clear but limited signal |
| low | Small sample (< 5 interviews, < 200 visitors), ambiguous signal, or only one evidence source |

**Confidence modifiers:**
- Survey-only evidence: cap at `low` regardless of sample size
- Single experiment: cap at `medium` regardless of signal strength
- Contradictory evidence across experiments: cap at `low`
- Behavioral evidence (prepay, workaround, switch): +1 level

---

## Edge Cases

### "They said they'd buy it"

This is NOT `confirmed` (HR-V1). Record it as evidence with:
```yaml
verdict: inconclusive
confidence: low
verdict_rationale: "Verbal purchase intent expressed but no behavioral evidence (signup, prepay, workaround). Stated intent does not predict behavior."
```

### Zero results

Zero is valid data. "0 signups from 500 visitors" is a clear `falsified` signal:
```yaml
verdict: falsified
confidence: high
verdict_rationale: "0 conversion events from 500 unique visitors over 2 weeks. Below kill criteria of 2% signup rate."
```

### Mixed signals

Some interviews positive, some negative. Record as:
```yaml
verdict: inconclusive
confidence: low
verdict_rationale: "3/8 interviewees described the problem unprompted; 5/8 did not recognize it. Signal is mixed — may indicate a narrower persona."
```

### User wants to mark confirmed without behavioral evidence

Refuse (HR-V1):
> "I can't mark this assumption as confirmed based on [stated intent / survey data / generic
> interest]. To confirm, I need behavioral evidence: someone signed up, prepaid, built a
> workaround, or switched from a competitor. What you have supports `inconclusive` with a
> recommendation to run [a behavioral experiment]."

### Evidence from browser MCP analytics

Analytics data (from `read_analytics` mode) feeds into capture_evidence but requires user
confirmation:
> "I found [X metric] on your analytics dashboard. Can you confirm this is accurate and
> represents real user behavior (not bot traffic, not your own visits)?"

Analytics alone cannot confirm an assumption — it can support other evidence or falsify
(e.g., "landing page bounce rate 95%" is clear negative signal).
