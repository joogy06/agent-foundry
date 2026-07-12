# avengers — Reuse Map (for alf)

**Purpose (design §13.5 — upstream drift / blast-radius control).** This file tells
`alf` (the evolution / drift-audit agent) which files avengers REUSES or DEPENDS
ON that it does not own, and what breaks if those files change. When alf reviews
any file listed under "Upstream dependencies" below, it should treat avengers as a
downstream dependent and check the coupling contract before recommending a change.

avengers is a SIBLING of forge and of adversarial-team-brainstorm (ATB), not a
subcomponent. It owns its own tree (`skills/avengers/`) and reuses shared
machinery through explicit, versioned contracts — never by forking.

## Upstream dependencies (files avengers does NOT own but couples to)

| Upstream file | What avengers reuses | Coupling contract | Blast radius if it changes |
|---|---|---|---|
| `skills/adversarial-team-brainstorm/references/arbiter-synthesis.md` | The arbiter synthesis machinery, via the `arbiter_mode` top-level switch (WP-4). avengers uses `arbiter_mode: decision \| deliverable \| forge_brief`. | `arbiter_mode` is the top-level switch; `arbiter_mode: ideas` (default) preserves ATB's legacy `output_class` sub-switch verbatim. The three non-`ideas` modes are avengers' consumers. | If `arbiter_mode` is removed/renamed or the non-`ideas` schema changes, avengers' ARBITER phase and `forge_brief`/`decision` outputs break. Regression fixtures: `skills/adversarial-team-brainstorm/tests/` (semantic-equivalence for all four `output_class` values + caller sweep). |
| `skills/forge/SKILL.md` (Step 3 intake, Step 6 recursion guard, Step 7 dissent surfacing) | The `came_from_avengers: true` + `avengers_brief_path` intake block (WP-4). This is the build path exit. | The `avengers_brief` schema in [`outcome-routing.md`](outcome-routing.md) MUST match the forge Step 3 per-field intake mapping EXACTLY. `contract_map_signed`/`bob_ready` are mechanically always-false. | If the forge intake field names/order change, avengers' `forge_brief` route emits an unreadable brief. Lock: `skills/forge/tests/test_avengers_intake.py` + `fixtures/avengers_intake_mapping.json`. |
| `skills/visual-companion/SKILL.md` | The `show-comparison` operation, auto-invoked by the `website-ux` profile (visual track ON). | avengers' `website-ux` profile overrides visual-companion's offer-first default with `visual.auto: true`. Documented adapter note in visual-companion SKILL.md. | If `show-comparison` is renamed/removed, the `website-ux` visual track breaks. The adapter note in visual-companion SKILL.md is the tripwire. |
| `skills/cross-cli-deliberation/` | The anti-sycophancy protocol (Gate-1 null-hypothesis ballots; burden-of-evidence on the change-claim) inherited into `CONVERGE` for ratification families. | Behavioral inheritance (prose), not a code import. Ratification profiles (`coding-ratification`, `research-synthesis`) file Gate-1 ballots. | If the cross-cli-deliberation ballot semantics change, ratification convergence should be reviewed for consistency (soft coupling). |
| `codex-orchestration` skill + guard stacks | The pinned external-CLI guard stacks (codex `--ephemeral -s read-only` per-call effort pins; agy `--sandbox` flags-before-`-p`). | Resolver-injected invariants in `convene.py` (`CODEX_TIMEOUTS`, `SEED_LATENCY_S`, `RETIRED_EFFORT_TIERS`). The tier `high` is RETIRED and rejected. | If the effort-tier policy or CLI flags change (e.g. `high` un-retired, `--ephemeral` renamed), update `convene.py` constants AND the guard-stack HARD-RULE in SKILL.md. |
| `smart-config` skill | Advisory model-tier resolution for Claude seat spawns (`effort: default`). | Advisory only; fail-open (a broken policy never blocks a convene). | Low — advisory; a change degrades tier selection, never correctness. |

## Version pins (drift tripwires)

These are the versions the design (§2/§6) was validated against. alf should flag a
review if any drifts materially:

- `claude-code 2.1.207`
- `codex-cli 0.144.1` (gpt-5.6-sol)
- `agy 1.1.1`
- Python: stdlib only + **PyYAML** (explicitly owned) for human-authored YAML;
  ALL machine/runtime state is stdlib JSON.

## Contract-hash tripwires

- The `avengers_brief` schema (outcome-routing.md) ↔ forge Step 3 intake: locked by
  `skills/forge/tests/fixtures/avengers_intake_mapping.json`. A drift breaks the
  build path silently unless the fixture test runs.
- The `arbiter_mode` switch ↔ ATB legacy `output_class`: locked by the ATB
  regression fixtures (`arbiter_mode_contract.sha256` + `output_class_contract.json`).

## What avengers OWNS (not a reuse dependency; here for completeness)

`skills/avengers/**` — SKILL.md, `scripts/{kernel,convene,seat_prompt,memory_writeback}.py`,
`schemas/{session-plan,memory-record}.v1.schema.json`, `profiles/*.yaml`,
`roster/*.yaml`, `references/*.md`, `tests/**`. Member memory + trusted instruction
text live under `~/.claude/` (never repo-local). alf may review these directly as
avengers-owned; the table above is only for files avengers does NOT own.

## v1 out-of-scope (design §14 — do NOT flag as "missing")

Global member-memory tier (no loader branch by design); `vindicated/refuted`
calibration; mid-phase interjections; repo-local config overrides; roster-editing
UX; provider SDK/MCP abstraction; embeddings/vector retrieval. These are
design-for-not-build; their absence is intentional, not drift.
