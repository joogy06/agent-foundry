---
name: code-comprehension
description: Use when you want a cheap, standing, read-only GENERATED comprehension front-door (PROJECT.md + per-component COMPONENT.md) for an arbitrary code repository that has no durable contract-map — turns a code tree into non-drifting architecture docs built from a bounded synthetic component partition + structural code edges (AST/regex) + per-component LLM functional intent. Claimless and CB4-safe — writes ONLY to .comprehension/ scratch + generated docs (nothing under .ledger/ or progress/). Composes wiring-extract-static (--standalone), intent-extract (--standalone), the wiring-reconcile pure merge core, and intent-map-render pure functions. Shadow-first - generates to a SHADOW path for side-by-side parity before adoption; --migrate (overwrite real docs) is human-gated and separate. Also trigger on "generate PROJECT.md", "document this codebase", "comprehension front-door", "architecture docs for a repo without a contract-map", "what are the components of this code".
---

# code-comprehension (v1)

A cheap, standing, **read-only** generated comprehension front-door. Turns an arbitrary code repo into a **generated, non-drifting** `PROJECT.md` + `docs/components/<id>/COMPONENT.md` — built from a bounded synthetic component partition + structural code edges + per-component LLM intent — so the front-door stops being hand-maintained prose that drifts.

**Status:** PRODUCTION (D-A v1 ship).
**Design document:** `/path/to/project/docs/plans/2026-06-08-generated-front-door-design.md` (read §12 → §13 → §11 → §1–§10).
**Classification:** skill_text (Contract Map N/A). This skill is the *consumer* of synthetic contract-maps; it does not introduce a gated product surface.

## What this skill is for

The forge→bob contract-driven pipeline (`intent-extract`, `wiring-extract-static`) only starts on a repo that already carries a signed `progress/contract-map.yaml`. Most real code repos (legacy apps, the user's other projects) have **no durable full contract-map**. This skill is the bounded standalone path that:

1. **Synthesizes its own component partition** (`partition.py`) — directory-primary + entry-point seeding + a hard cap, with bidirectional auto-resolution of over- and under-partition (no user pause). The synthetic map is **UNSIGNED** and written to `.comprehension/` — **never under `progress/`** (collision hazard with a real signed map + poisoning a later `gates.py G1`).
2. **Runs both extractors in a new `--standalone` mode** where a bob claim is *structurally impossible* (no `--claim-uuid`, the heartbeat thread is never constructed, transition-request emission is unreachable). The run writes **nothing under `.ledger/`** → CB4-safe by absence.
3. **Renders deterministic, zero-LLM docs** (`render_docs.py`) — byte-identical on re-run given a fixed intent-map.

## What this skill is NOT

- **NOT an agent.** It is a cheap standing pipeline invoked on demand. No design team, no challengers, no bob cycle.
- **NOT a ledger writer.** It touches nothing under `.ledger/` or `progress/`. It cannot drive a real ledger transition (that is the CB4 kill-criterion, satisfied by absence).
- **NOT SCIP-precise.** v1 edges come from `wiring-extract-static`'s Python AST + JS/TS regex generic fallback (+ FastAPI/Express framework-route plugins only where a repo uses them). Edges are labeled **"structural (AST/regex)"** with a confidence note. Real SCIP wiring is a v2 prerequisite.
- **NOT a doc overwriter (by default).** v1 generates to a **shadow path** for side-by-side review. `--migrate` (which overwrites real docs) is a separate, human-gated step and is off the v1 critical path.

## CLI

```
code-comprehension build <repo>     # full pipeline → .comprehension/PROJECT.generated.md (shadow) + shadow COMPONENT.md
code-comprehension build <repo> --migrate   # HUMAN-GATED: archive + propose section-split + section-approval, then adopt
```

In practice the three scripts are invoked directly (this is a script skill, not an MCP tool):

```bash
python3 ~/.claude/skills/code-comprehension/scripts/comprehension_run.py --project-dir <repo> [--shadow]
```

The orchestrator (`comprehension_run.py`) owns the whole sequence; `partition.py` and `render_docs.py` are also independently runnable for testing.

## Pipeline (v1)

```
comprehension_run.py --project-dir <repo>          (claimless, read-only — NOT an agent)
  │  owns .wiring/ + .comprehension/ creation (the non-bob "single creator")
  │
  1. wiring-extract-static --standalone --contract-map-path none
  │     → .comprehension/.wiring/runs/<id>/static.jsonl   (first pass: src_component = unmapped_path:*)
  │
  2. partition.py  ── the load-bearing piece (§4) ──
  │     read static.jsonl + file tree + entry-points (reused from static.jsonl, NOT re-detected)
  │     → bounded component partition (directory-primary + entry-point seeds, ≤CAP)
  │     → AUTO-RESOLVE (§13): cap→collapse-tail into misc; giant/over-budget→auto-split
  │       if clean sub-boundary else auto-degrade to structural-only; ratify→auto-write lock
  │     → .comprehension/synthetic-contract-map.yaml   (UNSIGNED; never under progress/)
  │     → .comprehension/partition.lock (recomputed + diffed each run, per C9)
  │     → .comprehension/partition-report.json (partition + per-component cost; post-hoc)
  │
  3. wiring-extract-static --standalone RE-RUN with the synthetic map → real component ids on edges
  │
  4. intent-extract --standalone --contract-map-path .comprehension/synthetic-contract-map.yaml
  │     (Python/TS: real intent; other langs / degraded: structural-only, no LLM, confidence badge)
  │     → .comprehension/.wiring/intent-cache/<sha>.yaml   (content-hash cached)
  │
  5. render-bundle (in orchestrator):
  │     merge per-component intent caches → one {"components":[...]} intent-map (in memory)
  │     reconciler.reconcile(static_edges, [], manifest, comp_ids, ...) → component-edge view (in memory)
  │
  6. render_docs.py  (deterministic, ZERO-LLM)
  │     intent-map + component-edge view + manifests
  │     → .comprehension/PROJECT.generated.md (SHADOW) + .comprehension/components/<id>/COMPONENT.md
  │     → FRESHNESS:v1 + generated_from[] stamp ; edges labeled "structural (AST/regex)"
  │     → strip sampled_at / model_id / run-id for determinism
```

## CB4 boundary (the central guarantee)

`code-comprehension` writes **only** under the repo's `.comprehension/` scratch directory (and, on `--migrate`, the real docs after human approval). It writes **nothing** under `.ledger/` or `progress/`. The two extractors run in `--standalone` mode where:

- **No claim is required** (`--claim-uuid` is not accepted in standalone mode).
- **The heartbeat thread is never constructed** (not merely `--no-heartbeat` — the object is never created, so there is no path that could touch a claim file).
- **Transition-request emission is unreachable** (guarded at the call site by the standalone flag).
- **The output root is configurable** under `.comprehension/`.

**HARD acceptance test:** snapshot `.ledger/` and `progress/` before and after a full `code-comprehension build --standalone` run → **byte-identical** (zero new/changed files). See `tests/test_cb4_boundary.py`.

This makes the run CB4-safe *by absence*: it cannot drive a real ledger transition because it never touches `.ledger/` at all. On an ecosystem repo that *has* a live `.ledger/`, the run still writes nothing there.

## Determinism (honest scoping)

- The **render is byte-deterministic GIVEN a fixed intent-map** (sorted keys, `sampled_at`/`model_id`/run-id stripped, FRESHNESS keyed to content hashes). `tests/test_render_determinism.py` deletes the render and rebuilds it from a fixed intent-map and asserts byte-identity.
- The **intent itself is NOT byte-stable across cold LLM regens** (temp=0 ≠ byte-identical; the cache evicts after 30 days). So `cache.py` **never evicts** content-addressed entries referenced by a current `partition.lock`, and `model_id` is pinned into `generated_from[]`. We do **not** claim cold-LLM-regen determinism.

## Multi-language

Python + TS/TSX get real intent. Other languages fall through `wiring-extract-static`'s generic fallback → **structural-only** components (no LLM intent; `confidence: structural-only` badge). Prose is never faked for unsupported languages.

## Generated-ownership (adoption prerequisite — WP-9)

Generated docs carry a banner:

```
<!-- GENERATED by code-comprehension — do not hand-edit; edits are erased on regen; narrative → ARCHITECTURE.md -->
```

plus a `generated_from[]` hash. A `freshness` check **fails on manual edits** (hash mismatch). Before any repo *adopts* a generated PROJECT.md, the writer contracts (`exit-with-docs`, `project-documentation`, forge, agent-teams) must be amended to detect the banner and redirect human updates to `ARCHITECTURE.md`/`history.md`. v1 ships the banner + guard; the writer-contract migration is a **deferred adoption prerequisite**, NOT on the v1 build/dogfood critical path (the dogfood is shadow-only and never adopts).

## Files

| Path | Role |
|---|---|
| `scripts/partition.py` | Bounded partitioner → synthetic unsigned contract-map + partition.lock + cost report |
| `scripts/comprehension_run.py` | Claimless read-only orchestrator (owns `.wiring/`+`.comprehension/`; both extractors `--standalone`; render-bundle) |
| `scripts/render_docs.py` | Deterministic zero-LLM intent+edges+manifests → PROJECT.md/COMPONENT.md |
| `scripts/ownership_guard.py` | Generated-doc banner + manual-edit detection (WP-9) |
| `scripts/migrate.py` | De-automated `--migrate`: archive + manifest + proposed split + human approval (WP-7) |
| `schemas/component-partition.v1.json` | Partition output schema |
| `references/algorithm.md` | Partitioner algorithm spec + thresholds |
| `references/cb4-boundary.md` | The claimless / CB4 boundary doc |
| `tests/` | Golden-file + fragmentation/giant auto-gate + render-determinism + CB4-boundary tests |

## Reuse (unchanged)

- `wiring-extract-static` core (AST/regex generic fallback + framework plugins).
- `intent-extract` core (per-component LLM pass + content-hash cache).
- `wiring-reconcile`'s **pure `reconciler.py` merge core only** (NOT its stubbed file/promotion lifecycle).
- `intent-map-render`'s `d1_sequence.render` / `d4_heatmap.render` as **pure functions** (NOT its CLI, which expects evo `.ledger/evo/...` paths + carries HARD-RULE-5 gating that does not apply here).
- The FRESHNESS:v1 machinery + the 4th SessionStart freshness hook (cheap hash-check + nudge; never eager-blocking).
