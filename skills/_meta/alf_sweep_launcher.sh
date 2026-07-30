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
# S055 supersession of the v1.1 headless stub: the headless print-mode launch
#     stub is DELETED. The alf-sweep workflow is journaled, budgeted, and read-only at the
#     finder level — the concurrent-writer hazard the (never-built) flock lease
#     was meant to guard never arises. #126 is RE-SCOPED to feed-write integrity
#     only (atomic write-rename for every JSON feed producer + a single-call flock
#     around the inventory-history append). See alf.md "#126 re-scope".
#
# Modes (S055):
#   --workflow : feature-detect capabilities.workflow_tool; if true, refresh feeds,
#                resolve tier->scope via _meta/sweep_scope.py, write the args file
#                (durable audit record with per-target feed excerpts + feed sha256),
#                and PRINT the Workflow({name:"alf-sweep", args:{...}}) invocation
#                block. If workflow_tool absent/false => print direct mode (exit 0).
#   --inline   : force the direct (print-the-prompt) path regardless of capability.
#
# Usage:
#   alf_sweep_launcher.sh <version|freshness|flow-pulse|full|flow-review> [scope] [--workflow|--inline]
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
shift || true

# S055: parse [scope] and the --workflow/--inline mode flag in any order.
SCOPE=""
MODE="auto"   # auto = feature-detect; workflow = force; inline = force direct
for arg in "$@"; do
  case "$arg" in
    --workflow) MODE="workflow" ;;
    --inline)   MODE="inline" ;;
    *)          SCOPE="$arg" ;;
  esac
done

# validate tier
case " $VALID_TIERS " in
  *" $TIER "*) : ;;
  *) die "unknown tier '$TIER'. One of: $VALID_TIERS" ;;
esac

# S055: feature-detect the workflow surface. `--workflow` forces it; `--inline`
# disables it; otherwise probe.sh decides. capabilities.workflow_tool is the ONLY
# capability API (no raw jq, no inline probing).
PROBE="$HOME/.claude/skills/env-adoption/scripts/probe.sh"
workflow_available() {
  [ "$MODE" = "inline" ] && return 1
  [ "$MODE" = "workflow" ] && return 0
  local cap
  cap=$(bash "$PROBE" get capabilities.workflow_tool 2>/dev/null) || cap="false"
  [ "$cap" = "true" ]
}

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
      # S074 (#217): NEW description collisions across the skill library. Exit 2 means
      # new pairs, which is a finding for the sweep to surface — not a launcher failure.
      python3 "$META_DIR/skill_overlap.py" --json \
        > "$HOME/.claude/state/skill-overlap.json" 2>/dev/null || true
    fi
    ;;
  full)
    if have_py; then
      bash "$HOME/.claude/skills/env-adoption/scripts/probe.sh" check --force --silent 2>/dev/null || true
      python3 "$META_DIR/rot_scan.py" >/dev/null 2>&1 || true
      python3 "$META_DIR/freshness.py" reindex >/dev/null 2>&1 || true
      # S054: advisory feed runs compare prod-shadow only — the prod-foundry
      # comparison (publish path-scrub makes the checker's own published copy
      # differ by design) belongs to the publish pipeline's strict check.
      python3 "$META_DIR/identity_check.py" --pair prod-shadow >/dev/null 2>&1 || true
      python3 "$META_DIR/skill_overlap.py" --json \
        > "$HOME/.claude/state/skill-overlap.json" 2>/dev/null || true
      refresh_note="all feeds refreshed"
    fi
    ;;
  flow-review)
    if have_py; then
      # S054: advisory feed runs compare prod-shadow only — the prod-foundry
      # comparison (publish path-scrub makes the checker's own published copy
      # differ by design) belongs to the publish pipeline's strict check.
      python3 "$META_DIR/identity_check.py" --pair prod-shadow >/dev/null 2>&1 || true
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

# ── S055 workflow mode: write the args file + print the Workflow invocation ──
if workflow_available; then
  RUN_DATE=$(date -u +%Y-%m-%d)
  RUN_LABEL="alf-sweep-${TIER}-$(date -u +%Y%m%dT%H%M%SZ)"
  ARGS_DIR="$STATE_FRESH"
  ARGS_PATH="$ARGS_DIR/sweep-args-${TIER}-${RUN_DATE}.json"
  mkdir -p "$ARGS_DIR"
  # Per-target feed sha256 hashes ride inside every finder prompt (changed feed
  # => changed prompt => cache miss). Computed at args-write time (same instant
  # as the refresh above). Scope resolution lives ONCE in _meta/sweep_scope.py.
  FEED_HASHES="{}"
  if have_py; then
    FEED_HASHES=$(python3 - "$TIER" "${feeds[@]}" <<'PYEOF'
import hashlib, json, os, sys
tier = sys.argv[1]
out = {}
for f in sys.argv[2:]:
    if os.path.isfile(f):
        out[f] = "sha256:" + hashlib.sha256(open(f, "rb").read()).hexdigest()
    else:
        out[f] = None
print(json.dumps(out))
PYEOF
)
  fi
  # Resolve tier spec (budget, finder model, verify arm) from the shared module.
  TIER_SPEC="{}"
  if have_py; then
    TIER_SPEC=$(python3 "$META_DIR/sweep_scope.py" "$TIER" 2>/dev/null || echo "{}")
  fi

  # S059 smart-config (NORMATIVE §7): resolve finder + verifier models caller-side via
  # the policy (workflow stages never read policy files — S055). Both alf sweep arms are
  # the 'light' tier (single-lens finders + cold-context cite-check), workflow surface.
  # Fail-open: a null/empty model leaves the field unset (the workflow inherits). The
  # resolver prints model:null on any failure, so MODEL_* stay empty and nothing breaks.
  RESOLVER="$HOME/.claude/skills/smart-config/scripts/model_policy.py"
  resolve_model() { # $1=reason -> prints model or empty
    have_py || return 0
    [ -f "$RESOLVER" ] || return 0
    python3 "$RESOLVER" resolve --tier light --surface workflow --reason "$1" --no-log 2>/dev/null \
      | python3 -c "import sys,json;
try:
    m=json.loads(sys.stdin.read().strip().splitlines()[-1]).get('model')
    print(m if m else '')
except Exception:
    print('')" 2>/dev/null || true
  }
  FINDER_MODEL_RESOLVED=$(resolve_model "alf sweep finder arm")
  VERIFIER_MODEL_RESOLVED=$(resolve_model "alf sweep verifier arm")
  RUN_STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  if have_py; then
    python3 - "$ARGS_PATH" "$TIER" "$RUN_STARTED_AT" "$RUN_LABEL" "$SCOPE" "$FEED_HASHES" "$TIER_SPEC" "$FINDER_MODEL_RESOLVED" "$VERIFIER_MODEL_RESOLVED" <<'PYEOF'
import json, sys
args_path, tier, started, label, scope, feed_hashes, tier_spec, finder_resolved, verifier_resolved = sys.argv[1:10]
spec = json.loads(tier_spec) if tier_spec else {}
# S059: policy-resolved models override the tier-spec defaults when present; an empty
# string (resolver returned null / failed) falls back to the spec default (fail-open).
finder_model = finder_resolved or spec.get("finder_model", "sonnet")
doc = {
    "sweep_id": label,
    "tier": tier,
    "run_started_at": started,
    "run_label": label,
    "scope": scope or None,
    "feed_sha256": json.loads(feed_hashes) if feed_hashes else {},
    "finder_model": finder_model,
    # verifier_model is NEW (S059 §7): undefined in the workflow => the verify arm
    # inherits (alf-sweep.js: model: args.verifier_model). Empty => omit the key.
    **({"verifier_model": verifier_resolved} if verifier_resolved else {}),
    "verify_arm": spec.get("verify_arm", "external-only"),
    "budget_tokens": spec.get("budget_tokens"),
    "targets": [],  # the in-session resolver fills these from the feeds at run time
}
import os
fd = os.open(args_path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
os.write(fd, (json.dumps(doc, indent=2) + "\n").encode())
os.close(fd)
os.replace(args_path + ".tmp", args_path)  # atomic write-rename (#126 re-scope)
PYEOF
    ARGS_SHA=$(python3 -c "import hashlib,sys; print('sha256:'+hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$ARGS_PATH" 2>/dev/null || echo "")
  fi
  cat <<EOF
========================================================================
alf evergreen sweep — tier: $TIER  (WORKFLOW MODE)
Feed refresh: ${refresh_note:-none}
Args file (durable audit record): $ARGS_PATH
========================================================================

Run this from the main loop (Claude Code >= 2.1.154):

Workflow({name: "alf-sweep", args: {
  args_path: "$ARGS_PATH",
  args_sha256: "${ARGS_SHA:-<compute>}",
  run_started_at: "$RUN_STARTED_AT",
  run_label: "$RUN_LABEL"
}})

The workflow returns an alf-sweep-summary.v1; the MAIN LOOP renders .alf/ from
it (the workflow writes ZERO .alf/ files). Feeds are launcher-frozen above.
========================================================================
EOF
  exit 0
fi

# ── print the ready-to-run alf prompt (direct / inline mode) ──
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

# S055: the v1.1 headless print-mode stub is DELETED (see header). The alf-sweep
# workflow (above) is the journaled, budgeted, read-only replacement; #126 is
# re-scoped to feed-write integrity only.

exit 0
