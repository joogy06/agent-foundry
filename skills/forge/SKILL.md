---
name: forge
description: Use when the user has an idea, feature, design, or change that needs exploration before implementation — architecture decisions, new features, system design, refactoring plans, or any creative/building task that benefits from structured design thinking before code.
---

# Forge — Ideas Into Designs & Implementation

## Overview

Turn ideas into fully formed designs through collaborative dialogue, then orchestrate implementation via **bob** (autonomous executor agent). Uses a two-phase approach: **Design Team** explores approaches with dual challengers (Claude + Codex) and UX advocate, then **bob** handles all execution — work package decomposition, team orchestration via agent-teams, verification, and delivery.

Every design and implementation decision must account for real human behaviour — how end users actually see, navigate, and interact with the product.

<HARD-RULE>
**Multi-Model Second Opinion**: For MEDIUM and COMPLEX tasks, run BOTH Codex (GPT-5.5) AND Antigravity CLI (`agy`, via `agy --sandbox -p`) in parallel alongside Claude agents — three models catch what two miss. For SIMPLE tasks, external models are optional. If Codex/agy unavailable, fall back gracefully but note each gap explicitly.
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
**Sandbox-Aware Routing**: For MEDIUM/COMPLEX tasks that call `agy` or Copilot (design exploration, challenger review, research analysis), compute `bridge-mode-detect.sh` output once at Step 4b and cache it for the session. In MODE=bridge, every downstream `agy`/Copilot call transparently routes through `bridge request`. Never mix modes within a single forge session — the caching is there precisely to prevent this. If the bridge is required but not initialized, halt Step 4b and tell the user to run `bridge init` first. See `git-cli-bridge` skill.
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
   - **capabilities.agy_analyst = true**: `agy` available, use a direct `agy --sandbox -p "..." < /dev/null` Bash call (read-only analyst, #157; `< /dev/null` is MANDATORY — without it agy blocks on stdin in non-TTY shells and hangs to timeout, #135).
   - **capabilities.bridge_fallback = true**: bridge mode active — route `agy`/Copilot calls through `bridge request`. Verify `bridge init` has been run. Codex is unchanged (runs locally).
   - **capabilities.triple_model = true**: all three models available for maximum coverage.

   The manifest is cached for the session — do not re-probe on every use. If Codex/agy unavailable, note the gap explicitly but continue with what's available. See `env-adoption` skill for full schema and `git-cli-bridge` skill for bridge protocol.
5. **Skill gap check** — identify skills needed, check if they exist (see Skill Gap Detection)
5b. **Hard rules checkpoint** — read `~/.claude/skills/_meta/hard-rules-checklist.md` DESIGN PHASE + CROSS-MODEL sections. Verify: Codex parallel for MEDIUM/COMPLEX? Performance expectations asked? Gap detection done?
6. **Phase 1: Design Exploration** — spawn design exploration team OR do single-agent exploration
7. **Present design** — in sections, get user approval after each section
7b. **Freeze the design skeleton (UI designs only)** — after the user approves the HTML mockup and BEFORE Step 8a signing: invoke `skeleton-extractor` then `visual-architect`. See "UI designs — design-skeleton freeze (Step 2.5)" under Visual Companion.
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
| **Simple** | Config change, single-file tweak, obvious solution | No team — single agent explores + optional Codex/agy |
| **Medium** | 2-3 valid approaches, touches 3-5 files | 2-3 approach agents + triple challengers (Claude + Codex + agy) |
| **Complex** | Architecture decision, 4+ approaches, cross-layer | 4-5 approach agents + triple challengers (Claude + Codex + agy) + Codex approach agent |

### Adaptive Checklist

| Step | Simple | Medium | Complex |
|------|--------|--------|---------|
| 1. Project context | Read if exists | Read | Read + invoke project-documentation |
| 2. Visual companion | Skip | If UI-facing | If UI-facing |
| 3. Clarifying questions | 1-2 max | As needed | As needed |
| 4. Complexity assessment | Done | Done | Done |
| 4b. Codex + agy check (sandbox-aware) | Skip | Check both + detect mode | Check both + detect mode |
| 5. Skill gap check | Skip | Check | Check |
| 6. Design exploration | Lead proposes directly | 2-3 agents + Codex + agy | Full team + Codex + agy |
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

## Step 6A fast path — `design-tournament` workflow (optional, main-loop only)

When the orchestration tier (Step 4b) selected the fast path: invoke
`Workflow({name: "design-tournament", args: {...}})` with `run_started_at`,
`run_label`, `brief_path`+`brief_sha256`, `shared_context_path`+`shared_context_sha256`,
`approaches[]`, `consultants[]`, `consultant_cmds{}`, `ui_facing`, `budget_tokens`,
`transcript_dir`, `external_transcripts[]` (pre-launched), `models{}`. The
workflow returns a `design-synthesis.v1` DRAFT + the disagreement matrix; forge
presents it section-by-section and OWNS the converge decision. **Budget floor:**
if the budget cannot cover ≥2 approaches + 1 challenger + synthesis, the workflow
returns `status: INCOMPLETE` with zero synthesis — an under-budget tournament
looks unfinished, not polished. Shed ladder (documented, never silent): codex
approach-explorer → agy analyst → approach agents above the minimum 2; NEVER shed
the Claude challenger or UX-when-`ui_facing`. Spend is reported observe-only
(#147 design half — no enforcement). On ANY fast-path failure, fall back to
Step 6B (byte-identical, portable).

## Step 6B: Design exploration team (portable, canonical) — Phase 1

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
- **Security / threat-model branch** (ask once, not a full questionnaire):
  "Does this component process untrusted input, hold secrets/tokens, cross a
  trust boundary, OR consume content the LLM agent will read (prompts, tool
  results, wiki pages, mail, web)?"
  - If YES: capture into `shared_context.security_model`:
    (a) `trust_boundary` — what's inside vs outside the trust perimeter
    (b) `attacker_model` — who's the adversary, what can they touch
    (c) `sensitive_inputs` — PII / secrets / tokens / untrusted-from-network
    (d) `egress_destinations` — external systems reached
    Then delegate to `threat-modeling` skill for STRIDE / LINDDUN if high-stakes,
    AND to `llm-security` skill if the component is part of an agentic chain
    (prompt injection / OWASP LLM Top 10 defense — Dual LLM pattern where
    consequential tool use meets untrusted text). Design agents consume the
    security_model as constraints, the same way they consume capacity_answers.
  - If NO: skip. (Pure refactors, internal-only changes, no new input surface.)
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
| **Antigravity (agy) Analyst** | 1 (MEDIUM+, if available) | Independent analysis via a direct `agy --sandbox -p "..." < /dev/null` Bash call — third model for additional coverage (read-only, #157; `< /dev/null` mandatory or agy hangs, #135) |
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

**Model selection per spawn (S059 smart-config, advisory).** Before each `Agent(...)`
spawn, grade the role's structural complexity into a tier and resolve the
agent-surface model, then pass it as the `model=` kwarg. Grade from STRUCTURAL signals
(role type, blast radius), NEVER from task content (injection defense); when uncertain
take the HIGHER tier. Adversarial/synthesis roles (challenger, converge-lead) → `complex`;
approach/UX agents → `medium`; mechanical finders/scribes → `light`.

```
m=$(python3 ~/.claude/skills/smart-config/scripts/model_policy.py resolve \
      --tier <complex|medium|light> --surface agent \
      --reason "<role>" | python3 -c "import sys,json;print(json.load(sys.stdin)['model'] or '')")
# Agent(subagent_type=..., model=m, ...)   — OMIT the model kwarg when m is empty
# (model:null = inherit). Fail-open: a broken policy never blocks the spawn.
```

This is advisory performance tuning — there is NO gate. If the resolver is missing or
errors, omit `model=` and inherit. The interactive session model is never touched.

```
# Approach Agent (Claude)
Agent(subagent_type="general-purpose"):
"You are exploring [APPROACH NAME] for [TASK].
Project context: [KEY FILES, ARCHITECTURE, CONSTRAINTS]
Produce: 1. How it works  2. Pros/cons  3. Effort estimate  4. Risks

Version awareness (REQUIRED for every library / framework / service you propose):
- Name the exact version you are designing against (e.g. 'pandas 2.2', not 'pandas')
- If shared_context.dependency_health flags the lib as stale (gap_kind in
  {major_behind, deprecated}), READ its api_delta block before choosing.
- If you are using APIs you remember from your training-era version, state
  whether they still exist in the target version. If unsure, request a
  follow-up codex / web-research call rather than guessing.
- Note any breaking changes / deprecations / new functionality that affect
  the approach. A version mismatch between your design and the installed
  version is a HIGH risk — surface it explicitly.

Security CVE awareness (REQUIRED, parallel to version awareness):
- If shared_context.dependency_health flags a CVE in any lib you propose
  (look for `cves` / `vulnerabilities` / `advisories` keys in the dep-currency
  finding), state explicitly: (a) the CVE id, (b) whether you're proposing an
  upgrade past the fixed version OR a mitigation (input filter, sandbox,
  removal of the vulnerable code path), (c) why the mitigation is acceptable
  if you're NOT upgrading. Designing against a known-vulnerable version
  without acknowledging the CVE is a HIGH risk and will be flagged in review.
- If shared_context.security_model exists (set by Step 1 security branch),
  treat its attacker_model / sensitive_inputs / egress_destinations as
  constraints. A design that ignores them is structurally wrong, not just
  insecure. Examples: trust_boundary='public API' means your approach MUST
  include input validation at the boundary; sensitive_inputs containing
  tokens/secrets means your approach MUST address storage hardening.
- For agentic components (LLM consuming untrusted text + having tools):
  reference Dual LLM architecture (Quarantined LLM processes untrusted data
  without tool access, Privileged LLM uses only symbolic vars) as the
  default-safe pattern. Deviations need explicit justification."

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

**Note on bridge mode**: Codex has no bridge fallback. Codex is the caller in this architecture, not a callee. If `bridge-mode-detect.sh` reports `bridge`, Codex still runs locally (it must be installed in the sandbox — it is the only CLI with that constraint). The bridge only affects `agy` and Copilot delegation.

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

**Fallback: Raw `codex exec`** (for parallel batch tasks or custom briefs). **STDIN RULE (#155):** the agy stdin rule applies to `codex exec` exactly the same — close stdin (`< /dev/null`) on every headless argv-prompt invocation or it hangs to timeout in background shells:

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
  "Read $CODEX_WORK/brief-challenger.md and execute the challenger review." < /dev/null || echo "CODEX_TIMEOUT: Codex did not respond within 600s" > "$CODEX_WORK/challenger.md" &

# Codex Second Opinion / Approach Explorer (independent perspective)
timeout 600 codex exec --ephemeral -C "$PROJECT_DIR" -s read-only \
  -o "$CODEX_WORK/approach.md" \
  "You are exploring approaches for [TASK].
Context: [KEY FILES, ARCHITECTURE, CONSTRAINTS]
Produce your top 2-3 recommended approaches with:
1. How it works  2. Pros/cons  3. Effort estimate  4. Risks
Be opinionated — recommend the best approach and explain why." < /dev/null || echo "CODEX_TIMEOUT: Codex did not respond within 600s" > "$CODEX_WORK/approach.md" &

# Codex Research (when task needs up-to-date info; web search is automatic — no flag)
timeout 600 codex exec --ephemeral --skip-git-repo-check \
  -o "$CODEX_WORK/research.md" \
  "Research current best practices for [TECHNOLOGY/PATTERN] as of 2026.
Latest versions, known limitations, community adoption, alternatives." < /dev/null || echo "CODEX_TIMEOUT: Codex did not respond within 600s" > "$CODEX_WORK/research.md" &

wait  # Wait for all Codex tasks to complete
```

**When to use plugin vs raw exec**: Plugin commands are preferred for single challenger/research tasks (structured output, job tracking). Use raw `codex exec` when running 3+ parallel tasks in a batch or when custom brief files with skill injection are needed.

#### Spawning Antigravity (agy) Analyst (MEDIUM+ — in parallel with Claude and Codex agents)

Check `agy` availability first: `command -v agy`. If unavailable, skip and note the gap.

`agy -p` returns **plain text on stdout** (the old `mcp__gemini-cli__*` MCP tools returned
structured fields — `agy` does not, so the lead parses the text reply, not JSON fields).
Raise `--print-timeout` above the 5m default for long analyses. Append a `served_by` probe
line to the prompt and capture it — self-reported model identity is unreliable.

**STDIN RULE (root-caused 2026-06-05, #135):** headless `agy` MUST have stdin closed or piped —
`< /dev/null` on every call. agy reads non-TTY stdin until EOF *before* the model call; in
background/harness shells stdin never EOFs, so agy hangs forever producing 0 bytes and
`--print-timeout` never fires (it only guards the print phase). Also wrap in a shell `timeout`.

Prompt size is NOT a factor (verified: 30-char prompt hung; 11KB prompt with `< /dev/null`
answered in 9s).

**SANDBOX RULE (S052 rogue-commit incident, #157):** the agy analyst is a READ-ONLY role — ALWAYS
invoke it with `--sandbox`. agy has write/shell/git tools by default; in S052 an un-sandboxed
"analyst" auto-authored and git-committed broken code mid-design (HARD-GATE violation). Codex is
unaffected (it already runs `-s read-only`). FLAG ORDER (root-caused 2026-07-02): `--sandbox` and
every other flag BEFORE `-p`, prompt LAST — `agy -p --sandbox "X"` silently runs UN-sandboxed
with the literal prompt `--sandbox` and discards "X" (agy then improvises from implicit memory —
the "does work instead of consulting" failure mode). Scope caveat (verified 2026-07-02, 1.0.15):
`--sandbox` constrains shell/git only, NOT native file writes — prefer piping content over
`--add-dir` on a writable repo, open the prompt with "Advisory only — do not modify any files;
answer on stdout", and run `git status --short` afterwards if a repo was exposed.

```bash
# Antigravity (agy) Analyst — independent third-model analysis
timeout 600 agy --sandbox -p "You are an analyst for [TASK].
Project context: [KEY FILES, ARCHITECTURE, CONSTRAINTS]
Analyze: 1. Architecture trade-offs  2. Scalability limits  3. Security surface
4. What approaches work best at scale for this pattern?
Be specific and cite real-world precedents where possible.
At the very end print one line: SERVED_BY=<model-id-you-are-running-as>." < /dev/null

# For codebase context, add the relevant paths to the workspace with --add-dir:
# CAUTION: --sandbox does NOT gate native file writes into --add-dir trees — prefer piping;
# if you must --add-dir a writable repo, run `git status --short` afterwards and revert strays.
timeout 600 agy --sandbox --add-dir [PATHS] -p "Advisory only — do not modify any files; answer on stdout.
Review the codebase at [PATHS] for [TASK].
Focus on: cross-cutting concerns, hidden coupling, N+1 patterns, missing error boundaries." < /dev/null

# For multi-methodology brainstorming (frame the methodology in the prompt itself):
timeout 600 agy --sandbox -p "Brainstorm approaches for [TASK] using the Six Thinking Hats methodology —
work through White (facts), Red (intuition), Black (caution), Yellow (benefits),
Green (alternatives), and Blue (process) in turn, then summarise." < /dev/null
```

**When to use agy vs Codex**: `agy` is a useful independent third model for architecture analysis, codebase review (add paths with `--add-dir`), and multi-methodology brainstorming. Codex excels at focused code review, devil's advocate challenger work, and prototype exploration.

### Bridge-mode agy analyst

When `bridge-mode-detect.sh` returned `bridge`, call `agy` via the bridge:

```bash
# Uses the already-initialized session from bridge init
BRIDGE_CALLER=forge BRIDGE_CALLER_TASK_ID="forge-$(date +%s)-agy-analyst" \
bridge request --tool agy --kind review \
  --context "$PROJECT_SUMMARY_PATH" \
  --wait --timeout 720 \
  "Analyze this design for architecture trade-offs, scalability limits, security surface.
  Cite real-world precedents."
```

Latency expectation: ~90s cold, ~40s warm. The parallel-model design pattern (Claude + Codex + agy in parallel) still holds — launch this alongside the Claude challenger and Codex adversarial review at the start of the design exploration team phase, not sequentially after.

#### Converging Triple-Model Findings

When collecting results, the lead MUST:
1. Read Claude challenger output AND Codex challenger output (`$CODEX_WORK/challenger.md`) AND agy analyst output
2. Read Codex approach exploration (`$CODEX_WORK/approach.md`)
3. Identify where models **agree** (high confidence) vs **disagree** (needs deeper analysis)
4. Flag disagreements to the user: "Claude, Codex, and agy disagree on X — here are all perspectives"
5. Weight all model findings equally — each has different blind spots and strengths
6. agy findings that cite real-world precedents — flag these as evidence (and verify per Stage 1.5)

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

timeout 600 codex exec --ephemeral -C "$PROJECT_DIR" -s read-only \
  -o "$CODEX_WORK/escalation-result.md" \
  "Read $CODEX_WORK/escalation-brief.md and provide a fresh solution." < /dev/null || echo "CODEX_TIMEOUT: Codex did not respond within 600s" > "$CODEX_WORK/escalation-result.md"
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

### Step 8a.0: Emit + corroborate the classification artifact (S042 / #115)

BEFORE deciding whether to build a map, forge MUST write `.forge/classification.json` (schema `contract-classification.v1`) — the recorded classification that travels with the cycle, analogous to the signed contract map. This closes the bare-`Contract map: N/A` hole at the producer side (not just bob's front door).

The artifact states:
- `introduces_components`: `"yes" | "no"`
- `reason_code`: a value from the **closed enum** {`skill_text`, `doc_only`, `direct_bugfix`, `refactor`, `self_contained_meta_helper`, `sidecar_telemetry`, `agent_text`, `existing_component_extension`} — NOT free-text (free-text reasons are a loophole).
- `design_doc`, `planned_globs`, `evidence` (confirmed_positives / negatives / prose_only).

Forge may hand-write it, or derive a default via the helper:
```bash
python3 ~/.claude/skills/_meta/classify_emit.py "<project_root>" \
  --design-doc "<design-doc-path>" --classified-by forge_design \
  --files-from "<planned-file-touch-list>"
```

Then forge **locally runs `G_CLASSIFY` to fail-fast at design time** (catch a misclassification before bob is ever spawned):
```bash
python3 ~/.claude/skills/_meta/gates.py G_CLASSIFY "<project_root>" \
  --design-doc "<design-doc-path>" \
  --asserted "<N/A if introduces_components==no, else provided>" \
  --files-from "<planned-file-touch-list>"
```
- Exit 0 → classification corroborated; proceed.
- Exit 2 → the scan contradicts the artifact (named signals). Fix the design/classification before continuing; do NOT hand bob a false N/A.
- Exit 3 → ambiguous; resolve with the user before spawning bob.

The artifact is a CLAIM the gate re-derives and corroborates — never trusted (the threat model includes a buggy/drifting producer). `existing_component_extension` makes the Ship-of-Theseus case (appending component logic into existing allowed files) a *declarable, checkable* category rather than a silent dodge.

### Step 8a.1+: Build the signed contract map (component cycles only)

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

The contract-map block is OMITTED only for designs that do not introduce components (pure refactors, single-file bugfixes). In that case, include an explicit line: `Contract map: N/A (no new components in this change) — <reason>.` **This `N/A` line is ADVISORY only** (S042 / #115): bob does NOT trust it: bob's mandatory `G_CLASSIFY` pre-flight independently re-derives and corroborates the classification, and authorizes skipping Step 1.5 SOLELY on a green (`exit 0`) gate. A false N/A is caught (exit 2 BLOCK with named signals).

**What to include in bob's prompt:**
- Path to the design doc (bob reads it himself)
- **Path to `.forge/classification.json`** (the Step 8a.0 classification artifact — bob's `G_CLASSIFY` pre-flight corroborates it)
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

### Cycle cost (observe-only, S046 #124)
[If bob's report includes a `Spawn cost` line, surface it verbatim: "captured
Claude-verifier spend: $X across N spawns; summed spawn duration Ys —
coverage: partial (forge approach-agents + Codex + agy costs NOT captured);
budget_enforced: false". This is OBSERVE-ONLY — v1 records, does not cap
(enforcement deferred → #147). Omit if bob ran no cold-context verifier spawn.]

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

### UI designs — design-skeleton freeze (Step 2.5)

For UI-facing designs — the design output includes an HTML mockup, CSS file, new user-facing screen, or new interactive element, and `ui_scope` is not `none` — the approved mockup MUST be frozen into a signed design-skeleton. This runs AFTER the user approves the HTML mockup (checklist Step 7b) and BEFORE Step 8a contract-map signing. This is the design-phase freeze that the `visual-architect` skill refers to as "forge Step 2.5".

1. **Invoke `skeleton-extractor`** — transforms the approved HTML mockup into a draft `design-skeleton.v1` YAML (`.design-ledger/skeletons/<screen>.draft.yaml`): puppeteer-core DOM walk at 3 breakpoints, bboxes + computed styles back-resolved to declared tokens + wired interaction handlers. The draft is UNSIGNED — `interactions[].binds_to` may be `null`, and hardcoded CSS values the extractor could not back-resolve land in `unresolved_tokens_report`.
2. **User reviews the draft** — the user supplies a `capability://...` URI (or `visual_only`) for every null `binds_to`, and explicitly approves or rejects every unresolved token. Capture these as a user-edits YAML (schema in `visual-architect/SKILL.md`).
3. **Invoke `visual-architect`** (`scripts/freeze.py freeze`) — validates every `binds_to: capability://...` URI resolves via `uri.exists` (first failure → challenge filed, exit 1); enforces **D2 strict** on unresolved tokens (each MUST be explicitly user-approved into the tokens block or explicitly rejected — no silent skip; otherwise exit 2); HMAC-signs the payload with `.forge/session.key` (file bytes including trailing newline); atomically two-file writes `.design-ledger/skeletons/index.yaml` + `<screen>.yaml` via `trusted_runner.bundle_write`; emits a `skeleton_frozen` transition request to `.ledger/requests/` — **bob applies it (CB4: bob is sole ledger writer; forge/visual-architect write nothing to `.ledger/claims/` or `progress/integration-ledger.md`)**.

**Why this cannot be skipped:** bob's UI-INTEGRATED → UI-VERIFIED transition verifies the built product against the frozen skeleton — `visual-arbiter` measures bbox / computed styles / interaction wiring against it, and both the `G_XR` gate and the visual-verdict 8-field tuple require `skeleton_hash`. No frozen skeleton means no `skeleton_hash`, and UI-VERIFIED is unreachable for that screen.

Read `skeleton-extractor/SKILL.md` and `visual-architect/SKILL.md` for invocation commands, exit codes, and the user-edits schema before invoking either.

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

If Stage 2 will dispatch external-model reviewers (Codex, agy), or if
external-model findings already exist from earlier in the design (Step 4b
challengers, the agy analyst), run the **verification pass** BEFORE
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

Codex and agy have observed false-positive rates of 60-65% on adversarial
spec/design review (DLP pilot 2026-04-09; S030-init WP-0). Skipping this
verification pass would propagate model hallucinations into the design doc
and waste user attention. The protocol — including worked examples of how
to distinguish a real bug from a model misread — lives at
`~/.claude/skills/forge/references/external-finding-verification.md`.

**Fast path — `ratify-design` workflow (S055, optional, main-loop only).**
When the orchestration tier (Step 4b) is the fast path (`probe.sh get
capabilities.workflow_tool` true AND `probe.sh context == main-loop`), Stage 1.5
MAY run as the `ratify-design` saved workflow, which MECHANIZES this verification
pass: deliberate (child `cross-cli-deliberation` — ratify-design is invoked
TOP-LEVEL via `Workflow({name})`, NEVER via `workflow()` from another script, so
its child consumes the single nesting level, WP-2 finding 7) → extract-findings
(substring-checks every quote against the ballot transcript; non-matching ⇒
`extraction_suspect` ⇒ NEEDS-FOLLOWUP) → verify-findings (ONE cold-context
verifier PER cited finding; deterministic-first `grep -n -F "<quote>"` at the
cited path — quote absent verbatim ⇒ FALSE-POSITIVE `citation-not-found`,
MANDATORY; a VERIFIED verdict without `cited_text_verbatim` + a grep line is
SCHEMA-INVALID) → assemble (`ratification-record.v1` with the per-run measured
`fp_rate`). Budget exhaustion mid-verify ⇒ ALL remaining findings NEEDS-FOLLOWUP
(never auto-VERIFIED) + `degraded: true`. The workflow NEVER edits the doc;
forge merges VERIFIED findings inline and spot-checks (re-greps ≥1 VERIFIED
finding per run). External consultant transcripts are PRE-LAUNCHED inline
(agy is unreachable from stages, WP-2). On any fast-path failure, fall back to
the inline Stage-1.5 protocol above (byte-identical, portable).

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
- **Always triple challengers for MEDIUM+** — Claude + Codex + agy catch what one or two models miss
- **Always include UX for UI work** — technically perfect but confusing = failed
- **Codex and agy run in parallel, not after** — launch all external model tasks alongside Claude agents, never sequentially
- **Escalate to Codex when stuck** — if Claude agents fail 2+ times, delegate to Codex for a fresh perspective before asking the user
- **Flag model disagreements** — when Claude, Codex, and agy disagree, present all perspectives to the user
- **agy as an independent third model** — use `agy --sandbox -p` for architecture analysis, codebase review (add paths with `--add-dir`), and multi-methodology brainstorming; `--sandbox` is mandatory for these advise-only calls (#157 — without it agy may edit/commit the reviewed project instead of reporting)
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
- Skipping the agy analyst without checking `bridge-mode-detect.sh` first (even in sandboxed environments, agy should be available via the bridge)
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
