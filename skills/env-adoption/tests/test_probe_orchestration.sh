#!/usr/bin/env bash
# test_probe_orchestration.sh — WP-1 (S055 workflow-adoption keystone).
# Covers: version-gate boundaries, harness block, capability reads, the
# `context` matrix (+ host-id sub-variants), v1->v2 auto-migration,
# v1-consumer back-compat, session-ID keying + pruning, and the A-1 live canary
# (child inherits parent session ID).
#
# Self-contained: runs probe.sh against a private HOME so it never mutates the
# real ~/.claude/state. No pytest dependency. Section 7 (agy roster cache) is
# fully offline (stub agy on PATH). Sections 3/4/6 run whatever real tools are on
# PATH under the private HOME; they only assert structure, so a tool that needs
# the network (gh auth status, and since S081 WP-R05 `agy models`, time-boxed at
# 5s) may fail there without failing a check.

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

# ── 7. agy roster cache (S081 WP-R05, design §4.3 / I17) ────────────────────
# probe.sh writes ~/.claude/state/agy-models.json from `timeout 5 agy models
# < /dev/null` on the inventory-refresh path. Every case below runs against a
# STUB `agy` first on PATH and a private HOME + XDG_RUNTIME_DIR: offline, and
# the real ~/.claude/state is never touched. Negative controls pre-seed a cache
# and assert it is byte-identical afterwards AND that `agy models` was really
# attempted (stub log), so "unchanged" can never pass because nothing ran.
echo "== agy roster cache =="
T7="$(mktemp -d)"
trap 'rm -rf "$THOME" "$T7"' EXIT
STUB="$T7/stub-bin"
mkdir -p "$STUB"
cat > "$STUB/agy" <<'AGYSTUB'
#!/usr/bin/env bash
# Offline agy stub. AGY_STUB_MODE selects the `agy models` behaviour.
[ -n "${AGY_STUB_LOG:-}" ] && printf '%s\n' "$*" >> "$AGY_STUB_LOG"
roster() {
  printf 'Fetching available models...\n'
  printf 'gemini-4.1-argon-high\tGemini 4.1 Argon (High)\n'
  printf 'gemini-4.1-argon-medium\tGemini 4.1 Argon (Medium)\n'
  printf 'gemini-3.9-flash-high\tGemini 3.9 Flash (High)\n'
  printf '\n'
  printf 'gemini-3.8-flash-low\r\n'
  printf 'claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)\n'
  printf 'gemini-3.9-flash-high\tduplicate row\n'
  printf 'gpt-oss-120b-medium'
}
case "${1:-}" in
  --version) printf 'agy 9.9.9\n'; exit 0 ;;
  models)
    case "${AGY_STUB_MODE:-ok}" in
      ok)      printf 'Fetching available models...\n' >&2; roster; exit 0 ;;
      fail)    roster; exit 1 ;;
      sleep)   roster; sleep 30; exit 0 ;;
      empty)   exit 0 ;;
      garbage) printf 'Fetching available models...\nerror: not logged in\n\n'; exit 0 ;;
      stdin)   cat > /dev/null; roster; exit 0 ;;
    esac
    exit 2 ;;
esac
exit 0
AGYSTUB
chmod +x "$STUB/agy"
EXPECTED_MODELS='["gemini-4.1-argon-high","gemini-4.1-argon-medium","gemini-3.9-flash-high","gemini-3.8-flash-low","claude-sonnet-4-6","gpt-oss-120b-medium"]'
SEAT_MODEL="$SCRIPT_DIR/../../_meta/seat_model.py"

# new_home <name> -> a fresh private HOME (+ runtime dir); prints its path.
new_home() { local h="$T7/$1"; mkdir -p "$h/.claude/state" "$h/run"; printf '%s' "$h"; }
# probe7 <home> <mode> <path> <args...> -> runs probe.sh; sets RC, ELAPSED.
probe7() {
  local h="$1" mode="$2" p="$3"; shift 3
  local start=$SECONDS
  env HOME="$h" XDG_RUNTIME_DIR="$h/run" CLAUDECODE=1 PATH="$p" \
    AGY_STUB_MODE="$mode" AGY_STUB_LOG="$h/agy-calls.log" \
    timeout 90 bash "$PROBE" "$@" > "$h/probe.out" 2> "$h/probe.err"
  RC=$?
  ELAPSED=$((SECONDS - start))
}
cache_of()   { printf '%s/.claude/state/agy-models.json' "$1"; }
models_called() {  # how many times the stub ran `agy models` (0 when never invoked at all)
  if [ -f "$1/agy-calls.log" ]; then grep -c '^models$' "$1/agy-calls.log" || true; else echo 0; fi
}
leftovers()  { ls -A "$1/.claude/state" 2>/dev/null | grep -c '^\.agy-models' || true; }
seed_cache() {
  printf '{"schema":"agy-models.v1","fetched_at":"2000-01-01T00:00:00Z","agy_version":"seed","models":["gemini-0.1-flash-high"]}\n' > "$(cache_of "$1")"
}
sha_of() { sha256sum "$1" 2>/dev/null | cut -d' ' -f1; }
mode_of() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1" 2>/dev/null; }
age_hours() {  # age_hours <hours> <file>: set mtime <hours> in the past (GNU, then BSD)
  touch -d "$1 hours ago" "$2" 2>/dev/null || touch -t "$(date -v-"$1"H +%Y%m%d%H%M)" "$2"
}

# 7a. happy path — the default session-start invocation (full check, no --inventory-only).
H=$(new_home happy)
probe7 "$H" ok "$STUB:$PATH" check --force --silent
C=$(cache_of "$H")
check "7a probe exit code" "$RC" "0"
check "7a --silent stdout empty" "$(wc -c < "$H/probe.out" | tr -d ' ')" "0"
check "7a agy models called once" "$(models_called "$H")" "1"
if [ -f "$C" ]; then
  check "7a schema" "$(jq -r '.schema' "$C")" "agy-models.v1"
  check "7a models == exactly the parseable first-column slugs, in order, deduplicated" "$(jq -c '.models' "$C")" "$EXPECTED_MODELS"
  check "7a agy_version from this run's probe" "$(jq -r '.agy_version' "$C")" "9.9.9"
  if jq -r '.fetched_at' "$C" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'; then
    ok "7a fetched_at is ISO-8601 Z ($(jq -r '.fetched_at' "$C"))"
  else
    bad "7a fetched_at not ISO-Z ($(jq -r '.fetched_at' "$C"))"
  fi
  check "7a document keys" "$(jq -c 'keys' "$C")" '["agy_version","fetched_at","models","schema"]'
else
  bad "7a no agy roster cache written at $C"
fi
check "7a no temp files left in state dir" "$(leftovers "$H")" "0"
check "7a cache file mode matches inventory.json (umask, not mktemp's 0600)" \
  "$(mode_of "$C")" "$(mode_of "$H/.claude/state/inventory.json")"
# The consumer reads this exact format: seat_model resolves agy seats FROM the
# cache (4.1 is only in the stub roster; without the cache it would serve the
# gemini-4-argon harness literal). The stub also lists flash, which the agy family
# rule (model_roster.AGY_FAMILY) never selects.
check "7a seat_model consultant_main reads the cache" \
  "$(HOME="$H" PYTHONDONTWRITEBYTECODE=1 python3 "$SEAT_MODEL" argv --role consultant_main --provider agy 2>/dev/null)" \
  "--model gemini-4.1-argon-high"
check "7a seat_model consultant_support reads the cache" \
  "$(HOME="$H" PYTHONDONTWRITEBYTECODE=1 python3 "$SEAT_MODEL" argv --role consultant_support --provider agy 2>/dev/null)" \
  "--model gemini-4.1-argon-medium"

# 7b. negative controls: failure leaves a pre-seeded cache byte-identical.
for mode in fail sleep empty garbage; do
  H=$(new_home "neg-$mode")
  seed_cache "$H"
  age_hours 48 "$(cache_of "$H")"
  BEFORE=$(sha_of "$(cache_of "$H")")
  probe7 "$H" "$mode" "$STUB:$PATH" check --inventory-only --force --silent
  check "7b[$mode] probe exit code unchanged" "$RC" "0"
  check "7b[$mode] agy models was attempted" "$(models_called "$H")" "1"
  check "7b[$mode] pre-seeded cache byte-identical" "$(sha_of "$(cache_of "$H")")" "$BEFORE"
  check "7b[$mode] no temp files left" "$(leftovers "$H")" "0"
  [ -f "$H/.claude/state/inventory.json" ] && ok "7b[$mode] inventory still written" || bad "7b[$mode] inventory missing"
  if [ "$mode" = "sleep" ]; then
    # stub sleeps 30s; the 5s timeout must cut it well before that.
    if [ "$ELAPSED" -lt 25 ]; then ok "7b[sleep] finished in ${ELAPSED}s (< 25s; stub sleeps 30s)"; else bad "7b[sleep] took ${ELAPSED}s — timeout not enforced"; fi
  fi
done
# write error while building the document: a `jq` wrapper (first on PATH) emits a
# partial document and fails for the cache-build call only (`-R`, which nothing
# else in probe.sh passes) and delegates every other call to the real jq. The
# cache must stay byte-identical: the document is assembled in a temp file and
# renamed over the cache only when complete.
REAL_JQ="$(command -v jq)"
JQWRAP="$T7/jq-wrap-bin"
mkdir -p "$JQWRAP"
cat > "$JQWRAP/jq" <<JQSTUB
#!/usr/bin/env bash
for a in "\$@"; do
  if [ "\$a" = "-R" ]; then printf '{"schema":"agy-models.v1","models":["partial'; exit 5; fi
done
exec "$REAL_JQ" "\$@"
JQSTUB
chmod +x "$JQWRAP/jq"
H=$(new_home neg-write-error)
seed_cache "$H"
age_hours 48 "$(cache_of "$H")"
BEFORE=$(sha_of "$(cache_of "$H")")
probe7 "$H" ok "$JQWRAP:$STUB:$PATH" check --inventory-only --force --silent
check "7b[write-error] probe exit code unchanged" "$RC" "0"
check "7b[write-error] agy models was attempted" "$(models_called "$H")" "1"
check "7b[write-error] CONTROL: the rest of the probe used real jq (inventory tier written)" \
  "$(jq -r '.tier | type' "$H/.claude/state/inventory.json" 2>/dev/null)" "number"
check "7b[write-error] pre-seeded cache byte-identical" "$(sha_of "$(cache_of "$H")")" "$BEFORE"
check "7b[write-error] no temp files left" "$(leftovers "$H")" "0"

# failure with NO prior cache creates nothing.
H=$(new_home neg-absent)
probe7 "$H" fail "$STUB:$PATH" check --inventory-only --force --silent
check "7b[absent] probe exit code" "$RC" "0"
[ -e "$(cache_of "$H")" ] && bad "7b[absent] a cache appeared after a failed refresh" || ok "7b[absent] no cache created by a failed refresh"
check "7b[absent] no temp files left" "$(leftovers "$H")" "0"
# --json output stays valid on a failed refresh (nothing leaks onto stdout).
H=$(new_home neg-json)
probe7 "$H" garbage "$STUB:$PATH" check --inventory-only --force --json
check "7b[json] probe exit code" "$RC" "0"
check "7b[json] stdout is the inventory document" "$(jq -r '.inventory.tools.agy.installed' "$H/probe.out" 2>/dev/null)" "true"

# 7c. stdin: the stub blocks until stdin is at EOF. The probe runs with its OWN
# stdin a FIFO held open (never EOF), so a cache can only appear if probe.sh
# redirects `agy models` from /dev/null.
FIFO="$T7/stdin.fifo"
mkfifo "$FIFO"
exec 7<>"$FIFO"
timeout 3 env AGY_STUB_MODE=stdin "$STUB/agy" models 0<&7 >/dev/null 2>&1
check "7c NEGATIVE CONTROL: stub blocks on an open stdin (timeout exit)" "$?" "124"
timeout 3 env AGY_STUB_MODE=stdin "$STUB/agy" models </dev/null >/dev/null 2>&1
check "7c CONTROL: stub completes when stdin is at EOF" "$?" "0"
H=$(new_home stdin)
probe7 "$H" stdin "$STUB:$PATH" check --inventory-only --force --silent 0<&7
check "7c probe exit code" "$RC" "0"
check "7c cache written although the probe's own stdin never reaches EOF" "$(jq -c '.models' "$(cache_of "$H")" 2>/dev/null)" "$EXPECTED_MODELS"
exec 7>&-

# 7d. staleness (STALENESS_HOURS=24, honoured by --force). The inventory is
# removed first so the refresh path is guaranteed to run; its reappearance is
# the CONTROL that the path ran.
H=$(new_home fresh)
seed_cache "$H"
BEFORE=$(sha_of "$(cache_of "$H")")
probe7 "$H" ok "$STUB:$PATH" check --inventory-only --silent
[ -f "$H/.claude/state/inventory.json" ] && ok "7d[fresh] CONTROL: refresh path ran (inventory rewritten)" || bad "7d[fresh] refresh path did not run"
check "7d[fresh] cache younger than 24h: agy models NOT called" "$(models_called "$H")" "0"
check "7d[fresh] cache byte-identical" "$(sha_of "$(cache_of "$H")")" "$BEFORE"

H=$(new_home stale)
seed_cache "$H"
age_hours 25 "$(cache_of "$H")"
probe7 "$H" ok "$STUB:$PATH" check --inventory-only --silent
check "7d[stale] cache 25h old: agy models called" "$(models_called "$H")" "1"
check "7d[stale] cache refreshed" "$(jq -c '.models' "$(cache_of "$H")" 2>/dev/null)" "$EXPECTED_MODELS"

# boundary: integer hours, same rule as inventory_age_hours (< STALENESS_HOURS is fresh).
H=$(new_home age23)
seed_cache "$H"
age_hours 23 "$(cache_of "$H")"
probe7 "$H" ok "$STUB:$PATH" check --inventory-only --silent
check "7d[23h] cache 23h old: agy models NOT called" "$(models_called "$H")" "0"

H=$(new_home age24)
seed_cache "$H"
age_hours 24 "$(cache_of "$H")"
probe7 "$H" ok "$STUB:$PATH" check --inventory-only --silent
check "7d[24h] cache 24h old: agy models called" "$(models_called "$H")" "1"

H=$(new_home force)
seed_cache "$H"
probe7 "$H" ok "$STUB:$PATH" check --inventory-only --force --silent
check "7d[force] fresh cache + --force: agy models called" "$(models_called "$H")" "1"
check "7d[force] cache refreshed" "$(jq -c '.models' "$(cache_of "$H")" 2>/dev/null)" "$EXPECTED_MODELS"

H=$(new_home fresh-invalid)
printf '{"schema":"something-else"}\n' > "$(cache_of "$H")"
probe7 "$H" ok "$STUB:$PATH" check --inventory-only --silent
check "7d[fresh-invalid] a young but invalid cache is not trusted: refreshed" "$(jq -c '.models' "$(cache_of "$H")" 2>/dev/null)" "$EXPECTED_MODELS"

# 7e. no `timeout` on PATH: skip the refresh, never run agy unbounded.
FARM="$T7/no-timeout-bin"
mkdir -p "$FARM"
for f in /usr/bin/* /bin/*; do
  n="${f##*/}"
  [ "$n" = "timeout" ] && continue
  [ -e "$FARM/$n" ] || ln -s "$f" "$FARM/$n" 2>/dev/null
done
check "7e precondition: timeout absent from the test PATH" "$(env PATH="$STUB:$FARM" bash -c 'command -v timeout || echo absent')" "absent"
H=$(new_home no-timeout)
seed_cache "$H"
age_hours 48 "$(cache_of "$H")"
BEFORE=$(sha_of "$(cache_of "$H")")
start=$SECONDS
env HOME="$H" XDG_RUNTIME_DIR="$H/run" CLAUDECODE=1 PATH="$STUB:$FARM" \
  AGY_STUB_MODE=sleep AGY_STUB_LOG="$H/agy-calls.log" \
  /usr/bin/timeout 90 bash "$PROBE" check --inventory-only --force --silent > "$H/probe.out" 2> "$H/probe.err"
RC=$?
ELAPSED=$((SECONDS - start))
check "7e probe exit code" "$RC" "0"
check "7e CONTROL: agy (the stub) was detected as installed" "$(jq -r '.tools.agy.installed' "$H/.claude/state/inventory.json" 2>/dev/null)" "true"
check "7e agy models never run without timeout" "$(models_called "$H")" "0"
check "7e cache byte-identical" "$(sha_of "$(cache_of "$H")")" "$BEFORE"
if [ "$ELAPSED" -lt 25 ]; then ok "7e did not block (${ELAPSED}s)"; else bad "7e blocked for ${ELAPSED}s"; fi

# 7f. agy not installed: no cache, probe unaffected.
H=$(new_home no-agy)
check "7f precondition: agy absent from the test PATH" "$(env PATH="/usr/bin:/bin" bash -c 'command -v agy || echo absent')" "absent"
probe7 "$H" ok "/usr/bin:/bin" check --inventory-only --force --silent
check "7f probe exit code" "$RC" "0"
[ -e "$(cache_of "$H")" ] && bad "7f cache written although agy is not installed" || ok "7f no cache when agy is not installed"
check "7f inventory records agy not installed" "$(jq -r '.tools.agy.installed' "$H/.claude/state/inventory.json" 2>/dev/null)" "false"

echo ""
echo "=================================="
echo "PASS=$PASS  FAIL=$FAIL"
echo "=================================="
[ "$FAIL" -eq 0 ]
