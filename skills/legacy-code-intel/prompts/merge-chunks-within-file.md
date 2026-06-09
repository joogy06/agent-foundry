# Prompt: merge-chunks-within-file (boundary reconciliation guidance)

Use this when an artifact was large enough to be split into multiple chunks
(`chunked: true` in the chunk manifest). You analysed each chunk independently with
`analyze-symbols.md`; this step reconciles the chunk-boundary `boundary_status`
markers BEFORE the skill runs the deterministic merge.

Important division of labour: the ACTUAL merge is performed by `scripts/accumulate.py`,
NOT by you. accumulate.py applies a deterministic predicate (dedup symbols by ID,
dedup occurrences by (symbol_id, role, line-range), pair partial relationships within
the overlap window, downgrade unpaired boundary partials to speculative). Your job is
only to make sure each chunk's `boundary_status` is set HONESTLY so the deterministic
pairing has correct inputs.

## What to verify per chunk before accumulate runs
- If a construct (a paragraph body, a multi-line `EXEC SQL`, a stage block, a
  function body) is cut at the END of a chunk, that chunk's `boundary_status` must be
  `partial_end` (or `partial_both`).
- If a chunk BEGINS inside a construct that started in the previous chunk, its
  `boundary_status` must be `partial_start` (or `partial_both`).
- A chunk with clean boundaries on both ends is `complete`.

## What NOT to do
- Do NOT hand-merge symbols or edges across chunks. accumulate.py does it
  deterministically (HARD-RULE 3) so the output is byte-reproducible.
- Do NOT invent a relationship to "complete" a construct split across a boundary. If
  a CALL/PERFORM/link is cut and its other half is not visible, leave it and let
  accumulate pair it (or downgrade it to speculative + a boundary gap).
- Do NOT renumber `symbol_id`s. The content-addressed IDs are stable across chunks
  because they derive from the artifact `file_sha256` + the scoped name, not from the
  chunk.

## Overlap
Chunks overlap by a small window (default 50 lines). The same construct may appear in
both the partial_end of chunk N and the partial_start of chunk N+1. That is EXPECTED —
accumulate dedups it. Just classify boundary_status correctly.
