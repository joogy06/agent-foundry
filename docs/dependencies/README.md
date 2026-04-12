# Dependencies — Overview

This document explains what you need to install to run the skills and agents in this repository. There are three install tiers depending on how much of the ecosystem you want to use.

## Install Tiers

| Tier | What works | What's required |
|------|-----------|----------------|
| **Minimal** | All documentation-only skills (domain knowledge for Claude). Domain skills work out of the box once placed in `~/.claude/skills/`. | Claude Code CLI only |
| **Standard** | Everything in Minimal + the core agent ecosystem (forge, bob, alf, wiki). Multi-model reviews (Codex challenger, Gemini analyst). | Claude Code CLI + Codex CLI + Codex plugin + Gemini CLI MCP |
| **Full** | Everything in Standard + persistent task tracking (pa agent with MCP), browser-based product reviews (alf product audits). | All of Standard + pa-server MCP + claude-in-chrome MCP |

See [`local-tools.md`](local-tools.md) for CLI install steps and [`mcp-servers.md`](mcp-servers.md) for MCP server setup.

---

## Install Location

Skills and agents are designed to live in Claude Code's standard configuration directory:

```
~/.claude/
├── skills/          # All skill folders go here (unzip contents of skills/ into here)
└── agents/          # All agent .md files go here
```

If you place them elsewhere, update the `~/.claude/skills/…` path references inside the agent files (alf.md, bob.md, wiki.md) to match.

---

## Component Dependency Matrix

### Agents

| Agent | Hard requirement | Optional but recommended | Degrades to |
|-------|-----------------|--------------------------|-------------|
| **forge** | Claude Code CLI, `skills/forge/`, `skills/agent-teams/`, `skills/challenger/`, `skills/web-research/`, `skills/research-for-skills/` | Codex CLI + plugin, Gemini CLI MCP | Claude-only design (no second-opinion models) |
| **bob** | Claude Code CLI, `skills/agent-teams/`, `skills/team-manager/`, `skills/research-for-skills/` | Codex plugin, Gemini CLI MCP | Execution without Codex/Gemini review gate |
| **alf** | Claude Code CLI, `skills/challenger/`, `skills/web-research/`, `skills/research-for-skills/` | Codex plugin, Gemini CLI MCP, claude-in-chrome MCP | Local-only review (no external freshness checks, HTTP-only product audits) |
| **pa** | Claude Code CLI | **pa-server MCP** (custom, not included — see mcp-servers.md) | Stateless mode — routing works, task tracking disabled |
| **wiki** | Claude Code CLI, `skills/wiki/` reference files | None | Full functionality, no external dependencies |

### Skills with external dependencies

| Skill category | Needs | Notes |
|----------------|-------|-------|
| **nano-banana, vertex-banana** | `GEMINI_API_KEY` or `VERTEX_API_KEY` env vars | Only needed if you use image generation skills |
| **confluence-rest-api, confluence-documentation, confluence-content-creator** | `CONFLUENCE_TOKEN`, `CONFLUENCE_BASE`, `CONFLUENCE_USER` env vars | Only for skills that hit the Confluence API |
| **jira-rest-api** | `JIRA_TOKEN`, `JIRA_BASE`, `JIRA_USER` env vars | Only for skills that hit the Jira API |
| **gh-copilot-cli** | GitHub Copilot CLI installed | Only for the `gh-copilot-cli` skill itself |
| **gemini-cli** | Gemini CLI installed | Only if you invoke Gemini CLI directly (not via MCP) |
| **claude-code-cli** | Claude Code CLI (already required) | Baseline |
| **All infrastructure skills** (rhel-*, ubuntu-*, windows-*, docker-*, db2-*, etc.) | None — pure documentation | Claude uses them as reference material; no runtime |

**Note**: Most skills are documentation for Claude. They don't execute code or call APIs themselves — they tell Claude *how* to help with a domain. The "dependencies" column is for skills that reference runtime tools Claude might invoke on your behalf.

---

## Agent Dependency Graph

```
                          ┌─────┐
                          │ pa  │ (optional top layer — needs pa-server MCP)
                          └──┬──┘
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
          ┌──────┐        ┌─────┐       ┌──────┐
          │forge │───────▶│ bob │       │ alf  │
          └──┬───┘        └──┬──┘       └──┬───┘
             │               │             │
             │               ▼             │
             │         ┌──────────┐        │
             │         │agent-    │        │
             │         │teams     │        │
             │         │(skill)   │        │
             │         └────┬─────┘        │
             │              │              │
             │              ▼              │
             │         ┌──────────┐        │
             │         │team-     │        │
             │         │manager   │        │
             │         │(skill)   │        │
             │         └────┬─────┘        │
             │              │              │
             │              ▼              │
             │         ┌──────────┐        │
             │         │specialist│        │
             │         │skills    │        │
             │         └──────────┘        │
             │                             │
             └──────┐              ┌───────┘
                    ▼              ▼
                 ┌─────────────────────┐
                 │  wiki (independent) │
                 └─────────────────────┘

  External: Codex CLI + Codex plugin (used by forge, bob, alf)
            Gemini CLI MCP (used by forge, bob, alf)
            claude-in-chrome MCP (used by alf for product audits)
            pa-server MCP (used by pa only)
```

### Flow

- **pa** is the top-level task router — calls `forge` for design, `bob` for execution, `alf` for reviews, `wiki` for knowledge queries
- **forge** handles design exploration, then hands off to `bob`
- **bob** decomposes plans into work packages and delegates to the `agent-teams` skill, which spawns specialists
- **alf** does evolution/review and hands approved changes to `bob`
- **wiki** is standalone — other agents query it at Tiers 1 (grep), 2 (skill call), or 3 (agent spawn)

### Critical note: circular cleanup

- `pa`, `forge`, `bob`, `alf` are designed to work as a unit. You can run any one of them standalone, but their full value comes from interoperation.
- You can install `wiki` on its own — it has no dependencies on the others.
- Individual domain skills (rhel-*, ubuntu-*, python-*, etc.) work fully standalone — they're documentation.

---

## Minimum Working Installation

For a **minimal install** that exercises most of the ecosystem:

1. Install **Claude Code CLI** (required)
2. Copy `skills/` → `~/.claude/skills/`
3. Copy `agents/` → `~/.claude/agents/`
4. Start Claude Code in any project directory

At this point: all domain skills work, `wiki` agent works, and `forge`/`bob`/`alf` work in **Claude-only mode** (no multi-model reviews). `pa` runs in stateless mode.

To unlock multi-model reviews: add Codex CLI + Codex plugin + Gemini CLI MCP → see [`local-tools.md`](local-tools.md) and [`mcp-servers.md`](mcp-servers.md).

To unlock persistent task tracking: add pa-server MCP → see [`mcp-servers.md`](mcp-servers.md).

---

## What's NOT Included

These components are **referenced but not shipped** in this repository:

| Component | Why not | What to do |
|-----------|---------|-----------|
| **pa-server MCP** | Custom, separate codebase | Build your own MCP server implementing the `pa_*` tools (see pa.md for tool list), or accept pa running in stateless mode |
| **Superpowers plugin** | Excluded per repository scope | Install separately if needed; the `using-superpowers` skill references it but isn't required |
| **Codex plugin for Claude Code** | Third-party plugin | Install via the Claude Code plugin marketplace |
| **Gemini CLI MCP server** | Third-party MCP server | Install via the Gemini CLI package — see [`mcp-servers.md`](mcp-servers.md) |
| **claude-in-chrome MCP** | Third-party MCP server | Install from the claude-in-chrome repository |

---

## Where to Go Next

- [`local-tools.md`](local-tools.md) — how to install Codex CLI, Gemini CLI, plugins, and set environment variables
- [`mcp-servers.md`](mcp-servers.md) — per-MCP-server setup (gemini-cli, claude-in-chrome, pa-server)
