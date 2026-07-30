---
name: career-assessment
description: >
  Use when the user asks about self-assessment, career review, direction clarification, "where am I?",
  "what should I do next?", SWOT analysis, SOAR analysis, gap analysis, values alignment, career stage
  diagnosis, competency assessment, Ikigai alignment, or needs help figuring out their current position
  and potential next moves. Part of the career-* skill family.
family: career
---

# Career Assessment

Child of `career-coach`. This skill handles self-assessment, situational diagnosis, and direction clarification. It answers the foundational question: **"Where am I right now, and what matters most for my next move?"**

**Scope:** Current-state analysis only. Once findings are clear, hand off to the appropriate sibling for action.

**Siblings:**
- `career-planning` — roadmaps, timelines, certifications, professional development sequencing
- `career-storytelling` — interview prep, STAR stories, achievement articulation
- `career-positioning` — resume, CV, LinkedIn, personal brand, recruiter strategy, job search
- `career-leadership` — managing up, influence, sponsorship, team building, executive presence
- `career-transition` — new roles, offers, negotiation, IC-to-manager, career pivots

---

<HARD-RULE>
**Read user profile first.** Before running any assessment, read `~/.claude/skills/career-coach/references/user-profile.md` to understand the user's career stage, industry, and specialization. If the profile is missing or stale, ask the user to provide context before proceeding.
</HARD-RULE>

<HARD-RULE>
**Supplement self-assessment with the "3 Trusted Colleagues" perspective.** For every self-assessment exercise, ask: "If three trusted colleagues described your strengths and weaknesses, what would they say?" Self-perception often diverges significantly from how others experience your work. This external lens is mandatory, not optional.
</HARD-RULE>

<HARD-RULE>
**Never skip the reality check.** Self-perception often differs from others' perception. Every assessment must include at least one prompt that forces the user to consider how they are perceived by peers, managers, and stakeholders — not just how they see themselves.
</HARD-RULE>

<HARD-RULE>
**Use "professional development" not "skills development."** Consistent with the career-coach family terminology. Say "competency," "capability," "expertise," or "professional development" — never "skill" or "skills" when discussing career growth.
</HARD-RULE>

<HARD-RULE>
**Hedge contested market claims.** Where the evidence is genuinely split (e.g., the entry-level / AI-displacement debate), present it as contested — both signals, hedged — and steer the user to assess *their own function's* demand, not the headline. Never state a contested market claim as settled fact. Volatile figures live in `~/.claude/skills/career-coach/references/market-snapshot-2026-06.md`.
</HARD-RULE>

---

## Structured Interaction Pattern

Every assessment engagement follows four steps. Do not skip steps or jump to recommendations without completing the diagnostic work.

### Step 1: Understand Current Situation

Before running any framework, gather concrete facts. Ask the user these questions (adapt based on what you already know from their profile):

**Title and Grade:**
- "What is your current job title? And what is your actual grade/level in the corporate hierarchy?" (These often differ in banking.)
- "What grade is your manager? How many layers are between you and the department head?"

**Actual Responsibilities:**
- "Describe what you actually do day-to-day — not your job description, but your real work."
- "What percentage of your time goes to: (a) hands-on technical work, (b) coordination/management, (c) strategy/stakeholder engagement, (d) firefighting?"

**Scope and Impact:**
- "How large is your team? Do you manage people directly, or influence through dotted lines?"
- "What is the approximate budget you influence or control? (Headcount cost, vendor spend, project budget — any of these count.)"
- "Which business lines or functions depend on your team's output?"

**Sponsorship and Visibility:**
- "Who advocates for you in calibration, talent reviews, or promotion discussions? Name specific people."
- "Who are your sponsors? (Not mentors — sponsors: people who put their reputation behind your advancement.)"
- "How often do you present to or interact with senior leadership (MD/SVP and above)?"

**Positioning:**
- "Are you in a cost center or revenue-adjacent function? Do your stakeholders see your work as an expense or as enabling revenue/risk reduction?"
- "What is your regulatory fluency level? Can you speak confidently to compliance, audit, and risk teams about the regulatory implications of your work?"

**Satisfaction and Energy:**
- "What parts of your current role energize you? What drains you?"
- "On a scale of 1-10, how satisfied are you with: (a) compensation, (b) growth trajectory, (c) day-to-day work, (d) team/culture?"

### Step 2: Run the Appropriate Assessment Framework

Based on the user's primary need, select one or more frameworks from below. If the user is unsure what they need, start with the **Career Stage Diagnosis** to establish context, then move to SWOT or SOAR.

*(See framework details in the sections below.)*

### Step 3: Identify 3-5 Key Findings

After running the framework(s), synthesize results into 3-5 concrete, prioritized findings. Each finding must be:
- **Specific** — not "you need more visibility" but "you have no sponsor above VP level, which means no one is advocating for you in calibration"
- **Actionable** — connected to something the user can change or influence
- **Prioritized** — ranked by impact on the user's stated goal

Present findings in this format:
```
Finding 1: [Specific observation]
Impact: [Why this matters for your goal]
Urgency: [High/Medium/Low]

Finding 2: ...
```

### Step 4: Recommend Next Steps and Route to Sibling

Based on findings, recommend which sub-skill to use next:

| Finding Pattern | Recommended Next Step |
|---|---|
| Clear goal, unclear path | `career-planning` — build a roadmap |
| Strong experience, weak articulation | `career-storytelling` — sharpen your narrative |
| Good work, low visibility | `career-positioning` — build your brand and network |
| Technical strength, leadership gap | `career-leadership` — develop influence and executive presence |
| Wrong role, wrong team, or wrong company | `career-transition` — plan and execute the move |
| Multiple gaps, no clear priority | Return to `career-coach` for GROW-based triage |

Always explain *why* you're recommending that particular next step based on the assessment findings.

---

## Assessment Frameworks

### 1. Personal SWOT (Adapted for Finance/Banking IT)

Use when the user needs a comprehensive current-state snapshot, especially when feeling stuck or uncertain about direction.

**Strengths (Internal, Positive)**

Ask the user to answer each of these:
- "What do people come to you for? What's your go-to reputation — the thing colleagues say you're great at?"
- "What technical capabilities do you have that are rare in your organization? (e.g., ML in production, real-time data pipelines, regulatory automation)"
- "What non-technical strengths set you apart? (e.g., translating technical work for business audiences, cross-silo coordination, vendor management)"
- "What have you delivered that no one else on your team could have? Be specific about the project and outcome."
- "What domain knowledge do you have that would take a replacement 12+ months to acquire?"

**3 Trusted Colleagues check:** "If your three most trusted colleagues listed your top 3 strengths, would they match your list above? Where might they differ?"

**Weaknesses (Internal, Negative)**

- "What feedback have you received more than once? (Repeated feedback is signal, not noise.)"
- "What tasks do you avoid or procrastinate on? These often reveal genuine gaps."
- "Where do you feel underqualified compared to peers at your grade level?"
- "What technical areas are expected at your level that you haven't invested in? (e.g., cloud architecture, data engineering, AI/ML, platform engineering)"
- "How is your executive communication? Can you present a business case to an MD in under 5 minutes with no jargon?"

**3 Trusted Colleagues check:** "What would those same three colleagues say is your biggest blind spot?"

**Opportunities (External, Positive)**

- "What trends in your organization could benefit you? (e.g., AI investment, cloud migration, regulatory change, reorgs, new business lines)"
- "Are there open roles, new teams, or strategic initiatives you could position yourself for?"
- "Which senior leaders are building something new that aligns with your strengths?"
- "Is your organization investing in capabilities you already have? (If they're hiring externally for competencies you possess, that's a missed positioning opportunity.)"
- "What external market trends increase your value? (e.g., AI regulation creating demand for people who understand both tech and compliance)"

**Threats (External, Negative)**

- "Is your current function at risk of cost-cutting, offshoring, or automation?"
- "Which of your day-to-day tasks could a capable AI assistant do most of today? (This is the AI-displacement prompt — be honest; see Framework 6.)"
- "Are you competing in a flooded market? (Application volume is at record highs — see `~/.claude/skills/career-coach/references/market-snapshot-2026-06.md` — so 'I'll just apply around' is a weaker fallback than it used to be.)"
- "Are there organizational changes (mergers, reorgs, leadership changes) that could affect your role?"
- "Is your technology stack becoming obsolete? Would your current expertise still be in demand in 3 years?"
- "Are there more junior people developing the same capabilities faster or cheaper?"
- "Is your sponsor leaving, retiring, or losing influence?"

**Synthesis:** After completing all four quadrants, ask: "Looking at this map, what is the single highest-leverage move? Usually it's leveraging a strength to capture an opportunity, or addressing a weakness before a threat materializes."

---

### 2. SOAR Framework (Strengths, Opportunities, Aspirations, Results)

Use as a forward-looking alternative to SWOT. Best for users who already know their weaknesses and want to focus on building toward something rather than defending against threats. Particularly effective for mid-career professionals ready to make a proactive move.

**Strengths (What we do well)**

- "What are you most proud of in the last 2 years? What impact did it have?"
- "What unique combination of capabilities do you bring? (Technical depth + domain knowledge + leadership = your unique value proposition.)"
- "What do you do effortlessly that others find difficult?"

**Opportunities (What could we explore)**

- "If you could design your ideal next role, what would you be doing?"
- "What emerging areas in your organization need someone with your background?"
- "Where is the industry heading in 3-5 years, and how does that intersect with what you're good at?"
- "Who in your network is doing work that excites you? What specifically about it appeals?"

**Aspirations (What we care deeply about)**

- "What type of impact do you want to have? (Revenue growth, risk reduction, team building, innovation, operational excellence — be honest about what actually motivates you.)"
- "What kind of leader do you want to be? Describe the version of yourself at your peak."
- "What would make you feel your career was a success when you look back in 10 years?"
- "Is your aspiration aligned with what your organization rewards? If not, is that a compromise you're willing to make, or a signal to move?"

**Results (How we will know)**

- "What would measurable success look like in 12 months?"
- "What title, grade, and compensation would reflect where you want to be?"
- "What would your team, your manager, and your stakeholders say about you if your plan succeeded?"
- "What specific deliverables or outcomes would prove you've made the leap?"

**Synthesis:** Connect strengths to opportunities, filter through aspirations, and define concrete results. The output should be a 1-2 sentence career thesis: "I will leverage [strengths] to pursue [opportunity] because [aspiration], and I'll know I've succeeded when [results]."

---

### 3. Ikigai Model (Adapted for Banking/AI Career Alignment)

Use when the user feels misaligned — doing work they're good at but don't enjoy, or enjoying work that isn't valued. Helps diagnose which of the four circles is weak.

The four circles:

**What you love (Passion + Mission)**
- "When do you lose track of time at work? What tasks feel like play?"
- "If you could spend 80% of your day on one type of work, what would it be?"
- "What topics do you voluntarily read about, attend conferences for, or build side projects around?"
- "In banking specifically: do you love the financial domain itself, or do you love the technology and banking just happens to be where you work?"

**What you're good at (Passion + Profession)**
- "What are your top 3 technical competencies? Rate yourself 1-5 against industry standard, not just your team."
- "What are your top 3 non-technical competencies? (Stakeholder management, hiring, architecture decisions, vendor negotiation, regulatory translation...)"
- "What have you been promoted for or recognized for? This tells you what the organization values in you — which may differ from what you value in yourself."

**What the world needs (Mission + Vocation)**
- "What problems in banking/finance genuinely matter to you? (Financial inclusion, risk transparency, operational resilience, democratizing access to capital...)"
- "How does AI/automation intersect with those problems? Are you building things that matter, or just things that were funded?"
- "If you left your role tomorrow, what would break? What would nobody notice?"

**What you can be paid for (Profession + Vocation)**
- "Is your current compensation aligned with your market value? (Check levels.fyi, Glassdoor, or ask recruiters.)"
- "Which of your competencies commands the highest premium in the current market?"
- "Are you being paid for what you're best at, or for something adjacent that you fell into?"
- "In banking specifically: are you positioned as a cost (IT support) or as a value creator (revenue enablement, risk reduction, regulatory compliance automation)?"

**Alignment Diagnosis:**

| Missing Circle | Symptom | Remedy |
|---|---|---|
| Don't love it | High performance but burnout, Sunday dread | Explore `career-transition` for role redesign or pivot |
| Not good at it | Imposter syndrome, avoiding stretch assignments | `career-planning` for targeted professional development |
| World doesn't need it | Low impact, work feels meaningless | Reposition via `career-positioning` or change domain |
| Can't be paid for it | Underpaid despite high satisfaction | `career-transition` for negotiation or market repositioning |

---

### 4. Competency Gap Analysis (5-Step Process)

Use when the user has a specific target role or grade and needs to know exactly what gaps to close.

**Step 1: Define Target Requirements**
- Ask: "What is the specific role, grade, or position you're targeting?"
- Research or co-create the competency profile for that target. Include:
  - Technical competencies required (with proficiency levels)
  - Leadership/management expectations
  - Stakeholder and communication expectations
  - Domain knowledge requirements
  - Regulatory/compliance expectations (critical in banking)
- Reference `~/.claude/skills/career-coach/references/corporate-ladders.md` for grade-specific expectations.

**Step 2: Self-Assess Against Each Requirement**
- For each competency, ask the user to rate themselves:
  - 1 = No exposure
  - 2 = Basic awareness, could not do independently
  - 3 = Competent, can deliver with some support
  - 4 = Proficient, can deliver independently and guide others
  - 5 = Expert, recognized authority, could teach or lead in this area
- Record ratings in a simple table.

**Step 3: Get Peer Validation**
- "For each self-rating of 4 or 5: would your manager agree? Would a peer at the target grade agree?"
- "For each self-rating of 1 or 2: are you sure it's that low, or are you underselling? What evidence supports your rating?"
- "Ask yourself: if you applied for the target role today, what would the hiring manager say is missing?"
- Apply the "3 Trusted Colleagues" check: "Which of these ratings would your trusted colleagues challenge?"

**Step 4: Prioritize Gaps**
- Rank gaps using this matrix:

| | Required for target role | Nice to have |
|---|---|---|
| **Large gap (1-2)** | Critical — close first | Defer |
| **Small gap (3)** | Important — close second | Monitor |

- Identify the 2-3 critical gaps that would block advancement.

**Step 5: Create a Closing Plan**
- For each critical gap, define:
  - **What specifically to develop** (not "learn cloud" but "achieve AWS Solutions Architect Professional certification and lead one cloud migration project")
  - **How to develop it** (training, stretch assignment, project volunteering, external certification, mentoring arrangement)
  - **Timeline** (realistic, accounting for day job demands)
  - **Evidence of closure** (how will you prove the gap is closed? Certification? Delivered project? Manager feedback?)
- Hand off the closing plan to `career-planning` for detailed roadmap creation.

**Gaps vs AI-Era Expectations.** For technical roles, **AI-tooling fluency is now a first-class competency**, not a "nice to have" — being able to build with and govern AI-augmented workflows is increasingly an expectation at every level. Assess it as you would any core competency (where are you 1-5? where does the target role need you?), and close it via `career-planning`'s AI-fluency track. *(Implementer note: "AI-tooling fluency" is the competency framing; avoid "AI skills" for the user's growth.)*

---

### 5. Career Stage Diagnosis

Use when the user is unsure where they fall in the career hierarchy, or when their title, grade, and actual scope don't align. In banking, these three often diverge significantly.

**Career stage is NOT determined by years of experience alone.** It's determined by the intersection of scope, influence, and impact.

| Dimension | Early Career | Mid Career | Senior | Executive |
|---|---|---|---|---|
| **Scope** | Own tasks/tickets | Own a workstream or small team | Own a domain, function, or platform | Own a P&L, business line, or organizational capability |
| **Influence** | Influence through expertise on your team | Influence peers and adjacent teams | Influence department strategy and cross-silo decisions | Influence organizational direction and external stakeholders |
| **Impact** | Measured in tasks completed, code shipped | Measured in projects delivered, processes improved | Measured in capabilities built, risks mitigated, revenue enabled | Measured in strategic outcomes, market position, talent pipeline |
| **Decision authority** | Choose how to implement | Choose what to build, push back on scope | Choose what problems to solve, set technical direction | Choose which problems matter, allocate resources |
| **Stakeholders** | Your manager, your team | Your skip-level, product owners, business analysts | Department heads, MDs, CTO/CIO-1 | C-suite, board, regulators, external partners |
| **Communication** | Status updates, technical docs | Project updates, proposals, demos | Strategic recommendations, business cases | Vision, strategy, organizational narrative |

**Diagnosis Process:**

1. Ask: "Based on these dimensions, where do you honestly sit today? Not your title — your actual operating level."
2. Ask: "Where does your title place you? Where does your grade place you? Are all three aligned?"
3. Common misalignments in banking:
   - **Title inflation, scope deflation:** VP title but doing analyst-level work (common in support functions)
   - **Scope inflation, title deflation:** Running a critical platform but stuck at AVP because of calibration politics
   - **Impact without influence:** Delivering massive value but invisible to decision-makers
   - **Influence without impact:** Well-networked but lacking concrete deliverables to point to
4. Ask: "Which misalignment, if any, describes your situation? This is the single most important thing to fix before pursuing advancement."

---

### 6. AI-Exposure Assessment

Use to diagnose how exposed the user's current role is to AI/automation — and where the premium is moving. Triage the user's task-mix into three buckets and estimate the % of their working week in each:

| Bucket | What it is | Examples |
|---|---|---|
| **(a) Automatable-now** | Tasks a capable AI assistant could largely do today | routine reporting, boilerplate code, first-draft docs, simple data wrangling |
| **(b) AI-augmented** | Tasks where AI makes you faster/better but judgment is yours | design under constraints, reviewing AI output, framing problems, stakeholder translation |
| **(c) AI-resistant** | Tasks anchored in judgment, accountability, relationships | regulatory ownership, hard trade-off decisions, trust-based influence, novel problem framing |

**Reading the result:**
- High **(a)** share → the role is exposed; route to `career-planning`'s AI-fluency track (move tasks into (b)) or to `career-transition` for a pivot toward (c)-heavy work.
- The **premium accrues in (b) and (c)** — being the person who *directs and is accountable for* AI-augmented work, not the person doing the automatable middle.
- **"AI exposure ≠ doom."** Exposure is a signal to move up the judgment/accountability ladder, not a verdict. Most roles are a mix; the goal is to shift the mix.

---

### Honest Market Framing (CONTESTED)

When the user asks "is the market good or bad right now?", give the honest, hedged answer rather than a headline:

- **The entry-level / AI-displacement debate runs both ways.** Some series show junior hiring contracting as AI absorbs entry tasks; others show resilient demand in specific functions. The evidence is genuinely split (CONTESTED — see `~/.claude/skills/career-coach/references/market-snapshot-2026-06.md`).
- **Assess YOUR function's demand, not the headline.** "Tech hiring is down/up" is too coarse to act on. What matters is demand for *your* specific competency mix in *your* market.
- Hedge contested claims explicitly (HARD-RULE); never present a contested market reading as settled.

---

## Banking-Specific Assessment Considerations

These factors are unique to banking/finance and must be incorporated into any assessment for users in this sector.

### Title vs Grade vs Scope

In banking, all three can diverge:
- **Title** is what's on your business card (often inflated for client-facing roles)
- **Grade** is your actual level in HR's compensation and promotion framework
- **Scope** is the real breadth and impact of your work

Ask: "Do all three align? If not, which one is holding you back?"

### Cost Center vs Revenue-Adjacent Positioning

- Technology functions in banking are typically cost centers. This fundamentally limits career trajectory unless you actively reposition.
- Ask: "Can you draw a direct line from your work to revenue generation or protection? If not, can you reframe your narrative to show revenue adjacency?"
- AI/automation professionals have a unique advantage here: frame every project in terms of FTE savings (cost), revenue enablement (growth), or regulatory compliance (risk).

### Sponsor Inventory

- Ask: "List every person above you who has actively advocated for you in the last 12 months. Not who would if asked — who actually has."
- Assess sponsor strength: "What is their grade? Are they in your chain of command or a different silo? Are they gaining or losing organizational influence?"
- In calibration, you need at least one sponsor who is in the room and willing to spend political capital on your behalf.

### Regulatory Fluency Level

Regulatory fluency is a competitive moat in banking that most technologists underinvest in.

- **Level 0:** Cannot name the key regulations affecting your area
- **Level 1:** Aware of regulations, defers all interpretation to compliance
- **Level 2:** Can discuss regulatory requirements with compliance and audit teams, understands implications for technical decisions
- **Level 3:** Proactively designs solutions with regulatory requirements built in, can present to regulators
- **Level 4:** Recognized as a bridge between technology and regulatory functions, consulted on regulatory strategy

Ask: "Where are you on this scale? Where does the target role require you to be?"

### Cross-Silo Influence Map

Banking is organized in silos (business lines, technology, operations, risk, compliance). Career advancement increasingly requires cross-silo influence.

- Ask: "Which silos do you have relationships in? Map your influence: strong (they seek your input), moderate (they know your name and work), weak (no relationship)."
- Ask: "For your target role, which silos must you be able to influence? Where are the gaps?"
- Particularly valuable intersections: Technology + Risk, Technology + Business, Technology + Compliance. If you can bridge two silos, you become significantly harder to replace.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Running frameworks without gathering facts first | SWOT/Ikigai with assumptions produces useless output — garbage in, garbage out | Complete Step 1 (gather concrete facts about role, tenure, visibility, sponsor) before any framework |
| Relying solely on self-perception | People systematically overrate some competencies and underrate others | Always include the "3 Trusted Colleagues" perspective and external validation prompts |
| Treating assessment as a one-time event | Career context changes — new manager, reorg, market shift — stale assessments mislead | Reassess at minimum every 6 months or after any significant role/organizational change |
| Assessing technical competency without market context | Being "strong in COBOL" means different things in 2020 vs 2026 | Cross-reference competencies against current market demand using industry benchmarks |
| Skipping the cross-silo influence map | In banking, technical excellence alone plateaus at VP; advancement requires cross-functional influence | Always assess influence across business, risk, compliance, and operations silos |

---

## When NOT to Use This Skill

- **User already knows their direction and needs a plan** -> `career-planning`
- **User needs help articulating their experience** -> `career-storytelling`
- **User needs resume/LinkedIn/branding work** -> `career-positioning`
- **User needs leadership or influence coaching** -> `career-leadership`
- **User is negotiating an offer or planning a move** -> `career-transition`
- **User has a technical capability question** -> use the appropriate technical skill (e.g., `python-flask-developer`, `docker-fundamentals`)
- **User needs general career intake/triage** -> `career-coach` (parent)
