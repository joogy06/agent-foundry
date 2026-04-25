---
name: project-state
description: Holistic deterministic projection over all source ledgers (contract-map, design-skeleton, flows, wiring, integration-ledger, process-observations). Single consolidated skill (Q6) with two ops — `reconcile` (hash-first freshness; mirrors wiring-reconcile lifecycle; emits transition request for bob to promote) and `query <op>` with 6 narrow ops (`focus_pack`, `orphans`, `next_buildable`, `by_status`, `impact`, `resolve`). Self-reports 5 observation classes (§3.8). Invoked on source-ledger write OR pre-transition OR session-start-if-stale OR query-if-stale.
---

# project-state (v1) — S028 ecosystem-keystone WP-11

**Design reference:** `/path/to/project/docs/plans/2026-04-23-ecosystem-keystone-design.md` section 3 (all 9 subsections).

## Purpose

Agents (bob, forge, alf) need *relevant* slices of project state without loading every ledger every turn. `project-state` is a deterministic projection generator + narrow query API over it. The projection is content-hashed against all source ledgers; queries validate the caller's input-hashes match projection's `generated_from[]` — if not, they reconcile before answering.

## When to invoke

- **Source-ledger write** — any bob-triggered write to `progress/contract-map.yaml`, `.wiring/latest.json`, `.design-ledger/skeletons/*.yaml`, `progress/flows.yaml`, `progress/integration-ledger.md`, `.process-observations/active.yaml` → `reconcile` (debounce 500ms for bursts).
- **Pre-transition** — bob cannot flip INTEGRATED or VERIFIED without a fresh projection; reconcile is BLOCKING per Q3.
- **Session start** — if `now - generated_at > freshness_window_s` OR no `latest.json`, reconcile opportunistically (warning on fail).
- **Query op self-heal** — if a query op sees caller-hashes differ from projection's `generated_from[]`, reconcile synchronously before answering (D10 MODIFIED hash-first primary).

## CLI

```bash
# Reconcile
python3 ~/.claude/skills/project-state/scripts/reconcile.py \
    --project-root <PROJECT_ROOT> \
    [--claim-uuid <UUID>] \
    [--skip-claim-check] [--skip-heartbeat] \
    [--force]

# Query
python3 ~/.claude/skills/project-state/scripts/query.py <op> \
    --project-root <PROJECT_ROOT> \
    [--no-self-heal]    # fail on stale projection instead of reconciling

# Ops:
python3 ~/.claude/skills/project-state/scripts/query.py focus_pack \
    --project-root <DIR> --uri <URI> \
    [--depth 2] [--ceiling 60000] \
    [--include-tests] [--include-observations]

python3 ~/.claude/skills/project-state/scripts/query.py orphans \
    --project-root <DIR>

python3 ~/.claude/skills/project-state/scripts/query.py next_buildable \
    --project-root <DIR> [--limit N]

python3 ~/.claude/skills/project-state/scripts/query.py by_status \
    --project-root <DIR> --status <S> [--modifier <M>]

python3 ~/.claude/skills/project-state/scripts/query.py impact \
    --project-root <DIR> --uri <URI>

python3 ~/.claude/skills/project-state/scripts/query.py resolve \
    --project-root <DIR> --uri <URI>
```

All outputs are canonical JSON on stdout (sorted keys, compact separators) so callers can hash stdout for caching (mirror of wiring-query convention).

## Output contracts

### `reconcile`

On idempotent no-op: returns projection_id unchanged, no rewrite.
On rebuild: emits `.project-state/runs/<run_id>/projection.json` (skill-owned scratch) + `.ledger/requests/<claim_uuid>.request.yaml` (transition request for bob-the-promoter).

### Query op surface

| Op | Signature | Semantics | Calls reconcile if stale |
|---|---|---|---|
| `focus_pack` | `--uri --depth --ceiling --include-tests --include-observations` | Relevance-strict BFS over PATH_EDGES; directive abort with `suggested_splits[]` when ceiling tripped | YES |
| `orphans` | (none) | List orphan URIs + reason + root_set_hash | YES |
| `next_buildable` | `[--limit N]` | URIs with all blocking[] VERIFIED | YES |
| `by_status` | `--status S [--modifier M]` | Filter entities by stage/modifier | YES |
| `impact` | `--uri U` | Reverse BFS over blocked_by + flow/test refs → retest set | YES |
| `resolve` | `--uri U` | `(path, jsonpointer, node)` — the ONLY op that skips freshness-check (pure read) | NO |

## Hard rules (do not violate)

- **Hash-first primary, wallclock defense-in-depth** (D10 MODIFIED). Any hash diff → reconcile. Wallclock 60s only catches `cp -p` edge where file bytes are stable but metadata was changed.
- **focus_pack ceiling abort is DIRECTIVE** — error carries `suggested_splits[]` for agent-teams, NOT blind truncation (D11 MODIFIED).
- **Reachability-based orphan detection** — BFS from visual entry points + `{cron, webhook, cli, api_public, test_harness, migration}` tagged roots (D8). Mutual-calls without entry → both orphans.
- **Tarjan SCC for build_order** — cycles land in `level: 99` with note + scc_id; projector does NOT refuse to emit.
- **Self-reports 5 observation classes** (Q5 resolved YES, §3.8):
  - Circular dep → `schema_mismatch` warning
  - Missing referenced file → `schema_mismatch` blocking
  - Unresolved URI → `flow_gap` blocking
  - Reconcile latency > 5s → `external_tool_slow` degraded (subject `project-state`)
  - HMAC verify fail on prior projection → `schema_mismatch` blocking
- **Single-writer discipline (CB4)**: skill writes to `.project-state/runs/<run_id>/projection.json` (skill-owned scratch); emits transition request `.ledger/requests/<claim_uuid>.request.yaml`; bob-the-promoter copies to `.project-state/latest.json` under `flock(.promote.lock, EX|NB)`. Skill does NOT write `.project-state/latest.json` directly.
- **Canonical JSON** everywhere — `json.dumps(obj, sort_keys=True, separators=(',',':'), ensure_ascii=False)`. HMAC reproducibility depends on this.
- **Fail-open claude_observe** — never let an observation write break reconcile.

## Files

```
project-state/
├── SKILL.md                        (this file)
├── schemas/
│   └── project-state.v1.json       JSON Schema for latest.json / runs/.../projection.json
├── scripts/
│   ├── reconcile.py                13-step lifecycle; mirrors wiring-reconcile/run.py
│   └── query.py                    6-op CLI; mirrors wiring-query/run.py
└── tests/
    └── test_project_state.py       TS-PS-01..07 (pytest with tmp_path)
```

## Exit codes

Reconcile:
- `0` — success (idempotent no-op OR new projection written).
- `1` — unrecoverable (missing source ledger, HMAC tamper detected, claim revoked).
- `2` — invalid CLI args.

Query:
- `0` — success.
- `1` — projection missing and `--no-self-heal`, OR stale and `--no-self-heal`, OR `resolve` not found.
- `2` — invalid CLI args.

## Drift canary

`ALDEBARAN-7` — shares canonical_json convention with wiring/HMAC pipeline. Any rearrangement breaks reproducibility.
