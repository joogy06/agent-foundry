# Manifest Schema Reference

JSON schema documentation for both state files produced by `probe.sh`.

## Inventory (`~/.claude/state/inventory.json`)

Persistent across sessions. Re-probed when older than 24 hours or on `--force`.

```json
{
  "version": 1,
  "last_probed": "2026-04-12T21:00:00Z",
  "tools": {
    "claude":      { "installed": true,  "version": "2.1.96" },
    "codex":       { "installed": true,  "version": "0.120.0" },
    "gemini":      { "installed": true,  "version": "0.36.2" },
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
| `version` | integer | Schema version (currently 1) |
| `last_probed` | string (ISO 8601) | UTC timestamp of last probe |
| `tools.<name>.installed` | boolean | Whether the tool binary is found via `command -v` |
| `tools.<name>.version` | string or null | Extracted semver, null if not parseable or not installed |
| `tools.bridge.installed` | boolean | Whether `bridge-mode-detect.sh` is executable at expected path |
| `tier` | integer (0-2) | Computed capability tier |
| `tier_label` | string | Human-readable tier name: minimal, standard, full |

### Tier Computation Rules

| Tier | Condition |
|------|-----------|
| 0 (minimal) | git OR python3 missing |
| 1 (standard) | git + python3 + gh + codex + gemini all installed |
| 2 (full) | tier 1 + copilot + docker + bridge all installed |

If git + python3 present but gh/codex/gemini incomplete, tier is 0.

## Session State (`$XDG_RUNTIME_DIR/env-adoption/session-<id>.json`)

Volatile, per-session. Destroyed on reboot (tmpfs). Created fresh for each session ID.

```json
{
  "session_id": "abc-123",
  "created": "2026-04-12T21:00:00Z",
  "bridge_mode": "local",
  "gemini_mcp_responding": true,
  "gh_authenticated": true,
  "gh_user": "joogy06",
  "codex_plugin_ready": true,
  "capabilities": {
    "triple_model": true,
    "codex_challenger": true,
    "gemini_analyst": true,
    "bridge_fallback": false,
    "container_workflows": true
  }
}
```

### Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | From `CLAUDE_SESSION_ID`, `FORGE_SESSION_ID`, or derived from PID |
| `created` | string (ISO 8601) | When this session state was created |
| `bridge_mode` | string | Output of `bridge-mode-detect.sh`: "local", "bridge", or "unknown" |
| `gemini_mcp_responding` | boolean | Whether Gemini CLI responds to `--version` |
| `gh_authenticated` | boolean | Whether `gh auth status` reports logged in |
| `gh_user` | string or null | GitHub username from `gh auth status` |
| `codex_plugin_ready` | boolean | Whether the Codex plugin cache dir exists |
| `capabilities.triple_model` | boolean | Codex installed AND Gemini responding |
| `capabilities.codex_challenger` | boolean | Codex installed |
| `capabilities.gemini_analyst` | boolean | Gemini responding |
| `capabilities.bridge_fallback` | boolean | Bridge mode is active |
| `capabilities.container_workflows` | boolean | Docker installed |

### Session ID Resolution

Priority order:
1. `$CLAUDE_SESSION_ID` environment variable
2. `$FORGE_SESSION_ID` environment variable
3. `ppid-<PID>` (fallback, derived from script PID)
