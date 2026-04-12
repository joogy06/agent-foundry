#!/usr/bin/env bash
# process-request.sh — per-request driver for both Gemini and Copilot.
#
# Usage: process-request.sh <req-dir> <tool:gemini|copilot>
#
# Responsibilities:
#   1. Drive status.json through the state machine (queued -> running -> done).
#   2. Assemble the prompt via M1 (assemble-prompt.sh).
#   3. Invoke the CLI with narrow scoping (M2).
#   4. Apply scrubber (M5) and canary check (M6) to the response.
#   5. Cap response size (M7).
#   6. Capture sanitized log tails (M23).
#   7. Write response.md (or error.md on failure).
#
# Runs as part of the bridge-gemini.yml / bridge-copilot.yml workflow.

set -euo pipefail

REQ_DIR="${1:?usage: process-request.sh <req-dir> <tool>}"
TOOL="${2:?usage: process-request.sh <req-dir> <tool>}"
SCRIPTS_DIR="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd)"
RESPONSE_CAP_BYTES=512000   # 500 KB

[ -d "$REQ_DIR" ] || { echo "req dir missing: $REQ_DIR" >&2; exit 1; }
STATUS="$REQ_DIR/status.json"
[ -f "$STATUS" ] || { echo "status.json missing" >&2; exit 1; }

REQ_ID="$(basename "$REQ_DIR")"
SID="$(yq '.session_id' "$REQ_DIR/request.md")"
MAX_RUNTIME="$(yq '.max_runtime_sec' "$REQ_DIR/request.md")"
MODEL="$(yq '.model // "auto"' "$REQ_DIR/request.md")"

# --- status helpers ---
update_status() {
  # $1 = state, $2 = phase, $3 = detail
  local state="$1" phase="$2" detail="$3"
  local now
  now="$(date -u +%FT%TZ)"
  jq --arg s "$state" --arg p "$phase" --arg d "$detail" --arg at "$now" \
    '.state = $s
     | .state_history += [{state: $s, at: $at}]
     | .progress = {phase: $p, detail: $d}
     | (if $s == "running" and (.started_at // null) == null then .started_at = $at else . end)
     | (if ($s == "succeeded" or $s == "failed" or $s == "timeout" or $s == "canary_detected") then .finished_at = $at else . end)
    ' "$STATUS" > "$STATUS.tmp" && mv "$STATUS.tmp" "$STATUS"
}

heartbeat() {
  local now
  now="$(date -u +%FT%TZ)"
  jq --arg at "$now" '.heartbeat_at = $at' "$STATUS" > "$STATUS.tmp" && mv "$STATUS.tmp" "$STATUS"
}

write_error() {
  # $1 = error_code, $2 = error_message, $3 = phase_when_failed
  local ec="$1" em="$2" phase="$3"
  local now
  now="$(date -u +%FT%TZ)"
  cat > "$REQ_DIR/error.md" <<EOF
---
schema_version: 1
request_id: $REQ_ID
session_id: $SID
failed_at: "$now"
status: error
error_code: $ec
error_message: "$em"
tool: $TOOL
model_requested: $MODEL
phase_when_failed: $phase
attempt: 1
workflow_run_id: "${GITHUB_RUN_ID:-unknown}"
workflow_run_url: "https://github.com/${GITHUB_REPOSITORY:-unknown}/actions/runs/${GITHUB_RUN_ID:-unknown}"
runner_os: "${RUNNER_OS:-unknown}"
cli_package: "$(cli_package_label)"
remediation: |
  See references/operations.md §4 for the runbook matching this error_code.
---

# Failure context

Workflow failed during phase $phase with error_code $ec.
Run URL: https://github.com/${GITHUB_REPOSITORY:-unknown}/actions/runs/${GITHUB_RUN_ID:-unknown}
EOF
  update_status "failed" "$phase" "$ec: $em"
}

cli_package_label() {
  case "$TOOL" in
    gemini)  printf '@google/gemini-cli@0.36.0' ;;
    copilot) printf '@github/copilot@1.0.21' ;;
    *)       printf 'unknown' ;;
  esac
}

invoke_gemini() {
  # $1 = prompt file, $2 = stdout file, $3 = stderr file
  local pf="$1" out="$2" err="$3"
  local policy="$(dirname "$SCRIPTS_DIR")/bridge-gemini-policy.json"
  timeout "$MAX_RUNTIME" gemini \
    --approval-mode plan \
    --policy "$policy" \
    --model "${MODEL/auto/gemini-2.5-pro}" \
    --output-format markdown \
    < "$pf" > "$out" 2> "$err"
}

invoke_copilot() {
  local pf="$1" out="$2" err="$3"
  timeout "$MAX_RUNTIME" copilot -p \
    --allow-tool='shell(git:status)' \
    --allow-tool='shell(git:diff)' \
    --deny-tool='shell(curl:*)' \
    --deny-tool='shell(wget:*)' \
    --deny-tool='shell(nc:*)' \
    --secret-env-vars COPILOT_GITHUB_TOKEN,GOOGLE_APPLICATION_CREDENTIALS \
    --no-ask-user \
    --output-format markdown \
    < "$pf" > "$out" 2> "$err"
}

# --- main flow ---
update_status "running" "assembling_prompt" "wrapping context with <user_data>"
heartbeat

PROMPT_FILE="$(mktemp)"
CLI_STDOUT="$REQ_DIR/logs/tool-stdout.log"
CLI_STDERR="$REQ_DIR/logs/tool-stderr.log"
mkdir -p "$REQ_DIR/logs"

if ! "$SCRIPTS_DIR/assemble-prompt.sh" "$REQ_DIR" > "$PROMPT_FILE"; then
  write_error "tool_install_failed" "assemble-prompt.sh failed" "assembling_prompt"
  exit 1
fi

update_status "running" "running_tool" "${TOOL} ${MODEL}"
heartbeat

# background heartbeat loop (refreshes every 15s during tool run)
(
  while true; do
    sleep 15
    heartbeat
  done
) &
HB_PID=$!
trap 'kill "$HB_PID" 2>/dev/null || true' EXIT

rc=0
case "$TOOL" in
  gemini)
    invoke_gemini "$PROMPT_FILE" "$CLI_STDOUT" "$CLI_STDERR" || rc=$?
    ;;
  copilot)
    invoke_copilot "$PROMPT_FILE" "$CLI_STDOUT" "$CLI_STDERR" || rc=$?
    ;;
  *)
    write_error "unknown" "tool=$TOOL not supported" "running_tool"
    exit 1
    ;;
esac

kill "$HB_PID" 2>/dev/null || true
trap - EXIT

# Sanitize log tails regardless of success.
"$SCRIPTS_DIR/sanitize-logs.sh" < "$CLI_STDOUT" > "$CLI_STDOUT.sanitized" && mv "$CLI_STDOUT.sanitized" "$CLI_STDOUT" || true
"$SCRIPTS_DIR/sanitize-logs.sh" < "$CLI_STDERR" > "$CLI_STDERR.sanitized" && mv "$CLI_STDERR.sanitized" "$CLI_STDERR" || true

if [ "$rc" -eq 124 ]; then
  write_error "tool_timeout" "CLI exceeded max_runtime_sec=$MAX_RUNTIME" "running_tool"
  exit 0
elif [ "$rc" -ne 0 ]; then
  write_error "tool_crash" "CLI exited with code $rc" "running_tool"
  exit 0
fi

# Cap response size.
update_status "running" "scrubbing_output" "size cap + scrubber"
if [ "$(stat -c %s "$CLI_STDOUT" 2>/dev/null || stat -f %z "$CLI_STDOUT")" -gt "$RESPONSE_CAP_BYTES" ]; then
  head -c "$RESPONSE_CAP_BYTES" "$CLI_STDOUT" > "$CLI_STDOUT.trunc" && mv "$CLI_STDOUT.trunc" "$CLI_STDOUT"
fi

# Scrub.
"$SCRIPTS_DIR/scrub-secrets.sh" "$CLI_STDOUT" || true

# Canary check.
update_status "running" "canary_check" "checking for env var exfiltration"
if "$SCRIPTS_DIR/canary-check.sh" "$CLI_STDOUT"; then
  # Canary detected — FAIL, do not commit response body.
  write_error "canary_detected" "BRIDGE_CANARY appeared in response body" "canary_check"
  update_status "canary_detected" "canary_check" "canary fired"
  exit 0
fi

# Write response.md.
update_status "running" "committing" "writing response.md"
NOW="$(date -u +%FT%TZ)"
cat > "$REQ_DIR/response.md" <<EOF
---
schema_version: 1
request_id: $REQ_ID
session_id: $SID
responded_at: "$NOW"
status: success
error_code: null
error_message: null
tool: $TOOL
model_used: "$MODEL"
runner_os: "${RUNNER_OS:-ubuntu-24.04}"
workflow_run_id: "${GITHUB_RUN_ID:-unknown}"
workflow_run_url: "https://github.com/${GITHUB_REPOSITORY:-unknown}/actions/runs/${GITHUB_RUN_ID:-unknown}"
workflow_version: 1
cli_package: "$(cli_package_label)"
---

EOF
cat "$CLI_STDOUT" >> "$REQ_DIR/response.md"

update_status "succeeded" "committing" "response.md written"
exit 0
