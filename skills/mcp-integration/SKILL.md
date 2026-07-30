---
name: mcp-integration
description: Use when wiring MCP servers into an application or agent as a consumer — deciding whether MCP is the right interface at all, the 2026-07-28 stateless protocol revision and what it breaks, transport and version negotiation, OAuth authorization and Client ID Metadata Documents, the context cost of tool lists and how cacheable list results reduce it, treating third-party servers as untrusted code, and operating remote servers behind ordinary HTTP infrastructure.
disambiguation: CONSUMING MCP servers from an application — selection, transport, auth, trust, cost, operations. BUILDING a server (tools, resources, prompts, SDK code) is mcp-server-creator; adding servers to VS Code specifically is vscode-agents; tool-poisoning and injection defence in depth is llm-security; whether the system needs agents at all is agentic-architecture.
---

# MCP integration

<!-- REVIEW-BY: 2027-01-31 -->
**Verified 2026-07-29 against the 2026-07-28 specification release announcement.** This revision
landed one day before this file was written — **read the specification itself before migrating**, and
treat the detail below as a map of what to look for, not a substitute for it.

## 1. The 2026-07-28 revision is a breaking change

**The protocol core became stateless.** This is the largest change since MCP was published, and it
invalidates a good deal of existing integration code and most tutorials.

| Removed / deprecated | Replaced by |
|---|---|
| `initialize` / `initialized` handshake | Protocol version, client identity and capabilities travel in `_meta` **on every request** |
| `Mcp-Session-Id` header | Nothing — there is no protocol-level session |
| Server-initiated elicitation, sampling, roots-list | **Multi Round-Trip Requests**: the server returns `resultType: "input_required"`, the client retries with `inputResponses` |
| Legacy HTTP+SSE transport | Streamable HTTP |
| Dynamic Client Registration | **Client ID Metadata Documents (CIMD)** |
| Roots, Sampling, Logging features | Deprecated, with a minimum 12-month sunset |

**Added:**

- **Header-based routing** — streamable HTTP requests carry `Mcp-Method` and `Mcp-Name`, so gateways,
  rate limiters and authorizers can route and authorise **without parsing the JSON body**.
- **Cacheable list results** — `tools/list`, `prompts/list`, `resources/list` and `resources/read`
  responses carry `ttlMs` and `cacheScope`.
- **Authorization hardening** — RFC 9207 issuer (`iss`) validation is now mandatory, an
  `application_type` parameter is supported, and client credentials are bound to the issuing
  authorization server.
- **A formal extensions framework**, with Tasks graduating to `io.modelcontextprotocol/tasks`
  (poll-based `tasks/get`, plus `tasks/update`) and notifications moving to `subscriptions/listen`.
- **A 12-month minimum deprecation policy**, which is what makes planned migration possible.

### Compatibility is the thing that will bite

**A server on the new revision may not work with an older client, and vice versa.** Both sides must
share a supported protocol era, or one side must implement deliberate fallback or translation.

**Before upgrading either side, enumerate what talks to it.** The stateless change is genuinely good
— it lets any instance answer any request behind ordinary round-robin HTTP, with no shared session
store — but it is not backward compatible, and a client you do not control is a hard constraint.

## 2. Do you need MCP here at all?

**MCP earns its cost when the tool surface is consumed by clients you do not own** — a desktop
assistant, an IDE, someone else's agent — or when several applications share one integration.

**It does not earn it for a private tool used by one application you control.** Native function
calling against your own code is simpler, faster, has no transport, no auth layer and no protocol
version to track. Wrapping your own function in a protocol so your own agent can call it is
infrastructure for its own sake.

**The honest test:** name the second consumer. If there isn't one and isn't likely to be, call the
function.

## 3. Transport

| Transport | Use for |
|---|---|
| **stdio** | Local, client-launched servers. Simplest and most reliable — no ports, no CORS, no auth layer |
| **Streamable HTTP** | Remote and shared servers |
| ~~HTTP+SSE~~ | **Deprecated.** Do not build new integrations on it |

**Default to stdio for anything local.** Reaching for HTTP because it feels more production-grade
adds an authentication surface and an availability dependency to something that was a subprocess.

## 4. Authorization

- **Validate the issuer.** RFC 9207 `iss` validation is mandatory in the current revision — it is the
  defence against a token minted by one authorization server being replayed at another.
- **Prefer CIMD over Dynamic Client Registration**, which is now formally deprecated.
- **Bind tokens to an audience, and never forward a user's token to a downstream API unchanged.** A
  server that accepts a user token and reuses it against a third party is a confused deputy: the
  downstream sees your service's authority, not the user's.
- **The permission the server holds is the permission the model effectively has.** Scope credentials
  to what the tools genuinely need, per server, not per organisation.

## 5. Tool lists cost tokens on every call

**Every connected server's tool definitions are input tokens on every request**, and a large
undifferentiated toolset also degrades tool selection — the same failure as overlapping skills.

- **Connect the servers a given surface actually needs**, not every server the organisation runs.
- **Use `ttlMs` / `cacheScope`** to avoid re-fetching lists that have not changed.
- **Place tool definitions in the cached prefix** of your prompt — they are static, so they belong at
  the top where prompt caching can reuse them (`llm-api-optimization` §2).
- **Watch for name collisions** across servers. Two servers exposing `search` is an ambiguity you pay
  for on every call.

## 6. Third-party servers are untrusted code

A community MCP server is a dependency that **runs on your machine or holds your credentials, and
supplies text directly into the model's context.**

- **Tool descriptions are an injection surface.** They enter the prompt, so a malicious description
  can instruct the model. Read them before installing.
- **Pin versions.** An auto-updating server is remote code execution with a changelog.
- **Least privilege per server** — separate credentials, minimum scopes, no shared admin token.
- **Gate destructive tools behind human approval**, at the client (`agentic-architecture` §6).
- **Treat every tool result as untrusted input**, not as trusted context — `llm-security` covers the
  defences, and this is exactly the boundary it is about.

## 7. Operating remote servers

- **Statelessness is what makes horizontal scaling ordinary** — no sticky sessions, no shared session
  store, any instance answers any request.
- **Exploit header-based routing** at the edge: `Mcp-Method` and `Mcp-Name` let a gateway authorise
  and rate-limit per tool without deserialising bodies. Per-tool rate limits are the practical
  defence against a runaway agent loop.
- **Handle tool errors as data, never as a crashed process** — one failed call must not take down
  every connected client.
- **Set timeouts and size caps on tool results** at the client. A server you do not control can
  return more than your context can hold.
- **Version-negotiate explicitly and log the negotiated era**, so a client-side incompatibility is a
  clear log line rather than a mystery.

## 8. Anti-patterns

- **Migrating to the stateless revision** without enumerating every client and server that talks to
  the thing being upgraded.
- **Building new integrations on HTTP+SSE**, which is deprecated.
- **Assuming a session exists.** There is no protocol session; state you need is yours to carry.
- **Wrapping your own function in MCP** so your own agent can call it.
- **HTTP transport for a local subprocess.**
- **Forwarding a user's token downstream unchanged.**
- **Connecting every available server** to every surface, then paying for the tool list on every call.
- **Installing a community server without reading its tool descriptions.**
- **Auto-updating third-party servers.**
- **Treating tool output as trusted context.**
- **No per-tool rate limit**, so an agent loop becomes a third-party bill.
