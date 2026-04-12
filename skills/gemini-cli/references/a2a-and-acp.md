# A2A and ACP in Gemini CLI

Gemini CLI supports two different agent-protocol roles. They are NOT the same thing — and neither is MCP.

## Three protocols at a glance

| Protocol | What it does | Gemini CLI role |
|---|---|---|
| **MCP** (Model Context Protocol) | Models call tools on external servers | Gemini is the **client** — it talks to MCP servers |
| **A2A** (Agent-to-Agent) | One agent calls another agent as a service | Gemini can be **both** client and server (via separate package) |
| **ACP** (Agent Client Protocol) | Editors/IDEs talk to a CLI agent | Gemini is the **server** — clients (e.g. Zed editor) talk to it |

## A2A — verified GA

`@google/gemini-cli-a2a-server@0.36.0` is **published on npm and verified GA** as of 2026-04-07. It is maintained in lockstep with the Gemini CLI itself (same major.minor.patch).

Verified evidence:

```bash
npm view @google/gemini-cli-a2a-server
# version: 0.36.0
# published: 2026-04-07
# matches gemini --version (0.36.0)
```

This **closes backlog item #10** ("Gemini A2A GA?") in the codex-orchestration skill — the answer is yes, GA, version 0.36.0.

### Using A2A

The A2A server is a separate npm package. Install:

```bash
npm install -g @google/gemini-cli-a2a-server
```

Then run as a server (the binary name and exact CLI surface are research-grade — verify with `--help` after install):

```bash
gemini-cli-a2a-server  # placeholder — confirm with the package
```

Once running, other A2A-aware agents can call this Gemini instance over the A2A protocol.

### Use cases

- One pa instance routing to a remote Gemini CLI for large-context analysis
- Distributed team setups where one machine has Gemini and others delegate to it
- Multi-agent workflows where Gemini is one of several specialised agents

## ACP — verified flag

`--acp` is a verified flag in `gemini --help` (Gemini CLI 0.36.0):

```
--acp                       Starts the agent in ACP mode  [boolean]
--experimental-acp          Starts the agent in ACP mode (deprecated, use --acp instead)  [boolean]
```

ACP is the **Agent Client Protocol** — a protocol for editor/IDE clients (most notably the Zed editor) to talk to a CLI agent as if it were a built-in language server.

### Using ACP

```bash
gemini --acp
```

This starts Gemini in ACP server mode. The editor (Zed, etc.) connects to this process via ACP and uses it for chat, code generation, and tool calls.

`--experimental-acp` is the deprecated alias — use `--acp` going forward.

### When to use ACP

- Embedding Gemini into a code editor that supports ACP
- Building a custom IDE plugin that doesn't want to reimplement Gemini's tool-use logic
- Local dev loop where the editor manages the chat UI and Gemini does the work

## A2A vs ACP vs MCP — picking the right protocol

| Need | Protocol |
|---|---|
| Give the model new tools (database, GitHub, custom) | **MCP** — `gemini mcp add` |
| Have one agent call another agent as a black-box service | **A2A** — `@google/gemini-cli-a2a-server` |
| Have an editor/IDE talk to Gemini as a backend | **ACP** — `gemini --acp` |
| Cross-tool skill that runs in any CLI | None of the above — use the Skill format directly |

These are independent. You can run Gemini with MCP servers configured, ACP enabled (`--acp`), and the A2A server running on a sibling process — all at once.

## Anti-patterns

| Don't | Why |
|---|---|
| Conflate A2A and MCP | A2A is agent-to-agent, MCP is model-to-tool. Different protocols. |
| Use `--experimental-acp` in new code | Deprecated. Use `--acp`. |
| Assume the A2A server ships with `@google/gemini-cli` | It is a separate package: `@google/gemini-cli-a2a-server`. Install it explicitly. |
| Treat ACP as "remote Gemini" | ACP is for editors/IDEs. For remote inference, use A2A or just call `gemini` over SSH. |
