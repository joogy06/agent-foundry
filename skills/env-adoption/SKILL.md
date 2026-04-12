---
name: env-adoption
description: Use when checking tool availability (Codex, Gemini, Copilot, gh, Docker, bridge), determining environment tier, reading cached inventory or session state, setting up missing tools, or when any skill needs to know what capabilities are available in the current environment.
---

# Environment Adoption — Centralized Capability Registry

## Overview

Single source of truth for tool detection, version tracking, and capability routing. Two-tier state model: persistent inventory (what is installed) and volatile session state (runtime connectivity, bridge mode, auth). Replaces scattered inline probing across forge, codex-orchestration, and other skills.

## When to Use

- Session start — probe environment, report tier
- Before delegating to Codex/Gemini — check `tools.codex.installed` / `capabilities.gemini_analyst`
- Before bridge routing — read `session.bridge_mode`
- When a skill needs to branch on tool availability — use `get` subcommand
- After installing a new tool — run `probe.sh check --force` to update inventory

## When NOT to Use

- Do not re-probe on every skill invocation (read the manifest instead)
- Do not use for bridge-mode hysteresis logic (that lives in `bridge-mode-detect.sh` — this skill *composes* with it)
- Do not use for Codex session management (use `codex-orchestration`)

## Operations

| Operation | Command | Purpose |
|-----------|---------|---------|
| **check** | `bash ~/.claude/skills/env-adoption/scripts/probe.sh check` | Probe tools, write inventory + session state |
| **get** | `bash ~/.claude/skills/env-adoption/scripts/probe.sh get <path>` | Read a value from inventory or session state |
| **setup** | `bash ~/.claude/skills/env-adoption/scripts/probe.sh setup` | Interactive guided install for missing tools |

### check flags

| Flag | Effect |
|------|--------|
| `--inventory-only` | Skip session state (connectivity checks, bridge mode) |
| `--force` | Re-probe even if inventory is fresh (<24h) |
| `--silent` | No stdout, just write state files |
| `--json` | Output combined inventory + session state as JSON |

### get paths

```bash
# Inventory (persistent)
probe.sh get tools.codex.installed    # true/false
probe.sh get tools.codex.version      # "0.120.0" or null
probe.sh get tier                     # 0, 1, or 2
probe.sh get tier_label               # minimal, standard, full

# Session state (volatile)
probe.sh get session.bridge_mode           # local/bridge/unknown
probe.sh get capabilities.triple_model     # true/false
probe.sh get capabilities.codex_challenger # true/false
probe.sh get capabilities.gemini_analyst   # true/false
```

## Tier Model

| Tier | Label | Requirements | What works |
|------|-------|-------------|------------|
| 0 | **minimal** | git + python3 | All skills as reference, wiki agent |
| 1 | **standard** | + gh + codex + gemini | forge/bob/alf with multi-model reviews |
| 2 | **full** | + copilot + docker + bridge | Everything incl. bridge fallback, containers |

## State Files

| File | Lifecycle | Content |
|------|-----------|---------|
| `~/.claude/state/inventory.json` | Persistent, re-probed if >24h old | Tools, versions, tier |
| `$XDG_RUNTIME_DIR/env-adoption/session-<id>.json` | Volatile, per-session | Bridge mode, auth, MCP, capabilities |

## Integration

Other skills consume the manifest instead of inline probing:

```bash
# Shell: via get subcommand
CODEX_OK=$(bash ~/.claude/skills/env-adoption/scripts/probe.sh get tools.codex.installed)

# Shell: via direct jq (faster, for hot paths)
CODEX_OK=$(jq -r '.tools.codex.installed' ~/.claude/state/inventory.json 2>/dev/null || echo false)

# Skill YAML/markdown: read ~/.claude/state/inventory.json
# Session routing: read $XDG_RUNTIME_DIR/env-adoption/session-*.json
```

See `references/integration.md` for full patterns.

## Anti-Patterns

| Don't | Why | Do Instead |
|-------|-----|------------|
| Reimplement bridge-mode-detect.sh | Two sources of truth, regression risk | Call it and record output |
| Make state bash-sourceable | Shell-specific, security risk | JSON canonical, `get` helper for shell |
| Single file for inventory + session | Different lifecycles, session interference | Two-tier: persistent + volatile |
| Probe on every skill invocation | Performance death by 1000 probes | Probe once, read many |
| Hard-fail when manifest missing | Breaks fresh installs | Auto-probe on first read, degrade gracefully |
| Bypass `get` with hardcoded paths | Breaks if state location changes | Use `get` or read documented paths |
