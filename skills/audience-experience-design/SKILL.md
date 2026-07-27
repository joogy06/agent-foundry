---
name: audience-experience-design
description: Use when designing how an audience will experience an artifact BEFORE building it — websites, web apps, dashboards, business reports, or any user-facing flow — turning audience, intent, and desired emotional/trust response into buildable design decisions. Covers audience/job/context modeling scoped per audience type, journey and reading-path design, information architecture and attention hierarchy, ergonomics and ease-of-use decisions, emotional-design intent (the audience must feel understood), buildable component/wireframe/state specs, semantic token and layout briefs, and measurable acceptance criteria. Trigger on - design the experience, user journey, information architecture, make it engaging, audience perception, wireframe, report layout, app flow design, ergonomics, emotional design. Built-interface reviews live in ux-reviewer; deck flows in presentation-narrative; commerce funnels in ecommerce-growth; persuasion copy in conversion-psychology; implementation in the platform skills.
---

# Audience Experience Design

Design how an audience will **experience** an artifact — before a line of it is
built. This skill turns *who the audience is*, *what they came to do*, and *how
they should feel* into concrete, buildable design decisions that a platform
skill can implement. It is medium-neutral at the contract layer and works for
websites, web apps, dashboards, business reports, and any user-facing flow.

Design decides; the platform renders. Every section below must end in a
**decision** — an ordered content choice, a component/interaction/state, a
layout or token-role choice, or a measurable acceptance criterion. If a section
is only principles, it is not doing this skill's job.

## 1. Overview, Routing & the Boundary Invariant

**BOUNDARY INVARIANT (load-bearing).** This skill owns the **medium-neutral
experience contract** and the currently-unowned mediums: **apps, business
reports, and generic user journeys**. Where a medium skill already owns the
journey, this skill produces the **upstream brief and HANDS OFF** — it never
re-derives an owned flow. Specifically, it does **not** re-derive:
- **deck / slide flows** → owned by `presentation-narrative`;
- **the commerce funnel** → owned by `ecommerce-growth`;
- **persuasion copy** → owned by `conversion-psychology`;
- **built-interface review** → owned by `ux-reviewer` (this skill designs; that
  skill reviews the built result).

**The decision this section produces — own vs hand off.** For the artifact in
front of you, classify each part: *does a medium skill already own this
journey?* If yes, write the brief (audience, intent, desired response,
acceptance criteria) and route to that owner. If no (a business report, an app
flow, a generic journey), this skill owns it end-to-end. Record the routing
decision explicitly before designing — it determines which sections below you
author versus hand off.

## 2. Audience Model

Produce a **named audience model**, scoped **per audience type** (do not design
for a mythical average user):

- **Type & job** — who they are and the concrete job they came to do
  ("finance reviewer approving a variance", "first-time shopper comparing two
  products", "on-call engineer triaging an alert").
- **Prior knowledge & vocabulary** — what they already know; which terms to use
  and which to define. This decides labels and the level of explanation.
- **Context** — device, environment, time pressure, attention budget. A report
  read in a Monday review meeting and a dashboard watched during an incident are
  different design problems.
- **"Feeling understood" — made concrete per type.** State the specific signal
  that makes THIS audience feel the artifact was built for them (e.g. the
  finance reviewer sees the variance and its driver in the first screen without
  scrolling; the shopper sees the one fact that resolves their comparison). This
  is a design decision, not an adjective.
- **Desired action + emotional/trust constraint** — the single primary action
  and the trust state required to take it (confidence, safety, urgency-without-
  pressure).

**Decision produced:** the audience type(s), their vocabulary, and the concrete
"understood" signal each must receive — which constrains labels, content, and
tone downstream.

## 3. Journey / Reading Path

Design the ordered path through the artifact — **entry, transitions, states,
completion** — for the chosen medium:

- **Apps / flows:** the task path step by step, plus the **error, empty, and
  loading states** for each step (an app design that omits these is unbuildable).
  Decide what the user can do next at each step and what happens when it fails.
- **Business reports (a medium this skill OWNS):** the **reading order** and the
  **two paths** — the executive path (headline → verdict → one supporting fact)
  and the deep path (methodology, detail, appendix). Decide which fact leads,
  what an executive can skip, and where the deep reader enters.
- **Drift guard — reports are NOT decks.** Business reports are an unowned
  medium this skill takes. **Slide/deck flows are NOT** — those stay in
  `presentation-narrative`. If the artifact is a slide sequence, write the brief
  and hand off. Stated here in-body to prevent authoring drift.

**Decision produced:** the ordered path and its per-step states (or the report's
reading order and executive-vs-deep split).

## 4. Information Architecture & Attention Hierarchy

Decide **what the audience sees first, next, and last, and why**:

- **Content ordering** — rank the content blocks by the audience's job, not by
  the org chart or the data model.
- **Attention hierarchy** — exactly one primary focus per view; everything else
  is secondary or tertiary. Decide the single thing the eye should land on first.
- **Progressive disclosure** — what is shown by default versus revealed on
  demand. Decide the default-visible set and the on-demand set; hiding the wrong
  thing is as costly as showing too much.

**Decision produced:** the ranked content order, the single primary focus per
view, and the default-visible vs on-demand split.

## 5. Buildable Specification

Turn the above into a spec precise enough to hand to a platform skill:

- **Components & states** — name each component and enumerate its states
  (default, hover/focus, active, disabled, loading, empty, error). A component
  without its states is not yet buildable.
- **Wireframe intent** — the layout regions and their relationship (what is
  fixed, what scrolls, what stacks on small screens), described as regions and
  priorities rather than pixel positions.
- **Ergonomics & ease-of-use** — apply Fitts- and Hick-level reasoning as
  decisions: make the primary action large and reachable; reduce the number of
  choices at each decision point; keep related controls together; specify
  keyboard and touch affordances (focus order, hit-target sizing intent, no
  hover-only actions on touch).

**Decision produced:** the component/state inventory, the layout-region
priorities, and the ergonomic choices (target prominence, choice count, input
modalities).

## 6. Semantic Token & Layout Brief (the Token Seam)

**This skill DECIDES token semantics; platform skills IMPLEMENT them. Design
decides, platform renders.** The brief names token **roles, scale intent, and
usage rules** in a medium-neutral, semantic vocabulary. It must contain **no
platform syntax** — name what a token is *for*, never how a framework spells it.
The platform owner (named in the handoff table) maps each role to its own
mechanism (a design-token preset layer, a custom-property layer, or utility
classes); that mapping is the platform's job, never written here.

Author the brief as roles and intent, for example (in words, not code):

- **Color roles** — name by role and emphasis: a primary-action role (the single
  highest-emphasis accent, used only for the one primary action per view); a
  neutral surface role and a raised-surface role; primary and muted text roles;
  and status roles (success, warning, danger). Give each a usage rule ("the
  primary-action role appears at most once per view").
- **Type scale** — a small ordered set by role (display, heading levels, body as
  the reading baseline, caption one step down and lower-emphasis). Decide the
  reading baseline and the steps around it, not point sizes.
- **Spacing rhythm** — one spacing scale named by role (tight inset, inset,
  stack gap, section gap) so rhythm is consistent; decide the roles, not the
  values.
- **Elevation / emphasis** — the ordered levels of prominence (flat, raised,
  overlay) and which content earns each.

**Layering note (medium-neutrality, answers the obvious objection).** The
audience, journey, and IA layers (§§2-4) are genuinely medium-neutral — the same
contract serves a web page, an app, or a report. The buildable-spec and token
layers (§§5-6) are produced **for the chosen medium against that medium's
constraints**: what is neutral is the *contract*, not the final spec. A token
brief for a report and for a web app share the same role vocabulary but resolve
to different platform mechanisms.

**Decision produced:** the named semantic token roles, their scale intent, and
per-role usage rules — handed to the platform owner to implement.

## 7. Acceptance Criteria

State the **measurable** checks the built artifact must pass — these feed
`ux-reviewer` for the post-build review:

- **Comprehension** — a member of the target audience can state the artifact's
  main point / find the primary action within a set time (e.g. the 5-second
  test) without help.
- **Task success** — the primary task completes without a dead end; every error
  state has a recovery path.
- **Engagement** — a medium-appropriate, measurable signal (report: the executive
  path answers the question on the first screen; app: the primary action is
  reachable within N interactions).
- **Accessibility** — keyboard-reachable primary flow, visible focus, sufficient
  contrast, labelled controls (WCAG AA as the floor).

**Decision produced:** the concrete pass/fail criteria the build is measured
against.

## 8. Medium Handoff Table

Once the contract is designed, hand off to the owner that implements it:

| Medium | Hand off to |
|---|---|
| Web page / site | `modern-frontend` (app/build) + `wordpress-developer` (CMS) |
| Store / commerce page | `ecommerce-growth` (funnel) + the WooCommerce skills (`woocommerce-developer`) |
| Slide deck | `presentation-narrative` |
| Business report — EXPERIENCE (layout, reading path, IA) | this skill |
| Business report — PROSE (the writing itself) | `content-writer` |
| Charts / data visualization | the `dataviz` skill — a **harness-provided plugin**, invoked by name (it is not a filesystem skill in this library, so this is a plugin route, not a cross-link) |
| Trading application surfaces | `trading-dashboard-ux` |
| Persuasion / conversion copy | `conversion-psychology` |
| Post-build interface review | `ux-reviewer` |

## 9. Anti-Patterns

| Anti-Pattern | Why it fails | Instead |
|---|---|---|
| A section that is only principles / a generic checklist | Produces nothing buildable — violates this skill's kill criterion | Every section must end in a named decision; delete or route the rest |
| Re-deriving an owned journey (deck flow, commerce funnel, persuasion copy) | Duplicates and drifts from the owner | Write the upstream brief and hand off per §8 |
| Emotion adjectives with no design decision ("make it feel premium") | Un-actionable; the builder cannot act on a mood | Translate the feeling into a concrete signal (§2) and a token/layout decision |
| Designing for an "average user" | No real person is average; the design fits no one | Model named audience types per §2 |
| Writing platform syntax in the token brief | Collapses the design/implement seam; ties the contract to one framework | Name token roles and intent only; let the platform skill implement (§6) |
| Skipping error / empty / loading states | The spec is unbuildable and fails in the real world | Enumerate every state in §5 |
