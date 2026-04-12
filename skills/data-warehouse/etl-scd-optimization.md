# ETL/ELT, SCDs, Partitioning, and Query Optimization

Reference file for the `data-warehouse` skill. Covers Data Vault 2.0, ETL/ELT design, slowly changing dimensions, partitioning/distribution strategies, and query optimization.

## 5. ETL/ELT Design

### Staging Layer

```sql
-- Staging: exact copy of source, truncated and reloaded each batch
CREATE TABLE staging.stg_customers (
    customer_id         VARCHAR(30),
    customer_name       VARCHAR(200),
    email               VARCHAR(200),
    segment             VARCHAR(50),
    city                VARCHAR(100),
    state_province      VARCHAR(100),
    country             VARCHAR(100),
    source_updated_at   TIMESTAMP,        -- source system timestamp
    -- ETL metadata
    stg_load_date       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    stg_batch_id        BIGINT,
    stg_row_hash        BYTEA             -- hash of all business columns for change detection
);

-- Truncate before each load (staging is transient)
TRUNCATE TABLE staging.stg_customers;

-- Load from source (example: PostgreSQL FDW, COPY, or application insert)
INSERT INTO staging.stg_customers (customer_id, customer_name, email, segment,
    city, state_province, country, source_updated_at, stg_batch_id, stg_row_hash)
SELECT
    customer_id, customer_name, email, segment,
    city, state_province, country, updated_at,
    :batch_id,
    md5(CONCAT_WS('|', customer_name, email, segment, city, state_province, country))::BYTEA
FROM source_crm.customers
WHERE updated_at > :last_watermark;
```

### Surrogate Key Pipeline

```sql
-- Option 1: IDENTITY / SERIAL (simplest, per-table)
CREATE TABLE dw.dim_customer (
    customer_key INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ...
);

-- Option 2: Sequence (shared across tables if needed)
CREATE SEQUENCE dw.dim_key_seq START 1 INCREMENT 1;

-- Option 3: Hash-based surrogate (deterministic, useful for distributed/parallel loads)
-- customer_key = ABS(HASHBYTES('SHA2_256', customer_id) % 2147483647)
```

### SCD Processing (see Section 6 for full SCD type details)

Generic SCD Type 2 load pattern:

```sql
-- Step 1: Expire changed rows
UPDATE dw.dim_customer tgt
SET expiry_date = CURRENT_DATE - INTERVAL '1 day',
    is_current = FALSE
FROM staging.stg_customers stg
WHERE tgt.customer_id = stg.customer_id
  AND tgt.is_current = TRUE
  AND tgt.row_hash IS DISTINCT FROM stg.stg_row_hash;

-- Step 2: Insert new/changed rows
INSERT INTO dw.dim_customer (customer_id, customer_name, email, segment,
    city, state_province, country, effective_date, expiry_date, is_current,
    row_hash, load_date, source_system)
SELECT
    stg.customer_id, stg.customer_name, stg.email, stg.segment,
    stg.city, stg.state_province, stg.country,
    CURRENT_DATE,           -- effective_date
    '9999-12-31'::DATE,     -- expiry_date
    TRUE,                   -- is_current
    stg.stg_row_hash,
    CURRENT_TIMESTAMP,
    'CRM_SYSTEM'
FROM staging.stg_customers stg
WHERE NOT EXISTS (
    SELECT 1 FROM dw.dim_customer tgt
    WHERE tgt.customer_id = stg.customer_id
      AND tgt.is_current = TRUE
      AND tgt.row_hash = stg.stg_row_hash
);
```

### Fact Loading

```sql
-- Fact load: look up surrogate keys, insert new rows
INSERT INTO dw.fact_sales (date_key, customer_key, product_key, store_key,
    promotion_key, order_number, quantity, unit_price, discount_amount,
    net_amount, tax_amount, gross_amount, cost_amount, load_date,
    source_system, batch_id)
SELECT
    TO_CHAR(s.sale_date, 'YYYYMMDD')::INT              AS date_key,
    COALESCE(dc.customer_key, -1)                       AS customer_key,
    COALESCE(dp.product_key, -1)                        AS product_key,
    COALESCE(ds.store_key, -1)                          AS store_key,
    COALESCE(dpr.promotion_key, -1)                     AS promotion_key,
    s.order_number,
    s.quantity,
    s.unit_price,
    s.discount_amount,
    s.quantity * s.unit_price - s.discount_amount       AS net_amount,
    (s.quantity * s.unit_price - s.discount_amount) * 0.10 AS tax_amount,
    (s.quantity * s.unit_price - s.discount_amount) * 1.10 AS gross_amount,
    s.unit_cost * s.quantity                            AS cost_amount,
    CURRENT_TIMESTAMP,
    'POS_SYSTEM',
    :batch_id
FROM staging.stg_sales s
LEFT JOIN dw.dim_customer dc
    ON dc.customer_id = s.customer_id AND dc.is_current = TRUE
LEFT JOIN dw.dim_product dp
    ON dp.product_id = s.product_id AND dp.is_current = TRUE
LEFT JOIN dw.dim_store ds
    ON ds.store_id = s.store_id AND ds.is_current = TRUE
LEFT JOIN dw.dim_promotion dpr
    ON dpr.promotion_id = s.promotion_id AND dpr.is_current = TRUE;
```

Use `-1` surrogate key for unknown/missing dimension members. Always pre-insert an "Unknown" row with key `-1` in every dimension table.

### Error Handling and Restart/Recovery

```sql
-- ETL batch control table
CREATE TABLE meta.etl_batch_log (
    batch_id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_name          VARCHAR(200)  NOT NULL,
    status              VARCHAR(20)   NOT NULL DEFAULT 'RUNNING',  -- RUNNING, SUCCESS, FAILED
    started_at          TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMP,
    rows_extracted      BIGINT,
    rows_loaded         BIGINT,
    rows_rejected       BIGINT,
    error_message       TEXT,
    watermark_value     VARCHAR(256)  -- high-water mark for incremental restart
);

-- Step-level logging
CREATE TABLE meta.etl_step_log (
    step_id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id            BIGINT        NOT NULL REFERENCES meta.etl_batch_log,
    step_name           VARCHAR(200)  NOT NULL,
    step_order          INT           NOT NULL,
    status              VARCHAR(20)   NOT NULL DEFAULT 'RUNNING',
    started_at          TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMP,
    rows_affected       BIGINT,
    error_message       TEXT
);
```

Restart pattern: on failure, set batch status to FAILED, fix the issue, then re-run the same batch_id. Idempotent loads (MERGE or delete-then-insert by partition) ensure no duplicates.

### Metadata Logging

```sql
-- Record load completion and update watermark
UPDATE meta.etl_batch_log
SET status = 'SUCCESS',
    completed_at = CURRENT_TIMESTAMP,
    rows_extracted = :extracted,
    rows_loaded = :loaded,
    rows_rejected = :rejected,
    watermark_value = :new_watermark
WHERE batch_id = :batch_id;

-- Next run reads the last successful watermark
SELECT watermark_value
FROM meta.etl_batch_log
WHERE batch_name = 'load_customers'
  AND status = 'SUCCESS'
ORDER BY batch_id DESC
LIMIT 1;
```

---

## 6. Slowly Changing Dimensions

### Type 0 — Fixed (Retain Original)

Never change the value. Used for attributes that must not be modified after initial load (original credit score at account opening, date of birth).

```sql
-- Type 0: simply skip updates for fixed columns
-- During SCD processing, exclude Type 0 columns from the hash comparison
-- and never overwrite them in UPDATE statements.
```

### Type 1 — Overwrite

Current value only, no history. Simplest approach — just UPDATE the row.

```sql
-- Type 1: overwrite in place
UPDATE dw.dim_customer tgt
SET customer_name   = stg.customer_name,
    email           = stg.email,
    segment         = stg.segment,
    load_date       = CURRENT_TIMESTAMP
FROM staging.stg_customers stg
WHERE tgt.customer_id = stg.customer_id
  AND tgt.is_current = TRUE
  AND (tgt.customer_name IS DISTINCT FROM stg.customer_name
    OR tgt.email IS DISTINCT FROM stg.email
    OR tgt.segment IS DISTINCT FROM stg.segment);
```

### Type 2 — Add New Row (Full History)

New row for each change with effective/expiry dates. Most common for dimensions where history matters.

```sql
-- Type 2: expire old row, insert new row (see SCD Processing in Section 5)
-- The pattern from Section 5's "SCD Processing" is the canonical Type 2 implementation.

-- Querying current state:
SELECT * FROM dw.dim_customer WHERE is_current = TRUE;

-- Querying state at a point in time:
SELECT * FROM dw.dim_customer
WHERE effective_date <= '2025-06-15'
  AND expiry_date > '2025-06-15';
```

### Type 3 — Add Column (Limited History)

Store current and previous value in separate columns. Only tracks one historical change.

```sql
ALTER TABLE dw.dim_customer
    ADD COLUMN previous_segment VARCHAR(50),
    ADD COLUMN segment_change_date DATE;

-- Type 3 update: shift current to previous, load new
UPDATE dw.dim_customer tgt
SET previous_segment    = tgt.segment,
    segment             = stg.segment,
    segment_change_date = CURRENT_DATE,
    load_date           = CURRENT_TIMESTAMP
FROM staging.stg_customers stg
WHERE tgt.customer_id = stg.customer_id
  AND tgt.is_current = TRUE
  AND tgt.segment IS DISTINCT FROM stg.segment;
```

### Type 4 — Mini-Dimension (History Table)

Rapidly changing attributes split into a separate mini-dimension. Main dimension stays small; the mini-dimension handles the volatility.

```sql
-- Current profile in mini-dimension (see mini-dimension example in Section 3)
-- Fact table carries both customer_key and demo_key
-- When demographics change, a new demo_key is assigned to new fact rows
-- Historical facts retain their original demo_key
```

### Type 6 — Hybrid (1 + 2 + 3)

Combines Type 1 overwrite, Type 2 history rows, and Type 3 current-value column. Every row has both the value at that point in time AND the current value.

```sql
-- Type 6 dimension: has history rows (Type 2) + current_segment column (Type 1 overwrite on all rows)
CREATE TABLE dw.dim_customer_type6 (
    customer_key        INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id         VARCHAR(30)  NOT NULL,
    customer_name       VARCHAR(200),
    segment             VARCHAR(50),      -- value at that point in time (Type 2)
    current_segment     VARCHAR(50),      -- always reflects the latest value (Type 1)
    effective_date      DATE         NOT NULL,
    expiry_date         DATE         NOT NULL DEFAULT '9999-12-31',
    is_current          BOOLEAN      NOT NULL DEFAULT TRUE
);

-- When segment changes:
-- Step 1: Expire current row (Type 2)
UPDATE dw.dim_customer_type6
SET expiry_date = CURRENT_DATE - 1, is_current = FALSE
WHERE customer_id = 'C001' AND is_current = TRUE;

-- Step 2: Insert new row with new segment (Type 2)
INSERT INTO dw.dim_customer_type6 (customer_id, customer_name, segment, current_segment,
    effective_date, expiry_date, is_current)
VALUES ('C001', 'Jane Doe', 'Premium', 'Premium', CURRENT_DATE, '9999-12-31', TRUE);

-- Step 3: Overwrite current_segment on ALL historical rows (Type 1)
UPDATE dw.dim_customer_type6
SET current_segment = 'Premium'
WHERE customer_id = 'C001';
```

### Hash Diff Detection

Use hash comparison to efficiently detect changed rows without comparing every column.

```sql
-- Generate hash in staging (PostgreSQL)
UPDATE staging.stg_customers
SET stg_row_hash = md5(
    CONCAT_WS('|',
        COALESCE(customer_name, ''),
        COALESCE(email, ''),
        COALESCE(segment, ''),
        COALESCE(city, ''),
        COALESCE(state_province, ''),
        COALESCE(country, '')
    )
)::BYTEA;

-- Snowflake equivalent
-- MD5(CONCAT_WS('|', NVL(customer_name,''), NVL(email,''), NVL(segment,''), ...))

-- Compare: only process rows where hash differs
SELECT stg.*
FROM staging.stg_customers stg
JOIN dw.dim_customer dim
    ON dim.customer_id = stg.customer_id AND dim.is_current = TRUE
WHERE dim.row_hash IS DISTINCT FROM stg.stg_row_hash;
```

---

## 7. Partitioning & Distribution

### Range Partitioning by Date

The single most impactful physical design decision for fact tables. Enables partition pruning, fast archival, and efficient incremental loads.

```sql
-- PostgreSQL: declarative partitioning
CREATE TABLE dw.fact_sales (
    sale_key        BIGINT GENERATED ALWAYS AS IDENTITY,
    date_key        INT NOT NULL,
    customer_key    INT NOT NULL,
    product_key     INT NOT NULL,
    net_amount      NUMERIC(12,2),
    load_date       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) PARTITION BY RANGE (date_key);

-- Monthly partitions
CREATE TABLE dw.fact_sales_202601 PARTITION OF dw.fact_sales
    FOR VALUES FROM (20260101) TO (20260201);
CREATE TABLE dw.fact_sales_202602 PARTITION OF dw.fact_sales
    FOR VALUES FROM (20260201) TO (20260301);
CREATE TABLE dw.fact_sales_202603 PARTITION OF dw.fact_sales
    FOR VALUES FROM (20260301) TO (20260401);

-- Auto-create future partitions (run monthly via cron or pg_partman)
-- pg_partman: CREATE EXTENSION pg_partman;
-- SELECT partman.create_parent('dw.fact_sales', 'date_key', 'native', 'monthly');
```

### Snowflake — Clustering Keys and Micro-Partitions

Snowflake auto-partitions into micro-partitions. Clustering keys determine sort order within micro-partitions for partition pruning.

```sql
-- Set clustering key on large fact tables
ALTER TABLE dw.fact_sales CLUSTER BY (date_key, store_key);

-- Monitor clustering depth (lower = better)
SELECT SYSTEM$CLUSTERING_INFORMATION('dw.fact_sales');

-- Automatic Clustering keeps it maintained (Enterprise Edition)
ALTER TABLE dw.fact_sales RESUME RECLUSTER;
```

### Redshift — Distribution and Sort Keys

```sql
-- Distribution strategies:
-- KEY: distribute by a join column (customer_key) — co-locates related data
-- ALL: replicate small dimension tables to every node
-- EVEN: round-robin (default, for tables with no clear join pattern)

CREATE TABLE dw.fact_sales (
    sale_key        BIGINT IDENTITY(1,1),
    date_key        INT NOT NULL,
    customer_key    INT NOT NULL,
    net_amount      DECIMAL(12,2)
)
DISTSTYLE KEY
DISTKEY (customer_key)
COMPOUND SORTKEY (date_key, customer_key);

-- Small dimension: replicate
CREATE TABLE dw.dim_store (
    store_key       INT PRIMARY KEY,
    store_name      VARCHAR(200)
)
DISTSTYLE ALL;

-- Maintenance
VACUUM FULL dw.fact_sales;   -- reclaim space, resort rows
ANALYZE dw.fact_sales;       -- update statistics
```

### BigQuery — Partitioned and Clustered Tables

```sql
-- Partition by date column, cluster by frequently filtered columns
CREATE TABLE `project.dw.fact_sales`
(
    sale_key        INT64,
    sale_date       DATE NOT NULL,
    customer_key    INT64,
    product_key     INT64,
    store_key       INT64,
    net_amount      NUMERIC
)
PARTITION BY sale_date
CLUSTER BY store_key, product_key
OPTIONS (
    partition_expiration_days = 3650,
    require_partition_filter = TRUE   -- prevent full table scans
);

-- Integer range partitioning (alternative)
-- PARTITION BY RANGE_BUCKET(date_key, GENERATE_ARRAY(20200101, 20301231, 100))
```

### DB2 Warehouse — MQTs and MDC

```sql
-- Multi-Dimensional Clustering (MDC): physical clustering on multiple dimensions
CREATE TABLE dw.fact_sales (
    date_key        INT NOT NULL,
    customer_key    INT NOT NULL,
    product_key     INT NOT NULL,
    store_key       INT NOT NULL,
    net_amount      DECIMAL(12,2)
)
ORGANIZE BY DIMENSIONS (date_key, store_key);
-- DB2 creates block indexes automatically for each dimension

-- Materialized Query Table (MQT) — DB2's materialized view
CREATE TABLE dw.mqt_daily_sales AS (
    SELECT
        date_key,
        store_key,
        SUM(net_amount)   AS total_sales,
        COUNT(*)          AS txn_count
    FROM dw.fact_sales
    GROUP BY date_key, store_key
)
DATA INITIALLY DEFERRED REFRESH DEFERRED;

REFRESH TABLE dw.mqt_daily_sales;
-- SET CURRENT REFRESH AGE = ANY   -- allows optimizer to route queries to MQT
```

### Partition Maintenance

```sql
-- PostgreSQL: detach old partitions for archival
ALTER TABLE dw.fact_sales DETACH PARTITION dw.fact_sales_202401;
-- Archive the detached table, then drop when no longer needed

-- Add new partitions ahead of time (automate via cron)
DO $$
DECLARE
    next_month DATE := DATE_TRUNC('month', CURRENT_DATE + INTERVAL '2 months');
    part_name TEXT;
    start_key INT;
    end_key INT;
BEGIN
    part_name := 'dw.fact_sales_' || TO_CHAR(next_month, 'YYYYMM');
    start_key := TO_CHAR(next_month, 'YYYYMMDD')::INT;
    end_key   := TO_CHAR(next_month + INTERVAL '1 month', 'YYYYMMDD')::INT;
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %s PARTITION OF dw.fact_sales FOR VALUES FROM (%s) TO (%s)',
        part_name, start_key, end_key
    );
END $$;
```

---

## 8. Query Optimization

### Star Join Optimization

Modern optimizers (PostgreSQL 12+, Snowflake, Redshift, BigQuery) recognize star join patterns and apply bitmap/hash join strategies.

```sql
-- Efficient star join: filter dimensions first, then join to fact
-- The optimizer does this automatically, but write queries to make intent clear
SELECT
    d.month_name,
    p.category,
    s.store_name,
    SUM(f.net_amount)      AS total_sales,
    SUM(f.quantity)         AS total_qty
FROM dw.fact_sales f
JOIN dw.dim_date d      ON f.date_key     = d.date_key
JOIN dw.dim_product p   ON f.product_key  = p.product_key
JOIN dw.dim_store s     ON f.store_key    = s.store_key
WHERE d.year_number = 2026
  AND p.category = 'Electronics'
  AND s.country = 'United Kingdom'
GROUP BY d.month_name, p.category, s.store_name
ORDER BY total_sales DESC;
```

### Bitmap Indexes (Oracle, DB2)

Bitmap indexes are ideal for low-cardinality columns in warehouse fact tables. PostgreSQL does not have persistent bitmap indexes but uses bitmap heap scans dynamically.

```sql
-- Oracle/DB2: bitmap index on low-cardinality fact columns
-- CREATE BITMAP INDEX idx_fact_sales_promo ON dw.fact_sales(promotion_key);
```

### Columnstore (SQL Server / Synapse)

```sql
-- SQL Server / Synapse: clustered columnstore index on fact table
CREATE CLUSTERED COLUMNSTORE INDEX cci_fact_sales ON dw.fact_sales;

-- Nonclustered columnstore for hybrid OLTP+analytics
-- CREATE NONCLUSTERED COLUMNSTORE INDEX ncci_sales ON dw.fact_sales (date_key, net_amount, quantity);
```

### PostgreSQL — BRIN Indexes

Block Range INdex — extremely small index for naturally ordered data (timestamps, date keys). Ideal for partitioned fact tables.

```sql
-- BRIN index on date_key (physically correlated with insert order)
CREATE INDEX idx_fact_sales_date_brin ON dw.fact_sales USING BRIN (date_key)
    WITH (pages_per_range = 32);

-- BRIN on load_date (always increasing)
CREATE INDEX idx_fact_sales_load_brin ON dw.fact_sales USING BRIN (load_date);

-- Check correlation (should be close to 1.0 or -1.0 for BRIN to be effective)
SELECT correlation FROM pg_stats
WHERE tablename = 'fact_sales' AND attname = 'date_key';
```

### Statistics and ANALYZE

```sql
-- PostgreSQL: update statistics after large loads
ANALYZE dw.fact_sales;

-- Increase statistics target for skewed columns
ALTER TABLE dw.fact_sales ALTER COLUMN store_key SET STATISTICS 1000;
ANALYZE dw.fact_sales;

-- Redshift: ANALYZE after significant loads
ANALYZE dw.fact_sales;

-- Snowflake: automatic — no manual ANALYZE needed
```

### Materialized Views

```sql
-- PostgreSQL: materialized view for common aggregation
CREATE MATERIALIZED VIEW dw.mv_daily_sales AS
SELECT
    f.date_key,
    f.store_key,
    f.product_key,
    SUM(f.net_amount)  AS total_sales,
    SUM(f.quantity)     AS total_quantity,
    COUNT(*)            AS transaction_count
FROM dw.fact_sales f
GROUP BY f.date_key, f.store_key, f.product_key;

CREATE UNIQUE INDEX idx_mv_daily_sales ON dw.mv_daily_sales (date_key, store_key, product_key);

-- Refresh after ETL load completes
REFRESH MATERIALIZED VIEW CONCURRENTLY dw.mv_daily_sales;

-- Snowflake: dynamic tables (auto-refreshing materialized views)
-- CREATE DYNAMIC TABLE dw.dt_daily_sales
--   TARGET_LAG = '1 hour'
--   WAREHOUSE = TRANSFORM_WH
-- AS SELECT date_key, store_key, SUM(net_amount) ... GROUP BY ...;
```

### Aggregate Awareness

Design aggregate tables at multiple granularities. BI tools with aggregate awareness (Looker, MicroStrategy) automatically route queries to the most appropriate aggregate.

```sql
-- Pre-aggregated: monthly sales by store (for dashboard cards)
CREATE TABLE dw.agg_monthly_store_sales AS
SELECT
    d.year_number,
    d.month_number,
    f.store_key,
    SUM(f.net_amount)  AS total_sales,
    SUM(f.quantity)     AS total_quantity,
    COUNT(*)            AS transaction_count
FROM dw.fact_sales f
JOIN dw.dim_date d ON f.date_key = d.date_key
GROUP BY d.year_number, d.month_number, f.store_key;
```

### Anti-Patterns to Avoid

- **SELECT * from fact tables** — always specify columns; wide fact scans are expensive in columnar stores
- **Cartesian joins from missing join conditions** — especially dangerous with multiple fact tables
- **Correlated subqueries in WHERE clauses on fact tables** — rewrite as JOINs or window functions
- **DISTINCT to mask duplicate loads** — fix the ETL, do not mask the symptom
- **Functions on join keys** — `WHERE YEAR(date_key) = 2026` prevents partition pruning; use `WHERE date_key BETWEEN 20260101 AND 20261231`
- **Missing statistics** — run ANALYZE after every significant load

---

## 9. Platform-Specific Guidance

### PostgreSQL (Analytical Warehouse)

PostgreSQL is viable for small-to-medium warehouses (< 500 GB). Use partitioning, BRIN indexes, parallel query, and materialized views.

```sql
-- Enable parallel query for large scans
SET max_parallel_workers_per_gather = 4;

-- Use COPY for fast bulk loads (much faster than INSERT)
COPY staging.stg_sales FROM '/data/extract/sales_20260331.csv'
    WITH (FORMAT csv, HEADER true, DELIMITER ',', NULL '');

-- Foreign Data Wrapper for federated queries
CREATE EXTENSION postgres_fdw;
CREATE SERVER source_crm FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host '10.0.1.5', port '5432', dbname 'crm');
CREATE USER MAPPING FOR etl_user SERVER source_crm
    OPTIONS (user 'readonly', password 'ReadP@ss!2024');
IMPORT FOREIGN SCHEMA public FROM SERVER source_crm INTO staging_fdw;
```

### Snowflake

```sql
-- Virtual warehouses: separate compute for ETL vs BI
CREATE WAREHOUSE etl_wh WITH WAREHOUSE_SIZE = 'LARGE' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE;
CREATE WAREHOUSE bi_wh  WITH WAREHOUSE_SIZE = 'MEDIUM' AUTO_SUSPEND = 120 AUTO_RESUME = TRUE;

-- Time Travel: query data as of a past point in time
SELECT * FROM dw.dim_customer AT(TIMESTAMP => '2026-03-30 12:00:00'::TIMESTAMP);

-- Undrop: recover accidentally dropped table
UNDROP TABLE dw.fact_sales;

-- Streams: CDC on Snowflake tables (for incremental downstream processing)
CREATE STREAM stg.stream_on_customers ON TABLE staging.stg_customers;
SELECT * FROM stg.stream_on_customers WHERE METADATA$ACTION = 'INSERT';

-- Tasks: scheduled SQL execution (ELT orchestration)
CREATE TASK etl.load_dim_customer
    WAREHOUSE = etl_wh
    SCHEDULE = 'USING CRON 0 2 * * * America/New_York'
AS
    CALL etl.sp_load_dim_customer();

-- Zero-copy cloning: instant dev/test environments
CREATE TABLE dw_dev.fact_sales CLONE dw.fact_sales;
```

### Redshift

```sql
-- Check table distribution and sort key effectiveness
SELECT "table", diststyle, sortkey1, skew_rows, pct_used
FROM svv_table_info
WHERE "schema" = 'dw'
ORDER BY pct_used DESC;

-- Identify queries that need optimization
SELECT query, elapsed, substring
FROM svl_qlog
WHERE elapsed > 10000000  -- > 10 seconds (microseconds)
ORDER BY elapsed DESC LIMIT 20;

-- Late binding views (for cross-schema, cross-database BI)
CREATE VIEW bi.v_sales WITH NO SCHEMA BINDING AS
SELECT ... FROM dw.fact_sales f JOIN dw.dim_date d ON f.date_key = d.date_key;

-- Spectrum: query S3 data directly (for cold/archived data)
CREATE EXTERNAL SCHEMA archive FROM DATA CATALOG DATABASE 'warehouse_archive'
    IAM_ROLE 'arn:aws:iam::123456789:role/RedshiftSpectrumRole';
```

### BigQuery

```sql
-- Cost control: require partition filter on large tables
ALTER TABLE `project.dw.fact_sales`
SET OPTIONS (require_partition_filter = TRUE);

-- Estimate query cost before running
-- (use dry run in bq CLI: bq query --dry_run 'SELECT ...')

-- Scheduled queries for ELT
-- Use BigQuery Scheduled Queries (UI or API) or Cloud Composer (Airflow)

-- Nested/repeated fields (avoid joins for denormalized structures)
CREATE TABLE `project.dw.orders_nested`
(
    order_id    INT64,
    order_date  DATE,
    customer    STRUCT<id INT64, name STRING, email STRING>,
    line_items  ARRAY<STRUCT<product_id INT64, quantity INT64, amount NUMERIC>>
);

-- Query nested data
SELECT
    order_id,
    customer.name,
    li.product_id,
    li.amount
FROM `project.dw.orders_nested`, UNNEST(line_items) AS li
WHERE order_date = '2026-03-31';
```

### DB2 Warehouse

```sql
-- MDC (Multi-Dimensional Clustering): see Section 7

-- Range partitioning
CREATE TABLE dw.fact_sales (
    date_key    INT NOT NULL,
    store_key   INT NOT NULL,
    net_amount  DECIMAL(12,2)
)
PARTITION BY RANGE (date_key)
(
    STARTING 20260101 ENDING 20260131,
    STARTING 20260201 ENDING 20260228,
    STARTING 20260301 ENDING 20260331
);

-- Database partitioning (distribution across partitions)
CREATE TABLE dw.fact_sales (...)
DISTRIBUTE BY HASH (customer_key);

-- Runstats (equivalent to ANALYZE)
RUNSTATS ON TABLE dw.fact_sales WITH DISTRIBUTION AND DETAILED INDEXES ALL;

-- Reorg after large deletes/updates
REORG TABLE dw.fact_sales;
```

---

