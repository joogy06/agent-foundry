#!/usr/bin/env bash
# Install the secrets pre-commit hook into the current repo.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/pre-commit"
dst="$root/.git/hooks/pre-commit"
if [ -e "$dst" ] && ! grep -q "secrets-scan.py --staged\|secrets-scan.py \"\$repo_root\" --staged" "$dst" 2>/dev/null; then
  cp "$dst" "$dst.bak-$(date -u +%Y%m%dT%H%M%SZ)"
  echo "existing pre-commit backed up to $dst.bak-*"
fi
# Refuse to install an inert hook. A pre-commit that silently skips is worse than
# none: it advertises enforcement that does not exist.
scanner=""
for c in "$root/scripts/secrets-scan.py" \
         "$HOME/.claude/skills/secret-scanning/scripts/secrets-scan.py"; do
  [ -f "$c" ] && { scanner="$c"; break; }
done
if [ -z "$scanner" ]; then
  echo "REFUSING TO INSTALL: no secrets-scan.py found." >&2
  echo "  looked in: $root/scripts/ and ~/.claude/skills/secret-scanning/scripts/" >&2
  echo "  An inert hook would claim protection it cannot provide." >&2
  exit 1
fi

cp "$src" "$dst"; chmod +x "$dst"
echo "installed: $dst"
echo "scanner:   $scanner"
