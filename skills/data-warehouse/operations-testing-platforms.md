# Operational Patterns, Testing, and Platform Guidance

Reference file for the `data-warehouse` skill. Covers platform-specific guidance (Snowflake, BigQuery, Redshift, Databricks), operational patterns (refresh strategies, monitoring, disaster recovery), and testing/quality.

## 10. Operational Patterns

### Incremental Loading — Watermark

```sql
-- High-water mark: track the last loaded timestamp per table
-- Read last watermark
SELECT watermark_value::TIMESTAMP AS last_loaded
FROM meta.etl_batch_log
WHERE batch_name = 'load_sales' AND status = 'SUCCESS'
ORDER BY batch_id DESC LIMIT 1;

-- Extract only new/changed records since last watermark
INSERT INTO staging.stg_sales
SELECT * FROM source_pos.sales
WHERE updated_at > :last_watermark
  AND updated_at <= :current_batch_timestamp;

-- Update watermark on success
UPDATE meta.etl_batch_log
SET watermark_value = :current_batch_timestamp::TEXT
WHERE batch_id = :current_batch_id;
```

### Incremental Loading — CDC (Change Data Capture)

```sql
-- PostgreSQL logical replication / Debezium: captures INSERT, UPDATE, DELETE as events
-- CDC event structure (from Kafka/Debezium):
-- { "op": "u", "before": {...}, "after": {...}, "ts_ms": 1711900800000, "source": {...} }

-- CDC staging table
CREATE TABLE staging.stg_customers_cdc (
    cdc_operation   CHAR(1),          -- 'I','U','D'
    cdc_timestamp   TIMESTAMP,
    customer_id     VARCHAR(30),
    customer_name   VARCHAR(200),
    email           VARCHAR(200),
    segment         VARCHAR(50),
    -- ... all source columns
    stg_load_date   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Apply CDC: use MERGE (or INSERT ON CONFLICT for PostgreSQL)
MERGE INTO dw.dim_customer tgt
USING staging.stg_customers_cdc src
ON tgt.customer_id = src.customer_id AND tgt.is_current = TRUE
WHEN MATCHED AND src.cdc_operation IN ('U','D') THEN
    UPDATE SET expiry_date = CURRENT_DATE - 1, is_current = FALSE
WHEN NOT MATCHED AND src.cdc_operation IN ('I','U') THEN
    INSERT (customer_id, customer_name, email, segment,
            effective_date, expiry_date, is_current, source_system)
    VALUES (src.customer_id, src.customer_name, src.email, src.segment,
            CURRENT_DATE, '9999-12-31', TRUE, 'CRM_CDC');
```

### Full Refresh

For small dimensions or reference data, truncate-and-reload is simpler and safer than incremental.

```sql
-- Full refresh pattern: swap via rename (zero-downtime)
CREATE TABLE dw.dim_store_new (LIKE dw.dim_store INCLUDING ALL);

INSERT INTO dw.dim_store_new
SELECT * FROM staging.stg_stores;  -- plus any transformations

-- Atomic swap
BEGIN;
ALTER TABLE dw.dim_store RENAME TO dim_store_old;
ALTER TABLE dw.dim_store_new RENAME TO dim_store;
COMMIT;

DROP TABLE dw.dim_store_old;
```

### Reconciliation

```sql
-- Row count reconciliation: source vs staging vs target
SELECT
    'source'  AS layer, COUNT(*) AS row_count FROM source_crm.customers
UNION ALL
SELECT
    'staging' AS layer, COUNT(*) AS row_count FROM staging.stg_customers
UNION ALL
SELECT
    'target'  AS layer, COUNT(*) AS row_count FROM dw.dim_customer WHERE is_current = TRUE;

-- Sum reconciliation: validate financial totals
SELECT
    'source'  AS layer, SUM(amount) AS total FROM source_pos.sales WHERE sale_date = '2026-03-31'
UNION ALL
SELECT
    'staging' AS layer, SUM(amount) AS total FROM staging.stg_sales WHERE sale_date = '2026-03-31'
UNION ALL
SELECT
    'target'  AS layer, SUM(net_amount) AS total FROM dw.fact_sales
    WHERE date_key = 20260331;

-- Automated reconciliation table
CREATE TABLE meta.reconciliation_log (
    recon_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id        BIGINT,
    table_name      VARCHAR(200),
    check_type      VARCHAR(50),     -- 'row_count', 'sum_amount', 'null_check'
    source_value    NUMERIC,
    target_value    NUMERIC,
    variance        NUMERIC,
    variance_pct    NUMERIC(5,2),
    status          VARCHAR(20),     -- 'PASS', 'WARN', 'FAIL'
    checked_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### ETL Monitoring

```sql
-- Dashboard query: recent batch status
SELECT
    batch_name,
    status,
    started_at,
    completed_at,
    EXTRACT(EPOCH FROM completed_at - started_at) / 60 AS duration_min,
    rows_loaded,
    rows_rejected
FROM meta.etl_batch_log
WHERE started_at >= CURRENT_DATE
ORDER BY started_at DESC;

-- Alert on failures or SLA breaches
SELECT batch_name, started_at, status
FROM meta.etl_batch_log
WHERE status = 'FAILED'
  AND started_at >= CURRENT_DATE - INTERVAL '1 day';

-- Alert: ETL not completed by SLA deadline
SELECT batch_name
FROM meta.etl_batch_log
WHERE batch_name = 'nightly_warehouse_load'
  AND started_at::DATE = CURRENT_DATE
  AND (status != 'SUCCESS' OR completed_at > CURRENT_DATE + TIME '06:00');
```

### SLA Management

Define and monitor ETL completion deadlines:

| Pipeline | SLA Deadline | Action if Breached |
|---|---|---|
| Nightly warehouse load | 06:00 local | Page on-call, notify stakeholders |
| Intraday ODS refresh | Every 15 min | Alert after 2 consecutive misses |
| Monthly close | T+2 business days | Escalate to data engineering lead |

### Capacity Planning

Monitor growth trends and project storage/compute needs:

```sql
-- PostgreSQL: table size over time
SELECT
    relname AS table_name,
    pg_size_pretty(pg_total_relation_size(oid)) AS total_size,
    pg_size_pretty(pg_table_size(oid)) AS data_size,
    pg_size_pretty(pg_indexes_size(oid)) AS index_size
FROM pg_class
WHERE relnamespace = 'dw'::regnamespace
ORDER BY pg_total_relation_size(oid) DESC;

-- Snowflake: storage and credit usage
SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME,
       ROW_COUNT, BYTES / (1024*1024*1024) AS GB
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'DW'
ORDER BY BYTES DESC;
```

### Archival

Move old partitions to cold storage. Keep the schema accessible for compliance queries.

```sql
-- PostgreSQL: detach and move to archive schema
ALTER TABLE dw.fact_sales DETACH PARTITION dw.fact_sales_202301;
ALTER TABLE dw.fact_sales_202301 SET SCHEMA archive;

-- Snowflake: move to lower-cost storage tier
ALTER TABLE dw.fact_sales_archive SET DATA_RETENTION_TIME_IN_DAYS = 1;

-- Redshift: unload to S3 and drop
UNLOAD ('SELECT * FROM dw.fact_sales WHERE date_key BETWEEN 20230101 AND 20231231')
TO 's3://warehouse-archive/fact_sales/2023/'
IAM_ROLE 'arn:aws:iam::123456789:role/RedshiftUnloadRole'
PARQUET;
```

---

## 11. Testing & Quality

### Unit Testing ETL (dbt)

```yaml
# dbt schema.yml: column-level tests
version: 2
models:
  - name: dim_customer
    columns:
      - name: customer_key
        tests:
          - unique
          - not_null
      - name: customer_id
        tests:
          - not_null
          - relationships:
              to: ref('stg_customers')
              field: customer_id
      - name: is_current
        tests:
          - accepted_values:
              values: [true, false]

  - name: fact_sales
    columns:
      - name: date_key
        tests:
          - not_null
          - relationships:
              to: ref('dim_date')
              field: date_key
      - name: customer_key
        tests:
          - not_null
      - name: net_amount
        tests:
          - not_null
    tests:
      - dbt_utils.expression_is_true:
          expression: "net_amount = quantity * unit_price - discount_amount"
```

### Unit Testing ETL (Great Expectations)

```python
# Great Expectations suite for fact_sales
import great_expectations as gx

context = gx.get_context()
batch = context.get_batch("fact_sales_batch")

# Row count check
batch.expect_table_row_count_to_be_between(min_value=1)

# No nulls on key columns
batch.expect_column_values_to_not_be_null("date_key")
batch.expect_column_values_to_not_be_null("customer_key")
batch.expect_column_values_to_not_be_null("net_amount")

# Value range checks
batch.expect_column_values_to_be_between("net_amount", min_value=0, max_value=1000000)
batch.expect_column_values_to_be_between("quantity", min_value=1, max_value=10000)

# Referential integrity
batch.expect_column_values_to_be_in_set(
    "customer_key",
    value_set=context.get_batch("dim_customer_keys")["customer_key"].tolist()
)

# Run and save results
results = context.run_checkpoint("fact_sales_checkpoint")
```

### Referential Integrity

Many cloud warehouses do not enforce foreign keys. Test referential integrity explicitly.

```sql
-- Orphaned fact rows: customer_key not in dim_customer
SELECT f.customer_key, COUNT(*) AS orphan_count
FROM dw.fact_sales f
LEFT JOIN dw.dim_customer dc ON f.customer_key = dc.customer_key
WHERE dc.customer_key IS NULL
  AND f.customer_key != -1   -- exclude known "Unknown" member
GROUP BY f.customer_key;

-- Orphaned fact rows: date_key not in dim_date
SELECT f.date_key, COUNT(*) AS orphan_count
FROM dw.fact_sales f
LEFT JOIN dw.dim_date dd ON f.date_key = dd.date_key
WHERE dd.date_key IS NULL
GROUP BY f.date_key;
```

### Balance Reconciliation

```sql
-- Cross-layer balance check: source amount = staging amount = target amount
WITH recon AS (
    SELECT 'source'  AS layer, SUM(amount) AS total
    FROM source_pos.sales WHERE sale_date = CURRENT_DATE - 1
    UNION ALL
    SELECT 'staging' AS layer, SUM(amount) AS total
    FROM staging.stg_sales WHERE sale_date = CURRENT_DATE - 1
    UNION ALL
    SELECT 'target'  AS layer, SUM(net_amount) AS total
    FROM dw.fact_sales WHERE date_key = TO_CHAR(CURRENT_DATE - 1, 'YYYYMMDD')::INT
)
SELECT
    layer,
    total,
    total - LAG(total) OVER (ORDER BY layer) AS variance
FROM recon;

-- Fail the batch if variance exceeds threshold
-- Implement in ETL orchestrator: IF ABS(variance) > 0.01 THEN RAISE ERROR
```

### Regression Testing

After ETL code changes, compare output against a known-good baseline.

```sql
-- Capture baseline row counts and checksums before code change
CREATE TABLE qa.baseline_checksums AS
SELECT
    'dim_customer' AS table_name,
    COUNT(*)       AS row_count,
    SUM(hashtext(customer_id::TEXT || customer_name || email)::BIGINT) AS checksum
FROM dw.dim_customer WHERE is_current = TRUE
UNION ALL
SELECT
    'fact_sales',
    COUNT(*),
    SUM(hashtext(date_key::TEXT || customer_key::TEXT || net_amount::TEXT)::BIGINT)
FROM dw.fact_sales WHERE date_key >= 20260301;

-- After code change: compare
SELECT
    b.table_name,
    b.row_count  AS baseline_rows,
    c.row_count  AS current_rows,
    b.checksum   AS baseline_checksum,
    c.checksum   AS current_checksum,
    CASE WHEN b.row_count = c.row_count AND b.checksum = c.checksum
         THEN 'PASS' ELSE 'FAIL' END AS result
FROM qa.baseline_checksums b
JOIN qa.current_checksums c ON b.table_name = c.table_name;
```

### Data Profiling

Run profiling before building ETL to understand source data characteristics.

```sql
-- Column profiling: nulls, distinct values, min/max
SELECT
    'customer_name' AS column_name,
    COUNT(*)                                    AS total_rows,
    COUNT(customer_name)                        AS non_null_count,
    COUNT(*) - COUNT(customer_name)             AS null_count,
    ROUND(100.0 * (COUNT(*) - COUNT(customer_name)) / COUNT(*), 2) AS null_pct,
    COUNT(DISTINCT customer_name)               AS distinct_count,
    MIN(customer_name)                          AS min_value,
    MAX(customer_name)                          AS max_value,
    MIN(LENGTH(customer_name))                  AS min_length,
    MAX(LENGTH(customer_name))                  AS max_length
FROM staging.stg_customers;
```

---

## Related Skills

| Domain | Skill |
|---|---|
| SQLAlchemy, Alembic, query optimization | `python-data-engineer` |
| DB2, Oracle, SQL Server, mainframe connectors | `python-enterprise-connectors` |
| PostgreSQL/MySQL/Redis on RHEL 9 | `rhel-databases` |
| PostgreSQL/MySQL/Redis on Ubuntu 24.04 | `ubuntu-databases` |
| Docker containers for dev/test warehouses | `docker-compose-patterns` |
| ETL/pipeline parallelism in Python | `python-parallelism` |
| Data pipeline profiling and load testing | `performance` |
