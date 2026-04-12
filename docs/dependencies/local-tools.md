# Local Tools & Environment Setup

This document covers local CLI tools, Claude Code plugins, and environment variables referenced by the skills and agents in this repository.

---

## 1. Claude Code CLI (required)

All skills and agents in this repository are designed for **Claude Code CLI**.

### Install

```bash
# macOS / Linux
curl -fsSL https://claude.ai/install.sh | bash

# Or via npm
npm install -g @anthropic-ai/claude-code
```

### Verify

```bash
claude --version
```

### Configure

Place the contents of this repository into Claude Code's config directory:

```bash
# Skills
cp -r skills/* ~/.claude/skills/

# Agents
cp -r agents/*.md ~/.claude/agents/
```

On next session start, Claude Code will auto-discover them.

---

## 2. Codex CLI (recommended)

The `forge`, `bob`, and `alf` agents use Codex (GPT-5.4) as a second-opinion model for challenger reviews and rescue operations. Without Codex, those agents fall back to Claude-only reasoning.

### Install

Codex CLI is published by OpenAI. Install from the official source:

```bash
# macOS / Linux (Homebrew)
brew install openai/tap/codex

# Or via npm
npm install -g @openai/codex

# Or via pip
pip install openai-codex-cli
```

Check the official Codex documentation for the current install method.

### Verify

```bash
codex --version
```

### Authentication

Codex requires an OpenAI API key or ChatGPT Plus/Pro subscription login. Follow the `codex login` flow on first run.

### Used by

- `forge` — challenger reviews, parallel research
- `bob` — optional review gate before reporting complete
- `alf` — freshness research, adversarial reviews
- `codex-orchestration` skill
- `challenger` skill

---

## 3. Codex Plugin for Claude Code (recommended)

The agents prefer Codex plugin slash commands over raw `codex exec` because they provide job tracking, resume capability, and structured output.

### Slash commands used by agents

| Command | Used by |
|---------|---------|
| `/codex:setup` | forge (availability check) |
| `/codex:rescue` | forge, alf (independent research) |
| `/codex:adversarial-review` | forge, alf, bob (challenger reviews) |
| `/codex:review` | bob (code review gate) |
| `/codex:status` | forge, bob (check background jobs) |
| `/codex:result` | forge, bob (retrieve background results) |

### Install

The Codex plugin is installed via the Claude Code plugin marketplace:

```bash
# Inside a Claude Code session
/plugin install codex
```

Or check the plugin marketplace repository for the current install flow.

### Verify

Inside a Claude Code session, run:

```
/codex:setup
```

If the command is recognized, the plugin is installed.

### Fallback

If the Codex plugin is unavailable, agents fall back to raw `codex exec` calls — functional but without background job tracking. If Codex CLI itself is unavailable, agents skip Codex work entirely and note the gap in reports.

---

## 4. Gemini CLI (recommended)

The `forge`, `bob`, `alf`, `challenger`, `web-research`, `research-for-skills`, and `large-file-analysis` skills call Gemini 3 via MCP for:

- Third-model verification (alongside Claude + Codex)
- Large-file analysis (1M-token context window)
- Google Search grounding for real-time freshness checks
- Structured brainstorming

See [`mcp-servers.md`](mcp-servers.md) for MCP setup. If you don't want the MCP wrapper, you can invoke the CLI directly via the `gemini-cli` skill.

### Install

```bash
# macOS / Linux (Homebrew)
brew install google/tap/gemini-cli

# Or via npm
npm install -g @google/gemini-cli
```

### Verify

```bash
gemini --version
```

### Authentication

Gemini CLI supports multiple auth modes:

- **Google subscription** (Google One AI Premium, etc.) — use OAuth login via `gemini login`
- **API key** — set `GEMINI_API_KEY` environment variable

> **Important**: If using a Google subscription (not API key), the Gemini CLI MCP server needs `GOOGLE_CLOUD_PROJECT=` (empty string) in its environment to avoid trying to bill against a Cloud project. See [`mcp-servers.md`](mcp-servers.md) for MCP config.

---

## 5. GitHub Copilot CLI (optional)

Only needed if you use the `gh-copilot-cli` skill. Not required for any agent.

```bash
# Install GitHub CLI first
brew install gh

# Then the Copilot extension
gh extension install github/gh-copilot
```

Verify:

```bash
gh copilot --version
```

---

## 6. Environment Variables

### Required for specific skills

| Variable | Used by | Purpose |
|----------|---------|---------|
| `GOOGLE_CLOUD_PROJECT` (empty string) | Gemini CLI MCP server | Forces subscription auth instead of Cloud billing |
| `GEMINI_API_KEY` | `nano-banana`, `gemini-cli`, Gemini CLI MCP (if using API key auth) | Gemini API authentication |
| `VERTEX_API_KEY` | `vertex-banana` (fallback image generation) | Vertex AI authentication |

### Required for Confluence integration

| Variable | Used by | Purpose |
|----------|---------|---------|
| `CONFLUENCE_TOKEN` | `confluence-rest-api`, `confluence-documentation`, `pa` sync | API token |
| `CONFLUENCE_BASE` | Same | Base URL (e.g., `https://yourcompany.atlassian.net/wiki`) |
| `CONFLUENCE_USER` | Same | Email/username |

### Required for Jira integration

| Variable | Used by | Purpose |
|----------|---------|---------|
| `JIRA_TOKEN` | `jira-rest-api`, `pa` sync | API token |
| `JIRA_BASE` | Same | Base URL (e.g., `https://yourcompany.atlassian.net`) |
| `JIRA_USER` | Same | Email/username |

### Setting variables

Add to your shell profile (`~/.bashrc`, `~/.zshrc`, or equivalent):

```bash
# Gemini CLI MCP — forces subscription auth (even if empty)
export GOOGLE_CLOUD_PROJECT=""

# Atlassian (only if you use Confluence/Jira skills)
export CONFLUENCE_TOKEN="your-api-token"
export CONFLUENCE_BASE="https://yourcompany.atlassian.net/wiki"
export CONFLUENCE_USER="you@company.com"

export JIRA_TOKEN="your-api-token"
export JIRA_BASE="https://yourcompany.atlassian.net"
export JIRA_USER="you@company.com"
```

> **Security**: The `pa` agent explicitly **refuses to store tokens or credentials** in its database. Sync configs reference environment variable **names** only, never values. Keep secrets in your environment, never in config files checked into git.

---

## 7. Claude Code Hooks (optional)

Some skills reference `settings.json` hooks for automated behaviors. If you want to replicate the full behavior of skills like `development-lifecycle` or `project-documentation`, you may configure hooks in `~/.claude/settings.json`. See the `update-config` skill for details.

Hooks are **not required** — all skills work without them; hooks just automate some behaviors.

---

## Minimum vs Recommended vs Full Install

| Tier | What you install |
|------|-----------------|
| **Minimum** | Claude Code CLI only |
| **Recommended** | Claude Code CLI + Codex CLI + Codex plugin + Gemini CLI + Gemini CLI MCP + `GOOGLE_CLOUD_PROJECT=""` env var |
| **Full** | Recommended + claude-in-chrome MCP + pa-server MCP (custom, see `mcp-servers.md`) + Confluence/Jira env vars if using those skills |

---

## Verification Checklist

After installation, verify each component works:

```bash
# Claude Code
claude --version

# Codex CLI
codex --version

# Gemini CLI
gemini --version

# Codex plugin (run inside Claude Code session)
/codex:setup

# Gemini MCP (run inside Claude Code session)
# Use the ping tool: mcp__gemini-cli__ping
```

If any component is missing, the agents will note the gap in their reports and continue with reduced capability — they **never hard-fail** because of missing optional tools.
