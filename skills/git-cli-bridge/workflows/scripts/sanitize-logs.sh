#!/usr/bin/env bash
# sanitize-logs.sh — M23 log scrubber.
#
# Reads stdin, strips ANSI escapes + applies scrub-secrets.sh patterns,
# writes to stdout. Used by process-request.sh to sanitize CLI stdout/stderr
# before writing to logs/.

set -euo pipefail

# ANSI strip then pipe into scrub-secrets inline. The inline sed expressions
# mirror scrub-secrets.sh but operate on streams instead of files.
REDACTED="[REDACTED-BRIDGE]"
sed -E '
  s/\x1b\[[0-9;]*[a-zA-Z]//g
  s/AIza[0-9A-Za-z_\-]{35}/'"$REDACTED"'/g
  s/sk-[A-Za-z0-9]{20,}/'"$REDACTED"'/g
  s/github_pat_[A-Za-z0-9_]{22,}/'"$REDACTED"'/g
  s/ghp_[A-Za-z0-9]{36}/'"$REDACTED"'/g
  s/gho_[A-Za-z0-9]{36}/'"$REDACTED"'/g
  s/ghu_[A-Za-z0-9]{36}/'"$REDACTED"'/g
  s/ghs_[A-Za-z0-9]{36}/'"$REDACTED"'/g
  s/xoxb-[A-Za-z0-9\-]{20,}/'"$REDACTED"'/g
  s/Bearer [A-Za-z0-9._\-]{20,}/Bearer '"$REDACTED"'/g
' | tr -d '\000-\010\013\014\016-\037\177'
