#!/usr/bin/env bash
# verify-codex-install.sh  (Evergreening v1, S041 — refresh-recipe (1) cli-reference)
#
# Sanity-check the local Codex CLI install against this skill's documented surface.
# Captures `codex --help` output, extracts the command/flag set, and reports drift vs
# the version anchor in codex-orchestration's docs. Bob's refresh recipe (1) runs this,
# then a normalized flag/command diff, then updates anchors + tables, then
# `freshness.py restamp`.
#
# Exit codes:
#   0 — clean: codex installed, version readable, help captured
#   1 — codex binary not found
#   4 — `codex --help` failed
#   3 — drift detected vs the documented version anchor (warning; --strict makes it fatal)
#
# Usage:
#   bash ~/.claude/skills/codex-orchestration/scripts/verify-codex-install.sh [--strict]
#
set -o errexit
set -o nounset
set -o pipefail

STRICT=0
[ "${1:-}" = "--strict" ] && STRICT=1

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INVENTORY="$HOME/.claude/state/inventory.json"
WORK_DIR="$(mktemp -d /tmp/verify-codex-XXXXXXXXXX)"
trap 'rm -rf "$WORK_DIR"' EXIT

ok()   { printf "  [OK]   %s\n" "$1"; }
warn() { printf "  [WARN] %s\n" "$1"; }
err()  { printf "  [ERR]  %s\n" "$1" >&2; }

printf "verify-codex-install.sh — checking %s\n\n" "$SKILL_DIR"

# 1. codex binary present
printf "1) codex binary\n"
if ! command -v codex >/dev/null 2>&1; then
  err "codex not found in PATH"
  exit 1
fi
CODEX_VERSION_RAW="$(codex --version 2>&1 || true)"
CODEX_VERSION="$(printf '%s' "$CODEX_VERSION_RAW" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
ok "found: $CODEX_VERSION_RAW (parsed: ${CODEX_VERSION:-unknown})"
echo

# 2. capture help surfaces
printf "2) capturing help to %s\n" "$WORK_DIR"
codex --help        > "$WORK_DIR/codex-help.txt" 2>&1 || { err "codex --help failed"; exit 4; }
codex exec --help   > "$WORK_DIR/codex-exec-help.txt" 2>&1 || warn "codex exec --help failed"
COMMANDS="$(grep -oE '^\s+[a-z][a-z-]+' "$WORK_DIR/codex-help.txt" | tr -d ' ' | sort -u | tr '\n' ' ')"
ok "commands: ${COMMANDS:-none extracted}"
echo

# 3. drift vs documented anchor (the SKILL.md / patterns.md version reference)
printf "3) version-anchor drift\n"
DOC_VERSION="$(grep -hoE 'Codex CLI [0-9]+\.[0-9]+\.[0-9]+|0\.1[0-9][0-9]\.[0-9]+' \
  "$SKILL_DIR/SKILL.md" "$SKILL_DIR/patterns.md" 2>/dev/null \
  | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
INV_VERSION="$(python3 -c "import json;print(json.load(open('$INVENTORY'))['tools']['codex'].get('version',''))" 2>/dev/null || true)"
printf "   installed=%s  documented=%s  inventory=%s\n" "${CODEX_VERSION:-?}" "${DOC_VERSION:-none}" "${INV_VERSION:-?}"
DRIFT=0
if [ -n "$CODEX_VERSION" ] && [ -n "$DOC_VERSION" ] && [ "$CODEX_VERSION" != "$DOC_VERSION" ]; then
  warn "documented version ($DOC_VERSION) != installed ($CODEX_VERSION) — restamp recommended:"
  warn "  python3 ~/.claude/skills/_meta/freshness.py restamp $SKILL_DIR/SKILL.md --tool codex --to $CODEX_VERSION"
  DRIFT=1
else
  ok "version anchor matches installed (or no anchor present)"
fi
echo

if [ "$DRIFT" -eq 1 ] && [ "$STRICT" -eq 1 ]; then
  err "drift detected and --strict set"
  exit 3
fi
printf "verify-codex-install.sh: done (drift=%s)\n" "$DRIFT"
exit 0
