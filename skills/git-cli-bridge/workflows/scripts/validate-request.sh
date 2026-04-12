#!/usr/bin/env bash
# validate-request.sh — request.md schema validation (yq-based).
#
# Usage: validate-request.sh <req-dir>
# Exits 0 if valid, non-zero with an error on stderr if not.
# Schema fields and constraints from references/protocol.md §3.

set -euo pipefail
REQ_DIR="${1:?usage: validate-request.sh <req-dir>}"
REQ="$REQ_DIR/request.md"
[ -f "$REQ" ] || { echo "request.md missing: $REQ" >&2; exit 1; }

require_field() {
  local key="$1"
  local val
  val="$(yq "$key // null" "$REQ" 2>/dev/null || echo null)"
  if [ "$val" = "null" ] || [ -z "$val" ]; then
    echo "validate-request: missing required field $key" >&2
    exit 1
  fi
  printf '%s' "$val"
}

# Required fields
sv="$(require_field '.schema_version')"
rid="$(require_field '.request_id')"
sid="$(require_field '.session_id')"
kind="$(require_field '.kind')"
tool="$(require_field '.tool')"
mrs="$(require_field '.max_runtime_sec')"
mto="$(require_field '.max_tokens_out')"
cname="$(require_field '.caller.name')"

# schema_version must be 1
if [ "$sv" != "1" ]; then
  echo "validate-request: schema_version=$sv, expected 1" >&2
  exit 1
fi

# request_id must match directory name
dir_rid="$(basename "$REQ_DIR")"
if [ "$rid" != "$dir_rid" ]; then
  echo "validate-request: request_id=$rid does not match dir name $dir_rid" >&2
  exit 1
fi

# kind enum
case "$kind" in
  review|research|prompt) ;;
  *) echo "validate-request: kind=$kind not in {review,research,prompt}" >&2; exit 1 ;;
esac

# tool enum
case "$tool" in
  gemini|copilot) ;;
  *) echo "validate-request: tool=$tool not in {gemini,copilot}" >&2; exit 1 ;;
esac

# max_runtime_sec range
if ! [[ "$mrs" =~ ^[0-9]+$ ]] || [ "$mrs" -lt 30 ] || [ "$mrs" -gt 600 ]; then
  echo "validate-request: max_runtime_sec=$mrs out of range [30,600]" >&2
  exit 1
fi

# max_tokens_out range
if ! [[ "$mto" =~ ^[0-9]+$ ]] || [ "$mto" -lt 100 ] || [ "$mto" -gt 32000 ]; then
  echo "validate-request: max_tokens_out=$mto out of range [100,32000]" >&2
  exit 1
fi

# context_paths existence (if any)
if yq -e '.context_paths' "$REQ" >/dev/null 2>&1; then
  while IFS= read -r cp; do
    [ -z "$cp" ] && continue
    if [ ! -f "$REQ_DIR/$cp" ]; then
      echo "validate-request: context path missing: $REQ_DIR/$cp" >&2
      exit 1
    fi
  done < <(yq '.context_paths[]' "$REQ" 2>/dev/null || true)
fi

# Total directory size cap (50 MB)
sz="$(du -sb "$REQ_DIR" 2>/dev/null | awk '{print $1}')"
if [ "${sz:-0}" -gt 52428800 ]; then
  echo "validate-request: request dir exceeds 50 MB ($sz bytes)" >&2
  exit 1
fi

echo "validate-request: OK ($rid)"
