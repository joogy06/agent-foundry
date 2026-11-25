---
name: forge
description: "Structured design before code: architecture decisions, new features, system design, refactoring plans. Explores and challenges approaches, then hands an approved design to bob. Use when an idea or change needs exploration before implementation."
---

# Forge — Ideas Into Designs & Implementation

## Overview

Turn ideas into fully formed designs through collaborative dialogue, then orchestrate implementation via **bob** (autonomous executor agent). Uses a two-phase approach: **Design Team** explores approaches with dual challengers (Claude + Codex) and UX advocate, then **bob** handles all execution — work package decomposition, team orchestration via agent-teams, verification, and delivery.

Every design and implementation decision must account for real human behaviour — how end users actually see, navigate, and interact with the product.

<HARD-RULE>
**Multi-Model Second Opinion**: For MEDIUM and COMPLEX tasks, run BOTH Codex (pinned per role through `skills/_meta/seat_model.py`: the codex std tier for the consultancy seats, codex TOP kept in reserve for escalation and complex review) AND Antigravity CLI (`agy`, via `agy --sandbox --mode plan $AGY_MODEL -p`, model pinned the same way) in parallel alongside Claude agents — three models catch what two miss. For SIMPLE tasks, external models are optional. If agy is unavailable, fall back gracefully and note the gap explicitly. If codex cannot serve a codex seat (the budget gate refuses it, the quota is exhausted, the CLI is missing, no eligible model is listed, or the call fails twice — after a capability failure on the std tier, the one TOP retry comes first), a fresh-context Claude main-tier agent serves that seat with the same brief — never a codex std or support model, which draw the same plan quota — and the round is recorded as Claude + Google (provider gap: OpenAI). A codex failure the classifier calls a gap is still a gap: note it explicitly.
</HARD-RULE>

<HARD-RULE>
**Do NOT invoke `superpowers:brainstorming`**. Forge is the canonical design workflow. Forge has its own internal design exploration team (approach agents, challengers, Codex). The superpowers brainstorming skill is a separate, overlapping workflow that lacks Codex integration, multi-agent teams, and custom skill awareness. If you feel tempted to invoke brainstorming, you are already inside the right workflow — continue with forge.
</HARD-RULE>

<HARD-RULE>
**Codex Escalation**: When Claude agents are stuck on a problem (2+ failed attempts, circular reasoning, or no clear solution), delegate the problem to Codex for a fresh perspective before asking the user.
</HARD-RULE>

<HARD-RULE>
**Contract Map Required**: For any design that introduces components (new services, modules, endpoints, integration points), a valid signed `progress/contract-map.yaml` MUST exist before spawning bob. This is enforced mechanically by bob's G1 subprocess check, not by prose.

- Forge invokes the `component-contract-mapping` skill at Step 8a to produce the map.
- Forge signs it with HMAC-SHA256 using `.forge/session.key` (per spec section 7.4).
- The signed payload MUST include `map_hash`, `map_revision`, `forge_session_id`, and `signed_at`.
- Missing or unsigned map = refuse to spawn bob. No workarounds. No "we'll add it later".
- Pure refactoring / single-file bugfixes with no new components are exempt.
</HARD-RULE>

<HARD-RULE>
**Multi-subsystem requests emit handoff docs, not inline decomposition** (S038 Batch G, 2026-05-25). When forge Step 1 detects that a request describes multiple independent subsystems (existing "Large Project Decomposition" pattern), instead of inline-spawning sub-forge cycles (depth+1), forge MUST invoke the `handoff` skill to emit one `/tmp/handoff-<sub>-<date>-<uuid>.md` per decomposed sub-project. Each handoff doc records the slice of context relevant to that sub-project and a "Suggested skills: forge (MEDIUM cycle on this sub)" directive. The user picks which sub-project to start first; forge does NOT recurse into all of them. Recursion limit (depth≥3 REFUSE per existing rule) remains in effect — handoff is the new exit, not a way around the limit.
</HARD-RULE>

<HARD-GATE>
Do NOT write any code, scaffold any project, or take any implementation action until:
1. A design has been presented and the user has approved it
2. Bob has been spawned with the approved design doc
This applies to EVERY project regardless of perceived simplicity.
</HARD-GATE>

## How to use this skill

This file is the entry point: the rules above, the checklist, and three blocks that fail silently when skipped. Each step's detail is in one file under `references/`, named on that step's checklist line.

- Read the named reference in full before the step. Do not work from memory of an earlier cycle.
- After a context compaction, re-read this file and the current step's reference. Only the first part of this file is re-attached (about 20,000 bytes): the Step 1 block starts inside it, and the Step 4 and Step 6 blocks sit after it.
- Every reference is named in this file. Where kept text says "see" a section or "below" and the section is not in this file, the index says which reference holds it.
- Spawned with `mode=amendment`: skip the checklist, read `references/amendment.md` and follow only that.

### Reference index

- `references/01-intake.md` — steps 1, 3, 5: Skill Gap Detection, what the lead asks in Step 1 (performance, runtime and security branches), Large Project Decomposition and the Recursion Limit.
- `references/02-design-team.md` — step 6: Step 6A fast path, Step 6B and the avengers recursion guard, Step 2 Approach Exploration (team, phases, model per spawn; the approach, UX and Claude-challenger briefs).
- `references/03-codex-seats.md` — step 6, and the codex reviewer seat of step 11: Spawning Codex Agents (the guarded seat call, admit, classify, substitution and quota-wait rules, the challenger and approach-explorer briefs, the research lookup).
- `references/04-agy-and-converge.md` — step 6: the agy analyst (stdin, sandbox, model and call-cap rules) and Converging Triple-Model Findings.
- `references/05-escalation.md` — any step where Claude is stuck: Codex Escalation and Escalation Termination. Read `references/03-codex-seats.md` with it for the seat rules it cites.
- `references/06-present-and-doc.md` — steps 2, 7, 7b, 8: Step 3 Present Design, the design doc's contents, Visual Companion, the design-skeleton freeze (Step 2.5).
- `references/07-contract-map.md` — step 8a: Contract Map Generation, Steps 8a.0 to 8a.4.
- `references/08-spec-review.md` — steps 8b, 8c, and the Stage 1.5 verification that steps 6 and 11 run: Spec Review (Stage 1, Stage 1.5, the `ratify-design` fast path, Stage 2).
- `references/09-bob-handoff.md` — step 9: Phase 2, Step 5 Spawn bob, Execution Method Selection.
- `references/10-close-out.md` — step 11: Collect Results (report template, spot-check), the advisory code review and its fix loop (D21).
- `references/principles.md` — steps 6, 7: UX Principles Reference, Key Principles.
- `references/amendment.md` — out of band (bob spawns forge with `mode=amendment`): Amendment Mode, the full protocol.
- `references/external-finding-verification.md` — step 8b (Stage 1.5) and the step 11 fix loop: how to verify a finding an external model raised.
- `superpowers-tracked.md` — not a step: the superpowers plugin version tracker, read when it updates.

---

## Checklist

You MUST create a task for each item and complete in order:

1. **Explore project context** — read PROJECT.md (architecture map, components, integration edges) and relevant COMPONENT.md files FIRST. Check history.md (if >400 lines, head+tail only — older context lives in `history/INDEX.md`), session_control.md. Invoke `project-documentation` to ensure all docs exist (creates PROJECT.md + COMPONENT.md stubs if missing). **If a wiki exists for the project** (CWD contains `.wiki/` OR `~/.wiki-registry.yaml` lists this project), use Tier 1 access: `Grep` the wiki's `wiki/` directory for prior decisions, research, and ADRs on the task topic. Include any findings in `shared_context` as a "Prior Wiki Knowledge" section so design agents can reference existing decisions. **Also run `python3 ~/.claude/skills/_meta/scan_hard_rules.py`** (plain mode) to scan CLAUDE.md (global + project-local) for hard-rule directives and diff against `~/.claude/skills/_meta/hard-rules-checklist.md`. If any are flagged as potentially missing, surface them to the user with a 1-line summary and ask: "add to checklist / wire into a skill / apply ad-hoc / ignore?" — do NOT silently skip. This is idempotent with the SessionStart hook but catches cases where forge is invoked from a subagent, after `cd`, or in sessions where the hook didn't run.

   **Dependency currency check (advisory only, MEDIUM+ tasks):** if any manifest is present at the project root (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `Gemfile`, `pom.xml`), invoke `dep-currency-check` to populate `shared_context.dependency_health`. Run it advisory-only — forge Step 1 NEVER fails on its exit code; blocking enforcement lives at bob's WP boundary, the `G_DEP_CURRENCY` gate, and pre-commit hooks. Skip for TRIVIAL/SIMPLE tasks (latency budget). Pattern:
   ```bash
   if find "$PWD" -maxdepth 4 \( -name 'pyproject.toml' -o -name 'package.json' -o -name 'Cargo.toml' -o -name 'go.mod' -o -name 'Gemfile' -o -name 'pom.xml' \) 2>/dev/null | grep -q .; then
     PYTHONPATH="$HOME/.claude/skills/dep-currency-check" python3 -m dep_currency_check "$PWD" \
       --format json --severity high --quiet \
       --output "/tmp/forge-dep-currency-${FORGE_SESSION_ID:-default}.json" 2>&1 || true
   fi
   ```
   The `|| true` is mandatory — Step 1 MUST NOT fail. Read the JSON if present, include `dependency_health` in shared_context. See `~/.claude/skills/dep-currency-check/references/integration-forge.md` for the full payload shape + skip rules.
   Read references/01-intake.md before this step. Run the cycle-start block under "Step 1: Understanding (Lead Only)" below first.
2. **Offer visual companion** (if topic involves visual questions) — see Visual Companion section. This is its own message, not combined with clarifying questions.
   Read references/06-present-and-doc.md before this step.
3. **Ask clarifying questions, scaled by ask size** (CLAUDE.md "Ask size sets the contract") — Simple: restate the ask and its done-when in one line, and ask zero or one material question; Medium/Complex: ONE bounded round, material questions only (answers that would change the work), bundled into one message, then commit. Settle purpose (`**Purpose:**`), non-goals, labelled constraints and success criteria (`## Done when` DWs). If the request describes multiple independent subsystems, flag and decompose first (see Large Project Decomposition). **Founder-intent routing:** if the request is "I have a startup idea" / "generate ideas" / "validate my idea" / "what should I build" / any pre-execution founder / innovator / inventor intent — route to the `founder` skill FIRST (not forge directly). Founder owns pre-execution (ideation, validation, business model, GTM); forge owns execution. Founder will hand back at the Scope→Launch gate with a populated `forge_brief` when the venture is ready for build. See `founder/references/forge-handshake.md` for the full contract.
   Read references/01-intake.md before this step.

**Explicit founder handoff**: If the spawn prompt or user message includes `came_from_founder: true` with a `venture_brief_path`, read that file and use its `forge_brief` block as the pre-clarified task statement:

- `forge_brief.problem` -> the design challenge (skip "what are we building?" questions)
- `forge_brief.success_criteria` -> pass to design agents as constraints
- `forge_brief.non_goals` -> pass as explicit scope boundaries
- `forge_brief.complexity_hint` -> seed Step 4 complexity assessment
- `forge_brief.open_questions` -> ask ONLY these in Step 3 (skip all other questions)
- `ideas_considered` / `assumptions` / `experiments` -> include as "Prior founder exploration" in shared_context for all design agents

If `came_from_founder` is absent or false, proceed with normal forge flow. Forge NEVER reads `.founder/venture-brief.yaml` at session start -- only on explicit handoff.

**Explicit avengers handoff**: If the spawn prompt or user message includes `came_from_avengers: true` with an `avengers_brief_path`, read that file and use its `avengers_brief` block as the pre-clarified task statement (mirrors `came_from_founder`; the avengers build path enters forge HERE at Step 3 intake, then flows through forge's own Step 4–9 gates — classification, contract map, spec review, bob):

- `avengers_brief.problem` -> the design challenge (skip "what are we building?" questions)
- `avengers_brief.constraints` -> passed to design agents as constraints
- `avengers_brief.success_criteria` -> passed to design agents as constraints
- `avengers_brief.ruled_out_approaches` -> non-goals + hard "do not explore" signals (each carries which seat killed it; same treatment as the founder phase-2 rule)
- `avengers_brief.recommended_direction` -> seed front-runner for Step 6 exploration (**advisory, NEVER locked** — design agents may reject it)
- `avengers_brief.dissent[]` -> surfaced **verbatim** to the user during Step 7 presentation (never summarized away)
- `avengers_brief.confidence` -> input to Step 4 complexity assessment (high+narrow MAY downgrade team size; low/speculative FORCES full exploration)
- `avengers_brief.deliberation_record` -> listed as a prior-exploration reference in shared_context (path, never inlined)

`avengers_brief.contract_map_signed` and `avengers_brief.bob_ready` are **mechanically always-false** — avengers NEVER signs a contract map or marks anything bob-ready; forge owns those gates. If either is true in the brief, treat the brief as malformed and re-clarify with the user.

If `came_from_avengers` is absent or false, proceed with normal forge flow. Forge NEVER reads an avengers session directory at session start -- only on explicit handoff. **Recursion guard**: a forge-convened avengers session (forge itself invoked avengers for design exploration, carrying `forge_session_id`) MUST NOT emit a brief back into forge — see the Step 6 recursion-guard note.
4. **Assess complexity** — determine design exploration team size needed
4b. **Check tool availability via env-adoption manifest** — Read `~/.claude/state/inventory.json` for tool availability and `$XDG_RUNTIME_DIR/env-adoption/session-*.json` for session capabilities. If the inventory is missing or stale (>24h), run `bash ~/.claude/skills/env-adoption/scripts/probe.sh check` first (completes in <3s). Branch on capabilities:

   - **capabilities.codex_challenger = true**: Codex available: run every codex seat through the guarded seat call (`codex_top_seat` / `seat_model.py argv --use`, see "Spawning Codex Agents").
   - **capabilities.agy_analyst = true**: `agy` available, use a `AGY_MODEL="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_main --provider agy)" && (d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "..." < /dev/null)` call (read-only analyst, #157; `< /dev/null` MANDATORY: open stdin hangs agy, #135).
   - **capabilities.triple_model = true**: all three models available for maximum coverage.

   The manifest is cached for the session — do not re-probe on every use. If Codex/agy unavailable, note the gap explicitly but continue with what's available. See `env-adoption` skill for full schema.
5. **Skill gap check** — identify skills needed, check if they exist (see Skill Gap Detection)
   Read references/01-intake.md before this step.
5b. **Hard rules checkpoint** — read `~/.claude/skills/_meta/hard-rules-checklist.md` DESIGN PHASE + CROSS-MODEL sections. Verify: Codex parallel for MEDIUM/COMPLEX? Performance expectations asked? Gap detection done?
6. **Phase 1: Design Exploration** — spawn design exploration team OR do single-agent exploration
   Read references/02-design-team.md, references/03-codex-seats.md, references/04-agy-and-converge.md and references/principles.md before this step, and Stage 1.5 in references/08-spec-review.md before converging the findings.
7. **Present design** — Simple/Medium: the whole design, one approval; Complex: section by section, approval for each
   Read references/06-present-and-doc.md and references/principles.md before this step.
7b. **Freeze the design skeleton (UI designs only)** — after the user approves the HTML mockup and BEFORE Step 8a signing: invoke `skeleton-extractor` then `visual-architect`. See "UI designs — design-skeleton freeze (Step 2.5)" under Visual Companion.
   Read references/06-present-and-doc.md before this step.
8. **Write design doc** — save to `docs/plans/YYYY-MM-DD-<topic>-design.md`
   Read references/06-present-and-doc.md before this step. Then run the `.forge/size` block under "Step 4: Write Design Doc" below.
8a. **Generate & sign contract map** (if design introduces components) — invoke `component-contract-mapping` skill, run G2 validation, sign via HMAC (see Contract Map Generation)
   Read references/07-contract-map.md before this step.
8b. **Spec review** — run spec self-review checklist, then dispatch reviewer subagent (see Spec Review)
   Read references/08-spec-review.md and references/external-finding-verification.md before this step.
8c. **User reviews spec** — ask user to review spec file before proceeding. Wait for approval.
   Read references/08-spec-review.md before this step.
8d. **Hard rules checkpoint** — read `~/.claude/skills/_meta/hard-rules-checklist.md` EXECUTION PHASE section before spawning bob.
9. **Spawn bob** — pass design doc path and shared context (see Execution Method Selection)
   Read references/09-bob-handoff.md before this step.
10. **Wait for bob** — bob handles decomposition, orchestration, verification autonomously
11. **Final integration** — collect execution results, verify, run the advisory code review and its fix loop (D21 — verified critical/major findings are FIXED, bar goal-fit (1a)), present to user, then delete `.forge/cycle-id` and `.forge/size` (close-out, every status; see Step 6: Collect Results)
   Read references/10-close-out.md and references/03-codex-seats.md before this step, and Stage 1.5 in references/08-spec-review.md with references/external-finding-verification.md before the review's fix loop. The close-out block is under "Step 6: Collect Results" below.

At any step where Claude is stuck (the Codex Escalation rule above), read references/05-escalation.md and references/03-codex-seats.md before escalating.

### Step 1: Understanding (Lead Only)

**Start the cycle first**, every cycle, before anything is edited: write a fresh cycle id and record the cycle base. Run from the project root:

```bash
mkdir -p .forge
if command -v uuidgen >/dev/null 2>&1; then
  uuidgen > .forge/cycle-id.tmp
else
  python3 -c "import uuid; print(uuid.uuid4())" > .forge/cycle-id.tmp
fi
if [[ -s .forge/cycle-id.tmp ]]; then
  mv -f .forge/cycle-id.tmp .forge/cycle-id
else
  rm -f .forge/cycle-id.tmp .forge/cycle-id
  echo "forge: could not generate a cycle id: this cycle's codex budget keys on adhoc-<date>-<cycle-base>"
fi
if git rev-parse --verify -q HEAD >/dev/null 2>&1; then
  git rev-parse HEAD > .forge/cycle-base
else
  echo "forge: no git HEAD here (not a repo, or no commits yet): .forge/cycle-base not recorded"
fi
```

`.forge/cycle-id` is the per-cycle astra budget key: `skills/_meta/codex_quota.py` `cycle_id_for` reads it first, so the codex `admit` calls made from this project root during the cycle count against this cycle's budget. It has three lifecycle points: it is written fresh here at Step 1 of every cycle, deleted at close-out (Phase 2 "Step 6: Collect Results", after the results are presented), and ignored once it is more than 24 hours old (`codex_quota.CYCLE_ID_MAX_AGE_S`), which covers abandoned sessions that never reach close-out. `.forge/session-id` is NOT the budget key: it is the contract-signing id (Step 8a.2) and is never re-minted. `.forge/cycle-base` has two readers: the advisory code reviewer's diff base (`git diff <cycle-base>..HEAD`; foundry-lab `docs/plans/2026-09-14-top-tier-model-roles-design.md` §4.6, not wired yet), and `cycle_id_for`, which builds the fallback key `adhoc-<YYYYMMDD>-<first 7 chars>` from it when no usable `.forge/cycle-id` exists.

**`.forge/size` lives and dies with the cycle id** (S081 revision 4, design §2.1 "Where size comes from"), and the two are documented together here precisely so they cannot drift apart. It is this cycle's review size — one line, `light` (Simple), `medium` (Medium) or `complex` (Complex) — written at **Step 4: Write Design Doc**, once forge's complexity assessment is settled, and deleted at close-out with the cycle id. `seat_model.read_forge_size` reads it, and inside a forge cycle forge's size WINS over the caller's (a genuine conflict takes the larger), so on a `light` or `medium` cycle the one sized codex seat — `code_reviewer` — resolves to the codex std tier instead of codex TOP (the models: codex-orchestration "Seat Models"). Since the astra reserve (roster rev 4) `consultant_main` (challenger, approach explorer) is the codex std tier at EVERY size and `escalation` is codex TOP at every size, so neither moves with the size; both still receive it, and it is recorded on their budget rows. That is why it must not outlive its cycle: a stale `size` would silently bill the NEXT cycle's seats at the wrong model class. Absent, the size resolves as `complex` with `size_source: default`, the back-compat rule that keeps every un-migrated call site working — so a failed write degrades to today's behaviour rather than to a wrong one. Nothing else writes it: Step 4 and close-out are its only two lifecycle points.

The rest of Step 1, what the lead asks and checks, is in `references/01-intake.md`.

---

## Complexity Assessment

Before spawning any design exploration team, assess complexity:

| Complexity | Signals | Design Exploration Team Size |
|------------|---------|---------------------|
| **Simple** | Config change, single-file tweak, obvious solution | No team — single agent explores + optional Codex/agy |
| **Medium** | 2-3 valid approaches, touches 3-5 files | 2-3 approach agents + triple challengers (Claude + Codex + agy) |
| **Complex** | Architecture decision, 4+ approaches, cross-layer | 4-5 approach agents + triple challengers (Claude + Codex + agy) + Codex approach agent |

### Adaptive Checklist

| Step | Simple | Medium | Complex |
|------|--------|--------|---------|
| 1. Project context | Read if exists | Read | Read + invoke project-documentation |
| 2. Visual companion | Skip | If UI-facing | If UI-facing |
| 3. Clarifying questions | 0-1 material question; one-line done-when | One bounded round (material only) | One bounded round (material only) |
| 4. Complexity assessment | Done | Done | Done |
| 4b. Codex + agy check (sandbox-aware) | Skip | Check both + detect mode | Check both + detect mode |
| 5. Skill gap check | Skip | Check | Check |
| 6. Design exploration | Lead proposes directly | 2-3 agents + Codex + agy | Full team + Codex + agy |
| 7. Present design | Brief, one approval | Whole design, one approval | Sections with approval each |
| 8. Write design doc | Optional (skip if <20 lines change) | Yes | Yes |
| 8b. Spec review | Self-review only | Self + subagent | Self + subagent |
| 8c. User reviews | Quick confirm | Review file | Review file |
| 9-11. Bob | Direct or bob | Bob | Bob |

---

## Step 4b: Orchestration tier (S055 — feature-detected)

Before Step 6, decide HOW design exploration runs. This is a fast-path choice,
never a dependency — the documented main path (Step 6B below) completes with
ZERO orchestration primitives.

- Read `bash ~/.claude/skills/env-adoption/scripts/probe.sh get capabilities.workflow_tool`
  (the ONLY capability API — never inline-probe, never raw jq) AND confirm the
  live context via `probe.sh context` (must be `main-loop`). The decision rule,
  restated: `can_orchestrate = capabilities.workflow_tool AND context == main-loop`.
  See `env-adoption/references/context-detection.md` — `capabilities.*` alone
  NEVER authorizes orchestration (session files are shared with subagents).
- **If both true (Step 6A fast path):** the main loop MAY run the
  `design-tournament` saved workflow (parallel approach/challenge/converge fan-out
  that returns a DRAFT synthesis + a script-computed disagreement matrix). The
  converge DECISION, all user questions/approvals, and the design-doc write STAY
  inline in forge (Workflow Boundary, below). External challengers are
  PRE-LAUNCHED inline by forge and passed as transcripts (agy is UNREACHABLE from
  workflow stages — WP-2 live finding).
- **Else (Step 6B portable, canonical):** run the existing design exploration
  team inline (Phase 1 below). This is byte-identical to the prior forge flow.
  Codex/Copilot/VS Code/older-Claude hosts always take this path.

## The three fail-silent blocks

These three blocks stay in this file because skipping one raises no error. A cycle that does not mint a fresh `.forge/cycle-id` draws on a budget that is not its own. A cycle that does not record `.forge/size` has its sized codex seat resolved at `complex`. A `.forge/cycle-id` or `.forge/size` left behind at close-out is read by the next cycle. Run each block at its step; the rest of each step is in the reference named under its heading.

The Step 1 block is not under this heading: it sits directly after the Checklist, so that it starts inside the part of this file that is re-attached after a compaction. The Step 4 and Step 6 blocks follow here.

### Step 4: Write Design Doc

What the design doc must contain is in `references/06-present-and-doc.md`. Write the doc first, then record the size:

**Record the cycle size** (S081 revision 4, design §2.1). The complexity assessment is settled by now, so write it next to `.forge/cycle-id` — `light` for Simple, `medium` for Medium, `complex` for Complex. Same atomic temp-file-and-move shape as the Step 1 mint, so a half-written file is never left behind for `seat_model` to read. Run from the project root, substituting this cycle's size:

```bash
mkdir -p .forge
printf '%s\n' "<light|medium|complex>" > .forge/size.tmp
if [[ -s .forge/size.tmp ]]; then
  mv -f .forge/size.tmp .forge/size
else
  rm -f .forge/size.tmp .forge/size
  echo "forge: could not record the cycle size: codex main seats resolve at complex (the back-compat default)"
fi
```

This is what makes a light or medium cycle's `code_reviewer` codex seat serve the codex std tier rather than spending scarce codex TOP quota (`consultant_main` is the std tier and `escalation` codex TOP at every size since the astra reserve); see the `.forge/size` paragraph at Step 1 for the full lifecycle and for why close-out must delete it.

### Step 6: Collect Results

Read `references/10-close-out.md` before this step. It holds the report template, the spot-check, and the advisory code review with its fix loop (D21). All of them run before the block below.

**Close the cycle — last, after the results are presented and the review's fix loop has settled, for EVERY status (COMPLETE, PARTIAL or FAILED).** Run from the project root:

```bash
rm -f .forge/cycle-id .forge/size
```

The cycle's astra budget ends here: out-of-round codex work afterwards keys on `adhoc-<date>-<cycle-base>`, and a `.forge/cycle-id` left behind by an abandoned session is ignored after 24 hours (`codex_quota.CYCLE_ID_MAX_AGE_S`). `.forge/size` is deleted in the same breath and has no such age fallback: a stale size is read as authoritative for as long as it survives, so the NEXT cycle's `code_reviewer` codex seat (the one seat a size moves since the astra reserve) would be billed at this cycle's model class, and every seat's budget row would record the wrong size. Deleting it restores the `complex` / `size_source: default` back-compat reading until the next Step 4 decides afresh.

---

## Red Flags — STOP and Reassess

- Starting design-team exploration before the user has validated their idea via `founder-ideation` (Phase 1) / `founder-validation` (Phase 2) — pre-execution founder intent belongs in the founder family FIRST, then hand back at the Scope->Launch gate
- Reading `.founder/venture-brief.yaml` at session start without an explicit `came_from_founder` handoff — ambient coupling creates stale-state bugs
- Reading an avengers session directory at session start without an explicit `came_from_avengers` handoff — same ambient-coupling stale-state bug class
- Letting a forge-convened avengers session emit a `forge_brief` back into forge (recursion) — a forge-convened avengers is `decision`-only, build path blocked (see Step 6 recursion guard)
- Treating `avengers_brief.contract_map_signed` / `bob_ready` as anything but always-false — avengers never signs a map or marks bob-ready
- Starting to code before design is approved
- Skipping the Claude challenger "to save tokens"
- Skipping the Codex challenger "Codex is unavailable" (check first, then skip only if truly unavailable)
- Running Codex/agy sequentially after Claude instead of in parallel
- Ignoring Codex or agy findings because they disagree with Claude
- Staying stuck on a problem without escalating to Codex
- Forge doing work package construction instead of letting bob handle it
- Forge micro-managing bob's team orchestration decisions
- Not giving bob enough context in the spawn prompt (design doc path, architecture docs, constraints)
- (S055) Letting a workflow stage make a user decision, sign a contract map, interpret a gate, classify, or write a durable doc — that is the Workflow Boundary (below); workflows return RECORDS, humans and gates DECIDE
- (S055) Inline-probing `claude --version` or raw-jq'ing `inventory.json` for orchestration capability instead of `probe.sh get capabilities.workflow_tool` + `probe.sh context == main-loop`
- (S055) Calling `agy`/`codex` LIVE from inside a `design-tournament` workflow stage — agy is UNREACHABLE from stages (WP-2); external challenger transcripts are PRE-LAUNCHED inline by forge and passed via args

**Cycle cost (S055, observe-only #147):** when the fast path runs the
`design-tournament` workflow, the dispatch log (`progress/workflow-runs.jsonl`)
records the run for cost correlation; forge reports captured spend observe-only
(no enforcement this cycle).

---

## Workflow Boundary (D1 — what NEVER moves into a Workflow)

Saved workflows are mechanical fan-out/fan-in only. The following NEVER execute
inside a workflow stage, on any harness, at any version. Workflows return
RECORDS; humans and gates DECIDE.

1. **User interaction of any kind.** Clarifying questions, section-by-section
   design approval, spec-review sign-off, amendment decisions (Q3b),
   unresolved-token approvals, NEEDS-FOLLOWUP adjudication. A workflow that
   needs user input is mis-scoped — split it; the judgment half stays inline.
2. **Contract-map HMAC signing and session-key custody.** Signing (Step 8a.2,
   visual-architect freeze) runs ONLY as main-loop Bash, outside any workflow.
   No workflow file, args object, or stage prompt may contain the signing-key
   string (W-KEY lint, mechanically checked). Honesty note: stages run with real
   tool access as the same OS user — this boundary is procedural + linted
   defense-in-depth within one trust perimeter, NOT cryptographic isolation. (A
   mechanical signing-event log is deferred hardening.)
3. **Gate verdict authority.** Gates stay Bash subprocesses callable from any
   context (CB3/CB4 unchanged; gates are NOT workflow-aware). A stage MAY run a
   gate where its role already does. A workflow SCRIPT only propagates a gate
   failure fail-closed — it never interprets, retries-around, waives, or
   overrides a gate exit code. Amendment is the only legal bypass and it is a
   user act.
4. **Classification authority.** Emitting `.forge/classification.json` and
   resolving a G_CLASSIFY exit 3 stay inline.
5. **The decision to orchestrate.** Choosing to invoke any workflow, spawning
   bob, accepting bob's report, bridge-mode computation — main-loop judgment.
6. **Durable doc writes.** docs/plans/, history.md, tasks.md, index.md — main
   loop only. (Ledger writes are bob-only per CB4 — separate, unchanged.)
7. **Test execution provenance.** The trusted runner
   (`~/.claude/skills/_meta/trusted_runner.py`) is bob-only (CB3). Any workflow
   stage whose evidence requires EXECUTED tests returns
   `needs_inline_verification`; the canonical bob loop (or the inline caller
   under trusted-runner discipline) executes.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Starting to code before design is approved | Rework when design changes; wasted implementation effort; team confusion about direction | Complete full design phase with challenger review before any code; design approval is a gate |
| Skipping the Codex challenger to save time | Loses the independent perspective that catches blind spots; Claude-only designs have systematic biases | Always run Codex in parallel during design; if unavailable, document the gap and proceed with extra scrutiny |
| Forge micro-managing bob's team orchestration | Forge owns design, bob owns execution; crossing this boundary creates confusion and bottleneck | After design approval, spawn bob with full context and let him handle work packages and team structure |
| Running Codex sequentially after Claude instead of in parallel | Doubles design phase time; loses the value of independent parallel exploration | Launch Codex tasks alongside Claude agents from the start; merge findings after both complete |
| Not including enough context in spawn prompts | Spawned agents (bob, challengers) lack critical information; produce irrelevant or wrong output | Include design doc path, architecture docs, constraints, and explicit success criteria in every spawn prompt |
