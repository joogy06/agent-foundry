# Hooks Portability

Hooks (lifecycle event handlers in `settings.json`) are a **Claude Code-native** mechanism. Among the four cross-tool CLIs, only Claude Code has a verified hooks system. There is **no verified hooks contract for the Antigravity CLI (`agy`)** — see the TODO(agy) note below.

> The retired Gemini CLI shipped a `gemini hooks migrate` one-shot importer from Claude's `settings.json`. **That mechanism is gone** along with the gemini CLI. Do NOT assume agy has an equivalent.

## Tool support matrix

| Tool | Hooks support | Schema |
|---|---|---|
| Claude Code | `~/.claude/settings.json` `hooks.<Event>[].matcher + hooks[]` | Native (verified) |
| Antigravity CLI (`agy`) | TODO(agy): verify equivalent — no confirmed hooks system or migration tool | Unverified |
| GitHub Copilot CLI | No hooks concept | N/A |
| Codex CLI | `[UNVERIFIED]` no documented hooks | N/A |

Only Claude Code has a verified hooks system. Author and run hooks on the Claude side; do not assume they port.

## Authoring hooks (Claude side)

Author hooks in Claude's `settings.json` as the source of truth, and keep the hook **logic** in standalone scripts (not inline in settings.json). A `command:` reference to an external script is the most portable form should any other tool gain a compatible hooks system later.

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

The key: keep the hook **logic** in a separate script. The `command` reference is the portable part; the inline definition is tool-specific.

## Cross-CLI hook re-entrancy

A Claude hook that shells out to another AI CLI (e.g. `agy`) can recurse if the called tool also runs hooks. Even though agy's hooks support is unverified, guard any hook that invokes another CLI with the `AI_CLI_CALL_DEPTH` convention:

```bash
#!/bin/bash
# Claude hook script that calls agy
export AI_CLI_CALL_DEPTH="${AI_CLI_CALL_DEPTH:-0}"
if [ "$AI_CLI_CALL_DEPTH" -ge 2 ]; then
  echo "Refusing to recurse: AI_CLI_CALL_DEPTH=$AI_CLI_CALL_DEPTH" >&2
  exit 0
fi
export AI_CLI_CALL_DEPTH=$((AI_CLI_CALL_DEPTH + 1))
agy -p "..."
```

Notes on the `agy` call: no `-m`/`--model` flag, no `GOOGLE_CLOUD_PROJECT=`/`GEMINI_API_KEY=` env prefix (agy authenticates via its own account), and output is plain text on stdout — parse text, not JSON.

Convention only — neither tool enforces this. See `challenger-concerns.md`.

## agy hooks — what is NOT verified

TODO(agy): verify equivalent. The following were Gemini-CLI-specific and have **no confirmed agy analogue**. Do not document any of these as supported for agy without checking `agy help` / `agy <sub> --help`:

- A `settings.json` hooks block / event schema (`PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, etc.).
- A migration tool (the retired `gemini hooks migrate` has no agy successor).
- Hook-event names matching Claude's set 1:1.

If a workflow needs lifecycle hooks on the agy side, probe `agy help` first and confirm before relying on it.

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

These are Claude Code events. Whether agy exposes anything comparable is UNVERIFIED.

## Anti-patterns

| Don't | Why |
|---|---|
| Assume agy has a hooks system | Unverified. Probe `agy help` before relying on lifecycle hooks. |
| Inline hook scripts in `settings.json` | Portable hooks reference external scripts |
| Forget the call-depth guard | Hooks that call other CLIs can recurse infinitely |
| Pass `-m <model>` or a `GEMINI_API_KEY=` prefix to `agy` in a hook | agy has no model flag and no env-key prefix; both are retired-gemini patterns |
| Treat Claude hook events as cross-tool | Only Claude's hooks system is verified |
