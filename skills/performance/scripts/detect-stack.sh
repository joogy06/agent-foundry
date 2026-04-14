#!/usr/bin/env bash
# detect-stack.sh
#
# Thin wrapper around ~/.claude/skills/project-documentation/context-detection.md.
# Use this ONLY when the performance skill is invoked by a non-context-aware
# caller (a CI script, an external tool, or any flow that bypasses the normal
# Claude Code session). Inside a normal session, the hosting agent should read
# context-detection.md directly and pass a ready-made context report to the
# performance skill.
#
# This script does NOT parse package manifests, import graphs, or PROJECT.md.
# It simply collects the signals context-detection.md expects, prints them as
# lines of `key=value` on stdout, and exits. The caller (agent or downstream
# script) must still run the classification logic from context-detection.md.
#
# Output contract (one key=value per line, stdout):
#   project_root=<absolute path>
#   project_md_present=true|false
#   component_md_count=<integer>
#   package_manifest=<filename or "none">
#   session_id=<value of CLAUDE_SESSION_ID or "unknown">
#   detection_hint=read ~/.claude/skills/project-documentation/context-detection.md
#
# Exit codes:
#   0 — signals emitted
#   1 — no readable project root
#
# Usage:
#   bash detect-stack.sh [project_root]
#   bash detect-stack.sh                 # uses CWD
#   bash detect-stack.sh /path/to/proj

set -o errexit
set -o nounset
set -o pipefail

ROOT="${1:-$PWD}"
if [ ! -d "$ROOT" ]; then
  printf "detect-stack.sh: not a directory: %s\n" "$ROOT" >&2
  exit 1
fi

ROOT_ABS="$(cd "$ROOT" && pwd)"

# Signal 1: PROJECT.md present?
if [ -f "$ROOT_ABS/PROJECT.md" ]; then
  PROJ_PRESENT=true
else
  PROJ_PRESENT=false
fi

# Signal 2: how many COMPONENT.md files under docs/components/?
COMP_COUNT=0
if [ -d "$ROOT_ABS/docs/components" ]; then
  # Use find with -print | wc -l for portability across gnu/bsd find.
  COMP_COUNT=$(find "$ROOT_ABS/docs/components" -type f -name 'COMPONENT.md' -print 2>/dev/null | wc -l | tr -d ' ')
fi

# Signal 3: which package manifest is present (first hit wins).
PKG_MANIFEST=none
for candidate in package.json pyproject.toml requirements.txt go.mod composer.json Cargo.toml pom.xml build.gradle Gemfile mix.exs; do
  if [ -f "$ROOT_ABS/$candidate" ]; then
    PKG_MANIFEST="$candidate"
    break
  fi
done

# Signal 4: session id if the caller exported one.
SESSION="${CLAUDE_SESSION_ID:-${FORGE_SESSION_ID:-unknown}}"

printf "project_root=%s\n" "$ROOT_ABS"
printf "project_md_present=%s\n" "$PROJ_PRESENT"
printf "component_md_count=%s\n" "$COMP_COUNT"
printf "package_manifest=%s\n" "$PKG_MANIFEST"
printf "session_id=%s\n" "$SESSION"
printf "detection_hint=read ~/.claude/skills/project-documentation/context-detection.md\n"
