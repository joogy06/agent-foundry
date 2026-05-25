---
name: datastage-developer
description: Use when developing or administering IBM DataStage — parallel job design, server job patterns, stage types (Transformer/Join/Lookup/Aggregator/Sort/Funnel/Merge), connectors (DB2/Oracle/ODBC/Sequential File/Complex Flat File), parallel framework configuration, job sequencing, performance tuning, scheduling, DataStage on Cloud Pak for Data, and migration from legacy versions. Part of the data-* skill family.
---

# IBM DataStage — Development & Administration

For enterprise database connectors from Python see: `python-enterprise-connectors`. For Docker-based deployment see: `docker-admin`.

<HARD-RULE>
Always design parallel jobs with explicit partitioning — relying on auto-partitioning causes unpredictable data distribution and join failures.
</HARD-RULE>

<HARD-RULE>
Never use server jobs for new development — parallel jobs outperform and are the supported path forward.
</HARD-RULE>

<HARD-RULE>
Always handle reject links on lookup and connector stages — unhandled rejects silently drop rows.
</HARD-RULE>

<HARD-RULE>
Never run REORG or DDL on target tables while DataStage bulk loads are active — it causes loader failures and data corruption.
</HARD-RULE>

---

## 1. Architecture

### Information Server Components

IBM Information Server is a three-tier platform:

| Tier | Components | Purpose |
|---|---|---|
| **Client** | DataStage Designer, Director, Administrator, Manager | Job design, monitoring, administration |
| **Services** | WebSphere Application Server (WAS), metadata services, logging | Web console, REST APIs, security, scheduling |
| **Engine** | DataStage engine (parallel framework / Orchestrate), connectors | Job execution, data processing |

The **XMETA repository** (DB2 or Oracle) stores all metadata: job designs, table definitions, column metadata, lineage, operational history, and user/role definitions. Protect XMETA — corruption or loss means losing all job definitions.

### Parallel Engine Architecture

The parallel engine (based on Orchestrate/APT) uses a process model:

- **Conductor** — The master process. Reads the compiled job (OSH), builds the execution graph, coordinates section leaders.
- **Section Leader** — One per processing node. Manages player processes on its node, handles inter-node communication.
- **Player** — Worker processes that execute operators (stages). The number of players per node is controlled by the APT_CONFIG_FILE.

```
Conductor
  ├── Section Leader (node1)
  │     ├── Player 0 (partition 0)
  │     ├── Player 1 (partition 1)
  │     └── Player 2 (partition 2)
  └── Section Leader (node2)
        ├── Player 3 (partition 3)
        ├── Player 4 (partition 4)
        └── Player 5 (partition 5)
```

### APT_CONFIG_FILE

The configuration file defines the runtime topology — how many nodes and partitions the engine uses.

```
// Single-node, 4 partitions
{
  node "node1"
  {
    fastname "server01"
    pools ""
    resource disk "/ds_scratch/part0" {pools ""}
    resource disk "/ds_scratch/part1" {pools ""}
    resource disk "/ds_scratch/part2" {pools ""}
    resource disk "/ds_scratch/part3" {pools ""}
    resource scratchdisk "/ds_scratch/part0" {pools ""}
    resource scratchdisk "/ds_scratch/part1" {pools ""}
    resource scratchdisk "/ds_scratch/part2" {pools ""}
    resource scratchdisk "/ds_scratch/part3" {pools ""}
  }
}
```

Multi-node (SMP or MPP) configurations add additional `node` blocks. Each `resource disk` entry defines one partition — a job using this config file runs with 4 parallel partitions.

Key environment variables:

| Variable | Purpose |
|---|---|
| `APT_CONFIG_FILE` | Path to the parallel config file (mandatory) |
| `APT_ORCHHOME` | Orchestrate engine install directory |
| `APT_PM_PLAYER_MEMORY` | Max memory per player process |
| `APT_BUFFER_MAXIMUM_MEMORY` | Max memory for inter-stage buffering |
| `APT_DUMP_SCORE` | Set to 1 to dump execution plan (debugging) |
| `DS_PROJECT` | Current DataStage project path |
| `TMPDIR` | Temporary directory for sort spills and intermediate data |

---

## 2. Parallel Job Design

### Canvas Layout Principles

- Data flows left to right: sources on the left, transformations in the center, targets on the right.
- Name stages descriptively: `trn_CleanAddress`, `lkp_CustomerDim`, `join_OrderDetail`, `seq_DailyLoad`.
- Use annotations to document business rules on the canvas.
- Group related logic into shared containers for reuse across jobs.

### Link Types

| Link Type | Purpose | Example |
|---|---|---|
| **Input** | Feeds data into a stage | Source to Transformer |
| **Output** | Emits processed data from a stage | Transformer to target |
| **Reference** | Lookup reference data (read-only) | Dimension table feeding Lookup stage |
| **Reject** | Captures rows that fail stage processing | Unmatched lookup rows, connector errors |

### Data Types

DataStage parallel data types map to SQL types:

| DS Type | SQL Equivalent | Notes |
|---|---|---|
| `VarChar(n)` | `VARCHAR(n)` | Variable-length string |
| `Char(n)` | `CHAR(n)` | Fixed-length, padded |
| `Int32` | `INTEGER` | 32-bit signed integer |
| `Int64` | `BIGINT` | 64-bit signed integer |
| `Decimal(p,s)` | `DECIMAL(p,s)` | Exact numeric, use for money |
| `Float` | `FLOAT` | Avoid for financial data |
| `Double` | `DOUBLE` | Avoid for financial data |
| `Date` | `DATE` | YYYY-MM-DD |
| `Time` | `TIME` | HH:MM:SS |
| `Timestamp` | `TIMESTAMP` | Date + time + fractional seconds |

### Runtime Column Propagation (RCP)

RCP automatically passes columns through stages without explicit mapping. Enable it on links where you want pass-through behavior (e.g., a Transformer that only adds/modifies a few columns). Disable RCP when you need strict control over output schema.

### Partitioning

Partitioning distributes data across players. Choose explicitly based on the downstream operation:

| Method | Use When | Example |
|---|---|---|
| **Hash** | Pre-partitioning for Join/Lookup/Aggregator/Remove Duplicates | Hash on join key before Join stage |
| **Modulus** | Even numeric key distribution | Partition by customer_id % N |
| **Range** | Data must be in sorted ranges | Range partition + sort for merge |
| **Random** | Even distribution, no key preference | Feeding a Transformer with no grouping |
| **Round Robin** | Strict even distribution | Balancing load across partitions |
| **Same** | Data is already correctly partitioned | After a Hash partition, before next stage using same key |
| **Entire** | Every partition gets all rows | Broadcasting a small reference table |
| **DB2** | Match DB2 table's physical partitioning | Reading from partitioned DB2 tables |

### Collecting

Collecting merges partitioned data back to a single partition or fewer partitions:

| Method | Purpose |
|---|---|
| **Gather** | Concatenate partitions (order not guaranteed) |
| **Sort/Merge** | Collect and sort — use when output must be ordered |
| **Round Robin** | Pull from partitions in round-robin fashion |

### Pipeline vs Partition Parallelism

- **Partition parallelism**: Multiple players process different slices of data simultaneously through the same operator. Controlled by APT_CONFIG_FILE partition count.
- **Pipeline parallelism**: Upstream stages feed data to downstream stages concurrently. Rows flow through the pipeline without waiting for all upstream processing to complete. Happens automatically in the parallel engine.

Both forms operate simultaneously for maximum throughput.

---

## 3. Key Stages

### Transformer Stage

The workhorse of DataStage. Handles column derivations, data type conversions, conditional logic, and null handling.

**Derivation patterns:**

```
// Simple column mapping
input.CustomerName

// Conditional logic
If input.Status = "A" Then "Active" Else "Inactive"

// Null handling (critical — nulls propagate silently)
If IsNull(input.Phone) Then "UNKNOWN" Else input.Phone

// String functions
Trim(input.Name) : " " : Trim(input.Surname)

// Date conversion
DateFromDaysSince(0, StringToDate(input.DateStr, "%yyyy-%mm-%dd"))

// Numeric conversion
DecimalToDecimal(input.Amount, "fix_zero")

// Stage variable (calculated once per row, reused in multiple derivations)
svFullName = Trim(input.FirstName) : " " : Trim(input.LastName)
```

**Stage variables** execute top-to-bottom before derivations. Use them for:
- Intermediate calculations reused in multiple output columns
- Row counters and running totals
- Complex conditional logic broken into steps

**Null handling rules:**
- `IsNull(column)` — test for null before using
- `SetNull()` — assign null to output column
- `NullToValue(column, default)` / `NullToZero(column)` — replace nulls
- Any arithmetic or string operation on a null returns null — always guard

### Join Stage

Combines two or more sorted inputs on matching keys.

| Join Type | Rows Returned |
|---|---|
| **Inner** | Only matching rows from both inputs |
| **Left Outer** | All left rows + matching right rows (nulls for non-matches) |
| **Right Outer** | All right rows + matching left rows |
| **Full Outer** | All rows from both inputs |

**Requirements:**
- Inputs MUST be sorted on join keys (or partitioned by hash on join key with sort within partition)
- Partition both inputs identically using Hash on the join key columns
- Join keys must be the same data type on both sides

```
// Typical pattern: Hash partition on key → Sort → Join
Source_A → [Hash partition on cust_id] → [Sort on cust_id] → Join_Inner
Source_B → [Hash partition on cust_id] → [Sort on cust_id] → Join_Inner
```

### Lookup Stage

Retrieves reference data to enrich or validate records. More flexible than Join for many scenarios.

**Reference link behavior:**
- Reference data is loaded into memory (or cache) at stage startup
- Main input stream is matched against reference data
- Multiple reference links supported (chained lookups)

**Caching options:**

| Mode | When to Use |
|---|---|
| **Normal (in-memory)** | Reference dataset fits in memory (default) |
| **Sparse** | Large reference — only cache recently accessed rows (issues DB query per miss) |

**Multiple matches handling:**
- First match (default)
- Last match
- All matches (generates multiple output rows per input)
- Reject on multiple matches

**Always add a reject link** — unhandled lookup failures silently drop rows. Route rejects to a log or error table.

### Aggregator Stage

Groups rows and computes aggregates: SUM, COUNT, MIN, MAX, AVG, FIRST, LAST, COUNT DISTINCT.

**Partitioning:** Hash partition on the grouping key before the Aggregator for correct results.

```
// Group by Region, calculate total sales
Group Key: Region
  Total_Sales = SUM(input.SaleAmount)
  Order_Count = COUNT(input.OrderId)
  Avg_Order   = AVG(input.SaleAmount)
```

Supports **pre-aggregation** — the engine aggregates within each partition first, then merges partial results. Reduces inter-partition data movement.

### Sort Stage

Sorts data within partitions. Controls:
- Sort key columns and direction (ascending/descending)
- Stable sort (preserves order of equal keys)
- Allow duplicates / create key change column
- Sort utility: DataStage sort (default) or Unix sort (for very large datasets with spill-to-disk)

**Performance tips:**
- Sort only when required (Joins need sorted input; many other stages do not)
- Set `TMPDIR` to fast local disk for sort spills
- Increase `APT_BUFFER_MAXIMUM_MEMORY` if sort spills excessively

### Funnel Stage

Combines multiple inputs into a single output.

| Mode | Behavior |
|---|---|
| **Continuous** | Round-robin read from all inputs (no ordering guarantee) |
| **Sequence** | Read inputs in port order (all of input 0, then all of input 1, etc.) |
| **Sort** | Merge-sort from pre-sorted inputs (all inputs must be sorted on same key) |

Use **Sort** mode when feeding a downstream stage that requires sorted input. Use **Continuous** for maximum throughput when order does not matter.

### Merge Stage

Combines rows from a master input and one or more update inputs based on matching keys. Supports update, insert, and reject processing:
- Matched rows: update master with update values
- Unmatched master rows: pass through
- Unmatched update rows: route to reject or insert

Both master and update inputs must be sorted on the merge key.

### Filter Stage

Routes rows to different output links based on conditions. One input, multiple outputs. Each output link has a WHERE-style predicate. Rows matching no predicate go to the reject link (if connected).

```
// Output link 1: Status = "Active"
// Output link 2: Status = "Inactive"
// Reject link: everything else
```

### Remove Duplicates Stage

Removes or flags duplicate rows. Requires sorted input on the duplicate key. Keeps first or last occurrence. Hash partition on the key columns before Sort and Remove Duplicates.

### Change Capture / Change Apply

**Change Capture** compares a before-image and after-image to detect inserts, updates, and deletes. Outputs a change code column. **Change Apply** applies those changes to a target. Together they implement SCD (Slowly Changing Dimension) patterns.

### Surrogate Key Generator

Generates unique, sequential integer keys. Configure:
- Start value and increment
- Key source: In-memory counter (reset per run) or persistent state (flat file storing the last value)
- Use persistent state for dimension surrogate keys to ensure uniqueness across runs

---

## 4. Connectors

### DB2 Connector

**Partitioned read:**
```
// DB2 Connector → Read mode
// Table action: Select
// Partition type: Auto (uses DB2 native partitioning)
// Or: User-defined SQL with $APT_ORCHHOME partition macros
SELECT * FROM SCHEMA.TABLE WHERE MOD(KEY_COL, $NUMPARTITIONS) = $PARTITIONNUM
```

**Partitioned write (LOAD utility):**
```
// DB2 Connector → Write mode
// Write method: LOAD (bulk load — fastest for large volumes)
// Table action: Insert / Replace / Truncate then Insert
// Array size: 10000 (batch insert size for non-LOAD mode)
// Enable reject link for constraint violations
```

DB2 LOAD locks the table — coordinate with application downtime windows. For concurrent access, use INSERT mode with array batching.

### Oracle Connector

```
// Read: SELECT /*+ PARALLEL(t,4) */ * FROM SCHEMA.TABLE t
// Write: Path method = Conventional (row-by-row) or Direct Path (bypasses redo — fast, requires table lock)
// Array size: 2000-10000 rows per batch
// Reject link: captures ORA- errors per row
```

### ODBC Connector

Generic connector for any ODBC-compliant database. Slower than native connectors (DB2, Oracle) due to ODBC layer overhead. Use when native connectors are unavailable.

```
// ODBC data source must be configured in $DSHOME/.odbc.ini or system odbc.ini
// Supports read (SQL query or table), write (insert/update/delete)
// Array size: 1000-5000 (tune based on row width)
```

### Sequential File Stage

Reads/writes delimited or fixed-width flat files.

**Delimited files:**
```
// File: /data/landing/customers_*.csv
// Format: Delimited (comma, pipe, tab, etc.)
// First line is header: Yes/No
// Quote character: Double quote
// Null representation: "" (empty string) or explicit null marker
// Schema file: /ds_schemas/customer.schema
```

**Fixed-width files:**
```
// File: /data/landing/transactions.dat
// Format: Fixed-width
// Column positions defined in schema file or metadata
// No delimiters — rely on exact byte positions
```

**Schema files** (`.schema`) define column layout externally, enabling reuse across multiple jobs:
```
record { final_delim end, delim=','
  field1: string[max=50];
  field2: int32;
  field3: decimal[10,2];
  field4: nullable date;
}
```

Wildcards in file paths (`/data/landing/cust_*.csv`) read multiple files in parallel, one file per partition.

### Complex Flat File Stage

Handles multi-record-type files (header/detail/trailer), hierarchical structures, and files with multiple schemas within a single file. Define record identification rules (first N bytes, regex) and map each record type to a separate output link.

### Dataset Stage

DataStage's native persistent parallel data format. Stores data in partitioned binary files — fastest for inter-job staging. Use as scratch between jobs in a sequence; avoid for long-term storage (format is version-dependent).

### Kafka Connector (v11.7+)

```
// Read: Consumer mode, topic(s), consumer group, offset strategy (earliest/latest/committed)
// Write: Producer mode, topic, key column, partition strategy
// Serialization: JSON, Avro (with Schema Registry), CSV, Binary
// Connection: Bootstrap servers, SASL/SSL authentication
```

### REST Connector (v11.7+)

```
// HTTP method: GET/POST/PUT/DELETE
// URL with parameterization: https://api.example.com/v1/records?page=${page}
// Headers, authentication (Basic, OAuth, API Key)
// Response parsing: JSON path extraction
// Pagination: offset-based, cursor-based, link-header
```

### MQ Connector

Reads/writes IBM MQ messages. Configure queue manager, queue name, message format (fixed, delimited, XML). Supports transactional reads (GET with commit/backout).

---

## 5. Server Jobs

### When to Use

Server jobs run in a single-threaded, single-process model. Use ONLY for:
- Maintaining legacy jobs not yet migrated to parallel
- Processing that requires BASIC language custom stages (rare)
- Very small data volumes where parallel overhead is unnecessary

### BASIC Transformer

Server job transformers use BASIC language instead of the parallel expression language:

```basic
* BASIC Transformer example
If Trim(input.Name) = "" Then
  output.Name = "UNKNOWN"
End Else
  output.Name = Trim(input.Name)
End
```

### Migration Path to Parallel

1. Export the server job as DSX/ISX.
2. Create a new parallel job with equivalent logic.
3. Replace BASIC Transformer expressions with parallel derivations.
4. Replace server stages (Sequential File, ODBC, etc.) with parallel equivalents.
5. Add explicit partitioning on Join/Lookup/Aggregator stages.
6. Test with identical input data; compare row counts and checksums.
7. Retire the server job once the parallel job is validated in production.

There is no automated server-to-parallel converter — it is a manual redesign process.

---

## 6. Job Sequences

### Purpose

Job sequences orchestrate multiple jobs, scripts, and activities into a controlled workflow with dependency management, conditional execution, and error handling.

### Sequencer Stage

The Sequencer stage controls flow convergence:
- **All** — Wait for all upstream activities to complete before proceeding
- **Any** — Proceed when any one upstream activity completes
- **Conditional** — Evaluate expression based on upstream trigger values

### Activity Types

| Activity | Purpose |
|---|---|
| **Job Activity** | Run a DataStage parallel or server job |
| **Routine Activity** | Execute a built-in or custom routine (BASIC or C) |
| **ExecCommand** | Run an OS command or shell script |
| **Email Notification** | Send email on success/failure/warning |
| **Wait for File** | Pause until a trigger file appears |
| **Start/Stop MQ** | Control MQ listener stages |
| **Nested Condition** | If/Else branching within the sequence |
| **Exception Handler** | Catch and handle errors from upstream activities |

### Job Activity Parameters

Pass parameters from the sequence to child jobs:
```
// In Sequence: Job Activity Properties → Parameters tab
// Parameter: input_date = $ENV{PROCESS_DATE}
// Parameter: source_file = "/data/landing/" : JobName : "_" : $ENV{PROCESS_DATE} : ".csv"
// Reset option: Reset if required, else run (ensures clean state)
```

### Error Handling

```
// Pattern: Try-Catch with Exception Handler
Job_Load → [Trigger: Failed] → Exception_Handler → Email_Notification_Failure
Job_Load → [Trigger: Succeeded] → Job_PostProcess → Email_Notification_Success

// Exception Handler properties:
// - Automatically aborts the sequence on unhandled exceptions
// - Log exception details to Director log
// - Use ExecCommand to write error details to a control table
```

### Conditional Execution

```
// Nested Condition: check if source file exists before loading
ExecCommand_CheckFile → [Output: exitcode=0] → Job_Load
ExecCommand_CheckFile → [Output: exitcode!=0] → Email_NoFileAlert
```

---

## 7. Performance Tuning

### APT_CONFIG_FILE Tuning

The single most impactful tuning lever. More partitions = more parallelism, but also more overhead.

```
// Guidelines:
// - Start with partitions = number of CPU cores
// - For I/O-bound jobs: partitions = 2x CPU cores
// - For CPU-bound transformations: partitions = CPU cores
// - For small datasets (< 100K rows): use 1-2 partitions
// - Each partition consumes memory — monitor RSS per player
```

**Multi-node configuration:**
```
{
  node "node1"
  {
    fastname "etl-server-01"
    pools ""
    resource disk "/ds_scratch_01/part0" {pools ""}
    resource disk "/ds_scratch_01/part1" {pools ""}
    resource scratchdisk "/ds_scratch_01/part0" {pools ""}
    resource scratchdisk "/ds_scratch_01/part1" {pools ""}
  }
  node "node2"
  {
    fastname "etl-server-02"
    pools ""
    resource disk "/ds_scratch_02/part0" {pools ""}
    resource disk "/ds_scratch_02/part1" {pools ""}
    resource scratchdisk "/ds_scratch_02/part0" {pools ""}
    resource scratchdisk "/ds_scratch_02/part1" {pools ""}
  }
}
```

### Partition Tuning Patterns

| Scenario | Recommendation |
|---|---|
| Join/Merge between two large tables | Hash partition both inputs on join key, sort within partition |
| Small lookup table (< 1M rows) | Use Lookup stage with in-memory cache, Entire partition on reference |
| Large lookup table (> 10M rows) | Hash partition both streams on lookup key, use Join stage instead |
| Aggregation | Hash partition on group-by key |
| Write to a single target file | Collect (Gather) before file write stage |
| Read many small files | Use wildcard pattern — engine distributes files across partitions |

### Buffering

Inter-stage buffers control pipeline parallelism efficiency:

```bash
# Increase buffer memory for wide rows or high-throughput pipelines
export APT_BUFFER_MAXIMUM_MEMORY=512    # MB per buffer (default varies by version)
export APT_BUFFER_FREE_RUN=200          # rows before blocking (pipeline flow control)
```

### Sort Optimization

```bash
# Ensure TMPDIR points to fast local disk, not NFS
export TMPDIR=/ds_scratch/tmp

# Restrict sort memory to avoid swapping
export APT_PM_PLAYER_MEMORY=512         # MB per player process
```

- Use **Sort** stage only when required (for Join, Merge, Remove Duplicates, Sort-mode Funnel).
- If data is already sorted from the source (ORDER BY in SQL), set partition type to **Same** and skip the Sort stage.
- Enable **key change column** in Sort to avoid a downstream Remove Duplicates stage.

### Database Bulk Load

| Database | Bulk Method | Notes |
|---|---|---|
| DB2 | LOAD utility via DB2 Connector | Fastest, locks table, no logging |
| Oracle | Direct Path (SQL*Loader) | Bypasses redo, requires exclusive access |
| SQL Server | BCP via ODBC/native connector | Bulk copy protocol |

Always prefer bulk load for initial loads and large batch inserts. Use conventional insert (with array batching, size 5000-10000) for incremental loads requiring concurrent access.

### Reject Links

Add reject links to every stage that supports them (Lookup, connectors, Join, Filter). Route rejects to:
- A Dataset stage for post-job analysis
- A Sequential File for error logging
- A database error table with job name, timestamp, and error details

### Operator Combination

The parallel engine automatically combines adjacent compatible operators into a single process to reduce inter-process communication. Verify with `APT_DUMP_SCORE=1` — the score file shows which operators were combined. Avoid breaking combination by inserting unnecessary stages between compatible operators.

---

## 8. Parallel Framework Configuration

### Config File Syntax

```
{
  node "logical_node_name"
  {
    fastname "hostname_or_ip"
    pools "pool_name"                         // optional grouping
    resource disk "/path/to/partition_dir" {pools "pool_name"}
    resource scratchdisk "/path/to/scratch" {pools "pool_name"}
  }
}
```

- One `resource disk` entry per partition on the node.
- `scratchdisk` is used for sort spills, hash joins, and temporary data.
- `fastname` is the hostname or IP used for inter-node communication.

### Single-Node vs Multi-Node

| Topology | Use Case |
|---|---|
| **Single-node, multiple partitions** | Most common. One server, 4-16 partitions depending on cores. |
| **Multi-node (SMP cluster)** | Large-scale processing, horizontally distributed across servers. |
| **Conductor-only node** | Dedicated node for the conductor process, separate from worker nodes. |

### Resource Allocation

```bash
# Project-level environment variables (set in Administrator or dsenv)
export APT_CONFIG_FILE=/opt/ds_configs/default.apt
export APT_ORCHHOME=/opt/IBM/InformationServer/Server/PXEngine
export APT_PM_PLAYER_MEMORY=512
export APT_BUFFER_MAXIMUM_MEMORY=256
export APT_STRING_PADCHAR=' '
export TMPDIR=/ds_scratch/tmp

# Per-job overrides: set in job properties → Parameters → Environment tab
```

### Scratch Disk Management

```bash
# Monitor scratch disk usage (sort spills, hash joins, temp datasets)
df -h /ds_scratch/

# Clean orphaned temp files (run when NO jobs are active)
find /ds_scratch/ -name "apt*" -mtime +1 -delete
find /tmp -name "osh*" -mtime +1 -delete

# Alert threshold: set monitoring to trigger at 80% usage
```

---

## 9. Administration

### Project Management

```bash
# List projects
/opt/IBM/InformationServer/Server/DSEngine/bin/dsadmin -listprojects

# Create project
/opt/IBM/InformationServer/Server/DSEngine/bin/dsadmin -createproject /opt/ds_projects/NEW_PROJECT

# Delete project (destructive — exports first)
/opt/IBM/InformationServer/Server/DSEngine/bin/dsadmin -deleteproject PROJECT_NAME
```

### User and Role Security

- **Suite Administrator**: Full control over all projects and server settings.
- **DataStage Administrator**: Project-level admin — create/delete jobs, manage users within a project.
- **DataStage Developer**: Design, compile, run jobs.
- **DataStage Operator**: Run and monitor jobs only (no design changes).

Assign roles in the Web Console (Information Server) or via command-line:
```bash
# Add user to project with role
/opt/IBM/InformationServer/Server/DSEngine/bin/dsadmin -adduser PROJECT_NAME username developer
```

### Import / Export (DSX and ISX)

**DSX format** (legacy, pre-v11.5):
```bash
# Export jobs to DSX file
/opt/IBM/InformationServer/Server/DSEngine/bin/dsexport.sh -domain HOST -user admin -password PASS \
  -project PROJECT -jobname "Job_*" -file /exports/jobs.dsx

# Import from DSX
/opt/IBM/InformationServer/Server/DSEngine/bin/dsimport.sh -domain HOST -user admin -password PASS \
  -project PROJECT -file /exports/jobs.dsx -overwrite
```

**ISX format** (v11.5+, preferred — includes lineage metadata):
```bash
# Export to ISX
/opt/IBM/InformationServer/Clients/istools/cli/istool.sh export \
  -domain HOST:PORT -u admin -p PASS \
  -ar /exports/jobs.isx \
  -ds "PROJECT/*"

# Import from ISX
/opt/IBM/InformationServer/Clients/istools/cli/istool.sh import \
  -domain HOST:PORT -u admin -p PASS \
  -ar /exports/jobs.isx \
  -ds "TARGET_PROJECT" -replace
```

### Version Control

DataStage does not have built-in Git integration. Recommended patterns:
1. Export jobs as ISX/DSX after each change.
2. Commit exported files to Git with meaningful messages.
3. Use `istool` in CI/CD pipelines for automated export/import across environments (Dev → Test → Prod).
4. Tag Git releases to match production deployment versions.

### Scheduling

**Director client** — built-in scheduler for simple cron-like job triggers.

**Enterprise schedulers** (preferred for production):
- **Control-M**: Define DataStage job type, pass parameters, capture return codes.
- **IBM TWS (Tivoli Workload Scheduler)**: Native integration with Information Server.
- **Autosys**: External command to invoke `dsjob` CLI.

```bash
# CLI: Run a job from scheduler or script
/opt/IBM/InformationServer/Server/DSEngine/bin/dsjob -run -mode NORMAL -wait \
  -param input_date=2026-03-31 PROJECT_NAME Job_DailyLoad

# Check job status
/opt/IBM/InformationServer/Server/DSEngine/bin/dsjob -jobinfo PROJECT_NAME Job_DailyLoad

# Return codes: 0=OK, 1=Warning, 2=Fatal, 3=Aborted
```

### Log Management

```bash
# Director logs location
/opt/IBM/InformationServer/Server/DSEngine/projects/PROJECT/logs/

# View job log via CLI
/opt/IBM/InformationServer/Server/DSEngine/bin/dsjob -logdetail PROJECT_NAME Job_DailyLoad

# Clean old logs (keep 30 days)
find /opt/IBM/InformationServer/Server/DSEngine/projects/*/logs/ -name "*.log" -mtime +30 -delete

# XMETA operational metadata grows over time — schedule purge
# Web Console → Administration → Operational Metadata → Purge
```

### XMETA Maintenance

```bash
# Backup XMETA database (DB2 example)
db2 backup database XMETA to /backup/xmeta/ compress

# RUNSTATS on XMETA tables (critical for query performance)
db2 "RUNSTATS ON TABLE XMETA.XTOOLSJOBRUN WITH DISTRIBUTION AND DETAILED INDEXES ALL"

# REORG XMETA tables periodically (during maintenance window)
db2 "REORG TABLE XMETA.XTOOLSJOBRUN"

# Monitor XMETA size
db2 "SELECT TBSP_NAME, TBSP_USED_SIZE_KB/1024 AS USED_MB FROM SYSIBMADM.TBSP_UTILIZATION"
```

---

## 10. Cloud Pak for Data (CP4D)

### DataStage as a CP4D Service

IBM DataStage on Cloud Pak for Data runs as a containerized service on OpenShift. Key differences from on-premises:

| Aspect | On-Premises | Cloud Pak for Data |
|---|---|---|
| **UI** | DataStage Designer (thick client) | Flow Designer (web browser) |
| **Engine** | Traditional PX engine on bare metal/VM | PX Runtime pods on OpenShift |
| **Repository** | XMETA on DB2/Oracle | Internal CP4D metastore |
| **Scaling** | Fixed config file | Dynamic pod scaling |
| **Connectivity** | Direct network | Connections via CP4D connection assets |

### PX Runtime

The PX Runtime is the execution engine in CP4D. It runs DataStage jobs compiled from Flow Designer or migrated ISX files. Configure PX Runtime resources in the CP4D admin UI:
- CPU and memory limits per runtime pod
- Number of compute nodes (partitions)
- Persistent storage for scratch and temp data

### Flow Designer (Web UI)

The browser-based replacement for DataStage Designer:
- Drag-and-drop canvas with the same stage types (Transformer, Join, Lookup, etc.)
- Integrated data preview and column-level lineage
- Parameterization via job parameters and environment variables
- Version history built into CP4D projects
- Shared connection assets for all data sources

### Migration from On-Prem

```bash
# 1. Export on-prem jobs as ISX
istool.sh export -domain ONPREM_HOST:PORT -u admin -p PASS \
  -ar /migration/all_jobs.isx -ds "PROJECT/*"

# 2. Upload ISX to CP4D via REST API or UI
# CP4D → DataStage → Import → Upload ISX file

# 3. Review and fix connection references
# On-prem connections (DSN, direct IP) must be remapped to CP4D connection assets

# 4. Test in CP4D environment
# - Verify row counts
# - Compare output checksums
# - Check performance (PX Runtime vs on-prem engine)
```

### Connectivity on OpenShift

Data sources outside the OpenShift cluster require:
- Network policies allowing egress to database hosts/ports
- TLS certificates for secure connections
- CP4D Connection Assets configured with proper credentials
- For on-prem databases behind firewalls: Satellite Connector or VPN tunnels

### DataStage REST API (CP4D)

```bash
# Get bearer token
TOKEN=$(curl -s -k -X POST "https://CP4D_HOST/icp4d-api/v1/authorize" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"PASS"}' | jq -r '.token')

# List DataStage flows in a project
curl -s -k -X GET "https://CP4D_HOST/v3/ds_codegen/flows?project_id=PROJECT_ID" \
  -H "Authorization: Bearer $TOKEN"

# Run a DataStage flow
curl -s -k -X POST "https://CP4D_HOST/v3/ds_codegen/flows/FLOW_ID/run?project_id=PROJECT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"job_run":{"job_parameters":[{"name":"input_date","value":"2026-03-31"}]}}'

# Get run status
curl -s -k -X GET "https://CP4D_HOST/v3/ds_codegen/flows/FLOW_ID/runs/RUN_ID?project_id=PROJECT_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 11. Migration & Modernization

### v8.x / v9.x to v11.7 Migration

1. **Assess**: Inventory all jobs, shared containers, table definitions, routines, parameter sets.
2. **Export**: Use `dsexport` (DSX) for v8.x sources; `istool export` (ISX) for v9.x+ sources.
3. **Upgrade XMETA**: Run Information Server upgrade installer — it migrates the XMETA schema in place.
4. **Import**: Import DSX/ISX into the v11.7 project.
5. **Recompile**: All jobs must be recompiled on the v11.7 engine.
6. **Test**: Full regression test — row counts, data checksums, performance benchmarks.
7. **Retire**: Decommission old engine only after production validation.

**Common migration issues:**
- Transform expressions using deprecated functions (consult IBM compatibility matrix)
- ODBC driver version mismatches — upgrade drivers on new engine
- APT_CONFIG_FILE paths differ between old and new servers
- Environment variable differences in `dsenv`

### ISX Export / Import Best Practices

```bash
# Export with dependencies (shared containers, table definitions, parameter sets)
istool.sh export -domain HOST:PORT -u admin -p PASS \
  -ar /exports/full_project.isx \
  -ds "PROJECT/*" \
  -includedependentobjects

# Import with conflict resolution
istool.sh import -domain HOST:PORT -u admin -p PASS \
  -ar /exports/full_project.isx \
  -ds "TARGET_PROJECT" \
  -replace -includealiases
```

### Server-to-Parallel Conversion

No automated tool exists. Manual process:

| Server Job Element | Parallel Equivalent |
|---|---|
| BASIC Transformer | Parallel Transformer (derivation expressions) |
| Hashed File stage | Lookup stage or Dataset |
| Sequential File (server) | Sequential File stage (parallel) |
| ODBC stage (server) | DB2/Oracle/ODBC connector (parallel) |
| UniVerse stage | DB2/Oracle connector + SQL |
| Aggregator (server) | Aggregator stage + Hash partition on group key |
| BASIC routines | Parallel routines (C/C++) or BuildOp |

### DataStage to Spark Migration

For organizations moving to Spark-based ETL (Databricks, AWS Glue, native Spark):

| DataStage Concept | Spark Equivalent |
|---|---|
| Parallel job | Spark application / notebook |
| Stage | DataFrame transformation |
| Partitioning | `repartition()` / `coalesce()` |
| Transformer | `withColumn()` / `select()` / UDF |
| Join stage | `df1.join(df2, key, "inner")` |
| Lookup stage | Broadcast join (`broadcast(df)`) |
| Aggregator | `groupBy().agg()` |
| Sort | `orderBy()` / `sortWithinPartitions()` |
| Sequential File | `spark.read.csv()` / `.parquet()` |
| Job sequence | Airflow DAG / Databricks Workflow |
| APT_CONFIG_FILE | Spark cluster config (`spark.executor.instances`, `spark.executor.cores`) |

### API-Driven Job Management

Modern DataStage (v11.7+ and CP4D) supports REST APIs for CI/CD integration:

```bash
# On-prem v11.7: Use dsjob CLI in CI/CD pipelines
# Compile job
dsjob -run -mode RESET PROJECT_NAME Job_Load
dsjob -run -mode VALIDATE PROJECT_NAME Job_Load

# CP4D: Use REST API (see Section 10)
# Integrate with Jenkins/GitLab CI:
# 1. Git push triggers pipeline
# 2. Pipeline calls istool import (on-prem) or CP4D REST API (cloud)
# 3. Run validation job
# 4. Promote to next environment on success
```

---

## 12. RHEL Installation & Configuration

### Prerequisites (RHEL 9)

```bash
# Required packages
sudo dnf install -y gcc gcc-c++ libstdc++ libstdc++-devel \
  pam pam-devel libaio numactl ksh perl \
  compat-openssl11 nss-pam-ldapd \
  xorg-x11-server-Xvfb libXext libXrender libXtst

# Kernel parameters — /etc/sysctl.conf
kernel.shmmax = 4294967296
kernel.shmall = 1048576
kernel.shmmni = 4096
kernel.sem = 250 256000 32 4096
kernel.msgmni = 16384
kernel.msgmax = 65536
net.core.rmem_default = 262144
net.core.wmem_default = 262144
net.core.rmem_max = 4194304
net.core.wmem_max = 4194304
sudo sysctl -p

# File descriptor limits — /etc/security/limits.conf
dsadm  soft  nofile  65536
dsadm  hard  nofile  65536
dsadm  soft  nproc   16384
dsadm  hard  nproc   16384
```

### Installation

```bash
# Create DataStage user and groups
sudo groupadd -g 1200 dstage
sudo useradd -u 1200 -g dstage -m -d /home/dsadm dsadm

# Mount installation media
sudo mount -o loop IIS_11.7.1_linux64.tar.gz /mnt/iis

# Silent install with response file
cd /mnt/iis
./setup -i silent -f /path/to/is_install.rsp

# Response file key settings:
# REPOSITORY_DB_TYPE=DB2        (or Oracle/PostgreSQL)
# XMETA_DB_NAME=xmeta
# WAS_INSTALL_DIR=/opt/IBM/WebSphere/AppServer
# IS_INSTALL_DIR=/opt/IBM/InformationServer
# ENGINE_DIR=/opt/IBM/InformationServer/Server/DSEngine
# DEDICATED_ENGINE=true
```

### Post-Install Configuration

```bash
# Source DataStage environment
. /opt/IBM/InformationServer/Server/DSEngine/dsenv

# Verify engine
dsjob -lprojects

# Configure conductor node
cd /opt/IBM/InformationServer/Server/DSEngine
cat dsenv | grep APT_CONFIG_FILE
# Default: /opt/IBM/InformationServer/Server/DSEngine/apt_config_file.apt

# Verify WebSphere console (services tier)
# https://hostname:9443/ibm/iis/console
```

### SELinux

```bash
# DataStage requires permissive contexts on install/engine directories
sudo semanage fcontext -a -t usr_t "/opt/IBM/InformationServer(/.*)?"
sudo restorecon -Rv /opt/IBM/InformationServer

# If SELinux blocks shared memory operations
sudo ausearch -m AVC -ts recent | grep dsadm
sudo ausearch -m AVC -ts recent | audit2allow -M datastage_custom
sudo semodule -i datastage_custom.pp

# Verify no denials
sudo ausearch -m AVC -ts recent | grep datastage
```

### Firewalld

```bash
# DataStage ports
sudo firewall-cmd --permanent --add-port=9443/tcp    # WAS admin console
sudo firewall-cmd --permanent --add-port=9080/tcp    # WAS HTTP
sudo firewall-cmd --permanent --add-port=31531/tcp   # DS RPC (dsrpcd)
sudo firewall-cmd --permanent --add-port=31532/tcp   # DS RPC range start
sudo firewall-cmd --permanent --add-port=31533-31540/tcp  # DS RPC range
sudo firewall-cmd --permanent --add-port=13400/tcp   # IS services
sudo firewall-cmd --permanent --add-port=13401/tcp   # IS services
sudo firewall-cmd --reload
```

### Systemd Service

```ini
# /etc/systemd/system/datastage.service
[Unit]
Description=IBM DataStage Engine
After=network.target db2inst1.service
Requires=db2inst1.service

[Service]
Type=forking
User=dsadm
Group=dstage
ExecStart=/opt/IBM/InformationServer/Server/DSEngine/bin/uv -admin -start
ExecStop=/opt/IBM/InformationServer/Server/DSEngine/bin/uv -admin -stop
TimeoutStartSec=300
TimeoutStopSec=120
Restart=on-failure
LimitNOFILE=65536
LimitNPROC=16384
Environment="DSHOME=/opt/IBM/InformationServer/Server/DSEngine"

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now datastage
```

### WebSphere Application Server (Services Tier)

```bash
# Start WAS for Information Server console
/opt/IBM/WebSphere/AppServer/profiles/InfoSphere/bin/startServer.sh server1

# Stop
/opt/IBM/WebSphere/AppServer/profiles/InfoSphere/bin/stopServer.sh server1

# Systemd service for WAS
# /etc/systemd/system/was-iis.service
# [Service]
# ExecStart=/opt/IBM/WebSphere/AppServer/profiles/InfoSphere/bin/startServer.sh server1
# ExecStop=/opt/IBM/WebSphere/AppServer/profiles/InfoSphere/bin/stopServer.sh server1
```

---

---

## Security — XML / XHTML parsing

<HARD-RULE>
When parsing any XML or XHTML payload from a remote API, untrusted file, or user-supplied source, NEVER use stdlib `xml.etree.ElementTree`, `xml.dom.minidom`, or `lxml.etree.fromstring` without XXE protection. Use `defusedxml` (`pip install defusedxml`) and replace `xml.etree.ElementTree` → `defusedxml.ElementTree`, `lxml.etree` → `defusedxml.lxml`. Stdlib XML parsers expand external entities by default and are vulnerable to billion-laughs / XXE / DTD-retrieval / SSRF-via-entity attacks (CWE-611). Local skill applicability:
- API payloads that may legitimately be XML (storage format, error responses)
- Imported / exported workflow files
- Bulk import / migration paths
</HARD-RULE>

For HTML/XHTML rendering of downstream output (storage format → display), sanitise with `bleach` or `nh3` BEFORE inserting into a browser context — never raw-render API-returned XHTML. See `llm-security` SKILL.md §4.4 for context-appropriate escaping rules.

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using server jobs when parallel jobs are available | Server jobs run single-threaded; performance bottleneck on large datasets | Always use parallel jobs; server jobs only for legacy migration or specific mainframe connectors |
| Hardcoding connection strings in job designs | Environment promotion (dev to test to prod) requires manual edits; missed changes cause data corruption | Use environment variables and parameter sets; configure connections through DataStage Administrator |
| Skipping RUNSTATS after bulk loads to DB2 | Optimizer uses stale statistics; queries against loaded tables run full table scans | Run RUNSTATS on affected tables and indexes immediately after every bulk load operation |
| One monolithic job for entire ETL pipeline | Impossible to restart mid-pipeline; one failure reruns hours of work; no parallel execution | Break into stages: extract, transform, load; use sequencer for orchestration with restart points |
| Not handling reject links on transformers | Bad data silently disappears; downstream reports have missing records with no audit trail | Always connect reject links to a reject file or error table; monitor reject counts in job logs |

---

## Related Skills

| Domain | Skill |
|---|---|
| Enterprise database connectors (Python) | `python-enterprise-connectors` |
| Data engineering (SQLAlchemy, Alembic, pipelines) | `python-data-engineer` |
| Docker containerization | `docker-admin` |
| RHEL server administration | `rhel-server-admin` |
| RHEL database administration | `rhel-databases` |
| Ubuntu database administration | `ubuntu-databases` |
| IBM WebSphere (services tier) | `ibm-websphere` |
| IBM MQ connectors | `ibm-mq` |
| DB2 on RHEL (XMETA repository) | `db2-rhel` |
