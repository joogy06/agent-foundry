#!/usr/bin/env bash
# rotate_and_age.sh - Daily rotation + retention orchestration per design section 4.5.
#
# Usage:
#   rotate_and_age.sh <project_root>
#
# Steps:
#   1. Daily rotation: events.jsonl -> events-<YYYY-MM-DD>.jsonl
#   2. Compact events-*.jsonl files older than 30 days into summaries/<YYYY-MM>.jsonl
#   3. Run active.yaml -> stale.yaml sweep (14d age-out, resolved demotion)
#   4. Delete summaries older than 180 days
#
# Intended to be called from pa-server cron (03:00 local) or from a session-start
# hook. The 24h .last_sweep sentinel inside sweep.py keeps repeat calls cheap.

set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <project_root>" >&2
  exit 2
fi

PROJECT_ROOT="$1"
OBS_DIR="$PROJECT_ROOT/.process-observations"
TODAY="$(date -u +%Y-%m-%d)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$OBS_DIR/summaries"

# 1. Daily rotation (non-destructive; -n = no-overwrite).
if [ -f "$OBS_DIR/events.jsonl" ]; then
  mv -n "$OBS_DIR/events.jsonl" "$OBS_DIR/events-$TODAY.jsonl" || true
fi

# 2. Compact 30+ day raw events -> monthly summaries + delete.
python3 "$SCRIPT_DIR/compact_events.py" --project-root "$PROJECT_ROOT" || true

# 3. active.yaml -> stale.yaml sweep (14d age-out AND resolved).
python3 "$SCRIPT_DIR/sweep.py" --project-root "$PROJECT_ROOT" || true

# 4. Age out summaries older than 180 days (belt-and-suspenders; compact_events also does this).
find "$OBS_DIR/summaries" -name '*.jsonl' -mtime +180 -delete 2>/dev/null || true

exit 0
