#!/bin/sh
# pre-commit-msosec.sh — POSIX pre-commit hook (advisory)
#
# Install:
#   cp ~/.claude/skills/ms-office-security-python/ms_office_security_check/pre-commit-msosec.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# Behavior:
# - Detects staged .py files
# - If none staged: exit 0
# - Otherwise: runs ms_office_security_check in advisory mode
# - NEVER passes --mode strict (that's for opt-in CI / future G_MSOSEC gate)
# - Mirrors dep-currency-check's exit-code mapping (0/1/2/3).
set -eu

PY=""
for cand in python3 python py; do
    if command -v "$cand" >/dev/null 2>&1; then
        PY="$cand"; break
    fi
done
if [ -z "$PY" ]; then
    echo "pre-commit-msosec: python3 not found on PATH; skipping check" >&2
    exit 0
fi

CHANGED=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.py$' || true)
if [ -z "$CHANGED" ]; then
    exit 0
fi

REPO_ROOT=$(git rev-parse --show-toplevel)
SKILL_DIR="${MSOSEC_SKILL_DIR:-$HOME/.claude/skills/ms-office-security-python}"
if [ ! -d "$SKILL_DIR" ]; then
    echo "pre-commit-msosec: skill dir not found ($SKILL_DIR); skipping" >&2
    exit 0
fi

CHANGED_LIST=$(echo "$CHANGED" | tr '\n' ',' | sed 's/,$//')

PYTHONPATH="$SKILL_DIR:${PYTHONPATH:-}" "$PY" -m ms_office_security_check "$REPO_ROOT" \
    --changed-files "$CHANGED_LIST" \
    --severity high \
    --format md \
    --quiet \
    || EXIT=$?

EXIT=${EXIT:-0}

case "$EXIT" in
    0) exit 0 ;;
    1) echo "pre-commit-msosec: STRICT BLOCK (unexpected in advisory mode)" >&2; exit 1 ;;
    2) echo "pre-commit-msosec: advisory findings present (commit allowed)" >&2; exit 0 ;;
    3) echo "pre-commit-msosec: environmental error; allowing commit" >&2; exit 0 ;;
    *) echo "pre-commit-msosec: unexpected exit $EXIT; allowing commit" >&2; exit 0 ;;
esac
