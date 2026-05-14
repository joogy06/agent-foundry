# Two-Arm Verification — Methodology

Per HARD-RULE 7 (design §13): every prose intent claim
(`responsibilities[]`, `assumptions[]`, `invariants[]`) gets
`confidence_level: grounded` only if (a) `evidence_edges[]` cite real
edges in `static.jsonl` AND (b) a cold-context second pass produced
≥0.95 semantic similarity. Single-arm output is `interpretive` and never
feeds gates or test generation.

## The two arms

**Arm A** — primary extraction. Full prompt, full context, full edge
neighbourhood. Produces the initial functional-intent.v1 document.

**Arm B** — second pass with the SAME prompt and SAME context but issued
in a fresh model invocation. The model has no memory of arm A's output.
Both arms operate at temperature=0, but token sampling is non-deterministic
enough at the prose level to expose hallucinations and assumption drift.

## Similarity metric

`scripts/two_arm_verify.py` uses `difflib.SequenceMatcher` on normalized
prose (lowercased, whitespace collapsed, trailing punctuation stripped).
Threshold for `grounded` is **0.95**.

Rationale for difflib over embeddings:
- Deterministic (same input → same score, always)
- No network calls / no model dependency
- Bounded latency (~ms per comparison)
- Embeds the "same wording" requirement directly — semantically similar
  but reworded text scores ~0.6, which we WANT to flag as `interpretive`,
  not auto-promote to `grounded`

Future S033+ may swap in a sentence-transformers backend without changing
the module's public API (`text_similarity` / `annotate_confidence`).

## Reconciliation rules

For each `responsibilities[]` entry in Arm A:

1. Compute best-match similarity against the pool of Arm B's
   responsibilities[].text values.
2. If best score ≥ 0.95 → `confidence_level: grounded`.
3. Else → `confidence_level: interpretive` AND set
   `intent.interpretive_disagreement: true`.

For the top-level `intent.one_line`:

1. Compute similarity between Arm A's one_line and Arm B's one_line.
2. If ≥ 0.95 → top-level `intent.confidence_level: grounded`.
3. Else → `intent.confidence_level: interpretive`.

## When the second arm fails

If Arm B is unavailable (budget exhaust mid-component, transient API
error, network drop):

- `intent.confidence_level` → `degraded`
- All `responsibilities[].confidence_level` → `degraded`
- `intent.interpretive_disagreement` → `true`
- The component manifest records `tokens_in/out` only for Arm A; the
  failure is logged in `intent-manifest.json` but the component itself
  is still emitted as `regenerated` (not `failed`) because Arm A produced
  schema-valid output.

Downstream consumers (ever-test-gen, gates) treat `degraded` and
`interpretive` identically: never feed them into characterization tests,
never block on them, surface them to the user as advisory.

## When the user wants to disable two-arm

Pass `--two-arm skip` to `run.py`. This halves the LLM cost but
**guarantees** that no claim is `grounded`. Useful for:
- Mode-a (intent-map-only) on very large repos where confidence
  promotion isn't needed for the downstream consumer
- Cost-sensitive batch runs where downstream uses prose only as
  prompts for human review

Default is `--two-arm strict`. Mode-c (cve-fix) ALWAYS runs strict.

## Determinism guarantees

The two-arm reconciliation itself is fully deterministic — given the same
Arm A output, the same Arm B output, and the same known_edges, it
produces byte-identical reconciled YAML.

The non-determinism is entirely in the LLM token sampling. That is
intentional — it's what makes the second arm a useful check.
