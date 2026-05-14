# Dataset Identity Resolution — 3-Step Waterfall

Reference for HARD-RULE 3: every dataset reference is canonicalized through this deterministic 3-step waterfall BEFORE OpenLineage emission. The waterfall runs in `prompts/resolve-identity.md` over the project-aggregate JSON; basename-only merge is OFF by default.

## The waterfall

```
For each source_dataset (namespace, name) tuple:
    1. SQL FQN rule       ← highest precedence (database datasets)
    2. Repo-relative path ← filesystem datasets
    3. Alias map override ← .lineage/aliases.yaml (optional)

Output the first rule that produces a canonical identity, or leave unchanged + emit gap: unresolved_identity.
```

## Step 1 — SQL FQN

If the reference appears in a SQL context (DDL, DML, JDBC URI):

- `namespace = <db-engine>://<host>:<port>/<db>`
- `name = <schema>.<table>` (or db-specific variation per the table below)

### Default-schema resolution table

| Engine | Default schema | Notes |
|---|---|---|
| PostgreSQL | `public` | `CREATE TABLE users` → `public.users` |
| MySQL / MariaDB | (connection db) | No schema layer; `CREATE TABLE users` → `users` (db-prefix in namespace) |
| Oracle | `<USER>` | `CREATE TABLE users` → `<connection-user>.users` |
| SQL Server | `dbo` | `CREATE TABLE users` → `dbo.users` |
| Snowflake | `<account>.<warehouse>` | Account + warehouse encoded in namespace |
| BigQuery | (project + dataset) | `bigquery://<project>` + `<dataset>.<table>` |
| DB2 LUW | `<USER>` | Similar to Oracle |
| DB2 z/OS | (Schema clause required) | No default; emit gap if absent |
| SQLite | `main` | Single-schema model |

### Examples

```sql
CREATE TABLE analytics.public.users (...)
-- → namespace=postgres://<host>:<port>/analytics, name=public.users
```

```sql
INSERT INTO orders                            -- PostgreSQL context, no schema
-- → namespace=postgres://<host>:<port>/<db>, name=public.orders
```

```python
conn = oracledb.connect("user/pass@oracle-prod:1521/analytics")
cur.execute("SELECT * FROM users")
-- → namespace=oracle://oracle-prod:1521/analytics, name=USER.users (the connection user)
```

```python
import sqlite3
conn = sqlite3.connect("/data/etl.db")
cur.execute("CREATE TABLE customers (...)")
-- → namespace=sqlite:/data/etl.db, name=main.customers
```

### When the host:port is not visible in the chunk

If the chunk has no connection-metadata context, fall back to `<host>` and `<port>` placeholders:

```sql
CREATE TABLE public.users (...)
-- → namespace=postgres://<host>:<port>/<db>, name=public.users
```

The downstream alias map (Step 3) can normalize these to concrete URIs if the user provides them.

## Step 2 — Repo-root-relative absolute path

For filesystem references:

1. Resolve relative paths against `project_root` (the input to `lineage-extract-static analyze`).
2. `realpath` to dereference symlinks.
3. If the resolved path is INSIDE the repo:
   - `namespace = file://<repo-root-anchor>` (the basename of `project_root`)
   - `name = <repo-relative path>` (forward slashes on all platforms)
4. If the resolved path is OUTSIDE the repo:
   - `namespace = file://`
   - `name = <absolute-path>`

### Examples

```python
# In repo /home/user/my-pipeline; chunk at etl/load_users.py
df = pd.read_csv("data/landing/users.csv")
# → namespace=file://my-pipeline, name=data/landing/users.csv
```

```python
# Absolute path outside repo
with open("/etc/config.yaml") as f:
    cfg = yaml.safe_load(f)
# → namespace=file://, name=/etc/config.yaml
```

```python
# __file__-relative
HERE = os.path.dirname(os.path.abspath(__file__))
df = pd.read_csv(os.path.join(HERE, "fixtures/users.csv"))
# → namespace=file://my-pipeline, name=etl/fixtures/users.csv
# (resolved against the script's location)
```

### Why `<repo-root-anchor>`

We don't use the absolute path of the repo because it varies by deployment (`/home/alice/my-pipeline` vs `/opt/projects/my-pipeline`). The basename anchor is stable: `file://my-pipeline` resolves consistently across machines.

## Step 3 — Configurable alias map

Optional. If `.lineage/aliases.yaml` is present in the project root, it can declare canonical mappings:

```yaml
# .lineage/aliases.yaml
aliases:
  - canonical:
      namespace: postgres://dwh-prod:5432/analytics
      name: public.users
    matches:
      - "DWH_PROD_DSN.users"             # ODBC DSN string used in code
      - "jdbc:oracle:thin:@legacy:1521:analytics.users"   # legacy migration alias
      - "postgres://<host>:<port>/<db>.public.users"   # placeholder collapse
  - canonical:
      namespace: s3://acme-data
      name: landing/users/2026-05-14.parquet
    matches:
      - "/mnt/landing/users/2026-05-14.parquet"        # NFS mount mirror
      - "file:///opt/data/landing/users/2026-05-14.parquet"  # alternative mount point
```

Resolution: if `source_dataset.namespace + "." + source_dataset.name` (or any string form) matches an entry's `matches[]`, replace `source_dataset` with the corresponding `canonical` value.

## DSX / dbt overrides (explicit declaration wins)

When the original evidence is a user's explicit declaration in a DSX `.dsx` file or a dbt `source()` declaration, that overrides path-based identity. The user's explicit declaration is more trustworthy than heuristic resolution.

### DSX example

```
Server="DWH_PROD"
Table="public.users"
```

→ `namespace=postgres://DWH_PROD:5432/<inferred>`, `name=public.users`. If port + db cannot be inferred, fall back to `namespace=dsx://DWH_PROD`, `name=public.users`. The alias map can then unify `dsx://DWH_PROD` ↔ `postgres://dwh-prod:5432/analytics`.

### dbt example

```yaml
# models/staging/users.sql sources from:
sources:
  - name: analytics
    tables:
      - name: users
```

```sql
SELECT * FROM {{ source('analytics', 'users') }}
```

→ `namespace=dbt://<project>`, `name=analytics.users`. dbt has its own catalog; this is the canonical reference. Alias map can collapse `dbt://my-project.analytics.users` ↔ `postgres://dwh:5432/analytics.public.users` if desired.

## Basename-only merge — OFF by default

Sometimes two datasets have different paths but the same basename:

- `file://my-pipeline/data/landing/users.csv` (local landing)
- `s3://acme-data/landing/users.csv` (S3 mirror)

These are SEPARATE datasets. We DO NOT collapse them by basename.

When `--merge-by-basename` is explicitly enabled, the renderer emits an additional advisory edge with `confidence: speculative` and a `possible_alias` custom facet listing the candidates. The original two datasets remain distinct in the OL output. NEVER silently merged.

## Why this matters

Identity resolution is the single biggest source of bad lineage. A wrong namespace+name canonical mapping silently merges datasets that shouldn't be one, or splits datasets that should. The 3-step waterfall is deterministic, the basename merge is opt-in + speculative-only, and the alias map gives the user explicit control over edge cases. No LLM judgment in pairing decisions.

## Tests

`tests/lineage-extract-static/unit/test_dataset_identity.py` enforces:
- Step 1 SQL FQN resolution for each engine in the table above
- Step 2 repo-relative path resolution (including symlink + `__file__` cases)
- Step 3 alias map override
- DSX / dbt explicit-declaration override
- Basename-only merge OFF unless `--merge-by-basename` set
- `gap: unresolved_identity` emitted when no rule produces a canonical identity
