#!/usr/bin/env bash
# cross-project-mail installer (v1, M1)
# Idempotent: safe to re-run. Does not modify ~/.claude/settings.json — the
# SessionStart hook wiring is left as a manual step (see end of script) so we
# don't accidentally touch user-managed config.
set -e

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
MAILBOX="${AI_MAILBOX:-$HOME/.ai-mailbox}"

echo "cross-project-mail installer (v1, M1)"
echo "  skill dir: $SKILL_DIR"
echo "  bin dir:   $BIN_DIR"
echo "  mailbox:   $MAILBOX"

# --- Check pyyaml
if ! python3 -c "import yaml" 2>/dev/null; then
  echo
  echo "ERROR: pyyaml not available. Install with:"
  echo "  python3 -m pip install --user pyyaml"
  exit 1
fi

# --- Install cpmail binary
mkdir -p "$BIN_DIR"
TARGET="$BIN_DIR/cpmail"
SRC="$SKILL_DIR/scripts/cpmail"
if [[ ! -x "$SRC" ]]; then
  chmod +x "$SRC"
fi
if [[ -L "$TARGET" && "$(readlink -f "$TARGET")" == "$(readlink -f "$SRC")" ]]; then
  echo "  cpmail: already linked"
else
  ln -sf "$SRC" "$TARGET"
  echo "  cpmail: linked $TARGET -> $SRC"
fi

# --- Initialise mailbox layout
mkdir -p "$MAILBOX/inbox" "$MAILBOX/outbox"
chmod 0700 "$MAILBOX"
echo "  mailbox: initialised $MAILBOX"

# --- SessionStart hook wiring (manual; print instructions)
HOOK_SRC="$SKILL_DIR/hooks/session-start.sh"
chmod +x "$HOOK_SRC"

echo
echo "Install complete."
echo
echo "Verify: cpmail doctor"
echo
echo "To enable the SessionStart notification in Claude Code, add to ~/.claude/settings.json:"
echo
cat <<EOF
  {
    "hooks": {
      "SessionStart": [
        { "command": "bash $HOOK_SRC" }
      ]
    }
  }
EOF
echo
echo "Codex parity (optional): symlink the same hook into ~/.codex/hooks/session-start.sh"
echo "  mkdir -p ~/.codex/hooks && ln -sf $HOOK_SRC ~/.codex/hooks/session-start.sh"
echo
echo "Gemini parity (optional): see ~/.gemini hook configuration."
echo
echo "PATH check: \$BIN_DIR ($BIN_DIR) must be on \$PATH for 'cpmail' to resolve."
case ":$PATH:" in
  *":$BIN_DIR:"*) echo "  $BIN_DIR is on PATH" ;;
  *) echo "  WARNING: $BIN_DIR is NOT on PATH. Add to ~/.bashrc or ~/.zshrc:"
     echo "    export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
