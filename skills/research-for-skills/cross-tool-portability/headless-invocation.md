# Headless Invocation

Side-by-side comparison of `-p` mode in Claude Code, Gemini CLI, and GitHub Copilot CLI. Use to translate scripts from one tool to another.

## The basic invocation

| Tool | Command |
|---|---|
| Claude Code | `claude -p "<prompt>"` |
| Gemini CLI | `gemini -p "<prompt>"` |
| Copilot CLI | `copilot -p "<prompt>" --allow-all-tools` |

Note: Copilot REQUIRES `--allow-all-tools` for `-p` mode (otherwise it blocks on permission prompts).

## Output format

| Tool | Plain | JSON | Streaming |
|---|---|---|---|
| Claude Code | `--output-format text` (default) | `--output-format json` | `--output-format stream-json --include-partial-messages` |
| Gemini CLI | `--output-format text` | `--output-format json` | `--output-format stream-json` |
| Copilot CLI | `--output-format text` (default) | `--output-format json` (JSONL — one object per line) | (no separate streaming flag — `--stream on/off` controls it) |

JSON output schemas differ. Don't try to parse Claude's JSON with Gemini's parser.

## Permission / approval mode

| Tool | Read-only | Auto-approve | YOLO |
|---|---|---|---|
| Claude Code | `--permission-mode plan` | `--permission-mode acceptEdits` | `--permission-mode bypassPermissions` |
| Gemini CLI | `--approval-mode plan` | `--approval-mode auto_edit` | `-y` / `--approval-mode yolo` |
| Copilot CLI | (no built-in plan mode — use `--available-tools` to limit) | `--allow-all-tools` | `--yolo` / `--allow-all` |

## Allowing/denying tools

| Tool | Allow specific | Deny specific |
|---|---|---|
| Claude Code | `--allowedTools "Bash(git:*) Read"` | `--disallowedTools "..."` |
| Gemini CLI | `--policy ./allow.policy.yaml` (Policy Engine) | (in policy file) |
| Copilot CLI | `--allow-tool='shell(git:*)' --allow-tool='read'` | `--deny-tool='shell(git push)'` |

Patterns differ. Translate carefully.

## Adding directories

| Tool | Flag |
|---|---|
| Claude Code | `--add-dir <dir>` (repeatable) |
| Gemini CLI | `--include-directories <dir>` (comma-sep or repeated) |
| Copilot CLI | `--add-dir <dir>` (repeatable) |

## Sessions

| Tool | Resume latest | Resume by ID |
|---|---|---|
| Claude Code | `--continue` | `--resume <id>` |
| Gemini CLI | `--resume latest` | `--resume <index>` |
| Copilot CLI | `--continue` | `--resume=<id>` |

## Model selection

| Tool | Flag |
|---|---|
| Claude Code | `--model <name>` (e.g. `sonnet`, `opus`) |
| Gemini CLI | `-m, --model <name>` |
| Copilot CLI | `--model <name>` |

Model names differ across tools. There's no shared naming.

## Worktree mode

| Tool | Flag |
|---|---|
| Claude Code | `-w, --worktree [name]` |
| Gemini CLI | `-w, --worktree [name]` |
| Copilot CLI | (no built-in worktree — use git separately) |

## CI-safe minimal mode

| Tool | Flag |
|---|---|
| Claude Code | `--bare` (CANONICAL — skips hooks, LSP, plugin sync, auto-memory, keychain) |
| Gemini CLI | (no equivalent — closest is `-y --approval-mode yolo` with explicit settings) |
| Copilot CLI | `--allow-all-tools --no-custom-instructions --no-auto-update` (closest combo) |

Only Claude has a single canonical flag. The other two require flag combinations.

## Cost / budget cap

| Tool | Flag |
|---|---|
| Claude Code | `--max-budget-usd <n>` (only with `-p`) |
| Gemini CLI | (no equivalent) |
| Copilot CLI | `--max-autopilot-continues <n>` (caps continuations, not $) |

Only Claude has a $ cap. Use external tooling for Gemini/Copilot budget enforcement.

## Structured output / schemas

| Tool | Flag |
|---|---|
| Claude Code | `--json-schema '<JSON Schema>'` (built-in validation) |
| Gemini CLI | (no equivalent — use `--output-format json` and validate downstream) |
| Copilot CLI | (no equivalent) |

Only Claude has built-in schema validation.

## Pinning a custom agent

| Tool | Flag |
|---|---|
| Claude Code | `--agent <name>` or `--agents '<JSON inline>'` |
| Gemini CLI | (no `--agent` flag — use extensions) |
| Copilot CLI | `--agent <name>` (format `[UNVERIFIED]`) |

## Putting it together — equivalent invocations

Run a one-shot prompt with JSON output, all tools allowed, in CI-safe mode:

### Claude Code

```bash
ANTHROPIC_API_KEY=$KEY \
  claude --bare -p "fix the bug" \
  --add-dir . \
  --output-format json \
  --permission-mode bypassPermissions
```

### Gemini CLI

```bash
GEMINI_API_KEY=$KEY \
  gemini -p "fix the bug" \
  --include-directories . \
  --output-format json \
  -y -s
```

### Copilot CLI

```bash
COPILOT_GITHUB_TOKEN=$TOKEN \
  copilot -p "fix the bug" \
  --add-dir . \
  --output-format json \
  --allow-all-tools \
  --no-custom-instructions \
  --no-auto-update -s
```

These are roughly equivalent. The exact behaviour differs in subtle ways:

- Claude's `--bare` skips more than just hooks (also LSP, auto-memory, plugin sync)
- Gemini's `-y` is yolo mode — same as bypassPermissions
- Copilot's `--allow-all-tools` allows tools but not all paths/URLs (use `--yolo` for that)

## Anti-patterns

| Don't | Why |
|---|---|
| Assume all three have `--bare` | Only Claude does. Use the closest equivalent for the other two. |
| Translate JSON output 1:1 | Schemas differ. Re-implement parsing per tool. |
| Use the same `--allowedTools` syntax in Gemini | Gemini deprecated `--allowed-tools`. Use Policy Engine. |
| Pin the same model name across tools | Model namespaces are independent. |
| Forget `--allow-all-tools` for Copilot `-p` mode | Copilot blocks on permission prompts. |
| Use `--yolo` in production scripts | Disables ALL safety. Use `--allow-all-tools` for Copilot, similar restraint elsewhere. |
| Pipe Claude's JSON output to a Gemini parser | Schemas differ. Validate downstream of each tool. |
