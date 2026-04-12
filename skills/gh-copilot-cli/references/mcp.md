# MCP Servers in Copilot CLI

Verified locally from `copilot mcp --help` (2026-04-08, `@github/copilot@1.0.21`).

## Configuration sources (verified)

```
User       ~/.copilot/mcp-config.json
Workspace  .mcp.json, .vscode/mcp.json, .devcontainer/devcontainer.json
Plugin     Installed plugins with MCP servers
```

Plus the built-in `github-mcp-server` and any inline `--additional-mcp-config` flag.

Sources are merged. Workspace overrides user; plugin servers are additive.

## Subcommands (verified)

| Command | Purpose |
|---|---|
| `copilot mcp add <name> [url-or-command-and-args...]` | Add a server (transport inferred from URL vs command) |
| `copilot mcp get <name>` | Show server details |
| `copilot mcp list` | List all configured servers |
| `copilot mcp remove <name>` | Remove a server |

## Adding a server

```bash
# Stdio (local process)
copilot mcp add my-tool /usr/local/bin/my-mcp-server --arg1 --arg2

# HTTP/SSE (remote endpoint)
copilot mcp add github-extra https://api.example.com/mcp/sse
```

Transport is **inferred** from the second argument (path/exec → stdio, URL → http/sse).

## Built-in `github-mcp-server`

Copilot ships a built-in MCP server for GitHub API access. Verified flags from `copilot --help`:

| Flag | Purpose |
|---|---|
| `--add-github-mcp-tool <tool>` | Enable specific tool (repeatable, `*` for all) |
| `--add-github-mcp-toolset <toolset>` | Enable a toolset (`all` for all toolsets) |
| `--enable-all-github-mcp-tools` | Enable all GitHub MCP tools (overrides toolset/tool flags) |
| `--disable-builtin-mcps` | Disable all built-in MCPs (currently just github-mcp-server) |
| `--disable-mcp-server github-mcp-server` | Disable just the github MCP server |

The default behaviour is to expose a CLI-curated subset of GitHub MCP tools. Use the flags to broaden or restrict.

## `~/.copilot/mcp-config.json` schema (research-grade)

The exact schema is **`[UNVERIFIED]`** — typical MCP config shape (similar to Claude's `.mcp.json` and Gemini's `mcpServers` block):

```json
{
  "mcpServers": {
    "my-tool": {
      "command": "/usr/local/bin/my-mcp-server",
      "args": ["--arg1"],
      "env": {
        "MY_KEY": "${MY_KEY}"
      }
    },
    "github-extra": {
      "url": "https://api.example.com/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${EXTRA_TOKEN}"
      }
    }
  }
}
```

Verify on first deploy with `copilot mcp list`.

## Workspace-scoped configs

Workspace files (`.mcp.json`, `.vscode/mcp.json`, `.devcontainer/devcontainer.json`) are loaded per-project. They override the user config for matching server names.

`.vscode/mcp.json` is the same file VS Code Copilot Chat reads — share configuration between the CLI and the IDE.

## Ad-hoc MCP per session

```bash
# Inline JSON
copilot -p "..." --allow-all-tools \
  --additional-mcp-config '{"mcpServers":{"throwaway":{"command":"/tmp/test-mcp"}}}'

# From a file
copilot -p "..." --allow-all-tools \
  --additional-mcp-config @./extra-mcp.json
```

The `@` prefix tells Copilot to read the file rather than parse the literal as JSON.

## Restricting servers per invocation

```bash
# Disable all built-ins for this run
copilot -p "..." --allow-all-tools --disable-builtin-mcps

# Disable just github MCP
copilot -p "..." --allow-all-tools --disable-mcp-server github-mcp-server

# Combine with allow/deny tools for fine control
copilot -p "..." --allow-all-tools \
  --disable-mcp-server github-mcp-server \
  --allow-tool='read' \
  --deny-tool='shell(git push)'
```

## Cross-tool MCP sharing

| Tool | Config file |
|---|---|
| Claude Code | `~/.claude/.mcp.json` or `--mcp-config <file>` |
| Gemini CLI | `~/.gemini/settings.json` (`mcpServers` block) |
| Copilot CLI | `~/.copilot/mcp-config.json` + workspace files |

The schemas are similar but not identical. Don't symlink one to another; instead, write the same logical config in each tool's native format.

For project-scoped MCP servers, Copilot's `.mcp.json` is the most portable file location — Claude Code and Gemini can also be configured to read it (via `--mcp-config` or extension manifest).

## Anti-patterns

| Don't | Why |
|---|---|
| Symlink Claude's `.mcp.json` to Copilot's user config | Schemas differ subtly. Write each tool's config separately. |
| Trust the schema until verified | Research-grade. Run `copilot mcp list` after editing to confirm. |
| Use both `--add-github-mcp-tool` and `--enable-all-github-mcp-tools` | The latter overrides the former. Pick one strategy. |
| Forget that workspace files override user config | A `.vscode/mcp.json` in the cwd silently shadows your `~/.copilot/mcp-config.json` |
| Disable `github-mcp-server` then complain Copilot can't see PRs | The built-in is the default GitHub bridge. Re-enable or provide an alternative. |
