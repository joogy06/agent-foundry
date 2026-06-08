# Custom Ecosystem (this machine)

This file documents the custom forge/bob/alf/pa/wiki/agent-teams stack layered on top of vanilla Claude Code 2.1.96. None of this is part of upstream superpowers — it is unique to this user's environment.

## Stack overview

```
                    pa  (orchestrator + workspace context)
                  / | \  \
              forge bob alf  119 skills
                |         \
               bob      (audit reports)
                |
           agent-teams (multi-team orchestration)
                |
           team-manager (single-team coordination)
                |
           specialists (invoke domain skills, implement)
```

`pa` sits on top, `forge → bob → agent-teams → team-manager → specialists` is the implementation cascade.

## Custom agents (`~/.claude/agents/`)

### `forge`
- **Purpose**: Design exploration with dual challengers (Claude + Codex). Creative work, system design, feature ideation.
- **Inputs**: User intent, domain context.
- **Outputs**: Approved design doc → handed to bob.
- **Hard rule**: Never implements directly — delegates to bob after approval. For MEDIUM/COMPLEX tasks, must run Codex AND Antigravity (agy) in parallel with Claude challengers.
- **Routing**: TRIVIAL/SIMPLE bypass forge entirely (handled directly or via single-skill invocation). MEDIUM and COMPLEX go through forge.

### `bob`
- **Purpose**: Autonomous implementation executor. Reads approved designs, decomposes into work packages, delegates orchestration to `agent-teams`, verifies output, reports back.
- **Inputs**: Design doc path, project root, caller context (forge / alf / pa / standalone).
- **Outputs**: Structured execution report with work-package status, deliverables, verification artifacts.
- **Hard rule**: For 3+ WPs delegate to `agent-teams`. For 1-2 S-complexity WPs execute directly. For 7+ WPs write a `.bob-checkpoint.md` to track state.

### `alf`
- **Purpose**: Evolution / improvement agent. Reviews skills, code, products for staleness, drift, gaps. Produces audit findings. Hands off remediation to bob.
- **Inputs**: Sweep scope (skill family, code dir, product).
- **Outputs**: Audit report with findings + remediation hand-off to bob.
- **History**: First full sweep (2026-04-05) produced 44 findings, all fixed (75 anti-pattern table additions, 22 splits, 18 description rewrites).

### `pa`
- **Purpose**: Personal assistant — task lifecycle, intent router, workspace context, enterprise sync (Jira/Confluence). MCP server with `pa_*` tools.
- **MCP server**: `pa-server` exposes `pa_create_task`, `pa_update_task`, `pa_query_tasks`, `pa_search`, `pa_log_action`, `pa_sync_jira`, `pa_sync_confluence`, `pa_get_preferences`, etc.
- **Detection**: Other agents (bob, alf, forge) check for `pa_*` MCP tool availability and conditionally update task status / log actions if pa is reachable. Standalone if not.

### `wiki`
- **Purpose**: Knowledge base builder/maintainer for persistent markdown wikis. Ingests sources, creates structured pages, queries and lints wikis.
- **Hard rules**: Cite every claim. `raw/` layer is immutable. `.wiki.lock` single-writer. Index-first navigation.
- **Binding**: Projects opt in via `.wiki-link` files at the project root. Registry at `~/.wiki-registry.yaml`.

## Hard rules checklist

The file `~/.claude/skills/_meta/hard-rules-checklist.md` is a compact nudge file that must be read at major decision checkpoints. It exists because models lose track of HARD-RULEs in long sessions.

| Checkpoint | Section to read |
|---|---|
| Before spawning any design team | DESIGN PHASE |
| Before spawning bob | EXECUTION PHASE |
| Before spawning alf | (relevant section) |
| Before claiming work complete | REVIEW / COMPLETION |
| Every 3-4 major tool calls in a long session | quick scan |

Critical rules summarised in the checklist:

- **DESIGN**: Codex + Antigravity (agy) in parallel for MEDIUM/COMPLEX. Never code before design approval. Performance expectations questions for hot-path tasks. Gap detection before design.
- **EXECUTION**: Bob does NOT orchestrate teams (agent-teams does). Bob direct-execute for small jobs. Test discovery before "run tests". Caller-aware output. Structured checkpoints for 7+ WPs.
- **REVIEW**: Evidence before assertions. Spot-check verification. Performance dimension if hot-path.
- **ROUTING**: Complexity pre-filter — TRIVIAL/SIMPLE bypass forge. PA is optional. Forge is a skill (inline), not a subagent.
- **GAP DETECTION**: Never block active task. Use policy matrix (score 0-4). Dedup gaps. Inline notice for CRITICAL.
- **TEMP FILES**: Always `mktemp -d`. Session-scoped. No hardcoded `/tmp/` paths.
- **CROSS-MODEL**: Timeout all `codex exec` (`timeout 120`). Escalation terminates. Session-scoped Codex availability check. Antigravity (agy) for COMPLEX only. Verify `command -v agy` before agy work; delegate via `agy -p "..."` (plain-text output — parse text, not JSON). Use agy for large-codebase / large-file analysis.
- **WIKI**: Cite every claim. Raw is immutable. Single-writer lock. Lint after batch ingest. Index-first navigation.

## Memory system

### Auto-memory
Per-project memory at `~/.claude/projects/<slug>/memory/MEMORY.md` with one-line index entries pointing to detail files in the same dir. Persists across conversations.

### Project context (read at session start)
For any project directory:

| File | Purpose |
|---|---|
| `PROJECT.md` | Hierarchical architecture map: components, integration edges, external deps |
| `history.md` | Session history, decisions, progress (bounded by rotation policy; older context in `history/INDEX.md`) |
| `tasks.md` | Task list, priorities, completion status |
| `index.md` | File index |
| `session_control.md` | Session-specific instructions |
| `docs/plans/*.md` | Approved design documents |
| `docs/components/*/COMPONENT.md` | Per-component architecture docs |
| `.wiki-link` | Wiki binding file (if any) |

If any of these exist, **read them BEFORE asking questions or starting work**.

### Wiki binding
After project context, check for wiki binding:
- `.wiki-link` file in project root or parent
- `.wiki/` subdirectory with embedded `WIKI.md`
- `~/.wiki-registry.yaml` entry whose path matches CWD

## Skill library

- **Claude skills**: `~/.claude/skills/<name>/SKILL.md` — 119 skills as of 2026-03-31 (post-enterprise expansion).
- **Codex skills**: `~/.codex/skills/<name>/` — 119 entries, mostly symlinks to the Claude originals plus 7 native Codex-only skills.
- **Authoring**: Use `research-for-skills` skill. Sub-skill `cross-tool-portability/` enforces cross-CLI compatibility.
- **Inventory**: `~/.claude/skills/_meta/inventory.json` with creation/update events in `creation-log.jsonl`.
- **Adversarial sweeps**: alf periodically scans for stale skills, missing anti-patterns tables, descriptions that don't lead with triggers.

### Skill skip list (do NOT symlink to Codex)
Claude-specific orchestration skills that depend on Claude Code internals: `agent-teams`, `codex-orchestration`, `forge`, `nano-banana`, `vertex-banana`, `research-for-skills`, `challenger`.

### Skill standards (S009 / 44-finding sweep)
Every SKILL.md must have:
- Frontmatter only `name + description` (cross-tool portable)
- Description leads with "Use when..." trigger language
- Anti-patterns table at the end
- Body <500 lines (split to `references/` if longer)
- Cross-model-compatible language ("Read the file" not "Use the Read tool")
- Specific data with sources, no vendor marketing as fact

## Session-start prompts (CLAUDE.md routing)

Two sequential prompts asked one at a time at session start:

1. **Autonomy mode**: "Allow file edits, shell commands, tool calls without permission, except design questions / production deploys / commits to main? (y/n)"
2. **Forge mode**: "Use forge for this session as the default workflow? (y/n)"

If both yes, the assistant runs autonomously and routes everything that touches code/skills/agents through forge.

## Routing by complexity (CLAUDE.md)

| Complexity | Route |
|---|---|
| TRIVIAL | Direct (config change, typo fix, single edit) |
| SIMPLE | Single skill invocation, no forge |
| MEDIUM | Forge (Simple complexity, single-agent + optional Codex) |
| COMPLEX | Full forge cycle (design team, dual challengers, Codex + Antigravity (agy), bob delegation) |

## Plugins integrated

- **superpowers** (marketplace) — source for `working-with-claude-code` reference fork. The forge skill subsumes superpowers' brainstorming/writing-plans/executing-plans/subagent-driven workflows.
- **codex** plugin v1.0.2 — preferred over raw `codex exec`. Slash commands: `/codex:review`, `/codex:adversarial-review`, `/codex:status`, `/codex:result`, `/codex:rescue`, `/codex:setup`.
- **frontend-design**, **javascript-typescript**, **payment-processing**, **multi-platform-apps** — domain plugins.

## File patterns and load-bearing config

- **`~/.claude/settings.json`** — active. Notification + stop hooks installed. Do NOT break.
- **`~/.claude/CLAUDE.md`** — global instructions (autonomy/forge defaults, routing, hard rules pointer).
- **`~/.claude/AGENTS.md` -> `~/.claude/CLAUDE.md`** — symlink. Created in S008 for Codex CLI compatibility. Native AGENTS.md support in Claude Code 2.1.96 is **UNVERIFIED** — flagged for first-boot test.
- **`~/.claude/agents/{forge,bob,alf,pa,wiki}.md`** — agent definitions. Only the agents in `~/.claude/agents/` are user-defined; other "agents" (challenger, qa-reviewer, ux-reviewer, team-manager) are skills assigned at runtime.
- **`~/.codex/skills/`** — Codex symlink mirror.
- **`~/.gemini/extensions/nanobanana`** — installed Gemini extension. Do NOT touch.

## See also

- `cross-tool-integration.md` — how Claude Code talks to Codex CLI and Antigravity CLI (agy)
- `upgrades-since-jan-2026.md` — delta vs the upstream superpowers snapshot
- `~/.claude/skills/_meta/hard-rules-checklist.md` — actual checklist file
- `~/.claude/skills/research-for-skills/cross-tool-portability/` — cross-CLI authoring rules
