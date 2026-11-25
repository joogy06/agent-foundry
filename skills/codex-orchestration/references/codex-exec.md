# Codex Orchestration — `codex exec` recipes

Read this file before writing a raw `codex exec` call. When it is read, return to SKILL.md.

"HARD-RULE at top" and "Seat Models" mean SKILL.md: its opening hard rules and its "Seat Models" section. The session directory rule and its recipe (`CODEX_WORK`) are in SKILL.md, under "Session Directory (REQUIRED)"; create that directory before running the patterns below.

## Core Integration: `codex exec`

The key command for non-interactive delegation:

```bash
codex exec [OPTIONS] [PROMPT]
# Or pipe prompt via stdin ($PIN = the seat_model argv fragment — always present):
echo "prompt" | codex exec $PIN -

# Critical flags:
#   --ephemeral                    Don't persist session files — NEVER on a role-resolved seat call
#                                  (TOP or consultant_support): the rollout records quota (HARD-RULE at top)
#   --skip-git-repo-check          Allow running outside git repos
#   -o, --output-last-message FILE Write final response to file
#   --json                         Stream JSONL events to stdout
#   --output-schema FILE           Enforce structured JSON output
#   -m, --model MODEL              ALWAYS set — via the seat_model argv fragment ($PIN); the
#                                  config default is whatever the TUI last persisted
#   -c KEY=VALUE                   Config override — carries the per-call effort pin inside $PIN
#                                  (-c model_reasoning_effort=low|medium|high|xhigh|max|ultra)
#   -C, --cd DIR                   Set working directory
#   -s, --sandbox MODE             read-only | workspace-write | danger-full-access
#   --full-auto                    Sandboxed auto-execution
#   -i, --image FILE               Attach image(s)
#
# Note: `--search` does NOT exist as a flag (re-checked against `codex exec --help`, 0.154.0,
# 2026-09-14). Codex web search is enabled automatically by the model's tool use when the sandbox
# allows it. Earlier versions of this skill mentioned --search; that was incorrect.
```

### Basic Delegation Pattern

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX) || exit 1

# Delegate a research task, capture output. consultant_support (the codex support tier @ medium) is
# a support role: no budget admit is needed, and no --ephemeral (its rollout meters the quota).
# Main-seat research uses consultant_main instead (admit first — see Seat Models).
PIN="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_support --provider codex)" \
  && timeout 600 codex exec --skip-git-repo-check $PIN \
       -o "$CODEX_WORK/research-output.txt" \
       "Research the top 5 approaches to container orchestration for single-node production deployments." < /dev/null

# Read the result back into Claude Code
# Read: $CODEX_WORK/research-output.txt
```

### Full Availability Check (When Needed)

```bash
check_codex() {
  if ! command -v codex &>/dev/null; then
    echo "UNAVAILABLE: codex not installed"
    return 1
  fi

  # Quick test (timeout after 10s) — pinned like every other call (support role, non-ephemeral)
  local PIN
  if ! PIN="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_support --provider codex)"; then
    echo "UNAVAILABLE: no codex seat pin resolved (seat_model.py failed)"
    return 1
  fi
  if ! timeout 10 codex exec --skip-git-repo-check $PIN \
    -o /dev/null "Reply OK" < /dev/null 2>/dev/null; then
    echo "UNAVAILABLE: codex auth/subscription issue"
    return 1
  fi

  echo "AVAILABLE"
  return 0
}
```
