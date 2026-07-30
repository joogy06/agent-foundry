---
name: career-planning
description: >
  Use when the user needs to build a career plan, set milestones, define OKRs, create
  timelines, choose certifications, or map a professional development roadmap.
  Part of the career-* skill family.
family: career
disambiguation: Forward-looking structure — milestones, OKRs, timelines, certifications, development paths. Turning what you have ALREADY done into narrative is career-storytelling.
---

# Career Planning

Child of `career-coach`. This skill turns career direction — whether from a formal assessment or a stated ambition — into concrete, time-bound, measurable plans with milestones, gate checks, and accountability mechanisms.

**Scope:** roadmaps, career OKRs, milestone sequencing, certification strategy, professional development plans, 30/90/365-day plans, multi-year trajectories.

**Siblings:**
- `career-coach` (parent) — overall career coaching, assessment, strategy
- `career-assessment` — strengths/gaps analysis, competency mapping, career fit evaluation
- `career-positioning` — LinkedIn, personal brand, recruiter strategy, visibility (positioning strategy)
- `career-application-writer` — writing/tailoring the CV and cover letter
- `career-online-presence` — personal site, GitHub, social, AI findability
- `career-transition` — salary, title, offer negotiation, moves, pivots

---

## When NOT to Use This Skill

| If the user needs...                          | Redirect to...               |
|-----------------------------------------------|------------------------------|
| Strengths/gaps analysis, "where am I today?"  | `career-assessment`          |
| Positioning strategy, LinkedIn, personal brand | `career-positioning`        |
| Writing or tailoring the CV / cover letter    | `career-application-writer`   |
| Building online presence / findability        | `career-online-presence`      |
| Salary negotiation, offer evaluation, moves   | `career-transition`          |
| General career advice, big-picture strategy   | `career-coach`               |

---

## Description Triggers

Activate this skill when the user mentions: career roadmap, career plan, goals, timeline, professional development, certifications, learning plan, OKRs, milestones, "how do I get there?", career planning, development plan, 30-day plan, 90-day plan, quarterly goals, career objectives, promotion timeline, skill-building plan, certification path.

---

## HARD RULES

1. **Always** read the user profile from `~/.claude/skills/career-coach/references/user-profile.md` before producing any plan.
2. Plans must have **specific dates**, not "soon" or "eventually."
3. Every plan item needs a **success metric** — a way to objectively verify completion or progress.
4. Reference `~/.claude/skills/career-coach/references/corporate-ladders.md` for promotion timeline expectations.
5. Use **"professional development"** not "skills development" terminology.
6. **Plan for role volatility.** AI is reshaping role mixes faster than traditional plans assume — every multi-year plan should re-validate its target on a semi-annual cadence, keep a portable evidence trail (deployed projects, quantified wins), and include an AI-fluency track (Framework 6). Don't lock a 3-year plan and walk away.

---

## Interaction Pattern

Follow this sequence for every planning engagement:

### Step 1: Confirm Career Target
Pull from a prior assessment or ask the user directly. The target must be specific:
- NOT: "I want to be a CTO"
- YES: "CTO of a mid-tier bank, 500+ tech staff, board exposure, within 7 years"

### Step 2: Choose Planning Horizon
Ask the user which timeframe they need:
- **30-day plan** — quick wins, visibility actions
- **90-day plan** — capability building, relationship expansion
- **365-day plan** — position transformation, title/grade progress
- **Multi-year trajectory** — full reverse career plan with stepping-stone roles

### Step 3: Apply Appropriate Framework
Select from the frameworks below based on the horizon and the user's situation.

### Step 4: Produce Concrete Plan
Every plan item must include:
- **What** — specific action
- **By when** — exact date
- **Success metric** — how we know it is done
- **Dependencies** — what needs to happen first

### Step 5: Identify First Action (This Week)
No plan is complete without a single action the user commits to executing **this week**. It must be small enough to be achievable and visible enough to create momentum.

---

## Frameworks

### 1. Reverse Career Planning (5-Step)

Use for multi-year trajectories and when the user has a clear end-state ambition.

**Step 1 — Define the End State Precisely**
Do not accept vague targets. Push for specificity:
- NOT: "CTO"
- YES: "CTO of mid-tier bank (AUM $50B-200B), managing 500+ tech staff, with board-level exposure, P&L ownership of technology budget, within 7 years"

Specificity dimensions: title, organization type/size, scope (headcount, budget), influence level, geography, and timeline.

**Step 2 — Research the Path**
- Identify 10-15 people who currently hold the target role (LinkedIn research)
- Map their career trajectories backwards — what roles did they hold 3, 5, 10 years ago?
- Identify the 2-3 most common stepping-stone paths
- Note the credentials, experiences, and relationships that recur across multiple profiles

**Step 3 — Identify the Penultimate Role**
- What role sits directly below the target?
- What are its hard requirements (title, scope, years of experience, certifications)?
- What is the typical tenure before promotion to the target?
- What differentiates those who make the jump from those who plateau?

**Step 4 — Work Backwards to Current Position**
- Map every gap between where the user is now and the penultimate role
- Categorize gaps: experience gaps, credential gaps, relationship gaps, visibility gaps
- Sequence the gap-closing actions — which must come first?

**Step 5 — Build 2-3 Parallel Paths**
- Never build a single-path plan; always provide optionality
- Path A: fastest route (highest risk, requires perfect execution)
- Path B: balanced route (moderate risk, allows for setbacks)
- Path C: conservative route (lowest risk, longest timeline, most resilience)

---

### 2. Career OKRs (Quarterly)

Use for converting long-term direction into quarterly execution cycles.

**Structure:**
- **Objective:** Directional, inspiring, tied to the career target. One sentence. Qualitative.
- **Key Results (3-4):** Measurable, time-bound, within the user's control. Quantitative.

**Principles:**
- Key Results must be outcomes, not activities ("Gain executive sponsorship from an MD-level leader" not "Have coffee with executives")
- At least one KR should be a stretch (60-70% confidence of achievement)
- KRs must be within the user's sphere of influence — do not depend on others' decisions

**Examples for Banking IT:**

> **Objective:** Establish myself as the go-to AI strategy leader in the technology division.
>
> **KR1:** Present AI strategy paper to the CIO forum by [specific date] — success metric: presentation delivered, at least 2 follow-up conversations with senior leaders.
>
> **KR2:** Gain executive sponsorship from an MD-level leader for an AI initiative by [specific date] — success metric: named sponsor documented in project charter.
>
> **KR3:** Complete AWS Solutions Architect Professional certification by [specific date] — success metric: certification earned and added to internal profile.
>
> **KR4:** Publish internal thought-leadership piece on AI in regulatory compliance by [specific date] — success metric: published on internal platform with 50+ views.

**Review Cadence:**
- **Weekly:** 15-minute self-check — are KRs on track? Any blockers?
- **Monthly:** Adjust KRs if circumstances change (reorg, new priorities). Document why.
- **Quarterly:** Full reset. Score each KR (0.0-1.0). Set new OKRs for next quarter.

**Scoring:**
- 0.7-1.0 = strong delivery
- 0.4-0.6 = progress but fell short
- 0.0-0.3 = missed — analyze why and adjust approach

---

### 3. 70/20/10 Professional Development Model

Use for building a comprehensive development plan that balances learning methods.

#### 70% Experiential Learning (On-the-Job)

Specific stretch assignments for banking IT professionals:
- **Lead a cross-functional initiative** — e.g., coordinate a cloud migration workstream across infrastructure, security, and business teams
- **Take P&L ownership** — volunteer to own the budget for a technology initiative, even a small one; demonstrate commercial acumen
- **Manage a crisis** — step up during an outage, audit finding, or regulatory issue; crisis leadership is disproportionately career-accelerating
- **Present to regulators** — volunteer for regulatory exam preparation; direct regulator interaction signals senior-readiness
- **Deliver an executive briefing** — present a technology strategy or risk assessment to C-suite; practice synthesizing complex topics for non-technical audiences
- **Run a vendor selection** — lead an RFP process end-to-end; demonstrates procurement, negotiation, and decision-making capability

#### 20% Social Learning (Relationships)

- **Executive coffee chats (2-3 per month):** Structured 20-minute conversations with leaders 2+ levels above. Prepare 2 thoughtful questions. Follow up with a brief thank-you and insight summary.
- **Peer mastermind group:** Form or join a group of 4-6 peers at similar career stages. Meet monthly. Each person brings one challenge; group problem-solves.
- **Structured feedback loops:** After every significant deliverable, ask your manager and one stakeholder: "What worked? What would you change?" Document and act on patterns.
- **Reverse mentoring:** Offer to mentor a senior leader on emerging technology (AI, cloud-native). Builds relationship while demonstrating expertise.

**AI-fluency examples across the bands:**
- **70% (experiential):** ship one real LLM-API project end-to-end; introduce an AI-augmented workflow to your team and own its quality bar.
- **20% (social):** join or run an AI-practitioner peer group; reverse-mentor a senior leader on practical AI use.
- **10% (formal):** targeted current-generation AI/tooling learning — but a demonstrable project beats a generic badge (see Framework 6 and §5).

#### 10% Formal Learning (Courses, Certifications, Events)

**Certifications that matter in banking:**
- See Certification Strategy section below for detailed tiers

**Conferences:**
- Sibos (SWIFT) — global banking infrastructure and payments
- Money20/20 — fintech, payments innovation
- Risk.net events — risk management, regulatory technology
- AWS re:Invent / Microsoft Ignite — cloud architecture (pick your platform)
- Internal bank conferences and town halls — visibility within the organization

**Executive Education:**
- Short programs (1-2 weeks): MIT Sloan, Wharton, INSEAD — signal ambition and breadth
- Timing: pursue after reaching senior manager / VP level; earlier is premature

---

### 4. Milestone Sequencing

Use for structuring any plan into time-bound phases with gate checks.

#### 30-Day Plan (Quick Wins and Visibility)

**Purpose:** Build momentum, establish presence, signal intent.

Template:
| # | Action | By Date | Success Metric | Status |
|---|--------|---------|----------------|--------|
| 1 | [Visibility action — e.g., volunteer for a visible task] | [date] | [metric] | |
| 2 | [Quick win — e.g., solve a known pain point] | [date] | [metric] | |
| 3 | [Relationship action — e.g., schedule 4 coffee chats] | [date] | [metric] | |
| 4 | [Learning action — e.g., start certification study] | [date] | [metric] | |

**Gate Check at Day 30:**
- Did I complete at least 3 of 4 actions?
- Did anyone senior notice? (If not, visibility strategy needs adjustment)
- What surprised me? What do I need to adjust?

#### 90-Day Plan (Capability Building)

**Purpose:** Deepen capabilities, expand network, take on a stretch assignment.

Template:
| # | Action | By Date | Success Metric | Dependencies | Status |
|---|--------|---------|----------------|--------------|--------|
| 1 | [Stretch assignment — e.g., lead a workstream] | [date] | [metric] | [deps] | |
| 2 | [Certification milestone — e.g., pass exam] | [date] | [metric] | [deps] | |
| 3 | [Network expansion — e.g., build 3 new senior relationships] | [date] | [metric] | [deps] | |
| 4 | [Thought leadership — e.g., publish internal paper] | [date] | [metric] | [deps] | |
| 5 | [Feedback collection — e.g., 360 feedback from 5 stakeholders] | [date] | [metric] | [deps] | |

**Gate Check at Day 90:**
- Am I on track for my annual target?
- Have I closed at least one significant gap?
- Do I have an executive sponsor or advocate? (If not, this is the #1 priority for the next 90 days)

#### 365-Day Plan (Position Transformation)

**Purpose:** Achieve a meaningful career shift — title change, grade promotion, new role, or significant scope expansion.

Template:
| Quarter | Theme | Key Actions | Success Metrics |
|---------|-------|-------------|-----------------|
| Q1 | Foundation | [actions] | [metrics] |
| Q2 | Acceleration | [actions] | [metrics] |
| Q3 | Consolidation | [actions] | [metrics] |
| Q4 | Harvest | [actions] | [metrics] |

**Gate Checks:**
- End of Q1: Are foundations in place? Adjust if behind.
- End of Q2: Is momentum building? If not, escalate effort or recalibrate target.
- End of Q3: Is the promotion/transition conversation happening? If not, force it.
- End of Q4: Did you achieve the target? If yes, set next year's target. If no, diagnose honestly.

---

### 5. Certification Strategy for Banking AI

Use when the user asks about certifications, learning paths, or credentialing.

**Guiding Principle:** Certifications that signal "deployable capability in regulated environments" are worth far more than generic AI badges.

**AI-credential currency (2026).** For AI specifically, **one demonstrable LLM-API project — deployed, with a live URL and a strong README — beats a stack of generic AI certificates.** Generic AI/ML badges remain low signal in hiring; a real project ties directly to your GitHub portfolio and findability (route the portfolio build to `career-online-presence`). Always **verify what counts as "current-generation" at planning time** — the credential and tooling landscape shifts fast, so don't plan around last year's hot cert. *(This principle generalizes above the banking tiers below: in any sector, shipped evidence > badge.)*

#### Tier 1 — High Signal (Prioritize These)

| Certification | Why It Matters in Banking | Study Time |
|---------------|---------------------------|------------|
| AWS Solutions Architect Professional | Proves you can design production cloud architecture; banks are cloud-first now | 2-3 months |
| Azure AI Engineer Associate | Microsoft-heavy banks value this; shows applied AI, not just theory | 1-2 months |
| CISSP | Gold standard for security credibility; required for many senior roles in banking | 3-6 months |

#### Tier 2 — Domain Credibility (Build on Tier 1)

| Certification | Why It Matters in Banking | Study Time |
|---------------|---------------------------|------------|
| CRISC (Certified in Risk and Information Systems Control) | Shows you understand risk — the language of banking leadership | 2-4 months |
| CISM (Certified Information Security Manager) | Management-focused security; complements CISSP for leadership roles | 2-3 months |
| Kubernetes (CKA/CKAD) + Terraform Associate | Proves you can automate at scale; essential for platform/infrastructure leads | 1-2 months each |

#### Tier 3 — Nice to Have (Low Priority)

| Certification | Notes |
|---------------|-------|
| Generic AI/ML badges (Coursera, edX) | Low signal in hiring; fine for personal learning |
| Vendor-specific narrow certs (e.g., single-service AWS certs) | Too narrow to signal architectural capability |
| Project management (PMP, PRINCE2) | Only if moving into pure delivery management; otherwise signals wrong direction for technical leaders |

**Sequencing Advice:**
1. Start with one Tier 1 cert that aligns with your bank's primary cloud platform
2. Add CISSP if pursuing any role with "security" or "risk" in the title or scope
3. Layer Tier 2 certs based on your specific gap analysis
4. Ignore Tier 3 unless you have completed Tier 1-2 and have spare capacity

---

### 6. AI-Fluency Competency Track

Use to plan deliberate growth in AI capability — a first-class competency for technical roles now, not an optional extra. Three levels, each mapped to the 70/20/10 model:

| Level | What it means | Plan it via |
|---|---|---|
| **L1 — Personal productivity** | Use AI tools well in your own work; know their failure modes | 10% formal + daily practice |
| **L2 — AI-augmented team workflows** | Introduce and govern AI-augmented workflows for your team; own the quality bar | 70% experiential + 20% social |
| **L3 — Builds / governs AI systems** | Design, ship, and govern AI systems and their controls (model risk, evaluation, accountability) | 70% experiential (real LLM-API project) + L2 foundation |

**Planning rules:**
- Sequence L1 → L2 → L3; don't skip the foundation.
- **Anchor on a portable evidence trail** — a deployed LLM-API project (live URL + README) is the durable artifact; tie it to `career-online-presence`'s GitHub portfolio.
- **Role-volatility planning** — re-validate your AI-fluency target semi-annually (HARD RULE 6); the bar moves.
- Generalizes above banking: the levels apply in any sector; the worked examples just use a banking-tech lens.

---

## Output Format

Every plan produced by this skill must include:

1. **Career Target Statement** — one sentence, specific
2. **Planning Horizon** — which timeframe was selected
3. **The Plan** — table format with actions, dates, metrics, dependencies
4. **First Action This Week** — bolded, specific, achievable
5. **Review Schedule** — when the user will check progress
6. **Risks and Contingencies** — what could go wrong and what to do about it

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Plans with vague timelines ("soon", "Q3-ish", "eventually") | No accountability, no urgency — plans without dates are wishes | Every action gets a specific date; every milestone gets a deadline with a review checkpoint |
| Stacking certifications without a strategic narrative | Random certs signal "learning for learning's sake" rather than deliberate career positioning | Sequence certs to build a coherent story aligned with your target role (e.g., cloud architect path, not scattered badges) |
| Planning without a success metric for each item | No way to know if the plan is working — "improve leadership" means nothing measurable | Every plan item needs a concrete metric: completed cert by date, visibility event count, sponsor meeting cadence |
| Creating a 3-year plan and never revisiting it | Career context changes — reorgs, market shifts, new opportunities — stale plans mislead | Build review gates: 30-day quick check, 90-day course correction, annual strategy refresh |
| Optimizing for promotion timeline without considering lateral moves | Linear "wait for promotion" thinking ignores that lateral moves often accelerate advancement | Always evaluate lateral moves, scope expansion, and strategic jumps alongside linear promotion paths |
| Building an AI-era plan with no AI-fluency track | Role mixes are shifting under AI; a plan that ignores AI capability ages fast and leaves the user exposed | Include the AI-Fluency Competency Track (Framework 6) and a portable evidence trail in any multi-year plan |
