# Headless Invocation

Side-by-side comparison of `-p` mode in Claude Code, Antigravity CLI (`agy`), and GitHub Copilot CLI. Use to translate scripts from one tool to another. `agy` is this host's second-opinion / research delegate — it replaces the retired Gemini CLI for orchestration. See the `antigravity-cli` skill for the full flag reference (verified against `agy --help`, v1.0.4).

## The basic invocation

| Tool | Command |
|---|---|
| Claude Code | `claude -p "<prompt>"` |
| Antigravity CLI (`agy`) | `agy -p "<prompt>"` |
| Copilot CLI | `copilot -p "<prompt>" --allow-all-tools` |

Note: Copilot REQUIRES `--allow-all-tools` for `-p` mode (otherwise it blocks on permission prompts). `agy -p` takes no model flag and no API-key env prefix — it authenticates via the Antigravity account.

## Output format

| Tool | Plain | JSON | Streaming |
|---|---|---|---|
| Claude Code | `--output-format text` (default) | `--output-format json` | `--output-format stream-json --include-partial-messages` |
| Antigravity CLI (`agy`) | plain text on stdout (default; only verified mode) | TODO(agy): verify equivalent — no verified JSON output mode | TODO(agy): verify equivalent — no verified streaming mode |
| Copilot CLI | `--output-format text` (default) | `--output-format json` (JSONL — one object per line) | (no separate streaming flag — `--stream on/off` controls it) |

JSON output schemas differ. Don't try to parse Claude's JSON with another tool's parser. `agy -p` returns **plain text** — parse text, not JSON fields (the retired `mcp__gemini-cli__*` tools returned structured fields; agy does not).

## Permission / approval mode

| Tool | Read-only | Auto-approve | YOLO |
|---|---|---|---|
| Claude Code | `--permission-mode plan` | `--permission-mode acceptEdits` | `--permission-mode bypassPermissions` |
| Antigravity CLI (`agy`) | `--sandbox` (terminal restrictions; TODO(agy): verify plan-only mode) | TODO(agy): verify equivalent — no verified per-edit auto-approve flag | `--dangerously-skip-permissions` (auto-approve all tool calls; fully-headless only) |
| Copilot CLI | (no built-in plan mode — use `--available-tools` to limit) | `--allow-all-tools` | `--yolo` / `--allow-all` |

## Allowing/denying tools

| Tool | Allow specific | Deny specific |
|---|---|---|
| Claude Code | `--allowedTools "Bash(git:*) Read"` | `--disallowedTools "..."` |
| Antigravity CLI (`agy`) | TODO(agy): verify equivalent — no verified per-tool allow flag (the gemini Policy Engine has no confirmed agy analogue) | TODO(agy): verify equivalent |
| Copilot CLI | `--allow-tool='shell(git:*)' --allow-tool='read'` | `--deny-tool='shell(git push)'` |

Patterns differ. Translate carefully.

## Adding directories

| Tool | Flag |
|---|---|
| Claude Code | `--add-dir <dir>` (repeatable) |
| Antigravity CLI (`agy`) | `--add-dir <dir>` (repeatable) |
| Copilot CLI | `--add-dir <dir>` (repeatable) |

## Sessions

| Tool | Resume latest | Resume by ID |
|---|---|---|
| Claude Code | `--continue` | `--resume <id>` |
| Antigravity CLI (`agy`) | `-c` / `--continue` | `--conversation <id>` |
| Copilot CLI | `--continue` | `--resume=<id>` |

## Model selection

| Tool | Flag |
|---|---|
| Claude Code | `--model <name>` (e.g. `sonnet`, `opus`) |
| Antigravity CLI (`agy`) | (no model flag — `agy` uses its Antigravity-account-configured model; `-m` is not defined) |
| Copilot CLI | `--model <name>` |

Model names differ across tools. There's no shared naming. `agy` exposes one configured model with no per-call selector.

## Worktree mode

| Tool | Flag |
|---|---|
| Claude Code | `-w, --worktree [name]` |
| Antigravity CLI (`agy`) | TODO(agy): verify equivalent — no verified worktree flag |
| Copilot CLI | (no built-in worktree — use git separately) |

## CI-safe minimal mode

| Tool | Flag |
|---|---|
| Claude Code | `--bare` (CANONICAL — skips hooks, LSP, plugin sync, auto-memory, keychain) |
| Antigravity CLI (`agy`) | (no equivalent — closest is `--dangerously-skip-permissions --sandbox`; raise `--print-timeout` for long runs) |
| Copilot CLI | `--allow-all-tools --no-custom-instructions --no-auto-update` (closest combo) |

Only Claude has a single canonical flag. The others require flag combinations.

## Cost / budget cap

| Tool | Flag |
|---|---|
| Claude Code | `--max-budget-usd <n>` (only with `-p`) |
| Antigravity CLI (`agy`) | (no equivalent) |
| Copilot CLI | `--max-autopilot-continues <n>` (caps continuations, not $) |

Only Claude has a $ cap. Use external tooling for agy/Copilot budget enforcement.

## Structured output / schemas

| Tool | Flag |
|---|---|
| Claude Code | `--json-schema '<JSON Schema>'` (built-in validation) |
| Antigravity CLI (`agy`) | TODO(agy): verify equivalent — no verified JSON / schema output mode; `agy -p` returns plain text only |
| Copilot CLI | (no equivalent) |

Only Claude has built-in schema validation.

## Pinning a custom agent

| Tool | Flag |
|---|---|
| Claude Code | `--agent <name>` or `--agents '<JSON inline>'` |
| Antigravity CLI (`agy`) | TODO(agy): verify equivalent — no verified `--agent` flag (plugins via `agy plugin`) |
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

### Antigravity CLI (`agy`)

```bash
agy -p "fix the bug" \
  --add-dir . \
  --dangerously-skip-permissions \
  --sandbox
```

`agy` takes no model flag and no API-key env prefix (it authenticates via the Antigravity account). Output is plain text on stdout — there is no verified JSON output mode (TODO(agy): verify equivalent). Raise `--print-timeout <dur>` for long runs.

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
- `agy`'s `--dangerously-skip-permissions` auto-approves all tool calls — same intent as bypassPermissions; use only in fully-headless contexts
- Copilot's `--allow-all-tools` allows tools but not all paths/URLs (use `--yolo` for that)

## Anti-patterns

| Don't | Why |
|---|---|
| Assume all three have `--bare` | Only Claude does. Use the closest equivalent for the other two. |
| Translate JSON output 1:1 | Schemas differ. Re-implement parsing per tool. `agy` has no verified JSON mode — parse its plain-text stdout. |
| Pass `-m <model>` to `agy` | `agy` has no model flag — `-m` is "not defined". Drop it. |
| Pin the same model name across tools | Model namespaces are independent. `agy` has no per-call model selector. |
| Forget `--allow-all-tools` for Copilot `-p` mode | Copilot blocks on permission prompts. |
| Use `--yolo` / `--dangerously-skip-permissions` in production scripts | Disables safety. Use the minimum approval level the task needs. |
| Add a `GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY=` prefix to `agy` | That was a gemini-OAuth hack; `agy` authenticates via its own account. Drop it. |
