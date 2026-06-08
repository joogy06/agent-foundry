#!/usr/bin/env bash
# alf_sweep_launcher.sh — assemble + print the ready-to-run alf evergreen sweep prompt.
#
# Part of Ecosystem Evergreening v1 (S041). The SessionStart digest ends with either
# "say 'run the version sweep'" (in-session, zero-paste — the session spawns alf with
# the assembled prompt) OR this launcher (the explicit, copy-paste path).
#
# v1: launcher.sh <tier> reads _meta/sweep-cadence.md, refreshes any stale feed, and
#     PRINTS the ready-to-run alf prompt with the feed paths + target scope inlined.
#     It does NOT spawn alf itself (the in-session "run the version sweep" path does).
#
# v1.1 (STUB ONLY — do NOT implement in v1): a --headless flag would drive
#     `claude -p "$PROMPT" --max-budget-usd <cap>` with a lockfile, stderr capture, a
#     success marker, and a visible-failure task. GATED ON #126's flock lease — the
#     stub below is commented out and must stay that way until #126 lands.
#
# Usage:
#   alf_sweep_launcher.sh <version|freshness|flow-pulse|full|flow-review> [scope]
#   alf_sweep_launcher.sh --list          # show the tiers
#
# stdlib bash + the evergreening engines only. Deterministic. Prints to stdout.

set -euo pipefail

META_DIR="$HOME/.claude/skills/_meta"
STATE_FRESH="$HOME/.claude/state/freshness"
INVENTORY="$HOME/.claude/state/inventory.json"
HISTORY="$HOME/.claude/state/inventory-history.jsonl"
CADENCE="$META_DIR/sweep-cadence.md"

die() { printf 'alf_sweep_launcher: %s\n' "$1" >&2; exit 1; }

VALID_TIERS="version freshness flow-pulse full flow-review"

usage() {
  cat <<EOF
alf_sweep_launcher.sh — print the ready-to-run alf evergreen sweep prompt

Tiers (see $CADENCE for the full definition):
  version      event-driven; skills referencing a just-changed CLI
  freshness    monthly-ish; RED/YELLOW rot findings + deadlines in horizon
  flow-pulse   monthly; efficacy-rollup thresholds + open flow tasks
  full         quarterly; whole library or a named family
  flow-review  quarterly; the orchestration spine (bob/alf/forge/pa/_meta)

Usage:
  alf_sweep_launcher.sh <tier> [scope]
  alf_sweep_launcher.sh --list
EOF
}

[ $# -ge 1 ] || { usage; exit 2; }

if [ "$1" = "--list" ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  usage
  exit 0
fi

TIER="$1"
SCOPE="${2:-}"

# validate tier
case " $VALID_TIERS " in
  *" $TIER "*) : ;;
  *) die "unknown tier '$TIER'. One of: $VALID_TIERS" ;;
esac

# ── feed-refresh preamble (the only "compute" steps; the sweep does no re-derivation) ──
# Each is best-effort: a refresh failure must not block the launcher from printing.
refresh_note=""
have_py() { command -v python3 >/dev/null 2>&1; }

rot_stale() {
  # true if rot-report missing or older than 7 days
  local f="$STATE_FRESH/rot-report.json"
  [ -f "$f" ] || return 0
  local age_days
  age_days=$(( ( $(date +%s) - $(stat -c %Y "$f" 2>/dev/null || echo 0) ) / 86400 ))
  [ "$age_days" -gt 7 ]
}

case "$TIER" in
  version)
    if have_py; then
      bash "$HOME/.claude/skills/env-adoption/scripts/probe.sh" check --force --silent 2>/dev/null || true
      refresh_note="probe.sh --force (history appended)"
    fi
    ;;
  freshness)
    if have_py; then
      if rot_stale; then
        python3 "$META_DIR/rot_scan.py" >/dev/null 2>&1 || true
        refresh_note="rot_scan refreshed (was stale)"
      else
        refresh_note="rot-report fresh (<7d) — not re-run"
      fi
      python3 "$META_DIR/freshness.py" reindex >/dev/null 2>&1 || true
    fi
    ;;
  full)
    if have_py; then
      bash "$HOME/.claude/skills/env-adoption/scripts/probe.sh" check --force --silent 2>/dev/null || true
      python3 "$META_DIR/rot_scan.py" >/dev/null 2>&1 || true
      python3 "$META_DIR/freshness.py" reindex >/dev/null 2>&1 || true
      python3 "$META_DIR/identity_check.py" >/dev/null 2>&1 || true
      refresh_note="all feeds refreshed"
    fi
    ;;
  flow-review)
    if have_py; then
      python3 "$META_DIR/identity_check.py" >/dev/null 2>&1 || true
      refresh_note="identity_check refreshed; rollup computed live"
    fi
    ;;
  flow-pulse)
    refresh_note="nothing to refresh — rollup computed live"
    ;;
esac

# ── assemble feed-path list for the prompt ──
feeds=()
case "$TIER" in
  version)     feeds=("$HISTORY" "$STATE_FRESH/drift-report.json") ;;
  freshness)   feeds=("$STATE_FRESH/rot-report.json" "$STATE_FRESH/index.json") ;;
  flow-pulse)  feeds=("(query.py rollup — computed live)" "tasks.md") ;;
  full)        feeds=("$INVENTORY" "$HISTORY" "$STATE_FRESH/rot-report.json" "$STATE_FRESH/index.json" "$STATE_FRESH/drift-report.json" "$STATE_FRESH/identity-report.json") ;;
  flow-review) feeds=("$STATE_FRESH/identity-report.json" "(query.py rollup — computed live)") ;;
esac

feed_lines=""
for f in "${feeds[@]}"; do
  feed_lines="${feed_lines}  - ${f}"$'\n'
done

# ── print the ready-to-run alf prompt ──
cat <<EOF
========================================================================
alf evergreen sweep — tier: $TIER
Feed refresh: ${refresh_note:-none}
========================================================================

Copy-paste this to alf (or just say "run the $TIER sweep" in-session):

----------------------------------------------------------------------
alf --sweep $TIER ${SCOPE:+$SCOPE }--feeds $STATE_FRESH

Tier definition: $CADENCE  (Step 2g routing)
Detection feeds to consume (read-only; HR5 — do NOT re-derive):
${feed_lines}
Rules: HR5 (consume feeds, never re-run --version) · HR6 (every finding cites
its feed record) · HR7 (surface, never fix — report + idempotent tasks.md rows
+ handoffs; the only path to a change is a user-approved bob handoff).
----------------------------------------------------------------------
EOF

# ── v1.1 STUB — headless launch (GATED ON #126 flock lease; do NOT implement) ──
# if [ "${HEADLESS:-0}" = "1" ]; then
#   # Requires #126's flock workspace lease to be safe against concurrent writers.
#   # LOCK="$STATE_FRESH/.sweep-$TIER.lock"
#   # exec 9>"$LOCK"; flock -n 9 || die "another sweep holds the lease"
#   # claude -p "$PROMPT" --max-budget-usd "${SWEEP_BUDGET_USD:-2.00}" \
#   #   2> "$STATE_FRESH/sweep-$TIER.stderr" && touch "$STATE_FRESH/sweep-$TIER.ok" \
#   #   || { echo "headless sweep FAILED — see stderr" >&2; exit 1; }
#   die "--headless is a v1.1 stub (gated on #126 flock lease); not implemented in v1"
# fi

exit 0
