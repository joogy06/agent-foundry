# Addendum: ETL (shell / SQL / Python) symbol vocabulary + call semantics

Read this alongside `analyze-symbols.md` when `format == etl`. Covers the ETL
scripting glue: shell scripts, standalone SQL, and Python ETL.

## `kind` closed set (ETL)
`function`, `variable`, `sql_cte`, `table`, `call_target`, `shell_task`.

- `function` — a shell function, Python `def`, or a named SQL block.
- `variable` — a shell/Python variable or SQL bind variable. Carry the assignment in
  `signature` when literal.
- `sql_cte` — a `WITH <name> AS (...)` common table expression.
- `table` — a database table/view referenced in SQL (`FROM`/`JOIN`/`INSERT INTO`).
- `call_target` — the target of an invocation (a called script/function/program).
- `shell_task` — a discrete pipeline step (a command invocation, a job step).

## Scoped names
- Function: `<file-stem>/<function-name>` (e.g. `load_dims/transform_rows`).
- Variable: `<file-stem>/var/<name>`.
- CTE: `<file-stem>/cte/<name>`.
- Table: `table/<schema>.<name>` if schema-qualified, else `table/<name>`
  (path-independent — the same table from two scripts resolves identically).
- Call target: `call/<target>` (literal) or `<file-stem>/dyn/<expr>` (dynamic).
- Shell task: `<file-stem>/task/<n>`.

## Relationships
- A function calling another function / script → `calls`. Grounded when the callee
  is a literal name; **speculative** when it is `$(...)`, `${VAR}`, an `eval`, a
  `.format()` / f-string, or otherwise dynamically constructed.
- `SELECT ... FROM <table>` → `reads`; `INSERT/UPDATE/DELETE/MERGE/COPY INTO` →
  `writes`. `SELECT *` is `speculative`.
- A CTE referenced by the main query → `references` from the query to the CTE
  (`inferred` — resolved within the same file).
- A shell step invoking the next step / a downstream job → `schedules` or `calls`
  depending on whether it is a scheduler hand-off or an in-process call.
- A script `contains` its functions / shell tasks.

## Dynamic-construction caution (HARD-RULE 2)
ETL glue is interpolation-dense: `${TABLE}`, `$(date +%Y%m%d)`, Python f-strings,
`.format()`, `%s` SQL params. ANY of these in the evidence forces `speculative` and
should also produce a gap describing what could not be resolved to a literal.

## Credential caution
ETL scripts routinely hold DSNs, `PGPASSWORD=`, JDBC URLs with `?password=`,
`aws_secret_access_key=`. Follow `redact-secrets.md` — never emit the value.
