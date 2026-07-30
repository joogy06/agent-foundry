# MCP Server Implementation

Reference file for the `mcp-server-creator` skill. Covers TypeScript and Python server implementation, tools definition with JSON Schema, and resources/resource templates.

## Overview

The Model Context Protocol (MCP) is an open standard that lets AI models interact with external data sources and tools through a unified client-server architecture. An MCP **host** (Claude Desktop, Claude Code, an IDE) runs an MCP **client** that connects to one or more MCP **servers**. Each server exposes **tools**, **resources**, and **prompts** that the AI model can discover and invoke at runtime.

### Core Architecture

```
Host (Claude Desktop / Claude Code / IDE)
  └── MCP Client
        ├── MCP Server A  (database tools)
        ├── MCP Server B  (API wrappers)
        └── MCP Server C  (file system access)
```

### Protocol Lifecycle

> **Superseded by the 2026-07-28 revision, which removed the handshake.** Protocol version,
> client identity and capabilities now travel in `_meta` on **every request**, so there is no
> connection to establish and no session to track — any instance can answer any request. The
> sequence below describes the PREVIOUS era, which a 12-month sunset keeps alive for existing
> clients. Know which era you are targeting before writing either. See `mcp-integration` §1.

**Previous era (pre-2026-07-28):**

1. **Initialize** — Client sends `initialize` with its protocol version and capabilities. Server responds with its own capabilities (tools, resources, prompts it supports).
2. **Initialized** — Client sends `initialized` notification. The connection is now active.
3. **Ongoing Communication** — Client calls tools, reads resources, gets prompts. Server can send notifications (resource changes, progress updates, log messages).
4. **Shutdown** — Either side closes the transport. Servers should clean up resources gracefully.

**Current era:** every request is self-describing and independent. Capability declaration still
exists — the table below remains accurate for what a server advertises — but it is no longer
negotiated once at connection time.

### Capability Negotiation

Servers declare what they support during initialization:

| Capability | Purpose |
|------------|---------|
| `tools` | Executable functions the model can call |
| `resources` | Data the model can read (files, DB rows, API responses) |
| `prompts` | Reusable prompt templates with arguments |
| `logging` | Server can emit log messages |

---

## TypeScript Server

Use `@modelcontextprotocol/sdk` (the official TypeScript SDK). The `McpServer` class provides a high-level API for defining tools, resources, and prompts.

### Project Setup

```bash
mkdir my-mcp-server && cd my-mcp-server
npm init -y
npm install @modelcontextprotocol/sdk zod
npm install -D typescript @types/node
npx tsc --init --outDir dist --rootDir src --declaration
```

```json
// tsconfig.json — key fields
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "Node16",
    "moduleResolution": "Node16",
    "outDir": "./dist",
    "rootDir": "./src",
    "declaration": true,
    "strict": true
  }
}
```

```json
// package.json — key fields
{
  "type": "module",
  "bin": { "my-mcp-server": "./dist/index.js" },
  "scripts": {
    "build": "tsc",
    "start": "node dist/index.js"
  }
}
```

### Minimal Server with a Tool

```typescript
// src/index.ts
#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const server = new McpServer({
  name: "my-mcp-server",
  version: "1.0.0",
});

// Define a tool with Zod schema for input validation
server.tool(
  "get_weather",                          // tool name
  "Get current weather for a city",       // description (consumed by AI)
  {                                       // input schema using Zod
    city: z.string().describe("City name, e.g. 'London'"),
    units: z.enum(["celsius", "fahrenheit"]).default("celsius")
      .describe("Temperature units"),
  },
  async ({ city, units }) => {            // handler — receives validated params
    // Your implementation here
    const temp = units === "celsius" ? "22°C" : "72°F";
    return {
      content: [
        { type: "text", text: `Weather in ${city}: ${temp}, partly cloudy` }
      ],
    };
  }
);

// Start with stdio transport
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("MCP server running on stdio");   // stderr for logs, stdout for protocol
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
```

> **Important:** Always log to `stderr`. The MCP protocol uses `stdout` for JSON-RPC messages. Anything written to `stdout` that is not valid JSON-RPC will break the transport.

### Tool Returning an Error

```typescript
server.tool(
  "divide",
  "Divide two numbers",
  {
    numerator: z.number(),
    denominator: z.number(),
  },
  async ({ numerator, denominator }) => {
    if (denominator === 0) {
      return {
        isError: true,
        content: [{ type: "text", text: "Error: Division by zero" }],
      };
    }
    return {
      content: [{ type: "text", text: String(numerator / denominator) }],
    };
  }
);
```

### Tool Returning an Image

```typescript
server.tool(
  "generate_chart",
  "Generate a chart image",
  { data: z.array(z.number()).describe("Data points for the chart") },
  async ({ data }) => {
    const base64Image = await renderChart(data); // your rendering logic
    return {
      content: [
        { type: "image", data: base64Image, mimeType: "image/png" },
        { type: "text", text: `Chart with ${data.length} data points` },
      ],
    };
  }
);
```

---

## Python Server

Use the `mcp` package (official Python SDK). The `FastMCP` class provides a decorator-based API.

### Project Setup

```bash
# Using uv (recommended)
uv init my-mcp-server && cd my-mcp-server
uv add mcp

# Or with pip
pip install mcp
```

### Minimal Server with a Tool

```python
# server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-mcp-server")

@mcp.tool()
def get_weather(city: str, units: str = "celsius") -> str:
    """Get current weather for a city.

    Args:
        city: City name, e.g. 'London'
        units: Temperature units — 'celsius' or 'fahrenheit'
    """
    temp = "22°C" if units == "celsius" else "72°F"
    return f"Weather in {city}: {temp}, partly cloudy"

if __name__ == "__main__":
    mcp.run()  # defaults to stdio transport
```

Python uses type hints and docstrings for schema generation. The function signature becomes the JSON Schema input, and the docstring becomes the tool description.

### Async Tools

```python
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("api-server")

@mcp.tool()
async def fetch_url(url: str) -> str:
    """Fetch the contents of a URL.

    Args:
        url: The URL to fetch (must be https)
    """
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS URLs are allowed")
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=30)
        response.raise_for_status()
        return response.text[:5000]  # truncate large responses
```

### Resources and Prompts in Python

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("full-server")

# Static resource
@mcp.resource("config://app")
def get_app_config() -> str:
    """Return application configuration."""
    return '{"theme": "dark", "language": "en"}'

# Dynamic resource with URI template
@mcp.resource("users://{user_id}/profile")
def get_user_profile(user_id: str) -> str:
    """Return user profile data."""
    return f'{{"id": "{user_id}", "name": "User {user_id}"}}'

# Prompt template
@mcp.prompt()
def review_code(code: str, language: str = "python") -> str:
    """Generate a code review prompt."""
    return f"Review this {language} code for bugs, security issues, and improvements:\n\n```{language}\n{code}\n```"
```

---

## Tools

Tools are the primary way MCP servers expose functionality. The AI model sees tool names, descriptions, and input schemas, then decides when and how to call them.

### Anatomy of a Tool Definition

Every tool has three parts:

| Part | Purpose |
|------|---------|
| `name` | Unique identifier. Use `snake_case`. Keep short: `query_db`, `send_email`. |
| `description` | Natural language explanation for the AI. Be specific about what the tool does, what it returns, and when to use it. |
| `inputSchema` | JSON Schema defining accepted parameters with types, constraints, descriptions. |

### Parameter Validation (TypeScript)

```typescript
server.tool(
  "search_records",
  "Search database records with filters. Returns up to 'limit' matching records.",
  {
    query: z.string().min(1).max(500)
      .describe("Search query string"),
    table: z.enum(["users", "orders", "products"])
      .describe("Table to search"),
    limit: z.number().int().min(1).max(100).default(10)
      .describe("Max results to return"),
    offset: z.number().int().min(0).default(0)
      .describe("Pagination offset"),
    filters: z.record(z.string()).optional()
      .describe("Key-value filter pairs, e.g. {\"status\": \"active\"}"),
  },
  async ({ query, table, limit, offset, filters }) => {
    const results = await db.search(table, query, { limit, offset, filters });
    return {
      content: [{
        type: "text",
        text: JSON.stringify(results, null, 2),
      }],
    };
  }
);
```

### Returning Embedded Resources

A tool can return content that references a resource URI, helping the client track provenance:

```typescript
server.tool(
  "read_log_file",
  "Read the most recent application log file",
  { lines: z.number().int().default(50).describe("Number of lines to return") },
  async ({ lines }) => {
    const logContent = await readLastLines("/var/log/app.log", lines);
    return {
      content: [{
        type: "resource",
        resource: {
          uri: "file:///var/log/app.log",
          mimeType: "text/plain",
          text: logContent,
        },
      }],
    };
  }
);
```

### Progress Reporting for Long-Running Tools

```typescript
server.tool(
  "bulk_import",
  "Import records from a CSV file. Reports progress during import.",
  { filePath: z.string().describe("Path to CSV file") },
  async ({ filePath }, { reportProgress }) => {
    const rows = await parseCsv(filePath);
    let imported = 0;
    for (const row of rows) {
      await insertRecord(row);
      imported++;
      // Report progress to the client
      await reportProgress({ progress: imported, total: rows.length });
    }
    return {
      content: [{ type: "text", text: `Imported ${imported} records` }],
    };
  }
);
```

### Python Tool with Error Handling

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("safe-server")

@mcp.tool()
def query_database(sql: str, database: str = "main") -> str:
    """Execute a read-only SQL query.

    Args:
        sql: SQL SELECT query to execute. Only SELECT statements are allowed.
        database: Database name to query against.
    """
    # Validate input
    normalized = sql.strip().upper()
    if not normalized.startswith("SELECT"):
        raise ValueError("Only SELECT queries are allowed")

    dangerous = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE"]
    if any(kw in normalized for kw in dangerous):
        raise ValueError(f"Query contains forbidden keywords")

    try:
        results = execute_query(database, sql)
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        raise ValueError(f"Query failed: {e}")
```

> When a Python tool raises an exception, FastMCP automatically converts it to an error response with `isError: true`.

---

## Resources

Resources let servers expose data that can be read by clients. Unlike tools (which perform actions), resources represent data the AI can pull into its context.

### Static Resources (TypeScript)

```typescript
import { ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";

// Fixed-URI resource
server.resource(
  "app-config",                           // internal name
  "config://app",                         // URI
  "Application configuration settings",   // description
  async () => ({
    contents: [{
      uri: "config://app",
      mimeType: "application/json",
      text: JSON.stringify(getConfig()),
    }],
  })
);
```

### Dynamic Resources with URI Templates (TypeScript)

```typescript
// URI template with parameter
server.resource(
  "user-profile",
  new ResourceTemplate("users://{userId}/profile", {
    list: async () => ({
      resources: (await db.getAllUserIds()).map(id => ({
        uri: `users://${id}/profile`,
        name: `Profile for user ${id}`,
        mimeType: "application/json",
      })),
    }),
  }),
  "User profile data",
  async (uri, { userId }) => ({
    contents: [{
      uri: uri.href,
      mimeType: "application/json",
      text: JSON.stringify(await db.getUser(userId)),
    }],
  })
);
```

### File-Based Resources (Python)

```python
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("file-server")

@mcp.resource("files://{path}")
def read_file(path: str) -> str:
    """Read a file from the allowed directory.

    Args:
        path: Relative path within the project directory.
    """
    # HARD-RULE: Validate path to prevent directory traversal
    base = "/opt/project"
    full_path = os.path.normpath(os.path.join(base, path))
    if not full_path.startswith(base):
        raise ValueError("Path traversal detected")
    if not os.path.isfile(full_path):
        raise FileNotFoundError(f"File not found: {path}")
    with open(full_path, "r") as f:
        return f.read()
```

### Database Query Resource

```python
@mcp.resource("db://tables")
def list_tables() -> str:
    """List all tables in the database."""
    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return json.dumps([t[0] for t in tables])

@mcp.resource("db://tables/{table_name}/schema")
def get_table_schema(table_name: str) -> str:
    """Get the schema for a specific table.

    Args:
        table_name: Name of the database table.
    """
    # Validate table name — only alphanumeric and underscores
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
        raise ValueError("Invalid table name")
    schema = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    columns = [{"name": r[1], "type": r[2], "nullable": not r[3]} for r in schema]
    return json.dumps(columns, indent=2)
```

---

