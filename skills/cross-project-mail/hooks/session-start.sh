#!/usr/bin/env bash
# cross-project-mail SessionStart hook (POSIX entry point).
# Kept as a file because its command string is the dedup identity in
# ~/.claude/settings.json; the behaviour lives in session_start.py, which this
# execs, so the two entry points cannot drift. Always exits 0.

SRC="${BASH_SOURCE[0]}"
# Follow symlinks (Codex parity installs link this file elsewhere).
while [ -L "$SRC" ]; do
  DIR="$(cd -P "$(dirname "$SRC")" 2>/dev/null && pwd)" || exit 0
  SRC="$(readlink "$SRC")"
  case "$SRC" in /*) ;; *) SRC="$DIR/$SRC" ;; esac
done
HERE="$(cd -P "$(dirname "$SRC")" 2>/dev/null && pwd)" || exit 0

PY="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)" || exit 0
[ -n "$PY" ] || exit 0
exec "$PY" "$HERE/session_start.py"
