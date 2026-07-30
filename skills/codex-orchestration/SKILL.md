---
name: codex-orchestration
description: "Use when delegating tasks to Codex CLI (OpenAI GPT-5.6) or Antigravity CLI (agy) from Claude Code — research tasks, challenger/devil's advocate reviews, prototyping, idea generation, code review, second-opinion analysis. Covers Codex plugin commands, codex exec (incl. per-call reasoning-effort tiers), and agy -p headless mode. Triple-model orchestration for Claude + Codex + Antigravity (agy)."
disambiguation: Delegation STRATEGY across external CLIs — when to ask a second model, how to frame the task, how to weigh the answer. The `agy` binary's own flags and failure modes are antigravity-cli.
---

# Cross-Model Orchestration — Claude + Codex + Antigravity (agy)

Delegate tasks to **Codex CLI (GPT-5.6-sol)** and the **Antigravity CLI (`agy`)** from Claude Code for second opinions, parallel research, challenger reviews, and idea generation. Each model runs as an independent agent with its own context, tools, and reasoning — different models catch different things.

<HARD-RULE>
Pin reasoning effort PER CALL on every `codex exec` delegation: `-c model_reasoning_effort=<tier>` (see "Reasoning-Effort Tiers" below). Never rely on the config default — `~/.codex/config.toml` holds whatever the interactive TUI last persisted, so an unpinned headless call can silently run anywhere from `none` to `max`.
</HARD-RULE>

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

## Antigravity CLI (`agy`) — Primary Interface

The **Antigravity CLI** (`agy`) is this host's second-opinion / challenger / research delegate. It authenticates itself via the Antigravity account — no API key or env prefix needed. There is no MCP server: call `agy` directly via Bash. See the `antigravity-cli` skill for the full reference.

**Headless single-prompt mode**:

```bash
timeout 600 agy --sandbox -p "<prompt>" < /dev/null
```

- **STDIN RULE (mandatory, #135):** `< /dev/null` on every headless agy call — agy reads
  non-TTY stdin until EOF before the model call; background/harness shells never EOF → infinite
  hang at 0 bytes (`--print-timeout` does not protect; it guards only the print phase). Piped
  input (`cat file | agy -p`) is safe (the pipe EOFs). Always wrap in shell `timeout`. Same
  behavior class as `codex exec`'s stdin-block.
- **FLAG ORDER RULE (mandatory, root-caused 2026-07-02):** every flag BEFORE `-p`, prompt LAST.
  `-p` is a string flag and consumes the next token — `agy -p --sandbox "X"` runs UN-sandboxed
  with the literal prompt `--sandbox` and discards "X", after which agy improvises from its
  implicit memory (the "does work instead of consulting" failure mode) and can fork-bomb
  re-testing the broken command. Correct: `agy --sandbox [--add-dir D] [--print-timeout 15m] -p "…"`.
- **SANDBOX RULE (mandatory for analyst/read-only delegation, #157):** `--sandbox` on every agy
  call that should only READ — agy has write/shell/git tools by default, and an un-sandboxed
  "analyst" can author and git-commit code (S052 rogue auto-commit incident). Scope caveat
  (verified 2026-07-02, 1.0.15): `--sandbox` constrains shell/git commands only, NOT agy's
  native file writes — do not `--add-dir` a writable live repo for consultancy (pipe content
  instead), open the prompt with "Advisory only — do not modify any files; answer on stdout",
  and run `git status --short` afterwards if a repo was exposed. Omit `--sandbox`
  only when the task explicitly requires writes, and say so in the prompt.
- Output is **plain text on stdout** — there are no structured response fields. Callers must parse text, not JSON.
- `agy` uses the Antigravity-account default model by **convention** — as of 1.0.5+ (current **1.1.6**) a `--model` flag and an `agy models` subcommand DO exist (there is no short `-m` alias), but omit `--model` unless a call explicitly needs a specific model. The account default is **`gemini-3.6-flash`** (verified 2026-07-24), so omitting the flag rides the current line automatically. **FLASH-ONLY HARD-RULE (user directive 2026-07-24): agy runs gemini flash models ONLY.** ✅ `gemini-3.6-flash-{high,medium,low}` (current) / `gemini-3.5-flash-*` (legacy). ❌ FORBIDDEN with no carve-out: `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium`, **and `gemini-3.1-pro-{high,low}`**. Reasons: (1) provider diversity — agy holds the third-model slot because it is neither Anthropic nor OpenAI; repointing it at `claude-sonnet-4-6` (the tempting "fix" for an agy no-show) collapses the cross-check into an echo, and `gpt-oss-*` collapses into the Codex arm; (2) flash-tier discipline — agy is advisory-tier, so don't reach for pro. On a no-show: retry under the STDIN/FLAG-ORDER/Pattern-2 rules, then record the provider gap honestly — there is no gemini fallback (retired 2026-07-25). Escalate to another arm rather than repointing agy.
- For long-running prompts raise the wait timeout: `agy --print-timeout 15m -p "<prompt>" < /dev/null` (default `5m0s`). Keep `< /dev/null` even here — `--print-timeout` only guards the print phase, NOT the stdin read, so omitting it still hangs to the shell `timeout` (#135).
- Append a `served_by` probe line to the prompt if you need provenance — self-reported model identity is unreliable, so capture it at the call layer.

**Use cases** (all via a single `agy -p` call): research, analysis, code review, large-file analysis, and brainstorming (frame the methodology — SCAMPER, Design Thinking, Divergent, Convergent, Lateral — directly inside the prompt text, since there is no dedicated brainstorm tool).

### `agy -p` invocation patterns

```bash
# Basic headless mode (plain-text stdout — no JSON output mode)
agy --sandbox -p "Review this code for security issues" < /dev/null

# With piped context
cat src/main.py | agy --sandbox -p "Find N+1 query problems"

# Reference a workspace directory instead of piping (repeatable)
# CAUTION: --sandbox does NOT gate native file writes into --add-dir trees — prefer piping;
# if you must --add-dir a writable repo, run `git status --short` afterwards and revert strays.
agy --sandbox --add-dir "$PROJECT_DIR" -p "Advisory only — do not modify any files; answer on stdout. Review for security issues in this project" < /dev/null

# Structured brainstorming — frame the methodology inside the prompt
agy --sandbox -p "Use SCAMPER to generate ideas for reducing checkout abandonment. List each lens separately." < /dev/null

# Parallel with Codex (triple-model validation)
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)
AGY_WORK=$(mktemp -d /tmp/agy-XXXXXXXXXX)

timeout 600 codex exec --ephemeral -C "$PROJECT_DIR" -s read-only \
  -o "$CODEX_WORK/review.md" "Review for security issues" < /dev/null &
timeout 600 agy --sandbox --add-dir "$PROJECT_DIR" -p "Review for security issues in this project" \
  > "$AGY_WORK/review.txt" < /dev/null &
wait
```

### `agy` Availability Check

```bash
AGY_AVAILABLE=$(agy --version 2>/dev/null && echo "yes" || echo "no")
```

Cache for the session like the Codex check. Both can be checked in parallel at session start.

---

## Reasoning-Effort Tiers (benchmarked 2026-07-11)

Measured on gpt-5.6-sol / codex-cli 0.144.1 with planted-bug review fixtures (14 scored
runs, easy + hard rounds + a delta-seeking challenger round). Every tier found all planted
bugs with zero false positives; the only quality separations were (a) one subtle unplanted
defect caught only at `xhigh`/`max` under a plain review prompt, and (b) finding ALTITUDE
under a delta-seeking prompt — `medium` returned concrete-bug deltas, `xhigh` added
state-consistency reasoning, `max` alone produced a design-level finding. `high` never beat
`medium` in any run — skip it. `ultra` matched `max`'s findings at 2.3x the time on bounded
tasks; it exists for orchestrated deep dives, not verdicts.

| Tier | Use for | Typical wall-clock | Shell timeout |
|---|---|---|---|
| `medium` | Inner-loop delta passes, mechanical consults, smoke checks | ~25–40s | 600s |
| `xhigh` | Challenger, QC, devil's advocate, Gate-1 ballots, arbiter verdicts (FLOOR for these roles) | ~2–2.5 min | 600s |
| `max` | Conceptual/direction reviews, design ratification, stuck-after-2-attempts escalation, post-incident analysis | ~5–7 min | 1200s |
| `ultra` | Deliberate orchestrated deep-dives ONLY (codex spawns its own agents; rewrite the prompt contract for fan-out) | 10–30 min | 1800s+ |

```bash
# Challenger call — xhigh floor, effort pinned per call
timeout 600 codex exec --ephemeral -s read-only \
  -c model_reasoning_effort=xhigh \
  -o "$CODEX_WORK/challenge.md" "$(cat "$CODEX_WORK/brief.md")" < /dev/null
```

**Delta-seeking challenger prompt (the honest-loop contract).** Prompt shape matters as
much as tier: telling codex "the basics are done" reallocates attention to the tail — at
`medium` this recovered a subtle bug that a plain review prompt missed even at `high`.
Template to embed in challenger briefs:

> A prior review already found: `<findings list>`. Your ONLY job: find genuine defects the
> prior review MISSED. Do not repeat, rephrase, or elaborate on listed findings. Inventing
> a finding to have something to say is a failure mode; if you find nothing genuinely new,
> output exactly: NONE_FOUND

**Operational notes:**
- Retry ONCE on `Selected model is at capacity` (transient; fails within ~2s, so the retry is cheap).
- Keep `-s read-only` on every consultancy call: at `max`, codex has run unrequested
  read-only shell detours (reading its own skill files) despite an explicit "do not browse
  the filesystem" instruction — the sandbox contained it.
- `max`/`ultra` workflow stages need raised timeouts (1200s/1800s), not the default 600s.

---

## Three-Model Validation Pattern

For COMPLEX tasks, run all three models for maximum coverage:

| Model | Role | Strength |
|-------|------|----------|
| Claude (Fable 5) | Orchestrator, architect | 1M context, skills/agents, MCP, conversation memory |
| Codex (GPT-5.6-sol) | Challenger, code review | Independent perspective, web search, structured review output |
| Antigravity (`agy`) | Analyst, research | Independent third-model perspective, headless `agy -p` delegation, brainstorming |

**Diverge → Challenge → Converge:**
1. Claude explores approaches (via forge design team)
2. Codex challenges (via `/codex:adversarial-review` or raw exec)
3. agy independently analyzes (via `agy -p`)
4. Claude synthesizes — flag agreements (high confidence) and disagreements (investigate)

---

## Current State (verified 2026-07-11)

| Component | Version / Value |
|---|---|
| Codex CLI | v0.144.1 (`codex-cli`) |
| Antigravity CLI | v1.1.1 (`agy`) — headless `agy -p`, self-authenticating, no MCP wrapper |
| Default Codex model | gpt-5.6-sol (from `~/.codex/config.toml`; verified live via exec banner) |
| Default agy model | account-default model used by convention; a `--model` flag + `agy models` exist (no short `-m`), but omit `--model` unless explicitly needed |
| Reasoning effort | per-call pin (see Reasoning-Effort Tiers) — config default is TUI-persisted and untrustworthy for headless calls |
| Claude Code model | Claude Fable 5 |
| Handover mechanism | Plugin commands (preferred) OR session-scoped temp dirs + `codex exec -o` |

### System Configuration

```toml
# ~/.codex/config.toml (as of 2026-07-11) — effort levels for gpt-5.6-sol:
# low | medium (TUI default) | high | xhigh | max | ultra
model = "gpt-5.6-sol"
model_reasoning_effort = "max"   # TUI-persisted; do NOT rely on it — pin per call
```

### Model Override

The interactive `/model` picker persists both `model` and `model_reasoning_effort` into
`config.toml`, and headless `codex exec` inherits both. Omit `-m` in delegation calls
(inherit the configured model) and pin only the EFFORT per call. Use `-m` solely when a
task explicitly needs a different model than the configured default.

### Cross-Model Advantage

Claude Fable 5 and GPT-5.6-sol have different strengths. Use both:

| Strength | Claude Fable 5 | GPT-5.6-sol via Codex |
|---|---|---|
| Context window | 1M tokens | provider default (not re-verified for 5.6-sol) |
| Tool ecosystem | MCP, skills, agents, Read/Edit/Grep | Shell, file I/O, web search |
| Code editing | Precise Edit tool with diffs | Full-file rewrites |
| Orchestration | Agent spawning, parallel teams | Multi-agent feature |
| Unique value | Skill library, conversation memory | Independent perspective, web search |

**Key principle**: Use Codex for tasks where a *different model's perspective* adds value — challenger reviews, second opinions, independent research. Don't use it as a replacement for Claude's tool ecosystem.

### New since 0.118 (subcommands added through 0.137.0)

The Codex CLI grew several subcommands between 0.118 and 0.137. Most are experimental backend
services, not day-to-day delegation entry points — `codex exec` and the plugin commands remain
the orchestration surface. Confirm any of these with `codex <sub> --help` before relying on it.

| Subcommand | What it is | Relevance to orchestration |
|---|---|---|
| `codex exec-server` | [EXPERIMENTAL] Run the standalone exec-server service | Persistent backend that serves repeated `codex exec` requests without per-call spawn — relevant only if you orchestrate many non-interactive runs and want to amortise startup. |
| `codex app-server` | [experimental] Run the app server / related tooling | Backend for an app/IDE integration. Not used by headless delegation; ignore unless wiring Codex into an app. |
| `codex remote-control` | [experimental] Manage the app-server daemon with remote control enabled | Drives an app-server daemon out-of-process. Niche; not part of the `codex exec` path. |
| `codex cloud` | [EXPERIMENTAL] Browse Codex Cloud tasks and apply changes locally | Cloud delegation of long-running tasks (billed). Surfaced as an affordance; treat as opt-in. |
| `codex features` | Inspect feature flags | Read which feature flags are active (pairs with the `--enable`/`--disable` / `-c features.<name>=…` overrides). Handy when a capability is gated. |

(Also present but already documented elsewhere in this skill: `archive` / `unarchive` for saved
sessions, `mcp-server` to run Codex itself as an MCP server, `completion` for shell completions.)

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
#   -m, --model MODEL              Override model (default: from config; currently gpt-5.6-sol)
#   -c KEY=VALUE                   Config override — used for per-call effort pins
#                                  (-c model_reasoning_effort=medium|xhigh|max|ultra)
#   -C, --cd DIR                   Set working directory
#   -s, --sandbox MODE             read-only | workspace-write | danger-full-access
#   --full-auto                    Sandboxed auto-execution
#   -i, --image FILE               Attach image(s)
#
# Note: `--search` does NOT exist as a flag in current Codex CLI (verified 2026-04-08).
# Codex web search is enabled automatically by GPT-5.x tool use when the sandbox allows it.
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
timeout 600 codex exec --ephemeral --skip-git-repo-check \
  -o "$CODEX_WORK/research-output.txt" \
  "Research the top 5 approaches to container orchestration for single-node production deployments." < /dev/null

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
    -o /dev/null "Reply OK" < /dev/null 2>/dev/null; then
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
| Web research (Codex's GPT-5.x tool use does this automatically) | File editing / code writing |
| Idea generation / brainstorming | Tool-heavy workflows (MCP, Grep, Read) |
| Independent prototype exploration | Tasks needing conversation context |
| Code review (codex review) | Tasks needing memory access |
| Parallel background research | Interactive user dialogue |
| Stress-testing with different model perspective | Tasks needing Claude's agent spawning |
| Domain-specific review (with skill injection) | Multi-step orchestration (forge, agent-teams) |

---

## Shared Skill Library

Claude skills are symlinked into Codex's skill directory (`~/.codex/skills/`). Codex has access to 112 shared reference skills plus its own 7 native skills (119 total). Claude has 119 skills total.

**Symlink structure:** `~/.codex/skills/<name>` -> `~/.claude/skills/<name>`

**Skills NOT shared (Claude-specific):** `agent-teams`, `codex-orchestration`, `forge`, `vertex-banana`, `vertex-banana`, `research-for-skills`, `challenger` (Codex has native `challenger-review`).

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
| Antigravity CLI reference (full) | `antigravity-cli` |
| GitHub Copilot CLI reference | `gh-copilot-cli` |
| Cross-tool skill authoring rules | `research-for-skills/cross-tool-portability/cross-tool-portability.md` |
| GCP Workstations deployment | `gcp-workstations` |

---

## Verified facts (verified 2026-06-05)

| Fact | Status |
|---|---|
| `codex exec --search` flag | **DOES NOT EXIST**. Codex web search is automatic via GPT-5.x tool use when the sandbox allows. |
| Codex CLI version | 0.139.0 (verified locally 2026-06-10 via `codex --version`) |

## Gotchas

| Gotcha | Mitigation |
|---|---|
| **`codex exec` blocks reading stdin in non-interactive shells — even with an argv prompt.** With no prompt argument (or the explicit `-` stdin form) it hangs waiting on stdin (observed 2026-06-04); #155 (S049) established that in background/harness shells `codex exec "<argv prompt>"` ALSO reads stdin to EOF and hangs to timeout. | Close stdin on EVERY headless invocation: `codex exec "…" < /dev/null` (argv form) or piped (`cat brief.md \| codex exec -` — the pipe EOFs). Always wrap with `timeout` so any residual hang is bounded. |
| **Long-running Codex tasks may exit non-zero before writing synthesis** even when the research itself completes successfully. The `-o` output file may contain useful results despite a non-zero exit code. | Always check the output file before treating non-zero exit as fatal failure. Pattern: `codex exec ... -o "$OUT"; if [ -s "$OUT" ]; then echo "got result"; fi` |
| `codex exec` with `--ephemeral` does NOT pollute history but the prompt is still in the running process — avoid secrets | Use env vars or file references. See HARD-RULE at top of file. |
| Background Codex jobs via `/codex:review --background` need explicit polling | Use `/codex:status` and `/codex:result` to retrieve when done. |

<!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: codex
    verified_against: "0.139.0"
    verified_on: "2026-06-10"
  - kind: tool_version
    subject: agy
    verified_against: "1.0.7"
    verified_on: "2026-06-10"
  - kind: tool_version
    subject: codex-plugin
    verified_against: "1.0.4"
    verified_on: "2026-06-10"
-->
