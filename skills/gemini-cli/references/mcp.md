# MCP Servers in Gemini CLI

Verified from local `gemini mcp --help` (2026-04-08, gemini 0.36.0):

```
gemini mcp

Manage MCP servers

Commands:
  gemini mcp add <name> <commandOrUrl> [args...]  Add a server
  gemini mcp remove <name>                        Remove a server
  gemini mcp list                                 List all configured MCP servers
  gemini mcp enable <name>                        Enable an MCP server
  gemini mcp disable <name>                       Disable an MCP server
```

Simpler than Claude's `mcp` surface (Claude has `add`, `add-json`, `get`, `list`, `remove`, `serve`, `reset-project-choices`).

## Adding an MCP server

```bash
# Stdio server
gemini mcp add my-tool /usr/local/bin/my-mcp-server --arg1 --arg2

# HTTP server (transport inferred from URL)
gemini mcp add github-mcp https://api.example.com/mcp/sse
```

Transport is **inferred** from the second argument:

| Argument shape | Inferred transport |
|---|---|
| Path or executable name | stdio |
| `http://` or `https://` URL | http or sse |

There is no explicit `--transport` flag in Gemini's `--help`. If you need fine control over transport semantics, edit `~/.gemini/settings.json` directly.

## Listing and managing

```bash
gemini mcp list                  # what's configured
gemini mcp enable <name>         # turn on
gemini mcp disable <name>        # turn off
gemini mcp remove <name>         # delete
```

## Restricting per-invocation

```bash
GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY= gemini -p --allowed-mcp-server-names github,linter "review this PR"
```

Only the named MCP servers are exposed to the model for this invocation. Useful for sandboxing CI runs.

## Already installed (this machine)

`~/.gemini/extensions/nanobanana` is installed and provides image generation via Vertex AI. Do NOT touch this directory — it is the user's working extension.

To use it from a `gemini -p` call:

```bash
GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY= gemini -p -e nanobanana "generate a thumbnail for this blog post"
```

## Settings.json MCP block

The full configuration lives in `~/.gemini/settings.json`. Schema is **UNVERIFIED** locally — see `references/settings-schema.md`.

A typical block looks like (research-grade):

```json
{
  "mcpServers": {
    "my-tool": {
      "command": "/usr/local/bin/my-mcp-server",
      "args": ["--arg1"],
      "env": {"FOO": "bar"}
    },
    "github-mcp": {
      "url": "https://api.example.com/mcp/sse"
    }
  }
}
```

The `gemini mcp add` command writes to this section.

## Building your own MCP server

See the `mcp-server-creator` skill for full Model Context Protocol implementation guidance (TypeScript, Python, Stdio/SSE/HTTP transports, tools, resources, prompts).

## Anti-patterns

| Don't | Why |
|---|---|
| Edit `~/.gemini/extensions/nanobanana` | User's working extension, don't break it |
| Assume Claude's `mcp add-json` works for Gemini | Gemini doesn't have it. Edit `settings.json` directly for complex configs. |
| Use `--allowed-mcp-server-names` without testing the names exist | Typo silently disables ALL MCP servers for that invocation |
| Mix `gemini extensions install` with manual `mcp add` for the same server | Conflicting sources. Pick one (extension OR direct). |
