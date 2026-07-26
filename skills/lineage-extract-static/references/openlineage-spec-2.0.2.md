# OpenLineage Spec 2.0.2 — What to Emit

Reference doc for the `lineage-extract-static` skill. Pinned to OpenLineage 2.0.2 (vendored at `schemas/openlineage-2.0.2-vendored.json`). Bumping the pin requires a deliberate constants change in `scripts/validate_ol.py` + re-test + history.md entry.

## Spec docs

- Base spec: <https://openlineage.io/spec/2-0-2/OpenLineage.json>
- Naming conventions: <https://github.com/OpenLineage/OpenLineage/blob/main/spec/Naming.md>
- Marquez (reference OL backend): <https://github.com/MarquezProject/marquez>

## Three event types we emit

### `DatasetEvent` — canonical for static lineage

```json
{
  "$schema": "https://openlineage.io/spec/2-0-2/OpenLineage.json",
  "eventType": "DATASET_EVENT",
  "eventTime": "2026-05-14T19:30:00Z",
  "producer": "urn:lineage:static-scan",
  "schemaURL": "https://openlineage.io/spec/2-0-2/OpenLineage.json",
  "dataset": {
    "namespace": "postgres://dwh:5432/analytics",
    "name": "public.users",
    "facets": {
      "datasetKind": {
        "_producer": "urn:lineage:static-scan",
        "_schemaURL": "https://foundry-lab.local/openlineage/facets/DatasetKindFacet/1-0-0.json",
        "kind": "table"
      }
    }
  }
}
```

**Required fields**: `eventType`, `eventTime`, `producer`, `schemaURL`, `dataset.namespace`, `dataset.name`.

### `JobEvent` — canonical for static lineage

```json
{
  "$schema": "https://openlineage.io/spec/2-0-2/OpenLineage.json",
  "eventType": "JOB_EVENT",
  "eventTime": "2026-05-14T19:30:00Z",
  "producer": "urn:lineage:static-scan",
  "schemaURL": "https://openlineage.io/spec/2-0-2/OpenLineage.json",
  "job": {
    "namespace": "repo://my-pipeline",
    "name": "etl/load_users.py:main",
    "facets": {
      "jobKind": {
        "_producer": "urn:lineage:static-scan",
        "_schemaURL": "https://foundry-lab.local/openlineage/facets/JobKindFacet/1-0-0.json",
        "kind": "script"
      },
      "staticAnalysis": {
        "_producer": "urn:lineage:static-scan",
        "_schemaURL": "https://foundry-lab.local/openlineage/facets/StaticAnalysisFacet/1-0-0.json",
        "extractor_id": "lineage-extract-static",
        "extractor_version": "1.0.0",
        "workspace_tree_hash": "abc123...",
        "mode": "static-extract",
        "runtime_observed": false
      }
    }
  },
  "inputs": [
    {"namespace": "file://repo", "name": "data/users.csv"}
  ],
  "outputs": [
    {"namespace": "postgres://dwh:5432/analytics", "name": "public.users"}
  ]
}
```

**Required fields**: `eventType`, `eventTime`, `producer`, `schemaURL`, `job.namespace`, `job.name`.

**Custom `staticAnalysis` facet** — attached to every JobEvent we emit. Signals to consumers (Marquez, Atlan, DataHub) that this event came from static-extract scanning, not runtime observation.

### `RunEvent` — opt-in compatibility export only (`--with-static-run`)

Per HARD-RULE 1, we do NOT emit `RunEvent` by default. The OL spec v1.0+ supports static lineage as `JobEvent` + `DatasetEvent` with NO Run wrapper. Phantom runs pollute downstream catalogs.

When `--with-static-run` is set, we wrap each JobEvent in a `RunEvent`:

```json
{
  "$schema": "https://openlineage.io/spec/2-0-2/OpenLineage.json",
  "eventType": "COMPLETE",
  "eventTime": "2026-05-14T19:30:00Z",
  "producer": "urn:lineage:static-scan",
  "schemaURL": "https://openlineage.io/spec/2-0-2/OpenLineage.json",
  "run": {
    "runId": "902099a3-09be-5fca-8926-b86347a4f978",
    "facets": {
      "staticAnalysis": { ... }
    }
  },
  "job": { ... },
  "inputs": [ ... ],
  "outputs": [ ... ]
}
```

The `runId` is **deterministic**: `uuid5(NAMESPACE_OID, workspace_tree_hash + scan_started_at)`. Same workspace + same start time = same runId. Idempotent for downstream catalogs.

## Namespacing convention (per Naming.md)

### Databases

| System | Namespace | Name |
|---|---|---|
| PostgreSQL | `postgres://<host>:<port>/<db>` | `<schema>.<table>` |
| MySQL / MariaDB | `mysql://<host>:<port>/<db>` | `<table>` (no schema) |
| Oracle | `oracle://<host>:<port>/<service>` | `<USER>.<table>` |
| SQL Server | `sqlserver://<host>:<port>/<db>` | `<schema>.<table>` |
| Snowflake | `snowflake://<account>` | `<db>.<schema>.<table>` |
| BigQuery | `bigquery://<project>` | `<dataset>.<table>` |
| DB2 | `db2://<host>:<port>/<db>` | `<schema>.<table>` |
| SQLite | `sqlite:<absolute path>` | `main.<table>` |

### Filesystem datasets

| Pattern | Namespace | Name |
|---|---|---|
| In-repo (resolved) | `file://<repo-root-anchor>` | `<repo-relative-path>` |
| Outside repo | `file://` | `<absolute-path>` |
| S3 | `s3://<bucket>` | `<key>` |
| GCS | `gs://<bucket>` | `<object>` |
| Azure Blob | `abfss://<container>@<account>.dfs.core.windows.net` | `<path>` |
| HDFS | `hdfs://<host>:<port>` | `<path>` |
| NFS mount mirror | (alias map only) | (alias map only) |

### Streaming / pub-sub

| System | Namespace | Name |
|---|---|---|
| Kafka | `kafka://<bootstrap-host>:<port>` | `<topic>` |
| GCP Pub/Sub | `pubsub://<project>` | `<topic>` |
| RabbitMQ | `amqp://<host>:<port>/<vhost>` | `<exchange>.<routing_key>` |
| Kinesis | `kinesis://<stream-arn>` | `<stream-name>` |

### Jobs

| Pattern | Namespace | Name |
|---|---|---|
| Script in repo | `repo://<repo-anchor>` | `<rel-path>:<symbol>` (e.g. `etl/load.py:main`) |
| Airflow DAG | `airflow://<airflow-id>` | `<dag_id>.<task_id>` |
| dbt model | `dbt://<project>` | `<dataset>.<model>` |
| Spark app | `spark://<deploy-target>` | `<app-name>` |
| DataStage job | `datastage://<project>` | `<job_name>` |
| Control-M job | `controlm://<environment>` | `<job_name>` |

## Facets we emit

### `datasetKind` (custom)

URI: `https://foundry-lab.local/openlineage/facets/DatasetKindFacet/1-0-0.json`

Carries `kind: "table" | "file" | "topic" | "endpoint" | "queue"`. Used by the renderer for node-shape selection.

### `jobKind` (custom)

URI: `https://foundry-lab.local/openlineage/facets/JobKindFacet/1-0-0.json`

Carries `kind: "script" | "dag_task" | "dsx_job" | "spark_app" | "stored_procedure"`.

### `staticAnalysis` (custom — HARD-RULE 1)

URI: `https://foundry-lab.local/openlineage/facets/StaticAnalysisFacet/1-0-0.json`

Attached at JobEvent level. Carries:
- `extractor_id` — always `"lineage-extract-static"`
- `extractor_version` — semver string
- `workspace_tree_hash` — sha256 of the workspace
- `mode` — always `"static-extract"`
- `runtime_observed` — always `false`

Signals to consumers: "This event came from static scanning, not runtime observation. Treat with appropriate skepticism."

### `possible_alias` (custom, only when `--merge-by-basename`)

URI: `https://foundry-lab.local/openlineage/facets/PossibleAliasFacet/1-0-0.json`

Attached when basename-only matching produces a speculative-confidence merge candidate. Lists the candidate canonical datasets that share the basename. NEVER auto-merged.

## What we DO NOT emit

- `ColumnLineageDatasetFacet` — column-level lineage requires schema metadata not available statically. Defer to v1.1.
- `SchemaDatasetFacet` — same reason; would require parsing DDL or sampling actual data.
- `OutputStatisticsFacet` — runtime row counts; not available statically.
- `LifecycleStateChangeDatasetFacet` — runtime DDL events; not available statically.
- `DataQualityMetricsInputDatasetFacet` — runtime quality checks; not applicable.

If a consumer requires any of these, they need a RUNTIME OL producer (openlineage-spark, openlineage-airflow, openlineage-dbt). lineage-extract-static is static-only by design.

## Compatibility note: `RunEvent`-only consumers

Marquez (the reference OL backend) historically required `RunEvent` for everything; modern versions (>= 0.46) accept `JobEvent` + `DatasetEvent` directly. Some commercial consumers (older Atlan, older DataHub) may still want RunEvents — use `--with-static-run` for those.

## Validation

`scripts/validate_ol.py` validates EVERY emitted event against the pinned schema BEFORE writing to `openlineage.ndjson`. Validation failure aborts the run (fail-closed per HARD-RULE 1). Schema `$id` mismatch raises `SchemaPinMismatch` to prevent silent pin drift.
