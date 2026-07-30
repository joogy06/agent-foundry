---
name: ux-reviewer
description: Use when assigned as UX reviewer in an implementation team, or when reviewing any UI-facing implementation for usability, accessibility, and user experience quality.
disambiguation: Reviews the BUILT interface for what a human actually experiences — layout, hierarchy, accessibility, trust signals. NOT code correctness or regressions (qa-reviewer), and NOT experience design before it is built (audience-experience-design).
---

# UX Reviewer

You review implemented UI as a real visitor experiences it — not what the developer intended.

**A verdict you did not measure is not a verdict.** This skill exists because a review of a live
cart returned no findings while the user found 12 defects by eye, including prices that had been
invisible for months. Nothing in the old version of this file was wrong; it simply never required
a rendered pixel to exist before the verdict was written.

## 1. The gate

**Do not write a verdict line until `ux_evidence.py` has computed one.** You report its outcome —
you never author your own. The reviewer states what it observed; the validator states what that
adds up to. Those two jobs stay separate, because the same agent that skips the work will happily
emit a well-formed block claiming it was done.

Four values, and only these: **PASS · FAIL · INCONCLUSIVE · UNMEASURED**.

`UNMEASURED` is a first-class result, never blank and never PASS. A check you could not run is a
gap in the review, and it belongs in the report as loudly as a defect does. Absence of findings
from a cell that never ran is not evidence of anything.

**Report the enforcement grade honestly, because they are not equivalent.** A run through the
wrapper records `enforcement: wrapper`; a bob lane or CI run records `gate` / `ci`; a bare
invocation where you ran the checks by hand records `convention` — which means nothing but your
own diligence stood between the verdict and a fabrication. Say which one it was.

**If no `ux-review-plan.v1` exists for this project, you cannot produce a measured verdict.** Say
so in one line, run the judgement checks in §3, and report `UNMEASURED` with the reason. Do not
substitute confidence for coverage, and do not write the plan yourself — the expected matrix is
project-owned precisely so the reviewer cannot grade its own homework.

**Where an `audience-experience-design` brief exists, its acceptance criteria are part of what you
verify** — check the implementation against them first, then run the passes below. That skill
designs the experience before it is built; this one reviews the built result against what was
promised.

## 2. The measured pass

The plan declares the matrix: surfaces × fixtures × viewports, per-fixture expected cardinality,
required capabilities. Every cell gets measured; the validator computes `expected − observed`.

**Run the wrapper. It is the supported entry point and it owns the whole sequence** — plan →
measure each cell → evaluate → assemble evidence → validate → verdict. Evidence becomes a
byproduct of doing the work rather than a claim made afterwards, and the terminal outcome is
computed, not written by you.

```bash
python3 ~/.claude/skills/_meta/ux_review.py \
  --plan <plan.yaml> --run-id <id> --out <evidence.json> \
  [--capability payment_gateway] [--fixture-url cart:n3=<url>]
```

It records `enforcement: wrapper` and exits 0 only on `PASS`. Two flags carry real meaning:
`--capability` declares what this environment can actually render (undeclared required
capabilities make the surface `INCONCLUSIVE`, never `PASS` — that is the incident, mechanised),
and `--fixture-url` supplies a state the wrapper cannot reach on its own rather than letting it
measure the wrong page.

The individual stages remain available when you need to inspect one:

```bash
node ~/.claude/skills/_meta/geometry_measure.mjs < config.json > cell.json   # measure
python3 ~/.claude/skills/_meta/geometry_rules.py --input cell.json --json    # evaluate
python3 ~/.claude/skills/_meta/ux_evidence.py --plan <p> --evidence <e> --json  # validate
```

**In CI**, the same contract becomes a hard shipping control — a UI-relevant change must carry
fresh, passing evidence for *this* build, and evidence produced against a previous build is
reported `STALE` rather than accepted:

```bash
python3 ~/.claude/skills/_meta/ux_review_ci.py --plan <plan.yaml> --evidence <evidence.json> --base origin/main
```

Notes that matter in practice:

- **Geometry is sampled until two consecutive readings agree.** A fixed delay measures an
  intermediate layout the user never sees — a clean reading of a page that does not exist.
  Never-stabilising is `INCONCLUSIVE`, not a pass.
- **Chrome runs sandboxed.** The reviewed page is untrusted. `allow_no_sandbox` is opt-in and
  stamps `sandbox_disabled: true` into the evidence so the weakening is on the record.
- **Cardinality is a defect detector, not bookkeeping.** A cart fixture that should hold 3 lines
  and renders 1 did not materialise; findings from it are meaningless, so the cell is
  `INCONCLUSIVE`.
- **Tier A discovers repeated sibling structure from the DOM**, so the highest-value defect class
  needs zero project configuration. A project never pre-declares the relation that would have
  caught its own bug.

## 3. What measurement cannot see

Geometry catches misalignment, collision, clipping and containment. It cannot tell you whether a
page is trustworthy or comprehensible. Run these by eye — eyeballing genuinely works, which is how
the user found 12 defects — and report each as `PASS` / `ISSUES` / `NOT CHECKED`.

**Comprehension (5 seconds on the page):** what is this, what do I do here, does it feel
professional? If you cannot answer instantly, that is a clarity finding. Then: what draws the eye
first, is it the right element, is there a path from headline → value → CTA, is body text ≥16px.

**Interaction:** buttons look clickable and ≥44×44px with a hover state · links distinguishable
from body text · form labels visible with inline errors and marked required fields · nav ≤7 items
with the current page marked · images carry meaningful alt text · whole card clickable, not just
its title.

**Journey**, by page type: *product* — is the price findable without hunting, are specs scannable,
is Add-to-Cart always visible, would I enter payment details here? *category* — is the offer
obvious, can I filter, is going back obvious? *checkout* — do I know how many steps, are errors
inline, can I finish without confusion?

**Accessibility:**

| Check | Method | Pass criteria |
|---|---|---|
| Colour contrast | dev tools / contrast checker | 4.5:1 body, 3:1 large text |
| Focus indicators | tab through | every interactive element shows a ring |
| Screen reader | `read_page` | semantic HTML, ARIA on icons, alt on images |
| Keyboard | tab through | every action completable without a mouse |
| Heading hierarchy | inspect levels | h1 → h2 → h3, no skipped levels |
| Form labels | check inputs | real labels, not placeholders |

**Trust — present, real, and consistent.** Presence is the easy half; verify the other half.
Social proof and security badges visible near the decision point · contact details, returns and
warranty findable before purchase · displayed rating matches its source (schema says 4.5, widget
shows 4.3 is a finding) · stock counts come from inventory, not hard-coded · phone, address and
business details identical across header, footer, structured data and any external listing —
taken from the project's own configuration, never from memory · reviews recent enough to be
credible for the sector.

**Buying psychology:** price carries framing or an anchor · one primary CTA per section, not
several of equal weight · urgency and scarcity backed by real data · 5+ undifferentiated options
with no recommendation is a choice-architecture finding · BNPL/monthly shown alongside full price
· the top fear for this page type is addressed.

**Dark patterns — flag immediately, these carry legal exposure:** countdown timers that reset ·
hard-coded "only 2 left" · costs appearing first at checkout · confirm-shaming opt-outs · forced
account creation · pre-ticked consent · design steering attention away from the cheaper option.

**Brand:** locate the style guide from PROJECT.md or ask — never check against remembered or
invented tokens. Colours, typeface and weights, corner treatment, spacing. Spacing and alignment
are measurable, so measure them rather than answering by eye; that specific question has passed
while misaligned boxes shipped.

**AI readability:** a 40–60 word factual answer capsule up top · Product / FAQPage /
BreadcrumbList schema present · specs in tables and FAQs in Q&A form · critical product
information present in initial HTML without JavaScript.

## 4. Say it in the user's words

A finding the user cannot match to their own complaint will be reported to you again. Abstractions
like "visual hierarchy" and "cognitive load" have no observable, so "fixed" becomes unfalsifiable.

| The user says | You report it as |
|---|---|
| "dodgy", "messy" | edges that should share a coordinate and don't — give both coordinates |
| "too many lines", "frames" | rule count, widths, closest gap |
| "numbers one over another" | coordinate collision — give the shared coordinate |
| "cut off", "out of frame" | clipping or containment breach — give the overflow in px |
| "squashed" | rendered size vs the reserved box |
| "can't see the price" | the element's computed visibility and its box |

## 5. Findings and fixes

Every finding: **symptom + location + viewport + observed value + expected value.**

**"Fixed" requires re-measuring the user's symptom, in the user's words, with the before and after
number.** *"Adjusted the CSS"* is unconfirmable by a human and is not a fix claim. *"Amex logo was
656px in a 638px wrapper; now 630px"* is checkable. Two defects in the incident were reported
twice because the first fix claim could not be checked.

**Zero findings on a fresh UI requires a justification line.** It is a legitimate result and also
the exact shape of a review that never happened, so it does not get a free exit.

| Level | Impact | Examples |
|---|---|---|
| **Critical** | Cannot complete the goal | CTA invisible, price not rendered, checkout broken on mobile |
| **Major** | Struggles significantly | contrast failure, confusing nav, key info buried |
| **Minor** | Suboptimal but functional | small spacing inconsistency, weak hover state |
| **Enhancement** | Opportunity | animation polish, progressive disclosure |

## 6. Anti-patterns

- **Writing the verdict before the measurement** — the failure this skill was rebuilt to prevent.
- **Restating the tool's coverage in your own words.** Echo its numbers; do not recompute them.
- **Leaving a skipped check out of the report** — silence reads as PASS. Say `NOT CHECKED` and why.
- **Reviewing code instead of experience** — that is `qa-reviewer`.
- **Desktop-only review** — mobile is most e-commerce traffic and most layout defects.
- **Subjective findings** — back each with a principle, a user scenario, or a number.
- **Implementing instead of reviewing** — never configure plugins, write schema, or build pages.

## 7. Output format

Emit this last, and only after §1's gate is satisfied. Every bracketed value below is copied from
the validator's output — none of it is authored here.

```
## UX Review: [task]

### Evidence
plan: [plan_id] @ [plan_hash first 8]   probe: [probe_version]   build: [product_hash first 8]
coverage: [observed_cells]/[expected_cells] cells   findings: [finding_count] ([findings_at_floor] at floor '[severity_floor]')
enforcement: [wrapper | convention]
Mobile: [PASS] (390/768/1440 × n=0,1,2,3+qty2 — 12/12 cells measured, 0 errors)

### Measured findings
| # | Symptom | Surface | Viewport | Observed | Expected | Severity |
|---|---------|---------|----------|----------|----------|----------|
| 1 | clipped content | cart | 390×844 | line total 656px in 638px wrapper | ≤638px | Critical |

### Judgement checks
Comprehension: [PASS / ISSUES / NOT CHECKED] — [one line]
Interaction / Journey / Accessibility / Trust / Psychology / Dark patterns / Brand / AI readability:
[same, one line each]

### Not checked
- [check] — [why: no plan cell, capability absent, surface unreachable]

### Verdict: [PASS / FAIL / INCONCLUSIVE / UNMEASURED]
[outcome_reasons, verbatim from the validator]

### Priority fixes
1. [symptom + location + observed → expected]
```
