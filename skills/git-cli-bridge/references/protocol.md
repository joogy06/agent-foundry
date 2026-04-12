# Protocol Reference — git-cli-bridge

Authoritative schemas for every file that travels between the client and the workflow. Schemas are versioned by `schema_version`, pinned per session, and enforced by `workflows/scripts/validate-request.sh` on the workflow side plus `scripts/bridge-*` on the client side.

## 1. Directory layout

### `main` branch of the bridge repo (setup only — never touched by sessions)

```
ai-bridge-<user>/
  .github/
    workflows/
      bridge-gemini.yml           # triggered by push to session/**
      bridge-copilot.yml          # triggered by push to session/**
      bridge-maintenance.yml      # cron prune (runs on main)
      bridge-budget.yml           # cron budget report (runs on main)
    scripts/
      process-request.sh          # per-request driver
      assemble-prompt.sh          # M1 delimiter wrapping
      scrub-secrets.sh            # M5 regex scrubber
      canary-check.sh             # M6 canary detection
      sanitize-logs.sh            # M23 log scrubber
      validate-request.sh         # schema validation
    bridge-gemini-policy.json     # Gemini --policy file
    bridge-integrity.lock         # M10 npm integrity hashes
    CODEOWNERS                    # protects .github/
  .bridge/
    setup-version                 # schema version of this bridge install
  README.md
  .gitignore
```

### A session branch (orphan — no shared history with `main`)

```
(orphan branch session/<session-id>)
  .bridge/
    session-id                    # e.g. 20260409-1432-a7f3c201b4e5d8f6
    created-at                    # ISO-8601 UTC
    workflow-version              # 1 (pinned from main at init)
    client-version                # bridge-client/1.0.0
    caller.json                   # {"caller": "forge", "version": "2.1.0", ...}
  .github/                        # M22: pinned copy at init
    workflows/{bridge-gemini,bridge-copilot}.yml
    scripts/*.sh
    bridge-gemini-policy.json
  requests/
    req-20260409-143501-9b4e2f18/
      request.md                  # client writes once
      context/                    # client writes once (optional)
      status.json                 # workflow updates multiple times
      response.md                 # workflow writes once on success
      error.md                    # workflow writes only on failure (mutex with response.md)
      logs/
        runner.log
        tool-stdout.log
        tool-stderr.log
    req-20260409-144218-c2a1f307/
      ...
  README-SESSION.md
```

## 2. Naming conventions

| Entity | Format | Example | Entropy |
|---|---|---|---|
| Session ID | `<YYYYMMDD>-<HHMM>-<hex16>` | `20260409-1432-a7f3c201b4e5d8f6` | 128 bits (SEC-11) |
| Session branch | `session/<session-id>` | `session/20260409-1432-a7f3c201b4e5d8f6` | inherited |
| Request ID | `req-<YYYYMMDD>-<HHMMSS>-<hex8>` | `req-20260409-143501-9b4e2f18` | 32 bits (scoped to session) |
| Archive tag | `archive/session/<session-id>-<YYYYMMDD>` | — | — |
| Bridge-bot author | `bridge-bot <bridge-bot@users.noreply.github.com>` | — | — |
| Response commit msg | `bridge: response for <req-id> [bridge-response]` | — | — |

## 3. `request.md` (written by the client)

```yaml
---
# --- Identity & versioning (all required) ---
schema_version: 1
request_id: req-20260409-143501-9b4e2f18
session_id: 20260409-1432-a7f3c201b4e5d8f6
created_at: "2026-04-09T14:35:01.123Z"

# --- Routing (required) ---
kind: review                                 # enum: review | research | prompt
tool: gemini                                 # enum: gemini | copilot
model: auto                                  # enum: auto | gemini-2.5-pro | gemini-2.5-flash | copilot-gpt-5 | ...

# --- Resource bounds (required, with defaults) ---
max_runtime_sec: 300                         # int, hard cap, default 300, max 600
max_tokens_out: 4000

# --- Context (optional) ---
context_paths:
  - context/diff.patch
  - context/snippet-auth.py
context_summary: |
  A proposed JWT validation function and the diff that introduces it.

# --- Caller metadata (required) ---
caller:
  name: forge                                # enum: forge | codex-orchestration | bob | alf | pa | manual
  version: "2.1.0"
  task_id: forge-step-4b-review-auth
  hostname: gcp-workstation-01
  parent_session: 20260409-1430-xyz

# --- Behavior flags (optional, with defaults) ---
flags:
  allow_web_grounding: true                  # research only
  return_citations: true                     # research only
  return_format: markdown                    # v1: markdown only; json reserved
  inline_log_tail: false
---

# Prompt body

Free-form markdown after the closing `---`. Everything here is sent to the tool
after M1 delimiter wrapping.
```

### Field-level validation (enforced by `validate-request.sh`)

- All required fields present.
- `schema_version == 1`.
- `request_id` matches the containing directory name exactly.
- `session_id` matches the current branch name exactly (`session/<session_id>`).
- `kind` in `{review, research, prompt}`.
- `tool` in `{gemini, copilot}`.
- `30 <= max_runtime_sec <= 600`.
- `100 <= max_tokens_out <= 32000`.
- All paths listed in `context_paths` exist on disk at that location.
- Total request directory size `<= 50 MB` (M24 workflow-side cap).
- `flags.return_format == "markdown"` (v1 only; `json` is reserved).

## 4. `response.md` (written by the workflow on success)

```yaml
---
schema_version: 1
request_id: req-20260409-143501-9b4e2f18
session_id: 20260409-1432-a7f3c201b4e5d8f6
responded_at: "2026-04-09T14:38:01.456Z"

status: success                              # enum: success | error | timeout | rate_limited | cancelled | canary_detected | schema_invalid
error_code: null
error_message: null

tool: gemini
model_used: gemini-2.5-pro
model_version: "gemini-2.5-pro-20260315"

tokens_in: 5342
tokens_out: 1891
tokens_total: 7233
duration_sec: 143.7
estimated_cost_usd: 0.0432
actions_minutes_used: 2.6

runner_os: ubuntu-24.04
runner_cpu: x64
workflow_run_id: "12345"
workflow_run_url: "https://github.com/<owner>/ai-bridge-<user>/actions/runs/12345"
workflow_sha: abc123def456...
workflow_version: 1
cli_package: "@google/gemini-cli@0.36.0"
cli_integrity: "sha512-XXXXX..."

citations:                                   # research-only
  - url: https://example.com/...
    title: "..."
    retrieved_at: "..."
    confidence: high

warnings:
  - code: context_truncated
    message: "context/diff.patch exceeded 200KB, truncated"
---

# Response body

The tool's verbatim response, in markdown. Client extracts this section via `bridge result`.
```

Notes:
- `response.md` and `error.md` are mutually exclusive — exactly one of them exists per terminal request. If both exist (pathological workflow bug), `bridge wait` prefers `error.md` and emits a warning.
- `warnings[]` is optional and may be omitted entirely.
- `citations[]` is populated only for `kind: research` runs with `flags.allow_web_grounding: true`.

## 5. `status.json` (updated by the workflow through the state machine)

```json
{
  "schema_version": 1,
  "request_id": "req-20260409-143501-9b4e2f18",
  "session_id": "20260409-1432-a7f3c201b4e5d8f6",
  "state": "running",
  "state_history": [
    { "state": "queued",  "at": "2026-04-09T14:35:01.123Z" },
    { "state": "running", "at": "2026-04-09T14:35:34.567Z" }
  ],
  "started_at": "2026-04-09T14:35:34.567Z",
  "heartbeat_at": "2026-04-09T14:36:12.890Z",
  "finished_at": null,
  "workflow_run_id": "12345",
  "workflow_run_url": "https://github.com/<owner>/ai-bridge-<user>/actions/runs/12345",
  "runner_id": "github-hosted-ubuntu-24.04",
  "attempt": 1,
  "error_code": null,
  "error_message": null,
  "progress": {
    "phase": "running_tool",
    "detail": "gemini-2.5-pro responding"
  }
}
```

### State machine

```
queued -> running -> succeeded
                  -> failed
                  -> timeout
                  -> rate_limited
                  -> canary_detected
                  -> schema_invalid
                  -> cancelled
```

### Phase values (enumerated for `progress.phase`)

`queued`, `checking_out`, `authenticating`, `installing_cli`, `verifying_integrity`, `assembling_prompt`, `running_tool`, `scrubbing_output`, `canary_check`, `committing`.

### Heartbeat semantics

- `heartbeat_at` is updated every 15 seconds during the `running_tool` phase.
- Client considers the workflow stalled if `heartbeat_at` is more than 90 seconds stale while `state == running`. `bridge wait` surfaces this as a warning (not a terminal failure) and continues polling.
- Client never trusts workstation clock. Timestamps come from `git log -1 --format=%cI` (server-side, NTP-synced on the runner) or the runner's `date -u`.

## 6. `error.md` (written by the workflow instead of `response.md` on any failure)

```yaml
---
# --- Identity (mirrors request.md) ---
schema_version: 1
request_id: req-20260409-143501-9b4e2f18
session_id: 20260409-1432-a7f3c201b4e5d8f6
failed_at: "2026-04-09T14:36:45.123Z"

# --- Outcome (mirrors response.md) ---
status: error                                # always one of: error | timeout | rate_limited | cancelled | canary_detected | schema_invalid
error_code: tool_crash                       # required, non-null
error_message: "gemini-cli exited with code 1: rate limit exceeded on gemini-2.5-pro"

# --- Attempted invocation ---
tool: gemini
model_requested: gemini-2.5-pro
phase_when_failed: running_tool              # which status.json phase was active at failure
attempt: 1

# --- Debugging breadcrumbs ---
workflow_run_id: "12345"
workflow_run_url: "https://github.com/<owner>/ai-bridge-<user>/actions/runs/12345"
workflow_sha: abc123def456...
runner_id: github-hosted-ubuntu-24.04
runner_os: ubuntu-24.04
cli_package: "@google/gemini-cli@0.36.0"
last_stdout_line: "Error 429: Rate limit exceeded. Retry after 60s."
last_stderr_line: "FATAL: quota_exhausted"

# --- User-facing remediation (rendered by `bridge result`) ---
remediation: |
  Gemini 2.5 Pro hit its rate limit. Options:
  1. Wait 60 seconds and retry the same request
  2. Use `--model gemini-2.5-flash` for a lower-latency model with higher RPM
  3. Check your current quota: https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas
---

# Full error context

gemini-cli was invoked with assembled prompt from request.md + context/.
Phase `running_tool` failed after 1 attempt.

See the workflow run for full (scrubbed) stdout/stderr: <workflow_run_url>.
```

### Required fields (validated on read by `bridge wait` / `bridge result`)

`schema_version`, `request_id`, `session_id`, `failed_at`, `status`, `error_code` (non-null), `error_message`, `tool`, `phase_when_failed`, `attempt`, `workflow_run_url`, `remediation`.

### Optional fields (may be absent if the failure happened before the relevant phase)

`model_requested`, `workflow_sha`, `runner_id`, `runner_os`, `cli_package`, `last_stdout_line`, `last_stderr_line`.

### Enumerated error codes

| Code | Meaning |
|---|---|
| `schema_invalid` | request.md failed validation |
| `context_too_large` | total request dir >50 MB |
| `auth_failed` | WIF or PAT auth step failed |
| `secret_fetch_failed` | `get-secretmanager-secrets` failed |
| `integrity_mismatch` | npm install integrity hash did not match lock |
| `tool_install_failed` | `npm install -g` failed for reasons other than integrity |
| `tool_crash` | CLI exited non-zero |
| `tool_timeout` | CLI exceeded `max_runtime_sec` |
| `canary_detected` | canary env var appeared in response body |
| `scrub_pattern_match` | scrubber redacted known-secret pattern (fail-closed mode) |
| `response_too_large` | response body exceeded 500 KB |
| `cancelled` | user cancelled the workflow run |
| `runner_out_of_memory` | runner killed the job |
| `unknown` | any uncategorized failure |

## 7. Commit message conventions

| Who | When | Format |
|---|---|---|
| Client | `bridge init` | `bridge: init session <id> [skip ci]` |
| Client | `bridge request` (single) | `bridge: request <request-id>` |
| Workflow | mid-run status update | `bridge: status <request-id> running [bridge-response] [skip ci]` |
| Workflow | response (single, success) | `bridge: response for <request-id> [bridge-response]` |
| Workflow | response (batch, rare) | `bridge: responses for <N> requests [bridge-response]` |
| Workflow | error | `bridge: error <request-id> <error-code> [bridge-response]` |
| Maintenance | archive | `bridge: archive session <id> [skip ci]` |

## 8. Version handshake

- At `bridge init`: client reads `main:.bridge/setup-version`, writes it to the session branch's `.bridge/workflow-version`, records client version in `.bridge/client-version`.
- At every `bridge request`: workflow reads pinned `workflow-version` from the session branch, reads `schema_version` from the request, fails with `error_code: schema_invalid` on mismatch.
- Session branches keep using their pinned workflow even if `main`'s workflow is updated mid-session. This is M22.

## 9. Fields deliberately NOT in v1 schema

- `auth:` / `credentials:` — secrets never travel in requests (Secret Manager only).
- `callback_url:` — push notifications are v2; v1 is pure polling.
- `retry_policy:` — retries are a client decision, not a request field.
- `priority:` — Actions has no native priority; would be cosmetic.
- `kind: agent` fields (sandbox policy, file allowlist, max commits) — reserved for v2.3, schema forward-compatible.

## 10. Exit codes for client scripts

| Code | Script | Meaning |
|---|---|---|
| 0 | any | Success |
| 1 | `bridge *` | Generic failure (usage error, flag parse) |
| 2 | `bridge init` | Bridge repo not private (SEC-7 violation, refuses to proceed) |
| 3 | `bridge request` | Context exceeds size caps |
| 4 | `bridge wait` | Terminal error — `error.md` present |
| 5 | `bridge wait` | Terminal timeout — `status.state == timeout` |
| 6 | `bridge wait` | Canary detected — `status.state == canary_detected` |
| 7 | `bridge request` / `bridge wait` | Rate limit (client-side or workflow-side) |
| 8 | `bridge result` | UTF-8 validation failed on response body |
| 9 | `bridge result` | Response hash cache mismatch (possible history rewrite) |
