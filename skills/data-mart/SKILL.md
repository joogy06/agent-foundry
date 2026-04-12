---
name: data-mart
description: Use when designing, building, or optimizing data marts — dimensional modeling (star/snowflake schemas), fact and dimension table design, conformed dimensions, slowly changing dimensions (SCD Types 1-6), aggregation strategies, ETL/ELT loading patterns, data mart bus architecture, performance optimization (indexing/partitioning/materialized views), and data quality frameworks. Part of the data-* skill family.
---

# Data Mart Design and Implementation

Comprehensive guide to building analytical data marts using dimensional modeling (Kimball methodology). Covers schema design, fact/dimension patterns, SCD handling, ETL/ELT loading, aggregation, performance tuning, and data quality.

<HARD-RULE>
Always define the grain of every fact table in a single declarative sentence before adding any measures. The grain declaration drives all design decisions — measures, dimensions, and row counts follow from it.
</HARD-RULE>

<HARD-RULE>
Never use natural keys as fact table foreign keys — always use integer surrogate keys. Natural keys change, are inconsistent across sources, and bloat fact tables. Surrogate keys are compact, stable, and enable SCD tracking.
</HARD-RULE>

<HARD-RULE>
Always implement SCD Type 2 with both effective_date/expiry_date AND a current_flag. Using only one mechanism forces every query to compute currency; using both gives the optimizer a simple filter (current_flag = 'Y') for current-state queries and a range join for point-in-time queries.
</HARD-RULE>

<HARD-RULE>
Never build aggregates without a corresponding detail-level fact table. Aggregates are performance accelerators, not replacements for detail. Without the detail table you cannot drill down, audit discrepancies, or answer unanticipated questions.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [fundamentals-modeling-facts.md](fundamentals-modeling-facts.md) | data mart fundamentals, dimensional modeling (star/snowflake), and fact table design |
| [performance-quality.md](performance-quality.md) | aggregation strategies, performance optimization, and data quality |
| [scd-etl-patterns.md](scd-etl-patterns.md) | slowly changing dimensions (SCD Types 1-6), conformed dimensions, and ETL/ELT loading patterns |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using snowflake schema for simple marts | Adds join complexity without storage savings on modern systems; query performance degrades | Default to star schema; only snowflake when dimension tables exceed millions of rows with clear normalization benefit |
| Skipping conformed dimensions | Same customer/product means different things across marts; dashboards show contradictory numbers | Define conformed dimensions in a shared layer; all marts reference the same dimension tables |
| Loading fact tables without surrogate keys | Natural keys change (account numbers, product codes); history breaks when source systems change keys | Always use integer surrogate keys; map natural keys through dimension lookup |
| Building SCD Type 2 for every dimension | Adds complexity, storage, and ETL logic for dimensions that rarely change or where history is irrelevant | Use SCD Type 1 by default; only use Type 2 where business users explicitly need historical attribute tracking |
| No date dimension table | Repeated date parsing in queries, inconsistent fiscal calendar logic, missing holiday flags | Create a comprehensive date dimension with fiscal periods, holidays, and business day flags |

---

## Related Skills

| Domain | Skill |
|---|---|
| PostgreSQL, MySQL, Redis administration | `rhel-databases`, `ubuntu-databases` |
| Python data engineering (SQLAlchemy, Alembic) | `python-data-engineer` |
| Enterprise database connectors (DB2, Oracle, SQL Server) | `python-enterprise-connectors` |
| Large file analysis (CSV, logs) | `large-file-analysis` |
| Performance profiling and optimization | `performance` |
