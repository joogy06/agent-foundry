# Per-Chunk Flat-File Layout Structure Analysis Prompt

You are analysing ONE chunk of ONE flat-file **layout document** as part of a
table/record **structure** recovery. The artifact is NOT the data — it is a
layout/spec describing a positional record, a `.schema` block, an embedded
copybook, or a delimited/CSV header. Read the chunk and emit the **declared
field layout** as exactly one structured JSON object conforming to
`structure-finding.v1`. No prose before or after the JSON.

This prompt is model-neutral: it is run by whichever in-session AI CLI is active
(Claude Code, Codex CLI, GitHub Copilot CLI, or the Antigravity CLI `agy`).
Apply the rules below literally.

## The ONE place a chunk-level finding may carry a position

> For most artifacts, `byte_offset` and `length` MUST be `null`. Flat-file
> **positional layout documents** are the single exception — but the declared
> position does **NOT** go in `byte_offset`/`length`. It goes in
> `declared_start` / `declared_end`, and **only** when you set
> `position_declared: true`. The validator still REJECTS any non-null
> `byte_offset`/`length`. The declared start/end are **advisory**: accumulate
> cross-checks them against the deterministically-computed sequence and downgrades
> + gaps on mismatch.

So: `byte_offset: null` and `length: null` on **every** field, always. Declared
positions live in `declared_start` / `declared_end` behind `position_declared`.

## Input you will receive

- `file_path` — repo-relative path of the file (forward-slash separators).
- `file_sha256` — sha256 of the **entire** file (NOT just this chunk).
- `chunk_id` — 1-indexed chunk number within the file.
- `start_line` / `end_line` — 1-indexed line range (inclusive) this chunk covers.
- `extractor_version` — the structure-recovery skill version (SemVer string).
- `chunk_content` — the verbatim text of the chunk.

## What you emit (one JSON object only)

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
  "object_kind": "flatfile_layout",
  "qualified_name": "<the layout/record identifier, e.g. LANDING/customers.dat>",
  "fields": [
    {
      "name": "<field name verbatim>",
      "ordinal": <0-indexed declaration order>,
      "byte_offset": null,
      "length": null,
      "level": null,
      "pic_clause": null,
      "usage": null,
      "declared_type": "<declared type token if the layout states one, else null>",
      "normalized_type": "<string | integer | decimal | date | datetime | boolean | binary | null>",
      "nullable": null,
      "occurs": null, "occurs_max": null, "occurs_depending_on": null,
      "redefines": null, "renames": null, "is_group": null, "is_filler": null,
      "sign_separate": null, "synchronized": null,
      "position_declared": <true ONLY for a positional doc that states byte positions; else null>,
      "declared_start": <declared start position, valid ONLY when position_declared=true; else null>,
      "declared_end": <declared end position, valid ONLY when position_declared=true; else null>,
      "confidence": "grounded | inferred | speculative",
      "evidence_kind": "declared_column",
      "enforcement": "unknown"
    }
  ],
  "relationships": [],
  "gaps": [
    { "kind": "dynamic_layout | redaction_applied", "line": <1-indexed file-relative line>, "description": "<= 512 chars" }
  ],
  "confidence": "grounded | inferred | speculative",
  "evidence": { "file_path": "<from input>", "line": <1-indexed line of the layout header> }
}
```

`fields`, `relationships`, `gaps` are required arrays (use `[]` when empty).
`byte_offset` and `length` are `null` on every field. `position_declared` /
`declared_start` / `declared_end` are **flat-file only** and MUST be `null`/absent
for SQL/DSX/COBOL findings. Emit **no keys outside the schema**
(`additionalProperties: false`).

## The four flat-file shapes

### 1. Positional-table layout doc (the declared-offset case)
A table like `Field | Start | End | Len | Type` (column headers vary:
`Position`, `From`, `To`, `Length`, `Format`). For each row:
- `name` = the field name.
- `position_declared: true`.
- `declared_start` = the stated start position; `declared_end` = the stated end
  position. Use the document's own convention as-is (1-indexed or 0-indexed — do
  not "fix" it; accumulate reconciles against the computed sequence).
- If only a length (no start/end) is given, set `declared_start: null`,
  `declared_end: null`, `position_declared: false`, and leave positions to the
  downstream sequencer (a length-only layout is ordinal + length, not a declared
  absolute position).
- `confidence: "grounded"` for a clearly tabulated row.

### 2. `.schema` block (typed fields, no positions)
A schema block listing `name: type` (Avro-ish / JSON-schema-ish / DataStage
`.schema`). Emit typed fields with `declared_type` + `normalized_type`,
`position_declared: false`, `declared_start/end: null`, ordinal by declaration
order, `confidence: "grounded"`.

### 3. Embedded copybook
If the layout embeds a COBOL copybook fragment (01-level + PIC clauses), apply
the **COBOL rules** from `analyze-cobol.md`: emit `level`, verbatim `pic_clause`,
`usage` (explicit DISPLAY when omitted, group USAGE inheritance), OCCURS /
REDEFINES / RENAMES, `byte_offset: null`, `length: null`, and
`position_declared: false`. Do NOT emit declared positions for a copybook (the
offset calculator computes them). You may keep `object_kind: "flatfile_layout"`
if the surrounding artifact is a flat-file spec, but treat the fields with COBOL
semantics.

### 4. Delimited / CSV header
A header row of comma/tab/pipe-separated column names (no positions). Emit one
field per column, ordinal by position, `declared_type: null` (a CSV header rarely
declares types), `position_declared: false`, `declared_start/end: null`,
`confidence: "inferred"` (a header names columns but does not declare a typed
schema). **No byte offsets** — delimited records have no fixed positions.

## Relationships

Flat-file layouts do not declare foreign keys. Emit `relationships: []`. (Any
cross-record relationship is the opt-in cross-file pass's concern.)

## Gaps

- `dynamic_layout` — the layout is templated/parameterised (e.g. a record format
  selected by a control field or a `#PARAM#`-style token), so the static layout
  is not fully determinable.
- `record_exceeds_chunk` — the chunker flagged the layout record as larger than
  the chunk cap (only emit if your input says so).
- `redaction_applied` — content was redacted (see `redact.md`).

`line` is 1-indexed and file-relative.

## Confidence summary

| Tier | When |
|---|---|
| `grounded` | A clearly tabulated positional row, a typed `.schema` field, or a clean embedded-copybook elementary item. |
| `inferred` | A delimited/CSV header (names without types), or a row you could only partially read. |
| `speculative` | A templated/parameterised layout, or a field cut by the chunk boundary. |

Roll the object-level `confidence` up to the most conservative tier present.

## Format requirements

- Emit ONE JSON object only. No prose, no markdown fences, no comments.
- Valid JSON: double-quoted strings, no trailing commas, no comments.
- `byte_offset` and `length` are always `null`. Declared positions go in
  `declared_start`/`declared_end` behind `position_declared: true`.
- `position_declared`/`declared_start`/`declared_end` appear ONLY on flat-file
  findings.
- Line numbers are 1-indexed and file-relative.
- If the chunk holds no layout, emit `fields: []` and set `qualified_name` to the
  best identifier you can read or `"UNKNOWN"`.

## Anti-patterns — DO NOT DO

- Do NOT put a value in `byte_offset` or `length` — declared positions live in
  `declared_start`/`declared_end`.
- Do NOT set `declared_start`/`declared_end` without `position_declared: true`.
- Do NOT emit declared positions for an embedded copybook (the calculator
  computes those).
- Do NOT emit byte positions for a delimited/CSV layout (it has none).
- Do NOT invent relationships.
- Do NOT include credentials in any string — elide per `redact.md`.
- Do NOT add keys outside the schema (`additionalProperties: false`).

## Worked example (this output passes `validate_finding.py`)

Input chunk (lines 1–6 of `layouts/customer.layout`, a positional doc):

```
Field        Start  End   Len  Type
CUST_ID          1    7      7  NUM
CUST_NAME        8   37     30  CHAR
BALANCE         38   46      9  NUM
```

Emit:

```json
{
  "schema_version": "1.0.0",
  "extractor_id": "structure-recovery",
  "extractor_version": "1.0.0",
  "file_path": "layouts/customer.layout",
  "file_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "chunk_id": 1,
  "start_line": 1,
  "end_line": 6,
  "object_kind": "flatfile_layout",
  "qualified_name": "customer.layout",
  "fields": [
    {"name": "CUST_ID", "ordinal": 0, "byte_offset": null, "length": null, "level": null, "pic_clause": null, "usage": null, "declared_type": "NUM", "normalized_type": "integer", "nullable": null, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": null, "is_filler": null, "sign_separate": null, "synchronized": null, "position_declared": true, "declared_start": 1, "declared_end": 7, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "unknown"},
    {"name": "CUST_NAME", "ordinal": 1, "byte_offset": null, "length": null, "level": null, "pic_clause": null, "usage": null, "declared_type": "CHAR", "normalized_type": "string", "nullable": null, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": null, "is_filler": null, "sign_separate": null, "synchronized": null, "position_declared": true, "declared_start": 8, "declared_end": 37, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "unknown"},
    {"name": "BALANCE", "ordinal": 2, "byte_offset": null, "length": null, "level": null, "pic_clause": null, "usage": null, "declared_type": "NUM", "normalized_type": "integer", "nullable": null, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": null, "is_filler": null, "sign_separate": null, "synchronized": null, "position_declared": true, "declared_start": 38, "declared_end": 46, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "unknown"}
  ],
  "relationships": [],
  "gaps": [],
  "confidence": "grounded",
  "evidence": {"file_path": "layouts/customer.layout", "line": 1}
}
```

(Note: positions are in `declared_start`/`declared_end` with
`position_declared: true`; `byte_offset`/`length` stay `null`. Accumulate
cross-checks these declared positions against the computed sequence and gaps on
mismatch.)

## You will now receive the chunk content. Emit one valid JSON object conforming to `structure-finding.v1` (object_kind = flatfile_layout).
