#!/usr/bin/env bash
# agy_call.sh — the SOLE safe invocation path for headless Antigravity CLI (agy)
# consultancy calls on this host.
#
# WHY THIS EXISTS (S052 / avengers 2026-07-12, patch P1)
# ------------------------------------------------------
# Four recurring agy misuse classes have caused real incidents:
#   1. FLAG ORDER: `agy -p --sandbox "X"` runs UN-sandboxed — `-p` is a string
#      flag that swallows the next token, so `--sandbox` becomes the literal
#      prompt and "X" is discarded; agy then improvises from implicit memory.
#   2. STDIN HANG: headless agy reads non-TTY stdin until EOF before the model
#      call; in background/harness shells stdin never EOFs -> agy hangs at 0 bytes.
#   3. UNSANDBOXED WRITES: headless `-p` auto-approves agy's write/shell/git
#      tools; a plain `agy -p` has authored and git-committed code.
#   4. WRITES AND REPO READS UNDER --sandbox (#366, measured on agy 1.4.12):
#      --sandbox restricts only the shell, so the wrapper also passes --mode plan
#      (no native writes) and runs agy from an empty temp directory (the cwd is
#      the workspace, so a call from a repo can read that repo).
#
# This wrapper makes misuse IMPOSSIBLE rather than merely forbidden: the caller
# never passes `-p`, `--sandbox`, or the stdin redirect. The wrapper ALONE
# assembles the command, so flag order is correct BY CONSTRUCTION. Any argument
# the wrapper does not recognize (including a stray positional) is a hard
# fail-closed exit 2 — that kills the `-p`-swallow class outright.
#
# INTERFACE
#   agy_call.sh [--role <role>] [--print-timeout <dur>] [--timeout <s>] [--reset-state|--keep-state]
#               [--dry-run]
#               (--prompt-file <f> | --prompt <str>)
#
#   --role <role>          seat role the model is resolved for, through
#                          `seat_model.py argv --role <role> --provider agy` (the
#                          ONLY source of --model; a failed resolution is exit 2,
#                          never an unpinned call). Default: consultant_support.
#   --print-timeout <dur>  agy --print-timeout (e.g. 15m). Default: agy's own (5m).
#   --timeout <s>          shell `timeout` seconds around agy. Default: 600.
#   --reset-state          clear agy implicit cross-call state first (DEFAULT ON
#                          for consultancy). Backed up reversibly before removal.
#   --keep-state           opt OUT of the reset (for stateful/continuation calls).
#   --dry-run              assemble + print the command (and perform reset-state),
#                          but do NOT exec agy. For tests.
#   --prompt-file <f>      read the prompt from file <f>.
#   --prompt <str>         inline prompt string.
#
# EXIT CODES
#   0  agy ran
#   2  argument error (unknown/positional arg; missing or doubled prompt source),
#      or the model could not be resolved through seat_model
#   *  agy's own exit code passed through (e.g. 124 = shell timeout)
#
# TEST SEAMS (no behavior change in production)
#   AGY_CALL_AGY_BIN   override the `agy` binary (a stub) for full-flow tests.
#   AGY_CALL_SEAT_MODEL override seat_model.py (a stub) to test a failed resolution.
#   HOME               reset-state operates under $HOME/.gemini/antigravity-cli.
set -euo pipefail

PROG="agy_call.sh"

usage() {
    sed -n '2,54p' "$0"
}

die_args() {
    echo "[$PROG] ERROR: $1" >&2
    echo "[$PROG] (fail-closed exit 2 — see --help)" >&2
    exit 2
}

# --- Defaults -------------------------------------------------------------
PRINT_TIMEOUT=""
SEAT_ROLE="consultant_support"
TIMEOUT_S="600"
RESET_STATE=1          # consultancy default: clear implicit cross-call state
DRY_RUN=0
PROMPT_MODE=""         # "file" | "str"
PROMPT_FILE=""
PROMPT_STR=""

PREAMBLE_TEXT="Advisory only — do not modify any files or run state-changing commands; answer on stdout."
SERVED_BY_PROBE="At the very end of your reply, on its own final line, output exactly: SERVED_BY: <the model identifier actually serving this request>"

# --- Parse (every unknown/positional arg is fatal) ------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --role)          [ $# -ge 2 ] || die_args "--role needs a value"; SEAT_ROLE="$2"; shift 2 ;;
        --print-timeout) [ $# -ge 2 ] || die_args "--print-timeout needs a value"; PRINT_TIMEOUT="$2"; shift 2 ;;
        --timeout)       [ $# -ge 2 ] || die_args "--timeout needs a value"; TIMEOUT_S="$2"; shift 2 ;;
        --reset-state)   RESET_STATE=1; shift ;;
        --keep-state)    RESET_STATE=0; shift ;;
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
FULL_PROMPT="${PREAMBLE_TEXT}"$'\n\n'"${PROMPT}"$'\n\n'"${SERVED_BY_PROBE}"

# One argument cannot pass 128 KB, and piped stdin never reaches the model (#366), so an oversized
# prompt is refused here rather than reaching exec. 120 KB is the largest size measured whole. The
# limit is in BYTES and covers the whole composed prompt, so count with LC_ALL=C.
FULL_PROMPT_BYTES="$(LC_ALL=C; export LC_ALL; printf '%s' "$FULL_PROMPT" | wc -c)"
[ "$FULL_PROMPT_BYTES" -le 120000 ] || die_args "prompt is over 120 KB ($FULL_PROMPT_BYTES bytes with the preamble and probe): split it, one call per chunk"

# --- Resolve the model (pinned on every call, through seat_model) --------
# The fragment is `--model <slug>`; an empty or failed resolution is fatal, so
# the wrapper never falls back to the account default model.
SEAT_MODEL_PY="${AGY_CALL_SEAT_MODEL:-$(cd "$(dirname "$0")" && pwd)/seat_model.py}"
# seat_model's own stderr is kept: its last line is the refusal reason.
SM_ERR="$(mktemp)"
if ! MODEL_PIN="$(python3 "$SEAT_MODEL_PY" argv --role "$SEAT_ROLE" --provider agy 2>"$SM_ERR")"; then
    # `|| true`: an EMPTY stderr makes grep exit 1, and under `set -euo pipefail` that would end the
    # script here with exit 1 and no message (#367 WP-C). The fallback reason below covers it.
    SM_REASON="$(grep -v '^[[:space:]]*$' "$SM_ERR" | tail -n 1 || true)"
    rm -f "$SM_ERR"
    die_args "could not resolve the agy model for role '$SEAT_ROLE' through seat_model: ${SM_REASON:-seat_model exited non-zero with an empty stderr}"
fi
rm -f "$SM_ERR"
read -r -a MODEL_ARGS <<< "$MODEL_PIN"
[ "${#MODEL_ARGS[@]}" -eq 2 ] && [ "${MODEL_ARGS[0]}" = "--model" ] \
    || die_args "seat_model returned an unexpected agy pin: '$MODEL_PIN'"

# --- Assemble the command (flag order correct BY CONSTRUCTION) ------------
# Order invariant: EVERY flag BEFORE -p, prompt LAST. --sandbox and --mode plan
# unconditional: an advisory call has no write path (#366).
AGY_BIN="${AGY_CALL_AGY_BIN:-agy}"

cmd=()
if command -v timeout >/dev/null 2>&1; then
    cmd+=(timeout "$TIMEOUT_S")
fi
cmd+=("$AGY_BIN" --sandbox --mode plan)
if [ -n "$PRINT_TIMEOUT" ]; then
    cmd+=(--print-timeout "$PRINT_TIMEOUT")
fi
cmd+=("${MODEL_ARGS[@]}")
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

maybe_reset_state

if [ "$DRY_RUN" -eq 1 ]; then
    render_cmd
    exit 0
fi

# --- Execute --------------------------------------------------------------
OUT="$(mktemp)"
EMPTY_CWD="$(mktemp -d)"     # the cwd is agy's workspace: an empty one exposes nothing (#366)
trap 'rm -f "$OUT"; rmdir "$EMPTY_CWD" 2>/dev/null || true' EXIT
set +e
( cd "$EMPTY_CWD" && "${cmd[@]}" < /dev/null > "$OUT" 2>&1 )
rc=$?
set -e

cat "$OUT"

# `|| true`: no probe line (an agy no-show prints nothing) makes grep exit 1, which under pipefail
# would end the script here and lose agy's own exit code.
served="$(grep -aE '^SERVED_BY:' "$OUT" | tail -n1 | sed -E 's/^SERVED_BY:[[:space:]]*//' || true)"
if [ -n "$served" ]; then
    echo "[$PROG] served_by: $served" >&2
else
    echo "[$PROG] served_by: (probe line not found in output)" >&2
fi

exit "$rc"
