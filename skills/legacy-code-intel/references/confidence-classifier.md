# Reference: bright-line confidence classifier (HARD-RULE 2)

Reused from `lineage-extract-static`'s classifier (and `dep-currency-check`'s tier
pattern), adapted to code symbols/edges. The classifier is BRIGHT-LINE: it keys on
SYNTACTIC markers, not on a vibe. Two enforcement layers:

1. The extraction prompt (`analyze-symbols.md`) instructs the LLM to classify.
2. `emit_index.py` re-checks deterministically and FORCES `speculative` on any
   occurrence whose evidence shows a dynamic/interpolation marker (defense in depth —
   the LLM cannot accidentally over-promote a dynamic edge to grounded).

## The three tiers

| Tier | Rule | Rendering / use |
|---|---|---|
| `grounded` | The symbol/target is a LITERAL fully resolved within the chunk: `CALL 'TAXCALC'`, `PERFORM 2100-COMPUTE-PAY`, `FROM TAX_BRACKETS`, a named DSX stage link. | Solid edge. Eligible to feed `impact()` once the format's gold precision clears the threshold. |
| `inferred` | Resolved by an IN-ARTIFACT heuristic: a copybook name resolved against an earlier `COPY`; a CTE referenced within the same file; a value resolved against a same-chunk `VALUE` clause. | Dashed edge. Advisory. |
| `speculative` | ANY dynamic/interpolation marker (below). | Dotted edge. Never authoritative; `impact()` framing stays speculative for these. |

## Speculative-forcing markers (deterministic — `emit_index._looks_dynamic`)
- `CALL <data-name>` (a dynamic call target — the operand is a variable, not a quoted
  literal). **A dynamic CALL is ALWAYS speculative**, never grounded.
- `COPY ... REPLACING ...` (post-replace names not statically knowable).
- DSX `RCP` (runtime column propagation) — the column set is runtime-determined.
- `#PARAM#` (DSX parameter interpolation).
- `${VAR}` / `$(...)` (shell interpolation / command substitution).
- `%s` / `%d` (printf-style interpolation).
- `.format(` / `f'...'` / `f"..."` (Python string interpolation).

## Worked examples

| Evidence | Tier | Reason |
|---|---|---|
| `PERFORM 2100-COMPUTE-PAY` | grounded | literal paragraph name resolved in-program |
| `CALL 'TAXCALC' USING WS-GROSS-PAY` | grounded | quoted literal program name |
| `CALL WS-PROGRAM-NAME USING ...` | speculative | dynamic call target (data-name) |
| `COPY EMPWS` | inferred | copybook member named; contents resolved on its own ingest |
| `COPY EMPWS REPLACING ==:TAG:== BY ==WS==` | speculative | REPLACING renames not knowable here |
| `SELECT RATE FROM TAX_BRACKETS` | grounded | literal table |
| `SELECT * FROM #SRC_TABLE#` | speculative | `SELECT *` + `#PARAM#` interpolation |
| `psql -c "$SQL"` (shell) | speculative | `$SQL` is a variable; content dynamic |

## Why this matters (design §8)
The confidence tag flags UNCERTAINTY but not INCORRECTNESS — a grounded edge can still
be wrong if the LLM misread. That residual is covered separately by the gold-file
accuracy gate (`goldcheck.py`), which measures real precision/recall and keeps
`impact()` advisory until a format clears 0.85. Confidence and accuracy are
complementary, not redundant: confidence is per-edge and syntactic; accuracy is
per-format and empirical.
