# Addendum: DataStage DSX symbol vocabulary + link/stage semantics

Read this alongside `analyze-symbols.md` when `format == dsx`. Vocabulary grounded
in `datastage-developer`.

DSX files are an XML/text export of DataStage jobs. The skill parses the XML with
`defusedxml` (XXE HARD-RULE) before you see it; you analyse the resulting structure.

## `kind` closed set (DSX)
`job`, `stage`, `link`, `column`, `parameter`, `container`, `routine`, `sequence`.

- `job` — a parallel or server job (`DSJOB` / job record). Top-level container.
- `stage` — a stage in a job (Transformer / Join / Lookup / Aggregator / Sort /
  Funnel / Merge / connector). Carry the stage type in `attributes.stage_type`.
- `link` — a link between two stages (Input / Output / Reference / Reject). This is
  the data-flow edge carrier.
- `column` — a column on a link or table definition.
- `parameter` — a job parameter (`#PARAM#`). References to `#PARAM#` are dynamic.
- `container` — a shared/local container.
- `routine` — a parallel/server routine or BuildOp.
- `sequence` — a job-sequence activity (controls job-to-job flow).

## Scoped names
- Job: `<job-name>`.
- Stage: `<job-name>/<stage-name>`.
- Link: `<job-name>/<stage-from>-><stage-to>` (or the link's own name if present).
- Column: `<job-name>/<stage-or-link>/<column-name>`.
- Parameter: `<job-name>/param/<param-name>`.
- Container: `container/<container-name>`.
- Routine: `routine/<routine-name>`.
- Sequence activity: `<sequence-name>/act/<activity-name>`.

## Relationships
- A `link` from stage A to stage B → `calls` from `<job>/A` to `<job>/B` (data flow;
  the navigator renders the stage DAG). Grounded when both stage endpoints are named
  in the export.
- A connector/source stage reading a table/file → `reads`; a target stage writing →
  `writes`.
- A sequence activity that runs job X → `schedules` from the sequence to job X.
- A job `contains` its stages/links/parameters.
- Runtime Column Propagation (RCP) enabled on a stage means the column set is not
  statically knowable → emit a `dsx_rcp` gap and mark any RCP-derived column edges
  `speculative`.
- A `#PARAM#` used as a table/file name → the resolved target is **speculative**
  (parameter interpolation); emit the edge with a reference to the parameter and a
  gap if the value is not a default in the export.

## Credential caution
Connector stages embed connection strings / passwords (often as `#PARAM#` or inline).
Follow `redact-secrets.md` — never emit the credential value in `evidence_snippet`.
