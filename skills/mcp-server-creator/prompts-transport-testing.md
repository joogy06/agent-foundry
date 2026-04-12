# Prompts, Transport, Error Handling, and Testing

Reference file for the `mcp-server-creator` skill. Covers prompts, transport layers (stdio, SSE, streamable HTTP), error handling patterns, and testing strategies.

## Prompts

Prompts are reusable templates that help the AI model generate structured requests. They accept arguments and return one or more messages.

### Simple Prompt (TypeScript)

```typescript
server.prompt(
  "summarize",
  "Summarize a document in a specific style",
  {
    content: z.string().describe("The text to summarize"),
    style: z.enum(["brief", "detailed", "bullet-points"]).default("brief")
      .describe("Summary style"),
  },
  async ({ content, style }) => ({
    messages: [{
      role: "user",
      content: {
        type: "text",
        text: `Summarize the following text in a ${style} style:\n\n${content}`,
      },
    }],
  })
);
```

### Multi-Message Prompt (TypeScript)

```typescript
server.prompt(
  "code_review",
  "Review code with specific focus areas",
  {
    code: z.string().describe("Code to review"),
    language: z.string().default("typescript"),
    focus: z.enum(["security", "performance", "readability", "all"]).default("all"),
  },
  async ({ code, language, focus }) => ({
    messages: [
      {
        role: "user",
        content: {
          type: "text",
          text: `You are reviewing ${language} code. Focus on: ${focus}.`,
        },
      },
      {
        role: "user",
        content: {
          type: "text",
          text: `\`\`\`${language}\n${code}\n\`\`\``,
        },
      },
    ],
  })
);
```

### Dynamic Prompt with Resource Context (Python)

```python
@mcp.prompt()
def debug_error(error_message: str, log_file: str = "app.log") -> list[dict]:
    """Create a debugging prompt that includes relevant log context.

    Args:
        error_message: The error message to debug.
        log_file: Log file to include for context.
    """
    logs = read_recent_logs(log_file, lines=50)
    return [
        {"role": "user", "content": f"I'm seeing this error: {error_message}"},
        {"role": "user", "content": f"Here are the recent logs:\n```\n{logs}\n```"},
        {"role": "user", "content": "What is causing this error and how do I fix it?"},
    ]
```

---

## Transport Layers

MCP supports three transport mechanisms. The transport is how the client and server exchange JSON-RPC messages.

### stdio (Standard I/O)

Best for: local integrations, CLI tools, Claude Desktop, Claude Code.

The client spawns the server as a child process. Messages flow over stdin/stdout. This is the simplest and most common transport.

```typescript
// TypeScript — stdio server
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new McpServer({ name: "my-server", version: "1.0.0" });
// ... define tools, resources, prompts ...

const transport = new StdioServerTransport();
await server.connect(transport);
```

```python
# Python — stdio server
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("my-server")
# ... define tools, resources, prompts ...
mcp.run()  # uses stdio by default
# or explicitly: mcp.run(transport="stdio")
```

### SSE (Server-Sent Events)

Best for: remote servers accessible over HTTP, servers shared across multiple clients.

```typescript
// TypeScript — SSE server
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import express from "express";

const app = express();
const server = new McpServer({ name: "my-server", version: "1.0.0" });
// ... define tools ...

let transport: SSEServerTransport;

app.get("/sse", (req, res) => {
  transport = new SSEServerTransport("/messages", res);
  server.connect(transport);
});

app.post("/messages", (req, res) => {
  transport.handlePostMessage(req, res);
});

app.listen(3001, () => console.error("SSE MCP server on port 3001"));
```

### Streamable HTTP

Best for: production deployments, stateless servers, serverless environments. This is the modern replacement for SSE that supports both streaming and non-streaming use cases.

```typescript
// TypeScript — Streamable HTTP server
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import express from "express";

const app = express();
app.use(express.json());

const server = new McpServer({ name: "my-server", version: "1.0.0" });
// ... define tools ...

app.post("/mcp", async (req, res) => {
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: undefined,  // stateless
  });
  await server.connect(transport);
  await transport.handleRequest(req, res);
});

app.listen(3001, () => console.error("Streamable HTTP MCP server on port 3001"));
```

### Choosing the Right Transport

| Transport | Use Case | Pros | Cons |
|-----------|----------|------|------|
| **stdio** | Local CLI, Claude Desktop/Code | Simplest, no networking | Local only |
| **SSE** | Remote HTTP server | Works over network, streaming | Requires persistent connection |
| **Streamable HTTP** | Production, serverless | Stateless, scalable, modern | Slightly more complex setup |

---

## Error Handling

<!-- HARD-RULE: Handle all errors gracefully — never crash the server. An unhandled exception in a tool handler must not terminate the MCP server process. -->

### MCP Error Codes

The protocol defines standard error codes (JSON-RPC 2.0 compatible):

| Code | Name | Meaning |
|------|------|---------|
| -32700 | Parse error | Invalid JSON received |
| -32600 | Invalid request | Request object is invalid |
| -32601 | Method not found | Tool/method does not exist |
| -32602 | Invalid params | Invalid method parameters |
| -32603 | Internal error | Server-side error |

### Tool Error Responses (TypeScript)

Return `isError: true` to indicate a tool-level error without crashing:

```typescript
server.tool(
  "risky_operation",
  "Perform an operation that may fail",
  { input: z.string() },
  async ({ input }) => {
    try {
      const result = await performOperation(input);
      return {
        content: [{ type: "text", text: JSON.stringify(result) }],
      };
    } catch (error) {
      // Return error to the model — server keeps running
      return {
        isError: true,
        content: [{
          type: "text",
          text: `Operation failed: ${error instanceof Error ? error.message : String(error)}`,
        }],
      };
    }
  }
);
```

### Global Error Handler (TypeScript)

Wrap your server startup to prevent crashes:

```typescript
async function main() {
  const server = new McpServer({ name: "my-server", version: "1.0.0" });
  // ... define tools ...

  const transport = new StdioServerTransport();

  // Handle transport errors
  transport.onerror = (error) => {
    console.error("Transport error:", error);
  };

  // Handle server errors
  server.server.onerror = (error) => {
    console.error("Server error:", error);
  };

  // Handle process signals for graceful shutdown
  process.on("SIGINT", async () => {
    console.error("Shutting down...");
    await server.close();
    process.exit(0);
  });

  await server.connect(transport);
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
```

### Python Error Handling

```python
from mcp.server.fastmcp import FastMCP
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("safe-server")

@mcp.tool()
def safe_operation(input_data: str) -> str:
    """Perform an operation with proper error handling.

    Args:
        input_data: The input to process.
    """
    try:
        result = process(input_data)
        return json.dumps(result)
    except ValueError as e:
        # Validation errors — raise to convert to isError response
        raise ValueError(f"Invalid input: {e}")
    except Exception as e:
        logger.exception("Unexpected error in safe_operation")
        raise RuntimeError(f"Operation failed: {e}")
```

---

## Testing

### MCP Inspector

The MCP Inspector is the primary debugging tool. It provides a web UI to connect to your server, browse tools/resources/prompts, and invoke them interactively.

```bash
# Run Inspector against a stdio server
npx @modelcontextprotocol/inspector node dist/index.js

# Run Inspector against a Python server
npx @modelcontextprotocol/inspector python server.py

# Run Inspector with environment variables
npx @modelcontextprotocol/inspector -e API_KEY=abc123 node dist/index.js

# Run Inspector against an SSE server
npx @modelcontextprotocol/inspector --url http://localhost:3001/sse
```

The Inspector opens a browser UI where you can:
- See all registered tools, resources, and prompts
- Call tools with custom inputs and see responses
- Read resources and inspect their contents
- Test prompts with arguments
- View raw JSON-RPC messages for debugging

### Manual Testing with stdio

You can pipe JSON-RPC messages directly to test a stdio server:

```bash
# Send initialize + tool call manually
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}}}' | node dist/index.js
```

### Automated Testing (TypeScript)

```typescript
// test/server.test.ts
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { describe, it, expect } from "vitest";

describe("MCP Server", () => {
  let client: Client;
  let server: McpServer;

  beforeEach(async () => {
    server = new McpServer({ name: "test-server", version: "1.0.0" });
    // Register tools on server...
    server.tool("add", "Add numbers", { a: z.number(), b: z.number() },
      async ({ a, b }) => ({
        content: [{ type: "text", text: String(a + b) }],
      })
    );

    // Create linked in-memory transports
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();

    client = new Client({ name: "test-client", version: "1.0.0" });
    await Promise.all([
      client.connect(clientTransport),
      server.connect(serverTransport),
    ]);
  });

  it("should add numbers", async () => {
    const result = await client.callTool("add", { a: 2, b: 3 });
    expect(result.content).toEqual([{ type: "text", text: "5" }]);
  });

  it("should list tools", async () => {
    const tools = await client.listTools();
    expect(tools.tools).toHaveLength(1);
    expect(tools.tools[0].name).toBe("add");
  });
});
```

### Automated Testing (Python)

```python
# test_server.py
import pytest
from mcp.server.fastmcp import FastMCP

# Import your server instance
from server import mcp

@pytest.mark.anyio
async def test_get_weather():
    """Test the get_weather tool directly via the FastMCP test helpers."""
    async with mcp.test_client() as client:
        result = await client.call_tool("get_weather", {"city": "London"})
        assert "London" in result.content[0].text
        assert result.isError is None or result.isError is False

@pytest.mark.anyio
async def test_list_tools():
    async with mcp.test_client() as client:
        tools = await client.list_tools()
        tool_names = [t.name for t in tools.tools]
        assert "get_weather" in tool_names
```

---

