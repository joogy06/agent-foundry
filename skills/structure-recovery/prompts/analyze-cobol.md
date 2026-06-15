# Per-Chunk COBOL Structure Analysis Prompt

You are analysing ONE chunk of ONE COBOL source file (or copybook) as part of a
table/record **structure** recovery. Your job is to read the chunk and emit the
**DECLARED record/field tree** as exactly one structured JSON object conforming
to `structure-finding.v1`. No prose before or after the JSON.

This prompt is model-neutral: it is run by whichever in-session AI CLI is active
(Claude Code, Codex CLI, GitHub Copilot CLI, or the Antigravity CLI `agy`). Do
not rely on any single model's behaviour — apply the rules below literally.

## CRITICAL SAFETY INVARIANT — read this first

> **You emit DECLARED facts only. You NEVER compute, declare, or guess a byte
> offset or a byte length.**
>
> Every field you emit MUST carry `"byte_offset": null` and `"length": null`.
> Byte offsets and lengths are computed DETERMINISTICALLY downstream by
> `scripts/cobol_offset_calc.py`, which walks the level-tree and the verbatim
> `pic_clause` / `usage` you provide. The validator
> (`scripts/validate_finding.py`) **REJECTS** any field whose `byte_offset` or
> `length` is non-null. A rejected finding is dropped — so a non-null offset
> here means your work is discarded.

Your contribution is the *declared structure*: names, levels, ordinals, the
verbatim PICTURE clause, USAGE, OCCURS/REDEFINES/RENAMES, and honest gaps. The
calculator does the arithmetic.

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
  "object_kind": "cobol_record",
  "qualified_name": "<the 01-level record name, e.g. CUSTOMER-RECORD>",
  "fields": [
    {
      "name": "<declared field name verbatim, or FILLER>",
      "ordinal": <0-indexed declaration order within the parent group>,
      "byte_offset": null,
      "length": null,
      "level": <COBOL level number: 1, 5, 10, 49, 66, 77, 88, ...>,
      "pic_clause": "<PICTURE clause VERBATIM, e.g. S9(7)V99, X(30), or null for group items>",
      "usage": "<DISPLAY | COMP-3 | COMP | COMP-1 | COMP-2 | BINARY | INDEX | NATIONAL | POINTER>",
      "declared_type": null,
      "normalized_type": "<string | integer | decimal | date | datetime | boolean | binary | null>",
      "nullable": null,
      "occurs": <fixed OCCURS count, or the maximum for OCCURS DEPENDING ON, else null>,
      "occurs_max": <upper bound of an OCCURS ... TO ... DEPENDING ON range, else null>,
      "occurs_depending_on": "<controlling field name for ODO, else null>",
      "redefines": "<name of the field this REDEFINES, else null>",
      "renames": "<THRU range or single field for a level-66 RENAMES, else null>",
      "is_group": <true for group items (children, no PIC), else false/null>,
      "is_filler": <true for FILLER items, else false/null>,
      "sign_separate": <true when the PIC carries SIGN ... SEPARATE, else false/null>,
      "synchronized": <true when the field is SYNCHRONIZED/SYNC, else false/null>,
      "confidence": "grounded | inferred | speculative",
      "evidence_kind": "declared_column",
      "enforcement": "unknown"
    }
  ],
  "relationships": [],
  "gaps": [
    {
      "kind": "unresolved_copybook | odo_variable_length | sync_alignment",
      "line": <1-indexed file-relative line of the gap site>,
      "description": "<one-line explanation, <= 512 chars>"
    }
  ],
  "confidence": "grounded | inferred | speculative",
  "evidence": { "file_path": "<from input>", "line": <1-indexed line of the 01-level declaration> }
}
```

`fields`, `relationships`, and `gaps` are all required arrays (use `[]` when
empty). Emit **no keys other than those shown** — the schema is
`additionalProperties: false`, so an unknown key is rejected.

## Rules for the COBOL data tree

### Levels and zero-byte items
- Preserve the declared `level` number on every field (01, 05, 10, 49, 66, 77, 88).
- **Level-88 condition-names and level-66 RENAMES occupy ZERO bytes.** Emit them
  as fields (they are part of the declared structure) — the calculator treats
  them as zero-storage. A level-66 carries `renames` (its THRU range); level-88
  carries the condition-name and `pic_clause: null`.
- A **group item** (has children, no PIC) gets `is_group: true`,
  `pic_clause: null`, `usage: null` (unless the group declares a USAGE — see
  inheritance). Group length is `Σ children`, computed downstream.

### PICTURE and USAGE — emit VERBATIM, never summarise
- Copy the `pic_clause` exactly as written: `S9(7)V99`, `X(30)`, `9(4) COMP`,
  `PIC 9(5)V9(2)`. Do NOT normalise `9(7)` to `9999999` and do NOT compute its
  width — the calculator parses the verbatim clause.
- `usage`: if a USAGE is declared on the field, emit it verbatim. If a field has
  a PIC but **no** explicit USAGE, emit the **explicit default** `"DISPLAY"`.
- **USAGE group inheritance:** when a group item declares a USAGE (e.g.
  `05 PACKED-GRP USAGE COMP-3.`), propagate that USAGE down to each child that
  does not override it. A child whose USAGE was inherited (not declared on the
  child itself) is `confidence: "inferred"` (group-propagated USAGE), not
  `grounded`.

### OCCURS
- Fixed `OCCURS n TIMES` → `occurs: n`, `occurs_max: null`,
  `occurs_depending_on: null`.
- `OCCURS m TO n TIMES DEPENDING ON CTRL-FIELD` → `occurs: m` (the minimum),
  `occurs_max: n` (the maximum/TO value), `occurs_depending_on: "CTRL-FIELD"`,
  AND emit a `gap` of kind `odo_variable_length`. The presence of
  `occurs_depending_on` tells the calculator to emit `byte_offset_min` /
  `byte_offset_max` / `variable_length: true` and to **refuse a single
  authoritative post-ODO offset** downstream — you do not compute any of that.

### REDEFINES / RENAMES
- `05 B REDEFINES A PIC ...` → `redefines: "A"`. (Downstream: shares A's offset,
  does not advance the cursor; a larger redefines extends the group. You only
  record the `redefines` name.)
- `66 FULL-NAME RENAMES FIRST THRU LAST.` → `renames: "FIRST THRU LAST"`,
  `level: 66`, zero bytes.

### SIGN and SYNCHRONIZED
- A PIC with `SIGN ... SEPARATE` (e.g. `S9(5) SIGN LEADING SEPARATE`) →
  `sign_separate: true` (downstream adds +1 byte for the sign).
- A field declared `SYNCHRONIZED` / `SYNC` → `synchronized: true` AND emit a
  `gap` of kind `sync_alignment`. Downstream the calculator emits
  RANGED/UNKNOWN offsets for SYNC fields and **never** a confident
  "without-slack" value — you simply flag it.

### COPY (cross-file — not resolved here)
- `COPY SOME-MEMBER.` → you cannot see the member's content in this chunk. Emit a
  `gap` of kind `unresolved_copybook` (e.g. `description: "COPY CUSTOMER-CPY —
  member not in chunk"`). Do NOT invent the copied fields. The cross-file pass
  resolves the member and splices it before offsets are computed.
- `COPY MEMBER REPLACING ==X== BY ==Y==.` → still `unresolved_copybook` here;
  any spliced fields the cross-file pass produces from a `COPY REPLACING` are
  marked `speculative` downstream (the post-replace names are not statically
  knowable from the COPY site alone).

## Confidence (per field and object-level)

Apply `confidence` to each field and roll the object-level `confidence` up to the
most conservative tier present:

| Tier | When |
|---|---|
| `grounded` | A cleanly declared elementary item with a verbatim PIC and an explicit-or-defaulted DISPLAY/COMP/COMP-3 USAGE. |
| `inferred` | USAGE was inherited from a parent group rather than declared on the field; or a name-resolution heuristic was needed. |
| `speculative` | Fields arising from a `COPY REPLACING` (downstream), or any item you can only partially read because the chunk is cut mid-record. |

`evidence_kind` for COBOL declared fields is `declared_column`; `enforcement` is
`unknown` (COBOL copybooks declare layout, not enforcement).

## Relationships

**Do NOT emit COBOL cross-record foreign keys at chunk level.** They are a
speculative, opt-in (`--infer-relationships`) cross-file concern handled later
(design §6 / K2). Emit `relationships: []` for COBOL chunks.

## Gap reporting (honest disclosure)

Gaps are NOT errors — they say "I saw something but cannot extract a confident
structural fact." Closed enum for `gap.kind` relevant to COBOL:

- `unresolved_copybook` — a `COPY` member is not resolvable in this chunk.
- `odo_variable_length` — `OCCURS DEPENDING ON` (variable record length).
- `sync_alignment` — a `SYNCHRONIZED` field whose alignment slack is unknown.
- `record_exceeds_chunk` — the chunker flagged that a single record is larger
  than the chunk cap (only emit if your input tells you so).
- `redaction_applied` — content was redacted (see `redact.md`).

`line` is 1-indexed and **file-relative** (not chunk-relative).

## Format requirements

- Emit ONE JSON object only. No prose, no markdown fences, no comments.
- Valid JSON: double-quoted strings, no trailing commas, no comments.
- Every field carries `"byte_offset": null` and `"length": null` — no exceptions.
- Line numbers are 1-indexed and file-relative.
- If the chunk holds no COBOL record declaration at all (e.g. it is procedure
  division code), emit `fields: []`, `relationships: []`, and a brief object with
  `qualified_name` set to the best record context you can see, or `"UNKNOWN"`.

## Anti-patterns — DO NOT DO

- Do NOT put a number in `byte_offset` or `length`. Ever. Both are `null`.
- Do NOT expand `9(7)` / `X(30)` into repeated characters or into a width — emit
  the PIC verbatim.
- Do NOT invent fields for an unresolved `COPY` — emit a gap instead.
- Do NOT emit a single post-ODO offset or "estimate" a variable record length.
- Do NOT emit cross-record FK relationships from a copybook.
- Do NOT include credentials in any string (a copybook rarely has them, but if a
  comment carries one, elide it per `redact.md`).
- Do NOT add keys outside the schema (`additionalProperties: false`).

## Worked example (this output passes `validate_finding.py`)

Input chunk (lines 10–16 of `copybooks/CUSTOMER.cpy`):

```
       01  CUSTOMER-RECORD.
           05  CUST-ID            PIC 9(7).
           05  CUST-BALANCE       PIC S9(7)V99 COMP-3.
           05  CUST-NAME          PIC X(30).
           05  CUST-FLAGS.
               10  ACTIVE-FLAG    PIC X.
```

Emit:

```json
{
  "schema_version": "1.0.0",
  "extractor_id": "structure-recovery",
  "extractor_version": "1.0.0",
  "file_path": "copybooks/CUSTOMER.cpy",
  "file_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "chunk_id": 1,
  "start_line": 10,
  "end_line": 16,
  "object_kind": "cobol_record",
  "qualified_name": "CUSTOMER-RECORD",
  "fields": [
    {"name": "CUST-ID", "ordinal": 0, "byte_offset": null, "length": null, "level": 5, "pic_clause": "9(7)", "usage": "DISPLAY", "declared_type": null, "normalized_type": "integer", "nullable": null, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": false, "is_filler": false, "sign_separate": false, "synchronized": false, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "unknown"},
    {"name": "CUST-BALANCE", "ordinal": 1, "byte_offset": null, "length": null, "level": 5, "pic_clause": "S9(7)V99", "usage": "COMP-3", "declared_type": null, "normalized_type": "decimal", "nullable": null, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": false, "is_filler": false, "sign_separate": false, "synchronized": false, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "unknown"},
    {"name": "CUST-NAME", "ordinal": 2, "byte_offset": null, "length": null, "level": 5, "pic_clause": "X(30)", "usage": "DISPLAY", "declared_type": null, "normalized_type": "string", "nullable": null, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": false, "is_filler": false, "sign_separate": false, "synchronized": false, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "unknown"},
    {"name": "CUST-FLAGS", "ordinal": 3, "byte_offset": null, "length": null, "level": 5, "pic_clause": null, "usage": null, "declared_type": null, "normalized_type": null, "nullable": null, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": true, "is_filler": false, "sign_separate": false, "synchronized": false, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "unknown"},
    {"name": "ACTIVE-FLAG", "ordinal": 0, "byte_offset": null, "length": null, "level": 10, "pic_clause": "X", "usage": "DISPLAY", "declared_type": null, "normalized_type": "string", "nullable": null, "occurs": null, "occurs_max": null, "occurs_depending_on": null, "redefines": null, "renames": null, "is_group": false, "is_filler": false, "sign_separate": false, "synchronized": false, "confidence": "grounded", "evidence_kind": "declared_column", "enforcement": "unknown"}
  ],
  "relationships": [],
  "gaps": [],
  "confidence": "grounded",
  "evidence": {"file_path": "copybooks/CUSTOMER.cpy", "line": 10}
}
```

(Note: `ACTIVE-FLAG` is `ordinal: 0` because ordinal is **per parent group** —
it is the first child of `CUST-FLAGS`. `byte_offset`/`length` are null on every
field; `cobol_offset_calc.py` computes CUST-BALANCE's packed length as
`floor(7/2)+1 = 4` bytes downstream.)

## You will now receive the chunk content. Emit one valid JSON object conforming to `structure-finding.v1` (object_kind = cobol_record).
