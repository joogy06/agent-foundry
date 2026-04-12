#!/usr/bin/env bash
# bridge-mode-detect.sh — sandbox-aware routing decision for git-cli-bridge.
#
# Prints "local" or "bridge" to stdout and exits 0 on success.
# Priority order:
#   1. AI_BRIDGE_DISABLE=1      -> always "local", ignore cache
#   2. AI_BRIDGE_MODE=1         -> always "bridge", ignore cache
#   3. Cached decision          -> reuse (sticky, M21)
#   4. Probe gemini --version + copilot --version with 3s timeout each.
#      Both reachable -> "local", reset fail counter.
#      Either fails   -> increment counter; >= 3 fails -> "bridge" (cached).
#
# The first 2 probe failures still return "local" (hysteresis). This matches
# the design-doc's 3-failure threshold and is verified by IT4/IT5 smoke tests.
#
# Options:
#   --reset   Clear cache + counter for current session tag, exit 0.
#   --probe   Probe once; do NOT update the cache. Useful for diagnostics.
#
# Environment overrides for testing (consumed by the smoke test harness):
#   BRIDGE_PROBE_GEMINI=ok|fail     force gemini probe result
#   BRIDGE_PROBE_COPILOT=ok|fail    force copilot probe result
#   BRIDGE_MODE_CACHE_DIR=/path     override $XDG_RUNTIME_DIR (for test isolation)

set -euo pipefail

BRIDGE_SELF_DIR="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd)"
# shellcheck disable=SC1091
. "$BRIDGE_SELF_DIR/bridge-env.sh"

CACHE_DIR="${BRIDGE_MODE_CACHE_DIR:-$BRIDGE_RUNTIME_DIR}"
mkdir -p "$CACHE_DIR" 2>/dev/null || true

SESSION_TAG="$(bridge_session_tag)"
CACHE_FILE="$CACHE_DIR/bridge-mode-$SESSION_TAG"
COUNTER_FILE="$CACHE_DIR/bridge-mode-fails-$SESSION_TAG"

# -------- argument parsing --------
MODE_RESET=0
MODE_PROBE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --reset) MODE_RESET=1 ;;
    --probe) MODE_PROBE_ONLY=1 ;;
    *)
      printf 'bridge-mode-detect.sh: unknown option: %s\n' "$arg" >&2
      exit 1
      ;;
  esac
done

if [ "$MODE_RESET" -eq 1 ]; then
  rm -f "$CACHE_FILE" "$COUNTER_FILE"
  exit 0
fi

# -------- priority 1: disable wins everything --------
if [ "${AI_BRIDGE_DISABLE:-}" = "1" ]; then
  printf 'local\n'
  exit 0
fi

# -------- priority 2: explicit bridge mode --------
if [ "${AI_BRIDGE_MODE:-}" = "1" ]; then
  printf 'bridge\n'
  exit 0
fi

# -------- priority 3: cached decision --------
if [ "$MODE_PROBE_ONLY" -eq 0 ] && [ -f "$CACHE_FILE" ]; then
  cached="$(cat "$CACHE_FILE" 2>/dev/null || true)"
  if [ "$cached" = "local" ] || [ "$cached" = "bridge" ]; then
    printf '%s\n' "$cached"
    exit 0
  fi
fi

# -------- priority 4: probe --------
probe_cli() {
  # $1 = cli name
  # Returns 0 if CLI is reachable, 1 otherwise.
  local name="$1"
  local override
  case "$name" in
    gemini)  override="${BRIDGE_PROBE_GEMINI:-}" ;;
    copilot) override="${BRIDGE_PROBE_COPILOT:-}" ;;
    *)       override="" ;;
  esac
  if [ -n "$override" ]; then
    [ "$override" = "ok" ]
    return
  fi
  if ! command -v "$name" >/dev/null 2>&1; then
    return 1
  fi
  timeout 3 "$name" --version >/dev/null 2>&1 || return 1
  return 0
}

gemini_ok=0
copilot_ok=0
probe_cli gemini  && gemini_ok=1 || gemini_ok=0
probe_cli copilot && copilot_ok=1 || copilot_ok=0

if [ "$gemini_ok" -eq 1 ] && [ "$copilot_ok" -eq 1 ]; then
  # Both work — reset counter, return local.
  if [ "$MODE_PROBE_ONLY" -eq 0 ]; then
    rm -f "$COUNTER_FILE"
    printf 'local\n' > "$CACHE_FILE"
  fi
  printf 'local\n'
  exit 0
fi

# One or both failed — increment counter (unless probe-only).
if [ "$MODE_PROBE_ONLY" -eq 0 ]; then
  current=0
  if [ -f "$COUNTER_FILE" ]; then
    current="$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)"
    # Guard against garbage / non-numeric cache contents.
    case "$current" in ''|*[!0-9]*) current=0 ;; esac
  fi
  current=$((current + 1))
  printf '%d\n' "$current" > "$COUNTER_FILE"

  if [ "$current" -ge 3 ]; then
    printf 'bridge\n' > "$CACHE_FILE"
    printf 'bridge\n'
    exit 0
  else
    # Hysteresis: still return local for the first two failures.
    printf 'local\n'
    exit 0
  fi
else
  # Probe-only: do not mutate counters.
  if [ "$gemini_ok" -eq 0 ] && [ "$copilot_ok" -eq 0 ]; then
    printf 'bridge\n'
  else
    printf 'local\n'
  fi
  exit 0
fi
