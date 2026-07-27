# Headless GitHub Copilot CLI

Verified locally from `copilot --help` on `@github/copilot@1.0.21` (2026-04-08).

## The default

```bash
copilot -p "<prompt>" --allow-all-tools
```

`-p, --prompt <text>` puts Copilot in non-interactive mode. The process exits after one response (unless `--autopilot` is set).

**`--allow-all-tools` is required for non-interactive mode** — without it, Copilot will block on first permission prompt that no human is there to answer.

## Verified flag inventory

### Mode and execution

| Flag | Verified | Notes |
|---|---|---|
| `-p, --prompt <text>` | YES | Non-interactive mode |
| `-i, --interactive <prompt>` | YES | Hybrid: run prompt then drop to interactive |
| `--continue` | YES | Resume most recent session |
| `--resume[=sessionId]` | YES | Resume specific session or open picker |
| `--autopilot` | YES | Continue automatically in prompt mode |
| `--max-autopilot-continues <n>` | YES | Cap continuations (default unlimited) |
| `--no-ask-user` | YES | Disable `ask_user` tool — fully autonomous |
| `--acp` | YES | Start as Agent Client Protocol server (same protocol as Gemini's `--acp`) |

### Output

| Flag | Verified | Notes |
|---|---|---|
| `--output-format <text\|json>` | YES | `text` (default) or `json` (JSONL — one JSON object per line) |
| `-s, --silent` | YES | Output only the agent response (no stats), useful with `-p` |
| `--stream <on\|off>` | YES | Streaming mode toggle |
| `--no-color` | YES | Disable color output |
| `--plain-diff` | YES | Disable rich diff rendering |

### Permissions (the most important section)

| Flag | Verified | Notes |
|---|---|---|
| `--allow-all-tools` | YES | **Required for `-p` mode**. Allow all tools without confirmation. (env: `COPILOT_ALLOW_ALL`) |
| `--allow-all-paths` | YES | Disable file path verification |
| `--allow-all-urls` | YES | Allow all URLs without confirmation |
| `--allow-all` | YES | All three above combined |
| `--yolo` | YES | Same as `--allow-all` |
| `--allow-tool[=tools...]` | YES | Whitelist specific tools — supports glob patterns |
| `--deny-tool[=tools...]` | YES | Blacklist specific tools — takes precedence over allow |
| `--allow-url[=urls...]` | YES | Whitelist specific URLs/domains (defaults to HTTPS) |
| `--deny-url[=urls...]` | YES | Blacklist URLs — takes precedence over allow |
| `--available-tools[=tools...]` | YES | Restrict tool inventory the model sees |
| `--excluded-tools[=tools...]` | YES | Remove tools from inventory |
| `--add-dir <directory>` | YES | Add a directory to the allowed list (repeatable) |
| `--disallow-temp-dir` | YES | Prevent automatic access to system temp dir |

#### Tool-pattern syntax (verified examples from `copilot --help`)

```bash
# Allow all git commands except git push
copilot --allow-tool='shell(git:*)' --deny-tool='shell(git push)'

# Allow all file editing
copilot --allow-tool='write'

# Allow all but one specific tool from MCP server "MyMCP"
copilot --deny-tool='MyMCP(denied_tool)' --allow-tool='MyMCP'
```

The pattern is `<category>(<spec>)` where category can be `shell`, `write`, an MCP server name, etc.

#### URL patterns

```bash
# Allow GitHub API access (defaults to HTTPS)
copilot --allow-url=github.com

# Deny access to specific domain over HTTPS
copilot --deny-url=https://malicious-site.com
copilot --deny-url=malicious-site.com   # protocol optional
```

### Models and reasoning

| Flag | Verified | Notes |
|---|---|---|
| `--model <model>` | YES | Override model (e.g. `--model gpt-5.2`) |
| `--effort, --reasoning-effort <level>` | YES | low/medium/high/xhigh |
| `--enable-reasoning-summaries` | YES | Request reasoning summaries for OpenAI models |
| `--experimental` | YES | Enable experimental features |
| `--no-experimental` | YES | Disable experimental features |

### Configuration

| Flag | Verified | Notes |
|---|---|---|
| `--config-dir <directory>` | YES | Override `~/.copilot` |
| `--log-dir <directory>` | YES | Override `~/.copilot/logs/` |
| `--log-level <level>` | YES | none/error/warning/info/debug/all/default |
| `--no-custom-instructions` | YES | **Disable loading from AGENTS.md and related files** |
| `--no-auto-update` | YES | Disable auto-update (off by default in CI) |
| `--bash-env[=value]` | YES | Enable BASH_ENV support (on/off) |
| `--no-bash-env` | YES | Disable BASH_ENV |
| `--mouse[=value]` | YES | Mouse support in alt screen mode |
| `--no-mouse` | YES | Disable mouse support |
| `--screen-reader` | YES | Accessibility mode |
| `--banner` | YES | Show startup banner |

### Plugins and MCP

| Flag | Verified | Notes |
|---|---|---|
| `--plugin-dir <directory>` | YES | Load plugin from local dir (repeatable) |
| `--disable-builtin-mcps` | YES | Disable built-in MCPs (currently `github-mcp-server`) |
| `--disable-mcp-server <name>` | YES | Disable a specific MCP server (repeatable) |
| `--additional-mcp-config <json-or-@file>` | YES | Add ad-hoc MCP servers, augments `~/.copilot/mcp-config.json` |
| `--add-github-mcp-tool <tool>` | YES | Add a tool to enable for github-mcp-server (repeatable, `*` for all) |
| `--add-github-mcp-toolset <toolset>` | YES | Add a toolset (`all` for all toolsets) |
| `--enable-all-github-mcp-tools` | YES | Enable all GitHub MCP server tools (overrides toolset/tool) |

### Sharing and secrets

| Flag | Verified | Notes |
|---|---|---|
| `--share[=path]` | YES | Save session to markdown after completion (default `./copilot-session-<id>.md`) |
| `--share-gist` | YES | Save session as a secret GitHub gist |
| `--secret-env-vars[=vars...]` | YES | Strip and redact named env vars from shell/MCP environment and output |

### Custom agents and plugins

| Flag | Verified | Notes |
|---|---|---|
| `--agent <agent>` | YES | Specify a custom agent to use |
| `--plugin-dir <directory>` | YES | Load plugin from a local directory (repeatable) |

The custom agent format is **`[UNVERIFIED]`** — see `references/custom-agents.md`.

## Common patterns

```bash
# Minimal headless
copilot -p "fix the bug" --allow-all-tools

# CI-safe with JSON output
copilot -p "lint and fix" \
  --allow-all-tools \
  --autopilot --max-autopilot-continues 10 \
  --output-format json -s \
  --no-auto-update

# Locked-down: only specific tools
copilot -p "review the diff" \
  --allow-tool='read' \
  --allow-tool='shell(git diff)' \
  --allow-tool='shell(git log:*)' \
  --deny-tool='write' \
  --deny-tool='shell(git push)'

# YOLO mode
copilot -p "do whatever it takes" --yolo

# Resume previous session
copilot -p "continue" --continue --allow-all-tools

# Capture session as artifact
copilot -p "implement feature X" --allow-all-tools --share=./session.md

# Redact secrets
COPILOT_GITHUB_TOKEN=... \
copilot -p "do thing" --allow-all-tools \
  --secret-env-vars=COPILOT_GITHUB_TOKEN,DB_PASSWORD
```

## JSON output format

`--output-format json` emits **JSONL** — one JSON object per line, not a single JSON document. Parse with `jq -c .` or stream into your application:

```bash
copilot -p "list TODOs" --allow-all-tools --output-format json -s | while IFS= read -r line; do
  echo "$line" | jq .
done
```

The exact schema of the JSONL events is **`[UNVERIFIED]`** — capture sample output with `-s` and inspect.

## Equivalent to other CLIs

> The **gemini CLI column was removed 2026-07-26** — that CLI was retired from this ecosystem on
> 2026-07-25 and has no fallback path. `agy` (Antigravity CLI) is the third CLI on this host.
> See `antigravity-cli`.

| Claude Code | Antigravity CLI (`agy`) | Copilot CLI |
|---|---|---|
| `claude -p` | `agy -p` — **all flags BEFORE `-p`**, prompt LAST, and `< /dev/null` is mandatory | `copilot -p` |
| `--output-format json` | (none — plain text on stdout only; callers must parse text) | `--output-format json` (JSONL) |
| `--permission-mode bypassPermissions` | `--dangerously-skip-permissions` — still runs inside `--sandbox` | `--yolo` / `--allow-all` |
| `--permission-mode plan` | (none) | (no direct equivalent — use `--available-tools` to limit to read-only set) |
| `--allowedTools` | (not verified — do not assume; see `antigravity-cli` §Not verified) | `--allow-tool[=...]` |
| `--add-dir` | `--add-dir` | `--add-dir` |
| `--bare` (CI-safe minimal) | `--sandbox` (advisory/read-only default) | `--allow-all-tools --no-custom-instructions` (closest) |
| `--from-pr` | (none) | (none — use `gh pr view` and pipe) |
| `--max-budget-usd` | (none) | (none — use `--max-autopilot-continues` for cap on continuations) |
