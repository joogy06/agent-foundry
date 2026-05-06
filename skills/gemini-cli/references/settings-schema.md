# Gemini settings.json Schema

The local Gemini CLI 0.36.0 reads configuration from `~/.gemini/settings.json` (and project-scoped overrides). The exact schema is **UNVERIFIED** on this machine — this file is research-grade and should be confirmed on first deploy.

## Top-level structure (research-grade)

From Google's docs (not yet verified locally):

```json
{
  "general": { ... },
  "ui": { ... },
  "model": { ... },
  "context": { ... },
  "tools": { ... },
  "mcpServers": { ... },
  "hooks": { ... },
  "experimental": { ... }
}
```

## Block-by-block

### `general`

```json
{
  "general": {
    "telemetry": false,
    "checkForUpdates": true
  }
}
```

### `ui`

```json
{
  "ui": {
    "theme": "dark",
    "showStatusLine": true
  }
}
```

### `model`

**Schema-key discrepancy (verified 2026-05-04):** the bundled docs at `/usr/local/lib/node_modules/@google/gemini-cli/bundle/docs/cli/settings.md` document the model key as **`model.name`**. This skill's schema (Google docs research) documents it as **`model.default` + `model.fallback`**. Set both for forward-compat; CLI 0.40.1 reads at least one of them.

```json
{
  "model": {
    "name": "gemini-3.1-pro-preview",
    "default": "gemini-3.1-pro-preview",
    "fallback": "gemini-2.5-pro",
    "temperature": 0.2
  }
}
```

**Important caveat (verified 2026-05-04):** pinning these keys does NOT guarantee the requested model is served. The OAuth subscription tier may silently route to a different model (e.g., requested `gemini-3.1-pro-preview`, served `gemini-2.5-pro`). The `-m <model>` CLI flag is also advisory. Always capture which model actually answered via a `served_by=<model_id>` probe line in the prompt — see `headless.md` "Capturing served_by" section.

**Recommendation on this host:** keep the canonical pattern (env prefix + `-m gemini-3.1-pro-preview` + served_by capture) AND pin the model in settings.json. Belt + braces.

### `context`

Determines what the model auto-loads at session start.

```json
{
  "context": {
    "fileDiscovery": ["GEMINI.md", "AGENTS.md"],
    "maxContextChars": 12000
  }
}
```

### `tools`

```json
{
  "tools": {
    "allowed": ["read_file", "list_directory"],
    "denied": ["run_command"]
  }
}
```

**Note**: As of 0.36.0, `tools.allowed` may be deprecated in favour of the Policy Engine — see `policy-engine.md`. Check on first deploy.

### `mcpServers`

```json
{
  "mcpServers": {
    "github": {
      "command": "/usr/local/bin/github-mcp",
      "args": ["--token", "${GITHUB_TOKEN}"],
      "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
    },
    "linter": {
      "url": "https://linter.example.com/mcp/sse"
    }
  }
}
```

### `hooks`

The output of `gemini hooks migrate` lands here. Schema mirrors Claude's, but the exact differences are **UNVERIFIED**:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit",
        "hooks": [{"type": "command", "command": "echo before edit"}]
      }
    ]
  }
}
```

### `experimental`

Reserved for opt-in features. Use sparingly.

## Sources of settings

1. `~/.gemini/settings.json` — user-global
2. `./.gemini/settings.json` — project (if exists)
3. CLI flags — override above

Specific override semantics (deep merge vs replace) are **UNVERIFIED**.

## How to verify on this machine

```bash
ls -la ~/.gemini/
# look for settings.json

cat ~/.gemini/settings.json 2>/dev/null | python3 -m json.tool
# or
cat ~/.gemini/settings.json 2>/dev/null | jq .
```

If the file doesn't exist, Gemini uses defaults. Create it manually or via `gemini` subcommands (e.g. `gemini mcp add` writes to it).

## Sanity check after editing

```bash
python3 -c "import json; json.load(open('$HOME/.gemini/settings.json'))" \
  && echo "settings.json is valid JSON" \
  || echo "settings.json is BROKEN"
```

This is part of `scripts/verify-gemini-install.sh`.

## Anti-patterns

| Don't | Why |
|---|---|
| Edit `~/.gemini/settings.json` without backing up | One bad keystroke breaks all Gemini config |
| Mix the deprecated `tools.allowed` with `--policy` | Pick one. Policy Engine wins. |
| Inline secrets in `mcpServers.*.env` | Use env-var interpolation `"${TOKEN}"` and set `TOKEN` at runtime via Secret Manager / `keychain` |
| Assume the schema is stable across minor versions | 0.36.0 → 0.37.0 may shift fields. Re-verify on upgrade. |
| Edit settings.json while Gemini is running interactively | Hot-reload behaviour is **UNVERIFIED** — restart Gemini after edits to be safe |

## See also

- `mcp.md` — `mcpServers` block details
- `hooks.md` — `hooks` block via `gemini hooks migrate`
- `policy-engine.md` — `--policy` and `--admin-policy` flags vs in-file `tools.allowed`
- `auth.md` — auth env vars (NOT in settings.json)
