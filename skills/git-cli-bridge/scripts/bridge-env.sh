#!/usr/bin/env bash
# bridge-env.sh — shared environment and helpers, sourced by all bridge-* scripts.
# NOT an executable command. Always `source` this file, never run it.

# Require bash 4+ (associative arrays, mapfile).
if [ -z "${BASH_VERSION:-}" ]; then
  echo "bridge: bash required" >&2
  return 1 2>/dev/null || exit 1
fi

# --- Identity and paths ----------------------------------------------------
BRIDGE_CLIENT_VERSION="bridge-client/1.0.0"
BRIDGE_SCHEMA_VERSION=1

# Resolve the skill root no matter where the script is invoked from.
_bridge_self="${BASH_SOURCE[0]}"
BRIDGE_SKILL_ROOT="$(cd "$(dirname "$_bridge_self")/.." >/dev/null 2>&1 && pwd)"
BRIDGE_SCRIPTS_DIR="$BRIDGE_SKILL_ROOT/scripts"

# XDG-aware runtime / cache / data directories.
BRIDGE_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"
BRIDGE_CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/bridge"
BRIDGE_DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/bridge"
BRIDGE_LOCAL_WORKSPACE="$BRIDGE_DATA_DIR/workspace"

mkdir -p "$BRIDGE_CACHE_DIR" "$BRIDGE_DATA_DIR" "$BRIDGE_LOCAL_WORKSPACE" 2>/dev/null || true

# --- Output helpers (all stderr so stdout stays clean for pipelines) -------
bridge_info()  { printf 'bridge: %s\n' "$*" >&2; }
bridge_warn()  { printf 'bridge: WARN: %s\n' "$*" >&2; }
bridge_err()   { printf 'bridge: ERROR: %s\n' "$*" >&2; }

# --- Dependency check ------------------------------------------------------
# bridge_require cmd1 cmd2 ...
# Verifies every named command is on PATH; prints an actionable error and
# returns 1 if any is missing.
bridge_require() {
  local missing=()
  local cmd
  for cmd in "$@"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      missing+=("$cmd")
    fi
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    bridge_err "missing required commands: ${missing[*]}"
    bridge_err "install them before re-running. See references/first-boot.md."
    return 1
  fi
  return 0
}

# --- Session tag resolution ------------------------------------------------
# Returns the session tag used for cache file names. Priority:
#   1. $FORGE_SESSION_ID      (set by forge when it spawns bob)
#   2. $CLAUDE_SESSION_ID     (set by claude-code in some contexts)
#   3. $$                     (current process PID, good enough for manual use)
bridge_session_tag() {
  printf '%s' "${FORGE_SESSION_ID:-${CLAUDE_SESSION_ID:-$$}}"
}

# --- Bridge repo URL resolution --------------------------------------------
# Reads from `git config --global bridge.repo`. Returns non-zero if unset.
bridge_repo_url() {
  local url
  url="$(git config --global bridge.repo 2>/dev/null || true)"
  if [ -z "$url" ]; then
    return 1
  fi
  printf '%s' "$url"
}

# --- Current-session helpers -----------------------------------------------
# The current session id is recorded in $BRIDGE_CACHE_DIR/current-session
# by `bridge-init` and cleared by `bridge-close`.
bridge_current_session() {
  local f="$BRIDGE_CACHE_DIR/current-session"
  [ -f "$f" ] || return 1
  cat "$f"
}

bridge_set_current_session() {
  printf '%s\n' "$1" > "$BRIDGE_CACHE_DIR/current-session"
}

bridge_clear_current_session() {
  rm -f "$BRIDGE_CACHE_DIR/current-session"
}

# --- Rate limiter ----------------------------------------------------------
# bridge_rate_limit_check <session-id>
# Records each call in a rolling log; refuses (exit 7) if >10 calls in 60s.
bridge_rate_limit_check() {
  local session="$1"
  local log="$BRIDGE_CACHE_DIR/rate-$session.log"
  local now
  now="$(date +%s)"
  # Append the current timestamp.
  printf '%s\n' "$now" >> "$log"
  # Count entries within the last 60 seconds.
  local count
  count="$(awk -v cutoff="$((now - 60))" '$1 >= cutoff' "$log" | wc -l)"
  if [ "$count" -gt 10 ]; then
    bridge_err "rate limit: more than 10 requests in 60s for this session"
    return 7
  fi
  # Truncate old entries to keep the file small.
  awk -v cutoff="$((now - 120))" '$1 >= cutoff' "$log" > "$log.tmp" && mv "$log.tmp" "$log"
  return 0
}

# --- Safety: forbid sourcing response content ------------------------------
# Defensive no-op guard that other scripts can call before they read any file
# that contains workflow-originated content. The guard makes eval/source
# attempts a loud error rather than silent execution.
bridge_forbid_eval() {
  alias eval='bridge_err "eval is forbidden in bridge client scripts"; false' 2>/dev/null || true
}

# Export the important variables for subshells.
export BRIDGE_CLIENT_VERSION BRIDGE_SCHEMA_VERSION
export BRIDGE_SKILL_ROOT BRIDGE_SCRIPTS_DIR
export BRIDGE_RUNTIME_DIR BRIDGE_CACHE_DIR BRIDGE_DATA_DIR BRIDGE_LOCAL_WORKSPACE
