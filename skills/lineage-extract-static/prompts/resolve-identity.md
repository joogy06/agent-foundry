# Resolve Dataset Identity (3-Step Waterfall)

You are canonicalizing dataset identifiers across the project-aggregate JSON produced by `merge-across-files.md`. Every `source_dataset.namespace` + `name` tuple in `edges[]` is run through this deterministic 3-step waterfall BEFORE OpenLineage emission.

**HARD-RULE 3**: The waterfall is deterministic. You do NOT guess. You apply rules in order. If no rule produces a canonical identity, you leave the dataset reference unchanged and add a `gap: unresolved_identity` entry.

## Input you will receive

- The project-aggregate JSON from `merge-across-files.md`.
- `project_root` — absolute path to the project (for path resolution).
- `aliases` — content of `.lineage/aliases.yaml` if present (optional).

## The 3-step waterfall

For each `source_dataset` (and the target_job's namespace when applicable):

### Step 1 — SQL FQN (highest precedence)

If the reference is in a SQL context (DDL, DML, JDBC URI), canonicalize to:
- `namespace = <db-engine>://<host>:<port>/<db>`
- `name = <schema>.<table>`

Default-schema resolution:
- PostgreSQL: default schema is `public`.
- Oracle: default schema is `<USER>` (the connection user). Look for context like `connect_as=<user>` or default to `unknown_schema`.
- Snowflake: default is `<account>.<warehouse>` — typically expressed as part of the connection URI.
- MySQL / MariaDB: default schema is the connection database (no namespace prefix needed beyond db).
- BigQuery: namespace is `bigquery://<project>`, name is `<dataset>.<table>`.
- SQL Server: namespace is `sqlserver://<server>:<port>/<db>`, name is `<schema>.<table>` (default schema `dbo`).
- SQLite: namespace is `sqlite:<absolute path>`, name is `main.<table>` (single-schema model).
- DB2: namespace is `db2://<host>:<port>/<db>`, name is `<schema>.<table>`.

Examples:
- `CREATE TABLE analytics.public.users` → `namespace=postgres://dwh:5432/analytics`, `name=public.users` (if `dwh:5432` is inferable from connection metadata; otherwise `postgres://unknown:5432/analytics`).
- `INSERT INTO orders` (no schema) in PostgreSQL context → `namespace=postgres://<host>:<port>/<db>`, `name=public.orders`.
- `SELECT * FROM "DB2INST1"."CUSTOMERS"` → `namespace=db2://<host>:<port>/<db>`, `name=DB2INST1.CUSTOMERS`.

### Step 2 — Repo-root-relative absolute path (for filesystem datasets)

If the reference is a filesystem path:
1. Resolve relative paths against repo root (`project_root` input).
2. `realpath` to dereference symlinks (in your head — simulate as if calling `os.path.realpath`).
3. If the resolved path is INSIDE the repo: `namespace = file://<repo-root-anchor>`, `name = <repo-relative path>` (with forward slashes).
4. If the resolved path is OUTSIDE the repo (e.g. `/mnt/data/landing/users.csv`): `namespace = file://`, `name = <absolute path>`.
5. Choose the repo-root-anchor as the basename of `project_root`. Example: `project_root = /home/user/projects/my-data-pipeline` → `namespace = file://my-data-pipeline`.

Examples:
- `pd.read_csv("data/landing/users.csv")` from `etl/load_users.py` in repo `my-pipeline` → `namespace=file://my-pipeline`, `name=data/landing/users.csv`.
- `open("/etc/config.yaml")` (absolute path outside repo) → `namespace=file://`, `name=/etc/config.yaml`.

### Step 3 — Configurable alias map (`.lineage/aliases.yaml`)

If the `aliases` input declares a canonical mapping for the reference, apply it:

```yaml
aliases:
  - canonical: {namespace: "postgres://dwh-prod:5432/analytics", name: "public.users"}
    matches:
      - "DWH_PROD_DSN.users"             # ODBC DSN string
      - "jdbc:oracle:thin:@legacy:1521:analytics.users"   # legacy migration alias
```

If `source_dataset.namespace + "." + source_dataset.name` (or any string-key form) matches an entry in `aliases[].matches`, replace `source_dataset` with the corresponding `canonical` value.

## DSX / dbt overrides (explicit user declaration wins)

When you detect a DSX `Server` + `Table` property pair, OR a dbt `source()` declaration in the original evidence, that overrides path-based identity (the user's explicit declaration wins over heuristic):

- DSX example: `Server="DWH_PROD" Table="public.users"` → `namespace=postgres://DWH_PROD:5432/<inferred>`, `name=public.users`. If port + db cannot be inferred, fall back to `namespace=dsx://DWH_PROD`, `name=public.users`.
- dbt example: `source('analytics', 'users')` → `namespace=dbt://<project_name>`, `name=analytics.users`. dbt has its own catalog; the dbt namespace is the canonical reference.

## Basename-only merge — OFF BY DEFAULT

If you see two datasets that differ only by full path but share the same basename (e.g. `file://repo/data/landing/users.csv` and `s3://acme-data/users.csv`), DO NOT collapse them. They are separate datasets.

ONLY when the run was invoked with `--merge-by-basename` flag (you will be told this in the input), emit an additional advisory edge with `confidence: speculative` + a custom facet `possible_alias` listing the candidate match. NEVER silently merge.

## What you emit (one JSON object only)

Same structure as the input project-aggregate JSON, but with:
- Every `source_dataset` resolved through the waterfall.
- Every `target_job.namespace` normalized when applicable (e.g. for jobs declared in a Spark deploy URI).
- A new `identity_resolution_log` array recording every change made:

```json
{
  ...same as input...,
  "edges": [...],
  "gaps": [
    ...existing gaps...,
    {"kind": "unresolved_identity", "line": <source_file_line>, "description": "Could not resolve dataset reference X via any waterfall step"}
  ],
  "identity_resolution_log": [
    {
      "source_file": "etl/load_users.py",
      "source_file_line": 412,
      "original": {"namespace": "file://", "name": "users.csv"},
      "resolved": {"namespace": "file://my-pipeline", "name": "data/landing/users.csv"},
      "step": "step_2_repo_path"
    }
  ]
}
```

## Anti-patterns — DO NOT DO

- Do NOT collapse datasets by basename alone unless `--merge-by-basename` was set.
- Do NOT infer database hostnames or ports that aren't visible in the input — fall back to `<host>` / `<port>` placeholders if needed.
- Do NOT modify `target_job.namespace` unless you have explicit evidence (e.g. a `JobNamespaceOverrideFacet`).
- Do NOT touch `confidence` values during identity resolution — that's `analyze-file.md`'s call, not yours.
- Do NOT remove edges. If you cannot resolve an identity, leave the edge unchanged and add a `gap: unresolved_identity` entry.

## Format requirements

- Emit ONE JSON object only.
- Sort `identity_resolution_log[]` by `(source_file, source_file_line, step)` for deterministic output ordering.
- Preserve every edge and gap from the input.

## You will now receive the project-aggregate JSON + project_root + aliases (optional). Emit the identity-resolved aggregate JSON.
