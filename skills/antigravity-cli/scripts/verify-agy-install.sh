#!/usr/bin/env bash
# verify-agy-install.sh  (Evergreening v1, S041 — refresh-recipe (1) cli-reference)
#
# Sanity-check the local Antigravity CLI (`agy`) install against this skill's documented
# surface. Captures `agy --help`, extracts the command set, and reports drift vs the
# version anchor in antigravity-cli's docs. Bob's refresh recipe (1) runs this, then a
# normalized command diff, then updates anchors + tables, then `freshness.py restamp`.
#
# Exit codes:
#   0 — clean: agy installed, version readable, help captured
#   1 — agy binary not found
#   4 — `agy --help` failed
#   3 — drift detected vs the documented version anchor (warning; --strict makes it fatal)
#
# Usage:
#   bash ~/.claude/skills/antigravity-cli/scripts/verify-agy-install.sh [--strict]
#
set -o errexit
set -o nounset
set -o pipefail

STRICT=0
[ "${1:-}" = "--strict" ] && STRICT=1

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INVENTORY="$HOME/.claude/state/inventory.json"
WORK_DIR="$(mktemp -d /tmp/verify-agy-XXXXXXXXXX)"
trap 'rm -rf "$WORK_DIR"' EXIT

ok()   { printf "  [OK]   %s\n" "$1"; }
warn() { printf "  [WARN] %s\n" "$1"; }
err()  { printf "  [ERR]  %s\n" "$1" >&2; }

printf "verify-agy-install.sh — checking %s\n\n" "$SKILL_DIR"

# 1. agy binary present
printf "1) agy binary\n"
if ! command -v agy >/dev/null 2>&1; then
  err "agy not found in PATH"
  exit 1
fi
AGY_VERSION_RAW="$(agy --version 2>&1 || true)"
AGY_VERSION="$(printf '%s' "$AGY_VERSION_RAW" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
ok "found: $AGY_VERSION_RAW (parsed: ${AGY_VERSION:-unknown})"
echo

# 2. capture help surface (agy has a small surface — no model flag, account-auth)
printf "2) capturing help to %s\n" "$WORK_DIR"
agy --help > "$WORK_DIR/agy-help.txt" 2>&1 || { err "agy --help failed"; exit 4; }
COMMANDS="$(grep -oE '^\s+[a-z][a-z-]+' "$WORK_DIR/agy-help.txt" | tr -d ' ' | sort -u | tr '\n' ' ')"
ok "commands: ${COMMANDS:-none extracted}"
# sanity: agy must NOT have grown a -m/--model flag (host directive depends on its absence)
if grep -qE '(^|\s)(-m|--model)\b' "$WORK_DIR/agy-help.txt"; then
  warn "agy --help now mentions -m/--model — the 'no model flag' host directive may need review"
fi
echo

# 3. drift vs documented anchor
printf "3) version-anchor drift\n"
DOC_VERSION="$(grep -hoE 'Antigravity CLI [0-9]+\.[0-9]+\.[0-9]+|agy [0-9]+\.[0-9]+\.[0-9]+' \
  "$SKILL_DIR/SKILL.md" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
INV_VERSION="$(python3 -c "import json;print(json.load(open('$INVENTORY'))['tools']['agy'].get('version',''))" 2>/dev/null || true)"
printf "   installed=%s  documented=%s  inventory=%s\n" "${AGY_VERSION:-?}" "${DOC_VERSION:-none}" "${INV_VERSION:-?}"
DRIFT=0
if [ -n "$AGY_VERSION" ] && [ -n "$DOC_VERSION" ] && [ "$AGY_VERSION" != "$DOC_VERSION" ]; then
  warn "documented version ($DOC_VERSION) != installed ($AGY_VERSION) — restamp recommended:"
  warn "  python3 ~/.claude/skills/_meta/freshness.py restamp $SKILL_DIR/SKILL.md --tool agy --to $AGY_VERSION"
  DRIFT=1
else
  ok "version anchor matches installed (or no anchor present)"
fi
echo

# STDIN regression probe (#135, root-caused 2026-06-05): agy reads non-TTY stdin until
# EOF BEFORE the model call — an open never-EOF stdin (background/harness/cron shells)
# hangs agy forever at 0 bytes, and --print-timeout does NOT fire (print-phase only).
# Hang signature: exit 124 + empty output when stdin is left open in a background shell.
# Rule: EVERY headless agy call gets `< /dev/null` (or piped input) + a shell timeout.
STDIN_PROBE="$(timeout 25 agy -p 'Reply with exactly: STDIN-OK' < /dev/null 2>/dev/null || true)"
if printf '%s' "$STDIN_PROBE" | grep -q 'STDIN-OK'; then
  ok "stdin-guarded headless call works (< /dev/null)"
else
  warn "stdin-guarded probe failed — agy headless path broken (auth/network?); see task #135"
  DRIFT=1
fi
echo

if [ "$DRIFT" -eq 1 ] && [ "$STRICT" -eq 1 ]; then
  err "drift detected and --strict set"
  exit 3
fi
printf "verify-agy-install.sh: done (drift=%s)\n" "$DRIFT"
exit 0
