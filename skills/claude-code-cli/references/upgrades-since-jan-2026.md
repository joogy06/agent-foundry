# Upgrades Since the Jan 2026 Snapshot

The forked references in this skill come from `superpowers-developing-for-claude-code` v0.3.1 (released January 2026). This file tracks features and flags that exist in the local Claude Code 2.1.96 (verified 2026-04-08) but are not documented or are documented differently in the Jan 2026 snapshot.

This is a living delta. Run `scripts/verify-claude-install.sh` after any `claude update` to check what has shifted.

## Confirmed deltas (verified locally)

| Feature | 2.1.96 status | Jan 2026 snapshot | Notes |
|---|---|---|---|
| `--bare` flag | Present in `--help` | Mentioned | Canonical headless-CI flag. Skips hooks, LSP, plugin sync, attribution, auto-memory, background prefetches, keychain reads, and CLAUDE.md auto-discovery. Sets `CLAUDE_CODE_SIMPLE=1`. Auth must be `ANTHROPIC_API_KEY` or `apiKeyHelper` via `--settings`. Skills still resolve via `/skill-name`. |
| `--agent <name>` and `--agents '<json>'` | Present | Partial | Both verified in `--help`. `--agents` accepts inline JSON for ad-hoc agent definition; `--agent` pins one for the session. |
| `--json-schema '<schema>'` | Present | Possibly absent | Built-in structured-output validation for `--print` mode. Example: `'{"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}'`. |
| `--max-budget-usd <amount>` | Present | Possibly absent | Per-session $ cap. Only works with `--print`. |
| `--include-hook-events` | Present | Partial | Stream-json extension. Emits all hook lifecycle events alongside model output. |
| `--include-partial-messages` | Present | Partial | Required for true streaming output in `--output-format=stream-json`. |
| `--from-pr [value]` | Present | Possibly absent | Resume a session linked to a GitHub PR by number/URL, or open interactive picker. |
| `--brief` | Present | Partial | Enables the `SendUserMessage` tool for agent-to-user communication. |
| `--effort <level>` | Present | Partial | Effort level (low/medium/high/max). Affects model behaviour. |
| `--fallback-model <model>` | Present | Partial | Auto fallback when default model is overloaded. Only with `--print`. |
| `--file <file_id:path>` | Present | Partial | Inject file resources at startup. Format `file_abc:doc.txt file_def:img.png`. |
| `--fork-session` | Present | Partial | When resuming, create a new session ID instead of reusing the original. Combine with `--resume` or `--continue`. |
| `--ide` and `--no-chrome`/`--chrome` | Present | Partial | IDE auto-connect; Claude in Chrome integration toggle. |
| `--strict-mcp-config` | Present | Partial | Only use MCP servers from `--mcp-config`, ignoring all other configurations. |
| `--debug-file <path>` | Present | Possibly absent | Write debug logs to a specific file path (implicitly enables debug mode). |
| `--no-session-persistence` | Present | Partial | Disable session persistence — sessions not saved, can't be resumed. Only with `--print`. |
| `-w, --worktree [name]` and `--tmux` | Present | Partial | Built-in git worktree creation. `--tmux=classic` for traditional tmux when iTerm2 native panes are unavailable. |
| `permission-mode` choices | 6 modes | Probably 4 or 5 | Verified all 6 in `--help`: `acceptEdits`, `auto`, `bypassPermissions`, `default`, `dontAsk`, `plan`. |
| `auto-mode` subcommand | Present | Possibly absent | `claude auto-mode` inspects auto-mode classifier configuration. |
| `setup-token` subcommand | Present | Partial | `claude setup-token` sets up a long-lived authentication token (requires Claude subscription). |
| `claude plugin marketplace` subcommands | Verified | Partial | `add`, `list`, `remove`, `update` against marketplaces. |
| `claude mcp reset-project-choices` | Present | Possibly absent | Reset per-project MCP server consent choices. |
| `--remote-control-session-name-prefix` | Present | Possibly absent | Prefix for auto-generated Remote Control session names. |
| `--replay-user-messages` | Present | Possibly absent | Re-emit user messages from stdin back on stdout for acknowledgment (only works with `--input-format=stream-json` and `--output-format=stream-json`). |
| `--betas <betas...>` | Present | Possibly absent | Beta headers to include in API requests (API key users only). |

## Refreshed reference files (vs upstream)

The forked files were copied verbatim from `superpowers-developing-for-claude-code/0.3.1`. Where the upstream content disagrees with local `--help`, prefer the local truth and flag the diff in `verify-claude-install.sh`.

Files most likely to drift:

| File | Reason |
|---|---|
| `cli-reference.md` | Surface area of `--help` flags evolves on every release |
| `headless.md` | New flags like `--max-budget-usd`, `--json-schema`, `--bare` may not be covered |
| `mcp.md` | `claude mcp reset-project-choices` is recent |
| `plugins.md` / `plugins-reference.md` | Plugin marketplace surface evolves quickly |
| `sub-agents.md` | `--agent` / `--agents` JSON syntax recent |
| `settings.md` | Setting source overrides (`--setting-sources`) recent |

## Behaviour changes (cannot verify from `--help` alone)

These need first-boot or live testing:

| Change | Status | Test |
|---|---|---|
| Native AGENTS.md auto-load | UNVERIFIED | Move CLAUDE.md aside, leave only `AGENTS.md`, run `claude -p "what are my global instructions?"` |
| Hook re-entrancy guards | UNVERIFIED | Build a hook that calls `claude` recursively and watch what happens |
| Settings hot-reload | UNVERIFIED | Edit `settings.json` mid-session, observe whether changes apply |
| Auto-memory across sessions | UNVERIFIED | Start session, ask question, exit, restart, ask follow-up |

## How to refresh this delta

When `claude update` runs:

1. Capture `claude --help`, `claude mcp --help`, `claude plugin --help`, `claude agents --help` to `/tmp/`
2. Diff against the previous capture (kept in `~/.claude/skills/_meta/last-claude-help-snapshot.txt` if you snapshotted)
3. Add any new flags / subcommands to the table above
4. Note removed flags as deprecations
5. Re-run `verify-claude-install.sh` to confirm `cli-reference.md` matches

## Future maintenance task

A quarterly sync with upstream `superpowers-developing-for-claude-code` is on the project backlog (item #2 in the design doc's "Open Items"). The sync should:

- Diff each forked reference against the new upstream version
- Pull in upstream improvements (new content, corrections)
- Preserve local additions in `custom-ecosystem.md`, `cross-tool-integration.md`, this file, and the customised `SKILL.md`
- Update this file with any newly-confirmed-or-changed behaviour
