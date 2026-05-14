# Per-Chunk Lineage Analysis Prompt

You are analysing one chunk of one file as part of a data + process lineage extraction. Your task is to identify data-flow edges in the chunk and emit them as one structured JSON object conforming to `lineage-finding.v1`.

## Input you will receive

- `file_path` — repo-relative path of the file.
- `file_sha256` — sha256 of the entire file (NOT this chunk).
- `chunk_id` — 1-indexed chunk number within the file.
- `start_line` / `end_line` — 1-indexed line range (inclusive) this chunk covers within the file.
- `start_byte` / `end_byte` — byte range of the chunk within the file.
- `extractor_version` — the lineage-extract-static skill version.
- `chunk_content` — the verbatim text of the chunk.

## What you emit (one JSON object only)

```json
{
  "schema_version": "1.0.0",
  "extractor_id": "lineage-extract-static",
  "extractor_version": "<from input>",
  "file_path": "<from input>",
  "file_sha256": "<from input>",
  "chunk_id": <from input>,
  "start_line": <from input>,
  "end_line": <from input>,
  "start_byte": <from input>,
  "end_byte": <from input>,
  "boundary_status": "complete | partial_start | partial_end | partial_both",
  "edges": [
    {
      "edge_kind": "reads_from | writes_to | schedules | depends_on",
      "source_dataset": {
        "namespace": "<URI scheme + authority>",
        "name": "<in-namespace identifier>",
        "kind": "table | file | topic | endpoint | queue"
      },
      "target_job": {
        "namespace": "<repo-relative path or DAG id>",
        "name": "<symbol or task id>",
        "kind": "script | dag_task | dsx_job | spark_app | stored_procedure"
      },
      "evidence_line_start": <1-indexed line number, file-relative>,
      "evidence_line_end": <1-indexed line number, file-relative>,
      "evidence_snippet": "<verbatim text showing the lineage statement, <= 1024 chars, NO credentials>",
      "confidence": "grounded | inferred | speculative",
      "confidence_reason": "<one-line explanation>"
    }
  ],
  "gaps": [
    {
      "kind": "dynamic_path | unresolved_symbol | obfuscated | binary_file | language_unsupported",
      "line": <1-indexed line number, file-relative>,
      "description": "<one-line explanation>"
    }
  ]
}
```

## Edge kind taxonomy

- `reads_from` — the job consumes the dataset as input (e.g. `pd.read_csv("path/x.csv")`, `SELECT ... FROM table`).
- `writes_to` — the job produces the dataset as output (e.g. `df.to_csv("out.csv")`, `INSERT INTO table`, `CREATE TABLE`).
- `schedules` — a scheduler/orchestrator triggers the job (e.g. Airflow DAG declares a task, cron entry calls a script, Control-M defines a job).
- `depends_on` — the job has a downstream-task dependency (e.g. Airflow `task_a >> task_b`, Make rule `out: in`).

## Dataset kind taxonomy

- `table` — relational database table.
- `file` — filesystem path (local or networked).
- `topic` — message bus topic (Kafka, Pub/Sub, RabbitMQ exchange/queue).
- `endpoint` — HTTP / gRPC service endpoint.
- `queue` — task queue (Celery, Sidekiq, etc.) — distinguishable from `topic` by single-consumer semantics.

## Job kind taxonomy

- `script` — Python / shell / Node.js script invoked directly.
- `dag_task` — an individual task within an orchestrator DAG (Airflow / Prefect / Dagster).
- `dsx_job` — IBM DataStage job (`.dsx` file).
- `spark_app` — Spark application (PySpark, Scala Spark, Spark SQL).
- `stored_procedure` — SQL stored procedure / function.

## Confidence classification (BRIGHT-LINE — STRICT)

You MUST apply these rules verbatim. If you cannot determine the confidence, default to `speculative`.

| Tier | Rule | Examples |
|---|---|---|
| `grounded` | Literal string token (path/table-name) with NO interpolation; AND all symbols resolve in the local context (function args, top-level constants visible in the chunk) | `df = pd.read_csv("data/users.csv")` (literal path); `SELECT * FROM public.orders` (literal table); `with open(USERS_PATH) as f:` where `USERS_PATH = "/data/users.txt"` is in same chunk |
| `inferred` | Name-resolution heuristic — env-var resolved against an in-repo `.env` / `config.yaml`; OR relative path resolved against `__file__` location; OR SQL `FROM <alias>` resolved against a same-file CTE | `df = pd.read_csv(os.getenv("USERS_PATH"))` where `.env` in same repo declares `USERS_PATH=/data/users.csv`; `WITH cte AS (...) SELECT * FROM cte` |
| `speculative` | String interpolation (f-string / `.format()` / `%`-format / template literal) within ±20 lines; OR env-var without in-repo resolution; OR unresolved symbol; OR `SELECT *` without schema metadata; OR basename-only match | `df = pd.read_csv(f"{base}/users.csv")`; `df.to_csv(os.environ["OUT_PATH"])` where `OUT_PATH` not in `.env`; `INSERT INTO ${TABLE_NAME}` |

**HARD-RULE 2** baked in: if `evidence_snippet` contains ANY of:
- `f"..."` or `f'...'` (Python f-string)
- `.format(...)` call
- `%`-format like `"... %s ..." % var`
- `${...}` shell/env template
- `{{ ... }}` Jinja or similar

→ the edge MUST be `speculative`. NEVER `grounded` when interpolation is present.

If a symbol like `path = foo()` cannot be resolved to a literal within the current chunk, the edge MUST be `speculative` with `confidence_reason: "unresolved_symbol"`.

## Gap reporting (honest disclosure)

When you see something lineage-relevant but cannot extract a confident edge, emit a `gap` entry instead of a speculative edge. Closed enum for `gap.kind`:

- `dynamic_path` — the path is constructed at runtime (f-string, format, env-var without resolution).
- `unresolved_symbol` — a variable is referenced but its value is not visible in the chunk.
- `obfuscated` — the code is encoded / minified / generated.
- `binary_file` — chunk content is not text.
- `language_unsupported` — you don't have an extraction prompt for this format (e.g. proprietary binary serialization).

If you see no lineage-relevant content at all in the chunk, emit `edges: []` and `gaps: []`. An empty chunk is valid.

## Boundary status

Set `boundary_status` based on whether the chunk ends mid-statement:

- `complete` — the chunk begins after a clean statement boundary AND ends after a clean statement boundary.
- `partial_start` — the chunk begins inside a statement that started earlier (e.g. an open `SELECT ... FROM (` from the previous chunk).
- `partial_end` — a statement is open at the chunk's last line (e.g. SQL parenthesis count > 0, or Python code-block indent continues).
- `partial_both` — both `partial_start` AND `partial_end`.

For inline (single-chunk) files, `boundary_status` is always `complete`.

## Format requirements

- Emit ONE JSON object only. No prose before or after.
- Use valid JSON (double-quoted strings, no trailing commas, no comments).
- Line numbers are 1-indexed and file-relative (NOT chunk-relative).
- `evidence_snippet` MUST NOT contain credentials. If you see a credential in the source, replace it with `<REDACTED:reason>` in the snippet (e.g. `password="<REDACTED:password>"`). The downstream `redact.py` pass provides a second layer; you provide the first.
- `evidence_snippet` is capped at 1024 chars; truncate with `…` if needed.
- `confidence_reason` is capped at 256 chars; one-line, no newlines.

## Anti-patterns — DO NOT DO

- Do NOT emit `grounded` when the evidence has f-string / `.format()` / `%`-format / env-var template.
- Do NOT emit edges from comments or docstrings unless the comment is the canonical declaration site (e.g. SQL `-- @table public.users` annotations).
- Do NOT emit edges from import statements alone (`import pandas as pd` is not a lineage edge).
- Do NOT emit edges from variable assignments that don't terminate in I/O (`USERS_PATH = "/data/users.csv"` by itself is not a lineage edge — emit the edge only when the path is actually used in `pd.read_csv` / `open` / SQL etc.).
- Do NOT speculate about what a function call MIGHT do — only emit edges with direct in-chunk evidence.
- Do NOT include credentials, API keys, tokens, or passwords in `evidence_snippet` — substitute with `<REDACTED:reason>`.

## Tip — for SQL chunks

When chunking SQL, look for:
- `CREATE TABLE x.y` → emit `writes_to` edge with `source_dataset = (postgres://..., x.y, table)` and `target_job = (current-script-namespace, current-script-symbol, stored_procedure)`. Actually for DDL the JOB is the DDL execution context — encode the surrounding script's identity.
- `INSERT INTO x.y` → emit `writes_to` edge.
- `SELECT ... FROM x.y` → emit `reads_from` edge for `x.y`. For multi-table SELECTs, emit ONE edge per source table.
- `UPDATE x.y SET ...` → emit `writes_to` edge.
- `DELETE FROM x.y` → emit `writes_to` edge (a delete is still a write to the dataset state).

For SQL `JOIN`s, each joined table gets its own `reads_from` edge.

## Tip — for Python chunks

- `pd.read_csv("path")` / `pd.read_parquet(...)` / `pd.read_sql(...)` → `reads_from`.
- `df.to_csv(...)` / `df.to_parquet(...)` / `df.to_sql(...)` → `writes_to`.
- `open(path, 'r')` → `reads_from`. `open(path, 'w')` → `writes_to`.
- `requests.get(url)` / `httpx.get(url)` → `reads_from` with `kind: endpoint`.
- `requests.post(url, json=data)` → `writes_to` with `kind: endpoint`.
- `producer.send(topic, ...)` (Kafka) → `writes_to` with `kind: topic`.
- `consumer.subscribe(topic, ...)` → `reads_from` with `kind: topic`.

## Tip — for scheduler / orchestrator chunks

- Airflow `PythonOperator(task_id="...", python_callable=...)` → emit `schedules` edge from the DAG namespace to the script.
- Airflow `task_a >> task_b` → emit `depends_on` edge.
- Cron entry `0 2 * * * /opt/bin/load_users.py` → emit `schedules` edge from cron namespace to script.
- Control-M JSON job definition → emit `schedules` edge from Control-M namespace to the script/job.

If you're unsure about a scheduler format, fall back to `gap: language_unsupported`.

## You will now receive the chunk content. Emit one valid JSON object conforming to lineage-finding.v1.
