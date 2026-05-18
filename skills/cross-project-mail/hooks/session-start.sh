#!/usr/bin/env bash
# cross-project-mail SessionStart hook
# Budget: <100ms. Pure directory listing, no parsing.
# Wired via ~/.claude/settings.json hooks.SessionStart (and Codex/Gemini parity symlinks).
set -e

MAILBOX="${AI_MAILBOX:-$HOME/.ai-mailbox}"
CPMAIL="${CPMAIL_BIN:-cpmail}"

# Resolve current project (silent on failure — we exit 0)
PROJECT=$("$CPMAIL" _detect-project 2>/dev/null || true)
[[ -z "$PROJECT" ]] && exit 0

INBOX="$MAILBOX/inbox/$PROJECT"
[[ ! -d "$INBOX" ]] && exit 0

# Count *.md files directly under $INBOX (does NOT recurse into .acked/)
UNREAD=$(find "$INBOX" -maxdepth 1 -name '*.md' -type f 2>/dev/null | wc -l | tr -d ' ')
[[ "$UNREAD" -gt 0 ]] && echo "[mail] $UNREAD unread for $PROJECT (run: $CPMAIL list --unread)"
exit 0
