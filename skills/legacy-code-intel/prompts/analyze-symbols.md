# Prompt: analyze-symbols (per-chunk symbol/occurrence/relationship extraction)

You are analysing ONE chunk of a legacy code artifact to extract a SCIP-inspired
code-intelligence finding. Read the chunk, then emit ONE JSON object conforming to
`code-finding.v1` (schema in `schemas/code-finding.v1.json`). Emit ONLY the JSON
object — no prose before or after.

This prompt is the framework's parser. It is model-neutral: it works the same in
Claude Code, Codex CLI, Gemini CLI, and Copilot CLI. Do not assume any vendor
extensions.

## Inputs you are given
- `format` — one of `cobol`, `dsx`, `etl` (auto-detected; if it disagrees with
  what you see, trust what you see and set `format` accordingly).
- `file_sha256` — sha256 of the WHOLE artifact (copy it through verbatim).
- `chunk_id`, `start_line`, `end_line` — this chunk's position in the artifact.
- The chunk text itself.
- The matching per-format addendum (`cobol.md` / `dsx.md` / `etl.md`) — read it for
  the symbol vocabulary and the format's call/copy semantics.

## What to emit

A single `code-finding.v1` object with these arrays:

### `symbols[]`
Every named construct DEFINED in this chunk. Each symbol:
- `symbol_id` — a path-INDEPENDENT content-addressed ID (see `resolve-symbol-id.md`).
  Format: `codelib://sha256/<file_sha256>#sym/<scoped-name>`. Use the artifact's
  `file_sha256` you were given. The `<scoped-name>` is the qualified name
  (e.g. `PAYROLL/2100-COMPUTE-PAY` for a paragraph inside program PAYROLL).
- `kind` — from the format's closed enum (see the addendum). MUST be in the set.
- `name` — the human-readable name (paragraph name, stage name, function name).
- `signature` — optional declaration text (PIC clause, parameter list, stage type).
- `container_symbol_id` — optional enclosing symbol's ID (the section/program/job
  that contains this symbol). Use it to express containment.
- `attributes` — optional open object for per-format extras (level number, stage
  type, etc.).

### `occurrences[]`
Each place a symbol is defined OR referenced in this chunk:
- `symbol_id` — the symbol it refers to.
- `role` — `definition` (this is where the symbol is declared) or `reference`
  (this is a use of it).
- `range` — `{start_line, end_line}` (1-indexed, within the artifact, inclusive).
- `evidence_snippet` — the source line(s) supporting the occurrence. Keep it short
  (one logical statement). Do NOT include credentials — see `redact-secrets.md`.
- `confidence` — `grounded` / `inferred` / `speculative` per the bright-line rule
  below. **When in doubt, choose the LOWER tier.**
- `confidence_reason` — a short reason code (e.g. `literal_paragraph`,
  `dynamic_call_target`, `interpolated_path`).

### `relationships[]`
Typed edges between two symbols:
- `rel` — one of `contains`, `calls`, `reads`, `writes`, `copies`, `references`,
  `schedules`.
- `from_id`, `to_id` — the two symbol IDs.
- `evidence_line` — the line where the relationship is established.
- `confidence` — same tiers + bright-line rule.

Map the format's transfer constructs to `calls` (PERFORM and CALL for COBOL; stage
links for DSX; function invocation / task dependency for ETL — see the addendum).
A copybook `COPY` is `copies`. Program/section containment is `contains`. File or
table access is `reads` / `writes`.

### `gaps[]`
Honest disclosure of anything you could NOT resolve statically:
- `kind` — e.g. `dynamic_call`, `copy_replacing_rename`, `dsx_rcp`,
  `unsupported_format`, `unresolved_symbol`.
- `line`, `detail`.
Never invent an edge to fill a gap. Record the gap instead.

## The bright-line confidence rule (HARD-RULE 2)

- `grounded` — the symbol / target is a LITERAL that fully resolves within the
  chunk (a quoted program name in `CALL 'TAXCALC'`, a paragraph name in
  `PERFORM 2100-COMPUTE-PAY`, a table name in `FROM TAX_BRACKETS`).
- `inferred` — resolved by an in-artifact heuristic (a copybook name resolved
  against a `COPY` earlier in the file; a variable resolved against a `VALUE`
  clause in the same chunk).
- `speculative` — ANY of: the target is a data-name / variable (e.g.
  `CALL WS-PROGRAM-NAME`), string interpolation (`#PARAM#`, `${VAR}`, `.format()`,
  f-string, `%s`), `COPY ... REPLACING`, DSX runtime column propagation (RCP), a
  `SELECT *` without schema metadata, or any symbol you cannot resolve to a literal
  within the chunk. **A dynamic CALL target is ALWAYS speculative**, never grounded.

The skill re-checks this rule deterministically after you emit (defense in depth),
but you should classify correctly so the evidence and reason are accurate.

## `boundary_status`
- `complete` — the chunk does not cut through a statement at either end.
- `partial_start` / `partial_end` / `partial_both` — a construct (a paragraph body,
  a multi-line `EXEC SQL`, a stage definition) is cut by the chunk boundary. The
  skill's `accumulate.py` uses this to pair partials deterministically — set it
  honestly so duplicate/half edges are reconciled rather than double-counted.

## Output contract
Emit ONLY the JSON object. It must parse. Arrays may be empty. Copy `file_sha256`,
`chunk_id`, `start_line`, `end_line`, `format` through verbatim. Set
`schema_version` to `"1.0.0"` and `extractor_id` to `"legacy-code-intel"`.
