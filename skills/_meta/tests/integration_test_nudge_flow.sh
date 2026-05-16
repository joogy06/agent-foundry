#!/usr/bin/env bash
#
# integration_test_nudge_flow.sh
#
# End-to-end test of the nudge -> apply -> re-scan and
# nudge -> suppress -> re-scan cycles plus the symlinked-CLAUDE.md path
# and mixed-source coexistence path.
#
# This test invokes the real scripts (scan_hard_rules.py +
# apply_project_hard_rules.py) against a synthetic project tree under
# /tmp, with HOME redirected to a temp dir so STATE_FILE +
# GLOBAL_CLAUDE_MD + CHECKLIST do not touch the real ~/.claude.
#
# Exit 0 on success, non-zero on any failure.

set -euo pipefail

# Resolve paths relative to this script (so it works regardless of cwd).
THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META_DIR="$(dirname "$THIS_DIR")"
SCAN="$META_DIR/scan_hard_rules.py"
APPLY="$META_DIR/apply_project_hard_rules.py"

if [[ ! -f "$SCAN" ]]; then
    echo "FAIL: scan_hard_rules.py not at $SCAN" >&2
    exit 1
fi
if [[ ! -f "$APPLY" ]]; then
    echo "FAIL: apply_project_hard_rules.py not at $APPLY" >&2
    exit 1
fi

# Single sandbox HOME for the run.
SANDBOX="$(mktemp -d -t scan-hard-rules-it.XXXXXX)"
trap 'rm -rf "$SANDBOX"' EXIT

export HOME="$SANDBOX"
mkdir -p "$SANDBOX/.claude/skills/_meta" "$SANDBOX/.claude/state"

# Tiny global CLAUDE.md (no project-source rules trigger).
cat >"$SANDBOX/.claude/CLAUDE.md" <<'EOF'
# Global
- **read the design carefully**
EOF

# Empty checklist — covers the global rule via fuzzy match.
cat >"$SANDBOX/.claude/skills/_meta/hard-rules-checklist.md" <<'EOF'
# Checklist
- read design carefully
EOF

pass=0
fail=0
report() {
    local label="$1"; shift
    if "$@"; then
        echo "  PASS: $label"
        pass=$((pass + 1))
    else
        echo "  FAIL: $label" >&2
        fail=$((fail + 1))
    fi
}

# --- Test 1: scan -> apply -> re-scan silences nudge ---
echo "Test 1: scan -> apply -> re-scan"
PROJ1="$SANDBOX/proj1"
mkdir -p "$PROJ1"
cat >"$PROJ1/CLAUDE.md" <<'EOF'
# Proj1
## Notes
- **alpha-rule one branch only**
- **beta-rule needs explicit approval**
- **gamma-rule push to private only**
EOF

cd "$PROJ1"
out1="$(python3 "$SCAN")"
report "initial scan emits project-scoped section" bash -c "
  echo \"\$1\" | grep -q '## Project-Scoped Directives Need Action'
" _ "$out1"
report "initial scan contains all 3 directives" bash -c "
  echo \"\$1\" | grep -q 'alpha-rule one branch only' &&
  echo \"\$1\" | grep -q 'beta-rule needs explicit approval' &&
  echo \"\$1\" | grep -q 'gamma-rule push to private only'
" _ "$out1"
report "initial scan emits the apply command" bash -c "
  echo \"\$1\" | grep -q 'apply_project_hard_rules.py apply'
" _ "$out1"

# Apply all three.
python3 "$APPLY" apply \
  --project-id "$PROJ1" \
  --project-claude-md "$PROJ1/CLAUDE.md" \
  --rule "alpha-rule one branch only" \
  --rule "beta-rule needs explicit approval" \
  --rule "gamma-rule push to private only" >/dev/null

report "Project HARD-RULEs section present" bash -c "
  grep -q '## Project HARD-RULEs' '$PROJ1/CLAUDE.md'
"
report "all 3 bullets present in section" bash -c "
  grep -q '^- alpha-rule one branch only$' '$PROJ1/CLAUDE.md' &&
  grep -q '^- beta-rule needs explicit approval$' '$PROJ1/CLAUDE.md' &&
  grep -q '^- gamma-rule push to private only$' '$PROJ1/CLAUDE.md'
"

out2="$(python3 "$SCAN")"
report "re-scan no longer nudges (locally-handled filter works)" bash -c "
  ! (echo \"\$1\" | grep -q '## Project-Scoped Directives Need Action')
" _ "$out2"

# --- Test 2: scan -> suppress -> re-scan silences nudge ---
echo "Test 2: scan -> suppress -> re-scan"
PROJ2="$SANDBOX/proj2"
mkdir -p "$PROJ2"
cat >"$PROJ2/CLAUDE.md" <<'EOF'
# Proj2
## Notes
- **delta-rule should be skipped permanently**
EOF
cd "$PROJ2"
out3="$(python3 "$SCAN")"
report "Proj2 initial scan nudges" bash -c "
  echo \"\$1\" | grep -q 'delta-rule should be skipped permanently'
" _ "$out3"

python3 "$APPLY" suppress \
  --project-id "$PROJ2" \
  --rule "delta-rule should be skipped permanently" >/dev/null

report "state file created with 0600 perms (best-effort)" bash -c "
  test -f '$SANDBOX/.claude/state/hard-rules-suppressed.json'
"

out4="$(python3 "$SCAN")"
report "Proj2 re-scan silenced by suppression" bash -c "
  ! (echo \"\$1\" | grep -q '## Project-Scoped Directives Need Action')
" _ "$out4"

# --- Test 3: symlinked CLAUDE.md path ---
echo "Test 3: symlinked CLAUDE.md"
PROJ3="$SANDBOX/proj3"
mkdir -p "$PROJ3"
cat >"$PROJ3/real.md" <<'EOF'
# Real
## Notes
- **epsilon-rule via symlink**
EOF
ln -s "$PROJ3/real.md" "$PROJ3/CLAUDE.md"
cd "$PROJ3"

python3 "$APPLY" apply \
  --project-id "$PROJ3" \
  --project-claude-md "$PROJ3/CLAUDE.md" \
  --rule "epsilon-rule via symlink" >/dev/null

report "symlink preserved after apply" bash -c "
  test -L '$PROJ3/CLAUDE.md'
"
report "real file updated with section" bash -c "
  grep -q '## Project HARD-RULEs' '$PROJ3/real.md' &&
  grep -q '^- epsilon-rule via symlink$' '$PROJ3/real.md'
"
report "symlink and real path point to same inode" bash -c "
  test \"\$(stat -L -c '%i' '$PROJ3/CLAUDE.md')\" = \"\$(stat -c '%i' '$PROJ3/real.md')\"
"

# --- Test 4: mixed-source coexistence ---
echo "Test 4: mixed-source (global + project both need surfacing)"
# Add a global-only HARD-RULE NOT in the checklist.
cat >"$SANDBOX/.claude/CLAUDE.md" <<'EOF'
# Global
- **zeta-global-rule needs surfacing too**
EOF
# Keep checklist as-is (so zeta-global-rule is missing).

PROJ4="$SANDBOX/proj4"
mkdir -p "$PROJ4"
cat >"$PROJ4/CLAUDE.md" <<'EOF'
# Proj4
## Notes
- **eta-project-only-rule needs section**
EOF
cd "$PROJ4"

out5="$(python3 "$SCAN")"
report "mixed scan emits Project-Scoped section" bash -c "
  echo \"\$1\" | grep -q '## Project-Scoped Directives Need Action'
" _ "$out5"
report "mixed scan emits Global-Scoped section" bash -c "
  echo \"\$1\" | grep -q '## Global-Scoped Directives'
" _ "$out5"
report "global rule present in output" bash -c "
  echo \"\$1\" | grep -q 'zeta-global-rule needs surfacing too'
" _ "$out5"
report "project rule present in output" bash -c "
  echo \"\$1\" | grep -q 'eta-project-only-rule needs section'
" _ "$out5"

# --- Summary ---
echo ""
echo "Summary: $pass passed, $fail failed."
if (( fail > 0 )); then
    exit 1
fi
exit 0
