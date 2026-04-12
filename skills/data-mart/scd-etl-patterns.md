# SCDs, Conformed Dimensions, and ETL Patterns

Reference file for the `data-mart` skill. Covers slowly changing dimensions (SCD Types 1-6), conformed dimensions, and ETL/ELT loading patterns.

## 5. Slowly Changing Dimensions (SCD)

### SCD Type 0 — Retain Original

The attribute value is set once and never updated. Used for immutable facts like date of birth, original signup date.

```sql
-- No update needed. Simply skip the column during ETL updates.
-- The original value persists forever.
```

### SCD Type 1 — Overwrite

Replace the old value with the new value. No history is kept. Use for corrections (misspellings) or attributes where history is irrelevant.

```sql
-- Customer changed their name (correction)
UPDATE dim_customer
SET customer_name = 'Acme Corporation',
    load_timestamp = CURRENT_TIMESTAMP
WHERE customer_id = 'CUST-001'
  AND current_flag = 'Y';
```

**Trade-off:** Simple, but all historical facts now appear under the new value. Past reports change retroactively.

### SCD Type 2 — Add New Row

The most important SCD type. Creates a new dimension row for each change, preserving full history. The old row is expired; the new row becomes current.

```sql
-- Step 1: Expire the current row
UPDATE dim_customer
SET expiry_date  = CURRENT_DATE - INTERVAL '1 day',
    current_flag = 'N',
    load_timestamp = CURRENT_TIMESTAMP
WHERE customer_id = 'CUST-001'
  AND current_flag = 'Y';

-- Step 2: Insert new current row with new surrogate key
INSERT INTO dim_customer (
    customer_key, customer_id, customer_name, segment, region, country, city,
    postal_code, effective_date, expiry_date, current_flag, source_system, load_timestamp
) VALUES (
    nextval('seq_customer_key'), 'CUST-001', 'Acme Corporation', 'Enterprise',
    'West', 'US', 'San Francisco', '94105',
    CURRENT_DATE, '9999-12-31', 'Y', 'CRM', CURRENT_TIMESTAMP
);
```

**Point-in-time query:** What region was customer CUST-001 in on 2026-01-15?

```sql
SELECT region
FROM dim_customer
WHERE customer_id = 'CUST-001'
  AND '2026-01-15' BETWEEN effective_date AND expiry_date;
```

**Current-state query:** Get all current customers.

```sql
SELECT * FROM dim_customer WHERE current_flag = 'Y';
```

### SCD Type 3 — Add New Column

Stores only the previous value alongside the current value. Limited history (current + one prior).

```sql
ALTER TABLE dim_customer ADD COLUMN previous_region VARCHAR(50);
ALTER TABLE dim_customer ADD COLUMN region_change_date DATE;

-- When region changes:
UPDATE dim_customer
SET previous_region   = region,
    region            = 'West',
    region_change_date = CURRENT_DATE,
    load_timestamp    = CURRENT_TIMESTAMP
WHERE customer_id = 'CUST-001'
  AND current_flag = 'Y';
```

**Trade-off:** Simple to query ("compare current vs previous") but only one level of history. Rarely used alone; sometimes combined with Type 2.

### SCD Type 4 — History Table

Current values stay in the main dimension; full history is stored in a separate history table. Keeps the main dimension small for performance while preserving all history.

```sql
-- Main dimension (current only, small and fast)
CREATE TABLE dim_customer_current (
    customer_key    INT         NOT NULL PRIMARY KEY,
    customer_id     VARCHAR(20) NOT NULL UNIQUE,
    customer_name   VARCHAR(100) NOT NULL,
    segment         VARCHAR(30),
    region          VARCHAR(50),
    load_timestamp  TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- History table (all versions)
CREATE TABLE dim_customer_history (
    history_key     BIGINT      NOT NULL PRIMARY KEY,
    customer_key    INT         NOT NULL,
    customer_id     VARCHAR(20) NOT NULL,
    customer_name   VARCHAR(100) NOT NULL,
    segment         VARCHAR(30),
    region          VARCHAR(50),
    effective_date  DATE        NOT NULL,
    expiry_date     DATE        NOT NULL DEFAULT '9999-12-31',
    current_flag    CHAR(1)     NOT NULL DEFAULT 'Y',
    load_timestamp  TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ETL: on change, expire old history row, insert new history row,
--       AND update the current table
```

### SCD Type 5 — Type 4 + Type 1 Outrigger

Combines Type 4 (mini-dimension with history) plus a Type 1 current-profile key in the base dimension. Gives both current-state and historical-profile access from the fact table.

```sql
-- Fact table carries two keys:
--   customer_key      -> dim_customer (SCD Type 2, full history)
--   current_demo_key  -> dim_customer_demo (always points to current profile, Type 1 overwritten)
--   profile_demo_key  -> dim_customer_demo (profile at time of transaction, Type 2)

-- dim_customer has a Type 1 outrigger to the current mini-dimension row
ALTER TABLE dim_customer ADD COLUMN current_demo_key INT REFERENCES dim_customer_demo(demo_key);

-- ETL: when demographic changes, update current_demo_key in dim_customer (Type 1)
-- and insert new profile row in dim_customer_demo (Type 4 history)
```

### SCD Type 6 — Hybrid (1 + 2 + 3)

Combines Type 1 (overwrite), Type 2 (new row), and Type 3 (previous value column). The most expressive SCD type. Every historical row gets a "current_*" column that is Type 1 overwritten, plus the row's own as-was values.

```sql
CREATE TABLE dim_customer_scd6 (
    customer_key        INT         NOT NULL PRIMARY KEY,
    customer_id         VARCHAR(20) NOT NULL,
    customer_name       VARCHAR(100) NOT NULL,
    -- Type 2: as-was value (frozen at time of this version)
    region              VARCHAR(50) NOT NULL,
    -- Type 3: previous value
    previous_region     VARCHAR(50),
    -- Type 1: current value (overwritten on ALL rows for this customer)
    current_region      VARCHAR(50) NOT NULL,
    effective_date      DATE        NOT NULL,
    expiry_date         DATE        NOT NULL DEFAULT '9999-12-31',
    current_flag        CHAR(1)     NOT NULL DEFAULT 'Y',
    load_timestamp      TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- When region changes from 'East' to 'West':

-- Step 1: Expire current row
UPDATE dim_customer_scd6
SET expiry_date  = CURRENT_DATE - INTERVAL '1 day',
    current_flag = 'N',
    load_timestamp = CURRENT_TIMESTAMP
WHERE customer_id = 'CUST-001'
  AND current_flag = 'Y';

-- Step 2: Insert new row
INSERT INTO dim_customer_scd6 (
    customer_key, customer_id, customer_name, region,
    previous_region, current_region,
    effective_date, expiry_date, current_flag
) VALUES (
    nextval('seq_customer_key'), 'CUST-001', 'Acme Corporation', 'West',
    'East', 'West',
    CURRENT_DATE, '9999-12-31', 'Y'
);

-- Step 3: Type 1 overwrite — update current_region on ALL historical rows
UPDATE dim_customer_scd6
SET current_region = 'West',
    load_timestamp = CURRENT_TIMESTAMP
WHERE customer_id = 'CUST-001';
```

**Benefits:** Queries can access the as-was value (`region`), the previous value (`previous_region`), or the current value (`current_region`) without additional joins or subqueries.

### Choosing the Right SCD Type

| Scenario | Recommended Type |
|---|---|
| Attribute is immutable (birth date, original signup) | Type 0 |
| Data correction, no history needed | Type 1 |
| Full history required, point-in-time analysis | Type 2 |
| Only "current vs previous" comparison needed | Type 3 |
| Very large dimension, need fast current-state table | Type 4 |
| Need both current profile and historical profile on fact | Type 5 |
| Need as-was, previous, and current on every row | Type 6 |

Most data marts use Type 2 as the default for tracked attributes, Type 1 for corrections, and Type 0 for immutables.

---

## 6. Conformed Dimensions

### Shared Dimensions Across Fact Tables

Conformed dimensions are dimensions shared identically across multiple fact tables and data marts. They enable drill-across queries that combine facts from different business processes.

```sql
-- dim_date, dim_customer, dim_product are conformed dimensions
-- used by BOTH fact_sales and fact_returns

-- Drill-across: compare sales and returns by product and month
SELECT
    d.year_number,
    d.month_name,
    p.category,
    COALESCE(s.total_sales, 0)   AS total_sales,
    COALESCE(r.total_returns, 0) AS total_returns
FROM dim_date d
CROSS JOIN dim_product p
LEFT JOIN (
    SELECT date_key, product_key, SUM(net_amount) AS total_sales
    FROM fact_sales
    GROUP BY date_key, product_key
) s ON s.date_key = d.date_key AND s.product_key = p.product_key
LEFT JOIN (
    SELECT date_key, product_key, SUM(return_amount) AS total_returns
    FROM fact_returns
    GROUP BY date_key, product_key
) r ON r.date_key = d.date_key AND r.product_key = p.product_key
WHERE d.year_number = 2026 AND p.current_flag = 'Y';
```

### Rules for Conformance

1. **Same surrogate keys** — a customer_key of 42 must mean the same customer in every fact table
2. **Same attributes** — dim_customer has the same columns and values everywhere
3. **Same grain** — the dimension row represents the same entity at the same level of detail
4. **Single source of truth** — maintained in one ETL pipeline, distributed to all consuming marts
5. **Subset conformance** — a mart may use a subset of columns from a conformed dimension (e.g., `dim_date` used without fiscal columns), but the shared columns must match exactly

### Dimension Versioning

When a conformed dimension changes structure (new column, renamed attribute), version it carefully:

1. Add columns as nullable or with defaults — existing fact tables are unaffected
2. Never remove columns that existing marts depend on
3. Communicate changes through a dimension change log
4. Run regression tests on all dependent fact table queries

---

## 7. ETL/ELT Patterns

### Staging Area

Raw data lands in a staging schema before transformation. Staging tables mirror source structure, are truncated and reloaded each cycle.

```sql
CREATE SCHEMA staging;

CREATE TABLE staging.stg_sales (
    transaction_id  VARCHAR(30),
    transaction_date VARCHAR(20),  -- raw format from source
    customer_id     VARCHAR(20),
    product_id      VARCHAR(20),
    store_id        VARCHAR(10),
    quantity        VARCHAR(10),   -- still text from flat file
    unit_price      VARCHAR(15),
    discount_pct    VARCHAR(10),
    load_batch_id   INT NOT NULL,
    load_timestamp  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Truncate-and-load each ETL cycle
TRUNCATE TABLE staging.stg_sales;
-- COPY or INSERT from source
```

### Surrogate Key Lookup and Assignment

During ETL, map each natural key to its surrogate key. For SCD Type 2 dimensions, match on the natural key where `current_flag = 'Y'`.

```sql
-- Lookup existing surrogate key for a customer
SELECT customer_key
FROM dim_customer
WHERE customer_id = 'CUST-001'
  AND current_flag = 'Y';

-- If not found, assign a new surrogate key (new dimension member)
INSERT INTO dim_customer (customer_key, customer_id, customer_name, ..., effective_date, current_flag)
VALUES (nextval('seq_customer_key'), 'CUST-001', 'New Customer', ..., CURRENT_DATE, 'Y');

-- Batch lookup via JOIN (typical in ETL)
SELECT
    s.transaction_id,
    d.date_key,
    c.customer_key,
    p.product_key,
    st.store_key
FROM staging.stg_sales s
JOIN dim_date d ON d.full_date = CAST(s.transaction_date AS DATE)
JOIN dim_customer c ON c.customer_id = s.customer_id AND c.current_flag = 'Y'
JOIN dim_product p ON p.product_id = s.product_id AND p.current_flag = 'Y'
JOIN dim_store st ON st.store_id = s.store_id AND st.current_flag = 'Y';
```

### SCD Processing Pipeline

A complete ETL SCD Type 2 processing flow:

```sql
-- Step 1: Identify changed records by comparing staging to current dimension
CREATE TEMP TABLE scd_changes AS
SELECT
    s.customer_id,
    s.customer_name   AS new_name,
    s.region          AS new_region,
    d.customer_key    AS existing_key,
    d.customer_name   AS old_name,
    d.region          AS old_region
FROM staging.stg_customers s
JOIN dim_customer d
    ON s.customer_id = d.customer_id
    AND d.current_flag = 'Y'
WHERE s.customer_name != d.customer_name
   OR s.region != d.region;

-- Step 2: Expire changed rows
UPDATE dim_customer d
SET expiry_date  = CURRENT_DATE - INTERVAL '1 day',
    current_flag = 'N',
    load_timestamp = CURRENT_TIMESTAMP
FROM scd_changes c
WHERE d.customer_key = c.existing_key;

-- Step 3: Insert new versions
INSERT INTO dim_customer (
    customer_key, customer_id, customer_name, segment, region, country, city,
    postal_code, effective_date, expiry_date, current_flag, source_system, load_timestamp
)
SELECT
    nextval('seq_customer_key'),
    s.customer_id, s.customer_name, s.segment, s.region, s.country, s.city,
    s.postal_code, CURRENT_DATE, '9999-12-31', 'Y', 'CRM', CURRENT_TIMESTAMP
FROM staging.stg_customers s
JOIN scd_changes c ON s.customer_id = c.customer_id;

-- Step 4: Insert brand-new dimension members (not in dim at all)
INSERT INTO dim_customer (
    customer_key, customer_id, customer_name, segment, region, country, city,
    postal_code, effective_date, expiry_date, current_flag, source_system, load_timestamp
)
SELECT
    nextval('seq_customer_key'),
    s.customer_id, s.customer_name, s.segment, s.region, s.country, s.city,
    s.postal_code, CURRENT_DATE, '9999-12-31', 'Y', 'CRM', CURRENT_TIMESTAMP
FROM staging.stg_customers s
LEFT JOIN dim_customer d ON s.customer_id = d.customer_id
WHERE d.customer_id IS NULL;
```

### Fact Loading

```sql
-- Load fact table from staging, joining to all dimensions for surrogate key lookup
INSERT INTO fact_sales (
    sale_key, date_key, customer_key, product_key, store_key,
    transaction_id, line_number, quantity, unit_price,
    discount_amount, net_amount, cost_amount, profit_amount
)
SELECT
    nextval('seq_sale_key'),
    d.date_key,
    c.customer_key,
    p.product_key,
    st.store_key,
    s.transaction_id,
    s.line_number,
    s.quantity::INT,
    s.unit_price::DECIMAL(12,2),
    s.unit_price::DECIMAL * s.quantity::INT * s.discount_pct::DECIMAL / 100,
    s.unit_price::DECIMAL * s.quantity::INT * (1 - s.discount_pct::DECIMAL / 100),
    p.unit_cost * s.quantity::INT,
    (s.unit_price::DECIMAL * s.quantity::INT * (1 - s.discount_pct::DECIMAL / 100))
        - (p.unit_cost * s.quantity::INT)
FROM staging.stg_sales s
JOIN dim_date d      ON d.full_date = s.transaction_date::DATE
JOIN dim_customer c  ON c.customer_id = s.customer_id AND c.current_flag = 'Y'
JOIN dim_product p   ON p.product_id = s.product_id   AND p.current_flag = 'Y'
JOIN dim_store st    ON st.store_id = s.store_id       AND st.current_flag = 'Y';
```

### Incremental vs Full Load

**Full load:** Truncate and reload the target. Simple but expensive for large tables. Appropriate for small dimensions or when deletes must be captured.

**Incremental load:** Load only new and changed records using a high-water mark (timestamp, sequence number, or CDC log position).

```sql
-- High-water mark approach
-- Store last successful load timestamp
CREATE TABLE etl_control (
    table_name      VARCHAR(50) PRIMARY KEY,
    last_load_ts    TIMESTAMP NOT NULL
);

-- Extract only records modified since last load
SELECT *
FROM source_system.orders
WHERE modified_timestamp > (
    SELECT last_load_ts FROM etl_control WHERE table_name = 'orders'
);

-- After successful load, update the watermark
UPDATE etl_control
SET last_load_ts = CURRENT_TIMESTAMP
WHERE table_name = 'orders';
```

### Change Data Capture (CDC)

CDC captures row-level changes (INSERT/UPDATE/DELETE) from source database logs. More reliable than timestamp-based incremental loads because it catches deletes and avoids missed updates.

Common CDC approaches:
- **Log-based CDC:** Read database transaction logs (PostgreSQL logical replication, MySQL binlog, SQL Server CDC). Most reliable, minimal source impact.
- **Trigger-based CDC:** Database triggers write changes to a shadow table. Simple but adds overhead to every write.
- **Timestamp-based CDC:** Query `WHERE modified_ts > last_load`. Misses deletes and hard-updates that do not touch the timestamp.

Tools: Debezium (open source, Kafka-based), AWS DMS, Oracle GoldenGate, Fivetran, Airbyte.

### Error Handling

```sql
-- Orphan fact detection: facts that fail dimension lookup
INSERT INTO etl_error_log (batch_id, table_name, error_type, source_key, error_detail, created_ts)
SELECT
    @batch_id, 'fact_sales', 'ORPHAN_CUSTOMER',
    s.customer_id,
    'No matching dim_customer row for customer_id',
    CURRENT_TIMESTAMP
FROM staging.stg_sales s
LEFT JOIN dim_customer c ON c.customer_id = s.customer_id AND c.current_flag = 'Y'
WHERE c.customer_key IS NULL;

-- Option A: Reject orphans (skip loading them)
-- Option B: Point orphans to an "Unknown" dimension member (key = -1)
INSERT INTO dim_customer (customer_key, customer_id, customer_name, ..., current_flag)
VALUES (-1, 'UNKNOWN', 'Unknown Customer', ..., 'Y')
ON CONFLICT (customer_key) DO NOTHING;
```

---

## 8. Aggregation Strategies

### Pre-Aggregated Fact Tables

Store pre-computed summaries at a coarser grain to accelerate common queries. Must always have a detail-level fact table underneath (see HARD-RULE above).

```sql
-- Detail grain: one row per line item per transaction
-- fact_sales (detail)

-- Aggregate grain: one row per product per store per month
CREATE TABLE fact_sales_monthly (
    date_key        INT NOT NULL,  -- month-level date key
    product_key     INT NOT NULL,
    store_key       INT NOT NULL,
    total_quantity  BIGINT NOT NULL,
    total_revenue   DECIMAL(15,2) NOT NULL,
    total_cost      DECIMAL(15,2) NOT NULL,
    total_profit    DECIMAL(15,2) NOT NULL,
    transaction_count INT NOT NULL,
    PRIMARY KEY (date_key, product_key, store_key)
);

-- Populate from detail
INSERT INTO fact_sales_monthly
SELECT
    dm.month_date_key,
    f.product_key,
    f.store_key,
    SUM(f.quantity),
    SUM(f.net_amount),
    SUM(f.cost_amount),
    SUM(f.profit_amount),
    COUNT(DISTINCT f.transaction_id)
FROM fact_sales f
JOIN dim_date d ON f.date_key = d.date_key
JOIN dim_date_month dm ON d.year_number = dm.year_number AND d.month_number = dm.month_number
GROUP BY dm.month_date_key, f.product_key, f.store_key;
```

### Aggregate Navigation

BI tools or a query routing layer automatically redirect queries to the most appropriate aggregate table based on the dimensions and grain in the query. This is transparent to the user.

**Pattern:** Build a metadata catalog that maps each aggregate to its grain and dimensions. The query engine checks if all requested dimensions exist in an aggregate and if the requested grain is equal to or coarser than the aggregate's grain. If yes, route to the aggregate; otherwise, hit the detail table.

### Shrunken Dimensions

Aggregated fact tables use "shrunken" (rolled-up) versions of conformed dimensions that contain only the higher-level attributes relevant to the aggregate grain.

```sql
-- Full date dimension has 365+ rows per year
-- Shrunken to month grain for monthly aggregate
CREATE TABLE dim_date_month (
    month_date_key  INT         NOT NULL PRIMARY KEY,
    month_number    SMALLINT    NOT NULL,
    month_name      VARCHAR(10) NOT NULL,
    quarter_number  SMALLINT    NOT NULL,
    year_number     SMALLINT    NOT NULL,
    fiscal_quarter  SMALLINT    NOT NULL,
    fiscal_year     SMALLINT    NOT NULL
);
```

### OLAP Cubes vs Materialized Aggregates

**OLAP cubes** (SSAS, Oracle OLAP, etc.) pre-compute measures across all dimension combinations. Fast for exploratory analysis but complex to maintain and deploy.

**Materialized aggregates** (materialized views or aggregate tables) are simpler, live in the relational database, and are refreshed on schedule.

```sql
-- PostgreSQL materialized view as aggregate
CREATE MATERIALIZED VIEW mv_sales_by_category_month AS
SELECT
    d.year_number,
    d.month_number,
    p.category,
    SUM(f.net_amount)    AS total_revenue,
    SUM(f.quantity)      AS total_quantity,
    COUNT(*)             AS row_count
FROM fact_sales f
JOIN dim_date d    ON f.date_key = d.date_key
JOIN dim_product p ON f.product_key = p.product_key AND p.current_flag = 'Y'
GROUP BY d.year_number, d.month_number, p.category;

-- Create index on materialized view
CREATE INDEX idx_mv_sales_cat_month ON mv_sales_by_category_month (year_number, month_number, category);

-- Refresh (run after ETL load completes)
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_sales_by_category_month;
-- CONCURRENTLY requires a unique index on the materialized view
CREATE UNIQUE INDEX uidx_mv_sales_cat_month ON mv_sales_by_category_month (year_number, month_number, category);
```

---

