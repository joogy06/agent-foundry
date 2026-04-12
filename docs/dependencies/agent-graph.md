# Agent Interaction Graph

This document describes how the agents and supporting skills interconnect. Read this if you want to understand *why* something in the ecosystem calls something else, or to pick a minimal subset that still makes sense.

---

## The Diamond Architecture

```
                         ┌──────────────┐
                         │      pa      │  Task lifecycle, routing, MCP
                         │ (top router) │  Optional — pa-server MCP
                         └──────┬───────┘
                                │
                routes to       │         routes to
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
         ▼                      ▼                      ▼
    ┌─────────┐          ┌─────────────┐         ┌─────────┐
    │  forge  │─approved│     bob     │        │   alf   │
    │         │  plan  ▶│             │◀─approved│         │
    │ (design │         │ (execute)   │  plan    │(review) │
    └────┬────┘         └──────┬──────┘         └────┬────┘
         │                     │                     │
         │                     ▼                     │
         │               ┌──────────────┐            │
         │               │ agent-teams  │            │
         │               │   (skill)    │            │
         │               └──────┬───────┘            │
         │                      │                    │
         │                      ▼                    │
         │               ┌──────────────┐            │
         │               │ team-manager │            │
         │               │   (skill)    │            │
         │               └──────┬───────┘            │
         │                      │                    │
         │                      ▼                    │
         │               ┌──────────────┐            │
         │               │ specialists  │            │
         │               │ (domain      │            │
         │               │  skills)     │            │
         │               └──────────────┘            │
         │                                           │
         └──────────┐                     ┌──────────┘
                    ▼                     ▼
                 ┌──────────────────────────┐
                 │          wiki            │
                 │  (knowledge compiler)    │
                 │  Independent — no deps   │
                 └──────────────────────────┘

External tools (called by forge, bob, alf):
  ├── Codex CLI + /codex:* plugin commands    (GPT-5.4 second opinion)
  ├── Gemini CLI MCP (ask-gemini, brainstorm) (Gemini 3 third opinion, 1M context)
  └── claude-in-chrome MCP                    (browser automation for alf product reviews)
```

The **diamond** shape refers to `pa` at the top orchestrating three specialist peers (`forge`, `bob`, `alf`) that feed into shared execution infrastructure (`agent-teams` → `team-manager` → specialists). `wiki` sits off to the side as a queryable knowledge layer any agent can consult.

---

## Agent Roles at a Glance

| Agent | One-line role | Spawns | Called by |
|-------|---------------|--------|-----------|
| **pa** | Task router, lifecycle manager, persistent memory via MCP | forge (inline), bob (bg), alf (bg), wiki (tier 3) | User directly ("pa ...") |
| **forge** | Design exploration with multi-model challengers | bob (handoff after approval), skills inline | User, pa |
| **bob** | Autonomous implementation executor | agent-teams skill → specialists | forge, alf (with design doc), pa, user |
| **alf** | Evolution/improvement reviewer, evidence engine | bob (via approved design doc) | User, pa, scheduled sweeps |
| **wiki** | Persistent knowledge base builder & query layer | Nothing — terminal node | All other agents (tiered), user |

---

## Interaction Flows

### Flow 1: User → forge → bob (design-then-implement)

```
User: "Build a new auth system"
  │
  ▼
forge (inline skill)
  │
  ├─ Brainstorm approaches (Claude + Codex + Gemini in parallel for MEDIUM/COMPLEX)
  ├─ Write design doc to docs/plans/YYYY-MM-DD-auth-design.md
  ├─ Present to user for approval
  │
  ▼ (user approves)
bob (background agent)
  │
  ├─ Read design doc
  ├─ Decompose into work packages (WP-001, WP-002, ...)
  ├─ Delegate to agent-teams skill
  │    │
  │    ▼
  │  agent-teams orchestrates:
  │    ├─ Team topology selection
  │    ├─ Team lead spawning
  │    ├─ team-manager coordinates specialists
  │    └─ Specialist agents invoke domain skills per WP
  │
  ├─ Verify output against plan (tests, lint, build)
  ├─ Write execution report
  │
  ▼
User: receives design + execution report
```

### Flow 2: User → alf → bob (review-then-fix)

```
User: "Review skill python-flask-developer"
  │
  ▼
alf (background agent)
  │
  ├─ Read target file(s)
  ├─ Signal detection:
  │   ├─ 2a: Freshness check (via Codex /codex:rescue + Gemini Google Search)
  │   ├─ 2b: Best-practice comparison (via Codex)
  │   ├─ 2c: Challenger review (via /codex:adversarial-review or challenger skill)
  │   ├─ 2d: Creation log cross-reference
  │   └─ 2e: Ecosystem cross-reference
  ├─ Synthesize findings with 7-lens framework
  ├─ Write evolution report to .alf/reports/
  ├─ Present to user
  │
  ▼ (user approves changes)
alf generates design doc → hands off to:
  │
  ▼
bob (background agent)
  │
  ├─ Read evolution design doc
  ├─ Execute (same flow as Flow 1)
  └─ Return execution report to alf
  │
  ▼
alf verifies bob's execution → updates .alf/ledger.md
```

### Flow 3: pa routes everything

```
User (session start): "pa"
  │
  ▼
pa
  │
  ├─ Phase 1: pa_start_session() via MCP
  ├─ Phase 2: Catch-up (read active tasks, recent actions)
  └─ Phase 3: Background sync (Confluence, Jira) — non-blocking
  │
  ▼
User: "I need to add pagination to the API"
  │
  ▼
pa classifies intent → "design" signal → routes to forge (inline)
  │
  ▼
forge runs → design approved → pa spawns bob (background)
  │
  ▼
pa continues handling other requests while bob works in background
  │
  ▼
bob completes → notifies pa → pa updates task state via MCP → reports to user
```

### Flow 4: wiki queries (three tiers)

```
Agent needs knowledge from wiki:

Tier 1 — Direct grep (quick lookup, no wiki agent involvement)
  forge: grep wiki-root/index.md for "auth decisions"
  bob: grep wiki-root/wiki/decisions/ before implementing auth
  [no spawn, just file access]

Tier 2 — Skill invocation (single query or single-page addition)
  bob: reads skills/wiki/ingest.md, files ADR inline
  alf: reads skills/wiki/query.md, runs freshness check inline
  [no spawn, skill protocol followed inline]

Tier 3 — Agent spawn (multi-step ops: bootstrap, batch ingest, restructure)
  pa: spawns Agent(name: "wiki") for "create a wiki for project X"
  user: spawns wiki directly for batch ingestion
```

### Flow 5: Standalone agents

Each agent can run **without** the others:

| Agent | Standalone trigger | What still works |
|-------|-------------------|------------------|
| **forge** | User invokes `/forge` or says "design X" | Full design flow, bob handoff still works if bob.md is installed |
| **bob** | User gives bob a design doc path | Full execution if agent-teams skill is installed |
| **alf** | User says "review skill/codebase X" | Full review; bob handoff only works if bob is installed |
| **wiki** | User says "wiki query" or "create a wiki" | Fully standalone — no hard deps |
| **pa** | User says "pa" | Task routing; MCP features require pa-server |

---

## Skill Dependencies per Agent

### forge

**Required skills (referenced by forge.md):**
- `agent-teams` — for multi-team orchestration
- `challenger` — for internal challenger reviews
- `research-for-skills` — for skill-gap detection
- `web-research` — for external research
- `codex-orchestration` — for Codex delegation patterns

**Optional but recommended:**
- `qa-reviewer`, `ux-reviewer` — specialist reviewer roles within teams

### bob

**Required skills:**
- `agent-teams` — for delegation
- `team-manager` — for team coordination
- `research-for-skills` — for skill-gap detection during work-package planning

**Optional:**
- `wiki` skill (reference files) — for optional ADR filing after implementation
- Domain skills matching the work — specialists pick these up based on `skills_needed` in the work package

### alf

**Required skills:**
- `challenger` — for challenger review phase
- `web-research` — for external research with source tiering
- `research-for-skills` — for ecosystem cross-reference

**Optional:**
- `codex-orchestration` — for Codex rescue/adversarial-review invocation
- `wiki` skill (reference files) — for wiki target reviews

### pa

**Required:**
- `pa-server` MCP (optional — pa degrades to stateless mode without it)

**Referenced for routing:**
- All skills (discovered dynamically from frontmatter)
- All other agents (forge, bob, alf, wiki)

### wiki

**Required:**
- `skills/wiki/schema.md` — canonical structure, concurrency primitive, source lifecycle
- `skills/wiki/ingest.md` — ingestion protocol (owned + linked modes)
- `skills/wiki/query.md` — query operations
- `skills/wiki/lint.md` — health checks
- `skills/wiki/templates/` — domain templates

The `wiki` agent delegates almost all operational detail to these reference files — do not delete any of them.

---

## Data Contracts Between Agents

### forge → bob

**Design doc at** `docs/plans/YYYY-MM-DD-<feature>-design.md`:
- Approach (selected from 2-3 alternatives)
- Architecture decisions
- Component breakdown
- File scope
- Testing strategy
- Known risks

bob reads this as the canonical plan. bob does NOT redesign.

### bob → agent-teams

**Work packages** (structured input):
```yaml
work_packages:
  - id: WP-001
    description: "Add pagination to GET /users endpoint"
    dependencies: []
    estimated_complexity: S  # S | M | L
    file_scope: ["src/api/users.py", "tests/test_users.py"]
    skills_needed: ["python-flask-developer"]
```

Plus `shared_context` (design doc path, codebase summary, style guide) and `constraints` (max_teams, max_agents_per_team).

### bob → user (execution report)

Structured completion report:
- Status: COMPLETE | PARTIAL | FAILED
- Files changed
- Teams used
- Verification artifacts (test output, lint output, build output)
- How to verify
- Known issues

### alf → bob

**Evolution design doc** at `docs/plans/YYYY-MM-DD-evolution-<target>-design.md`:
- Evidence citations (source URL, tier, date, confidence per finding)
- Changes to apply
- Expected outcomes

Same format as a forge design doc — bob doesn't distinguish callers except to update `.alf/ledger.md` afterward.

### alf → user (evolution report)

Structured report with health score, findings by severity (critical/beneficial/cosmetic), priority scores, recommended actions.

### pa → any agent

pa passes the user's request as a natural-language prompt **plus** task context (task_id, history, previous decisions from `pa_search()`). Each callee is responsible for its own state management.

### wiki → any caller

Wiki returns **cited** content — every claim includes `[Source: raw/<file>, p.<page>]` or equivalent citation. Callers can trust the facts as traceable to raw sources.

---

## External Tool Integration

### Codex plugin (GPT-5.4)

Called by `forge`, `bob`, `alf`:

| Command | Purpose | Used by |
|---------|---------|---------|
| `/codex:setup` | Availability check | forge |
| `/codex:rescue` | Background research/investigation | forge, alf |
| `/codex:adversarial-review` | Challenger review | forge, bob, alf |
| `/codex:review` | Code review gate | bob |
| `/codex:status` | Check background jobs | forge, bob |
| `/codex:result` | Retrieve background results | forge, bob |

Fallback to raw `codex exec` if the plugin isn't installed.

### Gemini CLI MCP (Gemini 3)

Called by `forge`, `bob`, `alf`, `challenger`, `web-research`, `research-for-skills`, `large-file-analysis`:

| Tool | Purpose | Used by |
|------|---------|---------|
| `mcp__gemini-cli__ping` | Availability check | All |
| `mcp__gemini-cli__ask-gemini` | Prompt with optional Google Search grounding | All |
| `mcp__gemini-cli__brainstorm` | Structured brainstorming methodologies | forge |
| `mcp__gemini-cli__fetch-chunk` | Paginate large responses | large-file-analysis |

### claude-in-chrome MCP

Called by `alf` (product reviews) and `ux-reviewer` skill. Not used by any other agent.

### pa-server MCP

Called **only** by `pa`. No other agent interacts with it directly.

---

## Minimal Subsets

### "Just the knowledge base"
- `agents/wiki.md`
- `skills/wiki/`
- **No external deps.** Fully self-contained knowledge management.

### "Just domain skills, no orchestration"
- `skills/` (all domain skills you want)
- **No agents needed.** Claude will pick up skills automatically.

### "Design-then-implement only" (no review loop)
- `agents/forge.md`, `agents/bob.md`
- `skills/forge/`, `skills/agent-teams/`, `skills/team-manager/`, `skills/challenger/`, `skills/research-for-skills/`, `skills/web-research/`, `skills/codex-orchestration/`
- `skills/qa-reviewer/`, `skills/ux-reviewer/` (optional)
- Your domain specialist skills
- **Optional:** Codex CLI + plugin for multi-model challenger

### "Full ecosystem"
- All 4 agents + all skills
- + Codex CLI + Codex plugin
- + Gemini CLI + gemini-cli MCP (with `GOOGLE_CLOUD_PROJECT=""`)
- + claude-in-chrome MCP (optional — needed only for alf product reviews)
- + pa-server MCP (optional custom — needed only for persistent task tracking)

---

## Anti-Patterns to Avoid

- **Don't delete `skills/wiki/*.md`** if you ship `agents/wiki.md` — the agent delegates almost all operational detail to those reference files
- **Don't delete `skills/agent-teams/` or `skills/team-manager/`** if you ship `agents/bob.md` — bob delegates orchestration to them
- **Don't delete `skills/challenger/` or `skills/research-for-skills/`** if you ship `agents/alf.md` or `agents/forge.md` — they're structural dependencies
- **Don't assume pa works without pa-server** — it does (stateless mode), but users expecting persistence will be confused. Document the tradeoff.
- **Don't wire the agents into a hard chain** — each agent can run standalone. The diamond is a conceptual structure, not a runtime dependency.

---

## Summary

| You want | You install |
|----------|-------------|
| Just domain knowledge for Claude | `skills/` only (no agents) |
| Knowledge base | `agents/wiki.md` + `skills/wiki/` |
| Design + implementation | forge, bob + their dependency skills + Codex (optional) + Gemini MCP (optional) |
| Review/evolution | alf + bob + Codex (strongly recommended) |
| Persistent task tracking | pa + pa-server MCP (custom — build your own) |
| Everything | All 4 agents + all skills + Codex CLI/plugin + Gemini MCP + claude-in-chrome MCP + pa-server MCP |
