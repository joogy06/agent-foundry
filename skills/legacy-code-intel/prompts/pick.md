# Addendum: Pick / MultiValue symbol vocabulary + call/read/write semantics

Read this alongside `analyze-symbols.md` when `format == pick`. Vocabulary grounded
in `pick-developer`. Pick / MultiValue BASIC is the source language of the UniVerse,
UniData, D3, jBASE, OpenQM, ScarletDME, and Reality platforms — concepts are universal,
exact spellings are dialect-dependent.

## Format detection (Pick BASIC frequently has no canonical extension)
Pick programs often live as items inside a `BP`-type file, so the file extension may be
absent or arbitrary. Treat a chunk as Pick when the content shows MultiValue signatures:
`SUBROUTINE name(args)`, `READNEXT ... FROM ... ELSE`, dynamic-array `<a,v,s>` indexing,
`OCONV(`/`ICONV(`, `CRT` (the MultiValue display verb), `EQUATE ... TO @` (mark-character
equates), `BEGIN CASE`/`END CASE`, `READU`/`WRITEU`/`MATREAD`/`MATWRITE`, or `EXECUTE`/
`PERFORM` running a TCL/query sentence. The extension hint is advisory; the content is the
real signal.

## `kind` closed set (Pick)
`program`, `subroutine`, `paragraph`, `dict_item`, `file`, `common_block`, `label`,
`variable`.

- `program` — a top-level cataloged program (`PROGRAM name` or the first executable
  unit of a BP item). The primary container.
- `subroutine` — an external `SUBROUTINE name(args)` (a CALLed module; its own item).
- `paragraph` — a PROC item or a UniVerse VOC paragraph (a stored TCL/query sentence
  sequence). Distinct from a BASIC label.
- `dict_item` — a dictionary item (D / I / A / S / X / PH) describing a stored attribute
  or a computed/joined value. Carry the dict type in `attributes.dict_type`.
- `file` — a MultiValue file opened via `OPEN "<file>" TO fvar` (DICT or DATA part).
- `common_block` — a named or unnamed `COMMON [/name/]` shared-memory block.
- `label` — an internal `GOSUB` target (a statement label within the program).
- `variable` — a BASIC variable or an `@`-system variable reference when worth a symbol.

## Scoped names (for the path-independent symbol_id)
- Program: `<program-name>` (e.g. `ORD.POST`).
- Subroutine: `subroutine/<NAME>` (path-independent — the same external SUBROUTINE
  CALLed from two programs resolves to the same ID).
- Paragraph / PROC: `paragraph/<name>` (VOC/MD-stable across programs).
- Dict item: `dict/<file>/<item-name>` (the dictionary of a file is cross-program stable).
- File: `file/<file-name>` (path-independent — the same logical file opened from two
  programs resolves identically).
- Common block: `<program-name>/common/<name>` (or `/common/UNNAMED`).
- Label: `<program-name>/label/<label-name>`.
- Variable: `<program-name>/var/<name>`.

## Relationships
- `CALL <NAME>(args)` → `calls` from the enclosing program to `subroutine/<NAME>`,
  **grounded** when the target is a literal name.
- `CALL @<var>(args)` → `calls` to the indirect target, **always speculative**; also
  emit a `dynamic_call` gap (the resolved subroutine name is not statically knowable).
- `EXECUTE "<tcl>"` / `PERFORM "<tcl>"` → `calls` to the named program/verb/paragraph in
  the quoted sentence. Read the quoted string as the TCL/query layer, not BASIC.
  **Grounded** only if the sentence names a literal verb/program; **speculative** if the
  sentence is built with interpolation (`:` concat, `<...>` substitution) — emit a
  `dynamic_call` gap.
- `CHAIN "<tcl>"` / `ENTER <name>` → `calls` (a no-return transfer); same literal-vs-
  interpolated rule as EXECUTE.
- `OPEN "<file>" TO fvar` → defines a `file` symbol; subsequent reads/writes through
  `fvar` attach to it.
- `READ` / `READU` / `READL` / `READV` / `READNEXT` / `MATREAD` (… `FROM fvar`) → `reads`
  to the `file` symbol that `fvar` was opened to.
- `WRITE` / `WRITEU` / `WRITEV` / `MATWRITE` / `DELETE` (… `ON fvar`) → `writes` to that
  `file` symbol.
- `COPY` / `$INCLUDE` / `INCLUDE <file> <item>` → `copies` from the program to the
  included item.
- A `dict_item` whose correlative/I-descriptor is a `Tfile` / `TRANS(file,…)` → a
  `references` edge to `file/<that-file>` (this is the MultiValue substitute for a SQL
  JOIN — the "column" is pulled from another file). A `dict_item` also `references` the
  `file` whose attribute it describes.
- A program `contains` its subroutines-defined-inline, common blocks, labels, and
  variables (use `container_symbol_id` + a `contains` relationship).
- `GOSUB <label>` → `calls` from the enclosing context to `<program>/label/<label>`,
  grounded when the label is visible in the chunk; record a gap + `inferred` if not.

## Dialect caution
The dictionary attribute layout differs between classic Pick / D3 (attr-7 = conversion,
attr-8 = correlative) and the U2 family (UniVerse / UniData: conversion in field 3,
computation in an I-descriptor). When emitting `dict_item` symbols, record the observed
`dict_type` and do NOT assume a fixed attribute layout. `LOCATE`/`INS`/`DEL` are the most
dialect-divergent verbs; they do not produce call/read/write edges and need no special
relationship handling, but do not over-interpret their arguments.

## Dynamic-construction caution (HARD-RULE 2)
Force `speculative` (and emit a gap) for: `CALL @var` (indirect call); `EXECUTE`/
`PERFORM`/`CHAIN` whose sentence is built by concatenation/substitution rather than a
literal; a file variable opened to an interpolated/computed file name (the resolved file
is not statically knowable). `emit_index._looks_dynamic` enforces `CALL @` and
interpolated `EXECUTE/PERFORM/CHAIN` as defense-in-depth over this prompt.

## Credential caution
Pick connection/credential material can appear in `OPEN` to remote files, in `EXECUTE`d
TCL that logs to another account, or in embedded SQL on SQL-enabled platforms (UniVerse
SQL). Follow `redact-secrets.md` — never place a password or full connection string in
`evidence_snippet`; emit the structure with the credential elided.
