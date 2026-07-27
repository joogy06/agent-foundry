#!/usr/bin/env bash
# agy_call.sh — the SOLE safe invocation path for headless Antigravity CLI (agy)
# consultancy calls on this host.
#
# WHY THIS EXISTS (S052 / avengers 2026-07-12, patch P1)
# ------------------------------------------------------
# Three recurring agy misuse classes have caused real incidents:
#   1. FLAG ORDER: `agy -p --sandbox "X"` runs UN-sandboxed — `-p` is a string
#      flag that swallows the next token, so `--sandbox` becomes the literal
#      prompt and "X" is discarded; agy then improvises from implicit memory.
#   2. STDIN HANG: headless agy reads non-TTY stdin until EOF before the model
#      call; in background/harness shells stdin never EOFs -> agy hangs at 0 bytes.
#   3. UNSANDBOXED WRITES: headless `-p` auto-approves agy's write/shell/git
#      tools; a plain `agy -p` has authored and git-committed code.
#
# This wrapper makes misuse IMPOSSIBLE rather than merely forbidden: the caller
# never passes `-p`, `--sandbox`, or the stdin redirect. The wrapper ALONE
# assembles the command, so flag order is correct BY CONSTRUCTION. Any argument
# the wrapper does not recognize (including a stray positional) is a hard
# fail-closed exit 2 — that kills the `-p`-swallow class outright.
#
# INTERFACE
#   agy_call.sh [--print-timeout <dur>] [--timeout <s>] [--reset-state|--keep-state]
#               [--expose-ro <dir>] [--no-preamble] [--dry-run]
#               (--prompt-file <f> | --prompt <str>)
#
#   --print-timeout <dur>  agy --print-timeout (e.g. 15m). Default: agy's own (5m).
#   --timeout <s>          shell `timeout` seconds around agy. Default: 600.
#   --reset-state          clear agy implicit cross-call state first (DEFAULT ON
#                          for consultancy). Backed up reversibly before removal.
#   --keep-state           opt OUT of the reset (for stateful/continuation calls).
#   --expose-ro <dir>      widen agy's workspace to <dir> (maps to --add-dir) AND
#                          arm a post-call `git status --short` tripwire on it.
#   --no-preamble          suppress the advisory-only preamble (write-task use only).
#   --dry-run              assemble + print the command (and perform reset-state),
#                          but do NOT exec agy or run the tripwire. For tests.
#   --prompt-file <f>      read the prompt from file <f>.
#   --prompt <str>         inline prompt string.
#
# EXIT CODES
#   0  agy ran and (if armed) the exposed dir showed no write delta
#   2  argument error (unknown/positional arg; missing or doubled prompt source)
#   3  tripwire: an --expose-ro dir gained a git delta during the call
#   *  agy's own exit code passed through (e.g. 124 = shell timeout)
#
# TEST SEAMS (no behavior change in production)
#   AGY_CALL_AGY_BIN   override the `agy` binary (a stub) for full-flow tests.
#   HOME               reset-state operates under $HOME/.gemini/antigravity-cli.
set -euo pipefail

PROG="agy_call.sh"

usage() {
    sed -n '2,45p' "$0"
}

die_args() {
    echo "[$PROG] ERROR: $1" >&2
    echo "[$PROG] (fail-closed exit 2 — see --help)" >&2
    exit 2
}

# --- Defaults -------------------------------------------------------------
PRINT_TIMEOUT=""
TIMEOUT_S="600"
RESET_STATE=1          # consultancy default: clear implicit cross-call state
EXPOSE_RO=""
PREAMBLE=1
DRY_RUN=0
PROMPT_MODE=""         # "file" | "str"
PROMPT_FILE=""
PROMPT_STR=""

PREAMBLE_TEXT="Advisory only — do not modify any files or run state-changing commands; answer on stdout."
SERVED_BY_PROBE="At the very end of your reply, on its own final line, output exactly: SERVED_BY: <the model identifier actually serving this request>"

# --- Parse (every unknown/positional arg is fatal) ------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --print-timeout) [ $# -ge 2 ] || die_args "--print-timeout needs a value"; PRINT_TIMEOUT="$2"; shift 2 ;;
        --timeout)       [ $# -ge 2 ] || die_args "--timeout needs a value"; TIMEOUT_S="$2"; shift 2 ;;
        --reset-state)   RESET_STATE=1; shift ;;
        --keep-state)    RESET_STATE=0; shift ;;
        --expose-ro)     [ $# -ge 2 ] || die_args "--expose-ro needs a directory"; EXPOSE_RO="$2"; shift 2 ;;
        --no-preamble)   PREAMBLE=0; shift ;;
        --dry-run)       DRY_RUN=1; shift ;;
        --prompt-file)   [ $# -ge 2 ] || die_args "--prompt-file needs a path"; [ -z "$PROMPT_MODE" ] || die_args "exactly one prompt source (--prompt-file/--prompt)"; PROMPT_MODE="file"; PROMPT_FILE="$2"; shift 2 ;;
        --prompt)        [ $# -ge 2 ] || die_args "--prompt needs a string"; [ -z "$PROMPT_MODE" ] || die_args "exactly one prompt source (--prompt-file/--prompt)"; PROMPT_MODE="str"; PROMPT_STR="$2"; shift 2 ;;
        --help|-h)       usage; exit 0 ;;
        *)               die_args "unrecognized or positional argument: '$1'" ;;
    esac
done

# Exactly one prompt source.
if [ -z "$PROMPT_MODE" ]; then
    die_args "no prompt: pass exactly one of --prompt-file or --prompt"
fi
if [ "$PROMPT_MODE" = "file" ]; then
    [ -f "$PROMPT_FILE" ] || die_args "--prompt-file not found: $PROMPT_FILE"
    PROMPT="$(cat "$PROMPT_FILE")"
else
    PROMPT="$PROMPT_STR"
fi

# Validate --timeout is a bare integer (goes to `timeout <s>`).
case "$TIMEOUT_S" in
    ''|*[!0-9]*) die_args "--timeout must be an integer number of seconds: '$TIMEOUT_S'" ;;
esac

# --- Compose the prompt (preamble + body + SERVED_BY probe) ---------------
FULL_PROMPT=""
if [ "$PREAMBLE" -eq 1 ]; then
    FULL_PROMPT="${PREAMBLE_TEXT}"$'\n\n'
fi
FULL_PROMPT="${FULL_PROMPT}${PROMPT}"$'\n\n'"${SERVED_BY_PROBE}"

# --- Assemble the command (flag order correct BY CONSTRUCTION) ------------
# Order invariant: EVERY flag BEFORE -p, prompt LAST. --sandbox unconditional.
AGY_BIN="${AGY_CALL_AGY_BIN:-agy}"

cmd=()
if command -v timeout >/dev/null 2>&1; then
    cmd+=(timeout "$TIMEOUT_S")
fi
cmd+=("$AGY_BIN" --sandbox)
if [ -n "$EXPOSE_RO" ]; then
    cmd+=(--add-dir "$EXPOSE_RO")
fi
if [ -n "$PRINT_TIMEOUT" ]; then
    cmd+=(--print-timeout "$PRINT_TIMEOUT")
fi
cmd+=(-p "$FULL_PROMPT")

# Human-readable assembly (prompt shown as a placeholder so the invariant —
# order, --sandbox, -p-last — is asserted without dumping the whole prompt).
render_cmd() {
    local out="" tok
    for tok in "${cmd[@]}"; do
        case "$tok" in
            "$FULL_PROMPT") out="${out} <PROMPT>" ;;
            *) out="${out} ${tok}" ;;
        esac
    done
    # Trailing stdin redirect is applied at exec time; show it for clarity.
    echo "${out# } < /dev/null"
}

# --- reset-state: back up implicit cross-call state, then clear it --------
maybe_reset_state() {
    [ "$RESET_STATE" -eq 1 ] || return 0
    local state_dir="${HOME:-/nonexistent}/.gemini/antigravity-cli"
    local brain="$state_dir/brain"
    local jetski="$state_dir/jetski_state.pbtxt"
    if [ -d "$brain" ] || [ -f "$jetski" ]; then
        local ts backup
        ts="$(date -u +%Y%m%dT%H%M%SZ)"
        backup="$state_dir/brain.bak.$ts"
        mkdir -p "$backup"
        [ -d "$brain" ] && mv "$brain" "$backup/brain"
        [ -f "$jetski" ] && mv "$jetski" "$backup/jetski_state.pbtxt"
        echo "[$PROG] reset-state: implicit state backed up to $backup (reversible; mv back to restore)" >&2
    fi
    return 0
}

# --- Post-call tripwire on an exposed repo -------------------------------
tripwire() {
    [ -n "$EXPOSE_RO" ] || return 0
    if [ ! -d "$EXPOSE_RO/.git" ] && ! git -C "$EXPOSE_RO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        return 0   # not a git repo — nothing to diff
    fi
    local delta
    delta="$(git -C "$EXPOSE_RO" status --short 2>/dev/null || true)"
    if [ -n "$delta" ]; then
        echo "[$PROG] TRIPWIRE: exposed dir '$EXPOSE_RO' changed during the agy call:" >&2
        echo "$delta" >&2
        echo "[$PROG] a consultancy call must not write — investigate (exit 3)." >&2
        return 3
    fi
    return 0
}

maybe_reset_state

if [ "$DRY_RUN" -eq 1 ]; then
    render_cmd
    exit 0
fi

# --- Execute --------------------------------------------------------------
OUT="$(mktemp)"
trap 'rm -f "$OUT"' EXIT
set +e
"${cmd[@]}" < /dev/null > "$OUT" 2>&1
rc=$?
set -e

cat "$OUT"

served="$(grep -aE '^SERVED_BY:' "$OUT" | tail -n1 | sed -E 's/^SERVED_BY:[[:space:]]*//')"
if [ -n "$served" ]; then
    echo "[$PROG] served_by: $served" >&2
else
    echo "[$PROG] served_by: (probe line not found in output)" >&2
fi

# Tripwire runs regardless of agy's rc — a write during a failed call still matters.
if ! tripwire; then
    exit 3
fi

exit "$rc"
