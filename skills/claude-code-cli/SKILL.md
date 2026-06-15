---
name: claude-code-cli
description: Use when working with the Claude Code CLI (`claude`) — headless and interactive modes, flags, agents, plugins, MCP servers, hooks, settings, sessions, and the local custom ecosystem (forge, bob, alf, pa, wiki, agent-teams). Covers Claude Code 2.1.x. Refresh of the upstream `superpowers:working-with-claude-code` reference plus local-environment additions.
---

# Claude Code CLI

Task-indexed reference for Claude Code 2.1.170 (and the 2.1.x line in general). Forked from the superpowers `working-with-claude-code` skill at v0.3.1, refreshed against local ground truth, and extended with custom files that document this machine's forge/bob/alf/pa/wiki ecosystem.

This SKILL.md is the navigation index. Detailed documentation lives in `references/`. Read only what the current task needs.

## When to use

- Building anything that calls `claude` from the shell or a script (headless `-p` mode)
- Authoring or debugging Claude Code agents, skills, plugins, hooks, MCP servers
- Editing `~/.claude/settings.json`, `~/.claude/CLAUDE.md`, `~/.claude/AGENTS.md`
- Cross-referencing Claude Code features against Antigravity CLI (agy), Codex CLI, or GitHub Copilot CLI (see `antigravity-cli`, `gh-copilot-cli`, `cross-tool-portability` sub-skill)
- Operating inside the local custom ecosystem (forge, bob, alf, pa, wiki, agent-teams)

## Versions covered

| Component | Version (verified locally 2026-06-10) |
|---|---|
| Claude Code CLI | 2.1.170 |
| Plugin: superpowers (source for forked references) | 0.3.1 |
| Codex plugin | 1.0.2 |

When the local `claude` version drifts from this skill, run `scripts/verify-claude-install.sh` to flag stale sections.

## Quick task index

### Headless / scripted invocation

| Task | Read |
|---|---|
| Run a one-shot prompt and exit | `references/headless.md`, `references/cli-reference.md` |
| Pipe data in / out as JSON | `references/headless.md` (`--input-format`, `--output-format`, `--json-schema`) |
| CI-safe minimal mode (no hooks, no auto-memory, strict API key) | `references/headless.md` (`--bare` section) |
| Cap session $ spend | `references/headless.md` (`--max-budget-usd`) |
| Pin a pre-defined agent for a single invocation | `references/sub-agents.md` (`--agent`, `--agents`) |
| Pick the model / fallback model | `references/model-config.md` |

### Interactive use

| Task | Read |
|---|---|
| Slash commands, key bindings, modes | `references/interactive-mode.md`, `references/slash-commands.md` |
| Output styles, statusline | `references/output-styles.md`, `references/statusline.md` |
| Resume / fork / continue sessions | `references/cli-reference.md` (`--resume`, `--continue`, `--fork-session`, `--session-id`) |
| Built-in git worktree | `references/cli-reference.md` (`-w/--worktree`, `--tmux`) |

### Agents and skills

| Task | Read |
|---|---|
| Author an agent (`~/.claude/agents/<name>.md`) | `references/sub-agents.md` |
| Author a skill (`~/.claude/skills/<name>/SKILL.md`) | `references/skills.md` + the `cross-tool-portability` sub-skill of `research-for-skills` |
| Cross-tool skill that must work in Antigravity (agy)/Codex/Copilot | `research-for-skills/cross-tool-portability/cross-tool-portability.md` |
| Skill discovery / progressive disclosure | `references/skills.md` |

### Orchestration, teams, tasks, scheduling

| Task | Read |
|---|---|
| Workflow tool — script-driven multi-agent orchestration (`agent()`, `pipeline()`, `parallel()`, budget, journal resume) | `references/orchestration.md` |
| Saved/named workflows (`.claude/workflows/`, `~/.claude/workflows/`) | `references/orchestration.md` |
| Effort levels (low→max) and ultracode (v2.1.160+) | `references/orchestration.md` |
| Session cron (CronCreate/CronList/CronDelete), `/loop` pacing (ScheduleWakeup), RemoteTrigger, `/schedule` cloud routines, `/goal` | `references/orchestration.md` |
| Why a subagent cannot fan out (Agent/Workflow = main loop ONLY) and the invert-control pattern | `references/orchestration.md` (KEY ASYMMETRY section) |
| Native agent teams (TeamCreate/SendMessage — experimental, env-gated) | `references/native-teams-tasks.md` |
| Native task lifecycle (TaskCreate/TaskList/TaskGet/TaskUpdate/TaskStop/TaskOutput, Monitor) | `references/native-teams-tasks.md` |
| Teammate hooks (TeammateIdle/TaskCreated/TaskCompleted) | `references/native-teams-tasks.md` |
| Background agents (`run_in_background`, `claude agents` Agent View, `claude --bg --exec`, worktrees + EnterWorktree) | `references/native-teams-tasks.md` |
| Native teams vs the portable file-based `agent-teams` skill | `references/native-teams-tasks.md` |

### Plugins and marketplaces

| Task | Read |
|---|---|
| Install/uninstall/enable/disable a plugin | `references/plugins.md`, `references/cli-reference.md` (`plugin` subcommands) |
| Add a marketplace | `references/plugin-marketplaces.md` |
| Plugin component reference (commands, agents, skills, hooks, MCP, statuslines) | `references/plugins-reference.md` |
| Validate a plugin in development | `claude plugin validate <path>` (see `references/plugins.md`) |

### MCP servers

| Task | Read |
|---|---|
| Add a stdio/http/sse MCP server | `references/mcp.md` (`claude mcp add`, `add-json`) |
| Use a project-local MCP config | `references/mcp.md` (`--mcp-config`, `--strict-mcp-config`) |
| Reset per-project MCP choices | `claude mcp reset-project-choices` |
| Build your own MCP server | use the `mcp-server-creator` skill |

### Hooks and settings

| Task | Read |
|---|---|
| Settings.json schema | `references/settings.md` |
| Hooks lifecycle, events, matchers | `references/hooks.md`, `references/hooks-guide.md` |
| Override settings at the CLI | `--settings`, `--setting-sources` (see `references/cli-reference.md`) |
| Stream hook events to JSON | `--include-hook-events --output-format=stream-json` |

### Memory, context, files

| Task | Read |
|---|---|
| `CLAUDE.md` hierarchy and imports | `references/memory.md` |
| Add context dirs / extra files | `--add-dir`, `--file` (see `references/cli-reference.md`) |
| Custom system prompt | `--system-prompt`, `--append-system-prompt` |
| Checkpoints (auto-save / restore) | `references/checkpointing.md` |

### Authentication and providers

| Task | Read |
|---|---|
| API key / OAuth / token | `references/iam.md`, `claude auth` subcommands |
| Long-lived setup token | `claude setup-token` |
| Amazon Bedrock | `references/amazon-bedrock.md` |
| Google Vertex AI | `references/google-vertex-ai.md` (`CLAUDE_CODE_USE_VERTEX=1`) |
| Custom LLM gateway | `references/llm-gateway.md` |

### Cost, analytics, monitoring

| Task | Read |
|---|---|
| What sessions cost and how it's measured | `references/costs.md` |
| Where data goes | `references/data-usage.md` |
| Analytics export | `references/analytics.md` |
| Monitoring usage in CI | `references/monitoring-usage.md` |

### Editor / IDE integrations

| Task | Read |
|---|---|
| VS Code integration | `references/vs-code.md` |
| JetBrains plugin | `references/jetbrains.md` |
| Dev containers | `references/devcontainer.md` |
| GitHub Actions | `references/github-actions.md` |
| GitLab CI/CD | `references/gitlab-ci-cd.md` |
| Third-party integrations | `references/third-party-integrations.md` |

### Compliance, security, networking

| Task | Read |
|---|---|
| Permission modes (`acceptEdits`, `auto`, `bypassPermissions`, `default`, `dontAsk`, `plan`) | `references/security.md`, `references/cli-reference.md` |
| IAM / token scopes / roles | `references/iam.md` |
| Egress allow-list / firewall | `references/network-config.md` |
| Terminal config | `references/terminal-config.md` |
| Legal / compliance | `references/legal-and-compliance.md` |
| Migration from older versions | `references/migration-guide.md` |
| Troubleshooting | `references/troubleshooting.md` |

### Custom local ecosystem (this machine only)

These are not documented in upstream superpowers — they are specific to this user's setup.

| Task | Read |
|---|---|
| Forge → bob → agent-teams → team-manager → specialists workflow | `references/custom-ecosystem.md` |
| Hard-rules checklist before spawning agents | `references/custom-ecosystem.md` (Hard Rules section) |
| MEMORY index, project context (PROJECT.md, history.md, tasks.md) | `references/custom-ecosystem.md` (Memory + Project Docs sections) |
| 119-skill library, _meta inventory | `references/custom-ecosystem.md` (Skills section) |
| Cross-CLI orchestration: Claude + Codex + Antigravity (agy) in parallel | `references/cross-tool-integration.md` |
| What changed since the Jan 2026 superpowers snapshot | `references/upgrades-since-jan-2026.md` |

## Permission modes (verified from `claude --help`)

Six modes, exactly:

| Mode | Behaviour |
|---|---|
| `default` | Ask before each tool call |
| `acceptEdits` | Auto-allow file edits, ask for everything else |
| `auto` | Run the auto-mode classifier (see `claude auto-mode`) |
| `dontAsk` | Allow tool calls without prompting (use with `--allowedTools`) |
| `bypassPermissions` | Skip permission checks entirely (sandbox/trusted dirs only) |
| `plan` | Read-only planning mode |

`--allow-dangerously-skip-permissions` is a separate opt-in flag and should only be used in sandboxes with no internet access.

## Top-level subcommands (verified)

```
agents       Manage background agents (Agent View dashboard; --json for scripting)
auth         Manage authentication (login/logout/status)
auto-mode    Inspect auto mode classifier configuration
doctor       Check Claude Code auto-updater health
install      Install Claude Code native build
mcp          Configure and manage MCP servers
              add | add-json | get | list | remove | serve | reset-project-choices
plugin       Manage Claude Code plugins
              install | uninstall | enable | disable | list | update | validate
              marketplace { add | list | remove | update }
project      Manage Claude Code project state (purge: delete transcripts/tasks/file history/config)
setup-token  Set up a long-lived authentication token
ultrareview  Run a cloud-hosted multi-agent code review of the current branch / a PR (--json, --timeout)
update       Check for updates and install if available
```

Verified against `claude --help` on 2.1.170 (2026-06-10). `agents` is the background-agent Agent View (see `references/native-teams-tasks.md`), not a list of configured subagents. Use `claude agents --help` for the current sub-options on this machine.

## Headless (`-p`) cheat sheet

```bash
# One-shot prompt, plain text
claude -p "summarize this file" < notes.md

# JSON output for scripts
claude -p --output-format json "list TODOs in this repo"

# Strict structured output
claude -p --output-format json \
  --json-schema '{"type":"object","properties":{"todos":{"type":"array","items":{"type":"string"}}},"required":["todos"]}' \
  "list TODOs"

# Stream-json for incremental processing
claude -p --output-format stream-json --include-partial-messages "long task here"

# CI-safe minimal mode
ANTHROPIC_API_KEY=$KEY claude --bare -p "lint this file" \
  --add-dir . --settings ./ci-settings.json

# Pin a pre-defined agent for the call
claude -p --agent reviewer "review the diff in this branch"

# Inline custom agent
claude -p --agents '{"redactor":{"description":"Redacts secrets","prompt":"You are a secret redactor."}}' \
  --agent redactor "redact secrets from this file"

# Cap spend
claude -p --max-budget-usd 0.50 "research X and report"
```

See `references/headless.md` for the full surface.

## Anti-patterns

| Don't | Why |
|---|---|
| Put complete docs inline in this SKILL.md | Use `references/*.md` — progressive disclosure keeps loading cheap |
| Write `--max-budget-usd` outside `--print` | Flag only works in headless mode |
| Use `--output-format=stream-json` without `--include-partial-messages` for streaming UX | Only stream-json + partial messages emit incremental chunks |
| Edit references in `~/.claude/plugins/cache/...` | That's the read-only plugin cache. Edit only the forked copies in this skill. |
| Assume `~/.claude/AGENTS.md` is auto-loaded by Claude Code | Symlink `AGENTS.md -> CLAUDE.md` works for the user. Native AGENTS.md support is **UNVERIFIED** as of 2026-04-08 — flagged for first-boot test G2 |
| Skip `--bare` in CI when you need reproducibility | Hooks and auto-memory inject non-deterministic context in non-bare mode |
| Run `claude` against `/etc`, `/var`, or other system dirs without `--add-dir` review | Permission scoping silently fails if you don't list the dirs |
| Chain hooks across CLIs without an `AI_CLI_CALL_DEPTH` guard | Claude → Codex → Claude can recurse. Convention only — see `cross-tool-portability/challenger-concerns.md` |
| Forget to run `verify-claude-install.sh` after a `claude update` | Flag surface drifts; this fork goes stale silently |

## Verification

Run `scripts/verify-claude-install.sh` after any `claude update`. The script:

1. Captures `claude --version`, `claude --help`, `claude mcp --help`, `claude plugin --help`, `claude agents --help`
2. Diffs `cli-reference.md` against the new `--help` (loose diff — flag-name only)
3. Sanity-checks `~/.claude/settings.json` exists and parses as JSON
4. Reports drift loud and exits non-zero if anything looks stale

## See also

- `references/custom-ecosystem.md` — forge/bob/alf/pa/wiki/agent-teams stack
- `references/cross-tool-integration.md` — Claude + Codex + Antigravity (agy) orchestration
- `references/upgrades-since-jan-2026.md` — delta vs the superpowers snapshot
- `antigravity-cli` — Antigravity CLI (agy) counterpart
- `gh-copilot-cli` — GitHub Copilot CLI counterpart
- `gcp-workstations` — running this whole stack on a GCP Workstation
- `research-for-skills/cross-tool-portability/` — rules for skills that span multiple CLIs
- `codex-orchestration` — calling Codex CLI from Claude Code
