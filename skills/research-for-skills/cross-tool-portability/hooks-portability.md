# Hooks Portability

Hooks (lifecycle event handlers in `settings.json`) do NOT cleanly port between Claude Code and Gemini CLI. The schemas differ and the events differ.

## Tool support matrix

| Tool | Hooks support | Schema |
|---|---|---|
| Claude Code | `~/.claude/settings.json` `hooks.<Event>[].matcher + hooks[]` | Native |
| Gemini CLI | `~/.gemini/settings.json` (via `gemini hooks migrate`) | Migrated from Claude format |
| GitHub Copilot CLI | No hooks concept | N/A |
| Codex CLI | `[UNVERIFIED]` no documented hooks | N/A |

Only Claude and Gemini have hooks. Copilot and Codex don't.

## The migration tool

`gemini hooks migrate` is a **one-shot import** from Claude Code's `settings.json` format. It:

1. Reads `~/.claude/settings.json`
2. Translates the hooks block to Gemini's schema
3. Writes the result to `~/.gemini/settings.json`
4. Exits

It is NOT a continuous sync. If you re-edit Claude's hooks, Gemini's hooks don't update. You must re-run the migration.

## Recommended workflow

1. **Author hooks in Claude's `settings.json`** as the source of truth
2. **Run `gemini hooks migrate`** once to populate Gemini
3. **Commit both files** to version control
4. **After any Claude-side hook edit, re-run the migration** and commit both updated files

Treat `~/.gemini/settings.json` hooks block as a generated artifact.

## Don't share a single hooks file

Tempting:

```bash
ln -sfn ~/.claude/settings.json ~/.gemini/settings.json   # NO
```

Why this is wrong:

1. **Schemas differ.** Claude's `hooks.PostToolUse[].matcher` may not have a 1:1 Gemini equivalent. The migration tool exists because the schemas are different.
2. **Other settings collide.** `settings.json` contains more than just hooks (model defaults, MCP servers, etc.). Sharing means polluting both tools' config.
3. **Version conflicts.** Claude and Gemini might require different schema versions.

## Hook re-entrancy

A hook in Claude that calls `gemini` (or vice versa) can recurse if the called tool also has hooks. Use the `AI_CLI_CALL_DEPTH` convention:

```bash
#!/bin/bash
# Claude hook script that calls gemini
export AI_CLI_CALL_DEPTH="${AI_CLI_CALL_DEPTH:-0}"
if [ "$AI_CLI_CALL_DEPTH" -ge 2 ]; then
  echo "Refusing to recurse: AI_CLI_CALL_DEPTH=$AI_CLI_CALL_DEPTH" >&2
  exit 0
fi
export AI_CLI_CALL_DEPTH=$((AI_CLI_CALL_DEPTH + 1))
gemini -p "..." --output-format json
```

Convention only — neither tool enforces this. See `challenger-concerns.md`.

## Portable hook patterns

If you want hooks that work in both Claude and Gemini:

1. Author the hook script as a standalone bash/python script
2. In Claude's `settings.json`, reference it via `hooks[].command`
3. After `gemini hooks migrate`, the same script is referenced by Gemini's translated config
4. The script runs the same way under both tools

The key: keep the hook **logic** in a separate script, not inline in the settings.json. The `command` reference is portable; the inline definition is not.

```bash
# ~/.claude/hooks/post-edit-format.sh
#!/bin/bash
# Format the file that was just edited
FILE="$1"
case "$FILE" in
  *.py) ruff format "$FILE" ;;
  *.ts|*.tsx) prettier --write "$FILE" ;;
  *.go) gofmt -w "$FILE" ;;
esac
```

```json
// ~/.claude/settings.json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit",
      "hooks": [{
        "type": "command",
        "command": "/home/user/.claude/hooks/post-edit-format.sh ${file}"
      }]
    }]
  }
}
```

After `gemini hooks migrate`, the same script is referenced from Gemini's settings.json.

## What `gemini hooks migrate` produces

**`[UNVERIFIED]`** locally — the exact output schema is research-grade. Test in a throwaway directory before relying:

```bash
mkdir /tmp/gemini-hooks-test && cd /tmp/gemini-hooks-test
mkdir -p .claude
cat > .claude/settings.json <<'EOF'
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit",
      "hooks": [{"type": "command", "command": "echo edited"}]
    }]
  }
}
EOF
gemini hooks migrate
cat ~/.gemini/settings.json
```

After verifying, update this file with the actual schema.

## Common hook events (Claude side)

| Event | When fires |
|---|---|
| `PreToolUse` | Before any tool call |
| `PostToolUse` | After any tool call completes |
| `Notification` | On notification (status messages) |
| `Stop` | When the agent stops |
| `UserPromptSubmit` | When the user submits a prompt |
| `SessionStart` | At session start |
| `SessionEnd` | At session end |

Whether each of these has a 1:1 Gemini equivalent is UNVERIFIED. Run the migration on a complex hook config to find out.

## Anti-patterns

| Don't | Why |
|---|---|
| Symlink `settings.json` between Claude and Gemini | Schemas differ; collides on non-hook settings |
| Re-run `gemini hooks migrate` without testing the result | One-shot, may produce surprising output |
| Inline hook scripts in `settings.json` | Portable hooks reference external scripts |
| Forget the call-depth guard | Hooks that call other CLIs can recurse infinitely |
| Trust that Claude and Gemini hook events have identical names | They may differ subtly. Verify after migration. |
| Skip version control on `~/.gemini/settings.json` | The migration output IS the source of truth for Gemini side; protect it |
