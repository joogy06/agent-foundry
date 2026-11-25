# Forge reference — bob handoff

Checklist step 9 — previous: step 8d, the hard rules checkpoint; next: step 10, wait for bob, then step 11, final integration.
When this file is read, return to the SKILL.md checklist.

## Contents

- Phase 2: Implementation via bob
- Step 5: Spawn bob: the spawn brief, the contract-map block and its N/A line, reasoning effort, what to include in bob's prompt
- Execution Method Selection

## Phase 2: Implementation via bob

After the user approves the design, delegate execution to **bob** — the autonomous executor agent.

Bob handles everything: work package decomposition, team orchestration, monitoring, verification, and delivery. Forge stays focused on design.

### Step 5: Spawn bob

<!-- spawn-brief.v1 id=forge.bob -->
```
Agent(name: "bob", subagent_type: "bob", prompt: """
Execute this approved design.

Design document: [PATH_TO_DESIGN_DOC]
Project root: [PROJECT_DIR]

Goal: [OUTCOME, FOR WHOM, WHY — one or two sentences]
Non-goals: [the design's out-of-scope list; what must not change]
Open questions: if one would lead to materially different work, return it ONCE as needs.kind:
  clarification BEFORE your first mutation; otherwise decide, note the assumption, proceed.
  [Answers: ... and clarification_used: true — on a respawn after a clarification; forge records the
  allowance in the cycle directory, bob writes nothing when it asks]
Done when: the design's `## Done when` DW-1…DW-n hold (WPs `covers` them; integration DWs at finalize).
Stop when: done-when holds, or you are blocked (state the blocker).
Brief block: skills/_meta/spawn-brief.md

Contract map (required if design introduces components):
- Map:        progress/contract-map.yaml
- Signature:  progress/contract-map.yaml.sig
- Session id: .forge/session-id (inherited)
- Session key: .forge/session.key (inherited, 0600)

Bob MUST run gates.py G1 against the map before Step 1 completes. If G1 fails,
HALT and report to forge. Do NOT infer or fabricate a contract map.

Shared context:
- Architecture: PROJECT.md at [path]
- Component docs: [relevant COMPONENT.md paths]
- Coding conventions: [any style guide or conventions]
- Existing interfaces to respect: [if any]

The design has been reviewed and approved by the user. Execute it as specified.
""")
```

The contract-map block is OMITTED only for designs that do not introduce components (pure refactors, single-file bugfixes). In that case, include an explicit line: `Contract map: N/A (no new components in this change) — <reason>.` **This `N/A` line is ADVISORY only** (S042 / #115): bob does NOT trust it: bob's mandatory `G_CLASSIFY` pre-flight independently re-derives and corroborates the classification, and authorizes skipping Step 1.5 SOLELY on a green (`exit 0`) gate. A false N/A is caught (exit 2 BLOCK with named signals).

**Reasoning effort (#311 phase 1).** The Agent-tool spawn above has no effort parameter, so it runs at `agents/bob.md`'s static frontmatter default (`effort: medium`). When the main loop executes a bob plan stage by stage, it dispatches each work-package stage as the one-stage workflow `bob-stage` at the effort the WP's `complexity` gives (S `low`, M `medium`, L `high`, one step up for a sensitive file), and it records one dispatch row before and one outcome row after each stage through `skills/_meta/effort_policy.py`. The exact sequence is in `agents/bob.md`, "Per-WP reasoning effort — the one-stage dispatch". Protected review seats never take this path: they run at `seat_model.py effort --role R --provider claude` (`xhigh`), passed explicitly.

**What to include in bob's prompt:**
- Path to the design doc (bob reads it himself)
- **Path to `.forge/classification.json`** (the Step 8a.0 classification artifact — bob's `G_CLASSIFY` pre-flight corroborates it)
- Architecture docs: PROJECT.md path + relevant COMPONENT.md paths
- Coding conventions (if any)
- Existing interface contracts to respect
- Performance requirements (budgets, concurrency targets from design doc)
- Any user-specified constraints (e.g., "don't touch the database schema"), each keeping its label from the design doc: `owner-stated: "<quote>"` or `lead-inferred` (#345; a copied constraint never loses its label)

---

## Execution Method Selection

After the user approves the spec, spawn **bob** for execution. Bob handles all complexity levels autonomously — he decides team count and orchestration approach based on the work packages he constructs.

| Design Complexity | Signals | What Bob Does |
|-------------------|---------|---------------|
| **Simple** | Single component, 1-2 files | 1-2 WPs, direct execution (no agent-teams) |
| **Medium** | 2-3 components, multiple files | 4-6 WPs, delegates to agent-teams |
| **Complex** | Cross-layer, multiple domains | 7+ WPs, full agent-teams orchestration |

**Bob is the sole executor.** Do not route to superpowers plugin skills for execution — they are not aware of custom skills (forge, agent-teams, team-manager, domain skills, etc.) and cannot assign them to specialists.

**Design docs always saved to `docs/plans/`**.
