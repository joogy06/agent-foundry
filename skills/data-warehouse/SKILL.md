---
name: data-warehouse
description: Use when designing, building, or optimizing enterprise data warehouses — Kimball vs Inmon methodology, dimensional and normalized modeling, slowly changing dimensions, ETL/ELT pipeline design, partitioning and distribution strategies, materialized views, query optimization, data vault 2.0, warehouse platforms (PostgreSQL/Snowflake/Redshift/BigQuery/Synapse/DB2 Warehouse), and operational patterns (incremental loads, CDC, reconciliation). Part of the data-* skill family.
disambiguation: The ENTERPRISE layer — methodology choice, integration, SCD strategy, warehouse-wide modelling. One departmental subject-area mart is data-mart.
---

# Enterprise Data Warehouse — Design & Implementation

Companion skills: `python-data-engineer` (SQLAlchemy, Alembic, query optimization), `python-enterprise-connectors` (DB2, Oracle, SQL Server, mainframe integration), `rhel-databases` / `ubuntu-databases` (PostgreSQL/MySQL administration).

<HARD-RULE>
Always define and document the grain of every fact table before implementation. The grain is the single most important design decision — it determines what a row represents, which dimensions apply, and what facts are additive. Get this wrong and every report built on that table will be wrong.
</HARD-RULE>

<HARD-RULE>
Never mix granularities in a single fact table. If you need daily summaries alongside individual transactions, build separate fact tables at each grain. Mixing grains produces incorrect results when aggregating — users will get double-counted or inflated numbers with no obvious error.
</HARD-RULE>

<HARD-RULE>
Always implement idempotent ETL loads — rerunnability prevents data duplication after job failures. Every load process must produce the same result whether run once or five times for the same batch. Use MERGE/upsert patterns, staging-then-swap, or delete-and-reload by partition.
</HARD-RULE>

<HARD-RULE>
Never skip the staging layer — direct source-to-target makes debugging impossible and breaks restart/recovery. The staging layer is your forensic record, your restart checkpoint, and your data quality firewall. Without it, a failed load midway through transformation leaves the warehouse in an unrecoverable state.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [etl-scd-optimization.md](etl-scd-optimization.md) | Data Vault 2.0, ETL/ELT design, slowly changing dimensions, partitioning/distribution strategies, and query optimization |
| [methodology-modeling.md](methodology-modeling.md) | Kimball vs Inmon methodology, architecture patterns, dimensional modeling (star/snowflake schemas, fact/dimension tables) |
| [operations-testing-platforms.md](operations-testing-platforms.md) | platform-specific guidance (Snowflake, BigQuery, Redshift, Databricks), operational patterns (refresh strategies, monitoring, disaster recovery), and testing/quality |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using 3NF (normalized) design for user-facing query layers | Joins across 10+ normalized tables destroy query performance; business users cannot write their own queries | Use dimensional modeling (star schema) for consumption layer; normalize only in staging/integration layers |
| No slowly changing dimension strategy | Overwriting dimension attributes loses history; reports retroactively change when a customer moves or a product renames | Choose SCD type per attribute: Type 1 for corrections, Type 2 for historically significant changes, Type 3 for limited history |
| Loading the warehouse during business hours | ETL competes with queries for resources; users experience slow dashboards; lock contention causes failures | Schedule loads during off-hours batch windows; use change data capture (CDC) for near-real-time if business requires it |
| No materialized views or pre-aggregated tables for common queries | Dashboard queries recompute the same aggregations on millions of rows every time; slow and wasteful | Create materialized views for high-frequency query patterns; refresh on schedule; index aggregation columns |
| Skipping data quality checks between ETL stages | Bad data from source systems propagates into production reports; executives lose trust in the numbers | Implement data quality gates at each ETL stage: null checks, range validation, referential integrity, row count reconciliation |

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
