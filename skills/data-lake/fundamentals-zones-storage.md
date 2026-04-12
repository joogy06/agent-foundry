# Fundamentals, Zone Architecture, and Storage Layer

Reference file for the `data-lake` skill. Covers lake vs warehouse vs lakehouse comparison, zone architecture (raw/cleansed/curated/consumption), and storage layer configuration.

## 1. Fundamentals — Lake vs Warehouse vs Lakehouse

### When to Use Each

| Criteria | Data Lake | Data Warehouse | Lakehouse |
|---|---|---|---|
| Data types | Structured + semi/unstructured | Structured only | All types |
| Schema | Schema-on-read | Schema-on-write | Schema-on-read + enforcement |
| Cost | Low (object storage) | High (compute-storage coupled) | Medium (decoupled) |
| ACID transactions | No (unless table format) | Yes | Yes (Delta/Iceberg/Hudi) |
| Users | Data engineers, data scientists | Business analysts, BI tools | All |
| Latency | Minutes to hours | Seconds to minutes | Seconds to minutes |
| Best for | ML, exploration, raw archive | Reporting, dashboards, KPIs | Unified analytics + ML |

**Decision flow:** Start with a lakehouse if greenfield. Use a pure lake if you need cheap archival + ML workloads without BI. Use a warehouse if you only have structured data and need sub-second BI queries.

### Data Swamp Anti-Patterns

A data lake becomes a swamp when:
- **No catalog** — nobody knows what data exists, what it means, or who owns it
- **No quality gates** — garbage data flows from raw to curated unchecked
- **No retention policy** — storage grows forever with no cleanup, stale data confuses users
- **No access control** — everyone dumps anything, no ownership, no governance
- **No lineage** — impossible to trace where data came from or how it was transformed
- **Schema chaos** — same entity stored in 15 formats across 30 paths with no documentation

---

## 2. Zone Architecture

### Four-Zone Model

```
Sources → [Landing/Raw] → [Cleansed/Standardized] → [Curated/Enriched] → [Consumption]
              │                    │                        │                    │
         Immutable ingest    Schema conform         Business logic       BI / ML / API
         Any format          Columnar + typed       Joined + aggregated  Optimized views
         Partitioned by      Deduped + validated    Conformed dims       SLA-bound
         ingestion date      Quality-checked        Versioned            Access-controlled
```

### Zone Specifications

**Raw / Landing Zone:**
- Purpose: Immutable record of source data exactly as received
- Formats: Whatever the source provides (CSV, JSON, XML, Avro, binary)
- Partitioning: By ingestion date (`year=YYYY/month=MM/day=DD`) or source system
- Retention: Long (3-7 years for compliance, indefinite for audit)
- Access: Data engineers only; no direct analyst access
- Path pattern: `s3://datalake-raw/{source_system}/{entity}/{year}/{month}/{day}/`

**Cleansed / Standardized Zone:**
- Purpose: Schema-conformant, deduplicated, type-cast, quality-checked data
- Formats: Parquet or ORC (columnar, compressed)
- Transformations: Type casting, null handling, dedup, PII tagging, timestamp normalization
- Quality: Must pass completeness, uniqueness, and schema checks
- Retention: Medium (1-3 years, rebuild from raw if needed)
- Path pattern: `s3://datalake-cleansed/{domain}/{entity}/`

**Curated / Enriched Zone:**
- Purpose: Business-ready datasets, joined across domains, conformed dimensions
- Formats: Parquet with Delta Lake / Iceberg table format
- Transformations: Joins, aggregations, business rules, SCD handling, feature engineering
- Quality: Business rule validation, referential integrity checks
- Retention: Medium to long, versioned via table format time travel
- Path pattern: `s3://datalake-curated/{domain}/{entity}/`

**Consumption Zone:**
- Purpose: Optimized views for specific consumers (BI, ML, APIs)
- Formats: Parquet/Delta, or materialized into a serving layer (Redshift, BigQuery, Postgres)
- Optimizations: Pre-aggregated, denormalized star schemas, feature stores
- Access: Role-based per consumer team; SLA-monitored
- Path pattern: `s3://datalake-consumption/{use_case}/{dataset}/`

### Zone Transition Rules (PySpark Example)

```python
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, current_timestamp, sha2, concat_ws

spark = SparkSession.builder.appName("zone-transition").getOrCreate()

# --- Raw → Cleansed ---
# Read raw JSON as-is
raw_df = spark.read.json("s3a://datalake-raw/crm/customers/year=2026/month=03/day=31/")

# Apply schema, cast types, add metadata
cleansed_df = (
    raw_df
    .select(
        col("id").cast("long").alias("customer_id"),
        col("name").cast("string"),
        col("email").cast("string"),
        col("created_at").cast("timestamp"),
        col("country_code").cast("string"),
    )
    .filter(col("customer_id").isNotNull())      # Drop records missing PK
    .dropDuplicates(["customer_id"])              # Dedup on PK
    .withColumn("_ingested_at", current_timestamp())
    .withColumn("_row_hash", sha2(concat_ws("||", *raw_df.columns), 256))
)

# Quality gate: fail if >5% nulls in critical columns
total = cleansed_df.count()
null_pct = cleansed_df.filter(col("email").isNull()).count() / total
if null_pct > 0.05:
    raise ValueError(f"Quality gate failed: {null_pct:.1%} null emails exceeds 5% threshold")

# Write to cleansed zone as Parquet (partitioned by country)
(cleansed_df.write
    .mode("overwrite")
    .partitionBy("country_code")
    .parquet("s3a://datalake-cleansed/crm/customers/"))
```

### Retention Policy Template

```yaml
# retention-policy.yaml
zones:
  raw:
    default_retention_days: 2555    # ~7 years
    exceptions:
      - entity: gdpr_subject_data
        retention_days: 1095        # 3 years (GDPR right to erasure)
        delete_method: hard_delete
  cleansed:
    default_retention_days: 1095    # 3 years
    rebuild_from: raw               # Can be rebuilt
  curated:
    default_retention_days: 1825    # 5 years
    versioning: enabled             # Time travel via Delta/Iceberg
  consumption:
    default_retention_days: 365     # 1 year
    refresh_frequency: daily
```

---

## 3. Storage Layer

### Storage Platforms

| Platform | Best For | Protocol | Cost Tier |
|---|---|---|---|
| Amazon S3 | AWS-native lakes | s3:// / s3a:// | Low |
| Azure Data Lake Storage Gen2 | Azure-native lakes | abfss:// | Low |
| Google Cloud Storage | GCP-native lakes | gs:// | Low |
| HDFS | On-prem Hadoop clusters | hdfs:// | Medium (hardware) |
| MinIO | On-prem S3-compatible | s3a:// | Low (self-hosted) |

### Directory Layout — Hive-Style Partitioning

```
s3://datalake-curated/
├── sales/
│   └── orders/
│       ├── year=2025/
│       │   ├── month=01/
│       │   │   ├── part-00000.snappy.parquet
│       │   │   └── part-00001.snappy.parquet
│       │   └── month=02/
│       │       └── ...
│       └── year=2026/
│           └── ...
├── finance/
│   └── transactions/
│       ├── dt=2026-03-31/
│       │   ├── part-00000.zstd.parquet
│       │   └── _SUCCESS
│       └── ...
└── _metadata/
    └── catalog.json
```

### Partitioning Strategy

```python
# Good: Partition by frequently filtered columns with moderate cardinality
(df.write
    .partitionBy("year", "month")           # ~12-60 partitions/year
    .parquet("s3a://datalake-curated/sales/orders/"))

# Bad: Over-partitioning creates small files (< 128 MB each)
# AVOID partitioning by high-cardinality columns like customer_id
# This creates millions of tiny files → slow queries, high S3 API costs
```

**Partition sizing rules:**
- Target 128 MB - 1 GB per partition file
- Avoid partitions with < 100 rows (small file problem)
- Max ~10,000 partitions per table (metastore overhead)
- Common patterns: `year/month`, `dt=YYYY-MM-DD`, `region/year/month`

### Bucketing (Optimize Joins)

```python
# Bucket by join key — co-locates data for shuffle-free joins
(df.write
    .bucketBy(64, "customer_id")
    .sortBy("customer_id")
    .saveAsTable("curated.orders_bucketed"))
```

### Compaction (Fix Small Files)

```python
# Repartition to merge small files into larger ones
spark.read.parquet("s3a://datalake-cleansed/crm/events/") \
    .repartition(20) \
    .write.mode("overwrite") \
    .parquet("s3a://datalake-cleansed/crm/events/")

# Delta Lake automatic compaction
spark.sql("OPTIMIZE delta.`s3a://datalake-curated/sales/orders/`")
```

### Storage Tiering (S3 Lifecycle)

```json
{
  "Rules": [
    {
      "ID": "RawZoneTiering",
      "Filter": { "Prefix": "datalake-raw/" },
      "Status": "Enabled",
      "Transitions": [
        { "Days": 90,  "StorageClass": "STANDARD_IA" },
        { "Days": 365, "StorageClass": "GLACIER" },
        { "Days": 2555, "StorageClass": "DEEP_ARCHIVE" }
      ]
    },
    {
      "ID": "CuratedZoneTiering",
      "Filter": { "Prefix": "datalake-curated/" },
      "Status": "Enabled",
      "Transitions": [
        { "Days": 180, "StorageClass": "STANDARD_IA" }
      ]
    }
  ]
}
```

### MinIO On-Prem Setup (Docker Compose)

```yaml
# docker-compose.yml
services:
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: minio-admin
      MINIO_ROOT_PASSWORD: "ChangeMe!Strong2026"
    volumes:
      - minio-data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  minio-data:
```

```bash
# Create buckets matching zone architecture
mc alias set lake http://localhost:9000 minio-admin 'ChangeMe!Strong2026'
mc mb lake/datalake-raw
mc mb lake/datalake-cleansed
mc mb lake/datalake-curated
mc mb lake/datalake-consumption
```

---

## 4. File Formats

### Format Selection Matrix

| Format | Type | Schema | Splittable | Best For | Compression |
|---|---|---|---|---|---|
| Parquet | Columnar | Embedded | Yes | Analytics, BI, wide tables | Snappy, Zstd, Gzip |
| ORC | Columnar | Embedded | Yes | Hive-heavy workloads, ACID in Hive | Zlib, Snappy, Zstd |
| Avro | Row-based | Embedded | Yes | Streaming, schema evolution, Kafka | Snappy, Deflate |
| Delta Lake | Columnar+ | Transaction log | Yes | ACID, time travel, MERGE | Snappy, Zstd |
| JSON | Row-based | None | Yes (JSONL) | Landing zone, small datasets | Gzip |
| CSV | Row-based | None | Yes | Landing zone, interchange | Gzip |

**Default choice: Parquet with Snappy compression** for all analytical zones. Use Zstd for better compression ratio when storage cost matters more than write speed.

### Compression Codecs

| Codec | Ratio | Speed | CPU Cost | Use Case |
|---|---|---|---|---|
| Snappy | Good | Very fast | Low | Default for most workloads |
| Zstd | Excellent | Fast | Medium | Storage-optimized, cold data |
| LZ4 | Good | Fastest | Lowest | Streaming, low-latency |
| Gzip | Excellent | Slow | High | Maximum compression, archival |
| Uncompressed | 1:1 | N/A | None | Debugging only |

### Writing Parquet with Compression

```python
# PySpark — Parquet with Zstd
(df.write
    .option("compression", "zstd")
    .mode("overwrite")
    .parquet("s3a://datalake-curated/sales/orders/"))

# PySpark — ORC with Zlib
(df.write
    .option("compression", "zlib")
    .mode("overwrite")
    .orc("s3a://datalake-curated/sales/orders_orc/"))

# PyArrow — Parquet (standalone, no Spark)
import pyarrow as pa
import pyarrow.parquet as pq

table = pa.Table.from_pandas(df)
pq.write_table(table, "output.parquet", compression="zstd", row_group_size=128 * 1024)

# Pandas — Parquet via PyArrow engine
df.to_parquet("output.parquet", engine="pyarrow", compression="zstd", index=False)
```

### Format Conversion (Landing → Analytical)

```python
# Convert CSV landing data to Parquet with schema enforcement
from pyspark.sql.types import StructType, StructField, StringType, LongType, TimestampType

schema = StructType([
    StructField("order_id", LongType(), nullable=False),
    StructField("customer_id", LongType(), nullable=False),
    StructField("product_code", StringType(), nullable=False),
    StructField("amount", LongType(), nullable=False),         # Store as cents
    StructField("order_date", TimestampType(), nullable=False),
    StructField("region", StringType(), nullable=True),
])

raw_csv = (spark.read
    .option("header", "true")
    .option("mode", "PERMISSIVE")               # Capture malformed rows
    .option("columnNameOfCorruptRecord", "_corrupt")
    .schema(schema)
    .csv("s3a://datalake-raw/erp/orders/dt=2026-03-31/"))

# Separate good records from corrupt
good = raw_csv.filter(col("_corrupt").isNull()).drop("_corrupt")
bad  = raw_csv.filter(col("_corrupt").isNotNull())

# Write good records as Parquet
good.write.mode("append").partitionBy("region").parquet("s3a://datalake-cleansed/erp/orders/")

# Write bad records to dead letter queue
bad.write.mode("append").json("s3a://datalake-raw/_dead_letter/erp/orders/dt=2026-03-31/")
```

---

