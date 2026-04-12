# Cross-Tool Integration

How Claude Code 2.1.96 talks to Codex CLI 0.118.0 and Gemini CLI 0.36.0 in this environment, and what skills cover the bridges.

## Three-model orchestration

In MEDIUM/COMPLEX tasks, the design phase runs Claude + Codex + Gemini in parallel:

| Model | Role | Strength |
|---|---|---|
| Claude (Sonnet/Opus via `claude`) | Author + lead coordinator | Long-context reasoning, agent orchestration |
| Codex (GPT-5.4 via `codex` plugin) | Challenger + second opinion | Targeted code review, focused critique |
| Gemini (Gemini 3 via `gemini` MCP / CLI) | Large-context research + freshness | 1M token context, Google Search grounding |

Use Codex for focused code review and challenger work. Use Gemini for large-codebase analysis, freshness checks, and cross-source verification where context size matters.

## Calling Codex from Claude Code

The preferred entry point is the **codex plugin** (`~/.claude/plugins/cache/openai-codex/codex/1.0.2/`), invoked via slash commands. See `codex-orchestration` skill for patterns.

### Slash commands

| Command | Purpose |
|---|---|
| `/codex:setup` | Verify Codex CLI is ready, toggle stop-time review gate |
| `/codex:review` | Run a Codex code review (background-capable) |
| `/codex:adversarial-review` | Deeper adversarial analysis with concern hints |
| `/codex:status` | Check status of background Codex task |
| `/codex:result` | Fetch result of completed background task |
| `/codex:rescue` | Delegate investigation/fix to a Codex rescue subagent |

### Raw `codex exec` pattern (when slash commands don't fit)

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)
timeout 120 codex exec --ephemeral -s read-only \
  -o "$CODEX_WORK/result.md" \
  "Review this skill draft at [PATH]. Output: deploy / revise / rewrite."
```

Always wrap with `timeout`. Long-running Codex tasks may exit non-zero before writing synthesis even when research completes — check the output file before treating non-zero as failure.

### Codex result handling

- `/codex:result` returns the structured output from a background task
- Treat the verdict (deploy/revise/rewrite) as advisory, not binding
- For "revise": fix the issue and re-run the same review
- For "rewrite": return to design

## Calling Gemini from Claude Code

Two paths:

### Via the gemini-cli MCP server
Already installed at this machine. MCP tools:

| Tool | Purpose |
|---|---|
| `mcp__gemini-cli__ping` | Availability check (use BEFORE delegating Gemini work) |
| `mcp__gemini-cli__ask-gemini` | Direct prompt with optional Google Search grounding |
| `mcp__gemini-cli__brainstorm` | Brainstorming mode |
| `mcp__gemini-cli__fetch-chunk` | Pagination for large outputs |
| `mcp__gemini-cli__Help` | Tool help |

### Via the `gemini` CLI directly
For headless invocations or shell scripts:

```bash
gemini -p "summarise this codebase" --output-format json -y
gemini -p --include-directories ./src "find all the public API entry points"
```

See the `gemini-cli` skill for the full surface.

## Calling Claude Code from elsewhere

| From | Pattern |
|---|---|
| Codex CLI | `codex` reads `~/.codex/skills/` (symlinked from `~/.claude/skills/`) and `~/.codex/AGENTS.md` |
| Gemini CLI | `gemini` reads `~/.gemini/skills/` (planned symlink to `~/.claude/skills/`), can `gemini hooks migrate` from Claude's settings.json |
| GitHub Copilot CLI | No skills concept. Reference Claude skills via `AGENTS.md` or wrap as MCP servers in `~/.copilot/mcp-config.json`. See `gh-copilot-cli` skill |
| Shell script | `claude -p --bare` for CI-safe invocation |
| GitHub Actions | `references/github-actions.md` |

## Skill cross-references

| Cross-tool concern | Skill |
|---|---|
| Authoring rules for skills that work in multiple CLIs | `research-for-skills/cross-tool-portability/cross-tool-portability.md` |
| Calling Codex from Claude Code | `codex-orchestration` |
| Calling Gemini directly | `gemini-cli` |
| Operating GitHub Copilot CLI | `gh-copilot-cli` |
| Running everything on a GCP Workstation | `gcp-workstations` |
| Web research orchestration across all three | `web-research` |

## Hook re-entrancy warning

Hooks defined in `~/.claude/settings.json` may invoke `claude`, `codex`, or `gemini` as part of their action. If those tools also have hooks that loop back, you can recurse.

The convention (not enforced — see `cross-tool-portability/challenger-concerns.md`) is to set `AI_CLI_CALL_DEPTH` env var on entry, increment per call, refuse to recurse beyond depth 2.

```bash
# In a hook script
export AI_CLI_CALL_DEPTH="${AI_CLI_CALL_DEPTH:-0}"
if [ "$AI_CLI_CALL_DEPTH" -ge 2 ]; then
  echo "Refusing to recurse: AI_CLI_CALL_DEPTH=$AI_CLI_CALL_DEPTH" >&2
  exit 0
fi
export AI_CLI_CALL_DEPTH=$((AI_CLI_CALL_DEPTH + 1))
# ... call claude / codex / gemini ...
```

## Authentication landscape

| Tool | This machine (default) | Alternative |
|---|---|---|
| Claude Code | OAuth (`claude auth login`) | `ANTHROPIC_API_KEY`, Bedrock (`CLAUDE_CODE_USE_BEDROCK=1`), Vertex (`CLAUDE_CODE_USE_VERTEX=1`) |
| Codex CLI | OpenAI account login (`codex auth`) | `OPENAI_API_KEY` |
| Gemini CLI | OAuth personal | `GEMINI_API_KEY`, Vertex (`GOOGLE_GENAI_USE_VERTEXAI=1` + ADC), service account (`GOOGLE_APPLICATION_CREDENTIALS`) |
| Copilot CLI | Device flow (`copilot auth`) — UNVERIFIED until WP3 install | `GH_TOKEN`, `GITHUB_TOKEN`, Copilot subscription required |

For GCP Workstation deployment, see `gcp-workstations/references/auth-per-tool.md` for the canonical recommendation (Claude → Vertex ADC, Gemini → Vertex ADC, Copilot → device flow with TCP tunnel fallback).
