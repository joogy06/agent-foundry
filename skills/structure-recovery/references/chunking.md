# Reference: chunking discipline (design §3.1)

Legacy artifacts routinely exceed the LLM context window, so `structure-recovery`
chunks every input before the per-chunk extraction pass. The discipline below keeps a
single structural record from ever being bisected across a chunk boundary, while
staying **backward-compatible** with the sibling `lineage-extract-static` chunker
(its existing tests must stay green — DoD #7).

## Two pieces

1. **`structure-recovery/scripts/boundary_hints.py`** — PURE Python, NO LLM, NO XML
   parser (N2 — regex/text-scan only). Computes the SAFE split line numbers for a
   given format.
2. **`lineage-extract-static/scripts/chunk_file.py`** — the shared chunker, extended
   with a `preferred_break_lines` parameter that snaps cuts to those safe lines.
   Format detection stays OUTSIDE the chunker.

## Defaults (env-overridable)

```
STRUCT_CHUNK_LINES   = 1500   # target chunk size, in lines
STRUCT_OVERLAP_LINES = 200    # overlap carried between adjacent chunks
```

Both read from the environment in `chunk_file.py` (`STRUCT_CHUNK_LINES`,
`STRUCT_OVERLAP_LINES`). The overlap is what lets `accumulate_structure.py` re-pair a
record whose declaration straddles two chunks (its `_adjacent_within_overlap`
predicate).

## Safe-break detection per format (`boundary_hints.safe_break_lines`)

`safe_break_lines(text, format_hint)` returns a SORTED, de-duplicated list of line
numbers at which a cut will not bisect a record. By format:

| Format hint | Safe break = line of … |
|---|---|
| `sql` | a statement terminator `;` at paren-depth 0 (end of a `CREATE TABLE` / `CREATE VIEW`). |
| `cobol` / `copybook` | an `01` or `77` level number in Area A (cols 8-11) — the start of a new record/elementary item. |
| `datastage-dsx` | a `<Record>` / `<TableDefinition>` element span — **regex-DETECTED, NOT parsed** (N2: no XML parser, no XXE surface). |
| `flat-file-layout` | a section / record-header line (`RECORD:`, `[Section]`, a column-banner row). |

`normalize_format_hint` maps the file-extension hints into these buckets; the
structure extensions `.cpy` → `copybook` and `.fd` / `.layout` → `flat-file-layout`
are added to `chunk_file.detect_language_hint`.

## Snap / widen / oversized behavior (`chunk_file.compute_chunk_boundaries`)

The `preferred_break_lines` parameter is **`Sequence[int] | None`, default `None`
(NOT a mutable `[]` — Codex Finding 5)**:

- **`preferred_break_lines=None`** ⇒ the chunker is BYTE-IDENTICAL to its pre-change
  behavior. This is what keeps the lineage tests green (DoD #7).
- **`preferred_break_lines` provided** ⇒ each computed cut is snapped to the nearest
  **preceding** safe break, and the overlap is widened so a record header is carried
  forward into the next chunk.
- **A single record larger than `STRUCT_CHUNK_LINES`** ⇒ the chunker emits an
  **oversized chunk** spanning the whole record and records a
  **`gap:record_exceeds_chunk`** for that span, rather than splitting the record
  (v1 scope — per-field sub-chunking of an oversized record is out of scope, design
  §8). Downstream renderers banner the gap; the record is still extracted as a whole.

## Why snap to the *preceding* break

Snapping backward (never forward) guarantees the cut lands at or before the target
line, so a chunk never ends in the middle of a record and the next chunk always begins
at a clean record boundary. Combined with the widened overlap, the same record's
declaration is fully present in at least one chunk — the precondition the accumulator's
ordinal-union pairing relies on.

## Security note (N2)

DSX is read as **chunked text** and its record spans are **regex-detected**, never
XML-parsed — there is no XXE surface. If structural DSX parsing is ever needed in a
future version it MUST use `defusedxml`; v1 stays parser-dep-free on purpose.
