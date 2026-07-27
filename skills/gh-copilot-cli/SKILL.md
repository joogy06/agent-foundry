---
name: gh-copilot-cli
description: Use when working with GitHub Copilot CLI (`copilot`) — headless and interactive modes, permission flags, AGENTS.md and `.github/copilot-instructions.md`, MCP servers, custom agents, plugins, OAuth device-flow auth, and the bridge to VS Code Copilot Chat. Covers `@github/copilot@1.0.21`. Verified locally on 2026-04-08 against the actual `copilot --help`.
---

# GitHub Copilot CLI

Task-indexed reference for `@github/copilot@1.0.21` (April 2026). Verified locally on 2026-04-08 by installing the package and running `copilot --help`, `copilot init --help`, `copilot mcp --help`, and `copilot login --help`.

This skill is **mostly verified now** (the design doc carried `[UNVERIFIED]` markers because the package was not yet installed at design time — install + verification was performed during execution). Items that are still research-grade are explicitly marked `[UNVERIFIED]`.

## Disclaimer

Install the package and run `scripts/verify-copilot-install.sh` after any `copilot update`. The flag surface and subcommands evolve quickly.

## When to use

- Calling `copilot` from the shell or a script (headless `-p` mode)
- Authoring `.github/copilot-instructions.md`, `.github/instructions/**/*.instructions.md`, or `AGENTS.md` for Copilot consumption
- Adding MCP servers via `~/.copilot/mcp-config.json`
- Authenticating Copilot CLI on a workstation, CI runner, or GCP Workstation
- Bridging Copilot CLI ↔ VS Code Copilot Chat
- Cross-referencing Copilot vs Claude Code, Gemini CLI, or Codex CLI

## Versions covered

| Component | Version (verified locally 2026-04-08) |
|---|---|
| `@github/copilot` | 1.0.21 (npm `npm view @github/copilot version`) |
| Binary name | `copilot` |

## Quick task index

| Task | Read |
|---|---|
| Install Copilot CLI (npm package, brew, winget) | `references/install-and-auth.md` |
| Authenticate (device flow, env tokens) | `references/install-and-auth.md` |
| Headless `-p` invocation, JSON output, autopilot | `references/headless.md` |
| Permission flags (`--allow-all-tools`, `--yolo`, `--allow-tool`, etc.) | `references/headless.md` (Permissions section) |
| Instruction file hierarchy (AGENTS.md vs `.github/copilot-instructions.md`) | `references/instruction-files.md` |
| Custom agents | `references/custom-agents.md` |
| MCP servers (`~/.copilot/mcp-config.json` and workspace files) | `references/mcp.md` |
| Bridge to VS Code Copilot Chat | `references/vs-code-bridge.md` |
| Legacy `gh copilot` extension (suggest/explain) | `references/legacy-gh-copilot.md` |
| First-boot verification procedure | `references/first-boot-verification.md` |

## Verified surface — top-level commands

```
copilot [options] [command]

Commands:
  init                  Initialize Copilot instructions for this repo (writes .github/copilot-instructions.md)
  login [options]       Authenticate with Copilot (OAuth device flow)
  mcp                   Manage MCP servers (add | get | list | remove)
  plugin                Manage plugins
  update                Download the latest version
  version               Display version information
  help [topic]          Display help on a topic (commands, config, environment, logging, monitoring, permissions, providers)
```

Default behaviour (no command): launches interactive mode unless `-p` is set.

## Verified flags (selected)

| Flag | Purpose |
|---|---|
| `-p, --prompt <text>` | Execute a prompt in non-interactive mode (exits after completion) |
| `-i, --interactive <prompt>` | Start interactive mode and immediately execute this prompt |
| `--continue` | Resume the most recent session |
| `--resume[=sessionId]` | Resume a previous session (optional ID), or open picker |
| `--output-format <text\|json>` | `text` (default) or `json` (JSONL: one JSON object per line) |
| `-s, --silent` | Output only the agent response (no stats) — for scripting with `-p` |
| `--allow-all-tools` | Allow all tools without confirmation (REQUIRED for non-interactive) |
| `--allow-all-paths` | Disable file path verification |
| `--allow-all-urls` | Allow all URLs without confirmation |
| `--allow-all` | Equivalent to `--allow-all-tools --allow-all-paths --allow-all-urls` |
| `--yolo` | Same as `--allow-all` |
| `--allow-tool[=tools...]` | Whitelist specific tools |
| `--deny-tool[=tools...]` | Blacklist specific tools |
| `--allow-url[=urls...]` | Whitelist specific URLs/domains |
| `--deny-url[=urls...]` | Blacklist specific URLs/domains |
| `--available-tools[=tools...]` | Restrict the model's tool inventory |
| `--excluded-tools[=tools...]` | Remove tools from the model's inventory |
| `--autopilot` | Enable autopilot continuation in prompt mode |
| `--max-autopilot-continues <count>` | Cap autopilot continuations |
| `--no-ask-user` | Disable the `ask_user` tool (fully autonomous) |
| `--add-dir <directory>` | Allow file access to additional directory (repeatable) |
| `--config-dir <directory>` | Override config dir (default `~/.copilot`) |
| `--log-dir <directory>` | Override log dir (default `~/.copilot/logs/`) |
| `--log-level <level>` | none/error/warning/info/debug/all/default |
| `--model <model>` | Override the default model |
| `--effort <level>` | Reasoning effort: low/medium/high/xhigh |
| `--acp` | Start as Agent Client Protocol server (same protocol as Gemini's `--acp`) |
| `--no-custom-instructions` | Disable loading of custom instructions from **AGENTS.md and related files** |
| `--secret-env-vars[=vars...]` | Strip and redact secret env vars from shell/MCP environments and output |
| `--share[=path]` | Share session to a markdown file after completion (non-interactive) |
| `--share-gist` | Share session to a secret GitHub gist after completion |
| `--stream <on\|off>` | Enable/disable streaming |
| `--add-github-mcp-tool <tool>` | Enable specific tool on built-in github-mcp-server |
| `--enable-all-github-mcp-tools` | Enable all GitHub MCP tools |
| `--disable-mcp-server <name>` | Disable a specific MCP server |
| `--disable-builtin-mcps` | Disable built-in MCPs (currently `github-mcp-server`) |
| `--additional-mcp-config <json-or-@file>` | Add ad-hoc MCP servers for this session |
| `--plugin-dir <directory>` | Load a plugin from a local directory |

`--no-custom-instructions` is the load-bearing flag that proves Copilot **does** read AGENTS.md natively (otherwise the flag would not exist). This was unverified in the design doc and is now confirmed.

## Verified — non-interactive requirement

`--allow-all-tools` is **required** for non-interactive (`-p`) mode. Without it, Copilot would block waiting for permission prompts that no human is there to answer.

```bash
# This will hang or exit on first permission prompt
copilot -p "fix the bug"

# This works
copilot -p "fix the bug" --allow-all-tools

# Or, more aggressive:
copilot -p "fix the bug" --yolo

# Or, scripting-friendly with quiet output:
copilot -p "fix the bug" --allow-all-tools --silent --output-format json
```

## Verified — instruction file loading

From the `--no-custom-instructions` flag description: *"Disable loading of custom instructions from AGENTS.md and related files."*

This confirms Copilot CLI reads:

1. `AGENTS.md` (repo root)
2. `.github/copilot-instructions.md` (set up by `copilot init`)
3. **`[UNVERIFIED]`** `.github/instructions/**/*.instructions.md` with `applyTo:` frontmatter (Copilot docs claim this; not yet locally tested)
4. **`[UNVERIFIED]`** `~/.copilot/copilot-instructions.md` (user global — Copilot docs claim this; not locally tested)

`copilot init` is the canonical way to bootstrap `.github/copilot-instructions.md` — it analyses the repo with read-only tools and writes a contextual instructions file.

## Verified — MCP config locations

From `copilot mcp --help`:

```
Configuration is loaded from multiple sources:
  User       ~/.copilot/mcp-config.json
  Workspace  .mcp.json, .vscode/mcp.json, .devcontainer/devcontainer.json
  Plugin     Installed plugins with MCP servers
```

Subcommands:

| Command | Purpose |
|---|---|
| `copilot mcp add <name> [url-or-command-and-args...]` | Add a server (transport inferred from URL vs command) |
| `copilot mcp get <name>` | Show details for one server |
| `copilot mcp list` | List all configured servers |
| `copilot mcp remove <name>` | Remove |

The built-in `github-mcp-server` is enabled by default. Disable with `--disable-builtin-mcps` or `--disable-mcp-server github-mcp-server`. Tune which github MCP tools are exposed with `--add-github-mcp-tool`, `--add-github-mcp-toolset`, or `--enable-all-github-mcp-tools`.

## Verified — authentication

From `copilot login --help`:

> Authenticate with Copilot via OAuth device flow.
>
> The default authentication mode is a web-based browser flow. After completion, an authentication token will be stored securely in the system credential store. If a credential store is not found or there is an issue using it, the token will be stored in a plain text config file under `~/.copilot/`.
>
> Alternatively, Copilot CLI will use an authentication token found in environment variables. This method is most suitable for "headless" use such as automation. The following are checked in order of precedence: `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`.
>
> Supported token types include fine-grained personal access tokens (v2 PATs) with the "Copilot Requests" permission, OAuth tokens from the GitHub Copilot CLI app, and OAuth tokens from the GitHub CLI (`gh`) app.
>
> Classic personal access tokens (`ghp_`) are NOT supported.

This is fully verified ground truth — see `references/install-and-auth.md` for the full auth section.

## Headless cheat sheet

```bash
# One-shot prompt, plain text
copilot -p "fix the bug in main.js" --allow-all-tools

# JSON output for scripts (JSONL — one object per line)
copilot -p "list TODOs in this repo" --allow-all-tools --output-format json -s

# Resume the most recent session
copilot -p "continue what we were doing" --allow-all-tools --continue

# Resume a specific session
copilot --resume=0cb916db-26aa-40f2-86b5-1ba81b225fd2

# Allow specific tools, deny others
copilot -p "review the diff" \
  --allow-tool='shell(git:*)' \
  --deny-tool='shell(git push)'

# YOLO mode (most aggressive)
copilot -p "do whatever it takes" --yolo

# Add a directory to allowed list
copilot --add-dir /home/user/projects --add-dir /tmp

# Disable AGENTS.md loading
copilot -p "use only system prompt" --no-custom-instructions --allow-all-tools

# CI-safe with autopilot, capped continuations
copilot -p "fix all linter errors" \
  --allow-all-tools \
  --autopilot --max-autopilot-continues 10 \
  --output-format json -s
```

## Anti-patterns

| Don't | Why |
|---|---|
| Use `-p` without `--allow-all-tools` | Will block on first permission prompt |
| Use the package name `@github/copilot-cli` | NPM 404 — the correct name is `@github/copilot` (no `-cli` suffix) |
| Assume `--silent` is the long form | The flag is `-s, --silent`; `--silent` works because of the long form alias, but the design doc had this slightly wrong |
| Use classic `ghp_` PATs | Not supported. Use fine-grained v2 PATs with "Copilot Requests" permission. |
| Skip `copilot init` for new repos | The bootstrapped `.github/copilot-instructions.md` is much better than nothing |
| Edit the OAuth token in `~/.copilot/` directly | Stored in system credential store first; only falls back to plaintext if keychain fails |
| Run with `--yolo` in production | Equivalent to disabling all permission checks. Use `--allow-all-tools` (not paths/URLs) for slightly safer scripting |
| Forget that `-p` mode exits after one response | Use `-i` for hybrid mode (run prompt, then drop into interactive) |
| Set `GH_TOKEN` and expect Copilot to use a different env var | Precedence is `COPILOT_GITHUB_TOKEN` > `GH_TOKEN` > `GITHUB_TOKEN`. Unset higher-precedence vars to use a lower one. |

## See also

- `references/install-and-auth.md` — install paths, package name, full auth flows
- `references/headless.md` — full `-p` flag inventory and examples
- `references/instruction-files.md` — AGENTS.md, `.github/copilot-instructions.md`, paths-with-applyTo, user global
- `references/custom-agents.md` — `--agent` flag, custom agent format `[UNVERIFIED]`
- `references/mcp.md` — MCP server config files, transports, GitHub MCP tools
- `references/vs-code-bridge.md` — relationship between Copilot CLI and VS Code Copilot Chat
- `references/legacy-gh-copilot.md` — old `gh copilot suggest/explain` extension
- `references/first-boot-verification.md` — exact commands to validate after install
- `claude-code-cli` — Claude Code CLI counterpart
- `gcp-workstations/references/auth-per-tool.md` — Copilot device flow on a GCP Workstation
- `research-for-skills/cross-tool-portability/agents-md-canonical.md` — AGENTS.md as canonical content
