---
name: data-lake
description: Use when designing, building, or managing data lakes — zone architecture (raw/cleansed/curated/consumption), data catalog and governance, file formats (Parquet/ORC/Avro/Delta Lake/Apache Iceberg), storage layout and partitioning, schema evolution, Spark/Trino/Presto query engines, data quality frameworks, lakehouse patterns, and cloud/on-prem storage (S3/ADLS/HDFS/MinIO). Part of the data-* skill family.
---

# Data Lake Architecture & Implementation

For related skills see: `python-data-engineer` (SQLAlchemy, Alembic, DB admin), `python-enterprise-connectors` (DB2, Oracle, mainframe), `docker-compose-patterns` (containerized Spark/Trino), `large-file-analysis` (CSV/log processing).

<HARD-RULE>
Never modify data in the raw/landing zone — raw data is immutable. All transformations write to downstream zones. If raw data has errors, fix them in the cleansed zone and document the correction. Deleting or overwriting raw data destroys audit trails and reproducibility.
</HARD-RULE>

<HARD-RULE>
Always use columnar formats (Parquet/ORC) for analytical zones — CSV/JSON wastes 5-10x storage and kills query performance. Landing zone may accept CSV/JSON from sources, but the first transformation must convert to columnar format with appropriate compression.
</HARD-RULE>

<HARD-RULE>
Never allow schema-breaking changes without a migration plan — dropping columns, renaming fields, or narrowing types breaks downstream consumers. Use schema registries, table format evolution features, and compatibility checks. Every breaking change requires a versioned migration with rollback steps.
</HARD-RULE>

<HARD-RULE>
Always implement data quality gates between zones — bad data flowing unchecked turns a lake into a swamp. Every zone transition must validate completeness, accuracy, freshness, and schema conformance. Failed records go to dead letter queues, not downstream.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [formats-catalog-engines.md](formats-catalog-engines.md) | file formats (Parquet/ORC/Avro), table formats (Delta Lake/Apache Iceberg/Apache Hudi), data catalog/governance, and query engines |
| [fundamentals-zones-storage.md](fundamentals-zones-storage.md) | lake vs warehouse vs lakehouse comparison, zone architecture (raw/cleansed/curated/consumption), and storage layer configuration |
| [quality-ingestion-security.md](quality-ingestion-security.md) | schema evolution patterns, data quality frameworks, ingestion patterns, and security/access control |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Dumping raw data without zone separation | Data lake becomes a data swamp; no one knows what is clean, what is raw, what is trusted | Implement zone architecture: raw (landing), cleansed (validated), curated (business-ready), consumption (optimized) |
| No data catalog or metadata management | Users cannot find data; duplicate datasets proliferate; lineage is unknown; compliance audits fail | Deploy a data catalog (Apache Atlas, AWS Glue Catalog); tag every dataset with owner, schema, lineage, and classification |
| Storing everything as CSV | No schema enforcement, no compression, no predicate pushdown; queries scan entire files | Use columnar formats (Parquet, ORC) for analytics; Avro for streaming; Delta Lake/Iceberg for ACID and time travel |
| No partition strategy for large datasets | Full table scans on billions of rows; queries take hours instead of seconds | Partition by date and high-cardinality filter columns; align partition granularity with query patterns |
| Treating the data lake as append-only with no lifecycle management | Storage costs grow unbounded; stale data pollutes queries; compliance (GDPR right-to-delete) becomes impossible | Implement retention policies per zone; archive cold data to cheaper storage tier; enable deletion for compliance |

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
