# Gemini CLI Hooks

Gemini CLI ships with exactly **one** hook subcommand:

```
gemini hooks migrate    Migrate hooks from Claude Code to Gemini CLI
```

Verified locally on 2026-04-08:

```
$ gemini hooks --help
gemini hooks <command>

Manage Gemini CLI hooks.

Commands:
  gemini hooks migrate  Migrate hooks from Claude Code to Gemini CLI
```

There are **no** add/list/remove/edit subcommands surfaced via `--help`. Hook management appears to happen through `~/.gemini/settings.json` directly (similar to Claude's `~/.claude/settings.json`).

## What `gemini hooks migrate` does

Migrates a Claude Code-style hooks block from `~/.claude/settings.json` into Gemini's settings format. Treat this as a **one-shot import**, not a live sync:

1. Run `gemini hooks migrate` once after installing Gemini
2. Review the result in `~/.gemini/settings.json`
3. Commit both files
4. After this point, treat the Gemini hook block as a generated artifact

If you re-edit the Claude side, you must re-run the migration and re-review the diff. There is no live sync.

## Limitations and unknowns

**UNVERIFIED:**

- What format the migration produces (presumably analogous to Claude's `hooks.{Event}[].matcher + hooks[]` schema)
- Which hook events are supported (PreToolUse, PostToolUse, Notification, Stop, etc. — Claude's full set)
- Whether matchers translate correctly
- Whether the migration is idempotent or destructive
- Whether already-migrated hooks are detected and skipped

**Test in a throwaway directory first:**

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
ls -la ~/.gemini/settings.json && cat ~/.gemini/settings.json
```

This test path is documented as G4 in the design doc's first-boot verification gates.

## Re-entrancy

Hooks defined in Gemini that invoke `gemini`, `claude`, or `codex` can recurse if the called CLI also has hooks. Use the `AI_CLI_CALL_DEPTH` convention from `cross-tool-portability/challenger-concerns.md`:

```bash
#!/bin/bash
# Force OAuth subscription path when the shell has GOOGLE_CLOUD_PROJECT / GEMINI_API_KEY set for other Google tooling
export GOOGLE_CLOUD_PROJECT=
export GEMINI_API_KEY=
export AI_CLI_CALL_DEPTH="${AI_CLI_CALL_DEPTH:-0}"
if [ "$AI_CLI_CALL_DEPTH" -ge 2 ]; then
  exit 0
fi
export AI_CLI_CALL_DEPTH=$((AI_CLI_CALL_DEPTH + 1))
gemini -p --output-format json "..."
```

Convention only — not enforced by the tool.

## Settings.json hook block

Hook configuration lives in `~/.gemini/settings.json`. The exact schema is **UNVERIFIED** locally — see `references/settings-schema.md` for what we know and what is research-grade.

## Anti-patterns

| Don't | Why |
|---|---|
| Treat `gemini hooks migrate` as a continuous sync | One-shot. Re-run after Claude-side changes. |
| Skip the throwaway-dir test on first run | Migration semantics are unverified — protect your real settings.json |
| Share one hooks file between Claude and Gemini | Schemas differ. Edit Claude source, run migrate, commit both. See `cross-tool-portability/hooks-portability.md`. |
| Forget the call-depth guard | Hooks that invoke other CLIs can recurse infinitely |
