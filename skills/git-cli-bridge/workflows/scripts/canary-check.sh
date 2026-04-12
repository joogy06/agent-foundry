#!/usr/bin/env bash
# canary-check.sh — M6 canary detection.
#
# Usage: canary-check.sh <file>
#
# Reads BRIDGE_CANARY from the environment. If the canary value appears in
# <file>, the CLI exfiltrated env vars — exit 0 (BAD, detected).
# If the canary value does NOT appear, exit 1 (GOOD, clean).
#
# The workflow treats exit 0 as a canary detection event and sets
# status.state = canary_detected, skipping the response commit.

set -euo pipefail
FILE="${1:?usage: canary-check.sh <file>}"
[ -f "$FILE" ] || { echo "file not found: $FILE" >&2; exit 2; }

if [ -z "${BRIDGE_CANARY:-}" ]; then
  echo "canary-check.sh: BRIDGE_CANARY env var not set" >&2
  exit 2
fi

# Fixed-string grep; bail on first match.
if grep -F -q -- "$BRIDGE_CANARY" "$FILE"; then
  echo "CANARY DETECTED in $FILE" >&2
  exit 0
fi
exit 1
