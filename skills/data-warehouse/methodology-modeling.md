# Methodology, Architecture, and Dimensional Modeling

Reference file for the `data-warehouse` skill. Covers Kimball vs Inmon methodology, architecture patterns, dimensional modeling (star/snowflake schemas, fact/dimension tables).

## 1. Methodology

### Kimball — Bottom-Up, Dimensional, Bus Architecture

Build subject-area data marts first, integrated through conformed dimensions and the enterprise bus matrix. Business value delivered early and iteratively.

**Core principles:** dimensional modeling, conformed dimensions, bus architecture, drill-across queries.

```
Bus Matrix Example:
                    | Date | Customer | Product | Store | Employee | Promotion |
--------------------+------+----------+---------+-------+----------+-----------+
Sales Fact          |  X   |    X     |    X    |   X   |          |     X     |
Inventory Fact      |  X   |          |    X    |   X   |          |           |
Returns Fact        |  X   |    X     |    X    |   X   |    X     |           |
HR Attendance Fact  |  X   |          |         |       |    X     |           |
```

**When to choose Kimball:** business needs fast delivery, subject areas are well-understood, reporting/analytics is the primary use case, team has BI/reporting skills.

### Inmon — Top-Down, Normalized, EDW-First

Build a centralized, subject-oriented, 3NF enterprise data warehouse first. Data marts are derived views downstream. Single source of truth, but longer initial delivery.

**Core principles:** subject orientation, integration, non-volatility, time variance. The EDW is normalized (3NF); data marts may be dimensional.

```
Architecture:
Source Systems → ETL → [3NF Enterprise Data Warehouse] → ETL → Dimensional Data Marts → BI
```

**When to choose Inmon:** multiple overlapping subject areas, regulatory compliance requires a single auditable source, complex cross-functional reporting, data governance is paramount.

### Data Vault 2.0

Hub-and-spoke modeling for agility, auditability, and parallel loading. Raw vault captures source data without transformation; business vault applies business rules.

**Core principles:** insert-only (no updates to raw vault), hash keys for integration, parallel loading, full auditability, separation of business rules from raw data.

**When to choose Data Vault:** sources change frequently, auditability/compliance is critical, multiple teams load in parallel, hybrid of Kimball and Inmon needed.

### Hybrid Approaches

Most real-world warehouses blend methodologies:

| Layer | Methodology | Purpose |
|---|---|---|
| Raw / Landing | Data Vault or flat staging | Capture everything, audit trail |
| Integration / Core | Data Vault or 3NF | Single version of truth |
| Presentation / Marts | Kimball star schemas | Fast, intuitive BI queries |

---

## 2. Architecture

### Reference Architecture

```
┌─────────────┐    ┌──────────────┐    ┌─────────────────┐    ┌──────────────────┐    ┌──────────┐
│   Sources   │───▶│   Staging    │───▶│  Integration /  │───▶│   Presentation   │───▶│    BI    │
│             │    │   Layer      │    │  Core Layer     │    │   Layer (Marts)  │    │  Tools   │
│ - OLTP DBs  │    │              │    │                 │    │                  │    │          │
│ - Files/CSV │    │ - Raw copy   │    │ - 3NF / DV Hub  │    │ - Star schemas   │    │ - Looker │
│ - APIs      │    │ - No xforms  │    │ - Business keys │    │ - Aggregates     │    │ - PBI    │
│ - Streams   │    │ - Truncate/  │    │ - History (SCD) │    │ - Materialized   │    │ - Tableau│
│ - CDC logs  │    │   reload     │    │ - Conformed dims│    │   views          │    │          │
└─────────────┘    └──────────────┘    └─────────────────┘    └──────────────────┘    └──────────┘
                        ▲                      ▲                       ▲
                        │                      │                       │
                   ┌─────────────────────────────────────────────────────┐
                   │              Metadata / Lineage / Quality          │
                   │     (load audit, row counts, job status, lineage)  │
                   └─────────────────────────────────────────────────────┘
```

### ODS (Operational Data Store)

An ODS is a near-real-time, current-state, integrated view of operational data. It sits between source systems and the warehouse.

**Use when:** operational reporting needs < 15 min latency, customer service screens need integrated cross-system view, CDC feeds need a landing zone before warehouse batch loads.

**Do not conflate ODS with the warehouse** — the ODS is current-state only, the warehouse is historical.

### ETL vs ELT

| Aspect | ETL (Extract-Transform-Load) | ELT (Extract-Load-Transform) |
|---|---|---|
| Transform engine | External (Informatica, SSIS, Talend) | Warehouse itself (SQL, dbt) |
| Best for | On-prem, row-based DBs, complex transforms | Cloud warehouses with MPP compute |
| Scaling | Scale the ETL server | Scale the warehouse cluster |
| Cost model | License-based | Compute-time billing (Snowflake, BQ) |
| Data availability | After transform completes | Raw available immediately |

**Modern pattern (ELT with dbt):**
```
Source → Extract (Fivetran/Airbyte/custom) → Load to staging → dbt models → Presentation
```

### Metadata-Driven Architecture

Central metadata catalog drives pipeline behavior — source definitions, column mappings, load frequencies, SCD types, and quality rules stored as configuration, not code.

```sql
-- Example: metadata table driving ETL behavior
CREATE TABLE meta.table_config (
    table_id          SERIAL PRIMARY KEY,
    source_schema     VARCHAR(128) NOT NULL,
    source_table      VARCHAR(128) NOT NULL,
    target_schema     VARCHAR(128) NOT NULL,
    target_table      VARCHAR(128) NOT NULL,
    load_type         VARCHAR(20)  NOT NULL,  -- 'full', 'incremental', 'cdc'
    watermark_column  VARCHAR(128),           -- for incremental loads
    scd_type          SMALLINT DEFAULT 1,     -- 0,1,2,3,6
    is_active         BOOLEAN DEFAULT TRUE,
    load_frequency    VARCHAR(20) DEFAULT 'daily',
    last_loaded_at    TIMESTAMP,
    last_watermark    VARCHAR(256)
);
```

### Data Lineage

Track column-level lineage from source to presentation. Critical for impact analysis, regulatory reporting, and debugging.

```sql
-- Lineage tracking table
CREATE TABLE meta.column_lineage (
    lineage_id        SERIAL PRIMARY KEY,
    target_schema     VARCHAR(128),
    target_table      VARCHAR(128),
    target_column     VARCHAR(128),
    source_schema     VARCHAR(128),
    source_table      VARCHAR(128),
    source_column     VARCHAR(128),
    transformation    TEXT,           -- SQL expression or description
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 3. Dimensional Modeling

### Star Schema

Central fact table surrounded by denormalized dimension tables. Optimized for query performance and user comprehension.

```sql
-- Fact table: one row per sales transaction line item (grain = line item)
CREATE TABLE dw.fact_sales (
    sale_key            BIGINT GENERATED ALWAYS AS IDENTITY,
    date_key            INT         NOT NULL,  -- FK to dim_date
    customer_key        INT         NOT NULL,  -- FK to dim_customer (surrogate)
    product_key         INT         NOT NULL,  -- FK to dim_product (surrogate)
    store_key           INT         NOT NULL,  -- FK to dim_store (surrogate)
    promotion_key       INT         NOT NULL,  -- FK to dim_promotion (surrogate)
    -- Degenerate dimension (no separate table)
    order_number        VARCHAR(30) NOT NULL,
    -- Facts (measures)
    quantity            INT         NOT NULL,
    unit_price          NUMERIC(12,2) NOT NULL,
    discount_amount     NUMERIC(12,2) DEFAULT 0,
    net_amount          NUMERIC(12,2) NOT NULL,
    tax_amount          NUMERIC(12,2) NOT NULL,
    gross_amount        NUMERIC(12,2) NOT NULL,
    cost_amount         NUMERIC(12,2) NOT NULL,
    -- ETL audit
    load_date           TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_system       VARCHAR(30) NOT NULL,
    batch_id            BIGINT      NOT NULL,
    PRIMARY KEY (sale_key)
);

-- Date dimension (no surrogate needed — use YYYYMMDD integer key)
CREATE TABLE dw.dim_date (
    date_key            INT         PRIMARY KEY,  -- 20260331
    full_date           DATE        NOT NULL,
    day_of_week         SMALLINT    NOT NULL,      -- 1=Mon, 7=Sun
    day_name            VARCHAR(10) NOT NULL,
    day_of_month        SMALLINT    NOT NULL,
    day_of_year         SMALLINT    NOT NULL,
    week_of_year        SMALLINT    NOT NULL,
    iso_week            SMALLINT    NOT NULL,
    month_number        SMALLINT    NOT NULL,
    month_name          VARCHAR(10) NOT NULL,
    quarter_number      SMALLINT    NOT NULL,
    quarter_name        VARCHAR(6)  NOT NULL,      -- 'Q1-26'
    year_number         SMALLINT    NOT NULL,
    fiscal_month        SMALLINT,
    fiscal_quarter      SMALLINT,
    fiscal_year         SMALLINT,
    is_weekend          BOOLEAN     NOT NULL,
    is_holiday          BOOLEAN     DEFAULT FALSE,
    holiday_name        VARCHAR(50)
);

-- Customer dimension (SCD Type 2)
CREATE TABLE dw.dim_customer (
    customer_key        INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id         VARCHAR(30) NOT NULL,      -- business/natural key
    customer_name       VARCHAR(200),
    email               VARCHAR(200),
    segment             VARCHAR(50),
    city                VARCHAR(100),
    state_province      VARCHAR(100),
    country             VARCHAR(100),
    -- SCD Type 2 tracking
    effective_date      DATE        NOT NULL,
    expiry_date         DATE        NOT NULL DEFAULT '9999-12-31',
    is_current          BOOLEAN     NOT NULL DEFAULT TRUE,
    row_hash            BYTEA,                     -- for change detection
    -- ETL audit
    load_date           TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_system       VARCHAR(30) NOT NULL
);
```

### Snowflake Schema

Normalized dimensions — reduces storage but adds joins. Use sparingly when dimension tables are very large (> 10M rows) and share sub-dimensions.

```sql
-- Snowflaked: product → brand → manufacturer
CREATE TABLE dw.dim_manufacturer (
    manufacturer_key    INT PRIMARY KEY,
    manufacturer_name   VARCHAR(200),
    country             VARCHAR(100)
);

CREATE TABLE dw.dim_brand (
    brand_key           INT PRIMARY KEY,
    brand_name          VARCHAR(200),
    manufacturer_key    INT REFERENCES dw.dim_manufacturer
);

CREATE TABLE dw.dim_product (
    product_key         INT PRIMARY KEY,
    product_id          VARCHAR(30),
    product_name        VARCHAR(300),
    brand_key           INT REFERENCES dw.dim_brand,
    category            VARCHAR(100),
    subcategory         VARCHAR(100)
);
```

### Fact Table Types

| Type | Description | Example |
|---|---|---|
| **Transaction** | One row per event at atomic grain | `fact_sales` (one row per line item) |
| **Periodic snapshot** | One row per entity per period | `fact_monthly_balance` (one row per account per month) |
| **Accumulating snapshot** | One row per process instance, updated as milestones occur | `fact_order_fulfillment` (one row per order, dates filled in) |
| **Factless fact** | Records events with no numeric measures | `fact_student_attendance` (student was present) |

```sql
-- Accumulating snapshot: order fulfillment pipeline
CREATE TABLE dw.fact_order_fulfillment (
    order_key               BIGINT PRIMARY KEY,
    order_date_key          INT NOT NULL,
    payment_date_key        INT,           -- NULL until paid
    ship_date_key           INT,           -- NULL until shipped
    delivery_date_key       INT,           -- NULL until delivered
    customer_key            INT NOT NULL,
    product_key             INT NOT NULL,
    order_amount            NUMERIC(12,2),
    days_to_payment         INT,           -- calculated lag
    days_to_ship            INT,
    days_to_delivery        INT,
    current_status          VARCHAR(30),
    load_date               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Periodic snapshot: monthly account balance
CREATE TABLE dw.fact_monthly_balance (
    month_key               INT NOT NULL,         -- YYYYMM
    account_key             INT NOT NULL,
    opening_balance         NUMERIC(15,2),
    total_credits           NUMERIC(15,2),
    total_debits            NUMERIC(15,2),
    closing_balance         NUMERIC(15,2),
    transaction_count       INT,
    PRIMARY KEY (month_key, account_key)
);
```

### Dimension Types

**Conformed dimension:** shared across multiple fact tables with consistent keys, attributes, and values. The date dimension is the most common conformed dimension.

**Junk dimension:** low-cardinality flags and indicators combined into a single dimension to avoid cluttering the fact table.

```sql
-- Junk dimension: order flags
CREATE TABLE dw.dim_order_flags (
    order_flag_key      INT PRIMARY KEY,
    is_gift_wrapped     BOOLEAN,
    is_rush_delivery    BOOLEAN,
    payment_method      VARCHAR(20),   -- 'credit','debit','cash','wire'
    channel             VARCHAR(20)    -- 'web','store','phone','mobile'
);
-- Pre-populate all combinations (small cardinality)
-- Fact table carries order_flag_key instead of 4 separate columns
```

**Degenerate dimension:** dimension attribute stored directly on the fact table (no separate dimension table). Typically transaction/order numbers.

**Role-playing dimension:** same physical dimension referenced multiple times by different foreign keys.

```sql
-- Role-playing: dim_date used as order_date, ship_date, delivery_date
SELECT
    f.order_amount,
    od.full_date AS order_date,
    sd.full_date AS ship_date,
    dd.full_date AS delivery_date
FROM dw.fact_order_fulfillment f
JOIN dw.dim_date od ON f.order_date_key    = od.date_key
JOIN dw.dim_date sd ON f.ship_date_key     = sd.date_key
JOIN dw.dim_date dd ON f.delivery_date_key = dd.date_key;
```

**Mini-dimension:** frequently analyzed, rapidly changing attributes carved out of a large dimension to avoid SCD bloat. Common for demographic bands on a customer dimension.

```sql
-- Mini-dimension: customer demographics (changes often, avoid SCD2 bloat)
CREATE TABLE dw.dim_customer_demographics (
    demo_key            INT PRIMARY KEY,
    age_band            VARCHAR(20),    -- '18-25','26-35','36-45','46-55','56+'
    income_band         VARCHAR(20),    -- 'Low','Medium','High','Ultra-High'
    credit_score_band   VARCHAR(20)     -- 'Poor','Fair','Good','Excellent'
);
-- Fact table carries both customer_key and demo_key
```

---

## 4. Data Vault 2.0

### Core Components

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│   Hub    │────▶│   Link   │◀────│   Hub    │
│ Customer │     │ Sale     │     │ Product  │
└────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │                │
┌────▼─────┐     ┌────▼─────┐     ┌────▼─────┐
│Satellite │     │Satellite │     │Satellite │
│ Cust Dtl │     │ Sale Dtl │     │ Prod Dtl │
└──────────┘     └──────────┘     └──────────┘
```

### Hubs — Business Keys

```sql
-- Hub: unique business entities, insert-only
CREATE TABLE rv.hub_customer (
    hub_customer_hk     BYTEA       PRIMARY KEY,  -- hash of business key
    customer_id         VARCHAR(30) NOT NULL,      -- business key
    load_date           TIMESTAMP   NOT NULL,
    record_source       VARCHAR(50) NOT NULL
);

CREATE TABLE rv.hub_product (
    hub_product_hk      BYTEA       PRIMARY KEY,
    product_id          VARCHAR(30) NOT NULL,
    load_date           TIMESTAMP   NOT NULL,
    record_source       VARCHAR(50) NOT NULL
);
```

### Links — Relationships

```sql
-- Link: relationship between two (or more) hubs
CREATE TABLE rv.link_sale (
    link_sale_hk        BYTEA       PRIMARY KEY,  -- hash of all parent HKs
    hub_customer_hk     BYTEA       NOT NULL,
    hub_product_hk      BYTEA       NOT NULL,
    hub_store_hk        BYTEA       NOT NULL,
    sale_date           DATE        NOT NULL,      -- degenerate or FK to hub_date
    order_number        VARCHAR(30),               -- degenerate
    load_date           TIMESTAMP   NOT NULL,
    record_source       VARCHAR(50) NOT NULL
);
```

### Satellites — Descriptive Attributes

```sql
-- Satellite: versioned descriptive data for a hub (insert-only, one row per change)
CREATE TABLE rv.sat_customer_details (
    hub_customer_hk     BYTEA       NOT NULL,
    load_date           TIMESTAMP   NOT NULL,
    load_end_date       TIMESTAMP   DEFAULT '9999-12-31 00:00:00',
    record_source       VARCHAR(50) NOT NULL,
    hash_diff           BYTEA       NOT NULL,      -- hash of all descriptive columns
    customer_name       VARCHAR(200),
    email               VARCHAR(200),
    segment             VARCHAR(50),
    city                VARCHAR(100),
    state_province      VARCHAR(100),
    country             VARCHAR(100),
    PRIMARY KEY (hub_customer_hk, load_date)
);

-- Satellite on a link: measures/context for the relationship
CREATE TABLE rv.sat_sale_details (
    link_sale_hk        BYTEA       NOT NULL,
    load_date           TIMESTAMP   NOT NULL,
    load_end_date       TIMESTAMP   DEFAULT '9999-12-31 00:00:00',
    record_source       VARCHAR(50) NOT NULL,
    hash_diff           BYTEA       NOT NULL,
    quantity            INT,
    unit_price          NUMERIC(12,2),
    discount_amount     NUMERIC(12,2),
    net_amount          NUMERIC(12,2),
    PRIMARY KEY (link_sale_hk, load_date)
);
```

### Hash Key Generation

```sql
-- PostgreSQL: MD5 hash for hub key (use SHA-256 for higher cardinality / collision safety)
INSERT INTO rv.hub_customer (hub_customer_hk, customer_id, load_date, record_source)
SELECT
    md5(UPPER(TRIM(customer_id)))::BYTEA,
    customer_id,
    CURRENT_TIMESTAMP,
    'CRM_SYSTEM'
FROM staging.stg_customers s
WHERE NOT EXISTS (
    SELECT 1 FROM rv.hub_customer h
    WHERE h.hub_customer_hk = md5(UPPER(TRIM(s.customer_id)))::BYTEA
);

-- Snowflake: use MD5_BINARY or SHA2_BINARY
-- INSERT INTO rv.hub_customer (hub_customer_hk, customer_id, load_date, record_source)
-- SELECT MD5_BINARY(UPPER(TRIM(customer_id))), customer_id, CURRENT_TIMESTAMP(), 'CRM'
-- FROM staging.stg_customers s
-- WHERE NOT EXISTS (SELECT 1 FROM rv.hub_customer h WHERE h.hub_customer_hk = MD5_BINARY(UPPER(TRIM(s.customer_id))));
```

### PIT (Point-In-Time) Tables

PIT tables pre-join satellite effective dates for a hub, eliminating expensive temporal joins at query time.

```sql
-- PIT table: pre-computed satellite join dates for each hub member at each snapshot
CREATE TABLE bv.pit_customer (
    hub_customer_hk         BYTEA       NOT NULL,
    snapshot_date           TIMESTAMP   NOT NULL,
    sat_cust_details_ldts   TIMESTAMP,   -- load_date of active sat_customer_details row
    sat_cust_finance_ldts   TIMESTAMP,   -- load_date of active sat_customer_finance row
    PRIMARY KEY (hub_customer_hk, snapshot_date)
);

-- Populate PIT for a given snapshot date
INSERT INTO bv.pit_customer
SELECT
    h.hub_customer_hk,
    '2026-03-31 00:00:00'::TIMESTAMP AS snapshot_date,
    (SELECT MAX(sd.load_date) FROM rv.sat_customer_details sd
     WHERE sd.hub_customer_hk = h.hub_customer_hk
       AND sd.load_date <= '2026-03-31 00:00:00') AS sat_cust_details_ldts,
    (SELECT MAX(sf.load_date) FROM rv.sat_customer_finance sf
     WHERE sf.hub_customer_hk = h.hub_customer_hk
       AND sf.load_date <= '2026-03-31 00:00:00') AS sat_cust_finance_ldts
FROM rv.hub_customer h;
```

### Bridge Tables

Bridge tables resolve many-to-many link structures into a queryable format for BI tools.

### Raw Vault vs Business Vault

| Aspect | Raw Vault | Business Vault |
|---|---|---|
| Transformations | None — mirror source exactly | Business rules, derived calculations |
| Updates | Insert-only, never modify | Insert-only, but may recompute |
| Purpose | Audit trail, source of record | Business-ready integrated data |
| Examples | `rv.hub_*`, `rv.sat_*`, `rv.link_*` | `bv.pit_*`, `bv.bridge_*`, derived sats |

---

