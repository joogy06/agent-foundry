---
name: setup
description: First-time permission setup for Agent Foundry. Upgrades from conservative baseline to full autonomous config. Run once per project or globally.
---

# Setup — Agent Foundry Permission Configuration

Configures Claude Code permissions for autonomous agentic sessions. The repo ships with conservative per-command allow rules. This skill upgrades to full autonomous mode.

## When to Use

- First time running Claude Code in the agent-foundry repo
- After cloning and copying skills to `~/.claude/skills/`
- When you want to switch between conservative and autonomous modes

## Checklist

1. **Detect current state** — check what permissions are already configured
2. **Present options** — show the user what each level does
3. **Apply chosen config** — write settings to the appropriate location
4. **Verify** — confirm the config is valid and will take effect

---

## Step 1: Detect Current State

Read the following files and report what exists:

```
# Project-level (applies when running claude inside this repo)
.claude/settings.json          # shared baseline (committed)
.claude/settings.local.json    # power-user override (gitignored)

# User-level (applies to all projects)
~/.claude/settings.json        # global settings
```

Check each for:
- `permissions.defaultMode` value
- Whether `Bash(*)` is in the allow list (blanket vs granular)
- Whether `Bash(git push*)` is in the ask list
- Any MCP tool allow rules

Report the current state concisely:
> "Current: [conservative/autonomous/custom] at [project/global] level. [Details]."

## Step 2: Present Options

Present exactly these three options:

> **Permission levels:**
>
> **1. Conservative (current default)**
> `acceptEdits` mode + granular bash rules. Each command type explicitly allowed. Git push, reset --hard, rm -rf prompt. Safe for exploring.
>
> **2. Full autonomous**
> `acceptEdits` mode + `Bash(*)` blanket. Everything auto-approved except `git push` (still prompts). Best for productive agentic sessions.
>
> **3. Full autonomous + MCP**
> Same as (2) plus auto-approve all MCP tools (Gemini, pa-server, chrome). Best for multi-model workflows with forge/bob/alf.
>
> **Scope:**
> - **Project** — writes `.claude/settings.local.json` (gitignored). Only applies in this repo.
> - **Global** — writes `~/.claude/settings.json`. Applies to all projects.
>
> **Which level? (1/2/3) And scope? (project/global)**

Wait for the user's response.

## Step 3: Apply Config

### Level 2 — Full Autonomous

```json
{
  "permissions": {
    "defaultMode": "acceptEdits",
    "ask": [
      "Bash(git push*)"
    ],
    "allow": [
      "Bash(*)",
      "Agent",
      "WebFetch",
      "WebSearch",
      "NotebookEdit"
    ]
  }
}
```

### Level 3 — Full Autonomous + MCP

```json
{
  "permissions": {
    "defaultMode": "acceptEdits",
    "ask": [
      "Bash(git push*)"
    ],
    "allow": [
      "Bash(*)",
      "Agent",
      "WebFetch",
      "WebSearch",
      "NotebookEdit",
      "mcp__gemini-cli__*",
      "mcp__pa-server__*",
      "mcp__claude-in-chrome__*"
    ]
  }
}
```

### Scope: Project

Write to `.claude/settings.local.json` in the repo root. This file is gitignored and overrides the shared `.claude/settings.json` at precedence level 3 (above shared project settings at level 4).

### Scope: Global

Write to `~/.claude/settings.json`. **Important**: this file may already contain other settings (hooks, plugins, etc.). Read the existing file first and MERGE the permissions block — do not overwrite other keys.

## Step 4: Verify

After writing:

1. Validate JSON syntax: `python3 -c "import json; json.load(open('<path>'))"` 
2. Report what was written and where
3. Tell the user: "Restart `claude` (or start a new session) to pick up the new permissions. The status bar should show `accept edits on`."

## Reverting

To revert to conservative mode:
- **Project scope**: delete `.claude/settings.local.json`
- **Global scope**: remove the `permissions` block from `~/.claude/settings.json`
