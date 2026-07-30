---
name: wiring-extract-static
description: Emit run-scoped static wiring edges from a target project via SCIP (scip-python, scip-typescript) plus framework plug-ins (FastAPI, Express) or a generic fallback (Python ast + JS regex). Writes `.wiring/runs/<run_id>/static.jsonl` and `manifest.json` conforming to `wiring-source-edge.v1` and `wiring-source-manifest.v1`. Single-writer of `static.jsonl`. Deterministic Python, no LLM calls. Invoked by bob with a claim UUID; heartbeats every 60s via `~/.claude/skills/_meta/claims.py`.
family: wiring
disambiguation: EMITS per-run static edges from source via SCIP and framework plug-ins. Merging run artefacts into the promoted snapshot is wiring-reconcile.
---

# wiring-extract-static (v1)

**Status:** PRODUCTION. WP-1 (schemas) + WP-2 (runtime + plug-in API + generic fallback) + WP-3 (FastAPI + Express plug-ins) complete. Driven by bob via S023 wiring-ledger pipeline.

**Design document:** `/path/to/project/docs/plans/2026-04-14-wiring-skills-design.md` §5.1

## What this skill does

Given a target project directory and a run UUID issued by bob, emit per-run static wiring edges. Edges describe how components in the target project call, route to, import from, or persist into each other. Output:

- `.wiring/runs/<run_id>/manifest.json` — conforms to `wiring-source-manifest.v1`; lists every extractor source that ran, its status, and gaps
- `.wiring/runs/<run_id>/static.jsonl` — one JSON line per edge, each conforms to `wiring-source-edge.v1`
- A transition request at `.ledger/requests/<uuid>.request.yaml` that bob (sole ledger writer, CB4) consumes

The skill itself NEVER writes to the ledger, NEVER invokes LLMs, NEVER touches `.wiring/` root (that is bob's single-creator domain), and NEVER writes outside its run-scoped subdirectory.

## Invocation

```bash
python3 ~/.claude/skills/wiring-extract-static/scripts/run.py \
    --project-dir "$PROJECT_DIR" \
    --run-id "<uuid>" \
    --claim-uuid "<claim_uuid>" \
    [--config .ledger/config.yaml]
```

Exit codes:
- `0` — full or partial success. Gaps and per-source skipped/failed statuses are recorded in the manifest; downstream reconcile proceeds.
- `1` — unrecoverable. Disk full, claim revoked, git `write-tree` fails, target `.wiring/` missing.

## Lifecycle

1. Validate `claim_uuid` (first heartbeat immediate; background thread every 60s).
2. `git write-tree` → `workspace_tree_hash`.
3. Detect languages + frameworks (project-documentation/context-detection if importable; otherwise filesystem sniff).
4. Create `.wiring/runs/<run_id>/` and write initial `manifest.json` with `status: in_progress`.
5. For each detected language:
   - Load plug-ins via `scripts/plugin_loader.py`.
   - If a framework plug-in matches (`target_framework` in detected frameworks), run it against the language's source files.
   - Otherwise run the `generic-treesitter` fallback for that language.
6. Every yielded edge is schema-validated against `wiring-source-edge.v1` before it is appended; malformed edges are dropped and reported as a gap.
7. Canonical component naming: every `src_component` / `dst_component` comes from `progress/contract-map.yaml` via `ComponentResolver`. Files that do not match any component's `source_paths` are recorded as `unmapped_path:<path>` gaps.
8. Write `static.jsonl` and the terminal `manifest.json` atomically (tmp + rename).
9. Emit a YAML transition request with `target_stage` (`SCAFFOLDED` at first call, later `UNIT_TESTED`/`INTEGRATED` per bob's orchestration).

## Directory layout

```
~/.claude/skills/wiring-extract-static/
├── SKILL.md
├── schemas/
│   ├── wiring-source-edge.v1.json        # frozen (WP-1)
│   └── wiring-source-manifest.v1.json    # frozen (WP-1)
├── scripts/
│   ├── run.py                 # CLI entry
│   ├── plugin_loader.py       # discovers & validates plug-ins
│   ├── component_resolver.py  # contract-map-driven component id lookup
│   ├── heartbeat.py           # claim heartbeat thread (invokes claims.py)
│   └── scip_invoke.sh         # SCIP subprocess wrapper w/ 120s timeout
├── extractors/
│   ├── generic-treesitter/    # fallback: Python ast + JS/TS regex
│   ├── fastapi/               # WP-3 plug-in
│   └── express/               # WP-3 plug-in
├── references/
│   ├── plugin-author-guide.md # frozen plug-in contract
│   ├── edge-schema.md         # (future) human-readable schema notes
│   └── scip-notes.md          # (future) SCIP gotchas
├── fixtures/
│   ├── fastapi-minimal/       # WP-3 smoke fixture
│   └── express-minimal/       # WP-3 smoke fixture
└── tests/
    ├── test_schemas.py         # 6/6 (WP-1)
    ├── test_component_resolver.py
    ├── test_plugin_loader.py
    ├── test_generic_treesitter.py
    ├── test_heartbeat.py
    ├── test_plugin_fastapi.py   # WP-3
    └── test_plugin_express.py   # WP-3
```

## Plug-in author contract

See `references/plugin-author-guide.md`. Summary:

- `plugin.json` declares `id`, semver `version`, `target_framework`, `languages`, `edge_kinds`, `is_fallback`, `description`.
- `extractor.py` exposes `extract_edges(project_dir, symbols, source_files, workspace_tree_hash, extractor_version, config, resolve_component) -> Iterator[edge dict]`.
- Every edge MUST pass schema validation. `edge_id` MUST come from `~/.claude/skills/wiring-reconcile/scripts/edge_identity.compute_edge_id(...)`.
- No LLM calls, no network I/O, no writes outside what the loader stages.

## Hard rules (for all callers)

- Canonical component naming: NEVER invent component ids. Resolve via contract map, or use `external:<package>` for external deps.
- `edge_id` is five-tuple sha256 truncated to 16 hex — one source of truth in `wiring-reconcile/scripts/edge_identity.py`. No re-implementation.
- Atomic writes (tmp + rename) for every output file.
- Manifest is always written last with terminal statuses per source.
- Exit 0 on partial success (skipped / failed sources recorded); exit 1 only on unrecoverable errors.
- Single-writer discipline for `static.jsonl` — only this skill writes it. Agent-asserted edges go in the sibling `asserted/<agent_id>.jsonl`, owned by the agent.

## Tests

Run everything under `tests/` with Python 3.12+. Current pass count:

- `test_schemas.py` — 6/6
- `test_component_resolver.py` — 3/3
- `test_plugin_loader.py` — 6/6
- `test_generic_treesitter.py` — 4/4
- `test_heartbeat.py` — 3/3
- `test_plugin_fastapi.py` — fixture-driven smoke
- `test_plugin_express.py` — fixture-driven smoke

## Known gaps (v1)

- SCIP indexers (`scip-python`, `scip-typescript`) are optional; when absent the corresponding source is marked `skipped` and generic-treesitter covers the language with reduced precision (imports + intra-component calls only).
- Generic tree-sitter fallback uses Python `ast` + JS regex. Real `tree-sitter` Python bindings are optional and deferred to v2 when the dependency lands in env-adoption.
- No Go / Java / Ruby — explicit v2 deferral per design §2.2.
