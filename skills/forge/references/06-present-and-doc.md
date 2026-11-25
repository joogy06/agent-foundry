# Forge reference — present the design and write the doc

Checklist steps 2, 7, 7b and 8 — previous: step 6, design exploration (step 2 comes earlier, right after step 1); next: step 8a, the contract map.
When this file is read, return to the SKILL.md checklist.

The `.forge/size` block that closes the design-doc step is in SKILL.md, under "Step 4: Write Design Doc". "After convergence" refers to `references/04-agy-and-converge.md`.

## Contents

- Step 3: Present Design — checklist step 7
- Write Design Doc: what the doc must contain — checklist step 8
- Visual Companion — checklist step 2
- UI designs — design-skeleton freeze (Step 2.5) — checklist step 7b

### Step 3: Present Design

After convergence:
- Present design scaled to complexity: Simple/Medium present the whole design and ask for one approval; Complex presents section by section and asks for approval of each
- Always present the `## Done when` DWs; they are what every reviewer will rule against
- Always present the `**Purpose:**` line and the constraint labels; a `lead-inferred` one is the owner's to correct here
- **An item put to the owner states its effect on the Purpose (#345).** If the lead has not evaluated it, it says "not evaluated" and gives no recommendation. A default "I'd remove" is not allowed
- Cover: architecture, components, data flow, error handling, testing approach, performance considerations
- **Always include a UX section** for UI-facing work
- **If `came_from_avengers`**: surface the `avengers_brief.dissent[]` entries **verbatim** in the presentation — attributed to the seat, with each entry's trip-wire. Do NOT summarize or drop them; the user judges the design with the deliberation's dissent in view (mirrors the founder minority-report surfacing).
- Be ready to revise based on user feedback

### Write Design Doc: what the doc must contain

- Save to `docs/plans/YYYY-MM-DD-<topic>-design.md`
- **Required section `## Done when`** (#313): numbered, checkable criteria `DW-1…DW-n`, filled from the Step 3 success criteria. A criterion that spans WPs is marked `(integration)` and is verified at finalize, never by one WP. It is frozen with the design (plan_hash / signed-map bindings cover it): bob writes WP criteria but never changes a DW
- **Required `**Purpose:**` line at the top** (#345): the outcome the cycle exists for, one sentence. It quotes the owner, or is labelled `lead-inferred` and is then challengeable like any other inferred constraint
- **Every constraint is labelled** (#345): `owner-stated: "<quote>"` or `lead-inferred`. A constraint that adds to what the owner said is `lead-inferred` even when it seems implied. **The label travels:** wherever a constraint is copied (a bob brief, a reviewer brief, project memory) it keeps its label
- Existing docs are not rewritten retroactively. Where a review runs with no design doc (a standalone bob run, direct edits), the reviewer brief says `Purpose: none stated`; goal-fit is skipped and the report says so
- Update `history.md` and `index.md`
- Shut down design exploration team (if created)

---

## Visual Companion

The local `visual-companion` skill provides a server-less browser-based companion for showing mockups, diagrams, and visual options during design. It writes self-contained HTML files to `/tmp/visual-companion-<session>/` that the user opens in their browser, with no server or client-side state.

**When to offer:** After exploring project context, if upcoming questions will involve visual content (mockups, layouts, diagrams, architecture), offer it once:

> "Some of what we're working on might be easier to explain if I can show it to you in a web browser — mockups, diagrams, comparisons. Want to try the visual companion? (I'll write HTML files to /tmp/ that you open in your browser.)"

**This offer MUST be its own message.** Do not combine with clarifying questions. If they accept, invoke the `visual-companion` skill — read its SKILL.md for the protocol and templates.

**Per-question decision:** Even after acceptance, decide FOR EACH QUESTION whether to use browser or terminal. Use browser for visual content (mockups, wireframes, layout comparisons). Use terminal for text content (requirements, tradeoffs, scope decisions).

### UI designs — design-skeleton freeze (Step 2.5)

For UI-facing designs — the design output includes an HTML mockup, CSS file, new user-facing screen, or new interactive element, and `ui_scope` is not `none` — the approved mockup MUST be frozen into a signed design-skeleton. This runs AFTER the user approves the HTML mockup (checklist Step 7b) and BEFORE Step 8a contract-map signing. This is the design-phase freeze that the `visual-architect` skill refers to as "forge Step 2.5".

1. **Invoke `skeleton-extractor`** — transforms the approved HTML mockup into a draft `design-skeleton.v1` YAML (`.design-ledger/skeletons/<screen>.draft.yaml`): puppeteer-core DOM walk at 3 breakpoints, bboxes + computed styles back-resolved to declared tokens + wired interaction handlers. The draft is UNSIGNED — `interactions[].binds_to` may be `null`, and hardcoded CSS values the extractor could not back-resolve land in `unresolved_tokens_report`.
2. **User reviews the draft** — the user supplies a `capability://...` URI (or `visual_only`) for every null `binds_to`, and explicitly approves or rejects every unresolved token. Capture these as a user-edits YAML (schema in `visual-architect/SKILL.md`).
3. **Invoke `visual-architect`** (`scripts/freeze.py freeze`) — validates every `binds_to: capability://...` URI resolves via `uri.exists` (first failure → challenge filed, exit 1); enforces **D2 strict** on unresolved tokens (each MUST be explicitly user-approved into the tokens block or explicitly rejected — no silent skip; otherwise exit 2); HMAC-signs the payload with `.forge/session.key` (file bytes including trailing newline); atomically two-file writes `.design-ledger/skeletons/index.yaml` + `<screen>.yaml` via `trusted_runner.bundle_write`; emits a `skeleton_frozen` transition request to `.ledger/requests/` — **bob applies it (CB4: bob is sole ledger writer; forge/visual-architect write nothing to `.ledger/claims/` or `progress/integration-ledger.md`)**.

**Why this cannot be skipped:** bob's UI-INTEGRATED → UI-VERIFIED transition verifies the built product against the frozen skeleton — `visual-arbiter` measures bbox / computed styles / interaction wiring against it, and both the `G_XR` gate and the visual-verdict 8-field tuple require `skeleton_hash`. No frozen skeleton means no `skeleton_hash`, and UI-VERIFIED is unreachable for that screen.

Read `skeleton-extractor/SKILL.md` and `visual-architect/SKILL.md` for invocation commands, exit codes, and the user-edits schema before invoking either.
