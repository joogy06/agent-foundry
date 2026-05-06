# Headless Gemini CLI

Verified from local `gemini --help` output for Gemini CLI 0.36.0 on 2026-04-08; host-specific directive verified 2026-05-04 (CLI 0.40.1).

## Host directive (read this first)

**On this host, every headless gemini call MUST use:**

```bash
GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY= gemini -m gemini-3.1-pro-preview -p "<prompt>"
```

- The empty `GOOGLE_CLOUD_PROJECT=` and `GEMINI_API_KEY=` overrides force OAuth subscription routing. Without them, the shell-level `GOOGLE_CLOUD_PROJECT=thecpuwebwoov01` (set for vertex-banana / GA tooling) inherits in and the call returns 403 from `cloudcode-pa.googleapis.com`.
- `-m gemini-3.1-pro-preview` requests the top-tier model on this OAuth subscription. The flag is advisory — settings.json + server-side routing dominate — but pin it anyway to express intent and ensure consistent capability.
- Same prompt produces different verdicts on different served tiers. Always capture which model actually answered (see "Capturing served_by" below).

## The default

```
gemini -p "<prompt>"
```

`-p, --prompt` puts Gemini in non-interactive mode. The output goes to stdout, the process exits when the model is done. Stdin is appended to the prompt if both are provided.

## Capturing served_by

Model self-ID is unreliable on this CLI (verified 2026-05-04: same prompt asking the model what model it is returned `gemini-cli`, `gemini-2.5-pro`, and the actual served model in different runs). To reliably capture which model served a request:

```bash
GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY= gemini -m gemini-3.1-pro-preview -p "$(cat <<'EOF'
<your actual prompt>

---
At the very end of your response, append a single line:
served_by=<the exact model id you are running on, e.g. gemini-3.1-pro-preview>
EOF
)"
```

Then parse `served_by=` out of the tail. This is the only reliable mechanism — the User-Agent of the API call may also lie (Gemini CLI 0.40.1 advertised `gemini-3.1-pro-preview` while the API gateway returned 429 errors referring to `gemini-3-flash-preview`).

For deliberation / ballot work where verdict quality matters, log served_by alongside the verdict.

## Output formats

| Flag | Choices | Notes |
|---|---|---|
| `-o, --output-format` | `text` (default), `json`, `stream-json` | `json` returns a single result; `stream-json` emits incremental events |
| `--raw-output` | boolean | Disable sanitization of model output (allows ANSI escapes). **Security risk** if output is untrusted. |
| `--accept-raw-output-risk` | boolean | Suppress the security warning when using `--raw-output` |

```bash
# Force OAuth subscription path when the shell has GOOGLE_CLOUD_PROJECT / GEMINI_API_KEY set for other Google tooling
export GOOGLE_CLOUD_PROJECT=
export GEMINI_API_KEY=

gemini -p --output-format json "list TODOs"            # one-shot JSON
gemini -p --output-format stream-json "long task"     # streaming
```

## Approval modes

```
--approval-mode { default | auto_edit | yolo | plan }
```

Verified choices:

| Mode | Behaviour |
|---|---|
| `default` | Prompt for approval on each tool use |
| `auto_edit` | Auto-approve edit tools, prompt for everything else |
| `yolo` | Auto-approve all tools (also via `-y, --yolo`) |
| `plan` | Read-only — model can read but not write or run tools |

`-y` is shorthand for `--approval-mode yolo`. Use `plan` for CI dry-runs.

## Sandbox mode

```
-s, --sandbox
```

Runs Gemini's tool calls inside a sandbox (bubblewrap on Linux, seatbelt on macOS). Combine with `-y` for fully unattended runs that cannot escape the sandbox.

```bash
GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY= gemini -p -y -s "refactor function X across the repo"
```

## Hybrid mode

```
-i, --prompt-interactive "<initial prompt>"
```

Executes the initial prompt, then drops you into an interactive session. Useful for "investigate, then I'll take over".

## Sessions

| Flag | Purpose |
|---|---|
| `-r, --resume <id-or-latest>` | Resume a previous session by index or `latest` |
| `--list-sessions` | List available sessions for the current project and exit |
| `--delete-session <index>` | Delete a session by its index |

## Other flags

| Flag | Purpose |
|---|---|
| `-w, --worktree [name]` | Start Gemini in a new git worktree (auto-named if no value) |
| `-m, --model <name>` | Override the model |
| `-d, --debug` | Open debug console with F12 |
| `-e, --extensions <list>` | Extensions to use (default: all installed) |
| `-l, --list-extensions` | List installed extensions and exit |
| `--include-directories <dirs>` | Additional workspace directories (comma-sep or repeated flag) |
| `--screen-reader` | Accessibility mode |
| `--allowed-mcp-server-names <list>` | Restrict which MCP servers Gemini can talk to |
| `--policy <files>` | Additional policy files (comma-sep or repeated). See `policy-engine.md` |
| `--admin-policy <files>` | Admin-scope policy files. See `policy-engine.md` |
| `--acp` | Start Gemini as an ACP server (see `a2a-and-acp.md`) |
| `--experimental-acp` | Deprecated alias for `--acp` |

## Deprecated flags

| Flag | Replacement |
|---|---|
| `--allowed-tools` | `--policy <file>` (Policy Engine). The deprecated flag emits a warning. See `policy-engine.md`. |
| `--experimental-acp` | `--acp` |

## Exit codes

Verified: `0` on success. Non-zero on error. Specific exit-code semantics are not documented in `--help`; flagged for first-boot verification.

## Putting it together — CI patterns

```bash
# CI: read-only review, JSON for parsing, plan mode
GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY= gemini -m gemini-3.1-pro-preview -p \
  --approval-mode plan \
  --output-format json \
  --include-directories ./src \
  --policy ./ci-readonly.policy \
  "Review this PR for issues" \
  > /tmp/review.json

# CI: enforce one specific MCP server only
GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY= gemini -m gemini-3.1-pro-preview -p \
  --approval-mode auto_edit \
  --allowed-mcp-server-names github,linter \
  -y -s \
  "apply linter fixes and open PR" \
  < diff.patch
```

## Equivalent to Claude Code

| Claude Code | Gemini CLI |
|---|---|
| `claude -p "<prompt>"` | `gemini -p "<prompt>"` |
| `--output-format text/json/stream-json` | `--output-format text/json/stream-json` (identical) |
| `--permission-mode plan` | `--approval-mode plan` |
| `--permission-mode bypassPermissions` | `-y` / `--approval-mode yolo` |
| `--allowedTools` | `--policy <file>` (Policy Engine) |
| `--add-dir` | `--include-directories` |
| `-w/--worktree` | `-w/--worktree` |
| `--resume` | `-r/--resume` |
| `--bare` | (no equivalent — Gemini does not have a single canonical CI-safe flag) |
| `--max-budget-usd` | (no equivalent) |
| `--json-schema` | (no equivalent — use `--output-format json` and validate downstream) |
