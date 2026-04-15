---
name: wiring-reconcile
description: STUB (WP-4/5/6 pending). Merge per-run source artifacts (`static.jsonl` + per-agent `asserted/<agent_id>.jsonl`) into a run-scoped `snapshot.json` conforming to `wiring-snapshot.v1`. Single writer of reconciled snapshots. Does NOT promote to `latest.json` — bob does, atomically under flock. Deterministic Python, no LLM calls.
---

# wiring-reconcile (v1) — STUB

**Status as of 2026-04-14 S023 bob run:** Directory scaffolded; WP-1 (snapshot schema + `edge_identity.py`) complete; WP-4/5/6 (assertion inbox, reconciler core, atomic promote) NOT YET IMPLEMENTED.

**Design document:** `/path/to/project/docs/plans/2026-04-14-wiring-skills-design.md` §5.2 + §6 (WP-4, WP-5, WP-6)

## What is shipped in this partial state

- `schemas/wiring-snapshot.v1.json` — frozen v1 snapshot schema (validated by sibling skill test)
- `scripts/edge_identity.py` — **single source of truth** for `edge_id` derivation (sha256 first-16-hex of canonical-json five-tuple per design §4.1.1). Used by both `wiring-extract-static` and `wiring-reconcile`.

## What remains (future bob resume)

- `scripts/assertion_inbox.py` (WP-4) — normalizer library for per-run `asserted/<agent>.jsonl`
- `scripts/reconciler.py` (WP-5) — merge algorithm: group-by edge_id, build evidence[], compute status (live/stale/orphan/suppressed), compute blocking_eligible
- `scripts/snapshot_writer.py` (WP-5) — deterministic canonical JSON write, atomic tmp+rename
- `scripts/run.py` (WP-5) — CLI entry + heartbeat
- `scripts/promote.py` (WP-6) — bob-side atomic promote to `.wiring/latest.json` under flock on `.promote.lock`, increments `snapshot_generation`
- `references/reconciliation-rules.md`
- Tests: `tests/test_determinism.py`, `tests/test_concurrent_promote.py`
- `COMPONENT.md` in `docs/components/wiring-reconcile/`

## Hard rules (for future implementer)

- Deterministic: same inputs -> bit-identical `snapshot.json` (modulo timestamps). Sort edges by `edge_id`. Canonical JSON (sorted keys, no whitespace).
- `blocking_eligible` is TRUE iff >=1 `evidence[i].evidence_source == "static_extract"` AND `source_statuses.static.status in {succeeded, partial}`.
- Malformed jsonl lines: skip + log, don't fail overall.
- Never writes `.wiring/latest.json` — bob does.
- Previous-snapshot lookup for staleness: read-only.
