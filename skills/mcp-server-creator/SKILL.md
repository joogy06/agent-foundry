---
name: mcp-server-creator
description: Use when building MCP servers — Model Context Protocol specification, server implementation in TypeScript and Python, defining tools with JSON Schema parameters, resources and resource templates, prompts, transport layers (stdio, SSE, streamable HTTP), error handling, testing with MCP Inspector, packaging and distribution, and integration with Claude Code and other MCP clients.
---

# MCP Server Creator

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [config-packaging-patterns.md](config-packaging-patterns.md) | configuration (Claude Desktop, settings.json), packaging/distribution, common patterns (database, file system, API wrapper), best practices, and quick reference |
| [prompts-transport-testing.md](prompts-transport-testing.md) | prompts, transport layers (stdio, SSE, streamable HTTP), error handling patterns, and testing strategies |
| [server-implementation.md](server-implementation.md) | TypeScript and Python server implementation, tools definition with JSON Schema, and resources/resource templates |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Letting tool errors crash the server process | One failed tool call kills the entire MCP server; all connected clients lose their session | Catch all exceptions in tool handlers; return `isError: true` with a descriptive message; never let errors propagate |
| Defining tools without proper JSON Schema parameter validation | Invalid inputs cause cryptic runtime errors; no feedback to the LLM about what went wrong | Define complete JSON Schema with types, required fields, descriptions, and enums; validate inputs before processing |
| Using SSE transport when stdio would work | SSE adds HTTP complexity, CORS issues, and authentication overhead for local-only tools | Use stdio for CLI-launched servers (simplest, most reliable); SSE/streamable HTTP only for remote/web deployments |
| Not implementing resource templates for dynamic content | Every piece of dynamic content requires a dedicated tool call; inefficient for LLMs that need to browse/discover | Use resource templates with URI patterns for collections; tools for actions, resources for data access |
| Returning massive payloads from tools | LLMs have context limits; a 100KB tool response wastes tokens and may be truncated | Paginate large results; return summaries with drill-down options; stream large outputs when possible |
