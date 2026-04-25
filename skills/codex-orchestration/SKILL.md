---
name: codex-orchestration
description: Use when delegating tasks to Codex CLI (OpenAI GPT-5.4) or Gemini CLI (Google Gemini 3) from Claude Code — research tasks, challenger/devil's advocate reviews, prototyping, idea generation, code review, second-opinion analysis. Covers Codex plugin commands, codex exec, Gemini MCP tools (ask-gemini, brainstorm), and gemini -p headless mode. Triple-model orchestration for Claude + Codex + Gemini. Sandbox-aware: routes Gemini/Copilot calls through git-cli-bridge when local CLIs are unreachable.
---

# Cross-Model Orchestration — Claude + Codex + Gemini

Delegate tasks to **Codex CLI (GPT-5.4)** and **Gemini CLI (Gemini 3)** from Claude Code for second opinions, parallel research, challenger reviews, and idea generation. Each model runs as an independent agent with its own context, tools, and reasoning — different models catch different things.

<HARD-RULE>
Always check Codex availability before delegating. Read `tools.codex.installed` from `~/.claude/state/inventory.json` (written by `env-adoption` skill). If the inventory is missing, run `bash ~/.claude/skills/env-adoption/scripts/probe.sh check --inventory-only --silent` first. If `tools.codex.installed` is false, fall back to Claude Code agents.
</HARD-RULE>

<HARD-RULE>
Never pass secrets, API keys, or credentials in Codex prompts. Prompts may be logged in `~/.codex/sessions/` and `~/.codex/history.jsonl`. Use environment variables or file references instead.
</HARD-RULE>

<HARD-RULE>
Always use `--ephemeral` for orchestration tasks to avoid polluting Codex session history. Orchestration calls are fire-and-forget — they don't need persistent sessions.
</HARD-RULE>

<HARD-RULE>
When delegating to Gemini or Copilot, check `bridge-mode-detect.sh` first. If it reports "bridge", route the call through `bridge request` instead of calling the local CLI. Explicit `AI_BRIDGE_MODE=1` forces bridge; explicit `AI_BRIDGE_DISABLE=1` forces local; otherwise auto-detection with 3-failure hysteresis. See `git-cli-bridge` skill.
</HARD-RULE>

---

## Codex Plugin Commands (Primary Interface)

The **Codex plugin** (`codex@openai-codex`) provides first-class slash commands for structured Codex interaction. **Prefer plugin commands over raw `codex exec`** for reviews, task delegation, and managed workflows.

| Command | Purpose | Replaces |
|---------|---------|----------|
| `/codex:review` | Code review against git diffs | Manual `codex exec` review briefs |
| `/codex:adversarial-review` | Challenge review (design, tradeoffs) | Manual challenger briefs |
| `/codex:rescue` | Delegate investigation/fix to Codex | `codex exec` task delegation |
| `/codex:setup` | Check readiness, toggle review gate | Manual `codex --version` check |
| `/codex:status` | Track background jobs | No equivalent (was fire-and-forget) |
| `/codex:result` | Retrieve finished job output | Manual `-o` file reading |
| `/codex:cancel` | Cancel running jobs | No equivalent |

### When to Use Plugin vs Raw `codex exec`

| Use Plugin Commands | Use Raw `codex exec` |
|---------------------|---------------------|
| Code reviews (`/codex:review`) | Parallel batch tasks with `&` and `wait` |
| Adversarial/challenger reviews | Custom brief files with skill injection |
| Task delegation (`/codex:rescue`) | Structured output schemas (`--output-schema`) |
| Background job management | Streaming JSONL events (`--json`) |
| Resume prior Codex threads (`--resume`) | MCP server mode (`codex mcp-server`) |

**Plugin commands handle job lifecycle (tracking, resume, cancel). Raw `codex exec` is better for parallel orchestration and custom prompt engineering.**

---

## Gemini MCP Tools (Primary Interface)

The **gemini-mcp-tool** MCP server wraps the Gemini CLI binary, using your AI Pro subscription (OAuth). No API key needed.

| MCP Tool | Purpose | Use For |
|----------|---------|---------|
| `mcp__gemini-cli__ask-gemini` | Send any prompt to Gemini | Research, analysis, code review, large file analysis (1M context) |
| `mcp__gemini-cli__brainstorm` | Structured brainstorming with methodology frameworks | Idea generation (SCAMPER, Design Thinking, Divergent, Convergent, Lateral) |
| `mcp__gemini-cli__fetch-chunk` | Retrieve cached chunks from large responses | Paginated results from changeMode |

**Key parameters for `ask-gemini`:**
- `prompt` (required) — the task. Use `@filename` syntax to reference files for Gemini's 1M context
- `model` — default `gemini-2.5-pro`, auto-falls back to `gemini-2.5-flash` on quota exceeded
- `sandbox` — run in sandbox mode (read-only)
- `changeMode` — structured edit suggestions (OLD/NEW blocks)

### When to Use Gemini MCP vs Raw `gemini -p`

| Use MCP Tools | Use Raw `gemini -p` |
|---------------|---------------------|
| Single analysis tasks (`ask-gemini`) | Parallel batch tasks via Bash `&` and `wait` |
| Structured brainstorming (`brainstorm`) | Piped input (`cat file \| gemini -p "..."`) |
| Integrated Claude Code workflow | Scripted automation with `--output-format json` |
| File analysis with `@` syntax | Batch processing loops |

### Raw Gemini CLI (Fallback / Parallel)

```bash
# Force OAuth subscription path when the shell has GOOGLE_CLOUD_PROJECT / GEMINI_API_KEY set for other Google tooling
export GOOGLE_CLOUD_PROJECT=
export GEMINI_API_KEY=

# Basic headless mode
gemini -p "Review this code for security issues" --output-format json --yolo

# With piped context
cat src/main.py | gemini -p "Find N+1 query problems" --output-format json

# Parallel with Codex (triple-model validation)
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)
GEMINI_WORK=$(mktemp -d /tmp/gemini-XXXXXXXXXX)

codex exec --ephemeral -C "$PROJECT_DIR" -s read-only \
  -o "$CODEX_WORK/review.md" "Review for security issues" &
gemini -p "Review for security issues in $PROJECT_DIR" \
  --output-format json --yolo > "$GEMINI_WORK/review.json" &
wait
```

### Gemini Availability Check

```bash
GEMINI_AVAILABLE=$(gemini --version 2>/dev/null && echo "yes" || echo "no")
```

Cache for the session like the Codex check. Both can be checked in parallel at session start.

---

## Sandbox-Aware Routing via git-cli-bridge

In sandboxed environments where `gemini` or `copilot` CLIs are unreachable locally, route delegation through the `git-cli-bridge` skill. It pushes requests via git to a dedicated `ai-bridge-<user>` repo and executes the CLI on GitHub Actions runners.

### Routing matrix

| AI_BRIDGE_MODE | AI_BRIDGE_DISABLE | Local gemini --version | Local copilot --version | Effective mode |
|---|---|---|---|---|
| unset | unset | ok | ok | local |
| unset | unset | fail | ok | local (1-2 fails) -> bridge (3+ fails) |
| unset | unset | fail | fail | local (1-2 fails) -> bridge (3+ fails) |
| 1 | unset | any | any | bridge |
| unset | 1 | any | any | local |
| 1 | 1 | any | any | local (DISABLE wins) |

### Bridge call template

```bash
MODE=$("$HOME/.claude/skills/git-cli-bridge/scripts/bridge-mode-detect.sh")
if [ "$MODE" = "bridge" ]; then
  # Submit via bridge. Requires `bridge init` to have been run already in this session.
  BRIDGE_CALLER=codex-orchestration \
  bridge request \
    --tool gemini --kind review \
    --context "$CONTEXT_FILE" \
    --wait --timeout 720 \
    "$PROMPT_BODY"
else
  # Local path
  mcp__gemini-cli__ask-gemini(prompt: "$PROMPT_BODY")
fi
```

### Latency expectations

- Local Gemini call: ~2-5 seconds.
- Bridge Gemini call: ~90 seconds cold (workflow install + run), ~40 seconds warm (runner cache). This is the price of sandboxed operation. If latency is unacceptable, the user can switch back with `AI_BRIDGE_DISABLE=1`.

### When bridge mode is wrong

- Bridge mode activates but the user's local CLI is actually fine: run `AI_BRIDGE_DISABLE=1 bridge-mode-detect.sh --reset` then re-probe.
- Local CLI activates but the user's local CLI is blocked by a transient network issue: wait 1 minute, retry; hysteresis will catch it on the third failure.
- Bridge mode activates but `bridge init` was never run: the next `bridge request` will fail; either `bridge init` or set `AI_BRIDGE_DISABLE=1` for the rest of the session.

See `git-cli-bridge` skill for full protocol, security model, and client script reference.

---

## Three-Model Validation Pattern

For COMPLEX tasks, run all three models for maximum coverage:

| Model | Role | Strength |
|-------|------|----------|
| Claude (Opus 4.6) | Orchestrator, architect | 1M context, skills/agents, MCP, conversation memory |
| Codex (GPT-5.4) | Challenger, code review | Independent perspective, web search, structured review output |
| Gemini (Gemini 3) | Analyst, research | 1M context, multimodal, Google Search grounding, brainstorming |

**Diverge → Challenge → Converge:**
1. Claude explores approaches (via forge design team)
2. Codex challenges (via `/codex:adversarial-review` or raw exec)
3. Gemini independently analyzes (via `ask-gemini` MCP or raw `gemini -p`)
4. Claude synthesizes — flag agreements (high confidence) and disagreements (investigate)

---

## Current State (April 2026)

| Component | Version / Value |
|---|---|
| Codex CLI | v0.116.0 (`codex-cli`) |
| Codex Plugin | v1.0.2 (`@openai/codex-plugin-cc`) |
| Gemini CLI | v0.36.0 |
| Gemini MCP | v1.1.4 (`gemini-mcp-tool`) — wraps CLI binary, uses OAuth |
| Default Codex model | GPT-5.4 (migrated from GPT-5.2) |
| Default Gemini model | gemini-2.5-pro (auto-fallback to gemini-2.5-flash) |
| Reasoning effort | xhigh |
| Multi-agent | enabled |
| Claude Code model | Claude Opus 4.6 (1M context) |
| Handover mechanism | Plugin commands (preferred) OR session-scoped temp dirs + `codex exec -o` |

### System Configuration

```toml
# ~/.codex/config.toml (as of 2026-03-24)
model = "gpt-5.4"
model_reasoning_effort = "xhigh"
personality = "pragmatic"

[features]
multi_agent = true

[notice.model_migrations]
"gpt-5.2" = "gpt-5.4"
```

### Available Models (2026)

```bash
# Override model per-task
codex exec -m gpt-5.4 ...        # default, strongest reasoning
codex exec -m o3 ...              # OpenAI reasoning model
codex exec -m gpt-4.1 ...        # faster, lower cost
codex exec --oss ...              # local open-source (Ollama/LMStudio)
```

### Cross-Model Advantage

Claude Opus 4.6 (1M context) and GPT-5.4 have different strengths. Use both:

| Strength | Claude Opus 4.6 | GPT-5.4 via Codex |
|---|---|---|
| Context window | 1M tokens | ~256K tokens |
| Tool ecosystem | MCP, skills, agents, Read/Edit/Grep | Shell, file I/O, web search |
| Code editing | Precise Edit tool with diffs | Full-file rewrites |
| Orchestration | Agent spawning, parallel teams | Multi-agent feature |
| Unique value | Skill library, conversation memory | Independent perspective, web search |

**Key principle**: Use Codex for tasks where a *different model's perspective* adds value — challenger reviews, second opinions, independent research. Don't use it as a replacement for Claude's tool ecosystem.

---

## Core Integration: `codex exec`

The key command for non-interactive delegation:

```bash
codex exec [OPTIONS] [PROMPT]
# Or pipe prompt via stdin:
echo "prompt" | codex exec -

# Critical flags:
#   --ephemeral                    Don't persist session
#   --skip-git-repo-check          Allow running outside git repos
#   -o, --output-last-message FILE Write final response to file
#   --json                         Stream JSONL events to stdout
#   --output-schema FILE           Enforce structured JSON output
#   -m, --model MODEL              Override model (default: gpt-5.4)
#   -C, --cd DIR                   Set working directory
#   -s, --sandbox MODE             read-only | workspace-write | danger-full-access
#   --full-auto                    Sandboxed auto-execution
#   -i, --image FILE               Attach image(s)
#
# Note: `--search` does NOT exist as a flag in current Codex CLI (verified 2026-04-08).
# Codex web search is enabled automatically by GPT-5.4 tool use when the sandbox allows it.
# Earlier versions of this skill mentioned --search; that was incorrect.
```

### Session Directory (REQUIRED)

<HARD-RULE>
Always create a unique session directory before any Codex delegation. Multiple Claude sessions
may run in parallel across different projects — hardcoded /tmp/ paths cause cross-session
collisions where one session overwrites another's Codex results.
</HARD-RULE>

```bash
# Create ONCE per Codex delegation block — reuse for all tasks in that block
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

# All briefs, results, schemas, and events go under $CODEX_WORK/
# The directory is unique per invocation — no collision possible
```

### Basic Delegation Pattern

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

# Delegate a research task, capture output
codex exec --ephemeral --skip-git-repo-check \
  -o "$CODEX_WORK/research-output.txt" \
  "Research the top 5 approaches to container orchestration for single-node production deployments."

# Read the result back into Claude Code
# Read: $CODEX_WORK/research-output.txt
```

---

## Session-Scoped Availability

Check Codex once per session, cache the result:

```bash
CODEX_AVAILABLE=$(codex --version 2>/dev/null && echo "yes" || echo "no")
```

All subsequent checks in the session read this variable instead of re-running the command. Forge step 4b and all other callers should reference this pattern.

### Full Availability Check (When Needed)

```bash
check_codex() {
  if ! command -v codex &>/dev/null; then
    echo "UNAVAILABLE: codex not installed"
    return 1
  fi

  # Quick test (timeout after 10s)
  if ! timeout 10 codex exec --ephemeral --skip-git-repo-check \
    -o /dev/null "Reply OK" 2>/dev/null; then
    echo "UNAVAILABLE: codex auth/subscription issue"
    return 1
  fi

  echo "AVAILABLE"
  return 0
}
```

---

## Sandbox Modes

| Mode | Codex Can | Use For |
|---|---|---|
| `read-only` | Read files only | Research, review, analysis |
| `workspace-write` | Read + write in project dir | Prototyping, code generation |
| `danger-full-access` | Full system access | Only in controlled environments |
| `--full-auto` | Auto-approve + workspace-write | Prototyping with file creation |

<HARD-RULE>
Never use `--dangerously-bypass-approvals-and-sandbox` or `danger-full-access` unless the environment is externally sandboxed (container, VM). These modes give Codex unrestricted system access.
</HARD-RULE>

---

## When to Delegate to Codex vs Keep in Claude

| Delegate to Codex | Keep in Claude |
|---|---|
| Second opinion / challenger review | Primary implementation |
| Web research (Codex's GPT-5.4 tool use does this automatically) | File editing / code writing |
| Idea generation / brainstorming | Tool-heavy workflows (MCP, Grep, Read) |
| Independent prototype exploration | Tasks needing conversation context |
| Code review (codex review) | Tasks needing memory access |
| Parallel background research | Interactive user dialogue |
| Stress-testing with different model perspective | Tasks needing Claude's agent spawning |
| Domain-specific review (with skill injection) | Multi-step orchestration (forge, agent-teams) |
| Gemini delegation in sandboxed env | Via git-cli-bridge (see Sandbox-Aware Routing) |

---

## Shared Skill Library

Claude skills are symlinked into Codex's skill directory (`~/.codex/skills/`). Codex has access to 112 shared reference skills plus its own 7 native skills (119 total). Claude has 119 skills total.

**Symlink structure:** `~/.codex/skills/<name>` -> `~/.claude/skills/<name>`

**Skills NOT shared (Claude-specific):** `agent-teams`, `codex-orchestration`, `forge`, `nano-banana`, `vertex-banana`, `research-for-skills`, `challenger` (Codex has native `challenger-review`).

**Naming note:** Claude's `challenger` skill = Codex's `challenger-review` skill. Both provide the same framework from different model perspectives.

---

## Reference Files

For advanced patterns, templates, and examples, see:
- **`patterns.md`** — handover patterns, progress tracking, skill injection, multi-file output, streaming
- **`templates.md`** — ready-to-use brief templates for challenger, approach explorer, research, escalation, prototyping, code review

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Running Codex interactively from Claude | Blocks Claude's process | Use `codex exec` (non-interactive) |
| Not using `--ephemeral` | Pollutes Codex session history | Always use `--ephemeral` for orchestration |
| Passing secrets in prompts | Logged in Codex history | Use env vars or file references |
| Not checking availability first | Fails silently or hangs | Run availability check first |
| Huge prompts via command arg | Shell argument limits | Pipe via stdin: `cat brief.md \| codex exec -` |
| Ignoring sandbox modes | Security risk | Use `read-only` for analysis, `workspace-write` for prototyping |
| Not capturing output | Results lost | Always use `-o` or `--json` |
| Sequential Codex calls when parallel is possible | Slow | Use `&` and `wait` for parallel tasks |
| Re-checking availability every call | Wastes time and API calls | Cache with session-scoped variable |

---

## Related Skills

| Topic | Skill / Command |
|---|---|
| Forge design workflow | `forge` |
| Challenger role framework | `challenger` |
| Plugin adversarial review | `/codex:adversarial-review` |
| Plugin code review | `/codex:review` |
| Plugin task delegation | `/codex:rescue` |
| Plugin readiness check | `/codex:setup` |
| MCP server creation | `mcp-server-creator` |
| Large file analysis (cross-agent) | `large-file-analysis` |
| Code review methodology | `qa-reviewer` |
| Claude Code CLI reference | `claude-code-cli` |
| Gemini CLI reference (full) | `gemini-cli` |
| GitHub Copilot CLI reference | `gh-copilot-cli` |
| Cross-tool skill authoring rules | `research-for-skills/cross-tool-portability/cross-tool-portability.md` |
| GCP Workstations deployment | `gcp-workstations` |
| Git-based CLI bridge for sandboxed environments | `git-cli-bridge` |

---

## Verified facts (April 2026)

| Fact | Status |
|---|---|
| Gemini A2A GA | **VERIFIED** — `@google/gemini-cli-a2a-server@0.36.0` published on npm 2026-04-07, matches gemini-cli version. (Closes the previously-open backlog item asking whether A2A was GA.) |
| `codex exec --search` flag | **DOES NOT EXIST**. Codex web search is automatic via GPT-5.4 tool use when the sandbox allows. |
| Codex CLI version | 0.118.0 (verified locally 2026-04-08 via `codex --version`) |

## Gotchas

| Gotcha | Mitigation |
|---|---|
| **Long-running Codex tasks may exit non-zero before writing synthesis** even when the research itself completes successfully. The `-o` output file may contain useful results despite a non-zero exit code. | Always check the output file before treating non-zero exit as fatal failure. Pattern: `codex exec ... -o "$OUT"; if [ -s "$OUT" ]; then echo "got result"; fi` |
| `codex exec` with `--ephemeral` does NOT pollute history but the prompt is still in the running process — avoid secrets | Use env vars or file references. See HARD-RULE at top of file. |
| Background Codex jobs via `/codex:review --background` need explicit polling | Use `/codex:status` and `/codex:result` to retrieve when done. |
