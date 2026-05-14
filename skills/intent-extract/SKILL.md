---
name: intent-extract
description: Use during bob's Step 4.5 (after UNIT_TESTED) or evo's INTENT_MAPPED phase (per design §6 state machine) to extract per-component functional intent from a project's source code. Anchor-and-expand on contract-map components plus 1-hop call-graph neighbourhoods; per-component LLM pass at temperature=0; structured YAML output conforming to functional-intent.v1 with closed-set function_class enum, REQUIRED evidence_edges that resolve in static.jsonl, two-arm verification on prose claims; content-hash cached. Requires a bob-issued claim token, heartbeats it every 60s, emits transition requests for INTENT_MAPPED. Skill NEVER writes claim files, NEVER writes the integration ledger, NEVER traverses the call graph beyond 1-hop. CB4-compliant.
---

# intent-extract (v1)

Functional-intent extraction for the EVO agent ecosystem (S032).

**Status:** PRODUCTION (S032 WP-2 ship).
**Design document:** `/path/to/project/docs/plans/2026-05-13-evo-agent-design.md` §4.1 + §5.1.
**Schema:** `~/.claude/skills/_meta/schemas/functional-intent.v1.json` (frozen WP-1).

## What this skill is for

This skill takes a frozen contract-map and a static-wiring snapshot
(`.wiring/latest.json`) and produces one **functional-intent.v1** YAML file
per component, describing **what the component does** in both
mechanically-derived structural terms (entry points, side effects, error
paths, all with required `evidence_edges` into `static.jsonl`) and
LLM-interpretive prose (responsibilities, assumptions, invariants,
unknowns) that NEVER feeds gates or test generation in its raw form.

Two output forms per component:

1. **Cache file** at `.wiring/intent-cache/<sha256>.yaml` — content-addressable.
2. **Per-run symlink** at `.wiring/runs/<run_id>/intent/<component>.yaml`.

## Invocation contract

The skill is **always** invoked by evo (or, in S033+, by other orchestrators)
with a bob-issued claim UUID. It NEVER issues its own claim. It heartbeats
every 60s. If the lease expires, the skill exits cleanly and bob's
transition-request queue rejects the stale request.

```bash
python3 ~/.claude/skills/intent-extract/scripts/run.py \
  --project-root <abs path> \
  --run-id <uuid> \
  --claim-uuid <uuid> \
  --workspace-tree-hash <40-hex> \
  --components <component-id>[,<component-id>...] \
  --model-id claude-opus-4-7 \
  [--mode <intent-map-only|version-upgrade|cve-fix>] \
  [--two-arm <strict|skip>]  # default strict
```

## What lives in `scripts/`

- `run.py` — CLI entry. Parses args, holds claim, dispatches per-component.
- `anchor_expand.py` — given a component id + static.jsonl, returns the 1-hop
  symbol neighbourhood, evidence edge ids, file contents.
- `prompt_template.py` — locked LLM prompt template; hashed into output.
- `llm_call.py` — Anthropic API wrapper at temperature=0, with retry and
  budget checks (EVO_MAX_TOKENS_PER_RUN soft-fail).
- `two_arm_verify.py` — cold-context second pass for prose-field claims,
  semantic similarity scoring (≥0.95 required for confidence_level:grounded).
- `cache.py` — content-hash cache key derivation + read/write.
- `schema_validate.py` — validates output against functional-intent.v1.
- `manifest.py` — writes per-run intent-manifest.json (hit/regenerated/failed/gap).

## What lives in `references/`

- `anchor-and-expand.md` — algorithm spec for the 1-hop expansion strategy.
- `two-arm-verification.md` — cold-context second-pass methodology.
- `closed-enum-reference.md` — function_class / entry_point.kind /
  side_effect.kind / error_path.kind enumerations with examples.
- `caching-and-determinism.md` — cache key derivation, hit ratios, determinism budget.

## What lives in `templates/`

- `prompt-base.txt` — the canonical LLM prompt template (template_hash is
  sha256 of this exact file).

## Hard rules (HARD-RULE alignment per design §13)

1. **NEVER writes `.ledger/claims/`** — bob owns claim files (CB4).
2. **NEVER writes the integration ledger** — emits transition requests under
   `.ledger/requests/<request_id>.request.yaml` (CB4).
3. **NEVER traverses the call graph beyond 1-hop** — auto-traversal is an
   anti-pattern; declared flows only.
4. **NEVER returns `confidence_level: grounded` without two-arm verification**
   — single-arm output is `interpretive`; pure heuristic fallback is `degraded`.
5. **NEVER calls LLM if cache hit** — content-addressable cache short-circuits.
6. **NEVER blocks > EVO_MAX_TOKENS_PER_RUN** — soft-fail with cached fallback +
   advisory in intent-manifest.json (HARD-RULE 8 budget honesty).
7. **Heartbeats every 60s** — calls `claims.heartbeat_claim(claim_uuid)`.

## What feeds what downstream

| Downstream consumer | Field it reads |
|---|---|
| `wiring-reconcile@1.1` | per-component intent block (snapshot.v1.1 schema extension) |
| `wiring-query@1.1` | `intent_of(component)` op reads the cache directly |
| `intent-map-render` | reads cache + snapshot to emit D1/D3/D4 diagrams |
| `ever-test-gen` | reads `test_seeds[]` and `error_paths[]` for characterization tests |

## Determinism contract

Re-running on the same `workspace_tree_hash` + `content_hash` + `extractor_version`
+ `model_id` MUST produce ≥0.95 semantic similarity output (cached_interpretive
class). Cold runs on fresh content are `fresh_interpretive`. Pure-mechanical
fields (entry_points, side_effects, error_paths) are `deterministic`.

## How to invoke for testing

```bash
# Validate a generated functional-intent file against schema
python3 ~/.claude/skills/intent-extract/scripts/schema_validate.py \
    --intent .wiring/runs/<run_id>/intent/auth-service.yaml
```
