# Manifest Schema Reference

JSON schema documentation for both state files produced by `probe.sh`.

## Inventory (`~/.claude/state/inventory.json`)

Persistent across sessions. Re-probed when older than 24 hours or on `--force`.

```json
{
  "version": 2,
  "last_probed": "2026-04-12T21:00:00Z",
  "harness": {
    "claude_version": "2.1.172",
    "workflow_tool": true,
    "native_teams": false,
    "agent_spawn": true
  },
  "tools": {
    "claude":      { "installed": true,  "version": "2.1.96" },
    "codex":       { "installed": true,  "version": "0.120.0" },
    "agy":         { "installed": true,  "version": "1.0.4" },
    "copilot":     { "installed": false, "version": null },
    "gh":          { "installed": true,  "version": "2.87.0" },
    "git":         { "installed": true,  "version": "2.47.1" },
    "docker":      { "installed": true,  "version": "27.1.1" },
    "python3":     { "installed": true,  "version": "3.12.12" },
    "jq":          { "installed": true,  "version": null },
    "yq":          { "installed": true,  "version": "4.47.1" },
    "openssl":     { "installed": true,  "version": "3.5.1" },
    "bridge":      { "installed": true },

    "bandit":      { "installed": false, "version": null },
    "semgrep":     { "installed": false, "version": null },
    "gitleaks":    { "installed": false, "version": null },
    "trufflehog":  { "installed": false, "version": null },
    "trivy":       { "installed": false, "version": null },
    "pip-audit":   { "installed": true,  "version": "2.9.0" },
    "osv-scanner": { "installed": false, "version": null },
    "govulncheck": { "installed": false, "version": null }
  },
  "tier": 1,
  "tier_label": "standard"
}
```

The `bandit` / `semgrep` / `gitleaks` / `trufflehog` / `trivy` / `pip-audit` / `osv-scanner` / `govulncheck` entries were added by S038 Batch A (2026-05-22) for downstream security skills (`sast-tooling`, `secret-scanning`, `dep-currency-check`, the future `G_SECURE` gate). Read these from `inventory.json` instead of inline `command -v` probing.

### Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `version` | integer | Schema version (currently **2** — S055 added the `harness` block; a fresh-but-v1 inventory auto-migrates on next probe) |
| `last_probed` | string (ISO 8601) | UTC timestamp of last probe |
| `harness.claude_version` | string or null | Copy of `tools.claude.version`, same probe run |
| `harness.workflow_tool` | boolean | `version_ge(claude_version, "2.1.154")` — Q1 host capability for the Workflow tool. Fail-closed: missing/unparseable version ⇒ `false` |
| `harness.native_teams` | boolean | `version_ge(claude_version, "2.1.32")` AND the experimental gate (`CLAUDE_NATIVE_TEAMS=1`/`CLAUDE_CODE_NATIVE_TEAMS=1` env OR `settings.json experimental.nativeTeams`) |
| `harness.agent_spawn` | boolean | claude installed AND version parseable |
| `tools.<name>.installed` | boolean | Whether the tool binary is found via `command -v` |
| `tools.<name>.version` | string or null | Extracted semver, null if not parseable or not installed |
| `tools.bridge.installed` | boolean | Whether `bridge-mode-detect.sh` is executable at expected path |
| `tier` | integer (0-2) | Computed capability tier |
| `tier_label` | string | Human-readable tier name: minimal, standard, full |

### Tier Computation Rules

| Tier | Condition |
|------|-----------|
| 0 (minimal) | git OR python3 missing |
| 1 (standard) | git + python3 + gh + codex + agy all installed |
| 2 (full) | tier 1 + copilot + docker + bridge all installed |

If git + python3 present but gh/codex/agy incomplete, tier is 0.

## Session State (`$XDG_RUNTIME_DIR/env-adoption/session-<id>.json`)

Volatile, per-session. Destroyed on reboot (tmpfs). Created fresh for each session ID.

```json
{
  "schema_version": 2,
  "session_id": "abc-123",
  "created": "2026-04-12T21:00:00Z",
  "bridge_mode": "local",
  "agy_responding": true,
  "gh_authenticated": true,
  "gh_user": "your-gh-user",
  "codex_plugin_ready": true,
  "claude_version_live": "2.1.172",
  "capabilities": {
    "triple_model": true,
    "codex_challenger": true,
    "agy_analyst": true,
    "bridge_fallback": false,
    "container_workflows": true,
    "workflow_tool": true,
    "native_teams": false,
    "agent_spawn": true
  }
}
```

### Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | integer | Session schema version (currently **2** — S055) |
| `session_id` | string | From `CLAUDE_CODE_SESSION_ID`, `CLAUDE_SESSION_ID`, `FORGE_SESSION_ID`, or derived from PID |
| `created` | string (ISO 8601) | When this session state was created |
| `bridge_mode` | string | Output of `bridge-mode-detect.sh`: "local", "bridge", or "unknown" |
| `agy_responding` | boolean | Whether the Antigravity CLI (`agy`) responds to `--version` |
| `gh_authenticated` | boolean | Whether `gh auth status` reports logged in |
| `gh_user` | string or null | GitHub username from `gh auth status` |
| `codex_plugin_ready` | boolean | Whether the Codex plugin cache dir exists |
| `claude_version_live` | string or null | LIVE `timeout 2 claude --version` re-parse (the 24h inventory cache lags same-day auto-updates) |
| `capabilities.triple_model` | boolean | Codex installed AND agy responding |
| `capabilities.codex_challenger` | boolean | Codex installed |
| `capabilities.agy_analyst` | boolean | agy responding |
| `capabilities.bridge_fallback` | boolean | Bridge mode is active |
| `capabilities.container_workflows` | boolean | Docker installed |
| `capabilities.workflow_tool` | boolean | `version_ge(claude_version_live, "2.1.154")` AND `current_cli == "claude-code"` (Q2 — host session only) |
| `capabilities.native_teams` | boolean | workflow-gate AND `version_ge(.., "2.1.32")` AND live env gate AND `current_cli == "claude-code"` |
| `capabilities.agent_spawn` | boolean | claude version parseable live AND `current_cli == "claude-code"` |

> **`probe.sh get capabilities.<name>` is the ONLY consumer API for capability reads.** No skill, agent, launcher, or workflow may read `inventory.json` capability fields with raw `jq`, and none may inline-probe `claude --version`. (S055 R1 / HO-2.)

> **`capabilities.*` answers Q2 (does this SESSION's harness expose the surface) for the HOST session ONLY — it NEVER authorizes orchestration on its own.** Session files are keyed by the ROOT session ID and are **shared with subagents** (children inherit `CLAUDE_CODE_SESSION_ID`), so a subagent reading `capabilities.workflow_tool` sees the parent's value. The decision rule, restated in every consumer, is:
>
> ```
> can_orchestrate = capabilities.<surface> AND context == main-loop
> ```
>
> See `references/context-detection.md` for the live Q3 recipe.

### Session ID Resolution

Priority order (S055 fix — `CLAUDE_CODE_SESSION_ID` is the real harness key that
children inherit; before it, the `ppid-<PID>` fallback always fired and left
stale tmpfs session files):
1. `$CLAUDE_CODE_SESSION_ID` environment variable (harness-canonical)
2. `$CLAUDE_SESSION_ID` environment variable (legacy)
3. `$FORGE_SESSION_ID` environment variable
4. `ppid-<PID>` (fallback, derived from script PID)

Session files older than 7 days are pruned on every `probe.sh check`.

---

## Inventory extra surfaces — plugins & MCP servers (Evergreening v1, S041)

On a REAL probe (cache-miss / `--force`), `inventory_history.py` MERGES two extra
surfaces into `inventory.json` so downstream consumers (the freshness nudge, the rot
scanner's tool cross-reference) can see them:

```json
{
  "plugins": {
    "superpowers@superpowers-marketplace": { "enabled": true,  "version": "5.1.0" },
    "codex@openai-codex":                   { "enabled": true,  "version": null    }
  },
  "mcp_servers": ["chrome-devtools", "pa-server", "wordpress-mcp"],
  "coverage": { "plugins": "full", "mcp_servers": "full" }
}
```

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| `plugins.<id>.enabled` | boolean | `enabledPlugins` map in `settings.json` | `<id>` is the `name@marketplace` key |
| `plugins.<id>.version` | string or null | the plugin's `package.json` in `plugins/cache/` | `null` when the plugin ships no version |
| `mcp_servers` | string[] | `mcpServers` in `~/.claude.json` (top-level + project-scoped, unioned, sorted) | name list only — no config/secrets |
| `coverage.plugins` | `"full"` \| `"partial"` | derived | `partial` when no plugins map was found (absence reads as partial, NEVER a phantom remove) |
| `coverage.mcp_servers` | `"full"` \| `"partial"` | derived | same partial-on-absence rule |

**Key-name provenance (spec-review Issue 3):** the live key names were verified against
the running system before wiring — `enabledPlugins` (dict of `"name@marketplace": bool`)
in `settings.json`; `mcpServers` (dict of name→config) at the top level of `~/.claude.json`.
If a future Claude Code release renames or reshapes these, the collector records `{}` / `[]`
and `coverage: partial` rather than guessing — a missing surface must never manufacture an
add/remove delta.

## Change-record history (`~/.claude/state/inventory-history.jsonl`)

Append-only JSONL. One record PER CHANGE, written (O_APPEND, best-effort-never-raise) on a
REAL probe by `inventory_history.py`, after it diffs `inventory.json` against the prior
snapshot (`inventory-prev.json`, copied before the overwrite). **No change → no record** (the
debounce primitive that makes the change-record shape robust to missed probes and multi-change
windows — Adjudication 2). The FIRST-ever probe (no prev snapshot) emits nothing.

```json
{"schema_version":"inventory-history.v1","ts":"2026-06-04T23:11:16Z","surface":"cli","id":"codex","field":"version","before":"0.136.0","after":"0.137.0","severity":"minor","probe_id":"<uuid>"}
```

| Field | Type | Values / Notes |
|-------|------|----------------|
| `schema_version` | string | `"inventory-history.v1"` |
| `ts` | string (ISO 8601 UTC) | record write time |
| `surface` | string | `cli` \| `plugin` \| `mcp` \| `tool` (`cli` = claude/codex/agy/copilot/gh; `tool` = git/docker/jq/security tools/…) |
| `id` | string | tool name, `name@marketplace` plugin id, or MCP server name |
| `field` | string | `version` \| `presence` |
| `before` / `after` | string \| bool \| null | prior and new value (booleans for `presence`) |
| `severity` | string | `patch` \| `minor` \| `major` \| `added` \| `removed`. Semver compare at write; **0.x tools treat the second digit as minor** |
| `probe_id` | string (uuid) | groups all records emitted by one probe run |

### Privacy / publish guard

The entire `state/` tree — `inventory-history.jsonl`, `inventory-prev.json`, and the
`state/freshness/*` engine outputs — is **local detection state and never publishes**. It is
listed in `~/.claude/publish-config.json` `exclusions` (belt-and-braces, since `state/` already
lives outside the published `skills/agents/commands` source roots). The history can name local
plugins and MCP servers; keeping it out of the public mirror is intentional (#62 precedent). The
publish-ignore ships in the SAME work package as the writer (§6.1 / §6.13).
