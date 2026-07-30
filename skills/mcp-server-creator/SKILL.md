---
name: mcp-server-creator
description: Use when building MCP servers — Model Context Protocol specification, server implementation in TypeScript and Python, defining tools with JSON Schema parameters, resources and resource templates, prompts, transport layers (stdio, SSE, streamable HTTP), error handling, testing with MCP Inspector, packaging and distribution, and integration with Claude Code and other MCP clients.
disambiguation: BUILDING an MCP server — SDK code, tool and resource definitions, packaging, testing. Consuming servers from an application (selection, auth, trust, context cost, the stateless migration) is mcp-integration; adding servers to VS Code is vscode-agents.
---

# MCP Server Creator

> ## Protocol revision 2026-07-28 — reconciled 2026-07-29
>
> **The 2026-07-28 specification made the protocol core stateless**, removing the
> `initialize`/`initialized` handshake and the `Mcp-Session-Id` header, deprecating the legacy
> HTTP+SSE transport, replacing server-initiated elicitation/sampling/roots with **Multi Round-Trip
> Requests**, adding `Mcp-Method`/`Mcp-Name` routing headers and `ttlMs`/`cacheScope` on list
> results, and making RFC 9207 issuer validation mandatory.
>
> **The affected sections are now marked**, and the scope was narrower than first recorded: the
> handshake and transport material sits in `prompts-transport-testing.md` (transport section,
> comparison table, manual `initialize` probe) and `server-implementation.md` (protocol lifecycle).
> Tools, resources, prompts, error handling, testing, packaging and configuration are **unaffected
> and remain current**.
>
> **SDK code for the new revision is deliberately NOT reproduced here.** It has not been verified
> against the SDKs from this machine, and inventing plausible examples for an unread spec would be
> worse than pointing at the source. Read `mcp-integration` §1 for the change list, then the
> specification and your SDK's migration notes.
>
> A 12-month minimum sunset applies, so existing servers are not broken — but new ones should target
> the current revision.

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [config-packaging-patterns.md](config-packaging-patterns.md) | configuration (Claude Desktop, settings.json), packaging/distribution, common patterns (database, file system, API wrapper), best practices, and quick reference |
| [prompts-transport-testing.md](prompts-transport-testing.md) | prompts, transport layers (stdio, Streamable HTTP; SSE deprecated), error handling patterns, and testing strategies |
| [server-implementation.md](server-implementation.md) | TypeScript and Python server implementation, tools definition with JSON Schema, and resources/resource templates |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Letting tool errors crash the server process | One failed tool call kills the entire MCP server; all connected clients lose their session | Catch all exceptions in tool handlers; return `isError: true` with a descriptive message; never let errors propagate |
| Defining tools without proper JSON Schema parameter validation | Invalid inputs cause cryptic runtime errors; no feedback to the LLM about what went wrong | Define complete JSON Schema with types, required fields, descriptions, and enums; validate inputs before processing |
| Using an HTTP transport when stdio would work | It adds CORS, an auth surface and an availability dependency to what was a subprocess | stdio for client-launched servers; **Streamable HTTP** for remote. SSE is deprecated — do not adopt it |
| Not implementing resource templates for dynamic content | Every piece of dynamic content requires a dedicated tool call; inefficient for LLMs that need to browse/discover | Use resource templates with URI patterns for collections; tools for actions, resources for data access |
| Returning massive payloads from tools | LLMs have context limits; a 100KB tool response wastes tokens and may be truncated | Paginate large results; return summaries with drill-down options; stream large outputs when possible |

## See also

- `mcp-integration` — the **consumer** side generally: whether MCP is the right interface, the
  2026-07-28 stateless revision and its compatibility break, auth and CIMD, the context cost of tool
  lists, and treating third-party servers as untrusted code.
- `vscode-agents` — the consumer side in VS Code specifically (`.vscode/mcp.json`, the trust/security
  model, sandboxing).
- `python-enterprise-connectors` / `python-auth-security` — backing services + auth for tools your server exposes.
- `llm-security` / `threat-modeling` — hardening a server whose tools touch untrusted input or secrets.
