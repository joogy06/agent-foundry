---
name: presentation-narrative
description: >
  Use when presentation-builder delegates narrative construction — selecting audience-adapted
  narrative flows from 23 framework templates based on audience type, purpose, and constraints.
  Part of the presentation-* skill family.
---

# Presentation Narrative

Child of `presentation-builder`. This skill is responsible for selecting the
right narrative flow, generating a structured slide outline with action titles
and visual tags, and presenting it for approval before any visual work begins.

**Scope:** Narrative flow selection, slide outline generation, audience
adaptation, content structuring, and per-slide speaker notes (mandated by Hard
Rule 8). Does NOT handle visual design, styling, or final assembly — those are
handled by siblings.

**Siblings:**
- `presentation-datavis` — charts, tables, data visualization, data-driven slides
- `presentation-diagrams` — architecture diagrams, flowcharts, system visuals
- `presentation-styling` — templates, branding, colour palettes, layout conventions
- `presentation-renderer` — final assembly, PPTX/HTML export, format conversion

## Triggers

Invoke this skill when the user:
- Says "build a presentation", "create a deck", "put together slides"
- Provides a topic combined with a narrative or outline request
- Mentions a consulting presentation, pitch deck, status update, architecture
  review, retrospective, or training presentation
- Is routed here by `presentation-builder` after intake

## When NOT to Use

| Need | Redirect to |
|---|---|
| Charts, data visualization, data-driven slides | `presentation-datavis` |
| Architecture diagrams, flowcharts, system visuals | `presentation-diagrams` |
| Template, branding, styling, layout conventions | `presentation-styling` |
| Exporting to PPTX or HTML, final assembly | `presentation-renderer` |
| Full end-to-end orchestration (intake to export) | `presentation-builder` (parent) |

---

## 1. Flow Selection Logic

Based on audience + purpose, auto-select from the 23 flows defined in
`narrative-flows.md`. The selection matrix:

| Audience | Purpose | Recommended Flow(s) |
|---|---|---|
| Executive | Recommendation / decision | `minto-scr` or `pyramid-principle` |
| Executive | Status update | `status-risks-next` or `bluf` |
| Executive | Strategy / vision | `situation-complication-resolution` or `pyramid-principle` |
| Technical | Architecture review | `adr-presentation` or `rfc-design-review` |
| Technical | Demo / walkthrough | `problem-demo-architecture-next` or `show-and-tell` |
| Client | Sales / pitch | `aida` or `hook-problem-solution-proof-cta` |
| Client | Proposal / SOW | `pyramid-principle` or `problem-solution-benefit` |
| Mixed | Transformation / change | `before-during-after` or `heros-journey` |
| Mixed | Training / enablement | `tell-show-do-review` or `progressive-disclosure` |
| Banking | Regulatory / compliance | `exec-deepdive-appendix` |
| Banking | Risk review | `status-risks-next` with RAG indicators |
| Time-constrained | < 10 minutes | `kawasaki-10-20-30` or `ignite` |
| Time-constrained | Lightning talk (5 min) | `ignite` or `pecha-kucha` |
| Any | Retrospective | `timeline-retrospective` or `what-so-what-now-what` |
| Any | User-specified flow | Use the named flow directly |

The user can always override automatic selection by naming a specific flow.

## 2. Content Generation from Context

Gather content using the following priority order:

1. **Project context** — Read `PROJECT.md`, `COMPONENT.md` files if available
   in the current working directory or specified project path.
2. **Problem statement** — If the user provides a problem statement, brief, or
   objective, use it as the narrative spine.
3. **User-provided documents/data** — Read any files, links, or data the user
   supplies (reports, metrics, specs).
4. **Standalone mode** — If no project context exists, rely on LLM knowledge
   combined with user input to generate content.

For each slide, generate:
- **Title** — action title (the takeaway, NOT the topic)
- **Key message** — one sentence summarizing the slide's point
- **Bullet points** — 3-5 supporting points
- **Speaker notes** — what to say when presenting this slide
- **Visual tag** — one of `[DIAGRAM]`, `[CHART]`, `[IMAGE]`, `[TABLE]`, or
  `text` if no visual is needed. Include a brief description after the tag
  (e.g., `[CHART: revenue growth Q1-Q4]`).

## 3. Audience Adaptation

Reference `audience-profiles.md` for detailed tone, depth, and slide count
norms. Summary:

| Audience | Tone | Depth | Slide Count | Titles | Special Rules |
|---|---|---|---|---|---|
| Executive | Confident, concise | High-level, numbers-driven | 8-15 | Action titles mandatory | Lead with the answer, bigger numbers, no jargon |
| Technical | Precise, detailed | Deep, trade-offs welcome | 15-30 | Descriptive action titles | Diagrams expected, assumptions stated |
| Client | Polished, value-focused | Benefit-oriented | 10-20 | Benefit-oriented titles | No internal jargon, value propositions front and center |
| Banking | Formal, structured | Regulatory-grade | 12-25 | RAG status in titles where applicable | KRIs, source lines, regulatory citations required |
| Mixed | Accessible, layered | Progressive disclosure | 10-20 | Clear, jargon-free titles | Appendix for deep-dive material |

## 4. Outline Output Format

Always produce the outline in this exact structure:

```
## Slide Outline: [Presentation Title]
**Flow:** [framework name]
**Audience:** [type]
**Estimated slides:** [count]
**Estimated time:** [minutes]

### Slide 1: [Title Slide]
- Title: [Presentation title]
- Subtitle: [Date, presenter, team]
- Visual: [Logo placement]

### Slide 2: [Action Title — the takeaway]
- Key message: [one sentence]
- Supporting points: [bullets]
- Visual: [CHART: description] or [DIAGRAM: description] or text
- Speaker notes: [what to say]

### Slide 3: [Action Title — the takeaway]
- Key message: [one sentence]
- Supporting points: [bullets]
- Visual: [TABLE: description] or [IMAGE: description] or text
- Speaker notes: [what to say]

... (continue for all slides)

### Appendix slides (if applicable)
- Appendix A: [Title] — [purpose]
- Appendix B: [Title] — [purpose]
```

## 5. Hard Rules

1. **Always read user profile/capability map from parent** before generating
   content. The parent provides audience, context, and constraints.
2. **Always present outline for approval BEFORE generating visuals.** Never
   skip the approval gate.
3. **Action titles are MANDATORY.** The title IS the takeaway, not the topic.
   Bad: "Q3 Revenue". Good: "Q3 Revenue Exceeded Target by 12%".
4. **One idea per slide.** If a slide has two distinct points, split it.
5. **Tag visual needs explicitly:** `[DIAGRAM]`, `[CHART]`, `[IMAGE]`,
   `[TABLE]` — these tags drive parallel dispatch: `[CHART]`/`[TABLE]` to
   `presentation-datavis`, `[DIAGRAM]` to `presentation-diagrams`.
6. **Use "professional" language** for banking/executive audiences and
   **"accessible" language** for mixed audiences.
7. **Never exceed audience-appropriate slide count** without explicit user
   approval. If content demands more slides, ask first.
8. **Speaker notes are required** for every content slide (title and divider
   slides excluded).

## 6. Structured Interaction

Follow this sequence every time:

### Step 1: Confirm Goal and Audience
- If routed from parent, use the intake data provided.
- If invoked directly, ask: What is the presentation about? Who is the
  audience? What is the desired outcome?

### Step 2: Select Narrative Flow
- Auto-select using the flow selection matrix (Section 1).
- Present the selected flow with a one-line rationale.
- If the user names a specific flow, use it without question.

### Step 3: Gather Content
- Check for project context (PROJECT.md, COMPONENT.md).
- Read any user-provided files or data.
- If standalone, synthesize from LLM knowledge + user input.
- Ask clarifying questions only if critical information is missing.

### Step 4: Generate Slide Outline
- Produce the full outline in the format defined in Section 4.
- Apply audience adaptation rules from Section 3.
- Tag every visual need for downstream dispatch.

### Step 5: Present for Approval
- Show the complete outline to the user.
- Ask: "Does this outline capture what you need? Any slides to add, remove, or
  restructure?"
- Iterate until the user approves.

### Step 6: Return to Parent
- Pass the approved outline back to `presentation-builder` for parallel
  dispatch to `presentation-datavis`, `presentation-diagrams`, and
  `presentation-styling`, with final assembly by `presentation-renderer`.
- If invoked standalone (no parent), offer to expand the speaker notes in
  detail or hand off to sibling skills.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Choosing a narrative framework without knowing the audience | A persuasive pitch framework for a status update wastes time and annoys stakeholders | Profile the audience first (decision-maker, technical peer, mixed); select framework that matches their needs |
| Using the same framework for every presentation | Steering committee decks need different structure than technical reviews or training sessions | Match framework to purpose: Situation-Complication-Resolution for decisions, Pyramid for status, Story Arc for inspiration |
| Front-loading all the detail before the recommendation | Audiences lose attention; the key ask comes when energy is lowest; decisions get deferred | Lead with the recommendation/ask; support with evidence; detail in appendix for those who want depth |
| Not including a clear call-to-action | Audience agrees with the content but has no next step; presentation achieves nothing | Every presentation needs an explicit ask: approve, fund, decide, review by date, or acknowledge |
| Ignoring time constraints in narrative design | A 30-minute narrative for a 10-minute slot means rushing or cutting the conclusion (the most important part) | Design narrative to fit allocated time minus 20% (for questions); practice against clock |
