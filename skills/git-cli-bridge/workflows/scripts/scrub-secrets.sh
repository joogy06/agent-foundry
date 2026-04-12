#!/usr/bin/env bash
# scrub-secrets.sh — M5 regex scrubber.
#
# Usage: scrub-secrets.sh <file>
#
# In-place sed-based redaction of known secret patterns. Exit 0 on success.
# Fail-open by default (a scrubbed file is still committed); emit a warning on
# stderr if any redaction occurred so the workflow can annotate response.md
# with a warnings[] entry.
#
# SEC-4. Paired with canary-check.sh (M6) for env-var exfiltration.

set -euo pipefail
FILE="${1:?usage: scrub-secrets.sh <file>}"
[ -f "$FILE" ] || { echo "file not found: $FILE" >&2; exit 1; }

REDACTED="[REDACTED-BRIDGE]"

# Pattern definitions. Each is a sed -E expression.
patterns=(
  # Google API key: AIza followed by 35 base64url chars.
  's/AIza[0-9A-Za-z_\-]{35}/'"$REDACTED"'/g'
  # OpenAI key: sk- followed by 20+ chars.
  's/sk-[A-Za-z0-9]{20,}/'"$REDACTED"'/g'
  # GitHub fine-grained PAT.
  's/github_pat_[A-Za-z0-9_]{22,}/'"$REDACTED"'/g'
  # GitHub classic PAT.
  's/ghp_[A-Za-z0-9]{36}/'"$REDACTED"'/g'
  # GitHub OAuth token.
  's/gho_[A-Za-z0-9]{36}/'"$REDACTED"'/g'
  # GitHub user-to-server token.
  's/ghu_[A-Za-z0-9]{36}/'"$REDACTED"'/g'
  # GitHub server-to-server token.
  's/ghs_[A-Za-z0-9]{36}/'"$REDACTED"'/g'
  # Slack bot token.
  's/xoxb-[A-Za-z0-9\-]{20,}/'"$REDACTED"'/g'
  's/xoxp-[A-Za-z0-9\-]{20,}/'"$REDACTED"'/g'
  # Generic Bearer token (header-style).
  's/Bearer [A-Za-z0-9._\-]{20,}/Bearer '"$REDACTED"'/g'
  # PEM private key block: redact the entire body between markers.
  's#-----BEGIN [A-Z ]*PRIVATE KEY-----[^-]+-----END [A-Z ]*PRIVATE KEY-----#'"$REDACTED"'#g'
)

before_hash="$(sha256sum "$FILE" | awk '{print $1}')"
for pat in "${patterns[@]}"; do
  sed -i -E "$pat" "$FILE"
done
after_hash="$(sha256sum "$FILE" | awk '{print $1}')"

if [ "$before_hash" != "$after_hash" ]; then
  echo "WARN: scrub-secrets.sh redacted secret-shaped content in $FILE" >&2
fi
exit 0
