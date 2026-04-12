# Schema Evolution, Data Quality, Ingestion, and Security

Reference file for the `data-lake` skill. Covers schema evolution patterns, data quality frameworks, ingestion patterns, and security/access control.

## 9. Data Quality

### Quality Dimensions

| Dimension | Definition | Example Check |
|---|---|---|
| Completeness | Required fields are populated | `email IS NOT NULL` (>99%) |
| Uniqueness | No duplicate records for PKs | `COUNT(DISTINCT pk) = COUNT(*)` |
| Accuracy | Values match real-world truth | Revenue within expected range |
| Consistency | Same entity matches across sources | CRM customer_id = ERP customer_id |
| Freshness | Data arrives within SLA | Partition `dt=today` exists by 08:00 |
| Validity | Values conform to format/domain | Email matches regex, status IN ('A','I','C') |

### Great Expectations

```python
import great_expectations as gx

context = gx.get_context()

# Connect to data source
datasource = context.data_sources.add_spark("lake_spark", spark_session=spark)
asset = datasource.add_dataframe_asset("orders")

# Build expectation suite
suite = context.suites.add(gx.ExpectationSuite(name="orders_cleansed_suite"))

suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="order_id"))
suite.add_expectation(gx.expectations.ExpectColumnValuesToBeUnique(column="order_id"))
suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="customer_id"))
suite.add_expectation(gx.expectations.ExpectColumnValuesToBeBetween(
    column="amount", min_value=0, max_value=1_000_000_00    # cents
))
suite.add_expectation(gx.expectations.ExpectColumnValuesToBeInSet(
    column="region", value_set=["NA", "EU", "APAC", "LATAM"]
))
suite.add_expectation(gx.expectations.ExpectTableRowCountToBeBetween(
    min_value=1000, max_value=10_000_000
))

# Run validation
batch = asset.add_batch_definition_whole_dataframe("full").get_batch(
    batch_parameters={"dataframe": orders_df}
)
results = batch.validate(suite)

if not results.success:
    # Route to dead letter queue or halt pipeline
    failed_expectations = [r for r in results.results if not r.success]
    raise ValueError(f"Quality gate failed: {len(failed_expectations)} checks failed")
```

### AWS Deequ (Spark-native)

```python
from pydeequ.checks import Check, CheckLevel
from pydeequ.verification import VerificationSuite, VerificationResult

check = (Check(spark, CheckLevel.Error, "orders_quality")
    .isComplete("order_id")
    .isUnique("order_id")
    .isComplete("customer_id")
    .isNonNegative("amount")
    .isContainedIn("region", ["NA", "EU", "APAC", "LATAM"])
    .hasSize(lambda x: x >= 1000))

result = (VerificationSuite(spark)
    .onData(orders_df)
    .addCheck(check)
    .run())

result_df = VerificationResult.checkResultsAsDataFrame(spark, result)
result_df.show(truncate=False)

# Fail pipeline if any check fails
if result_df.filter("check_status = 'Error'").count() > 0:
    raise ValueError("Data quality checks failed — see result_df for details")
```

### Quality Gate Pattern (Between Zones)

```python
def quality_gate(df, zone_name, checks):
    """
    Generic quality gate — validates DataFrame before writing to next zone.
    Failed records go to dead letter queue. Pipeline halts if failure rate exceeds threshold.
    """
    total = df.count()
    if total == 0:
        raise ValueError(f"Quality gate [{zone_name}]: Empty DataFrame — no data to process")

    failed_mask = None
    for check_name, check_fn, threshold in checks:
        violations = df.filter(~check_fn(df))
        violation_pct = violations.count() / total

        if violation_pct > threshold:
            raise ValueError(
                f"Quality gate [{zone_name}] FAILED: {check_name} — "
                f"{violation_pct:.1%} violations exceeds {threshold:.1%} threshold"
            )
        # Accumulate failed records
        if failed_mask is None:
            failed_mask = ~check_fn(df)
        else:
            failed_mask = failed_mask | ~check_fn(df)

    good = df.filter(~failed_mask) if failed_mask else df
    bad = df.filter(failed_mask) if failed_mask else spark.createDataFrame([], df.schema)
    return good, bad


# Usage
from pyspark.sql.functions import col

checks = [
    ("order_id_not_null", lambda d: col("order_id").isNotNull(), 0.0),
    ("amount_positive",   lambda d: col("amount") > 0,          0.01),
    ("region_valid",      lambda d: col("region").isin("NA","EU","APAC","LATAM"), 0.02),
]

good_df, bad_df = quality_gate(orders_df, "raw_to_cleansed", checks)

# Write good records to cleansed zone
good_df.write.mode("append").parquet("s3a://datalake-cleansed/sales/orders/")

# Write bad records to dead letter queue
bad_df.write.mode("append").json("s3a://datalake-raw/_dead_letter/sales/orders/dt=2026-03-31/")
```

---

## 10. Ingestion Patterns

### Batch — Spark JDBC (Database Extract)

```python
# Extract from PostgreSQL
jdbc_df = (spark.read
    .format("jdbc")
    .option("url", "jdbc:postgresql://db-host:5432/production")
    .option("dbtable", "(SELECT * FROM orders WHERE updated_at >= '2026-03-30') AS t")
    .option("user", "etl_reader")
    .option("password", "ETLr3ader!")
    .option("driver", "org.postgresql.Driver")
    .option("fetchsize", "10000")
    .option("numPartitions", "8")
    .option("partitionColumn", "order_id")
    .option("lowerBound", "1")
    .option("upperBound", "10000000")
    .load())

# Write to landing zone
(jdbc_df.write
    .mode("overwrite")
    .parquet(f"s3a://datalake-raw/postgres/orders/dt=2026-03-31/"))
```

### Streaming — Kafka to Delta Lake (Spark Structured Streaming)

```python
# Read from Kafka
kafka_df = (spark.readStream
    .format("kafka")
    .option("kafka.bootstrap.servers", "kafka:9092")
    .option("subscribe", "orders")
    .option("startingOffsets", "latest")
    .option("maxOffsetsPerTrigger", "100000")
    .load())

# Parse Avro/JSON payload
from pyspark.sql.functions import from_json, col
from pyspark.sql.types import StructType, StructField, LongType, StringType, TimestampType

order_schema = StructType([
    StructField("order_id", LongType()),
    StructField("customer_id", LongType()),
    StructField("amount", LongType()),
    StructField("region", StringType()),
    StructField("event_time", TimestampType()),
])

parsed = (kafka_df
    .selectExpr("CAST(value AS STRING) AS json_str")
    .select(from_json("json_str", order_schema).alias("data"))
    .select("data.*"))

# Write to Delta Lake with exactly-once via checkpointing
(parsed.writeStream
    .format("delta")
    .outputMode("append")
    .option("checkpointLocation", "s3a://datalake-checkpoints/orders_stream/")
    .trigger(processingTime="1 minute")
    .start("s3a://datalake-cleansed/streaming/orders_delta/"))
```

### CDC — Debezium to Lake

```json
{
  "name": "postgres-cdc-orders",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "db-host",
    "database.port": "5432",
    "database.user": "debezium",
    "database.password": "Deb3z1um!",
    "database.dbname": "production",
    "database.server.name": "prod-pg",
    "table.include.list": "public.orders,public.customers",
    "plugin.name": "pgoutput",
    "slot.name": "debezium_orders",
    "topic.prefix": "cdc",
    "transforms": "unwrap",
    "transforms.unwrap.type": "io.debezium.transforms.ExtractNewRecordState",
    "transforms.unwrap.add.fields": "op,source.ts_ms",
    "key.converter": "org.apache.kafka.connect.json.JsonConverter",
    "value.converter": "org.apache.kafka.connect.json.JsonConverter"
  }
}
```

Then consume `cdc.public.orders` topic with Spark Structured Streaming (above) and apply MERGE into a Hudi or Delta table for upsert semantics.

### File Drop Ingestion

```python
# Watch S3 prefix for new files (event-driven via S3 notifications + SQS)
# Or poll-based with Auto Loader (Databricks) / file stream

# Spark Auto Loader (Databricks)
(spark.readStream
    .format("cloudFiles")
    .option("cloudFiles.format", "csv")
    .option("cloudFiles.schemaLocation", "s3a://datalake-checkpoints/autoloader/orders/schema/")
    .option("cloudFiles.inferColumnTypes", "true")
    .load("s3a://datalake-raw/file-drops/orders/")
    .writeStream
    .format("delta")
    .option("checkpointLocation", "s3a://datalake-checkpoints/autoloader/orders/")
    .trigger(availableNow=True)
    .start("s3a://datalake-cleansed/file-drops/orders_delta/"))

# Generic Spark file stream (non-Databricks)
(spark.readStream
    .schema(order_schema)
    .option("header", "true")
    .option("maxFilesPerTrigger", "10")
    .csv("s3a://datalake-raw/file-drops/orders/")
    .writeStream
    .format("parquet")
    .option("checkpointLocation", "s3a://datalake-checkpoints/file-drops/orders/")
    .trigger(processingTime="5 minutes")
    .start("s3a://datalake-cleansed/file-drops/orders/"))
```

---

## 11. Security & Access Control

### Column-Level and Row-Level Security

```sql
-- Trino: Row-level filter via view
CREATE VIEW consumption.orders_regional AS
SELECT * FROM curated.orders
WHERE region = current_user_region();

-- Trino: Column masking via view
CREATE VIEW consumption.customers_masked AS
SELECT
    customer_id,
    name,
    CASE
        WHEN current_role() IN ('pii-reader', 'admin')
        THEN email
        ELSE regexp_replace(email, '(^.)(.*)(@.*)', '$1***$3')
    END AS email,
    country_code
FROM curated.customers;
```

```python
# AWS Lake Formation — grant column-level access via boto3
import boto3

lf = boto3.client("lakeformation", region_name="eu-west-1")

lf.grant_permissions(
    Principal={"DataLakePrincipalIdentifier": "arn:aws:iam::123456789012:role/AnalystRole"},
    Resource={
        "TableWithColumns": {
            "DatabaseName": "curated",
            "Name": "customers",
            "ColumnNames": ["customer_id", "name", "country_code"],
            # email column excluded — analysts cannot see it
        }
    },
    Permissions=["SELECT"],
)
```

### Apache Ranger Policy (On-Prem)

```json
{
  "policyName": "curated-orders-analyst-access",
  "service": "hive",
  "resources": {
    "database": { "values": ["curated"] },
    "table": { "values": ["orders"] },
    "column": { "values": ["order_id", "amount", "region", "order_date"] }
  },
  "policyItems": [
    {
      "users": [],
      "groups": ["analysts"],
      "accesses": [{ "type": "select", "isAllowed": true }]
    }
  ],
  "denyPolicyItems": [
    {
      "users": [],
      "groups": ["analysts"],
      "accesses": [{ "type": "select", "isAllowed": true }],
      "resources": {
        "column": { "values": ["customer_id", "email"] }
      }
    }
  ]
}
```

### Encryption

```python
# S3 server-side encryption (SSE-S3 — default, transparent)
# Set at bucket level:
# aws s3api put-bucket-encryption --bucket datalake-curated \
#   --server-side-encryption-configuration \
#   '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"arn:aws:kms:..."}}]}'

# Client-side encryption with PySpark (column-level)
from pyspark.sql.functions import aes_encrypt, aes_decrypt, lit

key = lit("0123456789abcdef0123456789abcdef")  # 256-bit key — use KMS in production

# Encrypt PII before writing
encrypted_df = df.withColumn("email_enc", aes_encrypt(col("email"), key, lit("GCM")))
encrypted_df.drop("email").write.parquet("s3a://datalake-curated/crm/customers_encrypted/")

# Decrypt when reading (only authorized roles)
decrypted_df = (spark.read.parquet("s3a://datalake-curated/crm/customers_encrypted/")
    .withColumn("email", aes_decrypt(col("email_enc"), key, lit("GCM")).cast("string")))
```

### Data Masking Functions

```sql
-- Dynamic masking examples (Spark SQL / Trino)
-- Email masking
SELECT regexp_replace(email, '(^.)(.*)(@.*)', '$1***$3') AS masked_email
FROM curated.customers;
-- Result: j***@example.com

-- Credit card masking
SELECT concat('****-****-****-', right(card_number, 4)) AS masked_card
FROM curated.payments;
-- Result: ****-****-****-1234

-- Phone masking
SELECT concat('+', left(phone, 2), '-***-***-', right(phone, 4)) AS masked_phone
FROM curated.customers;
-- Result: +44-***-***-5678
```

### Audit Logging

```python
# Log every data access event for compliance
import json
import datetime

def log_data_access(user, table, action, row_count, query_id):
    event = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "user": user,
        "table": table,
        "action": action,       # READ, WRITE, DELETE, SCHEMA_CHANGE
        "row_count": row_count,
        "query_id": query_id,
        "source_ip": "10.0.1.50",
    }
    # Write to audit log (append-only, separate from data lake)
    with open("/var/log/datalake/audit.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")

# In production: ship to immutable storage (S3 + Object Lock, or WORM)
# and index in Elasticsearch/OpenSearch for compliance queries
```

---

## Related Skills

| Domain | Skill |
|---|---|
| Database admin (SQLAlchemy, Alembic, query optimization) | `python-data-engineer` |
| Enterprise DB connectors (DB2, Oracle, mainframe) | `python-enterprise-connectors` |
| Containerized infrastructure (Spark/Trino in Docker) | `docker-compose-patterns` |
| Large file processing strategies | `large-file-analysis` |
| Python parallelism (asyncio, multiprocessing, Dask) | `python-parallelism` |
| Web research for technology evaluation | `web-research` |
