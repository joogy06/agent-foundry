#!/usr/bin/env bash
# stage_to_public.sh — GENERIC, gated "scrub then publish" driver (bring-your-own scrub list).
#
# The publishable companion to publish_prep.py: it takes a scrubbed staging dir,
# HARD-GATES on the forbidden-pattern verify (so a leak can never reach the public
# repo), mirrors it into your public repo, shows the diff, and — only after you
# confirm — commits and pushes.
#
# This contains NO project-specific logic and NO private strings (HARD-RULE). All
# your private rules — what to scrub, what to forbid, what to exclude — live in YOUR
# OWN publish-config.json (start from templates/publish-config.example.json). The
# framework is shared; the scrub list is yours.
#
# Usage:
#   ./stage_to_public.sh [STAGING_DIR] [--repo-root PATH] [--yes]
#
#   STAGING_DIR   a dir produced by publish_prep.py (default: newest /tmp/claude-skills-public-*)
#   --repo-root   your public repo clone (default: $PUBLIC_REPO_ROOT env)
#   --yes         skip the confirm prompt (for CI; the scrub gate still runs)
#
# Exit codes: 0 ok / 1 usage or env error / 2 SCRUB GATE FAILED (leak — refused to publish)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLISH_PREP="$SCRIPT_DIR/publish_prep.py"

STAGING_DIR=""
REPO_ROOT="${PUBLIC_REPO_ROOT:-}"
ASSUME_YES=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-root) REPO_ROOT="$2"; shift 2 ;;
        --yes|-y)    ASSUME_YES=1; shift ;;
        -*)          echo "ERROR: unknown flag $1" >&2; exit 1 ;;
        *)           STAGING_DIR="$1"; shift ;;
    esac
done

if [[ -z "$REPO_ROOT" ]]; then
    echo "ERROR: no target repo. Pass --repo-root PATH or set PUBLIC_REPO_ROOT." >&2
    exit 1
fi
if [[ ! -d "$REPO_ROOT/.git" ]]; then
    echo "ERROR: $REPO_ROOT is not a git repo. Clone your public repo first." >&2
    exit 1
fi
if [[ -z "$STAGING_DIR" ]]; then
    STAGING_DIR=$(ls -dt /tmp/claude-skills-public-* 2>/dev/null | head -1 || true)
fi
if [[ -z "$STAGING_DIR" || ! -d "$STAGING_DIR" ]]; then
    echo "ERROR: no staging dir. Run publish_prep.py first (or pass STAGING_DIR)." >&2
    exit 1
fi

echo "=== Stage to public ==="
echo "  Staging:  $STAGING_DIR"
echo "  Repo:     $REPO_ROOT"
echo ""

# ---------------------------------------------------------------------------
# SCRUB GATE — the headline safety net. publish_prep's verify can FAIL while
# still leaving a staging dir on disk; publishing it anyway is exactly how a leak
# reaches a public repo. We re-verify here and HARD-ABORT if anything remains.
# ---------------------------------------------------------------------------
if [[ -f "$PUBLISH_PREP" ]]; then
    echo "=== Scrub gate: verify staging has no forbidden patterns ==="
    if ! python3 "$PUBLISH_PREP" --verify "$STAGING_DIR"; then
        echo "" >&2
        echo "ERROR: scrub gate FAILED — staging contains forbidden patterns." >&2
        echo "       Refusing to publish a leak. Fix the source, or add a scrub rule /" >&2
        echo "       exclusion / forbidden_pattern to YOUR publish-config.json, regenerate" >&2
        echo "       staging, and re-run." >&2
        exit 2
    fi
else
    echo "ERROR: publish_prep.py not found next to this script — cannot run the scrub gate." >&2
    exit 1
fi

# Mirror staging -> public repo (delete files no longer in staging).
rsync -av --delete --exclude='.git' --exclude='.gitignore' "$STAGING_DIR/" "$REPO_ROOT/"

cd "$REPO_ROOT"
CHANGED=$(git status --porcelain | wc -l)
if [[ "$CHANGED" -eq 0 ]]; then
    echo "No changes — public repo already up to date."
    exit 0
fi
echo ""
echo "=== Changes ($CHANGED) ==="
git status --short
echo ""
git diff --stat || true
echo ""

if [[ "$ASSUME_YES" -ne 1 ]]; then
    read -p "Commit and push these changes? [y/N] " -n 1 -r; echo ""
    [[ "$REPLY" =~ ^[Yy]$ ]] || { echo "Aborted. Changes staged in $REPO_ROOT but not committed."; exit 0; }
fi

git add -A
git commit -m "Publish: scrubbed skills/agents update ($(date -u +'%Y-%m-%d %H:%M UTC'))"
git push origin "$(git branch --show-current)"
echo ""
echo "=== Published to $REPO_ROOT ==="
