# Client Scripts Reference — git-cli-bridge

All scripts under `~/.claude/skills/git-cli-bridge/scripts/`, with `bridge` symlinked to `~/.local/bin/bridge` so `bridge <subcommand>` works from anywhere. Every script is plain bash, `set -euo pipefail`, no external deps beyond `git`, `yq`, `jq`, `gh`, `openssl`, `sed`, `tr`, `iconv`.

## 1. `bridge` (dispatcher)

Thin front-end that routes `bridge <subcommand>` to the matching `bridge-<subcommand>` script. Usage:

```
bridge init                              # create session
bridge request [flags] "prompt"          # submit a request (prints req-id, optionally waits)
bridge wait <req-id>                     # poll to terminal state
bridge result <req-id> [--verbose]       # extract and display response body
bridge status [--all] [--json]           # show session/request state
bridge logs <req-id>                     # tail workflow logs via gh run view
bridge close                             # archive + delete session branch
bridge cleanup [--dry-run] [--older N]   # prune stale sessions
bridge --help                            # this help
bridge --version                         # bridge-client/1.0.0
```

Exit codes (shared across all `bridge-*` scripts): see `protocol.md` §10.

## 2. `bridge-env.sh` (shared environment sourceable)

Not a command. Other scripts `source` it. Exports:

- `BRIDGE_SKILL_ROOT` — absolute path to the skill directory.
- `BRIDGE_CLIENT_VERSION` — `bridge-client/1.0.0`.
- `BRIDGE_REPO_URL` — read from `git config --global bridge.repo`; errors if unset (except during `bridge init` which accepts `--repo`).
- `BRIDGE_LOCAL_WORKSPACE` — `$XDG_DATA_HOME/bridge/workspace` (defaults to `$HOME/.local/share/bridge/workspace`).
- `BRIDGE_CACHE_DIR` — `$XDG_CACHE_HOME/bridge`.
- `BRIDGE_RUNTIME_DIR` — `$XDG_RUNTIME_DIR` if set, else `/tmp`.
- Color functions `bridge_info`, `bridge_warn`, `bridge_err` (all write to stderr).
- Helper `bridge_require` — verifies a command exists in `$PATH`, exits 1 with an actionable error if not.
- Helper `bridge_session_tag` — computes the forge/claude session tag for caching (`$FORGE_SESSION_ID` | `$CLAUDE_SESSION_ID` | PID).

## 3. `bridge-init`

Creates a new session on the bridge repo.

```
bridge init [--repo <url>] [--caller <name>] [--caller-version <ver>]
```

Behavior:

1. Source `bridge-env.sh`. Resolve `BRIDGE_REPO_URL`.
2. `bridge_require git openssl gh yq jq`.
3. **SEC-7 check**: `gh api repos/<owner>/<repo> --jq .private` must return `true`; refuse (exit 2) if `false`.
4. Clone or fetch the repo into `$BRIDGE_LOCAL_WORKSPACE/ai-bridge-<user>`.
5. Generate `SESSION_ID = $(date -u +%Y%m%d-%H%M)-$(openssl rand -hex 16)`.
6. Collision check (M16): `git ls-remote origin "refs/heads/session/$SESSION_ID"` — retry up to 3 times if non-empty.
7. `git checkout --orphan session/$SESSION_ID`.
8. `git rm -rf .` (wipe everything from the parent checkout).
9. Copy workflow templates from `origin/main:.github` into `./.github/` (pinned per session — M22).
10. Create `.bridge/session-id`, `.bridge/created-at`, `.bridge/workflow-version` (from `origin/main:.bridge/setup-version`), `.bridge/client-version`, `.bridge/caller.json`.
11. Write a short `README-SESSION.md` explaining the branch is ephemeral and will be pruned after 7 days of inactivity.
12. `git add . && git commit -m "bridge: init session $SESSION_ID [skip ci]" && git push -u origin "session/$SESSION_ID"`.
13. Cache the session in `$BRIDGE_CACHE_DIR/current-session` (used by subsequent `bridge request` without explicit `--session`).
14. Print the session ID + branch URL + next-step suggestion.

Caller field population: `--caller forge --caller-version 2.1.0` is the expected forge usage. Manual invocation defaults to `--caller manual`.

## 4. `bridge-request`

Submits a request. Optionally waits synchronously.

```
bridge request \
  --tool gemini|copilot \
  --kind review|research|prompt \
  [--model auto|gemini-2.5-pro|...|copilot-gpt-5] \
  [--context PATH]... \
  [--max-runtime SEC] \
  [--max-tokens-out N] \
  [--wait] [--timeout SEC] \
  [--caller NAME] [--caller-task-id ID] \
  "Prompt body (positional)"
```

Behavior:

1. Rate-limit check: refuse if this session has already submitted 10 requests in the last 60 seconds (exit 7).
2. Context size caps: each file <= 1 MB, total context <= 10 MB. Exit 3 on violation.
3. `REQUEST_ID = req-$(date -u +%Y%m%d-%H%M%S)-$(openssl rand -hex 4)`.
4. `mkdir requests/$REQUEST_ID{,/context,/logs}`.
5. Copy each `--context` path into `requests/$REQUEST_ID/context/` preserving base name.
6. Write `request.md` with full frontmatter (see `protocol.md` §3) followed by the positional prompt body.
7. Write initial `status.json` at state `queued`, `state_history: [{queued, <now>}]`.
8. `git add requests/$REQUEST_ID && git commit -m "bridge: request $REQUEST_ID" && git push`.
9. Print the request ID + workflow URL (once the run exists).
10. If `--wait`: exec `bridge-wait $REQUEST_ID --timeout ${BRIDGE_TIMEOUT:-$FLAG_TIMEOUT:-900}`.

Never passes secrets via flags — the `--caller-task-id` and `--prompt` are both on the command line and could be logged; avoid putting PII or secrets in either.

## 5. `bridge-wait`

Polls a request to terminal state.

```
bridge wait <req-id> [--timeout SEC] [--poll SEC]
```

Behavior:

1. Default timeout: 900s (15 min). Default poll interval: 5s.
2. Loop:
   - `git fetch --quiet origin "$(git rev-parse --abbrev-ref HEAD)"`.
   - `git show "origin/HEAD:requests/$req/status.json"` (or local path if fetched).
   - Parse `.state` via `jq`.
   - If terminal (`succeeded`, `failed`, `timeout`, `cancelled`, `canary_detected`, `schema_invalid`, `rate_limited`): break.
   - If `running` and `heartbeat_at` is >90s stale: print warning but keep polling.
   - If wall clock exceeds `--timeout`: exit 5.
   - Sleep `--poll`.
3. Exit codes:
   - `succeeded` -> 0
   - `failed` / `error.md` present -> 4
   - `timeout` -> 5
   - `canary_detected` -> 6
   - `rate_limited` -> 7
   - others -> 1

Never calls `eval` or `source` on any fetched file. Parsing is strict: yq for YAML frontmatter, jq for JSON.

## 6. `bridge-result`

Displays the response body (or remediation + error body, on failure).

```
bridge result <req-id> [--verbose] [--raw]
```

Behavior:

1. Determine the latest fetched state; if not present, `git fetch` first.
2. Prefer `error.md` if both `error.md` and `response.md` exist (mutex rule).
3. Extract body: everything after the first `---` / `---` frontmatter block.
4. Sanitize:
   - ANSI strip: `sed 's/\x1b\[[0-9;]*[a-zA-Z]//g'`.
   - Non-printable strip: `tr -d '\000-\010\013\014\016-\037\177'`.
   - UTF-8 validate: `iconv -f UTF-8 -t UTF-8 -c` (drop invalid sequences).
5. Hash cache (M14): compute SHA256 of the sanitized body, store at `$BRIDGE_CACHE_DIR/response-hashes/<session>-<req-id>.sha256`. On re-read, warn (exit code 9 in `--strict` mode) if differs.
6. Print:
   - On success: the sanitized body.
   - On error: a stderr header with the remediation text pulled from `error.md`, then the body.
7. `--verbose`: also print the full frontmatter (response or error) before the body.
8. `--raw`: skip sanitization (DANGEROUS — intended only for forensic inspection of response integrity; the man page for `bridge result --raw` warns explicitly and refuses if stdout is a tty unless `BRIDGE_I_UNDERSTAND_RAW=1` is set).

Hard rule (grep-verified): this script never calls `eval`, `source`, `sh`, `bash`, or `| sh`/`| bash`.

## 7. `bridge-status`

```
bridge status [--all] [--json]
```

Shows session + request state.

- Default: the current session from `$BRIDGE_CACHE_DIR/current-session`, listing each request with its state, elapsed time, last heartbeat, tool.
- `--all`: every `session/*` branch on the remote, with a count of running / succeeded / failed requests per session.
- `--json`: machine-readable output (arrays of objects), safe for piping to `jq`.

Never fetches `response.md` bodies — only the `status.json` metadata — so stale heartbeats are visible without loading large files.

## 8. `bridge-logs`

```
bridge logs <req-id> [--step STEP] [--job JOB]
```

Wraps `gh run view --log` scoped to the workflow run that processed this request. Reads `workflow_run_id` from the latest `status.json` / `response.md` / `error.md` (whichever exists), then:

```
gh run view <workflow_run_id> --log [--job <job-id>]
```

If per-job scoping fails (older `gh` version), falls back to `gh run view <workflow_run_id>` which prints the whole run log. All output is piped through the client-side sanitizer (ANSI strip + non-printable strip) before display.

## 9. `bridge-close`

```
bridge close [--force] [--no-archive]
```

Behavior:

1. Refuse if any request in the current session is in `running` state (override with `--force`).
2. Push `archive/session/<session-id>-$(date -u +%Y%m%d)` tag (skipped with `--no-archive`).
3. `git push origin --delete session/<session-id>`.
4. `git branch -D session/<session-id>` locally.
5. Remove `$BRIDGE_CACHE_DIR/current-session` entry.
6. Keep `$BRIDGE_CACHE_DIR/response-hashes/<session>-*` for forensic integrity checks (cleaned by `bridge cleanup --hashes`).

## 10. `bridge-cleanup`

```
bridge cleanup [--dry-run] [--older DAYS] [--local-only] [--remote-only] [--hashes]
```

Behavior:

- Default age: 7 days (matches server-side maintenance).
- Discovers stale sessions via `git for-each-ref --format='%(committerdate:unix) %(refname)' refs/remotes/origin/session/*`.
- For each stale ref:
  - Skip if any `status.json` inside shows `state: running` (running-state guard, M17).
  - Archive before delete: push `archive/session/<id>-<date>` tag.
  - Delete local + remote (gated by `--local-only` / `--remote-only`).
- `--hashes`: also cleans `$BRIDGE_CACHE_DIR/response-hashes/` entries older than the threshold.
- `--dry-run`: print what would happen without executing.

Uses `git log -1 --format=%ct <ref>` for the age value, not the workstation clock (M18).

## 11. `bridge-mode-detect.sh`

The sandbox-aware routing helper. Called by `codex-orchestration` and `forge` Step 4b.

```
bridge-mode-detect.sh           # prints "local" or "bridge" to stdout, exit 0
bridge-mode-detect.sh --reset   # clear cache for current session tag
bridge-mode-detect.sh --probe   # single probe without updating cache
```

Decision tree (priority order):

1. `AI_BRIDGE_DISABLE=1` -> always `local`. Ignore cache.
2. `AI_BRIDGE_MODE=1` -> always `bridge`. Ignore cache.
3. Cached decision at `$BRIDGE_RUNTIME_DIR/bridge-mode-<session-tag>` -> reuse (sticky — M21).
4. Otherwise probe: `gemini --version` AND `copilot --version`, each with a 3-second timeout.
   - Both succeed -> `local`, reset counter file.
   - Either fails -> read counter file, increment. If counter >= 3 -> `bridge` (cached for rest of session). Otherwise -> `local` (first two failures still return local for hysteresis).
5. Write decision to cache file.

Important: the **first call in a fresh environment with no cache and both CLIs unreachable** returns `local` and increments the counter to 1. Three calls with failures are needed before `bridge` is returned. This is M21 hysteresis and is verified by IT4/IT5 smoke tests.

Session tag resolution: `$FORGE_SESSION_ID` | `$CLAUDE_SESSION_ID` | `$$` (PID). Keeps concurrent sessions isolated (IT9 verifies cross-session non-contamination).

## 12. `setup-wif.sh`

First-boot helper that wraps `gcloud` to create a Workload Identity Federation pool, provider, and service account bound to this one `ai-bridge-<user>` repo. Not a `bridge` subcommand — run directly: `bash ~/.claude/skills/git-cli-bridge/scripts/setup-wif.sh`. See `auth-and-secrets.md` for the step-by-step. The script is idempotent and safe to re-run.

## 13. `bump-bridge-deps.sh`

Dev helper that bumps npm deps and refreshes the integrity lock.

```
bash ~/.claude/skills/git-cli-bridge/scripts/bump-bridge-deps.sh \
  --gemini 0.37.0 --copilot 1.1.0
```

Steps:

1. For each named package and version, run `npm view @<pkg>@<ver> dist.integrity` to fetch the sha512 hash.
2. Validate the package actually exists at that exact version on the registry (no `@latest` resolution).
3. Rewrite `workflows/bridge-integrity.lock` with the new hashes, preserving any other pinned packages.
4. Write a summary diff.
5. If run inside a git checkout of the skill, propose a commit message `bridge: bump gemini 0.36.0 -> 0.37.0, copilot 1.0.21 -> 1.1.0`.
6. Do NOT edit the workflow YAML file version strings — that is a manual review step so the reviewer sees the bump intent.

## 14. Per-script environment matrix

| Script | Requires `bridge init` done? | Writes to remote? | Reads workflow logs? | Needs network? |
|---|---|---|---|---|
| `bridge-init` | no | yes (push session branch) | no | yes (git + gh) |
| `bridge-request` | yes | yes (push request commit) | no | yes (git) |
| `bridge-wait` | yes | no | no | yes (git fetch) |
| `bridge-result` | yes | no | no | maybe (git fetch if not present) |
| `bridge-status` | yes | no | no | yes (git ls-remote / fetch) |
| `bridge-logs` | yes | no | yes (`gh run view`) | yes (gh api) |
| `bridge-close` | yes | yes (delete branch, push archive tag) | no | yes |
| `bridge-cleanup` | yes (for current session resolution) | yes (delete stale refs, push archive tags) | no | yes |
| `bridge-mode-detect.sh` | no | no | no | partial (probes local CLIs) |
| `setup-wif.sh` | no | no | no | yes (gcloud to GCP) |
| `bump-bridge-deps.sh` | no | no | no | yes (npm registry read) |

## 15. Hard rules recap

- **Never** `eval`, `source`, `sh`, `bash`, or pipe response content to any interpreter. Grep-verified on every PR.
- **Never** retry silently on network failures — always surface the error.
- **Always** ANSI-strip response output before display.
- **Always** validate UTF-8 on response bodies.
