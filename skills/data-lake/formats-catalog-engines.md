# File Formats, Table Formats, Catalog, and Query Engines

Reference file for the `data-lake` skill. Covers file formats (Parquet/ORC/Avro), table formats (Delta Lake/Apache Iceberg/Apache Hudi), data catalog/governance, and query engines.

## 5. Table Formats (Lakehouse)

### Delta Lake

Delta Lake adds ACID transactions, time travel, and MERGE (upserts) to Parquet files via a JSON transaction log (`_delta_log/`).

```python
# Write as Delta
(df.write
    .format("delta")
    .mode("overwrite")
    .partitionBy("region")
    .save("s3a://datalake-curated/sales/orders_delta/"))

# Read Delta table
orders = spark.read.format("delta").load("s3a://datalake-curated/sales/orders_delta/")

# MERGE (upsert) — incoming updates into existing table
from delta.tables import DeltaTable

target = DeltaTable.forPath(spark, "s3a://datalake-curated/sales/orders_delta/")
source = spark.read.parquet("s3a://datalake-cleansed/erp/orders_incremental/")

(target.alias("t")
    .merge(source.alias("s"), "t.order_id = s.order_id")
    .whenMatchedUpdateAll()
    .whenNotMatchedInsertAll()
    .execute())

# Time travel — query previous version
orders_v3 = spark.read.format("delta").option("versionAsOf", 3).load("s3a://datalake-curated/sales/orders_delta/")
orders_yesterday = spark.read.format("delta").option("timestampAsOf", "2026-03-30").load("s3a://datalake-curated/sales/orders_delta/")

# OPTIMIZE + Z-ORDER (data compaction + co-location)
spark.sql("""
    OPTIMIZE delta.`s3a://datalake-curated/sales/orders_delta/`
    ZORDER BY (customer_id, order_date)
""")

# VACUUM — remove old files beyond retention
spark.sql("VACUUM delta.`s3a://datalake-curated/sales/orders_delta/` RETAIN 168 HOURS")
```

### Apache Iceberg

Iceberg provides hidden partitioning (users query without knowing partition layout), schema evolution, and snapshot isolation.

```python
# Spark with Iceberg catalog
spark = (SparkSession.builder
    .appName("iceberg-demo")
    .config("spark.sql.catalog.lakehouse", "org.apache.iceberg.spark.SparkCatalog")
    .config("spark.sql.catalog.lakehouse.type", "hadoop")
    .config("spark.sql.catalog.lakehouse.warehouse", "s3a://datalake-curated/iceberg/")
    .getOrCreate())

# Create Iceberg table with hidden partitioning
spark.sql("""
    CREATE TABLE lakehouse.sales.orders (
        order_id    BIGINT,
        customer_id BIGINT,
        amount      DECIMAL(12, 2),
        order_date  TIMESTAMP,
        region      STRING
    )
    USING iceberg
    PARTITIONED BY (month(order_date), region)
""")

# Insert data — partition transforms are automatic
spark.sql("""
    INSERT INTO lakehouse.sales.orders
    SELECT * FROM cleansed_orders
""")

# Schema evolution — add column (backward compatible)
spark.sql("ALTER TABLE lakehouse.sales.orders ADD COLUMNS (discount DECIMAL(5, 2))")

# Schema evolution — rename column
spark.sql("ALTER TABLE lakehouse.sales.orders RENAME COLUMN amount TO total_amount")

# Time travel — query a specific snapshot
spark.sql("SELECT * FROM lakehouse.sales.orders VERSION AS OF 123456789")
spark.sql("SELECT * FROM lakehouse.sales.orders TIMESTAMP AS OF '2026-03-30 12:00:00'")

# Expire old snapshots
spark.sql("CALL lakehouse.system.expire_snapshots('sales.orders', TIMESTAMP '2026-03-25 00:00:00')")

# Rewrite data files (compaction)
spark.sql("CALL lakehouse.system.rewrite_data_files('sales.orders')")
```

### Apache Hudi

Hudi excels at upserts and incremental queries, ideal for CDC-sourced tables.

```python
# Write as Hudi Copy-on-Write table
hudi_options = {
    "hoodie.table.name": "orders",
    "hoodie.datasource.write.recordkey.field": "order_id",
    "hoodie.datasource.write.precombine.field": "updated_at",
    "hoodie.datasource.write.partitionpath.field": "region",
    "hoodie.datasource.write.operation": "upsert",
    "hoodie.upsert.shuffle.parallelism": "200",
}

(df.write
    .format("hudi")
    .options(**hudi_options)
    .mode("append")
    .save("s3a://datalake-curated/sales/orders_hudi/"))

# Incremental query — only records changed since last checkpoint
incremental_df = (spark.read
    .format("hudi")
    .option("hoodie.datasource.query.type", "incremental")
    .option("hoodie.datasource.read.begin.instanttime", "20260330120000")
    .load("s3a://datalake-curated/sales/orders_hudi/"))
```

### Table Format Comparison

| Feature | Delta Lake | Apache Iceberg | Apache Hudi |
|---|---|---|---|
| ACID transactions | Yes | Yes | Yes |
| Time travel | Yes (version/timestamp) | Yes (snapshot/timestamp) | Yes (instant time) |
| Schema evolution | Add/rename/reorder | Add/rename/reorder/widen | Add columns |
| Hidden partitioning | No (explicit) | Yes (transforms) | No (explicit) |
| MERGE / Upsert | Native MERGE | MERGE (Spark 3.x) | Native upsert engine |
| Compaction | OPTIMIZE + Z-ORDER | Rewrite data files | Built-in compaction |
| Ecosystem | Databricks, wide Spark | Multi-engine (Spark/Trino/Flink) | Spark, Flink, Presto |
| Best for | Databricks shops, general | Multi-engine, schema-heavy | CDC pipelines, upsert-heavy |

**Default recommendation:** Iceberg for new multi-engine lakes, Delta Lake for Databricks-centric shops.

---

## 6. Data Catalog & Governance

### Catalog Options

| Catalog | Type | Best For |
|---|---|---|
| Hive Metastore (HMS) | Self-hosted | On-prem Spark/Hive clusters |
| AWS Glue Data Catalog | Managed | AWS-native lakes |
| Unity Catalog | Managed | Databricks multi-cloud |
| Apache Atlas | Self-hosted | Hadoop ecosystem governance |
| OpenMetadata | Self-hosted | Open-source, engine-agnostic |
| DataHub | Self-hosted | Metadata platform, lineage |

### Hive Metastore — Register External Table

```sql
-- Register Parquet data as external Hive table
CREATE EXTERNAL TABLE IF NOT EXISTS cleansed.customers (
    customer_id    BIGINT,
    name           STRING,
    email          STRING,
    created_at     TIMESTAMP
)
PARTITIONED BY (country_code STRING)
STORED AS PARQUET
LOCATION 's3a://datalake-cleansed/crm/customers/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');

-- Discover partitions
MSCK REPAIR TABLE cleansed.customers;
```

### AWS Glue Catalog — Crawler + Athena

```python
# boto3 — create Glue crawler
import boto3

glue = boto3.client("glue", region_name="eu-west-1")

glue.create_crawler(
    Name="datalake-cleansed-crm",
    Role="arn:aws:iam::123456789012:role/GlueCrawlerRole",
    DatabaseName="cleansed",
    Targets={
        "S3Targets": [
            {"Path": "s3://datalake-cleansed/crm/customers/"},
            {"Path": "s3://datalake-cleansed/crm/orders/"},
        ]
    },
    SchemaChangePolicy={
        "UpdateBehavior": "UPDATE_IN_DATABASE",
        "DeleteBehavior": "LOG",                   # Don't auto-delete tables
    },
    Schedule="cron(0 6 * * ? *)",                  # Daily 06:00 UTC
)

glue.start_crawler(Name="datalake-cleansed-crm")
```

```sql
-- Query via Athena after crawler runs
SELECT country_code, COUNT(*) AS customer_count
FROM cleansed.customers
WHERE created_at >= DATE '2026-01-01'
GROUP BY country_code
ORDER BY customer_count DESC;
```

### Lineage and Classification

```python
# OpenMetadata — register lineage via API (simplified)
import requests

OM_URL = "http://openmetadata:8585/api/v1"
HEADERS = {"Authorization": "Bearer <token>"}

# Add lineage edge: raw.crm.customers → cleansed.crm.customers
requests.put(f"{OM_URL}/lineage", headers=HEADERS, json={
    "edge": {
        "fromEntity": {"id": "<raw-table-uuid>", "type": "table"},
        "toEntity": {"id": "<cleansed-table-uuid>", "type": "table"},
    },
    "description": "Schema enforcement, dedup, PII tagging",
})
```

### Access Control — Unity Catalog Example

```sql
-- Grant domain-level access
GRANT USAGE ON CATALOG main TO `data-engineers`;
GRANT USE SCHEMA ON SCHEMA main.curated TO `analysts`;
GRANT SELECT ON TABLE main.curated.orders TO `analysts`;

-- Row-level security via dynamic view
CREATE VIEW main.consumption.orders_filtered AS
SELECT * FROM main.curated.orders
WHERE region = current_user_attribute('region');

-- Column masking
ALTER TABLE main.curated.customers
ALTER COLUMN email SET MASK mask_email USING COLUMNS (role);
```

---

## 7. Query Engines

### Engine Selection

| Engine | Strength | Latency | Best For |
|---|---|---|---|
| Apache Spark | ETL + analytics, ML | Seconds-minutes | Batch transforms, ML pipelines |
| Trino (ex-Presto) | Interactive SQL | Sub-second-seconds | Ad-hoc queries, BI |
| Dremio | Self-service analytics | Sub-second-seconds | BI acceleration, data virtualization |
| DuckDB | Embedded analytics | Milliseconds | Local analysis, CI/CD tests, notebooks |
| Apache Flink | Stream processing | Milliseconds | Real-time transforms |
| Athena (Presto) | Serverless SQL | Seconds | AWS ad-hoc, cost-per-query |

### Apache Spark Configuration Tuning

```python
spark = (SparkSession.builder
    .appName("lake-etl")
    .master("yarn")
    # --- Memory ---
    .config("spark.executor.memory", "8g")
    .config("spark.executor.memoryOverhead", "2g")
    .config("spark.driver.memory", "4g")
    .config("spark.memory.fraction", "0.8")
    # --- Parallelism ---
    .config("spark.executor.cores", "4")
    .config("spark.executor.instances", "10")
    .config("spark.sql.shuffle.partitions", "200")        # Match data volume
    .config("spark.default.parallelism", "200")
    # --- S3 Access ---
    .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
    .config("spark.hadoop.fs.s3a.endpoint", "s3.eu-west-1.amazonaws.com")
    .config("spark.hadoop.fs.s3a.committer.name", "magic")  # S3A committer (no _temporary)
    .config("spark.sql.sources.commitProtocolClass",
            "org.apache.spark.internal.io.cloud.PathOutputCommitProtocol")
    # --- Performance ---
    .config("spark.sql.adaptive.enabled", "true")            # AQE
    .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
    .config("spark.sql.adaptive.skewJoin.enabled", "true")
    .config("spark.sql.parquet.enableVectorizedReader", "true")
    .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
    # --- Delta Lake / Iceberg extensions ---
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
    .getOrCreate())
```

**Key tuning rules:**
- `spark.sql.shuffle.partitions` = 2-3x total executor cores for medium data, reduce for small datasets
- `spark.executor.memory` = (node RAM - OS overhead) / executors_per_node
- Enable AQE (`spark.sql.adaptive.enabled=true`) — it auto-tunes shuffle partitions and handles skew
- Use S3A magic committer — avoids the slow rename-based commit protocol on S3

### Trino — Query Iceberg Tables

```sql
-- trino-cli or JDBC
-- Catalog configured in /etc/trino/catalog/iceberg.properties
SELECT
    region,
    DATE_TRUNC('month', order_date) AS order_month,
    SUM(total_amount) AS revenue,
    COUNT(DISTINCT customer_id) AS unique_customers
FROM iceberg.sales.orders
WHERE order_date >= DATE '2026-01-01'
GROUP BY region, DATE_TRUNC('month', order_date)
ORDER BY revenue DESC;
```

Trino Iceberg catalog config (`/etc/trino/catalog/iceberg.properties`):

```properties
connector.name=iceberg
iceberg.catalog.type=hive_metastore
hive.metastore.uri=thrift://hive-metastore:9083
iceberg.file-format=PARQUET
iceberg.compression-codec=ZSTD
```

### DuckDB — Local Parquet Analysis

```sql
-- DuckDB reads Parquet (and S3) natively — great for dev/test
INSTALL httpfs;
LOAD httpfs;
SET s3_region = 'eu-west-1';

SELECT region, SUM(amount) AS total
FROM read_parquet('s3://datalake-curated/sales/orders/**/*.parquet', hive_partitioning=true)
WHERE year = 2026
GROUP BY region;

-- Or local files
SELECT * FROM read_parquet('/data/lake/curated/sales/orders/*.parquet')
WHERE order_date >= '2026-03-01'
LIMIT 100;
```

---

## 8. Schema Evolution

### Evolution Types and Compatibility

| Change | Backward Compatible | Forward Compatible | Safe? |
|---|---|---|---|
| Add optional column | Yes | Yes | Safe |
| Add required column | No | No | Breaking |
| Remove column | No | Yes | Breaking |
| Rename column | No | No | Breaking |
| Widen type (int->long) | Yes | No | Safe with care |
| Narrow type (long->int) | No | No | Breaking |
| Change nullability (required->optional) | Yes | No | Safe |
| Change nullability (optional->required) | No | No | Breaking |

### Schema Evolution with Iceberg

```sql
-- Safe: add optional column
ALTER TABLE lakehouse.sales.orders ADD COLUMNS (
    discount DECIMAL(5, 2) COMMENT 'Applied discount percentage'
);

-- Safe: widen type
ALTER TABLE lakehouse.sales.orders ALTER COLUMN order_id TYPE BIGINT;

-- Safe: reorder columns
ALTER TABLE lakehouse.sales.orders ALTER COLUMN discount AFTER amount;

-- Rename (safe in Iceberg, handled by field IDs not names)
ALTER TABLE lakehouse.sales.orders RENAME COLUMN discount TO discount_pct;
```

### Schema Evolution with Delta Lake

```python
# Enable auto-merge for additive changes
spark.conf.set("spark.databricks.delta.schema.autoMerge.enabled", "true")

# Write new data with extra columns — schema auto-evolves
(new_df.write
    .format("delta")
    .mode("append")
    .option("mergeSchema", "true")
    .save("s3a://datalake-curated/sales/orders_delta/"))

# Overwrite schema entirely (use with caution — breaking change)
(new_df.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .save("s3a://datalake-curated/sales/orders_delta/"))
```

### Schema Registry (Avro / Kafka)

```python
# Register schema with Confluent Schema Registry
import requests

REGISTRY_URL = "http://schema-registry:8081"

avro_schema = {
    "type": "record",
    "name": "Order",
    "namespace": "com.example.sales",
    "fields": [
        {"name": "order_id", "type": "long"},
        {"name": "customer_id", "type": "long"},
        {"name": "amount", "type": {"type": "bytes", "logicalType": "decimal", "precision": 12, "scale": 2}},
        {"name": "order_date", "type": {"type": "long", "logicalType": "timestamp-millis"}},
        {"name": "region", "type": ["null", "string"], "default": None},
    ]
}

# Register with BACKWARD compatibility (default)
resp = requests.post(
    f"{REGISTRY_URL}/subjects/orders-value/versions",
    json={"schema": str(avro_schema).replace("'", '"')},
)

# Set compatibility level
requests.put(
    f"{REGISTRY_URL}/config/orders-value",
    json={"compatibility": "BACKWARD"},
)
```

### Migration Plan Template

```yaml
# schema-migration-v2.yaml
migration:
  table: curated.sales.orders
  version: 2
  changes:
    - action: add_column
      column: discount_pct
      type: DECIMAL(5,2)
      nullable: true
      default: null
      breaking: false
    - action: rename_column
      old_name: amount
      new_name: total_amount
      breaking: true
      migration_steps:
        - "Add total_amount column as alias"
        - "Update all downstream consumers to use total_amount"
        - "Verify no queries reference amount (grep pipelines)"
        - "Drop amount column after 30-day grace period"
  rollback:
    - "ALTER TABLE curated.sales.orders DROP COLUMN discount_pct"
    - "ALTER TABLE curated.sales.orders RENAME COLUMN total_amount TO amount"
  approved_by: data-platform-team
  scheduled: 2026-04-05
```

---

