# Custom agents — `.agent.md` reference

Current to 2026-06-24, from the official VS Code "Custom agents" + "Customize AI" docs.
A custom agent is a Markdown file: **YAML frontmatter** (config) + **body** (the agent's
system instructions). The filename minus `.agent.md` is the default agent `name`.

## Storage locations (first match wins; `chat.agentFilesLocations` extends)

| Scope | Path |
|---|---|
| Workspace (Copilot) | `.github/agents/<name>.agent.md` |
| Workspace (Claude format) | `.claude/agents/<name>.agent.md` |
| User profile (travels across projects) | `~/.copilot/agents/<name>.agent.md` |

## Frontmatter fields

| Field | Type | Meaning |
|---|---|---|
| `name` | string | agent identifier (defaults to filename) |
| `description` | string | shown as placeholder/hint text |
| `tools` | list | available tools — built-ins, **toolsets**, MCP tools, extension-contributed tools. Use `<server-name>/*` to include all tools of one MCP server |
| `model` | string \| array | the model; an array expresses a prioritized fallback order |
| `agents` | list | subagents this agent may call (as tools) |
| `handoffs` | list | sequential transitions to other agents (see below) |
| `argument-hint` | string | guidance text for the user |
| `user-invocable` | bool (default `true`) | whether it appears in the agents dropdown |
| `disable-model-invocation` | bool (default `false`) | prevent the model from invoking this as a subagent (human-only) |
| `target` | `vscode` \| `github-copilot` | which environment the agent targets |
| `mcp-servers` | object | MCP server configs scoped to this agent |
| `hooks` | object | hook commands scoped to this agent (guardrails) |

## Tools — least privilege

`tools` is a YAML list. Give each agent only what its role needs:
- A **Plan/analysis** agent → read-only tools (search, read files), **no** edit/terminal.
- A **Build** agent → edit + terminal + the specific MCP tools it needs.
- A **Review** agent → read + test-run tools.

Reference an entire MCP server's tools with `myserver/*`; reference one with `myserver/toolname`.

## Handoffs — building an agentic flow

`handoffs` is a list of transition objects; each renders as a button / can auto-submit:

| Handoff key | Meaning |
|---|---|
| `label` | button text |
| `agent` | target agent's `name` |
| `prompt` | prompt text seeded into the target agent |
| `send` | bool (default `false`) — auto-submit the prompt instead of waiting |
| `model` | optional model override for the handoff |

A Plan → Build → Review pipeline is the canonical shape; keep tools least-privilege per stage.

## Example — a read-only "Plan" agent that hands off to "Build"

```markdown
---
name: plan
description: Produce an implementation plan (read-only), then hand off to build.
tools: [codebase, search, usages, fetch]
model: [gpt-5, claude-sonnet-4-6]
user-invocable: true
handoffs:
  - label: Build this plan
    agent: build
    prompt: "Implement the plan above. Follow the repo conventions in AGENTS.md."
    send: false
---
You are a planning agent. Analyse the codebase and produce a concrete, step-by-step
implementation plan with file-level changes and a test strategy. Do NOT edit files or run
commands — you have read-only tools by design. End with a short risk list.
```

```markdown
---
name: build
description: Implement an approved plan with edits + terminal, then hand off to review.
tools: [edit, codebase, runCommands, problems, testFailure]
model: gpt-5
handoffs:
  - label: Review
    agent: review
    prompt: "Review the diff for correctness, security, and test coverage."
---
Implement the plan exactly. Run the test suite and fix failures in a loop. Keep changes
minimal and match existing style.
```

## Subagents vs handoffs

- **Handoffs** = explicit, user-visible *sequential* transitions (Plan→Build→Review).
- **`agents:` (subagents)** = agents callable *as tools* mid-task. Set
  `disable-model-invocation: true` on a subagent to keep it human-triggered only.
