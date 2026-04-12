# Fundamentals, Dimensional Modeling, and Fact Tables

Reference file for the `data-mart` skill. Covers data mart fundamentals, dimensional modeling (star/snowflake), and fact table design.

## 1. Data Mart Fundamentals

### Data Mart vs Data Warehouse

| Aspect | Data Warehouse | Data Mart |
|---|---|---|
| Scope | Enterprise-wide, all subject areas | Single subject area or department |
| Build time | Months to years | Weeks to months |
| Data sources | Many operational systems | Fewer, focused sources |
| Users | Analysts, data scientists, enterprise | Department analysts, business users |
| Schema | May include 3NF staging + dimensional | Typically pure dimensional (star/snowflake) |

### Dependent vs Independent Data Marts

**Dependent data mart:** Sourced from the enterprise data warehouse. Data flows from operational systems into the DW, then into the mart. Ensures consistency because the DW acts as a single source of truth.

**Independent data mart:** Sourced directly from operational systems, bypassing the DW. Faster to build but risks inconsistency when multiple independent marts define "customer" or "revenue" differently.

**Recommendation:** Prefer dependent marts or, at minimum, use conformed dimensions from a shared dimension bus to prevent silo inconsistencies.

### Bus Architecture (Kimball)

The enterprise data warehouse bus architecture maps business processes (rows) to conformed dimensions (columns). Each intersection where a process uses a dimension gets a checkmark. Data marts are implemented one business process at a time, sharing conformed dimensions to allow drill-across queries.

```
                    Date  Customer  Product  Store  Employee  Promotion
Retail Sales         X       X        X       X       X         X
Inventory            X                X       X
Purchasing           X                X
Customer Service     X       X        X       X       X
```

Each row is a candidate data mart (fact table). Shared dimensions (Date, Product, Customer) are conformed — identical structure and content across all marts.

### When to Build a Data Mart

Build a data mart when:
- A department needs fast, reliable analytical queries against a defined subject area
- Operational system queries are too slow or complex for business users
- Reporting requires joining data from multiple sources into a single coherent model
- You need historical tracking (SCD) that the operational system does not maintain
- Pre-aggregated summaries would eliminate redundant heavy queries

Do not build a data mart when:
- A single report or dashboard can query the operational system directly
- Data volumes are small and a materialized view would suffice
- There is no agreed grain or business process to model

---

## 2. Dimensional Modeling

### Star Schema

The star schema has a central fact table surrounded by denormalized dimension tables. Each dimension connects to the fact via a single foreign key. Simple, fast, and the most common data mart pattern.

```sql
-- Star schema: Sales data mart
CREATE TABLE dim_date (
    date_key        INT         NOT NULL PRIMARY KEY,
    full_date       DATE        NOT NULL,
    day_of_week     VARCHAR(10) NOT NULL,
    day_of_month    SMALLINT    NOT NULL,
    month_number    SMALLINT    NOT NULL,
    month_name      VARCHAR(10) NOT NULL,
    quarter_number  SMALLINT    NOT NULL,
    quarter_name    VARCHAR(6)  NOT NULL,
    year_number     SMALLINT    NOT NULL,
    fiscal_quarter  SMALLINT    NOT NULL,
    fiscal_year     SMALLINT    NOT NULL,
    is_weekend      CHAR(1)     NOT NULL DEFAULT 'N',
    is_holiday      CHAR(1)     NOT NULL DEFAULT 'N',
    holiday_name    VARCHAR(50)
);

CREATE TABLE dim_customer (
    customer_key    INT         NOT NULL PRIMARY KEY,
    customer_id     VARCHAR(20) NOT NULL,  -- natural key
    customer_name   VARCHAR(100) NOT NULL,
    segment         VARCHAR(30),
    region          VARCHAR(50),
    country         VARCHAR(50),
    city            VARCHAR(50),
    postal_code     VARCHAR(15),
    effective_date  DATE        NOT NULL,
    expiry_date     DATE        NOT NULL DEFAULT '9999-12-31',
    current_flag    CHAR(1)     NOT NULL DEFAULT 'Y',
    source_system   VARCHAR(20),
    load_timestamp  TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE dim_product (
    product_key     INT         NOT NULL PRIMARY KEY,
    product_id      VARCHAR(20) NOT NULL,  -- natural key
    product_name    VARCHAR(100) NOT NULL,
    category        VARCHAR(50),
    subcategory     VARCHAR(50),
    brand           VARCHAR(50),
    unit_cost       DECIMAL(12,2),
    unit_price      DECIMAL(12,2),
    effective_date  DATE        NOT NULL,
    expiry_date     DATE        NOT NULL DEFAULT '9999-12-31',
    current_flag    CHAR(1)     NOT NULL DEFAULT 'Y',
    source_system   VARCHAR(20),
    load_timestamp  TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE dim_store (
    store_key       INT         NOT NULL PRIMARY KEY,
    store_id        VARCHAR(10) NOT NULL,
    store_name      VARCHAR(100) NOT NULL,
    store_type      VARCHAR(20),
    district        VARCHAR(50),
    region          VARCHAR(50),
    state           VARCHAR(50),
    country         VARCHAR(50),
    open_date       DATE,
    close_date      DATE,
    current_flag    CHAR(1)     NOT NULL DEFAULT 'Y',
    source_system   VARCHAR(20),
    load_timestamp  TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Grain: one row per line item per transaction per day
CREATE TABLE fact_sales (
    sale_key        BIGINT      NOT NULL PRIMARY KEY,
    date_key        INT         NOT NULL REFERENCES dim_date(date_key),
    customer_key    INT         NOT NULL REFERENCES dim_customer(customer_key),
    product_key     INT         NOT NULL REFERENCES dim_product(product_key),
    store_key       INT         NOT NULL REFERENCES dim_store(store_key),
    transaction_id  VARCHAR(30) NOT NULL,  -- degenerate dimension
    line_number     SMALLINT    NOT NULL,
    quantity        INT         NOT NULL,
    unit_price      DECIMAL(12,2) NOT NULL,
    discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
    net_amount      DECIMAL(12,2) NOT NULL,
    cost_amount     DECIMAL(12,2) NOT NULL,
    profit_amount   DECIMAL(12,2) NOT NULL
);
```

### Snowflake Schema

Normalizes dimension tables into sub-dimensions. Saves storage but adds joins, complicating queries and sometimes hurting performance.

```sql
-- Snowflake: product dimension normalized
CREATE TABLE dim_category (
    category_key    INT         NOT NULL PRIMARY KEY,
    category_name   VARCHAR(50) NOT NULL,
    department      VARCHAR(50)
);

CREATE TABLE dim_product_snowflake (
    product_key     INT         NOT NULL PRIMARY KEY,
    product_id      VARCHAR(20) NOT NULL,
    product_name    VARCHAR(100) NOT NULL,
    category_key    INT         NOT NULL REFERENCES dim_category(category_key),
    brand           VARCHAR(50),
    unit_cost       DECIMAL(12,2),
    unit_price      DECIMAL(12,2)
);
```

**When to snowflake:** Only when a sub-dimension is very large, shared across multiple dimensions, or has its own SCD lifecycle. Prefer star schema for simplicity and query performance.

### Fact Table Types

**Transaction fact:** One row per event at the atomic grain. Most common. Example: `fact_sales` (one row per line item).

**Periodic snapshot fact:** One row per entity per time period, capturing cumulative or level metrics at regular intervals. Example: `fact_account_monthly` (one row per account per month).

```sql
-- Grain: one row per account per month
CREATE TABLE fact_account_monthly (
    date_key            INT         NOT NULL REFERENCES dim_date(date_key),
    account_key         INT         NOT NULL REFERENCES dim_account(account_key),
    balance_amount      DECIMAL(15,2) NOT NULL,  -- semi-additive (don't sum across time)
    transaction_count   INT         NOT NULL,     -- additive
    deposits_amount     DECIMAL(15,2) NOT NULL,   -- additive
    withdrawals_amount  DECIMAL(15,2) NOT NULL,   -- additive
    PRIMARY KEY (date_key, account_key)
);
```

**Accumulating snapshot fact:** One row per entity lifecycle, updated as the entity progresses through milestones. Example: `fact_order_fulfillment` with multiple date keys.

```sql
-- Grain: one row per order, updated as milestones are reached
CREATE TABLE fact_order_fulfillment (
    order_key           BIGINT  NOT NULL PRIMARY KEY,
    order_date_key      INT     REFERENCES dim_date(date_key),
    payment_date_key    INT     REFERENCES dim_date(date_key),
    ship_date_key       INT     REFERENCES dim_date(date_key),
    delivery_date_key   INT     REFERENCES dim_date(date_key),
    customer_key        INT     NOT NULL REFERENCES dim_customer(customer_key),
    product_key         INT     NOT NULL REFERENCES dim_product(product_key),
    order_amount        DECIMAL(12,2) NOT NULL,
    days_to_payment     INT,
    days_to_ship        INT,
    days_to_delivery    INT
);
```

**Factless fact:** Records events that have no measures — just the relationship between dimensions. Example: student attendance, promotion coverage, event participation.

```sql
-- Grain: one row per student per class per day (attendance tracking)
CREATE TABLE fact_attendance (
    date_key        INT NOT NULL REFERENCES dim_date(date_key),
    student_key     INT NOT NULL REFERENCES dim_student(student_key),
    class_key       INT NOT NULL REFERENCES dim_class(class_key),
    PRIMARY KEY (date_key, student_key, class_key)
);

-- "What classes did student X attend?" -> rows that exist
-- "What classes did student X miss?" -> rows that DON'T exist (anti-join with coverage table)
```

### Grain Definition

The grain statement is the most important design decision. It must be a single declarative sentence stating what one row represents.

Examples:
- "One row per sales transaction line item" (transaction fact)
- "One row per account per calendar month-end" (periodic snapshot)
- "One row per insurance claim from filing through settlement" (accumulating snapshot)
- "One row per student per class per scheduled day" (factless fact / coverage)

### Degenerate Dimensions

Operational identifiers (transaction number, invoice number, order number) that live in the fact table as attributes, not in their own dimension table. They have no descriptive attributes worth modeling.

```sql
-- transaction_id and line_number are degenerate dimensions in fact_sales
-- They exist only in the fact table, not in a separate dim_transaction
```

### Junk Dimensions

Low-cardinality flags and indicators combined into a single dimension instead of cluttering the fact table with many small columns.

```sql
CREATE TABLE dim_transaction_flags (
    flag_key            INT     NOT NULL PRIMARY KEY,
    is_online           CHAR(1) NOT NULL,  -- Y/N
    is_gift_wrapped     CHAR(1) NOT NULL,
    is_loyalty_member   CHAR(1) NOT NULL,
    payment_type        VARCHAR(15) NOT NULL,  -- Cash, Credit, Debit, Digital
    delivery_method     VARCHAR(15) NOT NULL   -- Standard, Express, Pickup
);
-- Populate with the Cartesian product of all valid combinations
-- Reference from fact table: flag_key INT REFERENCES dim_transaction_flags
```

### Role-Playing Dimensions

A single physical dimension table referenced multiple times in the same fact table, each time playing a different role. Typically `dim_date`.

```sql
-- dim_date is role-played as order date, ship date, and delivery date
CREATE VIEW dim_order_date    AS SELECT * FROM dim_date;
CREATE VIEW dim_ship_date     AS SELECT * FROM dim_date;
CREATE VIEW dim_delivery_date AS SELECT * FROM dim_date;

-- fact_order references dim_date three times
-- order_date_key   -> dim_order_date.date_key
-- ship_date_key    -> dim_ship_date.date_key
-- delivery_date_key -> dim_delivery_date.date_key
```

### Bridge Tables

Resolve many-to-many relationships between facts and dimensions. Common for multi-valued dimensions (a patient with multiple diagnoses, an account with multiple holders).

```sql
CREATE TABLE bridge_account_holder (
    account_key     INT NOT NULL REFERENCES dim_account(account_key),
    customer_key    INT NOT NULL REFERENCES dim_customer(customer_key),
    weighting_factor DECIMAL(5,4) NOT NULL,  -- allocates measures proportionally
    PRIMARY KEY (account_key, customer_key)
);
-- Sum of weighting_factor per account_key should equal 1.0
-- Join: fact -> bridge -> dim_customer
```

---

## 3. Fact Table Design

### Grain Statement

Write it first. Every design decision flows from it.

```
GRAIN: fact_sales contains one row per line item per sales transaction.
GRAIN: fact_inventory_daily contains one row per product per store per day.
GRAIN: fact_claim_lifecycle contains one row per insurance claim, updated at each milestone.
```

### Measures — Additive, Semi-Additive, Non-Additive

**Additive measures** can be summed across all dimensions. Examples: revenue, quantity, cost, discount_amount, profit.

**Semi-additive measures** can be summed across some dimensions but not across time. Examples: account balance (sum across accounts, not across months), inventory on-hand (sum across products, not across days).

```sql
-- WRONG: summing balance across months gives nonsense
SELECT SUM(balance_amount) FROM fact_account_monthly;

-- RIGHT: balance at a point in time, summed across accounts
SELECT SUM(balance_amount)
FROM fact_account_monthly
WHERE date_key = 20260331;

-- RIGHT: average balance across months for trending
SELECT date_key, AVG(balance_amount)
FROM fact_account_monthly
GROUP BY date_key;
```

**Non-additive measures** cannot be meaningfully summed across any dimension. Examples: unit_price, margin_percentage, ratios. Store the components and compute in the query.

```sql
-- WRONG: storing margin_pct in the fact table and summing it
-- RIGHT: store revenue and cost, compute margin at query time
SELECT
    d.category,
    SUM(f.net_amount) AS total_revenue,
    SUM(f.cost_amount) AS total_cost,
    (SUM(f.net_amount) - SUM(f.cost_amount)) / NULLIF(SUM(f.net_amount), 0) * 100 AS margin_pct
FROM fact_sales f
JOIN dim_product d ON f.product_key = d.product_key
GROUP BY d.category;
```

### Surrogate Keys

Every fact table foreign key should reference a surrogate key (integer sequence) in the dimension table, not the natural key from the source system.

```sql
-- Surrogate key generation (PostgreSQL)
CREATE SEQUENCE seq_customer_key START 1;

-- During ETL: lookup or assign surrogate key
INSERT INTO dim_customer (customer_key, customer_id, customer_name, ...)
VALUES (nextval('seq_customer_key'), 'CUST-001', 'Acme Corp', ...);
```

Benefits: compact joins (INT vs VARCHAR), source-system independence, SCD Type 2 support (same natural key, multiple surrogate keys for historical versions).

### Late-Arriving Facts

Transactions that arrive after the period has been closed. The referenced dimension rows may have changed since the transaction occurred.

```sql
-- Scenario: a sale from 2026-01-15 arrives on 2026-03-31.
-- The customer may have moved (SCD Type 2) between Jan and Mar.

-- Solution: look up the dimension surrogate key that was current on the transaction date.
SELECT customer_key
FROM dim_customer
WHERE customer_id = 'CUST-001'
  AND '2026-01-15' BETWEEN effective_date AND expiry_date;

-- Insert the fact with the historically-correct surrogate key
INSERT INTO fact_sales (date_key, customer_key, product_key, ...)
VALUES (20260115, /* key from above */, ...);
```

---

## 4. Dimension Table Design

### Surrogate Keys vs Natural Keys

| Aspect | Surrogate Key | Natural Key |
|---|---|---|
| Type | Integer sequence | Source system identifier (e.g. CUST-001) |
| Stability | Never changes | May be recycled, reformatted, or merged |
| SCD support | Multiple rows per entity (one per version) | Cannot distinguish versions |
| Join performance | Fast (INT comparison) | Slower (VARCHAR comparison, longer) |
| Cross-system | Unifies multiple source keys | Requires composite keys or mapping |

**Always use surrogate keys as primary keys in dimensions and foreign keys in facts. Keep the natural key as a non-key attribute for traceability.**

### Hierarchies

**Fixed hierarchy:** Consistent number of levels with no skipping. Example: Country > State > City.

```sql
-- Embedded in the dimension (denormalized — preferred in star schema)
CREATE TABLE dim_geography (
    geography_key   INT         NOT NULL PRIMARY KEY,
    city            VARCHAR(50) NOT NULL,
    state           VARCHAR(50) NOT NULL,
    country         VARCHAR(50) NOT NULL,
    continent       VARCHAR(30) NOT NULL
);
```

**Ragged hierarchy:** Variable depth, some branches shorter than others. Example: organization hierarchy where some managers have many layers, others have one.

```sql
-- Approach 1: fixed columns with NULLs for missing levels
CREATE TABLE dim_org (
    org_key     INT         NOT NULL PRIMARY KEY,
    level_1     VARCHAR(50) NOT NULL,   -- CEO
    level_2     VARCHAR(50),            -- VP
    level_3     VARCHAR(50),            -- Director
    level_4     VARCHAR(50),            -- Manager
    level_5     VARCHAR(50),            -- Team Lead
    leaf_name   VARCHAR(50) NOT NULL,
    depth       SMALLINT    NOT NULL
);
```

**Parent-child hierarchy:** Self-referencing table for recursive structures of arbitrary depth. Common for org charts, account hierarchies, BOM (bill of materials).

```sql
CREATE TABLE dim_employee (
    employee_key    INT         NOT NULL PRIMARY KEY,
    employee_id     VARCHAR(15) NOT NULL,
    employee_name   VARCHAR(100) NOT NULL,
    title           VARCHAR(50),
    department      VARCHAR(50),
    parent_employee_key INT     REFERENCES dim_employee(employee_key),
    hierarchy_level SMALLINT    NOT NULL,
    -- Flattened path for query convenience
    path_string     VARCHAR(500)  -- '/1/5/23/107'
);

-- Recursive CTE to traverse
WITH RECURSIVE org_tree AS (
    SELECT employee_key, employee_name, parent_employee_key, 1 AS depth
    FROM dim_employee WHERE parent_employee_key IS NULL
    UNION ALL
    SELECT e.employee_key, e.employee_name, e.parent_employee_key, t.depth + 1
    FROM dim_employee e
    JOIN org_tree t ON e.parent_employee_key = t.employee_key
)
SELECT * FROM org_tree ORDER BY depth, employee_name;
```

### Outrigger Dimensions

A dimension referenced by another dimension (not by a fact table). Use sparingly — they add complexity.

```sql
-- dim_product references dim_product_launch_date (an outrigger)
CREATE TABLE dim_product (
    product_key         INT NOT NULL PRIMARY KEY,
    product_name        VARCHAR(100) NOT NULL,
    launch_date_key     INT REFERENCES dim_date(date_key),  -- outrigger to date dimension
    category            VARCHAR(50),
    ...
);
-- This lets you filter products by launch date attributes (launch quarter, etc.)
-- without duplicating date attributes in dim_product
```

### Mini-Dimensions

Split rapidly changing or high-cardinality attributes out of a large dimension to avoid excessive SCD Type 2 row proliferation.

```sql
-- Main customer dimension (stable attributes, SCD Type 2)
CREATE TABLE dim_customer (
    customer_key    INT         NOT NULL PRIMARY KEY,
    customer_id     VARCHAR(20) NOT NULL,
    customer_name   VARCHAR(100) NOT NULL,
    signup_date     DATE,
    effective_date  DATE        NOT NULL,
    expiry_date     DATE        NOT NULL DEFAULT '9999-12-31',
    current_flag    CHAR(1)     NOT NULL DEFAULT 'Y'
);

-- Mini-dimension for volatile demographic bands (SCD Type 0 — overwrite)
CREATE TABLE dim_customer_demo (
    demo_key            INT         NOT NULL PRIMARY KEY,
    age_band            VARCHAR(15) NOT NULL,   -- '18-24', '25-34', etc.
    income_band         VARCHAR(15) NOT NULL,   -- 'Low', 'Medium', 'High'
    credit_score_band   VARCHAR(15) NOT NULL    -- 'Poor', 'Fair', 'Good', 'Excellent'
);

-- Fact table references both
-- customer_key  -> dim_customer (who)
-- demo_key      -> dim_customer_demo (what they looked like at time of transaction)
```

---

