# Architecture Reference — git-cli-bridge

Expanded form of Sections 1 and 3 of the design doc. This file is the authoritative reference for bridge shape, naming, and data flow. Other reference files link here for anything structural.

## 1. Name, location, and relationships

- **Skill name**: `git-cli-bridge`
- **Install path**: `~/.claude/skills/git-cli-bridge/`
- **Codex symlink**: `~/.codex/skills/git-cli-bridge` -> `~/.claude/skills/git-cli-bridge/`
- **Bridge repo name**: `ai-bridge-<user>` (one per user, private by default)
- **Patched sibling skills**: `codex-orchestration/SKILL.md`, `forge/SKILL.md`
- **Unchanged siblings**: `bob`, `alf`, `pa` (they inherit bridge awareness via `codex-orchestration`)

## 2. Conceptual architecture

```
+--------------------------+                   +----------------------------+
| GCP Workstation          |                   | GitHub (ai-bridge-<user>)  |
| --------------           |                   | ---------------------      |
| - Claude Code / Codex    |  git push         | session/20260409-1432-..   |
| - bridge client scripts  |  (session branch) |   requests/req-xxx/        |
| - AI_BRIDGE_MODE=1       |------------------>|     request.md             |
|                          |                   |     context/               |
|                          |<------------------|     status.json  <- wf     |
|                          |  git fetch (poll) |     response.md  <- wf     |
+--------------------------+                   +----------+-----------------+
                                                          | push trigger
                                                          v
                                           +------------------------------+
                                           | GitHub Actions runner         |
                                           | ---------------------         |
                                           | 1. Checkout session branch    |
                                           | 2. auth@v2 (WIF -> GCP)       |
                                           | 3. get-secretmanager-secrets  |
                                           | 4. run-gemini-cli OR          |
                                           |    npm i @github/copilot      |
                                           | 5. Run with --allow-tool      |
                                           |    scoping + --policy file    |
                                           | 6. Sanitize + commit response |
                                           | 7. git push back              |
                                           +-------------------------------+
```

## 3. The eight architectural pillars

1. **Dedicated bridge repo** `ai-bridge-<user>`. Private by default, enforced at `bridge init` via `gh api ... --jq .private`. Separate from work repos, reusable across all projects you touch from the same workstation. The blast radius of a compromise is contained to this one repo.

2. **Per-session orphan branch**. Each Claude/forge/manual session gets its own branch `session/<YYYYMMDD>-<HHMM>-<hex16>`. Orphan-based (no shared history with `main`) — clean diff surface, perfect physical isolation between concurrent sessions, trivial cleanup by deleting the branch. No advisory locks, no rebase retries, no shared state.

3. **Per-request subdirectory**. Under a session branch, each request lives at `requests/req-<ts>-<hex8>/` and contains `request.md`, optional `context/`, `status.json`, `response.md` OR `error.md`, and `logs/`. Append-only from the client, monotonic-state from the workflow, lock-free.

4. **Workflow YAML pinned per session**. `bridge init` copies the current workflow YAML from `main` into the session branch's `.github/` tree. Mid-session updates to `main`'s workflows do NOT break in-flight sessions — the runner uses whatever version was pinned when the session started.

5. **Triple self-trigger prevention**. Three independent layers running simultaneously: (a) commit message marker `[bridge-response]` which GitHub Actions treats as `[skip ci]` equivalent for bridge-originated commits; (b) author identity check `if: github.actor == github.repository_owner` — bridge-bot is never the owner; (c) path filter `paths: ['requests/**/request.md']` — response commits only touch `response.md`, `error.md`, `status.json`, and `logs/`, never `request.md`. Any one of the three is enough to break the loop; having all three is defense in depth.

6. **GCP Secret Manager + Workload Identity Federation** for all secrets. Zero long-lived credentials in GitHub. The WIF pool's attribute condition pins `assertion.repository` to this specific `ai-bridge-<user>` repo only. Token TTL is 1 hour (GCP default for WIF-issued access tokens); workflows are capped at 10 minutes, so token expiry mid-run is rare but handled (see `operations.md` Incident 5).

7. **Prompt injection defense-in-depth**. `<user_data>...</user_data>` delimiter wrapping in the assembled prompt; narrow tool whitelisting (Gemini `--approval-mode plan`, Copilot `--allow-tool='shell(git:status)'` only); no tool execution in v1 for the three job kinds shipped; regex scrubber over `response.md` before commit; canary env var check to detect env-var exfiltration; client ANSI-strip on display.

8. **Monitoring-only cost controls**. No hard cost cap per user ruling B4. Per-run soft caps: `timeout-minutes: 10` on the workflow, per-step `--max-runtime 300` on the CLI, retry count 1. Client-side: max 10 `bridge request` calls in 60 seconds per session. Reporting: `bridge-budget.yml` cron runs day 1 / day 15 / day 28 each month and posts a GitHub issue with current Actions minutes, flagging as `[ALERT]` when above `vars.BRIDGE_BUDGET_ALERT_MIN` (default 4000).

## 4. Session lifecycle

```
[ workstation idle ]
         |
         |  user or forge Step 4b invokes `bridge init`
         v
[ .bridge/session-id generated ]
         |
         |  git clone / fetch ai-bridge-<user>
         |  git checkout --orphan session/<id>
         |  copy .github/ from main
         |  write .bridge/{session-id,created-at,workflow-version,client-version,caller.json}
         |  git commit + push
         v
[ session ready, branch exists on GitHub ]
         |
         |  `bridge request --tool T --kind K "..."` (1..N times)
         v
[ request.md + status.json + context/ committed, pushed ]
         |
         |  GitHub Actions triggers on push (path filter + author + marker)
         v
[ workflow runs on ubuntu-24.04 runner ]
         |  checkout, auth@v2 WIF -> GCP, get-secretmanager-secrets,
         |  integrity-verify npm, install with --ignore-scripts,
         |  assemble prompt (M1), canary setup (M6),
         |  run CLI with --allow-tool / --policy scoping (M2),
         |  scrub-secrets.sh (M5), canary-check.sh (M6),
         |  write response.md OR error.md, commit with [bridge-response] marker, push
         v
[ client poll loop: `bridge wait` ]
         |  git fetch every 5s, read status.json
         v
[ terminal state: succeeded | error | timeout | canary_detected ]
         |
         |  `bridge result <req-id>`
         v
[ ANSI strip + UTF-8 validate + hash cache + display ]
         |
         |  repeat request loop OR `bridge close`
         v
[ archive tag archive/session/<id>-<date>, delete branch local + remote ]
```

## 5. Data flow — a single `bridge request --wait`

1. Client generates `request_id = req-<YYYYMMDD>-<HHMMSS>-<hex8>`.
2. Client validates context paths (size caps), writes `request.md` + `context/*`, pre-seeds `status.json` at state `queued`.
3. Client commits and pushes. Commit message: `bridge: request <request-id>`.
4. GitHub Actions sees push, evaluates triggers:
   - path filter passes (`requests/**/request.md` present in diff),
   - author gate passes (`github.actor == github.repository_owner`),
   - commit marker NOT present (no `[bridge-response]`).
5. Both `bridge-gemini.yml` and `bridge-copilot.yml` are eligible; `process-request.sh` parses `tool:` in the request frontmatter and routes. (In practice one workflow handles both via a matrix, or the two workflows gate on `tool == 'gemini'` vs `tool == 'copilot'` in a step-level `if:`. See `workflows.md` for the chosen shape.)
6. Workflow transitions `status.json` through `queued -> checking_out -> authenticating -> installing_cli -> verifying_integrity -> assembling_prompt -> running_tool -> scrubbing_output -> canary_check -> committing`. Heartbeat updated every 15s during `running_tool`.
7. CLI stdout is captured to a temp file, passed through `scrub-secrets.sh` + `canary-check.sh`, and written to `response.md` with a full frontmatter block.
8. Workflow commits `response.md` + `status.json` + `logs/` with `bridge: response for <req-id> [bridge-response]`, pushes.
9. Client `bridge wait` sees `state == succeeded`, exits 0.
10. Client `bridge result <req-id>` reads `response.md`, extracts body, ANSI-strips, validates UTF-8, caches SHA256, prints to stdout.

## 6. Pinned identifiers and versions (v1)

| Thing | v1 value |
|---|---|
| Session ID format | `YYYYMMDD-HHMM-<hex16>` (128 bits entropy) |
| Session branch format | `session/<session-id>` |
| Request ID format | `req-<YYYYMMDD>-<HHMMSS>-<hex8>` (32 bits, scoped to session) |
| Archive tag format | `archive/session/<session-id>-<YYYYMMDD>` |
| Bridge-bot identity | `bridge-bot <bridge-bot@users.noreply.github.com>` |
| Response commit marker | `[bridge-response]` |
| Runner image | `ubuntu-24.04` (never `ubuntu-latest`) |
| `@google/gemini-cli` | `0.36.0` |
| `@github/copilot` | `1.0.21` |
| `google-github-actions/auth` | `v2` pinned by commit SHA (see `workflows/bridge-integrity.lock`) |
| `google-github-actions/run-gemini-cli` | pinned by commit SHA |
| `google-github-actions/get-secretmanager-secrets` | `v2.2.2` pinned by commit SHA |
| Schema version | `1` |
| Workflow version | `1` |
| Client version | `bridge-client/1.0.0` |

## 7. Integration surface

- **New skill**: `~/.claude/skills/git-cli-bridge/` (this tree)
- **Patched skills**: `codex-orchestration/SKILL.md` (5 patches), `forge/SKILL.md` (6 patches)
- **Untouched**: `bob.md`, `alf.md`, `pa.md`, all other skills
- **Client `$PATH`**: symlink `bridge` from `~/.claude/skills/git-cli-bridge/scripts/bridge` to `~/.local/bin/bridge`
- **Session-cache directory**: `$XDG_RUNTIME_DIR/bridge-mode-<session-tag>` (falls back to `/tmp/bridge-mode-<session-tag>` when `XDG_RUNTIME_DIR` is unset)

## 8. Non-goals for v1 (explicit)

- Multi-user / team bridge — revisit in v2.8 if demand materializes
- Streaming responses — unlikely to ship, conflicts with git transport
- Cloud Run execution venue — deferred to v2.1, revisit only if Actions latency (~90s cold) proves unacceptable
- `kind: agent` agentic delegation — reserved in schema for v2.3
- Fallback when GitHub itself is unreachable — out of scope; user degrades to local CLIs or waits
- Bob integration with direct Gemini/Copilot calls — bob uses `codex-orchestration` which is bridge-aware post-patch

## 9. Where to go next

- Protocol schemas: `protocol.md`
- Workflow YAML and helper scripts: `workflows.md`
- Client-side scripts: `client-scripts.md`
- Security details: `security-model.md`
- First-boot setup: `first-boot.md`
- Debugging and incident runbooks: `operations.md`
- Integration with `codex-orchestration` and `forge`: `integration.md`
- Auth, WIF, Secret Manager, PAT rotation: `auth-and-secrets.md`
- Deferred features: `v2-bucket.md`
