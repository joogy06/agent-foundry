---
name: process-observation
description: Use when emitting, querying, or rotating process-level friction observations from any skill, agent, gate, or external tool. Provides the `claude-observe` CLI one-liner, Python API `claude_observe()`, and query/sweep/compaction primitives over a two-file ledger (`active.yaml` aggregate + `events.jsonl` truth log). BEST-EFFORT writes - never raise to the caller. 13-category closed-set taxonomy. Ships with 14-day active retention, indefinite compressed stale retention, 180-day hashed event summaries, and write-time anonymization for the cross-project global rollup. S039 efficacy-telemetry extension - a gate-run denominator writer (`gate-runs.jsonl` sidecar) plus a read-only `query.py rollup` op that computes the four orchestration-efficacy metrics (gate-fail / false-positive / dual-verdict-disagreement / user-override) for alf sweeps.
---

# Process Observation - Feedback Ledger

## Overview

Single source of truth for cross-skill friction: gate false blocks, skill bugs,
agent drift, flow gaps, schema mismatches, external tool failures, timeouts,
environment limits, context overflows, recursive loops, and deprecation
surfaces. Every auto-hook writes through this skill so alf, pa, and operators
have one place to ask "what is painful this week?".

Two-file layout (both sources of truth):

- `active.yaml` - aggregate keyed by `dedup_key` (count, last_seen, evidence_tail)
- `events.jsonl` - append-only truth log (regenerable on active.yaml corruption)

Cold storage:

- `stale.yaml` - demoted (14d aged OR resolved), compressed, indefinite retention
- `summaries/<YYYY-MM>.jsonl` - hashed monthly summary of raw events older than 30 days, retained 180 days
- `~/.claude/state/observations.jsonl` - write-time anonymized cross-project rollup

Efficacy-telemetry sidecar (S039 extension — separate from the friction ledger):

- `gate-runs.jsonl` - append-only gate-run denominator log (one bump + one outcome record per gate invocation). NEVER `active.yaml` — the 13-category friction taxonomy is untouched, zero schema bump.
- `.telemetry_window` - sentinel recording `denominator_window_start` (first-bump ISO timestamp; forward-looking, never backfilled).

## When to Use

- A gate/skill/agent observed friction that should be visible to operators
- An external tool (codex/gemini/copilot) returned malformed / slow / non-zero
- A schema mismatch, HARD-RULE deviation, or flow gap was detected
- You need to ask "show me hot observations in the last 7 days"
- A daily cron or session-start hook needs to rotate/compact/age-out the ledger

## When NOT to Use

- Do not use for task-management - use `pa` or `tasks.md`
- Do not use as an authoritative gate signal - observation writes are diagnostic only; the gate exit code is authoritative
- Do not hand-write `.process-observations/active.yaml` - always go through `claude-observe` (dedup + atomicity + session tracking)
- Do not catch exceptions from `claude_observe()` - it already swallows everything; treating it as raising is an anti-pattern

## Public API

### Shell CLI

```bash
claude-observe <category> "<what_happened>" \
  [--subject=<id>] [--subject-type=agent|skill|gate|external_tool|schema|env] \
  [--severity=blocking|degraded|slow|noisy] \
  [--dedup-key=<explicit>] [--fingerprint=<hex>] \
  [--session=<id>] \
  [--root-cause="..."] [--suggested-fix="..."] \
  [--related=task://43,uri://component-x,file://path]
```

Exit 0 on success; exit 0 on *swallowed-failure* (never raises). Stderr carries diagnostics when things go wrong.

### Python API

```python
from process_observation.scripts.write import claude_observe

claude_observe(
    category,              # one of 13 closed-set values below
    subject_id,
    what_happened,
    *,
    fingerprint=None,
    subject_type="agent",  # agent | skill | gate | external_tool | schema | env
    severity="degraded",   # blocking | degraded | slow | noisy
    session_id=None,
    related=None,
    root_cause_hypothesis=None,
    suggested_fix=None,
)  # BEST-EFFORT; returns None; never raises
```

### Query operations

```bash
python3 ~/.claude/skills/process-observation/scripts/query.py hot \
    --threshold=5 --window=7d --min-severity=degraded \
    [--project-root=<dir>]
python3 ~/.claude/skills/process-observation/scripts/query.py stats
python3 ~/.claude/skills/process-observation/scripts/query.py subject:bob
python3 ~/.claude/skills/process-observation/scripts/query.py category:gate_false_block
python3 ~/.claude/skills/process-observation/scripts/query.py session:<id>
python3 ~/.claude/skills/process-observation/scripts/query.py since:2026-04-01
python3 ~/.claude/skills/process-observation/scripts/query.py rollup \
    --project-root=<dir> --window=7d --format=json|text
```

Output is canonical JSON (sorted keys, compact). Severity thresholds for `hot`
per D12: blocking=2, degraded=5, slow=10, noisy=20.

### Sweep / rotate / compact

```bash
python3 ~/.claude/skills/process-observation/scripts/sweep.py [--project-root=<dir>] [--force]
python3 ~/.claude/skills/process-observation/scripts/compact_events.py [--project-root=<dir>]
bash   ~/.claude/skills/process-observation/scripts/rotate_and_age.sh <project_root>
```

Sweep is idempotent for 24 hours via a `.last_sweep` sentinel (mirrors `env-adoption` pattern).

## The 13-Category Closed-Set Taxonomy

New category = v2 schema bump. The vocabulary is deliberately small.

| Category | Fires when | NOT this (boundary) |
|---|---|---|
| `gate_false_block` | Gate returns non-zero on input a human would accept | `skill_bug` - skill internal logic wrong |
| `gate_false_pass` | Gate returns 0 on input provably invalid (retroactively discovered) | `schema_mismatch` - two schemas disagree |
| `skill_bug` | Skill observable behavior contradicts its SKILL.md contract | `skill_incomplete` - contract says X, code is stub |
| `skill_incomplete` | SKILL.md promises capability; implementation raises or no-ops | `skill_bug` - capability present but wrong |
| `agent_drift` | Agent violates its own HARD-RULE (attempted, even if refused) | `flow_gap` - no rule covers the situation |
| `flow_gap` | Process step missing entirely (no one owns X handoff) | `skill_incomplete` - a specific skill is the gap |
| `schema_mismatch` | Two ledgers disagree on URI/shape OR consumer expects vN sees vN-1 | `gate_false_pass` - data invalid by spec |
| `external_tool_fail` | Codex/Gemini/Copilot returns malformed/unusable/hallucinated | `external_tool_slow` - returned OK but late |
| `external_tool_slow` | Tool returned valid output but exceeded reasonable wall (>60s default) | `context_overflow` - tool ran OOM on input |
| `environment_limit` | Sandbox/permission/egress denied | `external_tool_fail` - tool itself broke |
| `context_overflow` | Task needed > ceiling (focus_pack > 60k per D11) | `skill_incomplete` - contract did not anticipate |
| `recursive_loop` | Skill invokes itself transitively (cycle detected) | `flow_gap` - step missing, not repeating |
| `deprecation_surfaced` | Old API leaking into new work (caller uses retired signature) | `schema_mismatch` - versions diverge actively |

Decision tiebreakers:

- `gate_false_block` vs `gate_false_pass`: `gate_false_pass` is strictly worse (silent). Auto-severity = `blocking`. When unsure, prefer `gate_false_pass` for higher attention.
- `agent_drift` vs `flow_gap`: named HARD-RULE violated -> drift; no rule exists -> flow_gap.
- `schema_mismatch` vs `flow_gap`: concrete file with `schema_version` -> mismatch; nothing authoritative -> flow_gap.

## Dedup Key Algorithm

```python
dedup_key = re.sub(r"[^a-z0-9:_-]", "-",
                   f"{category}:{subject_id}:{fingerprint}".lower())[:120]
# fingerprint = caller-supplied, else sha256(what_happened)[:8]
```

Auto-writers MUST specify `fingerprint` to prevent collapse/explosion:

- Gate failures -> `fingerprint = <gate_name>` (all G1 refusals collapse to one record)
- HARD-RULE deviations -> `fingerprint = "hardrule-<n>"` (one record per rule)
- External tool failures -> `fingerprint = <error_class>` (`timeout`, `malformed_output`, `returncode-2`) NOT full stderr
- Challenges -> `fingerprint = <reason>` (one of 4 closed-set reasons)

Manual `claude-observe` writes may omit `--fingerprint` and let the
auto-fingerprint (sha256 of what_happened) do the work.

## Invariants

- BEST-EFFORT: `claude_observe()` never raises. Everything wrapped in `try/except`; failure logs to stderr only. The caller sees `None` in Python / exit 0 in shell.
- Self-referential guard: observation about `subject_id == "process-observation"` is logged to stderr only; never persisted (prevents infinite loops on retention/compaction bugs).
- events.jsonl writes are lock-free `O_APPEND` (POSIX atomic for records < 4KB); active.yaml writes hold `.write.lock`.
- Sweep and write locks are separate (`.write.lock` vs `.sweep.lock`) - writers never wait on sweep.
- Retention: 14 days active -> stale (indefinite, compressed). 30 days raw events -> monthly hashed summary -> 180 days summaries.
- Global rollup is anonymized at write time (not query time): `subject.id` dropped to `subject_type`; paths, UUIDs, and quoted strings redacted.

## Project-Root Discovery

Walks up from `$CWD`:

1. `.process-observations/` directory
2. `PROJECT.md`
3. `.git/`
4. None found -> stderr warn and write to global rollup only

Session id: `$CLAUDE_SESSION_ID` -> `$FORGE_SESSION_ID` -> cached
`$XDG_RUNTIME_DIR/claude/session` -> `ppid-<PPID>` fallback.

## Efficacy Telemetry (S039 extension)

A pure extension that measures whether the `forge→bob→alf→pa` orchestration
machinery catches real defects or just adds ceremony. Two parts:

### 1. Gate-run denominator writer (`scripts/gate_runs.py`)

Loaded by `_meta/gates.py` via a fail-open loader (no-op stubs on ImportError,
mirrors the existing `claude_observe` loader). In `gates.py main()`: a
PRE-dispatch `bump_gate_run(gate)` (never-raises) plus a `try/except SystemExit`
that records the terminal exit code and **re-raises the identical SystemExit** —
gate control flow and exit code are provably unchanged. Both helpers wrap their
entire body in `try/except BaseException`. The denominator lands in the
`gate-runs.jsonl` sidecar, NEVER `active.yaml` (zero friction pollution).

Record shape (lock-free `O_APPEND`, like `events.jsonl`):
```json
{"ts":"2026-06-03T10:00:00Z","gate":"G1","run_id":"<uuid4>","code":0}
```
`code` is the **raw normalized exit code** (int) the `SystemExit` carried, or
`null` (a run killed before the terminal exit was caught — counted in the
denominator, excluded from outcome tallies). The bump writes `code:null`; the
outcome appends a second record with the same `run_id` carrying the real code.
Classification happens at READ time in the rollup — the writer never derives a
label, so changing a gate's exit semantics only updates the rollup's policy
table, never the write path.

### 2. Read-only rollup (`scripts/rollup.py`, op `query.py rollup`)

```bash
python3 ~/.claude/skills/process-observation/scripts/query.py rollup \
    --project-root <dir> --window 7d [--format json|text]
```

Pure read — writes NOTHING under `.ledger/` or `.process-observations/`.
Computes four metrics into an `efficacy-rollup.v1` object; every metric prints
`{numerator, denominator, rate, ...}` plus `denominator_window_start` and
coverage flags:

| Metric | Source | Honesty caveat surfaced |
|---|---|---|
| `gate_fail_rate` | `gate-runs.jsonl` | fail = exit **2 only**; exit 3 (advisory/env-error) and 4 (skip) broken out as separate tallies, NOT counted as fail (§6.1 policy table) |
| `false_positive_rate` | `events.jsonl` `gate_false_block` / `gate-runs.jsonl` | UPPER BOUND ("blocked", not "blocked AND human-accepted"); numerator exists for only **6 of 12 gates** — others report null + `no_false_block_numerator` |
| `dual_verdict_disagreement_rate` | `.ledger/verdicts/*.verdict.yaml` | reads **`audit_arm.result` + `arbiter_arm.verdict` ONLY** (asymmetric canonical keys); ignores the `claude_verdict`/`codex_verdict` decoy sub-vocabulary; never substring-greps for `AUDIT_UNAVAILABLE` (it can appear in a free-text rerun-history field while the canonical result is `REJECTED`). AUDIT_UNAVAILABLE on a canonical key → indeterminate, excluded from denominator (N1) |
| `user_override_rate` | `.ledger/scope-deltas/*.yaml` | counts `status ∈ {amended, excluded}`; `--no-verify` (git layer) and escalation-override have no code hook → reported `not_yet_instrumented`, never faked |

The denominator is **forward-looking only** (no backfill) — `denominator_window_start`
is surfaced so a too-young baseline is self-evident. alf reads this rollup during
sweeps (alf Step 2f) with honesty-gated thresholds.

## References

- Design: `docs/plans/2026-04-23-ecosystem-keystone-design.md` section 4 (all subsections)
- Decisions: D12 (retention), D13 (dedup), D14 (closed-set taxonomy), D15 (anonymization), D16 (best-effort)
- Contract: `progress/contract-map.yaml` (`process-observation` component, TS-OBS-01..07)
- Efficacy extension (S039): `docs/plans/2026-06-03-efficacy-telemetry-v1-design.md` (§5 store layout, §6 metrics, §7 gate hook, §8 rollup CLI, §9 honest limits). Tests: `tests/test_gate_run_telemetry.py` (WP1 exit-code-invariance ship-gate), `tests/test_efficacy_rollup.py` (WP2 four metrics + N1 + parse guards).
