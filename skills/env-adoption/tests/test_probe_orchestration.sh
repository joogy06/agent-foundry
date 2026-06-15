#!/usr/bin/env bash
# test_probe_orchestration.sh — WP-1 (S055 workflow-adoption keystone).
# Covers: version-gate boundaries, harness block, capability reads, the
# `context` matrix (+ host-id sub-variants), v1->v2 auto-migration,
# v1-consumer back-compat, session-ID keying + pruning, and the A-1 live canary
# (child inherits parent session ID).
#
# Self-contained: runs probe.sh against a private HOME so it never mutates the
# real ~/.claude/state. No network. No pytest dependency.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE="$SCRIPT_DIR/../scripts/probe.sh"

PASS=0
FAIL=0
ok()   { printf '  OK:   %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  FAIL: %s\n' "$1"; FAIL=$((FAIL+1)); }
check(){ if [ "$2" = "$3" ]; then ok "$1 ($3)"; else bad "$1 (want=$3 got=$2)"; fi; }

[ -x "$PROBE" ] || { echo "probe.sh not executable at $PROBE"; exit 1; }

# ── 1. version_ge boundaries (sourced; suppress the dispatcher) ──────────────
echo "== version_ge boundaries =="
vg() { CLAUDECODE= bash -c '
  # source only the function region by pulling the file but neutering main:
  eval "$(sed -n "/^version_ge()/,/^}/p" "'"$PROBE"'")"
  if version_ge "$1" "$2"; then echo ge; else echo lt; fi' _ "$1" "$2"; }

check "2.1.154 >= 2.1.154 (workflow boundary, eq)" "$(vg 2.1.154 2.1.154)" "ge"
check "2.1.153 >= 2.1.154 (just under)"            "$(vg 2.1.153 2.1.154)" "lt"
check "2.1.172 >= 2.1.154 (over)"                  "$(vg 2.1.172 2.1.154)" "ge"
check "2.1.31 >= 2.1.32 (teams boundary, under)"   "$(vg 2.1.31 2.1.32)"   "lt"
check "2.1.32 >= 2.1.32 (teams boundary, eq)"      "$(vg 2.1.32 2.1.32)"   "ge"
check "empty A fails closed"                       "$(vg '' 2.1.154)"      "lt"
check "junk A fails to 0.0.0 (lt)"                 "$(vg junk 2.1.154)"    "lt"
check "v-prefixed strip (v2.1.154 >= 2.1.154)"     "$(vg v2.1.154 2.1.154)" "ge"

# ── 2. context matrix ──────────────────────────────────────────────────────
echo "== context matrix =="
# NOTE: unset child markers explicitly — this test process may itself be a
# subagent that inherited CLAUDE_CODE_CHILD_SESSION (the very fact WP-1 detects).
check "main-loop"            "$(env -u CLAUDE_CODE_CHILD_SESSION -u CLAUDE_CODE_SUBAGENT CLAUDECODE=1 bash "$PROBE" context)" "main-loop"
check "child via CHILD_SESSION" "$(CLAUDECODE=1 CLAUDE_CODE_CHILD_SESSION=x bash "$PROBE" context)" "child-session"
check "child via SUBAGENT"   "$(CLAUDECODE=1 CLAUDE_CODE_SUBAGENT=1 bash "$PROBE" context)"         "child-session"
check "non-claude:codex"     "$(env -u CLAUDECODE CODEX_VERSION=0.139.0 bash "$PROBE" context)"     "non-claude-host:codex"
check "non-claude:copilot"   "$(env -u CLAUDECODE COPILOT_CLI=1 bash "$PROBE" context)"             "non-claude-host:copilot"
check "non-claude:vscode"    "$(env -u CLAUDECODE TERM_PROGRAM=vscode bash "$PROBE" context)"       "non-claude-host:vscode"
check "non-claude bare"      "$(env -u CLAUDECODE -u CODEX_VERSION -u COPILOT_CLI -u TERM_PROGRAM -u VSCODE_PID bash "$PROBE" context)" "non-claude-host"

# ── 3. harness block + capability reads against a private HOME ──────────────
echo "== harness block + capability reads =="
THOME="$(mktemp -d)"
trap 'rm -rf "$THOME"' EXIT
# Run a real probe under the private HOME. claude may/may not be present; we
# only assert structural shape + that get-API resolves the keys.
HOME="$THOME" CLAUDECODE=1 bash "$PROBE" check --force --silent >/dev/null 2>&1 || true
INV="$THOME/.claude/state/inventory.json"
if [ -f "$INV" ]; then
  check "inventory version == 2" "$(jq -r '.version' "$INV")" "2"
  HKEYS=$(jq -r '.harness | keys_unsorted | join(",")' "$INV" 2>/dev/null)
  if printf '%s' "$HKEYS" | grep -q 'workflow_tool' && printf '%s' "$HKEYS" | grep -q 'native_teams' \
     && printf '%s' "$HKEYS" | grep -q 'agent_spawn' && printf '%s' "$HKEYS" | grep -q 'claude_version'; then
    ok "harness has all 4 keys ($HKEYS)"
  else
    bad "harness keys incomplete ($HKEYS)"
  fi
  # workflow_tool/native_teams/agent_spawn are booleans (fail-closed when no claude)
  for k in workflow_tool native_teams agent_spawn; do
    v=$(jq -r ".harness.$k" "$INV")
    case "$v" in true|false) ok "harness.$k is boolean ($v)";; *) bad "harness.$k not boolean ($v)";; esac
  done
  # get-API: capabilities.workflow_tool resolves to a boolean
  cap=$(HOME="$THOME" CLAUDECODE=1 bash "$PROBE" get capabilities.workflow_tool 2>/dev/null)
  case "$cap" in true|false) ok "get capabilities.workflow_tool boolean ($cap)";; *) bad "get capabilities.workflow_tool ($cap)";; esac
else
  bad "no inventory produced under private HOME"
fi

# ── 4. v1 -> v2 auto-migration ─────────────────────────────────────────────
echo "== v1->v2 auto-migration =="
THOME2="$(mktemp -d)"
mkdir -p "$THOME2/.claude/state"
# Plant a FRESH (age 0) but v1 inventory.
cat > "$THOME2/.claude/state/inventory.json" <<'V1'
{"version":1,"last_probed":"2026-06-11T00:00:00Z","tools":{"claude":{"installed":true,"version":"2.1.173"},"git":{"installed":true,"version":"2.52.0"},"python3":{"installed":true,"version":"3.12.13"}},"tier":0,"tier_label":"minimal"}
V1
# No --force: the freshness conjunct must STILL re-probe because version < 2.
HOME="$THOME2" CLAUDECODE=1 bash "$PROBE" check --inventory-only --silent >/dev/null 2>&1 || true
NV=$(jq -r '.version' "$THOME2/.claude/state/inventory.json" 2>/dev/null)
check "fresh-but-v1 auto-migrates to v2" "$NV" "2"
jq -e '.harness' "$THOME2/.claude/state/inventory.json" >/dev/null 2>&1 \
  && ok "migrated inventory gained harness block" || bad "migrated inventory missing harness"
rm -rf "$THOME2"

# ── 5. v1-consumer back-compat (tools.* still present) ─────────────────────
echo "== v1-consumer back-compat =="
if [ -f "$INV" ]; then
  jq -e '.tools.claude' "$INV" >/dev/null 2>&1 && ok "tools.* still present (v1 consumers unbroken)" || bad "tools.* missing"
  jq -e '.tier' "$INV" >/dev/null 2>&1 && ok "tier still present" || bad "tier missing"
fi

# ── 6. session-ID keying + pruning + A-1 child inheritance ─────────────────
echo "== session keying + pruning + A-1 canary =="
THOME3="$(mktemp -d)"
RDIR="$THOME3/run"
mkdir -p "$RDIR"
SID="canary-$$"
# Parent probe with an explicit session id.
HOME="$THOME3" XDG_RUNTIME_DIR="$RDIR" CLAUDE_CODE_SESSION_ID="$SID" CLAUDECODE=1 \
  bash "$PROBE" check --silent >/dev/null 2>&1 || true
SF="$RDIR/env-adoption/session-$SID.json"
[ -f "$SF" ] && ok "session file keyed by CLAUDE_CODE_SESSION_ID" || bad "session file NOT keyed by CLAUDE_CODE_SESSION_ID (got $(ls "$RDIR/env-adoption/" 2>/dev/null))"
# A-1: a CHILD that inherits the same CLAUDE_CODE_SESSION_ID resolves the SAME
# session file (children share the parent's session state — the load-bearing
# fact that makes capabilities.* answer Q2-for-host only, never Q3-for-child).
# Verified behaviourally: a child probe with the inherited session id must NOT
# create a second session-*.json; it reuses the parent's exactly-one file.
BEFORE_COUNT=$(ls "$RDIR/env-adoption/"session-*.json 2>/dev/null | wc -l | tr -d ' ')
HOME="$THOME3" XDG_RUNTIME_DIR="$RDIR" CLAUDE_CODE_SESSION_ID="$SID" CLAUDE_CODE_CHILD_SESSION=child CLAUDECODE=1 \
  bash "$PROBE" check --silent >/dev/null 2>&1 || true
AFTER_COUNT=$(ls "$RDIR/env-adoption/"session-*.json 2>/dev/null | wc -l | tr -d ' ')
if [ -f "$SF" ] && [ "$BEFORE_COUNT" = "$AFTER_COUNT" ]; then
  ok "A-1: child inherits parent session-ID -> reuses same file (count stable $AFTER_COUNT)"
else
  bad "A-1: child created a distinct session file (before=$BEFORE_COUNT after=$AFTER_COUNT)"
fi
# pruning: an 8-day-old stale session file is deleted on next check.
touch -d '8 days ago' "$RDIR/env-adoption/session-STALE.json" 2>/dev/null || touch "$RDIR/env-adoption/session-STALE.json"
[ "$(uname)" = "Linux" ] && touch -d '8 days ago' "$RDIR/env-adoption/session-STALE.json"
HOME="$THOME3" XDG_RUNTIME_DIR="$RDIR" CLAUDE_CODE_SESSION_ID="$SID" CLAUDECODE=1 \
  bash "$PROBE" check --silent >/dev/null 2>&1 || true
[ -f "$RDIR/env-adoption/session-STALE.json" ] && bad "stale session file NOT pruned" || ok "stale session file pruned (>7d)"
rm -rf "$THOME3"

echo ""
echo "=================================="
echo "PASS=$PASS  FAIL=$FAIL"
echo "=================================="
[ "$FAIL" -eq 0 ]
