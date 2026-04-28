---
name: forge
description: Use when the user has an idea, feature, design, or change that needs exploration before implementation — architecture decisions, new features, system design, refactoring plans, or any creative/building task that benefits from structured design thinking before code.
---

# Forge — Ideas Into Designs & Implementation

## Overview

Turn ideas into fully formed designs through collaborative dialogue, then orchestrate implementation via **bob** (autonomous executor agent). Uses a two-phase approach: **Design Team** explores approaches with dual challengers (Claude + Codex) and UX advocate, then **bob** handles all execution — work package decomposition, team orchestration via agent-teams, verification, and delivery.

Every design and implementation decision must account for real human behaviour — how end users actually see, navigate, and interact with the product.

<HARD-RULE>
**Multi-Model Second Opinion**: For MEDIUM and COMPLEX tasks, run BOTH Codex (GPT-5.4) AND Gemini (Gemini 3 via `ask-gemini` MCP tool) in parallel alongside Claude agents — three models catch what two miss. For SIMPLE tasks, external models are optional. If Codex/Gemini unavailable, fall back gracefully but note each gap explicitly.
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
**Sandbox-Aware Routing**: For MEDIUM/COMPLEX tasks that call Gemini or Copilot (design exploration, challenger review, research analysis), compute `bridge-mode-detect.sh` output once at Step 4b and cache it for the session. In MODE=bridge, every downstream Gemini/Copilot call transparently routes through `bridge request`. Never mix modes within a single forge session — the caching is there precisely to prevent this. If the bridge is required but not initialized, halt Step 4b and tell the user to run `bridge init` first. See `git-cli-bridge` skill.
</HARD-RULE>

<HARD-GATE>
Do NOT write any code, scaffold any project, or take any implementation action until:
1. A design has been presented and the user has approved it
2. Bob has been spawned with the approved design doc
This applies to EVERY project regardless of perceived simplicity.
</HARD-GATE>

---

## Checklist

You MUST create a task for each item and complete in order:

1. **Explore project context** — read PROJECT.md (architecture map, components, integration edges) and relevant COMPONENT.md files FIRST. Check history.md, session_control.md. Invoke `project-documentation` to ensure all docs exist (creates PROJECT.md + COMPONENT.md stubs if missing). **If a wiki exists for the project** (CWD contains `.wiki/` OR `~/.wiki-registry.yaml` lists this project), use Tier 1 access: `Grep` the wiki's `wiki/` directory for prior decisions, research, and ADRs on the task topic. Include any findings in `shared_context` as a "Prior Wiki Knowledge" section so design agents can reference existing decisions. **Also run `python3 ~/.claude/skills/_meta/scan_hard_rules.py`** (plain mode) to scan CLAUDE.md (global + project-local) for hard-rule directives and diff against `~/.claude/skills/_meta/hard-rules-checklist.md`. If any are flagged as potentially missing, surface them to the user with a 1-line summary and ask: "add to checklist / wire into a skill / apply ad-hoc / ignore?" — do NOT silently skip. This is idempotent with the SessionStart hook but catches cases where forge is invoked from a subagent, after `cd`, or in sessions where the hook didn't run.
2. **Offer visual companion** (if topic involves visual questions) — see Visual Companion section. This is its own message, not combined with clarifying questions.
3. **Ask clarifying questions** — one at a time, understand purpose/constraints/success criteria. If the request describes multiple independent subsystems, flag and decompose first (see Large Project Decomposition). **Founder-intent routing:** if the request is "I have a startup idea" / "generate ideas" / "validate my idea" / "what should I build" / any pre-execution founder / innovator / inventor intent — route to the `founder` skill FIRST (not forge directly). Founder owns pre-execution (ideation, validation, business model, GTM); forge owns execution. Founder will hand back at the Scope→Launch gate with a populated `forge_brief` when the venture is ready for build. See `founder/references/forge-handshake.md` for the full contract.

**Explicit founder handoff**: If the spawn prompt or user message includes `came_from_founder: true` with a `venture_brief_path`, read that file and use its `forge_brief` block as the pre-clarified task statement:

- `forge_brief.problem` -> the design challenge (skip "what are we building?" questions)
- `forge_brief.success_criteria` -> pass to design agents as constraints
- `forge_brief.non_goals` -> pass as explicit scope boundaries
- `forge_brief.complexity_hint` -> seed Step 4 complexity assessment
- `forge_brief.open_questions` -> ask ONLY these in Step 3 (skip all other questions)
- `ideas_considered` / `assumptions` / `experiments` -> include as "Prior founder exploration" in shared_context for all design agents

If `came_from_founder` is absent or false, proceed with normal forge flow. Forge NEVER reads `.founder/venture-brief.yaml` at session start -- only on explicit handoff.
4. **Assess complexity** — determine design exploration team size needed
4b. **Check tool availability via env-adoption manifest** — Read `~/.claude/state/inventory.json` for tool availability and `$XDG_RUNTIME_DIR/env-adoption/session-*.json` for session capabilities. If the inventory is missing or stale (>24h), run `bash ~/.claude/skills/env-adoption/scripts/probe.sh check` first (completes in <3s). Branch on capabilities:

   - **capabilities.codex_challenger = true**: Codex available, use `/codex:setup` or delegate directly.
   - **capabilities.gemini_analyst = true**: Gemini available, use `mcp__gemini-cli__ask-gemini`.
   - **capabilities.bridge_fallback = true**: bridge mode active — route Gemini/Copilot calls through `bridge request`. Verify `bridge init` has been run. Codex is unchanged (runs locally).
   - **capabilities.triple_model = true**: all three models available for maximum coverage.

   The manifest is cached for the session — do not re-probe on every use. If Codex/Gemini unavailable, note the gap explicitly but continue with what's available. See `env-adoption` skill for full schema and `git-cli-bridge` skill for bridge protocol.
5. **Skill gap check** — identify skills needed, check if they exist (see Skill Gap Detection)
5b. **Hard rules checkpoint** — read `~/.claude/skills/_meta/hard-rules-checklist.md` DESIGN PHASE + CROSS-MODEL sections. Verify: Codex parallel for MEDIUM/COMPLEX? Performance expectations asked? Gap detection done?
6. **Phase 1: Design Exploration** — spawn design exploration team OR do single-agent exploration
7. **Present design** — in sections, get user approval after each section
8. **Write design doc** — save to `docs/plans/YYYY-MM-DD-<topic>-design.md`
8a. **Generate & sign contract map** (if design introduces components) — invoke `component-contract-mapping` skill, run G2 validation, sign via HMAC (see Contract Map Generation)
8b. **Spec review** — run spec self-review checklist, then dispatch reviewer subagent (see Spec Review)
8c. **User reviews spec** — ask user to review spec file before proceeding. Wait for approval.
8d. **Hard rules checkpoint** — read `~/.claude/skills/_meta/hard-rules-checklist.md` EXECUTION PHASE section before spawning bob.
9. **Spawn bob** — pass design doc path and shared context (see Execution Method Selection)
10. **Wait for bob** — bob handles decomposition, orchestration, verification autonomously
11. **Final integration** — collect execution results, verify, present to user

---

## Complexity Assessment

Before spawning any design exploration team, assess complexity:

| Complexity | Signals | Design Exploration Team Size |
|------------|---------|---------------------|
| **Simple** | Config change, single-file tweak, obvious solution | No team — single agent explores + optional Codex/Gemini |
| **Medium** | 2-3 valid approaches, touches 3-5 files | 2-3 approach agents + triple challengers (Claude + Codex + Gemini) |
| **Complex** | Architecture decision, 4+ approaches, cross-layer | 4-5 approach agents + triple challengers (Claude + Codex + Gemini) + Codex approach agent |

### Adaptive Checklist

| Step | Simple | Medium | Complex |
|------|--------|--------|---------|
| 1. Project context | Read if exists | Read | Read + invoke project-documentation |
| 2. Visual companion | Skip | If UI-facing | If UI-facing |
| 3. Clarifying questions | 1-2 max | As needed | As needed |
| 4. Complexity assessment | Done | Done | Done |
| 4b. Codex + Gemini check (sandbox-aware) | Skip | Check both + detect mode | Check both + detect mode |
| 5. Skill gap check | Skip | Check | Check |
| 6. Design exploration | Lead proposes directly | 2-3 agents + Codex + Gemini | Full team + Codex + Gemini |
| 7. Present design | Brief, 1 section | Sections | Sections with approval each |
| 8. Write design doc | Optional (skip if <20 lines change) | Yes | Yes |
| 8b. Spec review | Self-review only | Self + subagent | Self + subagent |
| 8c. User reviews | Quick confirm | Review file | Review file |
| 9-11. Bob | Direct or bob | Bob | Bob |

---

## Skill Gap Detection

After assessing complexity, identify what domain skills agents will need:

Follow gap-detection protocol at `~/.claude/skills/research-for-skills/gap-detection.md`

---

## Phase 1: Design Team

### Step 1: Understanding (Lead Only)

The lead handles all user interaction:
- Check current project state (files, docs, recent commits)
- Ask questions **one at a time** (prefer multiple choice)
- Focus on: purpose, constraints, success criteria
- **Performance expectations** (ask if task creates/modifies endpoints, queries, UI, or batch processes):
  - "Expected concurrency / data volume?"
  - "Latency requirements? (e.g., p95 < 200ms)"
  - "Is this on a hot path?"
  - "Existing performance budgets to respect?"
- **Runtime / observability branch** (ask once, not a full questionnaire):
  "Does this change runtime behavior, service boundaries, or SLOs?"
  - If YES: delegate full capacity questionnaire to `performance` skill
    (`references/capacity-questionnaire.md`), full signals-map drafting to
    `observability` skill, BEFORE design-team exploration. Capture the
    signals-map path + capacity answers into `shared_context` so design
    agents consume them as constraints.
  - If NO: skip. Existing performance-expectation questions still apply.
- Determine complexity level

### Step 2: Approach Exploration

**Simple tasks**: Lead proposes 2-3 approaches directly. Skip to "Present Design."

**Medium/Complex tasks**: Spawn a design exploration team.

#### Design Exploration Team Structure

| Role | Count | Responsibility |
|------|-------|----------------|
| **Lead** | 1 | Coordinates, asks user questions, synthesises design |
| **Approach Agents** | 2-5 | Each deeply explores ONE approach with trade-offs |
| **UX/Usability Agent** | 1 (always for UI-facing work) | Evaluates every approach from end-user perspective |
| **Claude Challenger** | 1 (always) | Questions every proposal, finds flaws, plays devil's advocate |
| **Codex Challenger** | 1 (always, if available) | Independent GPT-5.4 challenger — different model catches different flaws |
| **Gemini Analyst** | 1 (MEDIUM+, if available) | Independent Gemini analysis via `ask-gemini` MCP — third model, 1M context, Google Search grounding |
| **Codex Second Opinion** | 1 (always for creative/design, if available) | Parallel exploration via Codex for independent perspective |

#### Three Phases

**Diverge** — Each approach agent explores independently:
- Give each agent a distinct approach/angle
- Include full project context in spawn prompt (teammates don't inherit conversation)
- Each produces: approach description, pros/cons, effort estimate, risks

**Challenge** — Challenger reviews all proposals:
- Share all findings with the challenger
- Challenger finds flaws, gaps, missing edge cases
- Challenger ranks approaches with reasoning

**Converge** — Lead synthesises:
- Collect all findings and challenges
- Identify consensus, disagreements, open questions
- Synthesise into a single recommended design

#### Spawning Design Exploration Agents

**All agents below should be spawned in parallel where possible.**

```
# Approach Agent (Claude)
Agent(subagent_type="general-purpose"):
"You are exploring [APPROACH NAME] for [TASK].
Project context: [KEY FILES, ARCHITECTURE, CONSTRAINTS]
Produce: 1. How it works  2. Pros/cons  3. Effort estimate  4. Risks"

# UX Agent (for UI-facing work)
Agent(subagent_type="multi-platform-apps:ui-ux-designer"):
"You are the UX advocate for [TASK].
Evaluate every approach through: user journey, visual hierarchy,
cognitive load, mobile ergonomics, trust/emotion, accessibility.
Rank approaches by real-world usability."

# Claude Challenger Agent
Agent(subagent_type="general-purpose"):
"You are the devil's advocate for [TASK].
Invoke the `challenger` skill first.
Find flaws in EVERY proposal including UX findings.
Rank approaches with reasoning."
```

#### Spawning Codex Agents (ALWAYS — in parallel with Claude agents)

Check Codex availability first (step 4b). If unavailable, skip Codex agents and note the gap.

**Note on bridge mode**: Codex has no bridge fallback. Codex is the caller in this architecture, not a callee. If `bridge-mode-detect.sh` reports `bridge`, Codex still runs locally (it must be installed in the sandbox — it is the only CLI with that constraint). The bridge only affects Gemini and Copilot delegation.

**Primary: Use Codex plugin commands** (structured output, job tracking, resume capability):

```
# Codex Challenger — use /codex:adversarial-review for design challenge
# Run via Skill("codex:adversarial-review") or invoke the command:
/codex:adversarial-review --background look for scalability, security, maintainability issues and rank approaches

# Codex Research — use /codex:rescue for independent exploration
/codex:rescue --background "Explore approaches for [TASK]. Context: [KEY FILES, ARCHITECTURE, CONSTRAINTS]. Produce top 2-3 approaches with pros/cons, effort, risks."

# Check status of background jobs
/codex:status
# Retrieve results when done
/codex:result [job-id]
```

**Fallback: Raw `codex exec`** (for parallel batch tasks or custom briefs):

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

# Codex Challenger (runs simultaneously with Claude challenger)
cat > "$CODEX_WORK/brief-challenger.md" << 'BRIEF'
# Challenger Review Brief
## Context
[TASK DESCRIPTION + KEY CONSTRAINTS]
Project files at: [PROJECT_DIR]
## Your Role
You are a devil's advocate / challenger. Find flaws in EVERY approach.
Focus on: scalability, security, maintainability, edge cases, operational complexity.
For each issue: Severity (critical/moderate/minor), What's wrong, Why it matters, How to fix.
Rank overall design: strong / acceptable / needs-rework / reject.
BRIEF

timeout 600 codex exec --ephemeral -C "$PROJECT_DIR" -s read-only \
  -o "$CODEX_WORK/challenger.md" \
  "Read $CODEX_WORK/brief-challenger.md and execute the challenger review." || echo "CODEX_TIMEOUT: Codex did not respond within 600s" > "$CODEX_WORK/challenger.md" &

# Codex Second Opinion / Approach Explorer (independent perspective)
timeout 600 codex exec --ephemeral -C "$PROJECT_DIR" -s read-only \
  -o "$CODEX_WORK/approach.md" \
  "You are exploring approaches for [TASK].
Context: [KEY FILES, ARCHITECTURE, CONSTRAINTS]
Produce your top 2-3 recommended approaches with:
1. How it works  2. Pros/cons  3. Effort estimate  4. Risks
Be opinionated — recommend the best approach and explain why." || echo "CODEX_TIMEOUT: Codex did not respond within 600s" > "$CODEX_WORK/approach.md" &

# Codex Research (when task needs up-to-date info)
timeout 600 codex exec --ephemeral --skip-git-repo-check --search \
  -o "$CODEX_WORK/research.md" \
  "Research current best practices for [TECHNOLOGY/PATTERN] as of 2026.
Latest versions, known limitations, community adoption, alternatives." || echo "CODEX_TIMEOUT: Codex did not respond within 600s" > "$CODEX_WORK/research.md" &

wait  # Wait for all Codex tasks to complete
```

**When to use plugin vs raw exec**: Plugin commands are preferred for single challenger/research tasks (structured output, job tracking). Use raw `codex exec` when running 3+ parallel tasks in a batch or when custom brief files with skill injection are needed.

#### Spawning Gemini Analyst (MEDIUM+ — in parallel with Claude and Codex agents)

Check Gemini availability first: `mcp__gemini-cli__ping()`. If unavailable, skip and note the gap.

```
# Gemini Analyst — leverages 1M context and Google Search grounding
mcp__gemini-cli__ask-gemini(prompt: "You are an analyst for [TASK].
Project context: [KEY FILES, ARCHITECTURE, CONSTRAINTS]
Analyze: 1. Architecture trade-offs  2. Scalability limits  3. Security surface
4. What approaches work best at scale for this pattern?
Be specific and cite real-world precedents where possible.")

# For large codebase context (Gemini's 1M window advantage):
mcp__gemini-cli__ask-gemini(prompt: "Review the codebase at [PATHS] for [TASK].
Focus on: cross-cutting concerns, hidden coupling, N+1 patterns, missing error boundaries.")

# For multi-methodology brainstorming:
mcp__gemini-cli__brainstorm(topic: "[TASK] approaches", methodology: "six_hats")
```

**When to use Gemini vs Codex**: Gemini excels at large context analysis (full codebase review), research with Google Search grounding, and multi-methodology brainstorming. Codex excels at focused code review, devil's advocate challenger work, and prototype exploration.

### Bridge-mode Gemini analyst

When `bridge-mode-detect.sh` returned `bridge`, call Gemini via the bridge:

```bash
# Uses the already-initialized session from bridge init
BRIDGE_CALLER=forge BRIDGE_CALLER_TASK_ID="forge-$(date +%s)-gemini-analyst" \
bridge request --tool gemini --kind review \
  --context "$PROJECT_SUMMARY_PATH" \
  --wait --timeout 720 \
  "Analyze this design for architecture trade-offs, scalability limits, security surface.
  Cite real-world precedents."
```

Latency expectation: ~90s cold, ~40s warm. The parallel-model design pattern (Claude + Codex + Gemini in parallel) still holds — launch this alongside the Claude challenger and Codex adversarial review at the start of the design exploration team phase, not sequentially after.

#### Converging Triple-Model Findings

When collecting results, the lead MUST:
1. Read Claude challenger output AND Codex challenger output (`$CODEX_WORK/challenger.md`) AND Gemini analyst output
2. Read Codex approach exploration (`$CODEX_WORK/approach.md`)
3. Identify where models **agree** (high confidence) vs **disagree** (needs deeper analysis)
4. Flag disagreements to the user: "Claude, Codex, and Gemini disagree on X — here are all perspectives"
5. Weight all model findings equally — each has different blind spots and strengths
6. Gemini findings often include real-world precedents and Google Search-grounded data — flag these as evidence

#### Codex Escalation (When Claude Is Stuck)

When Claude agents fail to solve a problem after 2+ attempts or enter circular reasoning:

**Primary: Use `/codex:rescue`** (managed job with resume capability):

```
/codex:rescue "Claude agents are stuck on [PROBLEM]. Tried: [APPROACHES]. Blocker: [ISSUE]. Need a fresh approach — challenge the assumptions that led to the dead end."
```

**Fallback: Raw `codex exec`** (for custom briefs):

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

cat > "$CODEX_WORK/escalation-brief.md" << 'BRIEF'
# Escalation: Claude agents are stuck on [PROBLEM]

## What was tried
[LIST APPROACHES THAT FAILED AND WHY]

## The specific blocker
[DESCRIBE THE EXACT ISSUE]

## Project context
[KEY FILES, ARCHITECTURE]

## What we need
A fresh approach to solve this. Don't repeat what was already tried.
Think differently — challenge the assumptions that led to the dead end.
BRIEF

timeout 600 codex exec --ephemeral -C "$PROJECT_DIR" -s read-only --search \
  -o "$CODEX_WORK/escalation-result.md" \
  "Read $CODEX_WORK/escalation-brief.md and provide a fresh solution." || echo "CODEX_TIMEOUT: Codex did not respond within 600s" > "$CODEX_WORK/escalation-result.md"
```

### Escalation Termination

Max escalation chain: Claude 2 attempts -> Codex 1 attempt -> user.

If Codex escalation also fails or times out:
1. Present the problem to the user with ALL attempted approaches
2. Include what Claude tried, what Codex tried, and why both failed
3. Ask the user for direction
4. Do NOT retry automatically. Do NOT loop back to Claude.

### Step 3: Present Design

After convergence:
- Present design in sections scaled to complexity
- Ask after each section: "Does this look right so far?"
- Cover: architecture, components, data flow, error handling, testing approach, performance considerations
- **Always include a UX section** for UI-facing work
- Be ready to revise based on user feedback

### Step 4: Write Design Doc

- Save to `docs/plans/YYYY-MM-DD-<topic>-design.md`
- Update `history.md` and `index.md`
- Shut down design exploration team (if created)

---

## Contract Map Generation (Step 8a)

When a design introduces components (new services, modules, APIs, integration points), forge MUST produce a signed contract map BEFORE invoking the spec review (Step 8b) and before spawning bob.

Pure refactors, bugfixes, and single-file changes with no new components are exempt.

### Step 8a.1: Invoke component-contract-mapping

Invoke the `component-contract-mapping` skill with:

1. The draft design doc path
2. Relevant PROJECT.md and COMPONENT.md paths
3. The user's spoken intent from design dialogue

The skill will:
1. Extract components from the design discussion
2. Define types dictionary with semantic_type per field (from the v1 18-type registry)
3. Write `progress/contract-map.yaml` (single writer — only ever written here)
4. Run G2 validation locally by invoking `python -m gates G2 progress/contract-map.yaml`
5. Auto-render a markdown table into the design doc
6. Request forge to sign the map

If G2 validation fails, fix the design doc (not the YAML — the skill rewrites it from the design doc). Re-invoke the skill. Bob will refuse to execute without a valid signed contract map.

### Step 8a.2: Emit session material and sign

Forge is responsible for the session material and the signing payload.

```bash
# Create session material once per forge session (idempotent)
mkdir -p .forge
[[ -f .forge/session-id ]] || uuidgen > .forge/session-id
[[ -f .forge/session.key ]] || { openssl rand -hex 32 > .forge/session.key && chmod 0600 .forge/session.key; }

# Read current state
MAP_HASH=$(sha256sum progress/contract-map.yaml | awk '{print $1}')
MAP_REVISION=$(yq eval '.revision' progress/contract-map.yaml)
SESSION_ID=$(cat .forge/session-id)
SIGNED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Build the signed payload per spec section 7.4 — full payload including session_id
PAYLOAD=$(jq -cn --arg h "$MAP_HASH" --arg r "$MAP_REVISION" --arg s "$SESSION_ID" --arg t "$SIGNED_AT" \
  '{map_hash: $h, map_revision: ($r | tonumber), forge_session_id: $s, signed_at: $t}')

# Canonical JSON (sort keys, no whitespace) — must match gates.py canonical_json() bit-for-bit
CANONICAL=$(printf '%s' "$PAYLOAD" | jq -cS .)

# Compute HMAC-SHA256 using the session key file content (ALL BYTES, including the
# trailing newline from `openssl rand -hex 32 > file`) as the key.
#
# gates.py reads the key via pathlib.Path.read_bytes() which returns 65 bytes
# (64 hex chars + newline). Shell command substitution `$(cat file)` strips trailing
# newlines and produces a 64-byte key — mismatches gates.py. This produced a G1
# signature-mismatch on every forge-signed contract map before 2026-04-19; see
# skill_factory/docs/reviews/2026-04-19-product-merger-codex-spec-review.md (tasks.md #85).
#
# Mirrors _meta/gates.sh §HMAC verification (Python oracle preferred; bash fallback uses
# xxd round-trip + openssl -macopt hexkey: to preserve the trailing newline byte).
if command -v python3 >/dev/null 2>&1; then
  SIG=$(printf '%s' "$CANONICAL" | python3 -c "
import hmac, hashlib, sys, pathlib
key = pathlib.Path('.forge/session.key').read_bytes()
msg = sys.stdin.buffer.read()
print(hmac.new(key, msg, hashlib.sha256).hexdigest())
")
else
  KEY_HEX=$(xxd -p -c 0 .forge/session.key)
  SIG=$(printf '%s' "$CANONICAL" | \
    openssl dgst -sha256 -mac HMAC -macopt "hexkey:$KEY_HEX" -binary | \
    xxd -p -c 256 | tr -d '\n')
fi

# Write the signature file — contains both payload and signature
jq -cn --argjson p "$PAYLOAD" --arg s "$SIG" '{payload: $p, signature: $s}' > progress/contract-map.yaml.sig
```

### Step 8a.3: Verify signature

Run G1 locally (with `--no-ledger-binding`, since bob has not yet initialized the ledger):

```bash
python3 ~/.claude/skills/_meta/gates.py G1 "$(pwd)" --no-ledger-binding
# exit 0 = signature valid, safe to hand off to bob
# exit 2 = G1_FAIL — fix and re-sign
```

If G1 fails, re-run Step 8a.2 after fixing the underlying issue (most common: the skill re-wrote the YAML without updating the signature; re-sign).

### Step 8a.4: Stage for bob

At this point the workspace contains:
- `progress/contract-map.yaml` (frozen — never edited after this)
- `progress/contract-map.yaml.sig` (full signed payload)
- `.forge/session-id` (UUID, inherited by bob)
- `.forge/session.key` (0600, inherited by bob)

Proceed to Step 8b (spec review).

---

## Phase 2: Implementation via bob

After the user approves the design, delegate execution to **bob** — the autonomous executor agent.

Bob handles everything: work package decomposition, team orchestration, monitoring, verification, and delivery. Forge stays focused on design.

### Step 5: Spawn bob

```
Agent(name: "bob", subagent_type: "bob", prompt: """
Execute this approved design.

Design document: [PATH_TO_DESIGN_DOC]
Project root: [PROJECT_DIR]

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

The contract-map block is OMITTED only for designs that do not introduce components (pure refactors, single-file bugfixes). In that case, include an explicit line: `Contract map: N/A (no new components in this change).`

**What to include in bob's prompt:**
- Path to the design doc (bob reads it himself)
- Architecture docs: PROJECT.md path + relevant COMPONENT.md paths
- Coding conventions (if any)
- Existing interface contracts to respect
- Performance requirements (budgets, concurrency targets from design doc)
- Any user-specified constraints (e.g., "don't touch the database schema")

### Step 6: Collect Results

Bob returns a structured execution report. When you receive it:

1. **Check status** — COMPLETE / PARTIAL / FAILED
2. **If PARTIAL or FAILED** — present bob's report to the user with remaining items and recommended next steps
3. **If COMPLETE** — present bob's report to the user:

```
## Implementation Complete: [Feature Name]

### What Was Built
[From bob's report — deliverables with descriptions]

### Files Changed
[From bob's report — all modified/created files]

### Verification
[From bob's report — what passed, what didn't]

### How to Verify
[From bob's report — step-by-step testing instructions]

### Known Limitations
[From bob's report — deferred items or edge cases]
```

**Forge spot-checks bob's verification artifacts.** Bob produces concrete verification artifacts (test output, lint output, build output) in his report. For medium/complex tasks, forge must:
1. Pick at least one verification artifact from bob's report and re-run the command independently
2. Read at least one modified file and confirm it matches the plan
3. If spot-check passes: present bob's report to the user
4. If spot-check fails: flag the discrepancy to the user before presenting

---

## Amendment Mode (S029)

This section runs only when bob spawns forge with `mode=amendment` during a contract-scope pause cycle. It is **not a numbered step** in the main checklist — Step 9 (Spawn bob) remains in place. Amendment Mode is an out-of-band invocation that handles a specific bob-initiated pause-state subprotocol.

**Trigger.** Bob's `G_CONTRACT_SCOPE` gate has flagged a critical undeclared artifact during a WP boundary or `INTEGRATED → VERIFIED` re-check; bob has acknowledged the pause and reached `MAP_UPDATING`. Bob then spawns forge with:

```
mode: amendment
project_root: <abs path>
contract_map_path: <abs path to current signed progress/contract-map.yaml>
gaps_dir: <abs path to .ledger/scope-deltas/>
pause_epoch: <epoch returned by claims.request_scope_pause>
```

**Authority — USER IS SOLE AUTHORITY (Q3b lock).** Forge cannot self-approve any amendment. Bob cannot self-approve. Both only mechanically apply user-approved decisions. There are **no waivers** — the only legal bypass for `G_CONTRACT_SCOPE` is a user-approved amendment of the signed contract map.

**What forge does in amendment mode.**
1. Load the helper from `~/.claude/skills/_meta/forge_amendment_helper.py`.
2. Read all undecided scope_delta records: `fah.read_undecided_deltas(project_root)`.
3. For each record, present a structured prompt to the user (path, artifact_kind, severity, requesting_wp, detection_point, closest declared component(s)) with decision options: **a**mend (add path to a component's `source_paths`), **e**xclude (add to top-level `excluded_paths`), **d**efer (leave undecided — escalate or HALT), **r**eject (forge proposes nothing for this delta; bob's pause cycle will time out → ROLLBACK).
4. Build a `decisions` list from the user's input.
5. Call `fah.draft_amendment(contract_map_path, decisions)` to obtain amended-YAML text. The helper bumps `revision` (rev_N → rev_N+1) and is a **pure function** — no I/O, no signing.
6. Write the proposal to a non-canonical path (recommended: `<project_root>/.forge/amendment-rev-<N>.yaml.proposal`). **Forge never overwrites `progress/contract-map.yaml`.**
7. Return `fah.return_to_bob(amended_path, deltas_resolved)` to bob — a dict `{amended_map_path, deltas_resolved}`.

**What forge does NOT do** (these are bob's responsibilities, enforced by static-scan tests on the helper):
- Compute or modify the HMAC signature, touch `.forge/session.key`, or write `progress/contract-map.yaml.sig`.
- Write to `progress/integration-ledger.md`, `.ledger/claims/`, `.ledger/deltas/`, or any subpath under `.ledger/`.
- Call `scope_delta.update_status` (bob's hand-off step at 8.7).
- Call `pause_state.transition_to`, `pause_state.request_pause`, or any other pause-state mutator (CB4: only `scope_reaction.handle` may call `pause_state.request_pause`; bob orchestrates the rest).
- Run G2 as the authoritative check — bob runs G2 again on receipt before signing.

**Reference.** Full protocol detail (entry signature, dialogue script, output contract, worked SQL-table-D example, HARD-RULEs) lives in `~/.claude/skills/forge/references/amendment.md`. Read that doc before handling any `mode=amendment` invocation.

**Cross-references:**
- Helper: `~/.claude/skills/_meta/forge_amendment_helper.py` (CONTRACT-C1).
- Schema: `~/.claude/skills/_meta/schemas/scope_delta.v1.json` (CONTRACT-A2).
- Bob hot path: `~/.claude/agents/bob.md` HARD-RULE 6, Step 4.6, Step 8.7.
- Pause state machine: `~/.claude/skills/_meta/pause_state.py` (CONTRACT-A0).
- Reaction (only legal pause-state caller): `~/.claude/skills/_meta/scope_reaction.py` (CONTRACT-B2).
- Design doc: `docs/plans/2026-04-26-contract-scope-enforcement-keystone-design.md` §7.3.

---

## Visual Companion

The local `visual-companion` skill provides a server-less browser-based companion for showing mockups, diagrams, and visual options during design. It writes self-contained HTML files to `/tmp/visual-companion-<session>/` that the user opens in their browser, with no server or client-side state.

**When to offer:** After exploring project context, if upcoming questions will involve visual content (mockups, layouts, diagrams, architecture), offer it once:

> "Some of what we're working on might be easier to explain if I can show it to you in a web browser — mockups, diagrams, comparisons. Want to try the visual companion? (I'll write HTML files to /tmp/ that you open in your browser.)"

**This offer MUST be its own message.** Do not combine with clarifying questions. If they accept, invoke the `visual-companion` skill — read its SKILL.md for the protocol and templates.

**Per-question decision:** Even after acceptance, decide FOR EACH QUESTION whether to use browser or terminal. Use browser for visual content (mockups, wireframes, layout comparisons). Use terminal for text content (requirements, tradeoffs, scope decisions).

---

## Large Project Decomposition

Before asking detailed design questions, assess scope. If the request describes multiple independent subsystems (e.g., "build a platform with chat, file storage, billing, and analytics"):

1. **Flag immediately** — don't spend questions refining details of a project that needs decomposition
2. **Help decompose** — identify independent pieces, relationships, and build order
3. **Brainstorm first sub-project** — each sub-project gets its own forge cycle (design -> approval -> implementation)

### Recursion Limit

Forge tracks decomposition depth:
- depth=0: top-level task (default)
- depth=1: first sub-project from decomposition
- depth=2: sub-project of a sub-project — WARN user: "Deeply nested. Consider flattening."
- depth>=3: REFUSE to recurse. Present remaining work as a flat list for the user to prioritize.

When spawning a sub-project forge cycle, pass depth+1 in the prompt.

---

## Spec Review

After writing the design doc (step 8), run a two-stage review:

**Stage 1 — Self-review (inline):**
1. **Placeholder scan:** Any "TBD", "TODO", incomplete sections, vague requirements? Fix them.
2. **Internal consistency:** Do any sections contradict each other? Does the architecture match the feature descriptions?
3. **Scope check:** Is this focused enough for a single implementation plan, or does it need decomposition?
4. **Ambiguity check:** Could any requirement be interpreted two different ways? Pick one and make it explicit.

Fix issues inline. Then proceed to stage 2.

**Stage 1.5 — External-finding verification (S030-quickwins #37):**

If Stage 2 will dispatch external-model reviewers (Codex, Gemini), or if
external-model findings already exist from earlier in the design (Step 4b
challengers, the Gemini analyst), run the **verification pass** BEFORE
merging any of those findings into the consolidated review report.

For each external-model finding that cites a specific code/file/symbol:

1. Open the cited artifact and confirm the citation actually exists.
2. Mark the finding `VERIFIED` (citation + claim match), `FALSE-POSITIVE`
   (citation does not match the claim — e.g. spec text contradicts the
   model's interpretation), or `NEEDS-FOLLOWUP` (citation is unclear or
   needs human judgement).
3. Only `VERIFIED` findings flow into the consolidated review report. Move
   `FALSE-POSITIVE` findings to a separate "False positives, with grep
   evidence" section. Move `NEEDS-FOLLOWUP` to a third section for the
   user to adjudicate.

Codex and Gemini have observed false-positive rates of 60-65% on adversarial
spec/design review (DLP pilot 2026-04-09; S030-init WP-0). Skipping this
verification pass would propagate model hallucinations into the design doc
and waste user attention. The protocol — including worked examples of how
to distinguish a real bug from a model misread — lives at
`~/.claude/skills/forge/references/external-finding-verification.md`.

**Stage 2 — Subagent review (dispatched):**
Dispatch a spec reviewer subagent:

```
Agent(subagent_type="general-purpose"):
"You are a spec document reviewer. Verify this spec is complete and ready for planning.
Spec to review: [SPEC_FILE_PATH]

Check for: completeness (TODOs, placeholders), consistency (contradictions),
clarity (ambiguous requirements), scope (single plan or needs decomposition),
YAGNI (unrequested features). Only flag issues that would cause real problems
during implementation. Approve unless there are serious gaps.

Output: Status (Approved / Issues Found), Issues (if any), Recommendations."
```

If issues found: fix and re-dispatch (max 3 iterations). Then present to user:

> "Spec written to `<path>`. Please review before we proceed to implementation."

Wait for user approval before continuing.

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

---

## UX Principles Reference

For UI-facing work, apply these when evaluating designs:

| Principle | Application |
|-----------|-------------|
| **Fitts's Law** | Make primary CTAs big and centrally placed |
| **Hick's Law** | Limit options, don't overwhelm with choices |
| **Jakob's Law** | Follow conventions users already know |
| **Miller's Law** | Group info into categories, max ~7 items |
| **Von Restorff Effect** | Make primary CTA visually distinctive |
| **F-Pattern / Z-Pattern** | Place key info along natural scan paths |
| **Progressive Disclosure** | Show only what's needed, reveal on demand |

---

## Key Principles

- **One question at a time** — don't overwhelm the user
- **Multiple choice preferred** — easier to answer than open-ended
- **YAGNI ruthlessly** — remove unnecessary features from all designs
- **Users first, code second** — every decision starts with "how does the user experience this?"
- **Always triple challengers for MEDIUM+** — Claude + Codex + Gemini catch what one or two models miss
- **Always include UX for UI work** — technically perfect but confusing = failed
- **Codex and Gemini run in parallel, not after** — launch all external model tasks alongside Claude agents, never sequentially
- **Escalate to Codex when stuck** — if Claude agents fail 2+ times, delegate to Codex for a fresh perspective before asking the user
- **Flag model disagreements** — when Claude, Codex, and Gemini disagree, present all perspectives to the user
- **Gemini for grounded research** — use Gemini's Google Search grounding and 1M context for real-world precedents, large codebase analysis, and freshness checks
- **Forge owns design, bob owns execution** — after design approval, spawn bob and let him handle everything
- **Teammates don't inherit context** — include ALL relevant info in spawn prompts
- **Prefer Codex plugin commands** (`/codex:adversarial-review`, `/codex:rescue`, `/codex:review`) over raw `codex exec` — they provide structured output, job tracking, and resume capability
- **Refer to `codex-orchestration` skill** for raw Codex CLI patterns when plugin commands don't fit (parallel batches, custom briefs, skill injection)

## Red Flags — STOP and Reassess

- Starting design-team exploration before the user has validated their idea via `founder-ideation` (Phase 1) / `founder-validation` (Phase 2) — pre-execution founder intent belongs in the founder family FIRST, then hand back at the Scope->Launch gate
- Reading `.founder/venture-brief.yaml` at session start without an explicit `came_from_founder` handoff — ambient coupling creates stale-state bugs
- Starting to code before design is approved
- Skipping the Claude challenger "to save tokens"
- Skipping the Codex challenger "Codex is unavailable" (check first, then skip only if truly unavailable)
- Skipping the Gemini analyst without checking `bridge-mode-detect.sh` first (even in sandboxed environments, Gemini should be available via the bridge)
- Running Codex/Gemini sequentially after Claude instead of in parallel
- Ignoring Codex or Gemini findings because they disagree with Claude
- Staying stuck on a problem without escalating to Codex
- Forge doing work package construction instead of letting bob handle it
- Forge micro-managing bob's team orchestration decisions
- Not giving bob enough context in the spawn prompt (design doc path, architecture docs, constraints)

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Starting to code before design is approved | Rework when design changes; wasted implementation effort; team confusion about direction | Complete full design phase with challenger review before any code; design approval is a gate |
| Skipping the Codex challenger to save time | Loses the independent perspective that catches blind spots; Claude-only designs have systematic biases | Always run Codex in parallel during design; if unavailable, document the gap and proceed with extra scrutiny |
| Forge micro-managing bob's team orchestration | Forge owns design, bob owns execution; crossing this boundary creates confusion and bottleneck | After design approval, spawn bob with full context and let him handle work packages and team structure |
| Running Codex sequentially after Claude instead of in parallel | Doubles design phase time; loses the value of independent parallel exploration | Launch Codex tasks alongside Claude agents from the start; merge findings after both complete |
| Not including enough context in spawn prompts | Spawned agents (bob, challengers) lack critical information; produce irrelevant or wrong output | Include design doc path, architecture docs, constraints, and explicit success criteria in every spawn prompt |
