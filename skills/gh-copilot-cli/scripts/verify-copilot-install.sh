#!/usr/bin/env bash
# verify-copilot-install.sh
#
# Sanity-check the local GitHub Copilot CLI install against this skill's documented surface.
# Captures help output, verifies subcommands and key flags, checks auth state.
#
# Exit codes:
#   0 — clean
#   1 — copilot binary not found
#   2 — version cannot be read
#   3 — required subcommand missing
#   4 — required flag missing
#
# Usage:
#   bash ~/.claude/skills/gh-copilot-cli/scripts/verify-copilot-install.sh
#
set -o errexit
set -o nounset
set -o pipefail

WORK_DIR="$(mktemp -d /tmp/verify-copilot-XXXXXXXXXX)"
trap 'rm -rf "$WORK_DIR"' EXIT

ok() { printf "  [OK]   %s\n" "$1"; }
warn() { printf "  [WARN] %s\n" "$1"; }
err() { printf "  [ERR]  %s\n" "$1" >&2; }

printf "verify-copilot-install.sh\n\n"

# 1. binary present
printf "1) copilot binary\n"
if ! command -v copilot >/dev/null 2>&1; then
  err "copilot not found in PATH"
  warn "Install with: npm install -g @github/copilot"
  warn "Or user-prefix: npm install --prefix ~/.npm-global @github/copilot"
  exit 1
fi
COPILOT_VERSION="$(copilot --version 2>&1 || echo "unknown")"
if [ "$COPILOT_VERSION" = "unknown" ]; then
  err "could not read copilot version"
  exit 2
fi
ok "found: copilot $COPILOT_VERSION"
echo

# 2. capture help
printf "2) capturing help surfaces to %s\n" "$WORK_DIR"
HELP_FILES=(
  "copilot-help.txt:copilot --help"
  "copilot-mcp-help.txt:copilot mcp --help"
  "copilot-login-help.txt:copilot login --help"
  "copilot-init-help.txt:copilot init --help"
)
for entry in "${HELP_FILES[@]}"; do
  fname="${entry%%:*}"
  cmd="${entry#*:}"
  if eval "$cmd" >"$WORK_DIR/$fname" 2>&1; then
    ok "$cmd -> $fname ($(wc -l < "$WORK_DIR/$fname") lines)"
  else
    warn "$cmd failed"
  fi
done
echo

# 3. required subcommands
printf "3) required subcommands\n"
EXPECTED_SUBCMDS=(init login mcp plugin update version help)
MISSING_SUBCMDS=()
for sub in "${EXPECTED_SUBCMDS[@]}"; do
  if ! grep -qE "^\s+$sub" "$WORK_DIR/copilot-help.txt" 2>/dev/null; then
    MISSING_SUBCMDS+=("$sub")
  fi
done
if [ ${#MISSING_SUBCMDS[@]} -eq 0 ]; then
  ok "all expected subcommands present: ${EXPECTED_SUBCMDS[*]}"
else
  err "missing subcommands: ${MISSING_SUBCMDS[*]}"
  exit 3
fi
echo

# 4. required key flags
printf "4) required key flags\n"
EXPECTED_FLAGS=(
  "--prompt"
  "--allow-all-tools"
  "--yolo"
  "--autopilot"
  "--output-format"
  "--continue"
  "--resume"
  "--add-dir"
  "--model"
  "--no-custom-instructions"
  "--acp"
  "--silent"
)
MISSING_FLAGS=()
for flag in "${EXPECTED_FLAGS[@]}"; do
  if ! grep -qF -e "$flag" "$WORK_DIR/copilot-help.txt" 2>/dev/null; then
    MISSING_FLAGS+=("$flag")
  fi
done
if [ ${#MISSING_FLAGS[@]} -eq 0 ]; then
  ok "all expected key flags present (${#EXPECTED_FLAGS[@]} flags)"
else
  err "missing key flags: ${MISSING_FLAGS[*]}"
  exit 4
fi
echo

# 5. mcp subcommands
printf "5) copilot mcp subcommands\n"
EXPECTED_MCP=(add get list remove)
for sub in "${EXPECTED_MCP[@]}"; do
  if grep -qE "^\s+$sub" "$WORK_DIR/copilot-mcp-help.txt" 2>/dev/null; then
    ok "copilot mcp $sub"
  else
    warn "copilot mcp $sub MISSING"
  fi
done
echo

# 6. auth state
printf "6) auth state hints\n"
AUTH_FOUND=0
if [ -n "${COPILOT_GITHUB_TOKEN:-}" ]; then
  ok "COPILOT_GITHUB_TOKEN is set (highest precedence)"
  AUTH_FOUND=1
fi
if [ -n "${GH_TOKEN:-}" ]; then
  ok "GH_TOKEN is set"
  AUTH_FOUND=1
fi
if [ -n "${GITHUB_TOKEN:-}" ]; then
  ok "GITHUB_TOKEN is set"
  AUTH_FOUND=1
fi
if [ -d "$HOME/.copilot" ]; then
  ok "~/.copilot/ config dir exists"
  AUTH_FOUND=1
fi
if [ "$AUTH_FOUND" -eq 0 ]; then
  warn "no auth env vars and no ~/.copilot/ — run 'copilot login' to authenticate"
fi
echo

# 7. config dir
printf "7) ~/.copilot config\n"
if [ -d "$HOME/.copilot" ]; then
  ok "$HOME/.copilot exists"
  if [ -f "$HOME/.copilot/mcp-config.json" ]; then
    if command -v python3 >/dev/null 2>&1; then
      if python3 -c "import json,sys; json.load(open('$HOME/.copilot/mcp-config.json'))" 2>/dev/null; then
        ok "mcp-config.json is valid JSON"
      else
        err "mcp-config.json is NOT valid JSON"
      fi
    fi
  else
    warn "mcp-config.json not present (ok if no MCP servers added)"
  fi
else
  warn "$HOME/.copilot does not exist (will be created on first run)"
fi
echo

# 8. summary
printf "Summary\n"
ok "version: $COPILOT_VERSION"
ok "subcommands: ${#EXPECTED_SUBCMDS[@]} verified"
ok "key flags  : ${#EXPECTED_FLAGS[@]} verified"
ok "work dir   : $WORK_DIR (will be removed on exit)"
printf "Done.\n"
exit 0
