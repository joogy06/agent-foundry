#!/usr/bin/env bash
# test_agy_wrapper.sh — unit + (skippable) live tests for skills/_meta/agy_call.sh
#
# Unit tests need NO agy binary: argument fail-closed cases, the assembled
# command string, reset-state backup behavior (fixture HOME), and the tripwire
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
asm2="$(bash "$WRAPPER" --dry-run --expose-ro /tmp/nope --print-timeout 15m --prompt x 2>/dev/null)"
if echo "$asm2" | grep -q -- '--add-dir /tmp/nope' && echo "$asm2" | grep -q -- '--print-timeout 15m'; then
    ok "assembly threads --expose-ro (--add-dir) and --print-timeout before -p"
else
    bad "assembly missing add-dir/print-timeout: $asm2"
fi

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

echo "== tripwire on synthetic dirty repo (stub agy) =="
STUB="$(mktemp)"
cat > "$STUB" <<'EOF'
#!/usr/bin/env bash
# stub agy: ignore all flags, emit a short reply + a SERVED_BY line.
echo "stub advisory reply"
echo "SERVED_BY: stub-model-x"
exit 0
EOF
chmod +x "$STUB"

# Clean repo -> exit 0.
CLEAN="$(mktemp -d)"; git -C "$CLEAN" init -q; git -C "$CLEAN" config user.email t@t; git -C "$CLEAN" config user.name t
echo base > "$CLEAN/f"; git -C "$CLEAN" add f; git -C "$CLEAN" commit -qm base
out="$(AGY_CALL_AGY_BIN="$STUB" bash "$WRAPPER" --keep-state --expose-ro "$CLEAN" --prompt x 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then ok "clean exposed repo -> exit 0"; else bad "clean repo tripwire misfired (rc=$rc: $out)"; fi
if echo "$out" | grep -q 'served_by: stub-model-x'; then ok "SERVED_BY parsed and echoed"; else bad "SERVED_BY not echoed: $out"; fi

# Dirty repo -> exit 3.
DIRTY="$(mktemp -d)"; git -C "$DIRTY" init -q; git -C "$DIRTY" config user.email t@t; git -C "$DIRTY" config user.name t
echo base > "$DIRTY/f"; git -C "$DIRTY" add f; git -C "$DIRTY" commit -qm base
# A dirty-repo stub: writes a file into the exposed dir to simulate a rogue write.
STUB2="$(mktemp)"
cat > "$STUB2" <<EOF
#!/usr/bin/env bash
echo "rogue write incoming"
echo "new content" > "$DIRTY/rogue.txt"
echo "SERVED_BY: stub-model-x"
exit 0
EOF
chmod +x "$STUB2"
out="$(AGY_CALL_AGY_BIN="$STUB2" bash "$WRAPPER" --keep-state --expose-ro "$DIRTY" --prompt x 2>&1)"; rc=$?
if [ "$rc" -eq 3 ]; then ok "rogue write in exposed repo -> exit 3 (tripwire)"; else bad "tripwire failed to fire (rc=$rc: $out)"; fi

echo "== corrected-order live re-probe (E4 / T2; skippable) =="
if command -v agy >/dev/null 2>&1; then
    DISPOSABLE="$(mktemp -d)"; git -C "$DISPOSABLE" init -q; git -C "$DISPOSABLE" config user.email t@t; git -C "$DISPOSABLE" config user.name t
    echo hi > "$DISPOSABLE/f"; git -C "$DISPOSABLE" add f; git -C "$DISPOSABLE" commit -qm base
    # Workflow-stage-like context: stdin already redirected, no TTY.
    live_out="$(bash "$WRAPPER" --timeout 120 --expose-ro "$DISPOSABLE" \
                    --prompt 'Reply with the single word OK.' < /dev/null 2>/tmp/agy_reprobe_err.$$)"; rc=$?
    live_err="$(cat /tmp/agy_reprobe_err.$$ 2>/dev/null)"; rm -f /tmp/agy_reprobe_err.$$
    if [ "$rc" -eq 0 ] && [ -n "$live_out" ]; then
        ok "LIVE re-probe: exit 0, non-empty stdout, no tripwire (T2 sufficiency evidence)"
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
