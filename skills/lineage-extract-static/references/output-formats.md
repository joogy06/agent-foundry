# Output Formats — OL JSON + CSV + HTML + Mermaid

Reference for the output contract of `lineage-extract-static analyze`. Every run produces files under `/tmp/lineage-extract-static-<session>/` (or `--output-dir <path>`).

## File layout

```
/tmp/lineage-extract-static-<session>/
├── openlineage.ndjson          ← canonical stream (one JobEvent or DatasetEvent per line)
├── openlineage.json            ← derived {"events": [...]} bundle
├── lineage_edges.csv           ← single denormalized CSV (default)
├── datasets.csv                ← OL-relational opt-in (--output-format=ol-relational)
├── jobs.csv                    ← OL-relational opt-in
├── edges.csv                   ← OL-relational opt-in
├── runs.csv                    ← OL-relational opt-in (ONLY when --with-static-run)
├── manifest.json               ← per-run metadata (validated against lineage-manifest.v1)
├── errors.jsonl                ← per-file extraction failures
├── views.json                  ← L1/L2 render payload (project_views.py; default on)
├── report.md                   ← Mermaid summary (air-gap L1 fallback)
└── report.html                 ← single self-contained 3-tab (L1/L2/L3-hidden) switcher
```

> Scheduler × language × engine coverage (deterministic vs LLM) is documented in
> `mainframe-lineage-parsers/references/coverage-matrix.md`.

## `openlineage.ndjson` — canonical OL stream

One event per line. JobEvent + DatasetEvent only by default. RunEvent added when `--with-static-run`.

Determinism: sort key is `(eventType, dataset.namespace + dataset.name | job.namespace + job.name)`. Two runs with same inputs produce byte-identical ndjson.

Validation: every event validated against `schemas/openlineage-2.0.2-vendored.json` BEFORE write. Failure = abort run (HARD-RULE 1 fail-closed).

### `sourceCodeLocation.contentSha256` JOB facet

Each JobEvent carries a `sourceCodeLocation` JOB facet when a source-file hash is
available:

```json
"sourceCodeLocation": {
  "_producer": "urn:lineage:static-scan",
  "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/SourceCodeLocationJobFacet.json",
  "type": "file",
  "path": "etl/load.py",
  "contentSha256": "<sha256 of the RAW on-disk source file bytes>"
}
```

`contentSha256` is the streaming whole-file sha256 of the source file's raw bytes
— **NO** encoding normalization, **NO** symbol/copybook expansion, **NO** chunk
scoping. This definition is IDENTICAL to the `mainframe-lineage-parsers` engine's
`sourceCodeLocation.contentSha256`, so the two streams join on the same key (the
deferred-to-v1.1 L3 functional view's lineage-JOB ↔ legacy-code-intel-artifact
join). The OL core pin stays at 2.0.2 — the facet is additive and self-describing.

### `schema` DATASET facet (SchemaDatasetFacet, 2026-07-01 uplift)

Each DatasetEvent carries a `schema` facet when the project-aggregate rollup has
a `dataset_schemas` entry for that `(namespace, name)` — i.e. when the dataset's
columns are NAMED IN SOURCE (dbt `schema.yml`, SQL DDL column lists, CSV header
rows, COBOL copybook fields, staged-model SELECT column lists):

```json
"schema": {
  "_producer": "urn:lineage:static-scan",
  "_schemaURL": "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json",
  "fields": [
    {"name": "id", "type": "bigint"},
    {"name": "email"}
  ]
}
```

Confidence rule: only columns actually named in source are emitted — speculative
columns are OMITTED, not banded; `type` appears only when the source states it
(never guessed). Attachment is fail-open (`attach_schema_facet_fail_closed`): a
facet the vendored OL schema rejects is dropped and the DatasetEvent is emitted
facet-less, with the reason surfaced in the merge summary's `schema_facet_gaps`.
Downstream, the DLP OpenLineage importer materializes these fields as
`type='column'` child elements (`facets.schema.fields[].name` is the contract it
parses). The OL core pin stays at 2.0.2 — the facet is additive.

## `views.json` — L1/L2 render payload (`project_views.py`)

A DETERMINISTIC, stdlib, NO-LLM post-pass over `openlineage.ndjson` +
`lineage_edges.csv`. Rebuilds the typed bipartite graph, reattaches per-edge
confidence/evidence from the CSV (the OL events drop it), and emits two views:

- **L1 — file interaction, JOB-RETAINED.** `kind=file` datasets, job node kept
  (dataset → job → dataset). NO job collapse; NEVER a fabricated file→file edge.
- **L2 — table/data + column.** `kind ∈ {table,topic,queue}`, job nodes kept.
  `columnLineage` (facet 1-2-0) nested under the parent table edge; tolerant of an
  absent facet (table-level L2 still works).

Shape:

```json
{
  "schema_version": "1.0.0",
  "producer": "lineage-extract-static/project_views",
  "views": ["l1", "l2"],
  "view_meta": { "l1": {...}, "l2": {...}, "l3": {"hidden": true} },
  "graph_views": { "l1": {"nodes": [...], "edges": [...]}, "l2": {...} },
  "cytoscape": { "l1": [<elements>], "l2": [<elements>] }
}
```

Atomic write + `sort_keys` + `SOURCE_DATE_EPOCH` ⇒ byte-identical re-runs. Each
view edge keys back to OL/CSV `(confidence, evidence_file, evidence_line)`; L2
column edges carry `output_field` / `input_namespace` / `input_name` /
`input_field` / `transformations`.

## `openlineage.json` — derived bundle

```json
{"events": [<event1>, <event2>, ...]}
```

Same events, single JSON document. Sorted; indented with 2 spaces. UTF-8. Trailing newline.

## `lineage_edges.csv` — single denormalized CSV (default)

```csv
src_dataset_namespace,src_dataset_name,src_kind,target_job_namespace,target_job_name,target_job_kind,edge_kind,confidence,evidence_file,evidence_line,extractor_id
file://repo,data/users.csv,file,repo://my-pipeline,etl/load_users.py:main,script,reads_from,grounded,etl/load_users.py,12,lineage-extract-static
postgres://dwh:5432/analytics,public.users,table,repo://my-pipeline,etl/load_users.py:main,script,writes_to,grounded,etl/load_users.py,20,lineage-extract-static
```

Sort key: `(target_job_namespace, target_job_name, edge_kind, src_dataset_name)`.

RFC 4180 quoting via `csv.QUOTE_MINIMAL`. Paths/names with commas correctly quoted.

## OL-relational CSV split (`--output-format=ol-relational`)

Four CSV files joined by `(namespace, name)`. Useful for downstream catalogs that want normalized tables.

### `datasets.csv`

```csv
namespace,name,kind
file://repo,data/users.csv,file
postgres://dwh:5432/analytics,public.users,table
```

### `jobs.csv`

```csv
namespace,name,kind
repo://my-pipeline,etl/load_users.py:main,script
```

### `edges.csv`

```csv
src_namespace,src_name,target_namespace,target_name,edge_kind,confidence,evidence_file,evidence_line
file://repo,data/users.csv,repo://my-pipeline,etl/load_users.py:main,reads_from,grounded,etl/load_users.py,12
postgres://dwh:5432/analytics,public.users,repo://my-pipeline,etl/load_users.py:main,writes_to,grounded,etl/load_users.py,20
```

### `runs.csv` (only when `--with-static-run`)

```csv
run_id,producer
902099a3-09be-5fca-8926-b86347a4f978,urn:lineage:static-scan
```

## `manifest.json` — per-run metadata

Validated against `schemas/lineage-manifest.v1.json`. Required fields:

```json
{
  "schema_version": "1.0.0",
  "run_id": "lineage-1716422400-12345678",
  "started_at": "2026-05-14T19:00:00Z",
  "completed_at": "2026-05-14T19:04:48Z",
  "project_root": "/home/user/my-pipeline",
  "workspace_tree_hash": "abc123...",
  "files_scanned": 1234,
  "files_skipped": [{"path": "vendor/lib.min.js", "reason": "binary"}],
  "total_chunks": 5678,
  "total_edges_emitted": 91011,
  "by_confidence": {"grounded": 4567, "inferred": 2345, "speculative": 1234},
  "duration_seconds": 287.4,
  "llm_token_cost_estimate_usd": 1.23,
  "extractor_id": "lineage-extract-static",
  "extractor_version": "1.0.0",
  "prompt_template_hash": "abc123...",
  "model_id": "claude-opus-4-7",
  "openlineage_spec_version": "2.0.2",
  "redaction_count": 3,
  "cache_hit_rate": 0.95,
  "errors": [{"file": "etl/legacy.py", "stage": "chunk", "message": "permission_denied"}],
  "exit_status": "SUCCESS"
}
```

## `errors.jsonl` — per-file failures

One JSON object per line. Same shape as `manifest.errors[]` but with full per-file context.

```json
{"file": "etl/legacy.py", "stage": "chunk", "message": "decode_error: invalid UTF-8 at byte 1024", "traceback": "..."}
{"file": "data/binary.dat", "stage": "chunk", "message": "skipped: binary_file"}
```

Non-fatal: errors here do NOT abort the run; they're surfaced for debugging.

## `report.md` — Mermaid summary

GitHub-renderable. Sections:

1. **Summary table** — counts.
2. **`flowchart LR`** — top-level job/dataset graph capped at 50 nodes. Over-cap emits top-20-by-degree + `<!-- truncated: see report.html -->` comment.
3. **`sankey-beta`** — read/write volumes (only when `OutputStatisticsFacet` row counts available; not in static v1 — section skipped).
4. **Top-20 datasets by edge count** — markdown table.
5. **Top-20 jobs by dataset count** — markdown table.
6. **Downloads section** — relative links to all output files.

Drill-ins via native `<details>` for the next 50 overflow before hard-stop at 100 nodes (over-cap rendered in `report.html` only).

Mermaid node-id encoding: `_safe_node_id()` strips non-alphanumeric chars; long ids get a short hash suffix for stability.

## `report.html` — single 3-tab Cytoscape switcher + tables

Self-contained, single HTML file. ONE Cytoscape instance. Sections:

1. **Header** — project, scan time, run id, extractor versions. `data-scan-id` attribute for determinism diff.
2. **Summary tiles** — datasets / jobs / edges / chunked-files counts + confidence histogram.
3. **3-tab view switcher** (when `views.json` is present, i.e. `--views` non-empty):
   - **L1 — file interaction (job-retained)** (default tab).
   - **L2 — table/data** with a column-lineage expand-on-click `<details>` table.
   - **L3 — functional** — tab slot RESERVED but HIDDEN in v1 (deferred to v1.1).
   - The tab handler swaps `cy.json({elements})` between the pre-built L1/L2
     element sets from `views.json` — ONE Cytoscape instance, no per-tab reload.
   - When `views.json` is absent the report falls back to the single bundle DAG.
4. **Interactive DAG** — Cytoscape (`zoom/pan/click-to-focus`).
   - Node shapes: dataset=rectangle, job=round-rectangle.
   - Edge styles: read=solid, write=dotted, schedules=dashed.
   - Confidence colors: grounded=blue, inferred=amber, speculative=red.
   - Layouts: `cose-bilkent` default + `dagre` toggle.
5. **Sortable tables** — datasets, jobs, edges. Pure-JS sort-on-header-click, no DataTables.js.
6. **Download links** — relative URLs to all sibling files.
7. **Per-file gap collapsibles** — native `<details>` per chunked file.

### Air-gap posture

- Default: looks for `~/.claude/skills/visual-companion/templates/vendor/cytoscape.min.js`.
  - **Vendor present**: inline-loads it via relative `<script src="...">`.
  - **Vendor missing AND CDN reachable**: falls back to unpkg CDN with banner.
  - **Vendor missing AND CDN unreachable**: `report.html` NOT produced; `report.md` carries the L1 Mermaid air-gap fallback (L2 column detail is HTML-only).
- `--no-vendor` flag forces the third behavior (Mermaid-only) regardless of network reachability.

### XSS safety (HARD-RULE 7)

Every user-controlled string interpolated via Jinja2 `|e` filter (which calls `html.escape`). EACH view's Cytoscape elements JSON (L1 and L2) is embedded through the SAME escape chain — `<` → `<`, `>` → `>`, `&` → `&`, plus U+2028/U+2029 — so user content cannot break out of the `<script>` tag context on any tab. The browser consumes the element sets ONLY via `cy.json({elements})` and builds the L2 column `<details>` table via `textContent` / `createTextNode`. The template assigns NO HTML-string sink (`innerHTML` / `outerHTML` / `insertAdjacentHTML` / `document.write`) anywhere — including the air-gap fallback notice, which is built with DOM APIs.

Required test: `tests/test_views_render_sha.py::test_html_escape_hostile_filenames_inert_across_tabs` verifies that a hostile dataset name (`</script><img src=x onerror=alert(1)>"&<>`) is rendered inert across BOTH the L1 and L2 embedded element sets (no literal `<`/`>` in the embedded JSON, no `</script>` breakout, no JS execution on page load).

## Determinism guarantee

When `SOURCE_DATE_EPOCH` env var is set to a Unix timestamp, all timestamps in the rendered output use that value instead of wall-clock time. Output is byte-identical across re-runs with same input + same `SOURCE_DATE_EPOCH`. Mirrors the Reproducible Builds convention.

Without `SOURCE_DATE_EPOCH`, the `scan_started_at` timestamp captures wall-clock time at run-start. Two back-to-back runs differ only in this timestamp.

## Cross-version compatibility note

The OL spec version is pinned to 2.0.2. Older OL consumers (≤ 0.30.x) may need `--with-static-run` to ingest the output (their pipelines reject JobEvent-only streams). Newer consumers (Marquez 0.46+, OpenMetadata 1.4+, DataHub 0.13+) accept the canonical format directly.
