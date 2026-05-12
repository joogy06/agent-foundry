#!/bin/sh
# pre-commit-dep-currency.sh — POSIX pre-commit hook (advisory)
#
# Install:
#   cp ~/.claude/skills/dep-currency-check/scripts/pre-commit-dep-currency.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# Behavior:
# - Detects staged manifest/lockfile changes
# - If none staged: exit 0 immediately
# - Otherwise: runs dep-currency-check in advisory mode
# - Never passes --mode strict (that's for the G_DEP_CURRENCY gate only)
set -eu

# Find python3 (try python3, python, py)
PY=""
for cand in python3 python py; do
    if command -v "$cand" >/dev/null 2>&1; then
        PY="$cand"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "pre-commit-dep-currency: python3 not found on PATH; skipping check" >&2
    exit 0
fi

# Collect changed manifests
CHANGED=$(git diff --cached --name-only --diff-filter=ACM | \
  grep -E '(package\.json|pyproject\.toml|requirements[^/]*\.txt|Cargo\.toml|go\.mod|Gemfile|pom\.xml|build\.gradle.*|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|go\.sum|Gemfile\.lock)$' || true)

if [ -z "$CHANGED" ]; then
    exit 0
fi

REPO_ROOT=$(git rev-parse --show-toplevel)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Determine the skill's Python module path
SKILL_DIR="${DEP_CURRENCY_SKILL_DIR:-$HOME/.claude/skills/dep-currency-check/scripts}"
if [ ! -d "$SKILL_DIR" ]; then
    echo "pre-commit-dep-currency: skill dir not found ($SKILL_DIR); skipping" >&2
    exit 0
fi

# Comma-separate CHANGED for --changed-manifests
CHANGED_LIST=$(echo "$CHANGED" | tr '\n' ',' | sed 's/,$//')

# Run advisory check (NO --mode strict)
PYTHONPATH="$SKILL_DIR/..:${PYTHONPATH:-}" "$PY" -m dep_currency_check "$REPO_ROOT" \
    --changed-manifests "$CHANGED_LIST" \
    --severity critical \
    --format json \
    --quiet \
    --render markdown \
    || EXIT=$?

EXIT=${EXIT:-0}

# Exit codes:
# 0 = clean
# 1 = strict block (not possible since we didn't pass --mode strict)
# 2 = soft finding — advisory only; do NOT block commit
# 3 = environmental — print warning, allow commit
# 4 = offline + cold cache — allow commit
case "$EXIT" in
    0) exit 0 ;;
    1) echo "pre-commit-dep-currency: STRICT BLOCK (should not happen in advisory mode)" >&2; exit 1 ;;
    2) echo "pre-commit-dep-currency: advisory findings present (commit allowed)" >&2; exit 0 ;;
    3) echo "pre-commit-dep-currency: environmental error; allowing commit" >&2; exit 0 ;;
    4) echo "pre-commit-dep-currency: offline + cold cache; allowing commit" >&2; exit 0 ;;
    *) echo "pre-commit-dep-currency: unexpected exit $EXIT; allowing commit" >&2; exit 0 ;;
esac
