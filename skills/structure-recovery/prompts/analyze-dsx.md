# Per-Chunk DataStage (.dsx) Structure Analysis Prompt

You are analysing ONE chunk of ONE IBM DataStage export (`.dsx`) as part of a
table/record **structure** recovery. Read the chunk **as text** and emit the
**declared table-definition / link column schema** as exactly one structured
JSON object conforming to `structure-finding.v1`. No prose before or after the
JSON.

This prompt is model-neutral: it is run by whichever in-session AI CLI is active
(Claude Code, Codex CLI, GitHub Copilot CLI, or the Antigravity CLI `agy`).
Apply the rules below literally.

## CRITICAL — read `.dsx` as chunked TEXT, never as XML (decision N2)

> The structure-recovery skill does **NO** programmatic XML parsing of `.dsx`
> (decision N2). You read the chunk as **plain text** and recognise the
> DataStage record/column markers by pattern. This is deliberate: not parsing
> XML means there is **no XXE attack surface** from a hostile `.dsx`. Do NOT
> attempt to "parse the XML tree" — scan the text for the column/record markers
> described below.

(If a future version ever needs true structural DSX parsing, the design requires
`defusedxml` — but v1, and therefore this prompt, is text-scan only.)

## Input you will receive

- `file_path` — repo-relative path of the file (forward-slash separators).
- `file_sha256` — sha256 of the **entire** file (NOT just this chunk).
- `chunk_id` — 1-indexed chunk number within the file.
- `start_line` / `end_line` — 1-indexed line range (inclusive) this chunk covers.
- `extractor_version` — the structure-recovery skill version (SemVer string).
- `chunk_content` — the verbatim text of the chunk.

## What you emit (one JSON object only)

A DataStage table definition or stage link column set maps to
`object_kind: "table"`.

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
  "object_kind": "table",
  "qualified_name": "<table-def or link identifier, e.g. dsx://JOB/STAGE/LINK or the table-def name>",
  "fields": [
    {
      "name": "<column name verbatim>",
      "ordinal": <0-indexed declaration order>,
      "byte_offset": null,
      "length": null,
      "level": null,
      "pic_clause": null,
      "usage": null,
      "declared_type": "<DataStage SQL type + precision/scale, e.g. Decimal(10,2), VarChar(255), Integer>",
      "normalized_type": "<string | integer | decimal | date | datetime | boolean | binary | null>",
      "nullable": <true | false when a Nullable flag is present; else null>,
      "occurs": null, "occurs_max": null, "occurs_depending_on": null,
      "redefines": null, "renames": null, "is_group": null, "is_filler": null,
      "sign_separate": null, "synchronized": null,
      "confidence": "grounded | inferred | speculative",
      "evidence_kind": "declared_column",
      "enforcement": "declared | unknown"
    }
  ],
  "relationships": [
    {
      "kind": "pk",
      "from_field": "<column flagged as key>",
      "to_object": null,
      "to_field": null,
      "evidence_kind": "declared_constraint",
      "enforcement": "unknown",
      "confidence": "grounded"
    }
  ],
  "gaps": [
    { "kind": "rcp_columns | dynamic_layout", "line": <1-indexed file-relative line>, "description": "<= 512 chars" }
  ],
  "confidence": "grounded | inferred | speculative",
  "evidence": { "file_path": "<from input>", "line": <1-indexed line of the table-def / link record> }
}
```

`fields`, `relationships`, `gaps` are required arrays (use `[]` when empty).
`byte_offset`, `length`, and all COBOL-only keys are `null` for DSX. Emit **no
keys outside the schema** (`additionalProperties: false`).

## Recognising columns in `.dsx` text

DataStage exports describe table definitions and stage link metadata in a
property-bag text format. Scan the chunk text for column/record markers such as:

- A record/table-definition marker (e.g. a `BEGIN DSRECORD` / `TableDefinition`
  / `Record` span, or a metadata block whose properties describe columns). Treat
  the span as one object; `qualified_name` = the table-def name or the
  `Job/Stage/Link` path you can read from the surrounding properties.
- Per-column property groups carrying a column `Name`, an SQL type (`SqlType` /
  `DataType`), `Precision` / `Scale`, a `Nullable` flag, and a key/`KeyPosition`
  flag. Emit one field per column.

Because you are reading text (not a parsed tree), recover what the markers
plainly state; when a column's properties are split across the chunk boundary and
you cannot read the full column, downgrade that field to `speculative` and let
accumulate union it with the adjacent chunk.

### Types
- `declared_type`: combine the DataStage type with precision/scale when present
  (`Decimal(10,2)`, `VarChar(255)`, `Integer`, `Timestamp`). Derive a best-effort
  `normalized_type`.
- `nullable`: `true`/`false` only when a `Nullable` property is explicit; else
  `null`.

### Keys → PK (grounded)
- A column flagged as a key (e.g. `Key = 1` / a non-zero `KeyPosition`) →
  emit a relationship `kind: "pk"`, `from_field` = the column name,
  `evidence_kind: "declared_constraint"`, `enforcement: "unknown"` (DataStage key
  flags assert a key but not a deployed DB constraint), `confidence: "grounded"`.
  For a composite key, emit `from_field` as the comma-joined key columns in key
  order.
- DataStage exports do not, in general, carry declared foreign keys — do **not**
  invent `fk` relationships. (Cross-object relationships are the cross-file
  pass's concern.)

## Gaps specific to DataStage

- **RCP (Runtime Column Propagation)** — when the stage/link has RCP enabled, the
  column schema is **not** statically present (columns propagate at runtime).
  Emit `fields: []` (or only the columns actually declared) plus a
  `gap: rcp_columns` (`description: "Runtime Column Propagation enabled — schema
  not statically declared"`).
- **`#PARAM#` / job-parameter names** — when a table name, file path, or column
  set is driven by a `#PARAM#` token (DataStage parameter substitution), the
  layout is dynamic. Emit a `gap: dynamic_layout` and mark any affected
  identifier `speculative`.
- `redaction_applied` — content was redacted (see `redact.md`).

`line` is 1-indexed and file-relative.

## Confidence summary

| Tier | When |
|---|---|
| `grounded` | A column whose name + type + (optional) key flag are plainly declared in the chunk text. |
| `inferred` | A column whose type/nullability you could only partially read. |
| `speculative` | A column or identifier driven by `#PARAM#`, or split across the chunk boundary so you cannot read it fully. |

Roll the object-level `confidence` up to the most conservative tier present.

## Format requirements

- Emit ONE JSON object only. No prose, no markdown fences, no comments.
- Valid JSON: double-quoted strings, no trailing commas, no comments.
- `byte_offset` and `length` are always `null`.
- Line numbers are 1-indexed and file-relative.
- Read the chunk as TEXT — never claim to have parsed XML.
- If the chunk holds no table-def/link columns, emit `fields: []`,
  `relationships: []`, and set `qualified_name` to the best identifier you can
  read or `"UNKNOWN"`.

## Anti-patterns — DO NOT DO

- Do NOT parse the `.dsx` as XML or build an element tree — text-scan only (N2).
- Do NOT invent foreign keys from a DataStage export.
- Do NOT emit columns for an RCP-enabled stage as if the schema were known —
  emit `gap: rcp_columns`.
- Do NOT resolve `#PARAM#` tokens to a concrete value — emit `gap: dynamic_layout`.
- Do NOT put a value in `byte_offset` or `length`.
- Do NOT include credentials (DSN passwords sometimes appear in DSX properties) —
  elide per `redact.md`.
- Do NOT add keys outside the schema (`additionalProperties: false`).

## Worked example (this output passes `validate_finding.py`)

Input chunk (lines 40–47 of `jobs/LOAD_CUSTOMERS.dsx`, read as text — a
table-definition block declaring three columns, the first a key):

```
   Name "CUSTOMERS_TD"
   Columns
     ( Name "CUST_ID";   SqlType Integer;       Nullable 0; KeyPosition 1 )
     ( Name "CUST_NAME";  SqlType VarChar(60);    Nullable 1; KeyPosition 0 )
     ( Name "BALANCE";    SqlType Decimal(11,2);  Nullable 1; KeyPosition 0 )
```

Emit:

```json
{
  "schema_version": "1.0.0",
  "extractor_id": "structure-recovery",
  "extractor_version": "1.0.0",
  "file_path": "jobs/LOAD_CUSTOMERS.dsx",
  "file_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "chunk_id": 3,
  "start_line": 40,
  "end_line": 47,
  "object_kind": "table",
  "qualified_name": "CUSTOMERS_TD",
  "fields": [
    {"name": "CUST_ID", "ordinal": 0, "byte_offset": null, "length": null, "level": null, "pic_clause": null, "usage": null, "declared_type": "Integer", "normalized_type": "integer", "nullable": false, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": null, "is_filler": null, "sign_separate": null, "synchronized": null, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "declared"},
    {"name": "CUST_NAME", "ordinal": 1, "byte_offset": null, "length": null, "level": null, "pic_clause": null, "usage": null, "declared_type": "VarChar(60)", "normalized_type": "string", "nullable": true, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": null, "is_filler": null, "sign_separate": null, "synchronized": null, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "declared"},
    {"name": "BALANCE", "ordinal": 2, "byte_offset": null, "length": null, "level": null, "pic_clause": null, "usage": null, "declared_type": "Decimal(11,2)", "normalized_type": "decimal", "nullable": true, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": null, "is_filler": null, "sign_separate": null, "synchronized": null, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "declared"}
  ],
  "relationships": [
    {"kind": "pk", "from_field": "CUST_ID", "to_object": null, "to_field": null, "evidence_kind": "declared_constraint", "enforcement": "unknown", "confidence": "grounded"}
  ],
  "gaps": [],
  "confidence": "grounded",
  "evidence": {"file_path": "jobs/LOAD_CUSTOMERS.dsx", "line": 40}
}
```

## You will now receive the chunk content. Emit one valid JSON object conforming to `structure-finding.v1` (object_kind = table). Read it as text — no XML parsing.
