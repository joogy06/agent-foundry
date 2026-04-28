---
name: retro-scan-s028
description: One-shot retro-baseline scanner for S029. Invoked ONCE per project, after S029 implementation lands and BEFORE #45 Phase-5b begins. Walks each component declared in `progress/contract-map.yaml`, classifies undeclared filesystem paths as `pre_existing_critical` (matches `CONTRACT_SCOPE_CRITICAL_GLOBS`, ALWAYS blocks recurrence) or `pre_existing_advisory` (documented baseline, doesn't block thin-coverage). Writes `progress/retro-scan-S028.yaml` conforming to `retro_scan.v1`. Read-only with respect to the contract map; non-blocking (does NOT call `pause_state.request_pause`). v1 file-level granularity only — symbol-level deferred to S030.
when_to_use: After S029 has shipped to a project (gates + scope_delta + ledger all wired) and before any S028-keystone Phase-5b thin-coverage remediation runs. The output baseline is consulted by `G_CONTRACT_SCOPE` to distinguish pre-existing artifacts (advisory) from newly-introduced ones (block).
authoring: bob (S029 WP-8) — implements design §10.1 + §7.5; reuses `_meta/extractors` and `_meta/gates.py:_gcs_*` glob helpers for behavioral consistency with the live gate.
inputs:
  - project_root (filesystem path; required)
outputs:
  - progress/retro-scan-S028.yaml (single canonical file; re-runs OVERWRITE; git history preserves prior versions)
non_goals:
  - Symbol-level extraction (deferred to S030 per design §17 OQ2)
  - Auto-amending contract-map (read-only invariant)
  - Triggering pause_state (non-blocking invariant)
  - Generating per-run timestamped artifacts (single canonical path per spec-review minor)
---

# retro-scan-s028 — One-shot S028 Retro Baseline Scanner

## Purpose (design §10.1, §7.5)

`G_CONTRACT_SCOPE` (the live gate from S029 WP-3) blocks every undeclared
artifact at WP boundary + INTEGRATED→VERIFIED. That works for *new* runs.
But the S028 ecosystem-keystone landed before S029 existed; its 10
INTEGRATED components carry undeclared artifacts that pre-date the gate.

The Q2 = Codex Option F policy threads the needle:

  * Pre-existing artifacts that match `CONTRACT_SCOPE_CRITICAL_GLOBS`
    are added to `baseline_critical_paths` — they ALWAYS block recurrence
    (Q2 #4: critical findings always block).
  * Pre-existing advisory findings are documented as a baseline
    snapshot but DO NOT block #45 Phase-5b thin-coverage remediation
    (Q2 #2: pre-existing advisory grandfathered).
  * Anything newly introduced or touched during #45 still blocks
    (handled by the live gate, not this skill).

This skill produces the baseline.

## Invocation contract

Single canonical entry point:

```bash
python3 ~/.claude/skills/retro-scan-s028/scripts/scan.py <project_root>
```

The scanner walks the workspace (skipping `.git`, `.ledger`, `.forge`,
`.design-ledger`, `__pycache__`, `node_modules`, `.venv`, `venv`, `.tox`,
`.mypy_cache`, `.pytest_cache` — same skip set as `gates._gcs_walk_workspace`),
reads `progress/contract-map.yaml`, classifies each path, and writes
`progress/retro-scan-S028.yaml`. Re-runs OVERWRITE (single canonical
output per spec-review minor; git history preserves prior versions).

Exit codes:
  * 0 — scan succeeded; output written; advisory summary printed to stdout
  * 2 — env error (contract-map missing, parse failure, etc.); diagnostic on stderr

The scanner does NOT exit non-zero based on findings count or severity.
Findings are an artifact for user review, not a gate verdict. (Non-blocking
invariant per design §7.5.)

## Output schema

The output conforms to `~/.claude/skills/_meta/schemas/retro_scan.v1.json`
(symlinked from `schemas/retro_scan.v1.json` in this skill). One source of
truth — the schema is owned by S029 WP-2 and lives in `_meta/schemas/`.

Top-level structure:

```yaml
schema_version: retro_scan.v1
generated_at: <ISO8601 Z>
generated_by: retro-scan-s028
contract_map_hash: sha256:<hex>
contract_map_revision: <int>
components:
  - component_id: <kebab-case>
    declared_source_paths: [...]
    actual_paths: [...]
    findings:
      - path: <project-relative>
        artifact_kind: <secret|db_migration|env_var|public_api|config_key|generated_artifact|file>
        in_declared: <bool>            # path is in the component's declared source_paths
        severity: pre_existing_critical | pre_existing_advisory
baseline_summary:
  total_findings: <int>
  pre_existing: <int>          # = total_findings (everything in a baseline is, by definition, pre-existing)
  pre_existing_critical: <int>
  pre_existing_advisory: <int>
  newly_introduced: 0          # always 0 in a baseline run
baseline_critical_paths: [...]  # paths classified pre_existing_critical (Q2 #4 enforcement list)
```

Stdout summary line example:

```
retro-scan-s028: 47 findings, 8 critical, 39 advisory across 10 components
```

## Behavior (design §10.1)

For each component declared in `progress/contract-map.yaml`:

1. Glob each `source_paths[]` entry; collect `actual_paths` from the workspace.
2. Compute `declared_set = source_paths` (the component's authority).
   `excluded_paths` from the map root applies UNLESS the path is in
   `CONTRACT_SCOPE_CRITICAL_GLOBS` (M4 precedence preserved — same rule as
   the live gate).
3. For each actual path NOT in `declared_set` AND NOT in `excluded_paths`
   (with M4 carve-out): classify via `extractors.first_match(project_root,
   path, "added")`. Severity = `pre_existing_critical` iff path matches
   `CONTRACT_SCOPE_CRITICAL_GLOBS`, else `pre_existing_advisory`.
4. Aggregate across all components into `baseline_summary` and
   `baseline_critical_paths`.
5. Atomic-write to `progress/retro-scan-S028.yaml`.

Implementation detail: re-uses `gates._gcs_glob_to_regex` /
`_gcs_glob_match` / `_gcs_walk_workspace` / `_gcs_matches_critical` /
`_gcs_in_universe` directly. `**` recursive-glob semantics are NOT
expressible via `fnmatch`, so importing the gate's helpers is mandatory
(spawn-2 noted this explicitly).

## Invariants (design §7.5)

| Invariant | Enforcement |
|---|---|
| Read-only w.r.t. contract-map | Scanner NEVER opens `progress/contract-map.yaml` for write; only reads |
| Non-blocking (no pause_state) | Scanner imports neither `pause_state` nor `scope_reaction`; static-scan test verifies |
| Single canonical output | `progress/retro-scan-S028.yaml` only; no per-run timestamping |
| Re-run idempotency | Same input → same output (modulo `generated_at`); atomic `.tmp + rename` |
| Symbol-level deferred | v1 is file-level only; `in_declared_capability` field in schema is reserved but unused in v1 |
| Classification consistency with live gate | Same `CONTRACT_SCOPE_CRITICAL_GLOBS` constant, same extractor priority chain, same glob-matcher |

## When NOT to invoke

* Mid-execution of #45 Phase-5b — too late; live `G_CONTRACT_SCOPE` is the
  authority once Phase-5b starts.
* On a project that has no `progress/contract-map.yaml` — the scanner
  exits 2 with a diagnostic.
* Repeatedly during a single session — the output is a baseline snapshot,
  not an audit trail.

## Tests

`tests/contract-scope/test_retro_baseline.py` — 10 unit tests covering:

  * TS-RS-01: clean baseline (all paths declared) → 0 findings, summary all-zero
  * TS-RS-02: critical undeclared (synthetic `migrations/001-x.sql`) → severity=pre_existing_critical
  * TS-RS-03: advisory undeclared (random `.md` not in CRITICAL_GLOBS) → severity=pre_existing_advisory
  * TS-RS-04: M4 precedence — path matches BOTH a critical glob AND `excluded_paths` → critical wins
  * TS-RS-05: removed-symbol case (DEFERRED per §17 OQ2; v1 file-level only) — test documents the deferral
  * TS-RS-06: multi-component (2+ synthetic components, each with own findings) → output groups by component
  * TS-RS-07: re-run overwrites previous output (idempotency)
  * TS-RS-08: schema conformance — output validates against `retro_scan.v1.json`
  * TS-RS-09: empty contract-map → empty output (no crash)
  * TS-RS-10: glob expansion correctness with `**` (uses gate's `_gcs_glob_to_regex`)

## Provenance

* Design: `docs/plans/2026-04-26-contract-scope-enforcement-keystone-design.md` §7.5, §10.1, §11 WP-8 row, §17 OQ2
* Contract: `progress/contract-map.yaml` component `retro-scan-s028-skill`
* Owner: bob (S029 WP-8)
* Schema source of truth: `~/.claude/skills/_meta/schemas/retro_scan.v1.json`
