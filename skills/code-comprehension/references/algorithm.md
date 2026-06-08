# partition.py — algorithm spec (v1)

Deterministic. **NO PageRank / NO community-detection** (cut from v1 as the unbounded rabbit hole — §4). Directory + entry-points + cap + auto-gate + ratify is enough to be "≥ as useful as a hand-written component list" and is finishable.

## Config block (the one place bob tunes)

| Key | Default | Meaning |
|---|---|---|
| `cap` | 12 | max component count (matches PROJECT.md Level-0 budget); long tail collapses into `misc` |
| `fragment_pct_threshold` | 0.40 | over-partition trigger: fraction of candidate components resolving to ≤1 file |
| `max_files` | 40 | under-partition (giant-component) trigger: files per component |
| `max_bytes` | 512000 | under-partition trigger: bytes per component |
| `per_component_token_budget` | 120000 | aggregate est-token cap fed to intent-extract per component before auto-degrade (factors in 2× two-arm) |

All live in `partition.PartitionConfig`.

## Steps

1. **Directory-primary partition.** One candidate component per top-level package / `src/*` / `services/*` / `app_deploy/src/*` dir. Scoring lifts project-documentation's component-detection signals: own-startup +3, own-config +2, depended-on-by-≥2 +2. (v1 uses the structural directory scan; the scoring informs ordering + the misc-tail decision.)

2. **Entry-point seeding — REUSE, not re-detect (Fix-2).** Every detected entry-point becomes a guaranteed component root. Entry-point data is **read from `static.jsonl`** — wiring's FastAPI/Express framework plug-ins already emit route roots, and Python `__main__`/console-scripts come from the manifest + AST already in the graph. WP-2 must NOT re-implement route detection. (When `static.jsonl` is the clean `unmapped_path:*` first pass it has no component ids yet, but it carries the symbols/files; entry-point markers are harvested from edge endpoints + a light `if __name__ == "__main__"` / `def main(` filesystem scan as the documented fallback.)

3. **Hard cap (≤ CAP).** The long tail (lowest-scored candidates beyond CAP-1, reserving one slot for `misc`) collapses into a `misc` component. Logged as a `collapse_tail` decision.

4. **Bidirectional auto-gate (§13 — replaces the pre-flight HALT; NO user pause).**
   - **Over-partition** (count > CAP **OR** > `fragment_pct_threshold` of candidates resolve to ≤1 file): cap → collapse-tail into `misc`. Recorded as `cap_applied` / `fragment_observed`.
   - **Under-partition / giant component** (any component exceeds `max_files` OR `max_bytes` OR a configured % of the repo): **auto-split** if a clean sub-boundary exists (a child directory that cleanly carves the component into ≥2 balanced parts), else **auto-degrade** that component to structural-only (skip its LLM intent pass, emit `confidence: degraded` + an omission note). Recorded as `auto_split` / `giant_observed` / `auto_degrade`.
   - **Per-component cost (C3):** the est-token total (bytes/4, **doubled** for two-arm) is computed BEFORE any intent-extract call. A component over `per_component_token_budget` is split or auto-degraded with an omission report. Recorded as `budget_exceeded`.
   - **Exclusive file coverage:** each file lands in **exactly one** component (deterministic first-match by sorted component id over the directory prefixes, with entry-point seeds taking precedence). **Entry-point coverage:** every detected entry-point lands in a component.

5. **Ratify-lock (§13 auto, C9 diff).** The accepted partition auto-writes `.comprehension/partition.lock`. Each subsequent run **recomputes a draft** partition and **diffs** it against the lock; on a coverage/boundary change (new/moved/deleted paths, changed entry-points) the lock is updated and the change is logged — the lock is a **diff baseline, not a permanent-blind skip**. Under §13 this proceeds automatically (no pause); under a future human-gated mode it would surface for approval.

## Output

`.comprehension/synthetic-contract-map.yaml` — conforms to `component-partition.v1.json`. Schema-compatible with the real contract-map on `components[].{id, source_paths}`; `inputs/outputs/dependencies/integration_points` empty. Carries:

- `provenance: synthetic-unsigned` + a `# UNSIGNED — never move under progress/` header comment.
- `components[].source_files` — the **C5 canonical expanded file inventory** (explicit project-relative files, exactly one component per file), consumed identically by wiring resolution, partitioning, hashing, and intent-extract.
- `components[].source_paths` — directory-prefix globs (the resolver's glob view).
- `components[].cost` — file/byte/est-token totals (visible cost).
- `components[].intent_mode` — `llm` | `structural-only` | `degraded`.

Plus `.comprehension/partition-report.json` (the same content as a machine-readable report) and `.comprehension/partition.lock`.

**Never written under `progress/`** — to avoid collision with a real signed map + poisoning a later real `gates.py G1` call.

## The canonical-inventory mismatch fix (C5)

The wiring resolver matches **directory prefixes** while intent-extract retains **matched files** — a semantic mismatch that would make the two extractors disagree on a component's membership. The partitioner resolves this by emitting one **canonical per-component file list** (`source_files`) and ensuring:

- `source_paths` (the globs) are derived FROM `source_files` (a minimal prefix cover), so a path that matches the glob is in `source_files` and vice-versa for the selected tree.
- Both extractors receive `--contract-map-path <synthetic>`; intent-extract's glob loader and wiring's prefix resolver both resolve to the same file set for the canonical tree.
- `--contract-map-path none` on the FIRST wiring pass = no resolution (clean `unmapped_path:*`), with **fallback to `progress/contract-map.yaml` PROHIBITED** so a stale partial map can't contaminate the first pass.
