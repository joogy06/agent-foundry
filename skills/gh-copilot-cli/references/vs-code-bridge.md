# VS Code Bridge

GitHub Copilot CLI and VS Code Copilot Chat are sibling tools — they share configuration files and conventions, but they are separate processes.

## Shared configuration

| Resource | Location | Used by |
|---|---|---|
| Instruction files | `AGENTS.md`, `.github/copilot-instructions.md` | Both CLI and VS Code Copilot Chat |
| Path-scoped instructions `[UNVERIFIED]` | `.github/instructions/**/*.instructions.md` with `applyTo:` | Both |
| MCP servers (workspace) | `.vscode/mcp.json`, `.mcp.json`, `.devcontainer/devcontainer.json` | Both |
| MCP servers (user, CLI) | `~/.copilot/mcp-config.json` | CLI only |
| MCP servers (user, VS Code) | VS Code settings.json | VS Code only |

The workspace-scoped MCP files (`.vscode/mcp.json` especially) are the natural cross-tool config — both VS Code Copilot Chat and Copilot CLI read them.

## What runs where

| Capability | CLI | VS Code Chat |
|---|---|---|
| Headless `-p` mode | YES | NO |
| JSON output for scripting | YES (JSONL) | NO |
| Permission flags (`--allow-tool`, `--deny-tool`, `--allow-all-tools`) | YES | NO (uses VS Code's prompt UX instead) |
| Custom agents (`--agent`) | YES | YES (via chat participants) |
| MCP servers | YES | YES |
| Plugins | YES (`--plugin-dir`, `copilot plugin`) | YES (VS Code extensions) |
| ACP server mode (`--acp`) | YES | N/A |
| Built-in `github-mcp-server` | YES | YES |
| Session sharing (`--share`, `--share-gist`) | YES | NO |

## Typical CLI ↔ VS Code workflow

1. Open the repo in VS Code with Copilot Chat
2. Edit code interactively, using Copilot Chat for explanations and small edits
3. For larger automated changes, switch to a terminal and run:
   ```bash
   copilot -p "refactor X across Y" --allow-all-tools --autopilot --max-autopilot-continues 20
   ```
4. Both tools read the same `AGENTS.md` and `.github/copilot-instructions.md`, so they share project context

## Copilot Workspaces `/delegate` `[UNVERIFIED]`

Per GitHub blog posts (research-grade), there's a `/delegate` slash command in Copilot Chat that hands off a task to the Copilot CLI Coding Agent (the cloud-side agent) running in a temporary GitHub Actions VM. This is separate from running `copilot` locally.

Not verifiable from local installation alone. Confirm with the latest GitHub Copilot docs.

## Both reading the same instructions: pros and cons

**Pro:** Consistency. The agent has the same context whether you ask in chat or in CLI.

**Con:** AGENTS.md content that's optimised for one mode may not fit the other. CLI tasks tend to be more autonomous (need explicit "do/don't" rules); chat tasks tend to be more conversational.

**Mitigation:** Keep AGENTS.md focused on facts about the project (build commands, conventions, file layout) and put mode-specific guidance in `.github/copilot-instructions.md` or a separate file referenced only by the CLI invocation:

```bash
copilot -p "..." --allow-all-tools --no-custom-instructions
# then use a different env or --add-dir to inject CLI-specific context
```

## Anti-patterns

| Don't | Why |
|---|---|
| Assume the CLI and VS Code share session state | They don't. CLI sessions live in `~/.copilot/`, VS Code sessions live in VS Code's storage. |
| Configure MCP servers in two places | Use `.vscode/mcp.json` for workspace-shared, `~/.copilot/mcp-config.json` for CLI-only. |
| Expect `--allow-tool` to affect VS Code | CLI flag only. VS Code uses its own prompt UX. |
| Use `--autopilot` for VS Code | VS Code Chat has its own continuation model. The CLI flag is unrelated. |
| Trust the `/delegate` claim until verified | Research-grade. May or may not be in the current Copilot Chat. |
