# MCP servers + the VS Code agent security model

Current to 2026-06-24, from the official VS Code "Add and manage MCP servers" doc.
This is the **security-critical** reference — read it before adding any MCP server or
auto-approving agent actions.

## `mcp.json` config

| Scope | Path | Notes |
|---|---|---|
| Workspace | `.vscode/mcp.json` | shareable via source control (the team gets the same servers) |
| User | `mcp.json` in the profile folder | open via **MCP: Open User Configuration** |

### Schema

```jsonc
{
  "servers": {
    "local-stdio": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@scope/some-mcp-server"],
      "env": { "API_TOKEN": "${input:api-token}" }   // input var — NOT a hardcoded secret
    },
    "remote-http": {
      "type": "http",                                 // or "sse"
      "url": "https://mcp.example.com"
    }
  },
  "sandbox": {                                        // optional, macOS/Linux
    "filesystem": { "allowWrite": ["${workspaceFolder}/.cache"] },
    "network":    { "allowedDomains": ["api.example.com"] }
  }
}
```

- **stdio** servers run a local process (`command` + `args`).
- **http** / **sse** servers are remote (`url`).
- **Secrets:** use `${input:...}` input variables or an env file — never hardcode tokens
  in `mcp.json` (it's often committed).

### Adding via UI
- Extensions view → search `@mcp` → **Install** (user) or right-click **Install in Workspace**.
- Command Palette → **MCP: Add Server** (guided; choose Global or Workspace scope).

## Security model — the part to check first

1. **Arbitrary code / prompt injection.** *"Local MCP servers can run arbitrary code on
   your machine. Only add servers from trusted sources."* A server's tool results are
   untrusted **data** the agent reads — a malicious server can attempt prompt injection.
2. **Trust dialog on first start.** VS Code asks you to confirm you trust the server + its
   capabilities before starting it. **Caveat:** *"If you start the MCP server directly from
   the `mcp.json` file, you will NOT be prompted to trust the server configuration."* — so
   add/enable through the UI flow, not by hand-launching from the JSON.
3. **Reset trust** any time with **MCP: Reset Trust**.
4. **Sandboxing (macOS/Linux).** `"sandboxEnabled": true` + the `sandbox` block confine a
   server's filesystem writes and network. Sandboxed servers may **auto-approve** tool
   calls precisely because they're isolated — prefer sandbox + minimal `allowWrite` /
   `allowedDomains` over a trusted-but-unconfined server.
5. **Enable/disable scope.** A server can be enabled globally or per-workspace; a disabled
   server doesn't start and its tools/prompts/resources are excluded from chat.

## Hardening the agent loop (beyond MCP)

- **Least-privilege `tools`** per custom agent (a Plan agent has no edit/terminal).
- **Hooks** = deterministic guardrails run at points in the agent loop — use them to block
  a forbidden command, require a check, or enforce policy (they don't depend on the model
  "deciding" to comply).
- **Terminal / edit auto-approval:** review the autorun settings before blanket-allowing the
  agent to run commands; keep a human in the loop for destructive ops.
- **`chat.useCustomizationsInParentRepositories`** is **off by default** — leave it off so a
  parent directory can't silently inject instructions/agents/MCP into your session.
- **Copilot coding agent** ships built-in security scanning + self-review on its PRs — but
  still review the diff; agent output is a proposal, not a trusted artifact.

## Pre-flight checklist (before wiring agents/MCP for real work)

- [ ] MCP servers come from a source you trust; added via the UI (trust prompt fired).
- [ ] Secrets via `${input:...}` / env files, not hardcoded in committed `mcp.json`.
- [ ] Sandbox enabled where supported; `allowWrite`/`allowedDomains` are minimal.
- [ ] Each custom agent's `tools` are least-privilege for its role.
- [ ] Destructive terminal/edit actions are NOT blanket auto-approved.
- [ ] Hooks enforce any non-negotiable guardrails.
- [ ] `chat.useCustomizationsInParentRepositories` stays off unless parents are trusted.
