---
name: founder-validation
description: >
  Use when the user asks to validate a business idea, design experiments, draft interview scripts,
  capture evidence from real-world tests, or review assumption status. Phase 2 subskill of the
  founder family. Validation SUPPORT — designs experiments, drafts interview scripts (Mom Test),
  captures evidence, reads analytics via browser MCP (Envelope D). You run the experiments and
  report back. Modes: design_experiment, draft_interview, capture_evidence, read_analytics,
  evidence_review. Routes via parent `founder` skill. Trigger on: "validate my idea", "design an
  experiment", "Mom Test", "interview script", "capture evidence", "what do we know", "assumption
  ledger", "read my analytics", "evidence review".
---

# Founder Validation (Phase 2)

Child of `founder`. Validation support — owns the assumption ledger, experiment design, interview
scripts (Mom Test protocol), browser MCP analytics reading (Envelope D), and evidence capture with
user-reported artifacts. The user is the validator. This skill is the infrastructure.

**Scope:** Validation infrastructure. Designs experiments, drafts scripts, captures user-reported
evidence, reads analytics, reviews evidence gaps. Does NOT autonomously validate a business. The
user runs the experiments and reports back.

**Siblings (parent = `founder`):**
- `founder-ideation` — Phase 1 — adversarial brainstorm + data grounding
- `founder-business-model` — Phase 2 — calculator mode unit economics
- `founder-sprint` — Phase 2 — lean gatekeeper stage machine
- `founder-gtm` — Phase 3 (deferred) — positioning, distribution, channel selection

---

<HARD-RULE id="HR-V1">
**Never mark assumption `confirmed` based only on "they said they'd buy".** Require behavioral
evidence: signed up, prepaid, built a workaround, switched from a competitor, committed time or
money. Verbal intent is not evidence. "I would definitely use that" is not evidence. Conversion
events, pre-orders, workaround behaviors, and competitive switching are evidence.
</HARD-RULE>

<HARD-RULE id="HR-V2">
**Refuse to advance to `founder-sprint` Decision stage unless at least 1 real interview is
logged.** Interviews mean conversations with real people (not LLM-simulated users). The
`interview_count` field in venture-brief must be >= 1 and must reference a real
`capture_evidence` entry with type `interview`.
</HARD-RULE>

<HARD-RULE id="HR-V3">
**Browser MCP tools follow the Envelope D allow-list.** Any tool not on the allow-list is BLOCKED
and the skill refuses with an explanation. See `references/browser-mcp-allow-list.md` for the
canonical list. No exceptions. No "just this once."
</HARD-RULE>

<HARD-RULE id="HR-V4">
**"Zero evidence" is a valid state.** Surface it honestly as "we don't know yet" rather than
inferring. Never fabricate evidence, never treat absence of disconfirmation as confirmation.
An assumption with no experiments is `untested`, not `plausible`.
</HARD-RULE>

<HARD-RULE id="HR-V5">
**User-reported evidence must include raw numbers, not just "it went well".** Capture_evidence
mode requires quantitative or specific behavioral data: interviews completed (count), replies
received (count), objections heard (list), prepay asks made (count), conversion events (count).
"Good feedback" without numbers is rejected.
</HARD-RULE>

**Inherited hard rules (from parent `founder`):** HR-1 through HR-11 all apply. Key inherited
constraints: no valuation/legal/tax advice (HR-1, HR-2), no LLM-generated TAM (HR-3), kill
criteria required on all ideas (HR-4), data citations required (HR-5), founder is pre-execution
only (HR-6), venture-brief is canonical state (HR-7), intake required (HR-8), physical-world
bridge preferred (HR-9), epistemic honesty first-class (HR-10), Reddit privacy (HR-11).

---

## Modes

### 1. `design_experiment`

Given an assumption from the venture-brief, produce an experiment design.

**Input:**
```yaml
mode: "design_experiment"
assumption_id: uuid           # links to venture-brief.assumptions[]
assumption_claim: string      # the claim to test (from assumptions[].claim)
biz_type: enum               # from venture-brief intake
niche: string                # from venture-brief intake
stage: enum                  # from venture-brief intake
```

**Flow:**

1. **Read `venture-brief.yaml`** — load the assumption, existing experiments, intake context.
   Refuse if missing or if assumption_id not found.
2. **Select method** from the methods matrix (see `references/experiment-design.md`):
   - Interview (Mom Test) — for problem/need assumptions
   - Landing page (fake door) — for demand assumptions
   - Concierge — for solution assumptions
   - Pre-order — for willingness-to-pay assumptions
   - Ad test — for channel/audience assumptions
   - Survey — for preference/demographic assumptions (weakest method — flag this)
3. **Produce experiment design:**
   ```yaml
   experiment:
     id: <uuid>
     assumption_id: <uuid>
     method: <selected>
     hypothesis: string           # "If [assumption] is true, then [observable outcome]"
     success_criteria: string     # quantitative threshold
     kill_criteria: string        # what result would falsify the assumption
     minimum_sample_size: int     # method-dependent minimum
     timeline: string             # realistic, not aspirational
     steps: list[string]          # 5-8 concrete steps the user takes
     tools_needed: list[string]   # what the user needs (Calendly, Typeform, etc.)
     cost_estimate: string        # $0 / <$50 / <$200 / custom
     risks: list[string]          # what could go wrong with this experiment
   ```
4. **Write to venture-brief.experiments[]** with `status: planned`
5. **Return to user** with the full experiment design and "here's what you do next"

**Output:** Structured experiment design ready for the user to execute.

### 2. `draft_interview`

Produce a Mom Test interview script for a specific assumption.

**Input:**
```yaml
mode: "draft_interview"
assumption_id: uuid           # which assumption this interview targets
target_persona: string        # who you're interviewing ("UK accountant, 1-5 person practice")
interview_context: string     # optional — "first interview" / "follow-up after landing page"
```

**Flow:**

1. Read venture-brief. Load assumption and any prior interview evidence.
2. Apply the Mom Test protocol (see `references/interview-scripts-mom-test.md`):
   - Talk about their life, not your idea
   - Ask about the past, not the future
   - Less talk, more listen
   - Never pitch — extract
3. Produce a script with 10-15 questions:
   ```yaml
   interview_script:
     target_assumption: string
     target_persona: string
     warm_up: list[string]        # 2-3 context-setting questions
     core_questions: list[
       question: string
       follow_up_prompts: list[string]
       red_flag_answers: list[string]  # answers that signal fake validation
       green_flag_answers: list[string]  # answers that signal real pain
     ]
     closing: list[string]        # 2-3 wrap-up questions including the "ask"
     interviewer_notes:
       - "If they say 'I would definitely use that' — DO NOT count this as validation (HR-V1)"
       - "If they describe a workaround they've built — this is strong behavioral evidence"
       - "If they can't describe the last time they had this problem — the pain may not be real"
   ```

**Output:** Complete interview script with red/green flag guidance.

### 3. `capture_evidence`

User reports what happened. Skill structures it into the assumption ledger.

**Input:**
```yaml
mode: "capture_evidence"
experiment_id: uuid           # links to venture-brief.experiments[]
evidence:
  type: enum                  # interview | landing_page | ad_test | survey | concierge | other
  date: date
  assumption_id: uuid
  method: string              # "Mom Test interview" / "fake door landing page" / etc.
  raw_data:
    interviews_completed: int
    replies_received: int
    objections_heard: list[string]
    prepay_asks_made: int
    conversion_events: int
    qualitative_notes: string
```

**Flow:**

1. Read venture-brief. Load the experiment and assumption.
2. **Validate the evidence artifact (HR-V5):**
   - Reject if raw_data has no quantitative fields filled (interviews_completed, replies_received,
     conversion_events, prepay_asks_made — at least one must be > 0 or the user must explain why)
   - Reject "it went well" without numbers
   - Accept zero values if the user explicitly reports "0 conversions out of 50 visitors"
3. **Determine verdict per assumption:**
   - `confirmed` — ONLY with behavioral evidence (HR-V1): signup, prepay, workaround, switch.
     Verbal "I'd buy it" does NOT qualify.
   - `falsified` — experiment ran, results clearly below kill criteria
   - `inconclusive` — experiment ran, results between success and kill criteria, or sample too
     small to conclude
4. **Assign confidence:** `high` (large sample, clear signal) / `medium` (adequate sample, some
   noise) / `low` (small sample or ambiguous signal)
5. **Write to venture-brief:**
   - Update `experiments[experiment_id].evidence` with the artifact
   - Update `experiments[experiment_id].verdict`
   - Update `experiments[experiment_id].status: completed`
   - Update `assumptions[assumption_id].evidence[]` with reference
   - Increment `interview_count` if type is `interview`
6. **Return structured summary** including verdict, confidence, what it means, and what to test next

**Verdict logic detail:**

| Evidence type | Confirmed requires | Falsified requires |
|---|---|---|
| Interview | Described workaround, switched from competitor, committed time/money | Could not describe the problem, no workaround, indifferent |
| Landing page | Signup rate > success_criteria, email collection > threshold | Signup rate < kill_criteria after minimum traffic |
| Ad test | CTR > success_criteria, CPC < ceiling | CTR < kill_criteria after minimum impressions |
| Pre-order | Pre-orders > 0 with real payment method | Zero pre-orders after adequate exposure |
| Concierge | Repeat usage, referral, willingness to pay for continued service | Dropped after first session, no referral |
| Survey | WARNING: surveys are the weakest method. Never mark `confirmed` from survey alone. | Can mark `falsified` if strong negative signal |

### 4. `read_analytics`

Browser MCP Envelope D. Reads analytics dashboards and pages for evidence capture.

**Input:**
```yaml
mode: "read_analytics"
target: string                # URL or description: "my GA4 dashboard", "landing page at example.com"
metrics_of_interest: list[string]  # what to look for: "signups", "bounce rate", "CTR"
```

**Flow:**

1. **Verify browser MCP availability.** If browser MCP tools are not available, return a graceful
   degradation message: "Browser MCP is not available in this session. Ask the user to provide
   the analytics data manually."
2. **Navigate to the target** using ONLY Envelope D tools (see `references/browser-mcp-allow-list.md`):
   - `navigate` to load the URL
   - `get_page_text` to extract visible content
   - `read_page` for DOM structure (forms, CTAs, key elements)
   - `read_network_requests` for XHR/Fetch responses (GA4 JSON, GSC JSON)
   - `find` for natural-language element search
   - `javascript_tool` ONLY for read-only expressions (regex-gated — see allow-list)
   - `computer` ONLY for `screenshot` + `scroll` — NO clicks, NO typing
3. **Extract structured metrics:**
   ```yaml
   analytics_snapshot:
     url: string
     captured_at: timestamp
     metrics:
       - name: string            # "signup_rate", "bounce_rate", "sessions"
         value: string           # "3.2%", "150", "45s"
         source: string          # "page_text", "network_xhr", "dom_element"
     observations: list[string]  # "Landing page has no clear CTA above the fold"
     raw_data_available: bool    # whether XHR captured structured data
   ```
4. **Return for evidence capture.** The analytics snapshot feeds into `capture_evidence` mode.

**Envelope D enforcement:** Any tool call not on the allow-list is BLOCKED immediately (HR-V3).
The skill does not attempt the call and explains why it was blocked. See
`references/browser-mcp-allow-list.md` for the canonical allow-list with regex patterns for
`javascript_tool` gating.

### 5. `evidence_review`

Across all experiments, what do we know? What's still unvalidated? What should we test next?

**Input:**
```yaml
mode: "evidence_review"
# No additional input needed — reads everything from venture-brief
```

**Flow:**

1. Read venture-brief. Load all assumptions, experiments, and evidence.
2. **Build assumption status matrix:**
   ```yaml
   assumption_matrix:
     - id: uuid
       claim: string
       experiments_run: int
       latest_verdict: enum       # confirmed | falsified | inconclusive | untested
       confidence: enum
       evidence_summary: string   # 1-sentence summary of what we know
       risk_level: enum           # high (core viability) | medium (growth) | low (nice-to-have)
       next_action: string        # "run experiment X" / "sufficient evidence" / "pivot needed"
   ```
3. **Gap analysis:**
   - Which high-risk assumptions have zero evidence? (HR-V4 — surface honestly)
   - Which assumptions have only survey data? (flag as weak)
   - Which assumptions have contradictory evidence across experiments?
   - Are there enough interviews logged? (HR-V2 check for sprint readiness)
4. **Sprint readiness check:** can the venture advance to the Decision stage?
   - Top-3 riskiest assumptions each have >= 1 experiment with recorded evidence
   - >= 1 real interview logged (HR-V2)
   - No high-risk viability assumption falsified without pivot or accepted_risk
5. **Return structured review** with the matrix, gaps, sprint readiness verdict, and recommended
   next experiments

**Output:**
```yaml
evidence_review:
  total_assumptions: int
  tested: int
  confirmed: int
  falsified: int
  inconclusive: int
  untested: int
  interview_count: int
  sprint_ready: bool
  sprint_blockers: list[string]  # what's missing for Evidence -> Decision transition
  gap_analysis: list[string]
  recommended_next: list[string]
  risk_flags: list[string]
```

---

## Evidence Capture Protocol

The skill requires user-reported artifacts to close the loop. Evidence is NOT inferred from
analytics alone — the user must explicitly report what happened.

```yaml
evidence_artifact:
  type: enum           # interview | landing_page | ad_test | survey | concierge | other
  date: date
  assumption_id: uuid  # links to venture-brief assumption
  method: string       # "Mom Test interview" / "fake door landing page" / etc.
  raw_data:            # user-reported
    interviews_completed: int
    replies_received: int
    objections_heard: list[string]
    prepay_asks_made: int
    conversion_events: int
    qualitative_notes: string
  verdict: enum        # confirmed | falsified | inconclusive
  confidence: enum     # high | medium | low
  verdict_rationale: string
```

See `references/evidence-capture-protocol.md` for the full protocol including verdict logic,
confidence scoring, and edge cases.

---

## Cross-Skill Integration

```
founder (parent)
  | intake populated, route to founder-validation
  v
founder-validation (this skill)
  | read venture-brief
  |
  |-- design_experiment --> writes to venture-brief.experiments[]
  |-- draft_interview --> returns script to user
  |-- capture_evidence --> user reports back, updates venture-brief
  |-- read_analytics --> browser MCP Envelope D, feeds capture_evidence
  |-- evidence_review --> gap analysis, sprint readiness check
  |
  v
founder-sprint (Phase 2)
  | checks evidence_review.sprint_ready before Evidence -> Decision gate
```

---

## Failure Modes

| Failure | Detection | Response |
|---|---|---|
| No venture-brief / missing intake | File missing or intake incomplete | Return to parent: "intake missing"; parent asks the user |
| Assumption not found | assumption_id not in venture-brief.assumptions[] | Return error: "assumption {id} not found in venture-brief" |
| Evidence lacks raw numbers | capture_evidence validation fails (HR-V5) | Reject with: "evidence must include raw numbers — how many interviews? how many conversions?" |
| User claims "confirmed" on verbal intent only | HR-V1 check fails | Reject verdict, explain why verbal intent is not behavioral evidence |
| Browser MCP unavailable | Tool call fails or tools not in environment | Degrade gracefully: "Browser MCP not available — please provide analytics data manually" |
| Browser MCP tool not on allow-list | Tool name not in Envelope D list (HR-V3) | Block immediately, explain: "tool X is not permitted in Envelope D (read-only analytics)" |
| Zero experiments for an assumption | evidence_review surfaces it | Flag honestly as "untested" (HR-V4), recommend experiment |
| Schema version mismatch | venture-brief schema_version != 2 | Error and refuse to proceed (HR-7) |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Marking "confirmed" because the user said "they loved it" | Verbal intent is the #1 source of false validation; people are polite, not committed | Require behavioral evidence: signup, prepay, workaround, switch (HR-V1) |
| Skipping interviews and going straight to landing page tests | Landing pages test messaging, not problem existence; you need interviews first | Interview first (Mom Test), then landing page to test positioning |
| Treating survey responses as strong evidence | Surveys measure stated preference, not revealed preference; gap is massive | Flag surveys as weak; never mark `confirmed` from survey alone |
| Running experiments without clear kill criteria | Without kill criteria, every result is "encouraging" | Experiment design MUST include kill criteria before execution |
| Using browser MCP to fill out forms or click buttons | Violates Envelope D (HR-V3); the skill is read-only | BLOCK any write action; explain the Envelope D boundary |
| Inferring evidence from analytics without user confirmation | Analytics can be misleading (bot traffic, self-visits, etc.) | Analytics feed into capture_evidence; user confirms the narrative |
| Advancing to Decision stage with 0 interviews | HR-V2 violation | Refuse and surface the gap: "0 interviews logged, need at least 1" |
| Fabricating confidence from lack of disconfirmation | Absence of evidence is not evidence of absence | Surface as "untested" or "inconclusive" (HR-V4) |

---

## Reference Files

Read these as needed during validation work:

- `references/assumption-ledger-schema.md` — YAML schema for structured assumptions, linking to
  experiments and evidence
- `references/experiment-design.md` — methods matrix (interview / landing page / concierge /
  pre-order / ad test / survey), sample sizes, timelines, success criteria templates, cost
  estimates
- `references/interview-scripts-mom-test.md` — Mom Test protocol, question templates per
  assumption type, red flags, anti-patterns, "the three critical questions"
- `references/browser-mcp-allow-list.md` — Envelope D tool allow-list with regex patterns for
  javascript_tool gating, blocked tools with reasons
- `references/evidence-capture-protocol.md` — how to structure user-reported artifacts, verdict
  logic per evidence type, confidence scoring, edge cases

---

## When NOT to Use This Skill

- **User wants to generate ideas** (not validate them) -- use `founder-ideation`
- **User wants unit economics / pricing** -- use `founder-business-model`
- **User wants to build the product** -- hand off to `forge` via sprint
- **User wants legal / regulatory validation** -- REFUSED (HR-1, HR-2); refer to counsel
- **User wants to scrape competitor sites** -- NOT in scope; Envelope D is read-only analytics
  for the user's own properties
- **User wants to automate outreach** (Envelope B/C) -- deferred to Phase 2.5; Envelope D is
  read-only
