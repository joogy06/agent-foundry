#!/usr/bin/env bash
# verify-gemini-install.sh
#
# Sanity-check the local Gemini CLI install against this skill's documented surface.
# Captures help output, lists registered skills/extensions/MCP servers, sanity-checks
# settings.json, and reports auth state.
#
# Exit codes:
#   0 — clean
#   1 — gemini binary not found
#   2 — settings.json present but invalid JSON
#   3 — required subcommand missing or non-functional
#
# Usage:
#   bash ~/.claude/skills/gemini-cli/scripts/verify-gemini-install.sh
#
set -o errexit
set -o nounset
set -o pipefail

WORK_DIR="$(mktemp -d /tmp/verify-gemini-XXXXXXXXXX)"
trap 'rm -rf "$WORK_DIR"' EXIT

ok() { printf "  [OK]   %s\n" "$1"; }
warn() { printf "  [WARN] %s\n" "$1"; }
err() { printf "  [ERR]  %s\n" "$1" >&2; }

printf "verify-gemini-install.sh\n\n"

# 1. gemini binary present
printf "1) gemini binary\n"
if ! command -v gemini >/dev/null 2>&1; then
  err "gemini not found in PATH"
  exit 1
fi
GEMINI_VERSION="$(gemini --version 2>&1 || true)"
ok "found: gemini $GEMINI_VERSION"
echo

# 2. capture help surfaces
printf "2) capturing help surfaces to %s\n" "$WORK_DIR"
HELP_FILES=(
  "gemini-help.txt:gemini --help"
  "gemini-skills-help.txt:gemini skills --help"
  "gemini-extensions-help.txt:gemini extensions --help"
  "gemini-hooks-help.txt:gemini hooks --help"
  "gemini-mcp-help.txt:gemini mcp --help"
)
FAILED=0
for entry in "${HELP_FILES[@]}"; do
  fname="${entry%%:*}"
  cmd="${entry#*:}"
  if eval "$cmd" >"$WORK_DIR/$fname" 2>&1; then
    ok "$cmd -> $fname ($(wc -l < "$WORK_DIR/$fname") lines)"
  else
    warn "$cmd failed (exit $?) — output saved to $WORK_DIR/$fname"
    FAILED=$((FAILED + 1))
  fi
done
if [ "$FAILED" -gt 0 ]; then
  warn "$FAILED help command(s) failed"
fi
echo

# 3. verify gemini hooks migrate exists
printf "3) gemini hooks migrate subcommand\n"
if grep -q "migrate" "$WORK_DIR/gemini-hooks-help.txt" 2>/dev/null; then
  ok "'gemini hooks migrate' is present"
else
  err "'gemini hooks migrate' is MISSING — Gemini layout has changed"
  exit 3
fi
echo

# 4. list registered skills
printf "4) registered skills\n"
if gemini skills list >"$WORK_DIR/skills-list.txt" 2>&1; then
  COUNT=$(grep -cv '^$' "$WORK_DIR/skills-list.txt" || echo 0)
  ok "gemini skills list -> $COUNT line(s) of output"
  if [ "$COUNT" -gt 0 ]; then
    head -20 "$WORK_DIR/skills-list.txt" | sed 's/^/         /'
  fi
else
  warn "gemini skills list failed (likely no skills installed yet)"
fi
echo

# 5. list registered extensions
printf "5) registered extensions\n"
if gemini extensions list >"$WORK_DIR/extensions-list.txt" 2>&1; then
  COUNT=$(grep -cv '^$' "$WORK_DIR/extensions-list.txt" || echo 0)
  ok "gemini extensions list -> $COUNT line(s) of output"
  if [ "$COUNT" -gt 0 ]; then
    head -20 "$WORK_DIR/extensions-list.txt" | sed 's/^/         /'
  fi
else
  warn "gemini extensions list failed"
fi
echo

# 6. list MCP servers
printf "6) configured MCP servers\n"
if gemini mcp list >"$WORK_DIR/mcp-list.txt" 2>&1; then
  ok "gemini mcp list ran successfully"
  head -20 "$WORK_DIR/mcp-list.txt" | sed 's/^/         /'
else
  warn "gemini mcp list failed"
fi
echo

# 7. settings.json sanity
printf "7) ~/.gemini/settings.json\n"
SETTINGS="$HOME/.gemini/settings.json"
if [ ! -f "$SETTINGS" ]; then
  warn "$SETTINGS does not exist (Gemini will use defaults)"
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

# 8. auth state hint
printf "8) auth state hint\n"
if [ -n "${GOOGLE_GENAI_USE_VERTEXAI:-}" ]; then
  ok "GOOGLE_GENAI_USE_VERTEXAI is set -> Vertex flow expected"
elif [ -n "${GEMINI_API_KEY:-}" ]; then
  ok "GEMINI_API_KEY is set -> AI Studio key flow"
elif [ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]; then
  ok "GOOGLE_APPLICATION_CREDENTIALS is set -> service account flow"
else
  warn "no auth env vars detected -> OAuth personal flow expected (run 'gemini auth login' if not yet authenticated)"
fi
echo

printf "Summary\n"
ok "work dir: $WORK_DIR (will be removed on exit)"
printf "Done.\n"
exit 0
