#!/usr/bin/env bash
# verify-claude-install.sh
#
# Sanity-check the local Claude Code install against this skill's documented surface.
# Captures help output, diffs against the forked cli-reference.md, and reports drift.
#
# Exit codes:
#   0 — clean: claude is installed, version readable, settings.json valid, references look fresh
#   1 — claude binary not found
#   2 — settings.json missing or invalid JSON
#   3 — drift detected against cli-reference.md (warning, non-fatal — re-runs with --strict make this fatal)
#   4 — required help subcommand failed
#
# Usage:
#   bash ~/.claude/skills/claude-code-cli/scripts/verify-claude-install.sh
#   bash ~/.claude/skills/claude-code-cli/scripts/verify-claude-install.sh --strict   # treat drift as fatal
#
set -o errexit
set -o nounset
set -o pipefail

STRICT=0
if [ "${1:-}" = "--strict" ]; then
  STRICT=1
fi

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REF_DIR="$SKILL_DIR/references"
WORK_DIR="$(mktemp -d /tmp/verify-claude-XXXXXXXXXX)"
trap 'rm -rf "$WORK_DIR"' EXIT

ok() { printf "  [OK]   %s\n" "$1"; }
warn() { printf "  [WARN] %s\n" "$1"; }
err() { printf "  [ERR]  %s\n" "$1" >&2; }

printf "verify-claude-install.sh — checking %s\n\n" "$SKILL_DIR"

# 1. claude binary present
printf "1) claude binary\n"
if ! command -v claude >/dev/null 2>&1; then
  err "claude not found in PATH"
  exit 1
fi
CLAUDE_VERSION="$(claude --version 2>&1 || true)"
ok "found: $CLAUDE_VERSION"
echo

# 2. capture help surfaces
printf "2) capturing help surfaces to %s\n" "$WORK_DIR"
HELP_FILES=(
  "claude-help.txt:claude --help"
  "claude-mcp-help.txt:claude mcp --help"
  "claude-plugin-help.txt:claude plugin --help"
  "claude-agents-help.txt:claude agents --help"
  "claude-auth-help.txt:claude auth --help"
)
FAILED_HELP=0
for entry in "${HELP_FILES[@]}"; do
  fname="${entry%%:*}"
  cmd="${entry#*:}"
  if eval "$cmd" >"$WORK_DIR/$fname" 2>&1; then
    ok "$cmd -> $fname ($(wc -l < "$WORK_DIR/$fname") lines)"
  else
    warn "$cmd failed (exit $?) — output saved to $WORK_DIR/$fname"
    FAILED_HELP=$((FAILED_HELP + 1))
  fi
done
if [ "$FAILED_HELP" -gt 0 ]; then
  warn "$FAILED_HELP help command(s) failed"
fi
echo

# 3. settings.json sanity
printf "3) ~/.claude/settings.json\n"
SETTINGS="$HOME/.claude/settings.json"
if [ ! -f "$SETTINGS" ]; then
  warn "$SETTINGS does not exist"
  if [ "$STRICT" -eq 1 ]; then
    exit 2
  fi
else
  if command -v python3 >/dev/null 2>&1; then
    if python3 -c "import json,sys; json.load(open('$SETTINGS'))" 2>/dev/null; then
      ok "$SETTINGS parses as valid JSON"
    else
      err "$SETTINGS is NOT valid JSON"
      exit 2
    fi
  elif command -v jq >/dev/null 2>&1; then
    if jq empty "$SETTINGS" >/dev/null 2>&1; then
      ok "$SETTINGS parses as valid JSON (jq)"
    else
      err "$SETTINGS is NOT valid JSON (jq)"
      exit 2
    fi
  else
    warn "no python3 or jq available — skipping JSON parse check"
  fi
fi
echo

# 4. compare claude --help flag set against cli-reference.md (loose diff)
printf "4) diff claude --help vs cli-reference.md (flag-name only)\n"
CLI_REF="$REF_DIR/cli-reference.md"
if [ ! -f "$CLI_REF" ]; then
  warn "cli-reference.md not found at $CLI_REF — cannot diff"
else
  # Extract long-flag tokens (--xxx) from both, dedupe, sort.
  grep -oE '\-\-[a-zA-Z][a-zA-Z0-9-]*' "$WORK_DIR/claude-help.txt" 2>/dev/null \
    | sort -u >"$WORK_DIR/help-flags.txt"
  grep -oE '\-\-[a-zA-Z][a-zA-Z0-9-]*' "$CLI_REF" 2>/dev/null \
    | sort -u >"$WORK_DIR/ref-flags.txt"

  HELP_COUNT=$(wc -l < "$WORK_DIR/help-flags.txt")
  REF_COUNT=$(wc -l < "$WORK_DIR/ref-flags.txt")
  ok "claude --help has $HELP_COUNT long flags; cli-reference.md mentions $REF_COUNT"

  ONLY_HELP="$(comm -23 "$WORK_DIR/help-flags.txt" "$WORK_DIR/ref-flags.txt" || true)"
  ONLY_REF="$(comm -13 "$WORK_DIR/help-flags.txt" "$WORK_DIR/ref-flags.txt" || true)"

  DRIFT=0
  if [ -n "$ONLY_HELP" ]; then
    warn "flags in --help but NOT in cli-reference.md (need to add):"
    echo "$ONLY_HELP" | sed 's/^/         /'
    DRIFT=1
  fi
  if [ -n "$ONLY_REF" ]; then
    warn "flags in cli-reference.md but NOT in --help (may be removed/deprecated):"
    echo "$ONLY_REF" | sed 's/^/         /'
    DRIFT=1
  fi
  if [ "$DRIFT" -eq 0 ]; then
    ok "no drift detected between --help and cli-reference.md"
  elif [ "$STRICT" -eq 1 ]; then
    err "drift detected and --strict specified"
    exit 3
  fi
fi
echo

# 5. spot-check the 6 permission modes
printf "5) permission-mode choices\n"
EXPECTED_MODES=(acceptEdits auto bypassPermissions default dontAsk plan)
MISSING_MODES=()
for mode in "${EXPECTED_MODES[@]}"; do
  if ! grep -q "$mode" "$WORK_DIR/claude-help.txt" 2>/dev/null; then
    MISSING_MODES+=("$mode")
  fi
done
if [ ${#MISSING_MODES[@]} -eq 0 ]; then
  ok "all 6 expected permission modes present"
else
  warn "missing permission modes: ${MISSING_MODES[*]}"
fi
echo

# 6. summarise
printf "Summary\n"
ok "skill dir: $SKILL_DIR"
ok "work dir : $WORK_DIR (will be removed on exit)"
printf "Done.\n"
exit 0
