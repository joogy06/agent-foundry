# MCP Server Setup

This document covers the Model Context Protocol (MCP) servers that the agents and some skills rely on.

All MCP servers are registered in Claude Code's configuration (`~/.claude/settings.json` or the per-project `.claude/settings.json`). Claude Code auto-starts registered MCP servers on session start.

---

## MCP Servers Used

| MCP Server | Required for | Tier |
|-----------|-------------|------|
| **gemini-cli** | forge, bob, alf, challenger, web-research, research-for-skills, large-file-analysis | Recommended |
| **claude-in-chrome** | alf (product reviews), ux-reviewer skill | Optional |
| **pa-server** | pa agent task tracking | Optional (custom, not included) |

---

## 1. Gemini CLI MCP Server

### Purpose

Provides Gemini 3 model access with:
- 1M-token context window for large-file analysis
- Google Search grounding for real-time freshness checks
- Structured brainstorming methodologies
- Third-model verification alongside Claude + Codex

### Tools exposed

| Tool | Purpose |
|------|---------|
| `mcp__gemini-cli__ping` | Availability check (call **before** delegating Gemini work) |
| `mcp__gemini-cli__ask-gemini` | Send any prompt with optional Google Search grounding |
| `mcp__gemini-cli__brainstorm` | Structured brainstorming (SCAMPER, Six Hats, Design Thinking, etc.) |
| `mcp__gemini-cli__fetch-chunk` | Paginate large responses |
| `mcp__gemini-cli__Help` | Tool documentation |
| `mcp__gemini-cli__timeout-test` | Diagnostic |

### Prerequisite

Gemini CLI must be installed locally — see [`local-tools.md`](local-tools.md) §4.

### Install the MCP server

The Gemini CLI MCP server ships with the Gemini CLI package. Register it in Claude Code:

```json
// ~/.claude/settings.json (or .mcp.json)
{
  "mcpServers": {
    "gemini-cli": {
      "command": "gemini",
      "args": ["mcp", "serve"],
      "env": {
        "GOOGLE_CLOUD_PROJECT": ""
      }
    }
  }
}
```

### Critical env var: `GOOGLE_CLOUD_PROJECT=""`

If you authenticate with a **Google subscription** (not an API key), the Gemini CLI MCP server **must** have `GOOGLE_CLOUD_PROJECT` set to an empty string — not unset, not omitted, explicitly empty. Otherwise the server tries to bill against a Cloud project that doesn't exist and fails silently.

If you use an API key instead, set `GEMINI_API_KEY` in the `env` block.

### Verify

Inside a Claude Code session, call:

```
mcp__gemini-cli__ping()
```

Successful response = MCP server is running. Error or timeout = server isn't configured or isn't authenticated.

> **Note**: `ping()` is not a reliable availability check in some Gemini CLI versions — it may succeed even when the underlying model access is broken. If `ping()` succeeds but `ask-gemini` fails, re-check authentication and `GOOGLE_CLOUD_PROJECT`.

### Graceful degradation

If `gemini-cli` MCP is unavailable:
- `forge` runs with Claude + Codex only (no third model)
- `bob` skips the optional Gemini review gate
- `alf` skips real-time freshness checks (lower confidence on version-drift findings)
- `web-research`, `research-for-skills`, `large-file-analysis` fall back to their other sources

No hard failures — gaps are noted explicitly in agent reports.

---

## 2. Claude-in-Chrome MCP Server

### Purpose

Provides browser automation for Chrome, allowing Claude to:
- Navigate pages, read content, interact with forms
- Take screenshots for UX review
- Read console logs and network requests
- Resize viewport for responsive testing

### Used by

- `alf` — full product audits (Core Web Vitals, accessibility, SEO health checks)
- `ux-reviewer` skill — screenshot-based UX reviews

Without it: `alf` degrades to HTTP-only product audits (headers, response times, sitemap, robots.txt) and cannot claim CWV, accessibility, or visual scores.

### Tools exposed

Partial list:

| Tool | Purpose |
|------|---------|
| `mcp__claude-in-chrome__tabs_context_mcp` | Get current tab state (call first) |
| `mcp__claude-in-chrome__tabs_create_mcp` | Open a new tab |
| `mcp__claude-in-chrome__navigate` | Navigate to URL |
| `mcp__claude-in-chrome__read_page` | Read page text |
| `mcp__claude-in-chrome__computer` | Click, type, screenshot |
| `mcp__claude-in-chrome__resize_window` | Change viewport size |
| `mcp__claude-in-chrome__read_console_messages` | Read browser console logs |
| `mcp__claude-in-chrome__read_network_requests` | Read network request log |
| `mcp__claude-in-chrome__javascript_tool` | Execute JS in page context |
| `mcp__claude-in-chrome__gif_creator` | Record multi-step interactions |

### Install

Claude-in-Chrome is distributed as a Chrome extension + MCP server pair. Install both:

1. Install the Chrome extension from the claude-in-chrome repository
2. Install the MCP server (typically via npm or a platform installer)
3. Register in `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "claude-in-chrome": {
      "command": "claude-in-chrome-mcp",
      "args": []
    }
  }
}
```

Refer to the claude-in-chrome project documentation for the current install command.

### Verify

Inside Claude Code, call:

```
mcp__claude-in-chrome__tabs_context_mcp()
```

If it returns tab information, the server is running and Chrome is connected.

### Important usage notes

- **Always call `tabs_context_mcp` first** at session start — never reuse tab IDs across sessions
- **Avoid triggering JavaScript dialogs** (alert, confirm, prompt) — they block all further events and require manual dismissal
- If a page uses dialogs, use `javascript_tool` to dismiss them before interacting

---

## 3. PA Server MCP (custom — not included)

### Purpose

Provides persistent task tracking for the `pa` agent:
- Task CRUD, status transitions, assigned agents
- Session tracking across conversations
- Action logging (every state change is logged)
- FTS5 search over history
- Preference learning
- Enterprise sync (Confluence, Jira) with conflict handling

### Status: **Not included in this repository**

The `pa-server` is a separate, custom MCP server. It is not bundled with the skills/agents in this repository for two reasons:

1. It's a standalone codebase (Python + SQLite)
2. It's specific to the original author's workflow

### Running `pa` without the server

The `pa` agent is designed to **degrade gracefully**:

```
If pa_health() fails (MCP not running or not configured):
  - PA operates in STATELESS MODE
  - Route work to forge/bob/alf/skills normally
  - Cannot: track tasks, log actions, search history, sync remotes
  - Warn user once: "PA running without MCP server — task tracking unavailable.
    Tasks will not persist across sessions."
  - Do NOT block. Do NOT fail. Continue as a router.
```

In stateless mode, `pa` still works as an **intent router** — it classifies requests and routes them to `forge`, `bob`, `alf`, `wiki`, or domain skills. You just lose persistent task state across sessions.

### Building your own

If you want persistent task tracking, build an MCP server implementing these tools (documented in `agents/pa.md`):

**Task management:**
- `pa_create_task(title, description, priority, tags)`
- `pa_update_task(task_id, status, assigned_agent, ...)`
- `pa_query_tasks(status, priority, tags, limit)`
- `pa_get_task(task_id)`

**Actions & logging:**
- `pa_log_action(task_id, action_type, details)`

**Sessions:**
- `pa_start_session(workspace, tool)`
- `pa_end_session(session_id, summary)`

**Search:**
- `pa_search(query)` — FTS5 over task history

**Sync:**
- `pa_sync_confluence()`
- `pa_sync_jira()`
- `pa_get_conflicts()`
- `pa_resolve_conflict(conflict_id, resolution)`

**Preferences:**
- `pa_get_preferences(category)`
- `pa_update_preference(category, key, value, confidence)`
- `pa_clear_preference(category, key)`

**Config:**
- `pa_set_sync_config(source, config)`
- `pa_get_sync_configs()`

**Health:**
- `pa_health()`

The MCP server should back these with SQLite (the reference implementation uses FTS5 for search). Register it in `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "pa-server": {
      "command": "path/to/your/pa-server",
      "args": []
    }
  }
}
```

---

## MCP Server Troubleshooting

### MCP server won't start

1. Check the underlying CLI is installed (Gemini CLI, claude-in-chrome extension, etc.)
2. Check the command in `settings.json` is on your `PATH`
3. Check env vars are set correctly (especially `GOOGLE_CLOUD_PROJECT` for gemini-cli)
4. Look at `~/.claude/logs/` for MCP server startup errors

### Tool calls fail silently

1. Call the server's ping/health tool first (`mcp__gemini-cli__ping`, `mcp__claude-in-chrome__tabs_context_mcp`, `pa_health`)
2. Check authentication — API keys, OAuth tokens, subscription status
3. Restart the Claude Code session to re-initialize MCP servers

### "Tool not found" errors

MCP tools use the format `mcp__<server-name>__<tool-name>`. If the server name in your `settings.json` doesn't match what the skills reference, you'll get tool-not-found errors.

| Skill references | Your `settings.json` must use |
|-----------------|------------------------------|
| `mcp__gemini-cli__*` | Server name: `gemini-cli` |
| `mcp__claude-in-chrome__*` | Server name: `claude-in-chrome` |
| `mcp__pa-server__*` | Server name: `pa-server` |

Renaming a server in `settings.json` breaks every skill that references it — stick to the canonical names above.

---

## Summary

| MCP | Required? | Without it |
|-----|-----------|-----------|
| **gemini-cli** | Strongly recommended | Lose third-model reviews, 1M-context analysis, Google Search grounding |
| **claude-in-chrome** | Optional | Lose full product audits (alf degrades to HTTP-only), lose visual UX reviews |
| **pa-server** | Optional (custom) | `pa` runs in stateless mode — routing works, task tracking disabled |

All three are optional in the sense that nothing hard-fails without them. The agents explicitly check for MCP availability and degrade gracefully with gap notes.
