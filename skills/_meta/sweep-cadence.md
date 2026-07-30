# Sweep Cadence — the single source of tier truth (Evergreening v1, S041)

This is the canonical definition of alf's 5 evergreen sweep tiers (alf Format 4 /
Step 2g). alf.md deliberately carries NO tier detail — it reads this file. Bob's
`alf_sweep_launcher.sh` reads this file to assemble the ready-to-run prompt.

**Binding rule (alf HR5):** a sweep CONSUMES the pre-computed detection feeds; it does
NOT re-derive them (no re-running `--version` across CLIs, no re-research when the delta
already names the bump). Every finding cites its feed record (HR6). Sweeps SURFACE,
never FIX (HR7) — the only path to a change is a user-approved bob handoff.

## The 5 tiers

| Tier | Scope (which targets) | Feeds consumed | Cadence | Budget note | Nudge-eligible |
|---|---|---|---|---|---|
| **version** | only skills whose anchors/index reference the changed tool (2-5 typical) | `inventory-history.jsonl` delta + `drift-report.json` | event-driven (a cli/plugin version bump) | small (~20-40k tokens) | YES |
| **freshness** | RED/YELLOW rot findings + deadlines in horizon + UNANNOTATED count + NEW skill-description collisions | `rot-report.json` + `freshness/index.json` `by_deadline` + `skill-overlap.json` `new_pairs[]` | monthly-ish | small-medium | YES |
| **flow-pulse** | efficacy-rollup thresholds + open flow tasks (#115-#129 status) | `process-observation query.py rollup` + `tasks.md` | monthly | small (Step 2f already exists) | only on threshold breach (e.g. disagreement > 0.40) |
| **full** | whole library or a named family | all feeds + Steps 2a-2f per target | quarterly / post-batch | high | NO (calendar) |
| **flow-review** | `bob.md` / `alf.md` / forge / pa / `_meta` — the 2026-05-23 review, recurring | rollup + `identity-report.json` + the review-doc deadline anchor | quarterly | high | NO (deadline anchor on the review doc fires it) |

Flow-review recurrence is **independent of tool drift**: the 2026-05-23 orchestration
review doc carries a `FRESHNESS:v1 date_review` anchor (`review_by: 2026-08-23`), so the
**freshness** tier surfaces it quarterly regardless of platform changes.

## Feed locations (read-only inputs)

| Feed | Path | Producer |
|---|---|---|
| inventory + plugins/mcp | `~/.claude/state/inventory.json` | `env-adoption/scripts/probe.sh` |
| version change-records | `~/.claude/state/inventory-history.jsonl` | `env-adoption/scripts/inventory_history.py` |
| rot report | `~/.claude/state/freshness/rot-report.json` | `_meta/rot_scan.py` |
| skill overlap | `~/.claude/state/skill-overlap.json` | `_meta/skill_overlap.py --json` |
| deadline / by_tool index | `~/.claude/state/freshness/index.json` | `_meta/freshness.py reindex` |
| drift report | `~/.claude/state/freshness/drift-report.json` | `affordance-advisor/scripts/drift_runner.py` |
| identity (3-tree) | `~/.claude/state/freshness/identity-report.json` | `_meta/identity_check.py` |
| efficacy rollup | (computed on demand) | `process-observation/scripts/query.py rollup` |

## Per-tier feed-refresh preamble (what the launcher runs before the sweep)

A sweep consumes feeds; if a feed is stale the launcher refreshes it FIRST (these are
the only "compute" steps — the sweep itself does no re-derivation):

- **version**: `probe.sh check --force` (appends the change-record) → `drift_runner.py` for the changed CLI only.
- **freshness**: `rot_scan.py --refresh` (if `rot-report.json` mtime > 7 days) → `freshness.py reindex` → `skill_overlap.py --json`.
- **flow-pulse**: nothing to refresh — `query.py rollup` is computed live.
- **full**: `probe.sh check --force` + `rot_scan.py --refresh` + `freshness.py reindex` + `identity_check.py`.
- **flow-review**: `identity_check.py` + `query.py rollup`.

`rot_scan` and `identity_check` are ~0.5-1s each; they run at sweep time (or via
`rot_scan.py --refresh`), NEVER inline at SessionStart (the nudge only READS the reports).

## Tier → scope resolution detail

- **version scope**: read `freshness/index.json` `by_tool[<changed-tool>]` for the
  FRESHNESS-annotated files, UNION the `rot-report.json` findings whose `detail`
  names the tool. Typically 2-5 files. If `by_tool` is empty (no FRESHNESS retrofit
  yet), fall back to the rot-report tool findings alone.
- **freshness scope**: every `rot-report.json` finding with verdict RED or YELLOW, plus
  the `by_deadline` entries within horizon. UNANNOTATED is a count only (advisory; a
  skill with no anchors is never RED — never auto-flagged for a refresh).
- **flow-pulse scope**: the 4 efficacy metrics + the open flow tasks (#115-#129).
  Only escalate to a finding on a threshold breach (the Step 2f honesty gates apply).
- **full scope**: a named family (`alf --sweep full ms-office`) or the whole library.
- **flow-review scope**: the orchestration spine — `bob.md`, `alf.md`, `forge/`, `pa.md`,
  `_meta/` — re-scoring #115-#129 against current telemetry.

## Budget posture (cost fields reserved — #124)

Cost/token capture is deferred to #124 (the cost-plumbing owner). Sweep reports
reserve `tokens_spent: null` until then. The "budget note" column is qualitative
guidance for the user deciding whether to run a tier now.

## v1.1 deferrals (do NOT implement in v1)

- **headless `--headless`** launcher (gate: #126 flock lease) — stub only in the launcher.
- **sweep cost fields** populated (gate: #124 plumbing).
- **pa MCP mirror** of deadline reminders (v1 writes `tasks.md` only — F1).
