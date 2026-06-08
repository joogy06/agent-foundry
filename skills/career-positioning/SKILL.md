---
name: career-positioning
description: "Use when the user needs positioning strategy — what to emphasize on a resume/CV, LinkedIn profile and content strategy, personal brand narrative, recruiter relationships, internal visibility, conference speaking, or network mapping. Strategy and emphasis only - to WRITE or tailor the CV/cover-letter document itself use career-application-writer; to build online presence beyond LinkedIn (website, GitHub, social, newsletters, AI findability) use career-online-presence. Trigger on - position myself, CV strategy, what should my resume emphasize, LinkedIn profile, personal brand, recruiter, visibility, thought leadership. Part of the career-* skill family."
---

# Career Positioning

Child of `career-coach`. This skill handles **positioning strategy** — what to emphasize and how you're seen by external and internal audiences. It owns strategy and emphasis; the actual document and your off-platform presence live in sibling skills.

Siblings: `career-coach` (parent), `career-application-writer` (writes the CV/letter), `career-online-presence` (website/GitHub/social/AI findability), other `career-*` skills.

---

## When NOT to Use

| Need | Redirect to |
|---|---|
| Career strategy, promotion planning, performance reviews | `career-coach` |
| Salary/compensation negotiation | `career-coach` / `career-transition` |
| Interview preparation, behavioural questions | `career-storytelling` |
| Leadership development, managing up | `career-leadership` |
| Technical competency gap analysis | `career-assessment` or domain-specific skill |
| Building online presence beyond LinkedIn (website, GitHub, social, AI findability) | `career-online-presence` |
| Writing or tailoring the CV / cover-letter document itself | `career-application-writer` |

Use this skill when the deliverable is **positioning strategy** (what to emphasize, brand narrative, LinkedIn strategy, visibility plan, recruiter approach, speaking strategy, network map).

---

## HARD RULES

1. **Always read user profile first** — tailor every recommendation to their actual seniority, domain, and goals.
2. **Emphasize business outcomes, not technology names** — "reduced manual processing by 73%" beats "built Python automation." (Document construction of these bullets lives in `career-application-writer`.)
3. **LinkedIn content must reinforce target positioning, not scatter across random topics.**
4. **Apply the right vertical lens** — banking/finance dynamics when the user is in that world; generalize the principle otherwise (the worked examples here use banking).
5. **PDF default for CVs** — PDF is the safe default for semantic ATS (the older "ATS can't read PDF" caution has largely reversed; see `~/.claude/skills/career-coach/references/market-snapshot-2026-06.md`). Document format details live in `career-application-writer`.
6. **Use "professional development" / "competency", not "skills development"** for the user's growth.

---

## Structured Interaction Flow

1. **What is the positioning need?** — Job search? Internal visibility? Thought leadership? All of the above?
2. **Assess current positioning** — Review LinkedIn profile and/or CV if the user can share them.
3. **Define target positioning narrative** — Who are you, for whom, solving what?
4. **Create or optimize specific assets** — CV, LinkedIn, brand document, recruiter brief, speaking abstract.
5. **Build a 90-day visibility plan** — Concrete weekly/monthly actions with accountability checkpoints.

---

## 1. CV / Résumé Strategy (what to emphasize)

> **Generation lives in `career-application-writer`.** This section is the *strategic skeleton* — what to foreground. To actually write or tailor the document, route to the writer.

- **Lead with outcomes, not tools** — every bullet answers "what business outcome did this produce?" "Reduced manual processing by 73% with auditable exception handling" beats "built Python automation." Outcome before tool.
- **Make scope legible** — team size (direct + dotted-line), budget, data/transaction scale, number of business lines, and the regulatory frameworks you operated within (banking worked example: MiFID II, Basel III/IV, BCBS 239, SOX, GDPR, PRA/FCA, DORA).
- **Title + grade** — where banking grade and functional title differ, show both ("Vice President — Head of AI Engineering"); note equivalences across institutions.
- **Emphasis maps to the scorecard** — foreground the competencies the target role actually evaluates against (semantic-ATS rewards concept alignment, not keyword repetition).

### Semantic ATS (strategy summary)

Modern ATS uses semantic (vector-embedding) matching, not keyword counting — so keyword-stuffing *lowers* scores, and the real automated filter is the eligibility/knockout gate, not content scoring (see `market-snapshot-2026-06.md`). **For how matching works and how to align a document to it, see `career-application-writer`'s ATS section.**

### Digital-Footprint Consistency

Your CV, LinkedIn, and public footprint are increasingly cross-checked by screening tools — titles, dates, and headline metrics must agree across all of them. Authoring the consistent documents lives in `career-application-writer`; building the off-platform footprint lives in `career-online-presence`. (Current screening figures: `market-snapshot-2026-06.md`.)

---

## 2. LinkedIn Optimization

### How LinkedIn Ranks Content Now

LinkedIn's feed and search appear to be driven by an LLM ranking engine ("360Brew", **LIKELY** — hedge this) over an Interest Graph rather than a simple chronological/engagement feed (see `~/.claude/skills/career-coach/references/market-snapshot-2026-06.md`). Practical implications:

- **Write in your own voice** — AI-generated posts appear to be de-rewarded. Author genuinely; if you draft with assistance, run a voice pass (see `~/.claude/skills/career-coach/references/ai-tells-catalog.md`). Never optimize against a detector — write to sound like you because that is what reads as credible.
- **Saves and Sends are high-weight signals** — content people save or DM to a colleague outranks content that just gets a like. Write things worth keeping.
- **Carousels (document posts) and newsletters are favored** formats — use them where the content fits.
- **Profile ↔ posts topic consistency matters** — the Interest Graph reads your profile and your posting as one entity; keep them on the same few topics.
- **AI people-search implications** — your profile copy is also read by AI answer engines resolving "who is <name>"; write it as the canonical statement of what you do (off-LinkedIn findability lives in `career-online-presence`).

### Profile Sections

- **Headline** — a value proposition, not a job title. "Engineering Director | Building Resilient Trading Platforms for Tier-1 Banks", not "VP at Bank X".
- **About** — a strategic positioning document, not a biography: open with the business problem you solve, include 2-3 quantified impact statements, close with what you want (if searching) or care about; first person, under 2,000 characters.
- **Experience** — mirror your CV's outcome-focused bullets (3-5 per role, measurable). "Led 45-person AI engineering team delivering $12M annual savings across 3 business lines", not "Managed team."
- **Featured** — pin your best evidence: published articles, conference recordings, case studies, media mentions.
- **Recommendations** — target 8-12 from diverse sources (direct reports, peers, managers, business stakeholders); request *specific* ones ("Could you speak to the impact of the X programme?"), not generic.

### Content Strategy — 5 Durable Pillars

All LinkedIn content should map to one of these pillars:

1. **Industry Interpretation** — Your take on news, regulations, trends in financial services technology. Shows you understand the landscape.
2. **Operating Principles** — How you lead, build teams, make decisions, run programmes. Shows your leadership philosophy.
3. **Market Reality** — What you observe on the ground: adoption challenges, vendor hype vs. reality, what actually works. Shows practical credibility.
4. **Talent & Culture** — Hiring, retention, team building, diversity, engineering culture in financial services. Shows you build organisations, not just systems.
5. **Responsible Innovation** — AI governance, ethical automation, risk-aware technology adoption. Shows you are a safe pair of hands for regulators and boards.

**Cadence**: 1 post per week minimum. Consistency matters more than volume.

---

## 3. Personal Brand Architecture

> **Boundary:** this section covers brand *strategy* (narrative, topic ownership). Building the off-platform surface that carries the brand — personal site, GitHub, newsletters, AI findability — lives in `career-online-presence`. Cadence figures here are a strategic guide; current platform-specific mechanics live in `career-online-presence` and the market snapshot.

- **Target narrative** — one sentence that captures your professional identity; specific enough to be memorable and credible enough to withstand scrutiny. "Credible operator who makes AI safe, useful, and commercially meaningful in regulated finance" — not "AI enthusiast" / "passionate about innovation."
- **Topic ownership** — pick 2-3 *sharp* topics, not broad categories: "AI governance in regulated financial services", not "AI".
- **Cadence (strategic guide)** — LinkedIn posts ~1-2/week; long-form ~1/month; speaking ~2-4/year. Consistency over volume.
- **Engagement** — comment substantively (add insight, respectfully challenge — "Great post!" does nothing); engage with people you want to be associated with; add commentary rather than resharing silently.

---

## 4. Recruiter Relationships

### Key Recruitment Firms for Finance IT

**Specialist (VP / Director level — contingency and retained)**:
- Selby Jennings
- Huxley
- Cititec Talent
- Oliver James
- Robert Walters
- Robert Half
- Harvey Nash

**Executive Search (ED / MD / C-suite — retained)**:
- Korn Ferry
- Heidrick & Struggles
- Egon Zehnder
- Spencer Stuart

### Retained vs Contingency — Know the Difference

| Model | Typical Level | How It Works | Implication for You |
|---|---|---|---|
| Contingency | VP, Director | Recruiter paid only on placement. Multiple firms may work the same role. Speed matters. | Be responsive. You are one of many candidates. |
| Retained | ED, MD, C-suite | Firm paid upfront to conduct exclusive search. Thorough, slower process. | Relationship-driven. They come to you. Build trust over years. |

> **The named firms are a banking worked example.** The general principle — build relationships with 3–5 specialist recruiters in *your* sector before you need them — applies everywhere.

> **Apply-early under the flood.** Application volume is at record highs and cold-application response is very low; applying early in a posting's window measurably helps, and referrals + direct outreach beat the cold-apply channel by a wide margin (see `~/.claude/skills/career-coach/references/market-snapshot-2026-06.md`; full job-search strategy in `career-transition`).

### Relationship Rules

1. **Build relationships BEFORE you need them.** Connect with 3-5 specialists in finance IT recruitment now, while you are not looking.
2. **Be clear about what you want.** Vague briefs waste everyone's time. Know your target title, compensation range, geography, and deal-breakers.
3. **Be responsive.** Even if a role is not right, reply within 48 hours. Recruiters remember who ghosts them.
4. **Be honest.** About your situation, your timeline, your competing offers.
5. **Be a connector.** Refer good candidates to recruiters. The best recruiter relationships are bidirectional.
6. **Understand the dynamic.** The recruiter works for the hiring company, not for you. They are paid by the employer. Your interests are aligned but not identical.

---

## 5. Internal Visibility Strategy

- **Cross-functional exposure** — say yes to cross-silo projects (steering committees, working groups, transformation programmes); offer to brief Risk / Compliance / Operations / Front Office; join or create communities of practice. Bridge-building is rare and valued.
- **Internal content** — monthly team updates visible to leadership; conference takeaways written up for internal distribution; knowledge-sharing sessions (lunch-and-learns, tech talks, demo days).
- **Relationship architecture** — build 2 levels up (skip-level + peers, who discuss your promotion in calibration) and 2 levels down (shows you develop talent); become the cultural broker connecting IT and business silos (disproportionately valued in banking).

---

## 6. Conference Speaking & Thought Leadership

> **Scope = positioning only** (which stages to target, how to progress, how to pitch). Drafting the article/abstract/talk → `content-writer` (+ `human-voice-writing` for voice). Choosing/running distribution channels (newsletter, YouTube, social) → `career-online-presence`.

- **Progression path** — internal (tech forums, demos) → semi-external (vendor roundtables, practitioner groups) → external (meetups, webinars, podcasts, panels) → keynote-track (industry conferences, published research, advisory boards).
- **Write first, speak second** — published material is the best conference application; organisers want speakers who have demonstrably articulated ideas clearly. Build the written portfolio before pitching.
- **Key finance-tech conferences (banking worked example)** — Sibos, Money20/20, Innovate Finance, Finextra, Risk.net, TradeTech, AI & Big Data Expo.
- **Proposal tips** — propose *specific outcomes*, not broad topics: "How We Cut False-Positive Fraud Alerts by 60% Using ML", not "AI in Banking".

---

## 7. Network Mapping

### Three-Circle Model

| Circle | Size | Contact Frequency | Who |
|---|---|---|---|
| Inner | 5-10 people | Weekly/fortnightly | Closest professional allies who actively advocate for you. Mentors, sponsors, trusted peers. |
| Middle | 20-30 people | Quarterly | Strong relationships. Former colleagues, industry contacts, recruiters. Regular but not constant. |
| Outer | 50-100 people | Annually / event-based | Acquaintances who can be activated when needed. Conference contacts, LinkedIn connections with real interactions. |

### Mapping Dimensions

Map each contact against two axes:
1. **Power to help your career goals** — Can they open doors, make introductions, provide references, sponsor you?
2. **Domain diversity** — Tech, business, risk, compliance, operations, external industry, academia, regulation?

### Common Pathology for Senior IT Professionals

Senior technologists typically have networks that are:
- **Too homogeneous** — all technologists, no business/risk/compliance contacts
- **Too internal** — strong within current employer, weak externally
- **Too passive** — contacts exist but are never activated or maintained

The 90-day visibility plan should explicitly address whichever of these applies.

---

## Output Artefacts

Depending on the positioning need, this skill produces:

- Optimized CV/resume (formatted document or structured content)
- LinkedIn profile rewrite (headline, about, experience bullets, featured section recommendations)
- Personal brand narrative (one-pager: target narrative, topic pillars, content calendar)
- Recruiter engagement brief (target firms, outreach templates, talking points)
- 90-day visibility plan (weekly actions across internal visibility, external content, network building)
- Conference speaking abstract (title, summary, 3 learning outcomes, speaker bio)
- Network map (three-circle model with gap analysis and action items)

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Leading CV bullets with technology names instead of business outcomes | Hiring managers scan for impact, not tools — "Built Python automation" is invisible next to "Reduced processing time by 73%" | Lead with outcome and metric, then mention technology as context |
| Posting random LinkedIn content unrelated to target positioning | Scatters your brand — recruiters and hiring managers see no coherent expertise signal | Define 2-3 topic pillars aligned with your target role and post consistently within them |
| Using the same CV for every application | Generic CVs get filtered out; each role has different keyword triggers and priority signals | Tailor the top third of your CV (summary, key achievements) for each target role or role category |
| Networking only when job hunting | Relationships take months to warm up — cold outreach during active search feels transactional | Maintain your Three-Circle network year-round with quarterly touchpoints |
| Listing responsibilities instead of achievements on CV | Calibration committees and hiring managers scan for impact, not job descriptions | Use STAR/SOAR format: Situation, Task/Opportunity, Action, Result with quantified metrics |
| Keyword-stuffing the CV to game semantic ATS | Semantic ATS *lowers* scores for keyword repetition — stuffing now hurts, not helps | Express each concept + natural synonyms once; map to the scorecard (generation in `career-application-writer`) |
| CV, LinkedIn, and public footprint that disagree on titles/dates/metrics | Screening tools cross-check documents; inconsistency reads as a red flag | Reconcile all surfaces before publishing (consistency owned by `career-application-writer` + `career-online-presence`) |
