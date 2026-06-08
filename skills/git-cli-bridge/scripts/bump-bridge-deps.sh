#!/usr/bin/env bash
# bump-bridge-deps.sh — dev helper to bump pinned npm deps and refresh the
# integrity lock under workflows/bridge-integrity.lock.
#
# Usage: bump-bridge-deps.sh [--agy 1.0.4] [--copilot 1.1.0]
#
# Per-design rules:
#   - Never resolves @latest.
#   - Uses `npm view @<pkg>@<version> dist.integrity` (local registry read, no install).
#   - Writes the lock file atomically.
#   - Does NOT edit workflow YAML version strings; reviewer handles that step.
#
# TODO(agy): verify equivalent — agy (Antigravity CLI) is NOT distributed as an
# npm package, so the `npm view ... dist.integrity` integrity-lock flow does not
# apply to it. The --agy flag below is a placeholder that records the requested
# version but cannot compute an npm integrity hash. Determine agy's actual
# install/distribution channel and a pin+verify mechanism before wiring this up.
# The --copilot path is unchanged (still a real npm package).

set -euo pipefail
BRIDGE_SELF_DIR="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd)"
# shellcheck disable=SC1091
. "$BRIDGE_SELF_DIR/bridge-env.sh"

AGY_VER=""
COPILOT_VER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --agy)     AGY_VER="$2"; shift 2 ;;
    --copilot) COPILOT_VER="$2"; shift 2 ;;
    -h|--help) sed -n '2,11p' "$0" >&2; exit 0 ;;
    *) bridge_err "unknown: $1"; exit 1 ;;
  esac
done

bridge_require npm || exit 1

LOCK="$BRIDGE_SKILL_ROOT/workflows/bridge-integrity.lock"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

fetch_integrity() {
  local pkg="$1" ver="$2"
  local out
  out="$(npm view "${pkg}@${ver}" dist.integrity 2>/dev/null || true)"
  if [ -z "$out" ]; then
    bridge_err "npm registry returned empty integrity for ${pkg}@${ver}"
    return 1
  fi
  printf '%s\n' "$out"
}

# Preserve any existing pinned packages that are not being bumped.
if [ -f "$LOCK" ]; then
  cp "$LOCK" "$TMP"
fi

update_lock_line() {
  local pkg="$1" ver="$2"
  local integ
  integ="$(fetch_integrity "$pkg" "$ver")" || return 1
  # Remove existing line for this pkg, append new one.
  awk -v p="$pkg" '$1 != p@NOPE_MARKER' "$TMP" > "$TMP.new" 2>/dev/null || true
  grep -v "^${pkg}@" "$TMP" > "$TMP.new" 2>/dev/null || true
  mv "$TMP.new" "$TMP"
  printf '%s@%s %s\n' "$pkg" "$ver" "$integ" >> "$TMP"
  bridge_info "bumped ${pkg}@${ver}: $integ"
}

if [ -n "$AGY_VER" ]; then
  # TODO(agy): verify equivalent — agy is not an npm package, so we cannot fetch
  # an npm integrity hash for it. Skip the npm lock-line update and warn loudly.
  bridge_err "TODO(agy): agy ($AGY_VER) is not an npm package; no npm integrity hash to pin. Skipping lock update for agy."
fi
if [ -n "$COPILOT_VER" ]; then
  update_lock_line "@github/copilot" "$COPILOT_VER"
fi

# Atomic write.
mv "$TMP" "$LOCK"
trap - EXIT

bridge_info "wrote $LOCK"
bridge_info "next: review the diff, update workflow YAML version strings, commit, open PR"
