#!/usr/bin/env bash
# install-pre-push-hook.sh — wire scripts/secrets-scan.sh as a pre-push hook.
#
# Idempotent: re-running replaces an existing hook only if it looks like ours
# (matches the marker comment); otherwise it backs up the existing hook to
# pre-push.bak first.
#
# Usage:
#   bash scripts/install-pre-push-hook.sh                  # bash scanner, $PWD
#   bash scripts/install-pre-push-hook.sh /path/to/repo    # bash scanner, target repo
#   bash scripts/install-pre-push-hook.sh --python         # use Python scanner (cross-platform)
#   bash scripts/install-pre-push-hook.sh --uninstall      # remove the hook
#
# Windows / cross-platform users: run scripts/install-pre-push-hook.py instead —
# pure-stdlib Python, works on enterprise laptops where PowerShell is blocked
# (Execution Policy / AppLocker / Constrained Language Mode) but Python runs:
#   python3 scripts/install-pre-push-hook.py --target-repo C:\path\to\repo

set -euo pipefail

MARKER="# managed-by: foundry-lab/scripts/install-pre-push-hook.sh"

ACTION=install
TARGET=""
USE_PYTHON=0
for arg in "$@"; do
    case "$arg" in
        --uninstall) ACTION=uninstall ;;
        --python) USE_PYTHON=1 ;;
        --help|-h) sed -n '2,18p' "$0"; exit 0 ;;
        -*) echo "ERROR: unknown flag: $arg" >&2; exit 2 ;;
        *) TARGET="$arg" ;;
    esac
done
TARGET="${TARGET:-$PWD}"

if [[ ! -d "$TARGET/.git" ]]; then
    echo "ERROR: $TARGET is not a git repository (no .git/)" >&2
    exit 2
fi

HOOK="$TARGET/.git/hooks/pre-push"

if [[ "$ACTION" == "uninstall" ]]; then
    if [[ -f "$HOOK" ]] && grep -q "$MARKER" "$HOOK"; then
        rm -f "$HOOK"
        echo "[uninstall] removed $HOOK"
    else
        echo "[uninstall] no managed hook at $HOOK (nothing to do)"
    fi
    exit 0
fi

# Install path. Detect existing non-managed hook and back it up.
if [[ -f "$HOOK" ]] && ! grep -q "$MARKER" "$HOOK"; then
    cp -p "$HOOK" "$HOOK.bak"
    echo "[backup] existing hook -> $HOOK.bak"
fi

# Resolve absolute path to scanner relative to this installer.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ $USE_PYTHON -eq 1 ]]; then
    SCANNER="$SCRIPT_DIR/secrets-scan.py"
else
    SCANNER="$SCRIPT_DIR/secrets-scan.sh"
fi

if [[ ! -x "$SCANNER" ]]; then
    chmod +x "$SCANNER" 2>/dev/null || true
fi

# Identity gate chained AHEAD of the secrets scan (avengers P2). Same dir as
# this installer; the generated hook runs it first (fail-closed on repo<->live
# drift), then the secrets scan.
IDENTITY_GATE="$SCRIPT_DIR/identity_gate.py"

if [[ $USE_PYTHON -eq 1 ]]; then
    cat > "$HOOK" <<EOF
#!/usr/bin/env bash
$MARKER
# Pre-push chain: identity gate (fail-closed on drift) -> secrets-scan.py.
# Override with: git push --no-verify

set -e

IDENTITY_GATE="$IDENTITY_GATE"
SCANNER="$SCANNER"
REPO_ROOT="\$(git rev-parse --show-toplevel)"

# --- 1. Identity gate: repo<->live _meta drift (fail CLOSED). Missing gate /
#        no python / environmental -> WARN and continue (never wedge a push). ---
if [ -f "\$IDENTITY_GATE" ]; then
    _IDPY=""
    for _p in python3 python py; do
        if command -v "\$_p" >/dev/null 2>&1; then _IDPY="\$_p"; break; fi
    done
    if [ -z "\$_IDPY" ]; then
        echo "[pre-push] WARN: no python for identity gate — skipping identity check" >&2
    else
        if [ "\$_IDPY" = "py" ]; then _IDPY="py -3"; fi
        if \$_IDPY "\$IDENTITY_GATE" --repo-root "\$REPO_ROOT"; then
            :
        else
            _IDRC=\$?
            if [ "\$_IDRC" -eq 1 ]; then
                echo "[pre-push] BLOCKED by identity gate: repo<->live drift in a safety-critical _meta file." >&2
                echo "[pre-push] Reconcile or acknowledge the drift; bypass one push with: git push --no-verify" >&2
                exit 1
            fi
            echo "[pre-push] WARN: identity gate could not verify (exit \$_IDRC) — continuing to secrets scan" >&2
        fi
    fi
else
    echo "[pre-push] WARN: identity gate not found at \$IDENTITY_GATE — skipping identity check" >&2
fi

# --- 2. Secrets scan (cross-platform Python). ---
if [[ ! -f "\$SCANNER" ]]; then
    echo "[pre-push] WARN: scanner not found at \$SCANNER — letting push through" >&2
    exit 0
fi

for PY in python3 python py; do
    if command -v "\$PY" >/dev/null 2>&1; then
        if [[ "\$PY" == "py" ]]; then
            exec py -3 "\$SCANNER" "\$REPO_ROOT"
        else
            exec "\$PY" "\$SCANNER" "\$REPO_ROOT"
        fi
    fi
done

echo "[pre-push] WARN: no python found — letting push through" >&2
exit 0
EOF
else
    cat > "$HOOK" <<EOF
#!/usr/bin/env bash
$MARKER
# Pre-push chain: identity gate (fail-closed on drift) -> secrets-scan.sh.
# Override with: git push --no-verify

set -e

IDENTITY_GATE="$IDENTITY_GATE"
SCANNER="$SCANNER"
REPO_ROOT="\$(git rev-parse --show-toplevel)"

# --- 1. Identity gate: repo<->live _meta drift (fail CLOSED). Missing gate /
#        no python / environmental -> WARN and continue (never wedge a push). ---
if [ -f "\$IDENTITY_GATE" ]; then
    _IDPY=""
    for _p in python3 python py; do
        if command -v "\$_p" >/dev/null 2>&1; then _IDPY="\$_p"; break; fi
    done
    if [ -z "\$_IDPY" ]; then
        echo "[pre-push] WARN: no python for identity gate — skipping identity check" >&2
    else
        if [ "\$_IDPY" = "py" ]; then _IDPY="py -3"; fi
        if \$_IDPY "\$IDENTITY_GATE" --repo-root "\$REPO_ROOT"; then
            :
        else
            _IDRC=\$?
            if [ "\$_IDRC" -eq 1 ]; then
                echo "[pre-push] BLOCKED by identity gate: repo<->live drift in a safety-critical _meta file." >&2
                echo "[pre-push] Reconcile or acknowledge the drift; bypass one push with: git push --no-verify" >&2
                exit 1
            fi
            echo "[pre-push] WARN: identity gate could not verify (exit \$_IDRC) — continuing to secrets scan" >&2
        fi
    fi
else
    echo "[pre-push] WARN: identity gate not found at \$IDENTITY_GATE — skipping identity check" >&2
fi

# --- 2. Secrets scan. ---
if [[ ! -x "\$SCANNER" ]]; then
    echo "[pre-push] WARN: scanner not found at \$SCANNER — letting push through" >&2
    exit 0
fi

bash "\$SCANNER" "\$REPO_ROOT"
EOF
fi

chmod +x "$HOOK"
echo "[install] pre-push hook installed at $HOOK"
echo "[install] runs: $SCANNER"
echo "[install] override per-push with: git push --no-verify"
