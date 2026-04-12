# Performance, Data Quality, and Aggregation

Reference file for the `data-mart` skill. Covers aggregation strategies, performance optimization, and data quality.

## 9. Performance Optimization

### Indexing Strategies

**Fact table indexes:**

```sql
-- Bitmap indexes on foreign keys (Oracle, PostgreSQL partial support via GIN)
-- Ideal for low-cardinality FK columns in large fact tables
CREATE INDEX idx_fact_sales_date     ON fact_sales (date_key);
CREATE INDEX idx_fact_sales_customer ON fact_sales (customer_key);
CREATE INDEX idx_fact_sales_product  ON fact_sales (product_key);
CREATE INDEX idx_fact_sales_store    ON fact_sales (store_key);

-- Composite index for common query patterns
CREATE INDEX idx_fact_sales_date_product ON fact_sales (date_key, product_key);
```

**Dimension table indexes:**

```sql
-- Natural key lookup (used during ETL surrogate key assignment)
CREATE INDEX idx_dim_customer_nk ON dim_customer (customer_id, current_flag);
CREATE INDEX idx_dim_product_nk  ON dim_product (product_id, current_flag);

-- SCD Type 2 date range lookup
CREATE INDEX idx_dim_customer_scd ON dim_customer (customer_id, effective_date, expiry_date);
```

### Partitioning Fact Tables by Date

Fact tables grow continuously. Partition by the date key to enable partition pruning, faster queries, and easier data lifecycle management.

```sql
-- PostgreSQL declarative partitioning by range
CREATE TABLE fact_sales (
    sale_key        BIGINT      NOT NULL,
    date_key        INT         NOT NULL,
    customer_key    INT         NOT NULL,
    product_key     INT         NOT NULL,
    store_key       INT         NOT NULL,
    transaction_id  VARCHAR(30) NOT NULL,
    line_number     SMALLINT    NOT NULL,
    quantity        INT         NOT NULL,
    unit_price      DECIMAL(12,2) NOT NULL,
    discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
    net_amount      DECIMAL(12,2) NOT NULL,
    cost_amount     DECIMAL(12,2) NOT NULL,
    profit_amount   DECIMAL(12,2) NOT NULL
) PARTITION BY RANGE (date_key);

-- Monthly partitions (date_key format: YYYYMMDD as integer)
CREATE TABLE fact_sales_202601 PARTITION OF fact_sales
    FOR VALUES FROM (20260101) TO (20260201);
CREATE TABLE fact_sales_202602 PARTITION OF fact_sales
    FOR VALUES FROM (20260201) TO (20260301);
CREATE TABLE fact_sales_202603 PARTITION OF fact_sales
    FOR VALUES FROM (20260301) TO (20260401);
-- ... generate partitions for each month

-- Drop old data by detaching/dropping partitions (much faster than DELETE)
ALTER TABLE fact_sales DETACH PARTITION fact_sales_202301;
DROP TABLE fact_sales_202301;
```

### Columnstore Indexes

For analytical workloads, columnstore indexes (SQL Server, PostgreSQL cstore_fdw/Citus columnar, ClickHouse) compress data and accelerate aggregation queries.

```sql
-- SQL Server: clustered columnstore on fact table
CREATE CLUSTERED COLUMNSTORE INDEX cci_fact_sales ON fact_sales;

-- PostgreSQL with Citus columnar access method
ALTER TABLE fact_sales SET ACCESS METHOD columnar;
```

### Materialized Views for Common Queries

See Section 8 for materialized view creation. Key maintenance practices:

```sql
-- Schedule refresh after each ETL load
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_sales_by_category_month;

-- Monitor staleness
SELECT
    schemaname, matviewname,
    pg_size_pretty(pg_total_relation_size(schemaname || '.' || matviewname)) AS size
FROM pg_matviews
WHERE schemaname = 'public';
```

### Statistics Maintenance

Query optimizers rely on accurate table statistics. After large loads, update statistics immediately.

```sql
-- PostgreSQL
ANALYZE fact_sales;
ANALYZE dim_customer;

-- Or analyze the entire database
ANALYZE;

-- Check when statistics were last updated
SELECT
    relname,
    n_live_tup,
    n_dead_tup,
    last_autoanalyze,
    last_analyze
FROM pg_stat_user_tables
WHERE schemaname = 'public'
ORDER BY n_live_tup DESC;

-- SQL Server
UPDATE STATISTICS fact_sales WITH FULLSCAN;

-- MySQL / MariaDB
ANALYZE TABLE fact_sales;
```

### Vacuum and Maintenance (PostgreSQL)

```sql
-- After large ETL loads, vacuum to reclaim dead tuple space
VACUUM (VERBOSE, ANALYZE) fact_sales;

-- For very large tables, consider VACUUM FULL during maintenance windows
-- (locks the table, rewrites it entirely)
VACUUM FULL fact_sales;

-- Autovacuum tuning for large fact tables
ALTER TABLE fact_sales SET (
    autovacuum_vacuum_scale_factor = 0.01,    -- trigger at 1% dead tuples instead of default 20%
    autovacuum_analyze_scale_factor = 0.005
);
```

---

## 10. Data Quality

### Referential Integrity Checks

Even if foreign keys are enforced at the database level, run explicit checks during ETL to catch issues before they reach the fact table.

```sql
-- Check for orphan facts: facts with no matching dimension
SELECT 'ORPHAN_CUSTOMER' AS check_name, COUNT(*) AS violations
FROM fact_sales f
LEFT JOIN dim_customer c ON f.customer_key = c.customer_key
WHERE c.customer_key IS NULL

UNION ALL

SELECT 'ORPHAN_PRODUCT', COUNT(*)
FROM fact_sales f
LEFT JOIN dim_product p ON f.product_key = p.product_key
WHERE p.product_key IS NULL

UNION ALL

SELECT 'ORPHAN_DATE', COUNT(*)
FROM fact_sales f
LEFT JOIN dim_date d ON f.date_key = d.date_key
WHERE d.date_key IS NULL

UNION ALL

SELECT 'ORPHAN_STORE', COUNT(*)
FROM fact_sales f
LEFT JOIN dim_store s ON f.store_key = s.store_key
WHERE s.store_key IS NULL;
```

### Dimension Completeness

```sql
-- Check that dim_date has no gaps in the date range
WITH date_range AS (
    SELECT generate_series(
        (SELECT MIN(full_date) FROM dim_date),
        (SELECT MAX(full_date) FROM dim_date),
        '1 day'::interval
    )::date AS expected_date
)
SELECT expected_date AS missing_date
FROM date_range dr
LEFT JOIN dim_date d ON dr.expected_date = d.full_date
WHERE d.date_key IS NULL;

-- Check SCD Type 2 integrity: no overlapping date ranges for the same entity
SELECT customer_id, COUNT(*) AS overlaps
FROM dim_customer a
JOIN dim_customer b
    ON a.customer_id = b.customer_id
    AND a.customer_key != b.customer_key
    AND a.effective_date <= b.expiry_date
    AND a.expiry_date >= b.effective_date
GROUP BY customer_id
HAVING COUNT(*) > 0;

-- Check that exactly one row is current per entity
SELECT customer_id, COUNT(*) AS current_count
FROM dim_customer
WHERE current_flag = 'Y'
GROUP BY customer_id
HAVING COUNT(*) != 1;
```

### Null Handling

```sql
-- Identify null measures in fact tables
SELECT
    COUNT(*) AS total_rows,
    COUNT(*) FILTER (WHERE quantity IS NULL) AS null_quantity,
    COUNT(*) FILTER (WHERE net_amount IS NULL) AS null_net_amount,
    COUNT(*) FILTER (WHERE cost_amount IS NULL) AS null_cost_amount
FROM fact_sales;

-- Identify null foreign keys (should be zero if Unknown member is used)
SELECT
    COUNT(*) FILTER (WHERE customer_key IS NULL) AS null_customer,
    COUNT(*) FILTER (WHERE product_key IS NULL) AS null_product,
    COUNT(*) FILTER (WHERE date_key IS NULL) AS null_date
FROM fact_sales;
```

**Best practice:** Never allow NULL foreign keys in fact tables. Map unknown/missing values to a dedicated "Unknown" dimension member (surrogate key = -1) so that every fact row joins cleanly to every dimension.

### Audit Columns

Add metadata columns to every table in the data mart for traceability and debugging.

```sql
-- Standard audit columns for dimension tables
load_timestamp  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
source_system   VARCHAR(20),
batch_id        INT

-- Standard audit columns for fact tables
load_timestamp  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
batch_id        INT NOT NULL,
source_file     VARCHAR(200)  -- for file-based loads
```

### Data Quality Dashboard Queries

```sql
-- Row count trends (detect anomalous loads)
SELECT
    batch_id,
    COUNT(*) AS rows_loaded,
    MIN(load_timestamp) AS load_start,
    MAX(load_timestamp) AS load_end
FROM fact_sales
GROUP BY batch_id
ORDER BY batch_id DESC
LIMIT 30;

-- Measure reasonability checks
SELECT
    'NEGATIVE_QUANTITY' AS check_name,
    COUNT(*) AS violations
FROM fact_sales WHERE quantity < 0
UNION ALL
SELECT 'ZERO_NET_AMOUNT', COUNT(*)
FROM fact_sales WHERE net_amount = 0 AND quantity > 0
UNION ALL
SELECT 'FUTURE_DATE', COUNT(*)
FROM fact_sales f
JOIN dim_date d ON f.date_key = d.date_key
WHERE d.full_date > CURRENT_DATE;

-- Bridge table weighting validation
SELECT account_key, SUM(weighting_factor) AS total_weight
FROM bridge_account_holder
GROUP BY account_key
HAVING ABS(SUM(weighting_factor) - 1.0) > 0.001;
```

---

## Related Skills

| Domain | Skill |
|---|---|
| PostgreSQL, MySQL, Redis administration | `rhel-databases`, `ubuntu-databases` |
| Python data engineering (SQLAlchemy, Alembic) | `python-data-engineer` |
| Enterprise database connectors (DB2, Oracle, SQL Server) | `python-enterprise-connectors` |
| Large file analysis (CSV, logs) | `large-file-analysis` |
| Performance profiling and optimization | `performance` |
