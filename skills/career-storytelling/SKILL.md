---
name: career-storytelling
description: >
  Use when the user needs to prepare interview answers, write a promotion case, build an
  achievement bank, practice STAR/STAR-L storytelling, quantify career accomplishments,
  or craft banking-specific professional narratives. Part of the career-* skill family.
triggers:
  - interview prep
  - mock interview
  - STAR stories
  - "how do I explain..."
  - achievement articulation
  - behavioral interview
  - promotion case
  - self-assessment writing
  - quantifying impact
---

# Career Storytelling

Child of `career-coach`. This skill focuses exclusively on converting raw experience into structured, compelling evidence — whether spoken (interviews, presentations) or written (CV bullets, self-assessments, promotion documents). It does NOT cover job search strategy, salary negotiation, or career path planning.

**Sibling cross-references:**
- Career path planning, progression strategy, promotion timing → `career-planning`
- Positioning strategy, LinkedIn profile, personal brand → `career-positioning`
- Salary negotiation, offer evaluation, job-search strategy → `career-transition`
- Leadership development, managing up → `career-leadership`
- Self-assessment / direction → `career-assessment`

> **Boundary:** storytelling supplies the raw quantified stories (the achievement bank); `career-application-writer` assembles them into the CV / cover-letter document.

---

## When NOT to Use This Skill

| If the user needs...                        | Redirect to...               |
|---------------------------------------------|------------------------------|
| Career path planning or progression strategy | `career-planning`           |
| Salary/compensation negotiation              | `career-transition`         |
| Job search strategy or recruiter engagement  | `career-transition`         |
| LinkedIn profile / positioning strategy      | `career-positioning`        |
| Leadership development or managing up        | `career-leadership`         |
| Self-assessment, "where am I?"               | `career-assessment`         |
| **Writing/tailoring the CV or cover letter** | `career-application-writer`  |
| **Building online presence / findability**   | `career-online-presence`     |

---

## Structured Interaction Pattern

Every engagement follows this flow:

1. **What is the context?** — Interview (which round?), promotion case, self-assessment, CV bullet, LinkedIn summary, presentation?
2. **What is the target audience?** — Recruiter, hiring manager, calibration committee, skip-level, LinkedIn connections?
3. **Gather raw experience** — Ask probing questions about what the user actually did. Drill into specifics: numbers, timelines, team size, decisions made, obstacles overcome, tools used, stakeholders involved.
4. **Apply the right framework** — Select and apply the appropriate framework below to structure the story.
5. **Refine until compelling** — Iterate until the story is specific, quantified, and tailored to the audience. Every claim must be backed by a concrete detail.

---

## Framework 1: STAR / STAR-L Method (Detailed)

The core framework for behavioral interview answers. STAR-L extends STAR with a Learning component that demonstrates growth mindset.

### S — Situation (Context with Specifics)
Set the scene with enough detail for the interviewer to understand the stakes:
- **Scale**: "a platform processing 4M transactions daily" not "a large system"
- **Regulatory environment**: "under FCA scrutiny following a Section 166 review"
- **Team size**: "a distributed team of 14 across London and Mumbai"
- **Budget**: "$3.2M annual run-rate program"
- **Business line**: "the retail mortgage origination platform serving 200K applications/year"

### T — Task (YOUR Specific Responsibility)
Distinguish between what the team was doing and what YOU specifically owned:
- **Assigned scope**: "I was brought in as tech lead to..."
- **Self-initiated scope**: "I identified the gap and proposed..."
- Clarify accountability: "I was directly accountable for delivery, reporting to the CTO weekly"

### A — Action (What YOU Did with Decision Rationale)
This is where senior candidates differentiate themselves. Focus on:
- **Decisions and trade-offs**: "I chose event-driven over batch processing because we needed sub-second fraud detection and the batch window was already at capacity"
- **Influence and leadership**: "I persuaded the risk committee to accept a phased rollout by presenting a risk-benefit matrix"
- **Technical depth when relevant**: "I designed the circuit-breaker pattern that prevented cascade failures during peak load"
- Use "I" not "we" — interviewers need to know YOUR contribution

### R — Result (Quantified in Metrics the Audience Cares About)
Always quantify. Map results to what the specific audience values:
- **Revenue**: "enabled $12M in new mortgage originations per quarter"
- **Cost**: "reduced annual infrastructure spend by $1.8M (34%)"
- **Risk**: "eliminated 3 critical audit findings, moving from Amber to Green RAG status"
- **Compliance**: "achieved full SOX compliance 6 weeks ahead of regulatory deadline"
- **SLA**: "improved API response time from 2.3s to 180ms (92% improvement)"
- **People**: "grew the team from 4 to 12, with 2 direct reports promoted within 18 months"

### L — Learning (Extension for Growth Mindset)
What you learned and — critically — how you applied that learning subsequently:
- "This taught me that stakeholder alignment before technical design saves 3x the rework. In my next program, I instituted a two-week discovery phase with all business stakeholders before writing a single line of architecture."

### Banking-Specific Metrics Checklist
When storytelling for banking roles, always try to include at least two of:
- FTE savings (manual effort eliminated)
- SLA improvement (latency, uptime, processing time)
- Regulatory findings closed or prevented
- Incidents prevented or MTTR reduced
- Manual processing eliminated (straight-through processing rate)
- Cost avoidance or reduction
- Risk events mitigated

---

## Framework 2: STAR Bank (Living Document)

A personal library of 15-20 achievement stories, organized by competency, ready to deploy at a moment's notice.

> **The bank is your antidote to generic-slop perception.** Recruiters increasingly perceive AI-generated, generic applications and answers (see `~/.claude/skills/career-coach/references/market-snapshot-2026-06.md`). The defense is concrete, verifiable, *yours-only* detail — the exact number, the specific constraint, the real decision. The STAR bank is where that lived specificity lives; it is also the evidence source `career-application-writer` draws on. Keep it true and keep it specific.

### Competency Categories for Banking IT
Organize stories across these categories (aim for 2-3 stories per category):
1. **Technical Leadership** — architecture decisions, platform builds, tech strategy
2. **Stakeholder Management** — managing competing priorities, influencing without authority
3. **Innovation** — introducing new technologies, process improvements, automation
4. **Team Building** — hiring, developing talent, building culture, succession planning
5. **Risk Management** — identifying and mitigating risks, incident response, controls design
6. **Regulatory Engagement** — working with compliance, audit responses, regulatory change programs
7. **Cost Optimization** — budget management, vendor negotiation, efficiency programs
8. **Crisis Management** — incident command, production outages, business continuity

### Generic (non-banking) categories
The same structure generalizes to any sector — pick the 6-8 competencies your target roles evaluate. A generalist set: Technical Leadership, Stakeholder Management, Delivery, Innovation, Team Building, Customer/User Impact, Cost/Efficiency, Incident/Crisis. (Banking is the worked example above; the principle — 2-3 true, quantified stories per competency — is universal.)

### Maintenance Cadence
- **Update monthly**: Add new achievements as they happen. If you wait until review season, you will forget critical details.
- **Before any interview or review**: Select 5-7 stories most relevant to the target audience and rehearse them aloud.
- **Annual refresh**: Archive stories older than 3 years unless they are landmark achievements. Replace with recent examples.

---

## Framework 3: SOAR-Accomplishment Format

For **written** achievements — CV bullets, self-assessment entries, promotion documents, LinkedIn summaries.

### Structure
```
[Action verb] [what you did] [at what scale] [resulting in what measurable outcome]
```

### Rules
- Lead with a strong action verb (Architected, Delivered, Transformed, Established, Spearheaded, Negotiated)
- Include scale indicators (team size, transaction volume, budget, user count)
- End with a measurable outcome (dollar amount, percentage improvement, time saved)
- One bullet = one achievement. Do not combine multiple accomplishments.

### Examples
- "Architected real-time fraud detection platform processing 2M daily transactions, reducing false positives by 60% and saving $1.8M annually in manual review costs"
- "Led 12-person cross-functional team through SOX remediation program, closing 14 critical findings in 8 weeks vs. 16-week regulatory deadline"
- "Established SRE practice for payments platform, improving uptime from 99.2% to 99.95% and reducing mean-time-to-recovery from 47 minutes to 8 minutes"
- "Negotiated $2.1M multi-year contract with infrastructure vendor, achieving 28% cost reduction while adding disaster recovery capabilities"

---

## Framework 4: Advanced Interview Frameworks (Senior Roles)

For VP, Director, and MD-level interviews where basic STAR is insufficient.

### SHARE: Situation, Hindrance, Action, Result, Evaluation
Best for showcasing how you overcame adversity or navigated organizational complexity:
- **Hindrance**: What made this hard? Budget cuts, political resistance, legacy tech debt, regulatory pressure, team attrition
- **Evaluation**: Your honest assessment of what worked and what you would do differently

### PARLA: Problem, Action, Result, Learning, Application
Best for demonstrating pattern recognition and continuous improvement:
- **Learning**: The insight or principle you extracted
- **Application**: A specific subsequent situation where you applied that learning

### "Table of Contents" Technique
For complex, multi-phase programs:
- Open with: "This was a 9-month program with three phases — discovery, platform build, and migration. I'll walk through the strategic decisions in each phase."
- Signals strategic thinking and organizational ability
- Gives the interviewer a mental map — they can follow along or redirect to the phase they care about most

### Senior-Level Principle: WHY > WHAT
At senior levels, interviewers already assume you can execute. They want to know:
- **Why** you chose this approach over alternatives
- **What trade-offs** you consciously accepted
- **How** you influenced the decision (not just made it)
- **What** would you do differently with hindsight

---

## Framework 5: Interview Format Preparation (Banking-Specific)

### Typical Banking Interview Pipeline
1. **Recruiter screen** — Culture fit, salary expectations, notice period, right to work
2. **Hiring manager** — Technical depth + team fit, your approach to problems
3. **Architecture / System design** — Whiteboard or take-home design exercise
4. **Behavioral panel** — Competency-based questions, usually 3-5 interviewers
5. **Sometimes: Case study** — Written or presentation-based scenario

### System Design Interviews
Structure your answer as: Requirements -> High-level design -> Deep dive -> Scaling
- **Always mention**: Regulatory constraints (data residency, encryption at rest), audit trails (who did what, when), disaster recovery (RPO/RTO targets, active-active vs active-passive)
- Banking differentiator: Show you think about compliance, data sovereignty, and operational resilience — not just performance

### Behavioral Panel
- Map your STAR Bank stories to the bank's published competency framework
- Banking panels commonly include: hiring manager, skip-level leader, HR business partner, cross-functional stakeholder (e.g., someone from risk or operations)
- Prepare for: "Tell me about a time you disagreed with a senior stakeholder," "Describe a production incident you managed," "How have you developed talent on your team?"

### Case Study
Common banking case study themes:
- Controls design: "How would you implement controls for X?"
- Resilience: "Design a disaster recovery strategy for our payments platform"
- Prioritization: "You have these 5 initiatives and budget for 3. Walk us through your decision."
- Incident response: "A critical production system is down. Walk us through your first 60 minutes."

---

## Framework 6: Promotion Case Writing

### Step-by-Step Process
1. **Get the competency framework** — Request the bank's official competency/grade framework from HR or your manager. Every bank has one. Your promotion case must map directly to it.
2. **Map achievements to competencies** — For each competency at your target grade, provide 2-3 concrete examples with SOAR-format bullets.
3. **Quantify in committee language** — Calibration committees care about four things:
   - Revenue enabled or protected
   - Risk reduced or controlled
   - Costs saved or avoided
   - Compliance achieved or maintained
4. **Collect stakeholder testimonials** — Get 3-5 written endorsements before calibration. Choose strategically: your manager, a skip-level leader, a peer from another function, a direct report, an external stakeholder (e.g., vendor, regulator contact).
5. **Demonstrate next-level thinking** — Show you are already operating at the next grade:
   - Strategic proposals you authored
   - Initiatives you started (not just delivered)
   - People you developed (promotions, stretch assignments, mentoring)
   - Cross-functional influence (impact beyond your immediate team)

---

## Framework 7: AI-Interview & One-Way-Screen Prep

AI / one-way video interviews have risen sharply and agentic screeners now sit early in many funnels (qualitative trend; figures in `~/.claude/skills/career-coach/references/market-snapshot-2026-06.md`). Preparing your STAR delivery for a machine-mediated first round:

- **State your numbers explicitly and verbally.** A one-way screen can't read your CV's formatting — say "we cut processing from four hours to thirty minutes" out loud, in the answer.
- **Structured, self-contained 60–90s answers.** Treat each prompt as a standalone STAR; don't rely on follow-up questions that a one-way format won't ask.
- **Natural delivery.** A human reviews the shortlist — rehearsed-robotic reads poorly. Clear, calm, specific beats performatively polished.
- **One prompt = one complete STAR.** Open with the situation, land the quantified result; don't trail off.

This is **clear-communication** guidance, not gaming — the goal is to be understood accurately by a constrained format, never to stuff keywords or manipulate a score.

**Candidate-side ethics (integrity).** Practicing *with* AI is fine and encouraged. **Live AI-ghosting of interview answers** (reading model-generated answers in a live or one-way interview) is a misrepresentation risk — your consistency duty extends to your live answers matching your documents and your real experience. Rehearse with AI; answer as yourself.

---

## Framework 8: Work-Sample & Live-Assessment Era

Skills-based hiring and live, proctored work-samples are increasingly replacing unsupervised take-homes (qualitative trend; see `market-snapshot-2026-06.md`). *(Implementer note: "skills-based hiring" is an industry term of art, quoted — not the family's competency usage.)*

- **Prep = rehearse doing the work live**, not memorizing answers. If the assessment is a live design or coding exercise, practice the actual activity under time and observation.
- **Your achievement bank is the source of reproducible patterns** — the approaches that worked before are what you reach for live. Mine it for the *method*, not a script.
- **Narrate your reasoning** as you work; assessors score how you think, not just the final artifact.

---

## HARD RULES

1. **Always read the user profile first** — Understand their current role, level, industry, and goals before crafting any story.
2. **No detector-gaming.** Detectors are unreliable and biased (see `~/.claude/skills/career-coach/references/market-snapshot-2026-06.md`); never coach toward "passing" or "fooling" an AI screen or detector. The goal is truthful, specific, human storytelling that reads as credible.
3. **Never fabricate or exaggerate** — Framing and emphasis only. Every claim must be truthful. Help the user find the best true version of their story.
4. **Always quantify** — "Led a team" is unacceptable. "Led a 12-person team delivering $2.3M in annual savings" is the standard.
5. **For banking: frame in committee language** — Revenue, risk, controls, compliance. These are the words that move calibration committees.
6. **Use "professional development" not "skills development"** — Aligns with corporate HR language in banking.
7. **When helping with interview prep, always ask what level/grade the target role is** — A VP behavioral answer is structured differently from an AVP answer.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Telling stories without quantified results | "Led a big migration" has no impact — interviewers remember numbers, not adjectives | Every story must include at least one metric: dollar amount, percentage, team size, timeline, or risk reduction figure |
| Using the same STAR story for every behavioral question | Interviewers notice repetition — signals shallow experience | Build an achievement bank of 8-12 stories mapped to different competency themes (leadership, conflict, innovation, delivery) |
| Preparing stories about what the team did without personal contribution | Panel interviews probe for individual impact — "we" answers get scored as unclear contribution | Use "I led/designed/decided/escalated" for your specific actions; acknowledge team context but be precise about your role |
| Fabricating or inflating achievements | One inconsistency under probing destroys credibility for the entire interview | Frame and emphasize truthfully — find the best true version of the story, never a fictional one |
| Skipping the Lessons Learned in STAR-L format | Missing the reflection component signals you execute but do not grow from experience | Always close with what you learned and how you applied it subsequently — this separates VP-level answers from AVP |
| Submitting AI-drafted answers or CV bullets verbatim | Reads as generic; recruiters perceive it, and live AI-ghosting is a misrepresentation risk | Use AI to rehearse, then deliver in your own voice with your own true specifics (Framework 7 ethics) |
