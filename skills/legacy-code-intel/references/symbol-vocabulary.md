# Reference: per-format symbol vocabulary (COBOL / DSX / ETL)

The ONLY per-format surface in `code-index.v1` is the `symbol.kind` enum. Everything
else (occurrences, relationships, gaps, the store, the query layer) is format-agnostic.
This is the single source of truth for the three closed `kind` sets; `emit_index.py`
enforces them (`KIND_BY_FORMAT`), and the per-format prompt addenda mirror them.

Vocabulary grounded in `cobol-developer`, `ibm-mainframe`, and `datastage-developer`.

## COBOL — `kind` ∈ {program, division, section, paragraph, data_item, copybook, file_descriptor, call_target}

| kind | what it is | scoped-name | primary relationships |
|---|---|---|---|
| `program` | `PROGRAM-ID` | `<PROG>` | `contains` its sections/paragraphs/data |
| `division` | IDENTIFICATION/ENV/DATA/PROCEDURE | `<PROG>/div/<name>` | `contains` |
| `section` | named section | `<PROG>/<section>` | `contains` |
| `paragraph` | PROCEDURE paragraph (call-graph node) | `<PROG>/<para>` | `calls` (PERFORM) |
| `data_item` | 01/05/… level (PIC in signature) | `<PROG>/data/<name>` | — |
| `copybook` | `COPY` member (cross-program stable) | `copybook/<member>` | `copies` |
| `file_descriptor` | `FD` entry | `<PROG>/fd/<name>` | `reads`/`writes` |
| `call_target` | `CALL` operand | `program/<TARGET>` or `<PROG>/dyn/<dn>` | `calls` |

## DSX — `kind` ∈ {job, stage, link, column, parameter, container, routine, sequence}

| kind | what it is | scoped-name | primary relationships |
|---|---|---|---|
| `job` | parallel/server job | `<job>` | `contains` |
| `stage` | Transformer/Join/Lookup/connector/… | `<job>/<stage>` | `calls` (via links), `reads`/`writes` |
| `link` | Input/Output/Reference/Reject | `<job>/<from>-><to>` | (carries the data-flow edge) |
| `column` | column on a link/table def | `<job>/<stage>/<col>` | — |
| `parameter` | `#PARAM#` job parameter | `<job>/param/<name>` | (interpolation → speculative) |
| `container` | shared/local container | `container/<name>` | `contains` |
| `routine` | routine / BuildOp | `routine/<name>` | `calls` |
| `sequence` | sequence activity | `<seq>/act/<name>` | `schedules` |

## ETL — `kind` ∈ {function, variable, sql_cte, table, call_target, shell_task}

| kind | what it is | scoped-name | primary relationships |
|---|---|---|---|
| `function` | shell fn / Python def / SQL block | `<stem>/<fn>` | `calls`, `contains` |
| `variable` | shell/Python var / SQL bind | `<stem>/var/<name>` | — |
| `sql_cte` | `WITH <name> AS (...)` | `<stem>/cte/<name>` | `references` |
| `table` | SQL table/view (cross-script stable) | `table/<name>` | `reads`/`writes` |
| `call_target` | invoked script/fn/program | `call/<target>` or `<stem>/dyn/<expr>` | `calls` |
| `shell_task` | pipeline step | `<stem>/task/<n>` | `schedules`/`calls` |

## Pick / MultiValue — `kind` ∈ {program, subroutine, paragraph, dict_item, file, common_block, label, variable}

| kind | what it is | scoped-name | primary relationships |
|---|---|---|---|
| `program` | cataloged top-level program | `<prog>` | `contains` |
| `subroutine` | external `SUBROUTINE name(args)` | `subroutine/<NAME>` | `calls` (CALL) |
| `paragraph` | PROC / VOC paragraph (stored TCL sentence) | `paragraph/<name>` | `calls` (EXECUTE/PERFORM) |
| `dict_item` | DICT item (D/I/A/S/X/PH) | `dict/<file>/<item>` | `references` (file / Tfile JOIN) |
| `file` | MultiValue file opened via `OPEN..TO` | `file/<name>` | `reads`/`writes` |
| `common_block` | `COMMON [/name/]` shared memory | `<prog>/common/<name>` | `contains` |
| `label` | `GOSUB` target | `<prog>/label/<name>` | `calls` (GOSUB) |
| `variable` | BASIC / `@`-system variable | `<prog>/var/<name>` | — |

Pick notes: `CALL @var` (indirect), interpolated `EXECUTE`/`PERFORM`/`CHAIN`, and
files opened to a computed name are **speculative** (HARD-RULE 2; `emit_index._looks_dynamic`
enforces `CALL @` + interpolated transfer verbs). A `dict_item` with a `Tfile`/`TRANS`
correlative `references` the other file — the MultiValue substitute for a SQL JOIN. The
classic-Pick vs U2 dictionary layout differs; record the observed `dict_type`, do not assume
a fixed attribute layout. See `pick-developer` for the full vocabulary.

## Relationship enum (format-agnostic)
`contains`, `calls`, `reads`, `writes`, `copies`, `references`, `schedules`.

## Extensibility
Adding a format = adding one `kind` set here + in `KIND_BY_FORMAT` + a new prompt
addendum. The schema keeps `kind` as a string so a single `code-index.v1` schema serves
all formats; the closed-set check is enforced in `emit_index.py` per declared format.
Additive only — never remove a kind from a shipped set (it would orphan stored symbols).
