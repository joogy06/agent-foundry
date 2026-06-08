# Cross-Tool Integration

How Claude Code 2.1.96 talks to Codex CLI 0.137.0 and Antigravity CLI (`agy`) 1.0.5 in this environment, and what skills cover the bridges.

## Three-model orchestration

In MEDIUM/COMPLEX tasks, the design phase runs Claude + Codex + Antigravity (agy) in parallel:

| Model | Role | Strength |
|---|---|---|
| Claude (Sonnet/Opus via `claude`) | Author + lead coordinator | Long-context reasoning, agent orchestration |
| Codex (GPT-5.4 via `codex` plugin) | Challenger + second opinion | Targeted code review, focused critique |
| Antigravity (agy via `agy`) | Large-context research + second opinion | Headless single-prompt delegate, restricted-terminal sandbox |

Use Codex for focused code review and challenger work. Use agy for large-codebase analysis and cross-source verification as a second-opinion / challenger delegate.

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
timeout 600 codex exec --ephemeral -s read-only \
  -o "$CODEX_WORK/result.md" \
  "Review this skill draft at [PATH]. Output: deploy / revise / rewrite."
```

Always wrap with `timeout`. Long-running Codex tasks may exit non-zero before writing synthesis even when research completes — check the output file before treating non-zero as failure.

### Codex result handling

- `/codex:result` returns the structured output from a background task
- Treat the verdict (deploy/revise/rewrite) as advisory, not binding
- For "revise": fix the issue and re-run the same review
- For "rewrite": return to design

## Calling Antigravity (agy) from Claude Code

The Antigravity CLI (`agy`) is this host's PRIMARY second-opinion / challenger / research delegate (the gemini CLI remains a fallback until Google retires it on 2026-06-18). The `gemini-cli` MCP server has been REMOVED — call `agy` directly via Bash. `agy` authenticates itself (Antigravity account, config under `~/.antigravity/`); there is no API-key env prefix. agy ≥1.0.5 HAS a `--model` flag (and an `agy models` subcommand), but the host convention remains to OMIT it — the Antigravity-account default model is used.

### Via the `agy` CLI directly
For headless invocations or shell scripts:

```bash
# Availability check (run BEFORE delegating agy work)
command -v agy && agy --version

# Headless single prompt — output is plain text on stdout
agy -p "summarise this codebase" < /dev/null

# Scope the run to one or more directories (repeatable)
agy --add-dir ./src -p "find all the public API entry points" < /dev/null

# Raise the wait timeout for long runs (default 5m0s)
agy --print-timeout 15m -p "deep analysis of this codebase" < /dev/null

# Restricted-terminal run; auto-approve tool calls only in a fully-headless context
agy --sandbox --dangerously-skip-permissions -p "..." < /dev/null
```

`agy -p` returns **plain text** on stdout — parse the text, not JSON fields (the removed `mcp__gemini-cli__*` tools returned structured fields; `agy` does not). Model self-identification is unreliable; if you need to confirm which model served a call, append a `served_by` probe line to the prompt rather than trusting any self-reported identity.

See the `antigravity-cli` skill for the full surface.

## Calling Claude Code from elsewhere

| From | Pattern |
|---|---|
| Codex CLI | `codex` reads `~/.codex/skills/` (symlinked from `~/.claude/skills/`) and `~/.codex/AGENTS.md` |
| Antigravity CLI (agy) | Scope context into a run with `agy --add-dir <path>` (repeatable). `# TODO(agy): verify equivalent` — no verified `agy` skills-directory or settings-migration mechanism (the old `gemini hooks migrate` / `~/.gemini/skills/` path does not carry over) |
| GitHub Copilot CLI | No skills concept. Reference Claude skills via `AGENTS.md` or wrap as MCP servers in `~/.copilot/mcp-config.json`. See `gh-copilot-cli` skill |
| Shell script | `claude -p --bare` for CI-safe invocation |
| GitHub Actions | `references/github-actions.md` |

## Skill cross-references

| Cross-tool concern | Skill |
|---|---|
| Authoring rules for skills that work in multiple CLIs | `research-for-skills/cross-tool-portability/cross-tool-portability.md` |
| Calling Codex from Claude Code | `codex-orchestration` |
| Calling Antigravity (agy) directly | `antigravity-cli` |
| Operating GitHub Copilot CLI | `gh-copilot-cli` |
| Running everything on a GCP Workstation | `gcp-workstations` |
| Web research orchestration across all three | `web-research` |

## Hook re-entrancy warning

Hooks defined in `~/.claude/settings.json` may invoke `claude`, `codex`, or `agy` as part of their action. If those tools also have hooks that loop back, you can recurse.

The convention (not enforced — see `cross-tool-portability/challenger-concerns.md`) is to set `AI_CLI_CALL_DEPTH` env var on entry, increment per call, refuse to recurse beyond depth 2.

```bash
# In a hook script
export AI_CLI_CALL_DEPTH="${AI_CLI_CALL_DEPTH:-0}"
if [ "$AI_CLI_CALL_DEPTH" -ge 2 ]; then
  echo "Refusing to recurse: AI_CLI_CALL_DEPTH=$AI_CLI_CALL_DEPTH" >&2
  exit 0
fi
export AI_CLI_CALL_DEPTH=$((AI_CLI_CALL_DEPTH + 1))
# ... call claude / codex / agy ...
```

## Authentication landscape

| Tool | This machine (default) | Alternative |
|---|---|---|
| Claude Code | OAuth (`claude auth login`) | `ANTHROPIC_API_KEY`, Bedrock (`CLAUDE_CODE_USE_BEDROCK=1`), Vertex (`CLAUDE_CODE_USE_VERTEX=1`) |
| Codex CLI | OpenAI account login (`codex auth`) | `OPENAI_API_KEY` |
| Antigravity CLI (agy) | Antigravity account (config under `~/.antigravity/`); `agy` authenticates itself — no API-key env prefix at the call layer | — |
| Copilot CLI | Device flow (`copilot auth`) — UNVERIFIED until WP3 install | `GH_TOKEN`, `GITHUB_TOKEN`, Copilot subscription required |

For GCP Workstation deployment, see `gcp-workstations/references/auth-per-tool.md` for the canonical recommendation (Claude → Vertex ADC, Copilot → device flow with TCP tunnel fallback).

<!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: codex
    verified_against: "0.137.0"
    verified_on: "2026-06-05"
-->
