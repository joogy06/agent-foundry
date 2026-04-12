# Configuration, Packaging, Common Patterns, and Best Practices

Reference file for the `mcp-server-creator` skill. Covers configuration (Claude Desktop, settings.json), packaging/distribution, common patterns (database, file system, API wrapper), best practices, and quick reference.

## Configuration

### Claude Desktop

Add your server to `claude_desktop_config.json`:

```json
// macOS: ~/Library/Application Support/Claude/claude_desktop_config.json
// Windows: %APPDATA%\Claude\claude_desktop_config.json
// Linux: ~/.config/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "my-server": {
      "command": "node",
      "args": ["/absolute/path/to/dist/index.js"],
      "env": {
        "API_KEY": "your-key-here"
      }
    },
    "python-server": {
      "command": "python",
      "args": ["/absolute/path/to/server.py"],
      "env": {
        "DATABASE_URL": "sqlite:///data.db"
      }
    },
    "uvx-server": {
      "command": "uvx",
      "args": ["my-mcp-package"]
    },
    "npx-server": {
      "command": "npx",
      "args": ["-y", "my-mcp-package"]
    },
    "docker-server": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "my-mcp-image"]
    },
    "remote-sse-server": {
      "url": "http://localhost:3001/sse"
    }
  }
}
```

### Claude Code

Add MCP servers to your project or user settings:

```bash
# Add a stdio server to the project
claude mcp add my-server -- node /path/to/dist/index.js

# Add with environment variables
claude mcp add my-server -e API_KEY=abc123 -- node /path/to/dist/index.js

# Add a remote SSE server
claude mcp add my-server --transport sse --url http://localhost:3001/sse

# List configured servers
claude mcp list

# Remove a server
claude mcp remove my-server
```

These commands write to `.claude/settings.json` in the project:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "node",
      "args": ["/path/to/dist/index.js"],
      "env": {
        "API_KEY": "abc123"
      }
    }
  }
}
```

### Environment Variables

Pass secrets and configuration via environment variables. Never hardcode them.

```typescript
// TypeScript — read from environment
const apiKey = process.env.API_KEY;
if (!apiKey) {
  console.error("API_KEY environment variable is required");
  process.exit(1);
}
```

```python
# Python — read from environment
import os
api_key = os.environ.get("API_KEY")
if not api_key:
    raise RuntimeError("API_KEY environment variable is required")
```

---

## Packaging

### npm (TypeScript)

```json
// package.json
{
  "name": "my-mcp-server",
  "version": "1.0.0",
  "description": "An MCP server for ...",
  "type": "module",
  "bin": {
    "my-mcp-server": "./dist/index.js"
  },
  "files": ["dist"],
  "scripts": {
    "build": "tsc",
    "prepublishOnly": "npm run build"
  },
  "keywords": ["mcp", "model-context-protocol"],
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.12.0",
    "zod": "^3.24.0"
  }
}
```

```bash
# Ensure shebang is present in dist/index.js
# #!/usr/bin/env node

# Build and publish
npm run build
npm publish

# Users install and run with:
npx -y my-mcp-server
# or
npx @your-scope/my-mcp-server
```

### PyPI (Python)

```toml
# pyproject.toml
[project]
name = "my-mcp-server"
version = "1.0.0"
description = "An MCP server for ..."
requires-python = ">=3.10"
dependencies = ["mcp>=1.6.0"]

[project.scripts]
my-mcp-server = "my_mcp_server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

```bash
# Build and publish
uv build
uv publish

# Users install and run with:
uvx my-mcp-server
# or
pip install my-mcp-server && my-mcp-server
```

### Docker

```dockerfile
# Dockerfile
FROM node:22-slim AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
ENTRYPOINT ["node", "dist/index.js"]
```

```bash
docker build -t my-mcp-server .
# Run with stdio (requires -i for stdin)
docker run -i --rm -e API_KEY=abc123 my-mcp-server
```

---

## Common Patterns

### Database Query Server

```typescript
// A read-only database query server
import Database from "better-sqlite3";

const db = new Database(process.env.DB_PATH || "data.db", { readonly: true });

server.tool(
  "query",
  "Execute a read-only SQL query against the database. Only SELECT statements are allowed.",
  {
    sql: z.string().min(1).describe("SQL SELECT query"),
  },
  async ({ sql }) => {
    const normalized = sql.trim().toUpperCase();
    if (!normalized.startsWith("SELECT")) {
      return {
        isError: true,
        content: [{ type: "text", text: "Only SELECT queries are permitted" }],
      };
    }
    try {
      const rows = db.prepare(sql).all();
      return {
        content: [{
          type: "text",
          text: JSON.stringify(rows, null, 2),
        }],
      };
    } catch (error: any) {
      return {
        isError: true,
        content: [{ type: "text", text: `Query error: ${error.message}` }],
      };
    }
  }
);
```

### API Wrapper Server (Python)

```python
import httpx
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("github-api")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
BASE_URL = "https://api.github.com"

def _headers():
    h = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h

@mcp.tool()
async def list_repos(org: str, per_page: int = 10) -> str:
    """List repositories for a GitHub organization.

    Args:
        org: GitHub organization name.
        per_page: Number of repos to return (max 100).
    """
    per_page = min(per_page, 100)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/orgs/{org}/repos",
            headers=_headers(),
            params={"per_page": per_page, "sort": "updated"},
            timeout=30,
        )
        resp.raise_for_status()
        repos = resp.json()
        # Return only relevant fields — avoid leaking tokens or internal data
        return json.dumps([
            {"name": r["name"], "url": r["html_url"], "stars": r["stargazers_count"]}
            for r in repos
        ], indent=2)

@mcp.tool()
async def get_issue(owner: str, repo: str, issue_number: int) -> str:
    """Get details about a specific GitHub issue.

    Args:
        owner: Repository owner (user or org).
        repo: Repository name.
        issue_number: Issue number.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/repos/{owner}/{repo}/issues/{issue_number}",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        issue = resp.json()
        return json.dumps({
            "title": issue["title"],
            "state": issue["state"],
            "body": issue["body"][:2000],
            "labels": [l["name"] for l in issue["labels"]],
            "created_at": issue["created_at"],
        }, indent=2)
```

### Authentication and Secrets Handling

<!-- HARD-RULE: NEVER expose credentials, API keys, tokens, or secrets in tool responses. Secrets must only be read from environment variables and used internally. Tool outputs are visible to the AI model and potentially to users. -->

```typescript
// CORRECT — secrets stay internal
server.tool("check_api_status", "Check if the external API is reachable", {},
  async () => {
    const apiKey = process.env.API_KEY;  // read from env, never from params
    const resp = await fetch("https://api.example.com/status", {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    // Return status only — never the key or auth headers
    return {
      content: [{ type: "text", text: `API status: ${resp.status} ${resp.statusText}` }],
    };
  }
);

// WRONG — never do this
server.tool("bad_example", "NEVER DO THIS", {},
  async () => {
    return {
      content: [{
        type: "text",
        // DANGER: This exposes secrets in the tool response!
        text: `Connected with key: ${process.env.API_KEY}`,
      }],
    };
  }
);
```

### Rate Limiting

```typescript
class RateLimiter {
  private timestamps: number[] = [];
  constructor(
    private maxRequests: number,
    private windowMs: number,
  ) {}

  async acquire(): Promise<void> {
    const now = Date.now();
    this.timestamps = this.timestamps.filter(t => now - t < this.windowMs);
    if (this.timestamps.length >= this.maxRequests) {
      const waitMs = this.timestamps[0] + this.windowMs - now;
      await new Promise(resolve => setTimeout(resolve, waitMs));
    }
    this.timestamps.push(Date.now());
  }
}

const limiter = new RateLimiter(10, 60_000); // 10 requests per minute

server.tool("rate_limited_call", "Call an external API with rate limiting", {
  endpoint: z.string(),
}, async ({ endpoint }) => {
  await limiter.acquire();
  const resp = await fetch(endpoint);
  return { content: [{ type: "text", text: await resp.text() }] };
});
```

### Caching

```typescript
const cache = new Map<string, { data: string; expiry: number }>();

function getCached(key: string, ttlMs: number, fetcher: () => Promise<string>): Promise<string> {
  const cached = cache.get(key);
  if (cached && cached.expiry > Date.now()) {
    return Promise.resolve(cached.data);
  }
  return fetcher().then(data => {
    cache.set(key, { data, expiry: Date.now() + ttlMs });
    return data;
  });
}

server.tool("cached_lookup", "Look up data with 5-minute cache", {
  query: z.string(),
}, async ({ query }) => {
  const data = await getCached(query, 5 * 60_000, () => expensiveLookup(query));
  return { content: [{ type: "text", text: data }] };
});
```

---

## Best Practices

### Tool Naming

- Use `snake_case`: `get_user`, `search_records`, `create_issue`.
- Be specific: `query_postgres` is better than `query`. `search_jira_issues` is better than `search`.
- Use verb-first naming: `get_`, `list_`, `create_`, `update_`, `delete_`, `search_`, `run_`.
- Keep names short but unambiguous. The AI reads these names.

### Description Writing

Descriptions are consumed by the AI model to decide when and how to use a tool. Write them for an AI audience:

```typescript
// GOOD — specific, says what it returns, mentions limitations
"Search the PostgreSQL users table by name or email. Returns up to 50 matching records with id, name, email, and created_at fields. Does not return password hashes or tokens."

// BAD — vague, doesn't help the AI decide when to use it
"Search users"
```

### Input Schema Design

- Use `describe()` on every parameter — the AI needs context to fill them correctly.
- Set sensible defaults with `.default()` so tools work with minimal input.
- Use enums (`z.enum()`) when the set of valid values is known.
- Mark optional parameters with `.optional()` rather than allowing null.
- Keep parameter count low (under 6). Use an object parameter for complex inputs.

<!-- HARD-RULE: Validate all inputs. Never trust input from the AI model. Always validate types, ranges, allowed values, and sanitize strings used in queries or shell commands. -->

### Idempotent Tools

Prefer tools that produce the same result when called multiple times with the same input. The AI model may retry tool calls. If a tool has side effects (creating records, sending emails), document this clearly:

```typescript
server.tool(
  "send_notification",
  "Send a notification to a user. WARNING: This sends a real notification — calling it multiple times will send duplicates. Use get_notification_status first to check if already sent.",
  { userId: z.string(), message: z.string() },
  async ({ userId, message }) => {
    // Consider adding idempotency keys
    const idempotencyKey = `${userId}:${hashMessage(message)}`;
    if (await alreadySent(idempotencyKey)) {
      return { content: [{ type: "text", text: "Notification already sent" }] };
    }
    await sendNotification(userId, message, idempotencyKey);
    return { content: [{ type: "text", text: "Notification sent" }] };
  }
);
```

### Security Considerations

1. **Path Traversal** — Always validate and normalize file paths against an allowed base directory. Reject `..` sequences.
2. **SQL Injection** — Use parameterized queries. Never interpolate user input into SQL strings.
3. **Command Injection** — Never pass tool inputs to shell commands via `exec()`. Use `execFile()` with explicit argument arrays.
4. **Secrets in Output** — Never include API keys, tokens, passwords, connection strings, or internal URLs in tool responses.
5. **Resource Limits** — Set timeouts on external calls. Limit response sizes. Cap result counts.
6. **Network Access** — Be explicit about what hosts your server connects to. Consider allowlists for URLs.

```typescript
// Parameterized query — SAFE
const rows = db.prepare("SELECT * FROM users WHERE name = ?").all(name);

// String interpolation — VULNERABLE, never do this
const rows = db.prepare(`SELECT * FROM users WHERE name = '${name}'`).all();
```

```python
# Safe subprocess call — use argument list, not shell string
import subprocess
result = subprocess.run(["ls", "-la", validated_path], capture_output=True, text=True)

# DANGEROUS — never do this
result = subprocess.run(f"ls -la {user_input}", shell=True, capture_output=True)
```

### Server Structure for Larger Projects

```
my-mcp-server/
├── src/
│   ├── index.ts          # Entry point — creates server, attaches transport
│   ├── server.ts         # McpServer instance and capability registration
│   ├── tools/
│   │   ├── index.ts      # Registers all tools on the server
│   │   ├── database.ts   # Database query tools
│   │   └── api.ts        # API wrapper tools
│   ├── resources/
│   │   ├── index.ts      # Registers all resources
│   │   └── files.ts      # File-based resources
│   ├── prompts/
│   │   └── index.ts      # Registers all prompts
│   └── utils/
│       ├── cache.ts
│       ├── rate-limit.ts
│       └── validation.ts
├── test/
│   └── server.test.ts
├── package.json
└── tsconfig.json
```

---

## Quick Reference

### Start a New TypeScript MCP Server

```bash
mkdir my-server && cd my-server
npm init -y
npm install @modelcontextprotocol/sdk zod
npm install -D typescript @types/node
npx tsc --init --outDir dist --rootDir src --declaration
mkdir src
# Edit src/index.ts — see "Minimal Server" section above
npm run build && npx @modelcontextprotocol/inspector node dist/index.js
```

### Start a New Python MCP Server

```bash
uv init my-server && cd my-server
uv add mcp
# Edit server.py — see "Minimal Server" section above
npx @modelcontextprotocol/inspector python server.py
```

### Connect to Claude Code

```bash
claude mcp add my-server -- node /absolute/path/to/dist/index.js
# or for Python:
claude mcp add my-server -- python /absolute/path/to/server.py
```

### Hard Rules Summary

<HARD-RULE>
Never expose credentials, API keys, tokens, or secrets in tool responses. Tool outputs are visible to the model and users.
</HARD-RULE>

<HARD-RULE>
Validate all inputs. Never trust data from the AI model. Check types, ranges, and sanitize strings used in queries or commands.
</HARD-RULE>

<HARD-RULE>
Handle all errors gracefully. A single tool failure must not crash the server process. Catch exceptions in every tool handler and return `isError: true` responses.
</HARD-RULE>
