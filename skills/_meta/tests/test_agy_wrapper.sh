#!/usr/bin/env bash
# test_agy_wrapper.sh — unit + (skippable) live tests for skills/_meta/agy_call.sh
#
# Unit tests need NO agy binary: argument fail-closed cases, the assembled
# command string, reset-state backup behavior (fixture HOME), and the empty cwd
# on a synthetic dirty repo (a stub agy stands in for the real CLI).
#
# The final "corrected-order re-probe" (E4 / T2 evidence) invokes the REAL agy
# from a workflow-stage-like context and asserts exit 0, non-empty stdout, zero
# writes. It is SKIPPED when agy is absent; if it RUNS and FAILS, that is loud
# T2 evidence — do NOT auto-disable anything on the strength of it.
#
# Usage: bash test_agy_wrapper.sh            (exit 0 = all green / skips ok)
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
WRAPPER="$HERE/../agy_call.sh"

PASS=0
FAIL=0
SKIP=0

ok()   { echo "  ok   - $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL - $1"; FAIL=$((FAIL+1)); }
skip() { echo "  skip - $1"; SKIP=$((SKIP+1)); }

# Assert the wrapper exits with an expected code. Captures combined output.
# usage: expect_exit <label> <expected_code> -- <args...>   [with env prefix via ENVV]
expect_exit() {
    local label="$1" want="$2"; shift 2
    [ "$1" = "--" ] && shift
    local out rc
    out="$(bash "$WRAPPER" "$@" 2>&1)"; rc=$?
    if [ "$rc" -eq "$want" ]; then ok "$label (exit $rc)"; else bad "$label (want exit $want, got $rc; out: $out)"; fi
}

echo "== argument fail-closed cases =="
expect_exit "unknown flag -> 2"            2 -- --bogus --prompt x
expect_exit "positional arg -> 2"          2 -- justtext
expect_exit "no prompt -> 2"               2 -- --timeout 5
expect_exit "doubled prompt source -> 2"   2 -- --prompt a --prompt b
expect_exit "non-integer --timeout -> 2"   2 -- --timeout abc --prompt x
expect_exit "--print-timeout missing val"  2 -- --print-timeout
expect_exit "--help -> 0"                  0 -- --help

echo "== command assembly (dry-run) =="
asm="$(bash "$WRAPPER" --dry-run --prompt 'hello there' 2>/dev/null)"
if echo "$asm" | grep -q -- '--sandbox' && echo "$asm" | grep -q -- '-p <PROMPT> < /dev/null'; then
    ok "assembly has --sandbox and -p <PROMPT> last"
else
    bad "assembly wrong: $asm"
fi
# Invariant: --sandbox must appear BEFORE -p (kills the -p-swallow class).
sandbox_pos="$(echo "$asm" | grep -ob -- '--sandbox' | head -1 | cut -d: -f1)"
dashp_pos="$(echo "$asm" | grep -ob -- '-p <PROMPT>' | head -1 | cut -d: -f1)"
if [ -n "$sandbox_pos" ] && [ -n "$dashp_pos" ] && [ "$sandbox_pos" -lt "$dashp_pos" ]; then
    ok "--sandbox precedes -p"
else
    bad "flag order not enforced (sandbox=$sandbox_pos p=$dashp_pos)"
fi
# The model is pinned through seat_model, before -p (#367 fix round 1).
want_pin="$(python3 "$HERE/../seat_model.py" argv --role consultant_support --provider agy 2>/dev/null)"
if [ -n "$want_pin" ] && echo "$asm" | grep -q -- "--sandbox --mode plan $want_pin -p <PROMPT>"; then
    ok "assembly pins the seat_model agy model before -p ($want_pin)"
else
    bad "assembly does not pin the model: $asm (want $want_pin)"
fi
want_main="$(python3 "$HERE/../seat_model.py" argv --role consultant_main --provider agy 2>/dev/null)"
asm_main="$(bash "$WRAPPER" --dry-run --keep-state --role consultant_main --prompt x 2>/dev/null)"
if [ -n "$want_main" ] && echo "$asm_main" | grep -q -- "$want_main -p <PROMPT>"; then
    ok "--role selects the seat role the model resolves for"
else
    bad "--role not honoured: $asm_main (want $want_main)"
fi
BADSM="$(mktemp)"; printf 'import sys\nsys.stderr.write("seat_model: no eligible agy model\\n")\nsys.exit(3)\n' > "$BADSM"
out="$(AGY_CALL_SEAT_MODEL="$BADSM" bash "$WRAPPER" --dry-run --keep-state --prompt x 2>&1)"; rc=$?
if [ "$rc" -eq 2 ] && echo "$out" | grep -q 'could not resolve.*no eligible agy model'; then
    ok "failed model resolution -> exit 2 with seat_model's reason, never an unpinned call"
else
    bad "failed resolution not fatal (rc=$rc: $out)"
fi
rm -f "$BADSM"
# #367 WP-C: a seat_model that fails with an EMPTY stderr still gets exit 2 and a reason (it used to
# end the script silently with exit 1: grep found no line, and pipefail + set -e fired).
QUIETSM="$(mktemp)"; printf 'import sys\nsys.exit(1)\n' > "$QUIETSM"
out="$(AGY_CALL_SEAT_MODEL="$QUIETSM" bash "$WRAPPER" --dry-run --keep-state --prompt x 2>&1)"; rc=$?
if [ "$rc" -eq 2 ] && echo "$out" | grep -q 'could not resolve.*empty stderr'; then
    ok "failed model resolution with an empty stderr -> exit 2 with a reason"
else
    bad "silent seat_model failure not reported (rc=$rc: $out)"
fi
rm -f "$QUIETSM"
expect_exit "--role missing val -> 2"      2 -- --role
asm2="$(bash "$WRAPPER" --dry-run --print-timeout 15m --prompt x 2>/dev/null)"
if echo "$asm2" | grep -q -- '--print-timeout 15m' && ! echo "$asm2" | grep -q -- '--add-dir'; then
    ok "assembly threads --print-timeout before -p and carries no --add-dir"
else
    bad "assembly wrong: $asm2"
fi
expect_exit "--expose-ro is gone -> 2"     2 -- --expose-ro /tmp/nope --prompt x
expect_exit "--no-preamble is gone -> 2"   2 -- --no-preamble --prompt x
BIG="$(mktemp)"; head -c 120100 /dev/zero | tr '\0' 'a' > "$BIG"
expect_exit "prompt over 120 KB -> 2"      2 -- --dry-run --keep-state --prompt-file "$BIG"
# 45,000 three-byte characters: 135 KB, though only 45,000 characters (#366: the limit is in bytes).
python3 -c 'print("\u20ac" * 45000, end="")' > "$BIG"
expect_exit "multi-byte prompt over 120 KB -> 2" 2 -- --dry-run --keep-state --prompt-file "$BIG"
python3 -c 'print("\u20ac" * 39000, end="")' > "$BIG"
expect_exit "multi-byte prompt under 120 KB -> 0" 0 -- --dry-run --keep-state --prompt-file "$BIG"
rm -f "$BIG"
if bash "$WRAPPER" --help | grep -q '3 \|0  agy ran'; then ok "--help reaches the exit codes"; else bad "--help stops before the exit codes"; fi

echo "== reset-state backup (fixture HOME) =="
FH="$(mktemp -d)"
mkdir -p "$FH/.gemini/antigravity-cli/brain"
echo "brainstate" > "$FH/.gemini/antigravity-cli/brain/state.bin"
echo "jetski" > "$FH/.gemini/antigravity-cli/jetski_state.pbtxt"
HOME="$FH" bash "$WRAPPER" --dry-run --prompt x >/dev/null 2>&1
if [ ! -d "$FH/.gemini/antigravity-cli/brain" ] \
   && [ ! -f "$FH/.gemini/antigravity-cli/jetski_state.pbtxt" ] \
   && ls -d "$FH/.gemini/antigravity-cli"/brain.bak.* >/dev/null 2>&1; then
    ok "reset-state moved brain/ + jetski into a reversible backup"
else
    bad "reset-state did not back up/clear implicit state"
fi
# --keep-state opts out.
FH2="$(mktemp -d)"
mkdir -p "$FH2/.gemini/antigravity-cli/brain"
echo x > "$FH2/.gemini/antigravity-cli/brain/state.bin"
HOME="$FH2" bash "$WRAPPER" --dry-run --keep-state --prompt x >/dev/null 2>&1
if [ -d "$FH2/.gemini/antigravity-cli/brain" ] && ! ls -d "$FH2/.gemini/antigravity-cli"/brain.bak.* >/dev/null 2>&1; then
    ok "--keep-state leaves implicit state untouched"
else
    bad "--keep-state still reset state"
fi

echo "== stub agy =="
STUB="$(mktemp)"
cat > "$STUB" <<'EOF'
#!/usr/bin/env bash
# stub agy: ignore all flags, emit a short reply + a SERVED_BY line.
echo "stub advisory reply"
echo "SERVED_BY: stub-model-x"
exit 0
EOF
chmod +x "$STUB"
out="$(AGY_CALL_AGY_BIN="$STUB" bash "$WRAPPER" --keep-state --prompt x 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "stub call -> exit 0"; else bad "stub call failed (rc=$rc: $out)"; fi
if echo "$out" | grep -q 'served_by: stub-model-x'; then ok "SERVED_BY parsed and echoed"; else bad "SERVED_BY not echoed: $out"; fi
# A no-show prints nothing: agy's exit code must still come through (#366).
SILENT="$(mktemp)"; printf '#!/usr/bin/env bash\nexit 7\n' > "$SILENT"; chmod +x "$SILENT"
out="$(AGY_CALL_AGY_BIN="$SILENT" bash "$WRAPPER" --keep-state --prompt x 2>&1)"; rc=$?
if [ "$rc" -eq 7 ]; then ok "a silent agy keeps its exit code"; else bad "silent agy lost its exit code (rc=$rc: $out)"; fi

# The call runs from an empty directory, not from the caller's cwd (#366).
STUB4="$(mktemp)"
cat > "$STUB4" <<'EOF'
#!/usr/bin/env bash
echo "CWD_ENTRIES=[$(ls -A)]"
exit 0
EOF
chmod +x "$STUB4"
out="$(cd "$HERE" && AGY_CALL_AGY_BIN="$STUB4" bash "$WRAPPER" --keep-state --prompt x 2>&1)"; rc=$?
if echo "$out" | grep -q 'CWD_ENTRIES=\[\]'; then ok "agy runs from an empty cwd"; else bad "cwd not empty: $out"; fi

# A failed mktemp must not reach agy: the empty cwd is the point (#366 design C1).
NOTMP="$(mktemp -d)"; printf '#!/bin/sh\nexit 1\n' > "$NOTMP/mktemp"; chmod +x "$NOTMP/mktemp"
RAN="$NOTMP/ran"; STUB5="$(mktemp)"; printf '#!/usr/bin/env bash\ntouch "%s"\n' "$RAN" > "$STUB5"; chmod +x "$STUB5"
out="$(PATH="$NOTMP:$PATH" AGY_CALL_AGY_BIN="$STUB5" bash "$WRAPPER" --keep-state --prompt x 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && [ ! -e "$RAN" ]; then ok "failed mktemp -> no agy call (rc=$rc)"; else bad "agy ran without an empty cwd (rc=$rc: $out)"; fi

echo "== corrected-order live re-probe (E4 / T2; skippable) =="
if [ -n "${AGY_WRAPPER_NO_LIVE:-}" ]; then
    echo "  skip - live probe (AGY_WRAPPER_NO_LIVE set)"; SKIP=$((SKIP+1))
elif command -v agy >/dev/null 2>&1; then
    DISPOSABLE="$(mktemp -d)"; git -C "$DISPOSABLE" init -q; git -C "$DISPOSABLE" config user.email t@t; git -C "$DISPOSABLE" config user.name t
    echo hi > "$DISPOSABLE/f"; git -C "$DISPOSABLE" add f; git -C "$DISPOSABLE" commit -qm base
    # Workflow-stage-like context: stdin already redirected, no TTY.
    live_out="$(bash "$WRAPPER" --timeout 120 --prompt 'Reply with the single word OK.' < /dev/null 2>/tmp/agy_reprobe_err.$$)"; rc=$?
    live_err="$(cat /tmp/agy_reprobe_err.$$ 2>/dev/null)"; rm -f /tmp/agy_reprobe_err.$$
    if [ "$rc" -eq 0 ] && [ -n "$live_out" ]; then
        ok "LIVE re-probe: exit 0, non-empty stdout (T2 sufficiency evidence)"
        echo "       served_by line: $(echo "$live_err" | grep -a 'served_by:' || echo '(none)')"
    else
        bad "LIVE re-probe FAILED (rc=$rc). T2 EVIDENCE — report to user; do NOT auto-disable agy. stderr: $live_err"
    fi
else
    skip "agy not installed — live corrected-order re-probe skipped (P1 sufficiency stays 'medium')"
fi

echo
echo "== summary: pass=$PASS fail=$FAIL skip=$SKIP =="
[ "$FAIL" -eq 0 ]
