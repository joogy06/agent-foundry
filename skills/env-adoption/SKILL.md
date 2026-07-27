---
name: env-adoption
description: Use when checking tool availability (Codex, Antigravity CLI (agy), Copilot, gh, Docker), determining environment tier, reading cached inventory or session state, setting up missing tools, or when any skill needs to know what capabilities are available in the current environment.
---

# Environment Adoption — Centralized Capability Registry

## Overview

Single source of truth for tool detection, version tracking, and capability routing. Two-tier state model: persistent inventory (what is installed) and volatile session state (runtime connectivity, auth). Replaces scattered inline probing across forge, codex-orchestration, and other skills.

## When to Use

- Session start — probe environment, report tier
- Before delegating to Codex/agy — check `tools.codex.installed` / `capabilities.agy_analyst`
- When a skill needs to branch on tool availability — use `get` subcommand
- After installing a new tool — run `probe.sh check --force` to update inventory

## When NOT to Use

- Do not re-probe on every skill invocation (read the manifest instead)
- Do not use for Codex session management (use `codex-orchestration`)

## Operations

| Operation | Command | Purpose |
|-----------|---------|---------|
| **check** | `bash ~/.claude/skills/env-adoption/scripts/probe.sh check` | Probe tools, write inventory + session state |
| **get** | `bash ~/.claude/skills/env-adoption/scripts/probe.sh get <path>` | Read a value from inventory or session state |
| **context** | `bash ~/.claude/skills/env-adoption/scripts/probe.sh context` | **Live Q3** — `main-loop` \| `child-session` \| `non-claude-host[:<id>]`. Pure env eval, NEVER cached. See `references/context-detection.md` |
| **setup** | `bash ~/.claude/skills/env-adoption/scripts/probe.sh setup` | Interactive guided install for missing tools |

### check flags

| Flag | Effect |
|------|--------|
| `--inventory-only` | Skip session state (connectivity checks) |
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
probe.sh get capabilities.triple_model     # true/false
probe.sh get capabilities.codex_challenger # true/false
probe.sh get capabilities.agy_analyst      # true/false

# Orchestration capabilities (S055 — workflow-adoption keystone)
probe.sh get capabilities.workflow_tool    # true/false  (Workflow tool surface, Q2)
probe.sh get capabilities.native_teams     # true/false  (experimental, env-gated)
probe.sh get capabilities.agent_spawn      # true/false  (Agent/subagent surface)
probe.sh get harness.workflow_tool         # true/false  (Q1 host capability, inventory)
```

> **Orchestration decision rule (restate verbatim in every consumer):**
> `can_orchestrate = capabilities.<surface> AND context == main-loop`.
> `capabilities.*` alone NEVER authorizes orchestration — session files are
> shared with subagents (children inherit `CLAUDE_CODE_SESSION_ID`), so the
> `probe.sh context` conjunct is mandatory. `probe.sh get capabilities.<name>`
> is the ONLY capability read API — no raw `jq` on `inventory.json`, no inline
> `claude --version`. See `references/context-detection.md`.

## Tier Model

| Tier | Label | Requirements | What works |
|------|-------|-------------|------------|
| 0 | **minimal** | git + python3 | All skills as reference, wiki agent |
| 1 | **standard** | + gh + codex + agy | forge/bob/alf with multi-model reviews |
| 2 | **full** | + copilot + docker | Everything incl. containers |

## State Files

| File | Lifecycle | Content |
|------|-----------|---------|
| `~/.claude/state/inventory.json` | Persistent, re-probed if >24h old | Tools, versions, tier |
| `$XDG_RUNTIME_DIR/env-adoption/session-<id>.json` | Volatile, per-session | Auth, MCP, capabilities |

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
| Make state bash-sourceable | Shell-specific, security risk | JSON canonical, `get` helper for shell |
| Single file for inventory + session | Different lifecycles, session interference | Two-tier: persistent + volatile |
| Probe on every skill invocation | Performance death by 1000 probes | Probe once, read many |
| Hard-fail when manifest missing | Breaks fresh installs | Auto-probe on first read, degrade gracefully |
| Bypass `get` with hardcoded paths | Breaks if state location changes | Use `get` or read documented paths |
