# Per-Chunk SQL Structure Analysis Prompt

You are analysing ONE chunk of ONE SQL file (DDL and/or DML) as part of a
table/view **structure** recovery. Read the chunk and emit the **declared
table/view schema** as exactly one structured JSON object conforming to
`structure-finding.v1`. No prose before or after the JSON.

This prompt is model-neutral: it is run by whichever in-session AI CLI is active
(Claude Code, Codex CLI, GitHub Copilot CLI, or the Antigravity CLI `agy`).
Apply the rules below literally.

## Input you will receive

- `file_path` — repo-relative path of the file (forward-slash separators).
- `file_sha256` — sha256 of the **entire** file (NOT just this chunk).
- `chunk_id` — 1-indexed chunk number within the file.
- `start_line` / `end_line` — 1-indexed line range (inclusive) this chunk covers.
- `extractor_version` — the structure-recovery skill version (SemVer string).
- `chunk_content` — the verbatim text of the chunk.

## What you emit (one JSON object only)

Emit ONE finding per `CREATE TABLE` / `CREATE VIEW` you can see in the chunk. If
the chunk contains several `CREATE` statements, emit ONE object for the primary
one and record the others as separate findings only if your harness asks for one
object per chunk — otherwise emit the most complete `CREATE` in the chunk and let
the cross-file/accumulate pass union the rest. (When the harness expects exactly
one object per chunk, pick the first complete `CREATE`; the chunker's safe
breaks keep statements whole.)

```json
{
  "schema_version": "1.0.0",
  "extractor_id": "structure-recovery",
  "extractor_version": "<from input>",
  "file_path": "<from input>",
  "file_sha256": "<from input>",
  "chunk_id": <from input>,
  "start_line": <from input>,
  "end_line": <from input>,
  "object_kind": "table | view",
  "qualified_name": "<schema-qualified name verbatim, e.g. analytics.public.users>",
  "fields": [
    {
      "name": "<column name verbatim>",
      "ordinal": <0-indexed declaration order within the table>,
      "byte_offset": null,
      "length": null,
      "level": null,
      "pic_clause": null,
      "usage": null,
      "declared_type": "<SQL type verbatim, e.g. VARCHAR(255), NUMERIC(10,2), TIMESTAMP>",
      "normalized_type": "<string | integer | decimal | date | datetime | boolean | binary | null>",
      "nullable": <true | false when declared (NULL / NOT NULL); else null>,
      "occurs": null, "occurs_max": null, "occurs_depending_on": null,
      "redefines": null, "renames": null, "is_group": null, "is_filler": null,
      "sign_separate": null, "synchronized": null,
      "confidence": "grounded | inferred | speculative",
      "evidence_kind": "declared_column | inferred_naming | observed_usage",
      "enforcement": "declared | unknown"
    }
  ],
  "relationships": [
    {
      "kind": "pk | fk | join | unique",
      "from_field": "<column (or comma-joined composite) on THIS object>",
      "to_object": "<referenced qualified name for fk/join, else null>",
      "to_field": "<referenced column for fk/join, else null>",
      "evidence_kind": "declared_constraint | inferred_naming | observed_usage",
      "enforcement": "declared | unknown",
      "confidence": "grounded | inferred | speculative"
    }
  ],
  "gaps": [
    { "kind": "select_star_no_schema", "line": <1-indexed file-relative line>, "description": "<= 512 chars" }
  ],
  "confidence": "grounded | inferred | speculative",
  "evidence": { "file_path": "<from input>", "line": <1-indexed line of the CREATE / DML statement> }
}
```

`fields`, `relationships`, `gaps` are required arrays (use `[]` when empty).
`byte_offset`, `length`, and all COBOL-only keys (`level`, `pic_clause`, `usage`,
`occurs*`, `redefines`, `renames`, `is_group`, `is_filler`, `sign_separate`,
`synchronized`) are `null` for SQL. Emit **no keys outside the schema**
(`additionalProperties: false`).

## Mapping rules (DDL — the grounded path)

- `CREATE TABLE x.y (...)` → `object_kind: "table"`, `qualified_name: "x.y"`,
  one field per column declaration, `confidence: "grounded"`,
  `evidence_kind: "declared_column"`.
- `CREATE VIEW x.y AS SELECT ...` → `object_kind: "view"`. If the view's SELECT
  lists explicit columns, emit them (`declared_column`); if it is `SELECT *`,
  emit `fields: []` and a `gap: select_star_no_schema`.
- Column `declared_type`: copy the type verbatim (`VARCHAR(255)`,
  `NUMERIC(10,2)`, `INT`, `TIMESTAMP WITH TIME ZONE`). Derive a best-effort
  `normalized_type` (`string` / `integer` / `decimal` / `date` / `datetime` /
  `boolean` / `binary`).
- `nullable`: `false` when the column says `NOT NULL`; `true` when it explicitly
  says `NULL`; otherwise `null` (undeclared).

## Constraints → relationships

- `PRIMARY KEY (col[, ...])` (inline or table-level) → relationship
  `kind: "pk"`, `from_field` = the column or comma-joined composite,
  `evidence_kind: "declared_constraint"`, `enforcement: "declared"`,
  `confidence: "grounded"`. `to_object`/`to_field` are `null` for a PK.
- `FOREIGN KEY (col) REFERENCES other.tbl (othercol)` →
  `kind: "fk"`, `from_field: "col"`, `to_object: "other.tbl"`,
  `to_field: "othercol"`, `evidence_kind: "declared_constraint"`,
  `enforcement: "declared"`, `confidence: "grounded"`.
- `UNIQUE (col[, ...])` → `kind: "unique"`, `evidence_kind:
  "declared_constraint"`, `enforcement: "declared"`, `confidence: "grounded"`.
- A `REFERENCES` written inline on a column is still a declared FK — emit the
  same `fk` relationship.

> `enforcement: "declared"` means the source *declares* the constraint; it does
> NOT prove the constraint is deployed/enforced in the live database. That is the
> honest limit of static analysis.

## DML fallback (the inferred path)

When there is no DDL for a table but the chunk uses it:

- `INSERT INTO x.y (col_a, col_b, ...) VALUES ...` → emit `object_kind: "table"`,
  `qualified_name: "x.y"`, one field per named column with
  `confidence: "inferred"`, `evidence_kind: "observed_usage"`,
  `enforcement: "unknown"`, `declared_type: null` (DML rarely declares types).
- `SELECT col_a, col_b FROM x.y` → inferred columns (`observed_usage`), same as
  above. For a multi-table SELECT, attribute each column to its table only when
  it is unambiguously qualified (`x.col`); otherwise leave it for accumulate.
- `SELECT * FROM x.y` with no derivable column list → `fields: []` plus a
  `gap: select_star_no_schema` (you saw the table but cannot recover its schema).

## JOIN — a hint, never a foreign key

- `... FROM a JOIN b ON a.k = b.k` → emit a relationship `kind: "join"`,
  `from_field: "k"` (the column on this object), `to_object: "b"`,
  `to_field: "k"`, `evidence_kind: "observed_usage"`, `enforcement: "unknown"`,
  `confidence: "inferred"`. A JOIN is an **advisory** join hint — it is NOT a
  declared foreign key. Do NOT emit `kind: "fk"` for a JOIN.

## Convention-based inference (`*_id` → `id`)

- A column named like `customer_id` MAY be an inferred join hint to a
  `customer(id)` table. If you choose to surface it, emit a relationship
  `kind: "join"` (NOT `fk`), `evidence_kind: "inferred_naming"`,
  `enforcement: "unknown"`, `confidence: "inferred"`. This is advisory; most of
  the time it is safer to leave convention inference to the cross-file
  relationship pass and emit nothing here.

## Confidence summary

| Tier | When |
|---|---|
| `grounded` | A declared `CREATE TABLE/VIEW` column, or a declared PK/FK/UNIQUE constraint. |
| `inferred` | Columns recovered from DML (INSERT/SELECT), a `JOIN ON` join hint, or a `*_id` naming convention. |
| `speculative` | Anything templated/interpolated (e.g. `INSERT INTO ${TABLE}`), or a partial statement cut by the chunk boundary. |

Roll the object-level `confidence` up to the most conservative tier present.

## Gap reporting

Closed enum for `gap.kind` relevant to SQL:

- `select_star_no_schema` — a `SELECT *` with no derivable column schema.
- `dynamic_layout` — a templated/interpolated table or column name
  (`${TABLE}`, `{{ name }}`, string-concatenated identifiers).
- `redaction_applied` — content was redacted (see `redact.md`).

`line` is 1-indexed and file-relative.

## Format requirements

- Emit ONE JSON object only. No prose, no markdown fences, no comments.
- Valid JSON: double-quoted strings, no trailing commas, no comments.
- `byte_offset` and `length` are always `null` (SQL never declares byte
  positions; that is a flat-file/COBOL-downstream concern).
- Line numbers are 1-indexed and file-relative.
- If the chunk holds no table/view structure, emit `fields: []`,
  `relationships: []`, and set `qualified_name` to the best identifier you can
  see or `"UNKNOWN"`.

## Anti-patterns — DO NOT DO

- Do NOT emit `kind: "fk"` for a `JOIN ON` — that is `kind: "join"` (inferred).
- Do NOT mark DML-inferred columns as `grounded` — they are `inferred` /
  `observed_usage`.
- Do NOT put a value in `byte_offset` or `length`.
- Do NOT emit `enforcement: "declared"` for an inferred/observed relationship.
- Do NOT include credentials from a connection string in any string — elide per
  `redact.md`.
- Do NOT add keys outside the schema (`additionalProperties: false`).

## Worked example (this output passes `validate_finding.py`)

Input chunk (lines 1–6 of `ddl/users.sql`):

```sql
CREATE TABLE analytics.users (
  id          BIGINT       NOT NULL,
  email       VARCHAR(255) NOT NULL,
  org_id      BIGINT       NOT NULL,
  PRIMARY KEY (id),
  FOREIGN KEY (org_id) REFERENCES analytics.orgs (id)
);
```

Emit:

```json
{
  "schema_version": "1.0.0",
  "extractor_id": "structure-recovery",
  "extractor_version": "1.0.0",
  "file_path": "ddl/users.sql",
  "file_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "chunk_id": 1,
  "start_line": 1,
  "end_line": 7,
  "object_kind": "table",
  "qualified_name": "analytics.users",
  "fields": [
    {"name": "id", "ordinal": 0, "byte_offset": null, "length": null, "level": null, "pic_clause": null, "usage": null, "declared_type": "BIGINT", "normalized_type": "integer", "nullable": false, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": null, "is_filler": null, "sign_separate": null, "synchronized": null, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "declared"},
    {"name": "email", "ordinal": 1, "byte_offset": null, "length": null, "level": null, "pic_clause": null, "usage": null, "declared_type": "VARCHAR(255)", "normalized_type": "string", "nullable": false, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": null, "is_filler": null, "sign_separate": null, "synchronized": null, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "declared"},
    {"name": "org_id", "ordinal": 2, "byte_offset": null, "length": null, "level": null, "pic_clause": null, "usage": null, "declared_type": "BIGINT", "normalized_type": "integer", "nullable": false, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": null, "is_filler": null, "sign_separate": null, "synchronized": null, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "declared"}
  ],
  "relationships": [
    {"kind": "pk", "from_field": "id", "to_object": null, "to_field": null, "evidence_kind": "declared_constraint", "enforcement": "declared", "confidence": "grounded"},
    {"kind": "fk", "from_field": "org_id", "to_object": "analytics.orgs", "to_field": "id", "evidence_kind": "declared_constraint", "enforcement": "declared", "confidence": "grounded"}
  ],
  "gaps": [],
  "confidence": "grounded",
  "evidence": {"file_path": "ddl/users.sql", "line": 1}
}
```

## You will now receive the chunk content. Emit one valid JSON object conforming to `structure-finding.v1` (object_kind = table or view).
