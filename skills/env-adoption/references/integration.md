# Integration Guide

How other skills and agents consume the env-adoption manifest.

## Quick Reference

```bash
# Check if a tool is installed
bash ~/.claude/skills/env-adoption/scripts/probe.sh get tools.codex.installed

# Get current tier
bash ~/.claude/skills/env-adoption/scripts/probe.sh get tier

# Get bridge mode for current session
bash ~/.claude/skills/env-adoption/scripts/probe.sh get session.bridge_mode

# Check a capability
bash ~/.claude/skills/env-adoption/scripts/probe.sh get capabilities.triple_model

# Direct jq for performance-critical paths (skips probe.sh overhead)
jq -r '.tools.codex.installed' ~/.claude/state/inventory.json 2>/dev/null || echo false
jq -r '.tier' ~/.claude/state/inventory.json 2>/dev/null || echo 0
```

## Integration Patterns by Consumer

### forge (step 4b)

Before env-adoption, forge step 4b did inline probing (`codex --version`, `agy --version`). After:

```
Read ~/.claude/state/inventory.json for tool availability.
Read $XDG_RUNTIME_DIR/env-adoption/session-<id>.json for capabilities.
Branch on capabilities:
  if capabilities.codex_challenger -> use Codex
  if capabilities.agy_analyst -> use agy (Antigravity CLI)
  if capabilities.bridge_fallback -> route through bridge
```

### codex-orchestration

Before: "Always check Codex availability before delegating. Run `codex --version` first."
After: "Read `tools.codex.installed` from `~/.claude/state/inventory.json`. If false, skip Codex delegation."

### hard-rules-checklist

Before: Individual per-tool check reminders.
After: "Verify env-adoption session state exists for current session."

### Shell scripts in other skills

```bash
# Pattern 1: via get subcommand (auto-probes if missing)
CODEX_OK=$(bash ~/.claude/skills/env-adoption/scripts/probe.sh get tools.codex.installed)
if [ "$CODEX_OK" = "true" ]; then
  # delegate to codex
fi

# Pattern 2: direct jq (faster, no auto-probe)
TIER=$(jq -r '.tier' ~/.claude/state/inventory.json 2>/dev/null || echo 0)
if [ "$TIER" -ge 1 ]; then
  # standard tier features available
fi
```

### CLAUDE.md session start

```markdown
On session start, run `bash ~/.claude/skills/env-adoption/scripts/probe.sh check`
(or read existing inventory if <24h old and create session state for current session).
Report tier and capabilities.
```

## Staleness Rules

| Condition | Behavior |
|-----------|----------|
| inventory.json missing | `get` auto-probes on first read |
| inventory.json > 24h old | `check` re-probes automatically |
| session state missing | `get session.*` auto-probes |
| `CLAUDE_REPROBE=1` env var | Force re-probe regardless of age |
| Tool installed/removed mid-session | User runs `probe.sh check --force` |

## Graceful Degradation

If inventory.json does not exist and cannot be created (e.g., read-only filesystem), skills should fall back to inline `command -v` checks. The env-adoption skill is an optimization, not a hard dependency.
