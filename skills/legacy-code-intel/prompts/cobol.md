# Addendum: COBOL symbol vocabulary + call/copy semantics

Read this alongside `analyze-symbols.md` when `format == cobol`. Vocabulary grounded
in `cobol-developer` + `ibm-mainframe`.

## `kind` closed set (COBOL)
`program`, `division`, `section`, `paragraph`, `data_item`, `copybook`,
`file_descriptor`, `call_target`.

- `program` — the `PROGRAM-ID`. The top-level container of everything.
- `division` — IDENTIFICATION / ENVIRONMENT / DATA / PROCEDURE.
- `section` — a named section (e.g. `FILE SECTION`, `WORKING-STORAGE SECTION`, or a
  PROCEDURE-DIVISION section).
- `paragraph` — a named paragraph in the PROCEDURE DIVISION (e.g. `2100-COMPUTE-PAY`).
  This is the primary call-graph node.
- `data_item` — a `01`/`05`/… level data declaration (carry the PIC clause in
  `signature`, the level number in `attributes.level`).
- `copybook` — a member named in a `COPY` statement.
- `file_descriptor` — an `FD` entry.
- `call_target` — the operand of a `CALL` (a literal program name, or a data-name
  for a dynamic call).

## Scoped names (for the path-independent symbol_id)
- Program: `<PROGRAM-ID>` (e.g. `PAYROLL`).
- Paragraph: `<PROGRAM-ID>/<paragraph-name>` (e.g. `PAYROLL/2100-COMPUTE-PAY`).
- Section: `<PROGRAM-ID>/<section-name>`.
- Data item: `<PROGRAM-ID>/data/<item-name>`.
- Copybook member: `copybook/<member-name>` (path-independent across programs — the
  same copybook referenced from two programs resolves to the same ID).
- Call target (literal): `program/<TARGET>`; (dynamic data-name): `<PROGRAM-ID>/dyn/<data-name>`.

## Relationships
- `PERFORM <paragraph>` → `calls` (from the enclosing paragraph to the target).
  Grounded when the target is a literal paragraph name.
- `PERFORM <a> THRU <b>` → `calls` edges to each paragraph in the range you can see;
  if the range endpoints are not both visible in the chunk, record a gap and emit
  what you can as `inferred`.
- `CALL 'LITERAL'` → `calls` to `program/<LITERAL>`, **grounded**.
- `CALL <data-name>` → `calls` to the dynamic target, **always speculative**; also
  emit a `gap` of kind `dynamic_call`.
- `COPY <member>` → `copies` from the program to `copybook/<member>`. `COPY ...
  REPLACING ...` → still `copies`, but **speculative** + a `copy_replacing_rename`
  gap (the post-replace symbol names are not statically knowable here).
- Program `contains` its sections/paragraphs/data items (use `container_symbol_id`
  + emit a `contains` relationship).
- `EXEC SQL SELECT ... FROM <table>` → `reads` to a `call_target`/table symbol;
  `INSERT/UPDATE/DELETE` → `writes`. A `SELECT *` is `speculative`.
- `READ <file>` → `reads`; `WRITE`/`REWRITE` → `writes` (file_descriptor symbol).

## Credential caution
`EXEC SQL CONNECT ... IDENTIFIED BY '<pw>'` and similar carry credentials. Follow
`redact-secrets.md`: do NOT place the password in `evidence_snippet`. Emit the
structure, with the credential elided.
