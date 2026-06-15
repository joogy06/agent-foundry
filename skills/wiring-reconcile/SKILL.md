---
name: wiring-reconcile
description: Merge per-run source artifacts (`static.jsonl` + per-agent `asserted/<agent_id>.jsonl` + optional `manual.jsonl`) into a run-scoped `snapshot.json` conforming to `wiring-snapshot.v1` (v1.1 adds per-component `intent` blocks via `intent_merge`). Single writer of reconciled snapshots. Does NOT promote to `latest.json` — bob does, atomically under flock. Deterministic Python, no LLM calls. Invoked by bob with a claim UUID; heartbeats every 60s via `_meta/claims.py`.
---

# wiring-reconcile (v1.1)

**Status:** SHIPPED. WP-1 (snapshot schema + `edge_identity.py`) landed S023; WP-4/5/6 (assertion inbox, reconciler core, atomic promote) landed 2026-04-15; S032 WP-3 added the v1.1 `intent` extension (`intent_merge.py`, 2026-05-14). 10 test files cover the surface, including determinism and concurrent-promote tests.

**Design documents:**
- `/path/to/project/docs/plans/2026-04-14-wiring-skills-design.md` §5.2 + §6 (WP-4, WP-5, WP-6)
- `/path/to/project/docs/plans/2026-05-13-evo-agent-design.md` §4.4 + WP-3 (v1.1 intent extension)

## Purpose

Take everything a wiring run produced — static extractor edges, per-agent assertions, optional manual edges — and merge them into ONE deterministic, schema-valid `snapshot.json` inside the run directory. Reconcile never touches `latest.json`; promotion is bob's job (via the `promote.py` library shipped here).

## Lifecycle (`scripts/run.py`)

1. Validate the bob-issued claim (`.ledger/claims/<uuid>.claim.yaml` via `_meta/claims.py classify_claim`).
2. Start a daemon heartbeat thread (60 s poll via `_meta/claims.py heartbeat_claim`; any non-`ok` state stops the skill).
3. Read `.wiring/runs/<run_id>/manifest.json`; abort if any source is non-terminal (`in_progress`).
4. Read `static.jsonl` — each line schema-validated against `wiring-source-edge.v1`; malformed/invalid lines are logged + skipped, never fatal.
5. Read all `asserted/<agent_id>.jsonl` through `assertion_inbox` (see below).
6. Read optional `manual.jsonl` (`evidence_source` forced to `manual`).
7. Load suppressed edge ids from `--config` YAML (`reconcile.suppress_edge_ids`), previous snapshot (read-only, from `.wiring/latest.json`, for staleness), and contract-map binding (`contract_map_hash` + `contract_map_revision` from `progress/contract-map.yaml`).
8. `reconciler.reconcile()` → in-memory snapshot dict (`snapshot_generation` provisional `1`; bob rewrites it on promote).
9. Schema-validate against `schemas/wiring-snapshot.v1.json`; exit 1 on violations.
10. Atomic write `.wiring/runs/<run_id>/snapshot.json` via `snapshot_writer`.
11. Emit transition request `.ledger/requests/<claim_uuid>.request.yaml` (target stage `INTEGRATED`, includes snapshot statistics + assertion-inbox stats).
12. Exit 0. Unrecoverable failures (missing run dir/manifest, revoked claim, schema-invalid snapshot) exit 1 with log.

## CLI

```bash
python3 ~/.claude/skills/wiring-reconcile/scripts/run.py \
    --project-dir $PROJECT_DIR \
    --run-id <run_id> \
    --claim-uuid <uuid> \
    [--config path/to/config.yaml] \
    [--log-level INFO]
```

Test-harness flags (never used in production): `--skip-heartbeat`, `--skip-claim-check`.

Exit codes: `0` success, `1` unrecoverable failure.

## Scripts

| Script | Role |
|---|---|
| `edge_identity.py` | **Single source of truth** for `edge_id` — first 16 hex of sha256(canonical-json five-tuple `(src_component, src_symbol, dst_component, dst_symbol, edge_kind)`). Imported by `wiring-extract-static` AND this skill; no other file computes edge_ids. |
| `assertion_inbox.py` | Read-only library that normalizes `asserted/<agent_id>.jsonl` files: validates every line against `wiring-source-edge.v1`, enforces canonical component naming against contract-map component ids (unmapped src/dst → skip + count), annotates `_agent_id` provenance, and FORCES `evidence_source: agent_asserted` regardless of what the file claims. Returns `(edges, AssertionStats)`; never writes files. |
| `reconciler.py` | Pure merge algorithm (zero file I/O): group by `edge_id`; merge `evidence[]` (dedupe by source/extractor/version/tree-hash, keep latest `last_seen_at` + max confidence); default confidences static 0.9 / manual 0.8 / agent 0.6, rounded to 2 decimals; dedupe `callsite_refs` by file/line/column; compute `status` (suppressed → orphan → live → stale) and `blocking_eligible`; aggregate `components[]`, `statistics`, `source_statuses`; derive `snapshot_id` (first 16 hex of sha256 over canonical projected edges). |
| `snapshot_writer.py` | Canonical JSON (`sort_keys=True, separators=(",", ":"), ensure_ascii=False` — must stay bit-identical with `_meta/gates.py` and `edge_identity.py`) + atomic write (tmp file + fsync + `os.replace`). |
| `run.py` | CLI entry + claim check + heartbeat + orchestration (lifecycle above). |
| `promote.py` | **Bob-side library** (bob imports it; NOT a standalone skill, emits no transition requests). `promote_snapshot(project_dir, run_id, session_key_path, session_id_path)`: non-blocking flock on `.wiring/.promote.lock` (raises `BlockingIOError` if held), bumps `.wiring/snapshot_generation` N→N+1, HMAC-SHA256-signs `{contract_map_hash, contract_map_revision, forge_session_id, snapshot_id, snapshot_generation, signed_at}` with the raw forge session-key bytes, rewrites the run snapshot AND `.wiring/latest.json` atomically, writes `.wiring/latest.run_id`. Idempotent: re-promoting the same run_id+snapshot_id verifies the signature and returns without bumping. Also exports `verify_signature()` for audit. |
| `intent_merge.py` | **v1.1 extension (S032 WP-3).** Pure post-processor library: `merge_into_snapshot(snapshot, project_root, run_id)` decorates `snapshot["components"][i]["intent"]` from per-component `functional-intent.v1` files at `.wiring/runs/<run_id>/intent/<component>.yaml` (produced by `intent-extract`). Adds stub component entries for intent-only components with no edges; bumps `schema_version`/`generated_by` to `1.1.0` iff ≥1 intent block was added. Backward-compatible: no intent files → snapshot stays v1.0-shaped. Note: `run.py` emits the base v1.0 snapshot; the orchestrating caller (evo's INTENT_MAPPED phase) applies `intent_merge` after `reconcile()` and before bob promotes. |

## Merge rules (summary — full detail in `references/reconciliation-rules.md`)

- **Status**: `suppressed` (edge_id in `reconcile.suppress_edge_ids`) > `orphan` (src or dst component not in contract-map components) > `live` (≥1 evidence entry with the current `workspace_tree_hash`) > `stale` (everything else).
- **`blocking_eligible`** is TRUE iff ≥1 `evidence[i].evidence_source == "static_extract"` AND the manifest-derived static source status is in `{succeeded, partial}`.
- **Promotion rules**: P1 static+agent → evidence merged, confidence from static (≥0.9); P4 manual → acts like a trusted assertion at 0.8. (P2/P3 involve `trace` evidence — deferred to v2; the v1 `evidence_source` enum permits only `{static_extract, agent_asserted, manual}`.)

## Determinism

Same inputs (including `generated_at`) → byte-identical `snapshot.json`. Edges sorted by `edge_id`; evidence and callsites sorted deterministically; canonical JSON throughout. The current-run timestamps are the only non-deterministic fields; `tests/test_determinism.py` stubs them and asserts byte-identical re-runs.

## Schemas and tests

- `schemas/wiring-snapshot.v1.json` — frozen v1 snapshot schema.
- `schemas/wiring-snapshot.v1.1.json` — v1.1 (optional per-component `intent` block).
- `tests/` (10 files): `test_assertion_inbox.py`, `test_blocking_eligible_invariant.py`, `test_determinism.py`, `test_intent_merge.py`, `test_promote.py`, `test_promote_concurrency.py`, `test_reconciler.py`, `test_run_integration.py`, `test_schema_conformance.py`, `test_snapshot_writer.py`.

## Hard rules (do not violate)

- Deterministic: same inputs -> bit-identical `snapshot.json` (modulo timestamps). Sort edges by `edge_id`. Canonical JSON (sorted keys, no whitespace).
- `blocking_eligible` is TRUE iff >=1 `evidence[i].evidence_source == "static_extract"` AND `source_statuses.static.status in {succeeded, partial}`.
- Malformed jsonl lines: skip + log, don't fail overall.
- Never writes `.wiring/latest.json` — bob does (sole writer of `latest.json`, `latest.run_id`, `snapshot_generation`, via `promote.py` under flock on `.wiring/.promote.lock`).
- Previous-snapshot lookup for staleness: read-only.
- Never writes `.ledger/claims/` (bob-only); never invokes an LLM; never modifies input files; never creates speculative edges beyond the input JSONL files.

## Drift canary

`ALDEBARAN-7` — NEVER rearrange the `canonical_json` parameters; a single-byte diff breaks the HMAC signature bob writes at promote time.
