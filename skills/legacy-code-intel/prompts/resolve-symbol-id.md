# Prompt: resolve-symbol-id (path-independent content-addressed IDs)

Every symbol gets a path-INDEPENDENT, content-addressed ID. This is a locked design
decision (design §3): content-hash dedup CONFLICTS with path-derived IDs — the same
copybook in two repositories must resolve to the SAME symbol ID, and a renamed-but-
identical file must NOT fork the graph. So the ID derives from the artifact's content
hash + a scoped name, NEVER from the filesystem path.

## ID format
```
codelib://sha256/<file_sha256>#sym/<scoped-name>
```
- `<file_sha256>` — the sha256 of the WHOLE artifact (given to you as `file_sha256`).
- `<scoped-name>` — the qualified, path-free name for the symbol (see each format's
  addendum for the exact scoping rule).

## Scoped-name rules (summary; the per-format addendum is authoritative)
- COBOL paragraph: `<PROGRAM-ID>/<paragraph-name>`
- COBOL copybook member: `copybook/<member-name>` (cross-program identical)
- DSX stage: `<job-name>/<stage-name>`
- ETL table: `table/<schema>.<name>` or `table/<name>`
- ETL function: `<file-stem>/<function-name>`

## Why paths are NOT in the ID
- The same copybook `EMPWS` `COPY`-ed from `PAYROLL.cbl` and `BILLING.cbl` resolves to
  the identical `copybook/EMPWS` symbol, so cross-artifact `refs` work.
- A file moved from `src/old/PAY.cbl` to `src/new/PAY.cbl` with identical bytes keeps
  the SAME symbol IDs (same `file_sha256`), so history is continuous.
- Paths still matter for navigation — they live in `refs.by_path` (the reverse
  index), populated by `emit_index.py`, NOT in the ID.

## Cross-artifact target IDs
When you emit a relationship whose target lives in ANOTHER artifact (a `COPY` of a
copybook, a `CALL` to another program, a table shared across scripts), use the
target's CONTENT-INDEPENDENT scoped form where the design says so:
- copybooks → `copybook/<member>` (no per-artifact hash; the copybook is its own
  artifact when ingested, and this stable name lets the catalog join them).
- literal program CALL → `program/<TARGET>`.
- shared table → `table/<name>`.
For these cross-artifact stable names, still wrap them in the `codelib://sha256/
<file_sha256>#sym/...` envelope using the CURRENT artifact's hash — the catalog joins
on the scoped tail. Do not fabricate another artifact's hash.

## Stability
The same artifact analysed twice (same bytes, same prompt set, same model) MUST
produce identical IDs. IDs are deterministic functions of (file_sha256, scoped-name)
— no timestamps, no counters, no randomness.
