---
name: db2-mainframe
description: Use when administering IBM DB2 for z/OS — subsystem management, buffer pool tuning, binding plans/packages, utilities (REORG/RUNSTATS/COPY/RECOVER), SQL performance (EXPLAIN/DSN_STATEMNT_TABLE), WLM service classes, data sharing groups, catalog/directory management, and z/OS-specific access patterns. Part of the db2-* skill family.
---

# IBM DB2 for z/OS — Mainframe DBA Administration

Companion skill to `python-enterprise-connectors` (Python connectivity to DB2 z/OS). For distributed DB2 see database skills in the `rhel-*` and `ubuntu-*` families.

<HARD-RULE>
NEVER run REORG with SHRLEVEL NONE on production tablespaces during business hours — it takes an exclusive drain lock, blocking all read and write access for the entire duration. Use SHRLEVEL REFERENCE (read-only access) or SHRLEVEL CHANGE (full access) instead.
</HARD-RULE>

<HARD-RULE>
Always run RUNSTATS after REORG and LOAD — access paths depend on current statistics. Without fresh statistics, the optimizer may choose full tablespace scans over available indexes, causing severe performance degradation. Bind/rebind after RUNSTATS to pick up new access paths.
</HARD-RULE>

<HARD-RULE>
Never BIND with VALIDATE(BIND) in production without thorough testing — if any object referenced in the SQL does not exist at bind time, the bind fails. But more critically, if you accidentally BIND with VALIDATE(RUN) in production without testing, invalid SQL is deferred to runtime, causing -818 (timestamp mismatch) or -805 (package not found) abends during execution. Always VALIDATE(BIND) in production after confirming all objects exist.
</HARD-RULE>

<HARD-RULE>
Always take IMAGE COPY after LOAD REPLACE or REORG — without it, RECOVER cannot go beyond that point. The recovery log chain is broken by these operations. If a failure occurs and no image copy exists post-LOAD/REORG, the tablespace is unrecoverable to any point after that operation. This is non-negotiable in production.
</HARD-RULE>

---

## 1. z/OS DB2 Subsystem Fundamentals

### Subsystem Identification

Every DB2 subsystem on z/OS has a 1-4 character **SSID** (Subsystem ID), e.g., `DB2P` (production), `DB2T` (test), `DB2D` (development). The SSID is used in all commands and JCL.

### Address Spaces

| Address Space | Purpose | Started Task |
|---------------|---------|--------------|
| **MSTR** (System Services) | Logging, recovery, command processing | `DB2PMSTR` |
| **DBM1** (Database Services) | SQL execution, buffer managers, EDM pool | `DB2PDBM1` |
| **DIST** (Distributed Data Facility) | DRDA connections, distributed SQL | `DB2PDIST` |
| **IRLM** (Internal Resource Lock Manager) | Lock management, deadlock detection | `DB2PIRLM` |
| **WLM-managed** | Stored procedures, UDFs | WLM-controlled |

### Starting and Stopping the Subsystem

```
// From the z/OS console:
-DB2P START DB2
-DB2P STOP DB2 MODE(QUIESCE)       /* Graceful — waits for threads to finish  */
-DB2P STOP DB2 MODE(FORCE)         /* Forced — terminates active threads      */

// Start with specific ZPARM member:
-DB2P START DB2,PARM(DSNZPARM),MSTR(DB2PMSTR),DBM1(DB2PDBM1)
```

### DSNZPARM — Subsystem Parameter Module

DSNZPARM is the load module containing all subsystem parameters. Built from macro `DSNTIJUZ` and loaded at startup.

Key parameter groups:

| ZPARM Panel | Parameters | Purpose |
|-------------|-----------|---------|
| DSNTIPE | BUFFERPOOL, EDMPOOL, SORTPOOL | Memory/buffer sizing |
| DSNTIP4 | MAXDBAT, CONDBAT, IDTHTOIN | Thread management |
| DSNTIP1 | LOGLOAD, CHKFREQ | Logging and checkpoint frequency |
| DSNTIP7 | CACHEDYN, MAXKEEPD, SRTPOOL | Dynamic SQL cache |
| DSNTIPB | STAESSION, STESSION | Distributed settings |
| DSNTIP8 | REALSTORAGE_MAX | Real storage limits |

Changing ZPARMs at runtime (DB2 12+):

```
-DB2P SET SYSPARM LOAD(DSNZP01N)
```

This loads a new ZPARM module without restarting DB2. Not all parameters are dynamic — some require a restart (documented in IBM's "Installable Parameters" reference).

---

## 2. Storage and Buffer Pools

### Buffer Pool Architecture

DB2 for z/OS has 50 buffer pools for 4K pages (BP0-BP49), 10 for 8K (BP8K0-BP8K9), 10 for 16K (BP16K0-BP16K9), and 10 for 32K (BP32K0-BP32K9). Each tablespace and indexspace is assigned to exactly one buffer pool.

### Assignment Strategy

| Buffer Pool | Recommended Use |
|-------------|----------------|
| BP0 | DB2 catalog and directory (default — do not share with user data) |
| BP1 | High-activity OLTP tablespaces |
| BP2 | Large sequential scan tablespaces |
| BP3-BP5 | Application-specific workloads |
| BP8K0 | 8K page tablespaces |
| BP16K0 | 16K page tablespaces |
| BP32K0 | LOB tablespaces, XML tablespaces |

### ALTER BUFFERPOOL

```
-- Increase virtual pool size to 50,000 4K pages (~200 MB)
-DB2P ALTER BUFFERPOOL(BP1) VPSIZE(50000)

-- Set thresholds
-DB2P ALTER BUFFERPOOL(BP1)
      VPSEQT(80)          /* Max % of pool for sequential steal    */
      DWQT(50)            /* Deferred write threshold (%)          */
      VDWQT(10)           /* Vertical deferred write threshold (%) */

-- Activate a buffer pool (if not already active)
-DB2P ALTER BUFFERPOOL(BP2) VPSIZE(20000)
```

### Tuning Parameters

| Parameter | What It Controls | Guideline |
|-----------|-----------------|-----------|
| **VPSIZE** | Number of pages in virtual pool | Size based on working set; monitor hit ratio |
| **VPSEQT** | Max % for sequential prefetch pages | 80% default; lower for random-I/O pools |
| **DWQT** | Deferred write trigger (% of pool) | 50% default; lower = more aggressive write-behind |
| **VDWQT** | Per-dataset deferred write threshold | 10% default; prevents one dataset hogging write queue |
| **PGSTEAL** | Page steal algorithm (LRU/FIFO/NONE) | LRU default; FIFO for pure sequential pools |

### Monitoring Buffer Pool Health

```
-DB2P DISPLAY BUFFERPOOL(BP1) DETAIL(*)
```

Key metrics from output:

| Metric | Target | Meaning |
|--------|--------|---------|
| Hit ratio (random) | > 95% | Pages found in memory without I/O |
| Hit ratio (sequential) | > 80% | Sequential reads served from pool |
| Synchronous writes | Near 0 | High value = DWQT too high, pages not written soon enough |
| Prefetch disabled | 0 | Non-zero = pool too small for sequential workload |

### Simulated Buffer Pools

For cost-effective development/test, use simulated pools that consume no real storage:

```
-DB2P ALTER BUFFERPOOL(BP10) VPSIZE(5000) PGSTEAL(NONE)
```

`PGSTEAL(NONE)` means pages are never cached — every read goes to disk. Used only for testing or very low-priority data.

### Group Buffer Pools (Data Sharing)

In a data sharing group, group buffer pools (GBP) reside in the coupling facility and cache cross-member interest pages.

```
-DB2P ALTER GROUPBUFFERPOOL(GBP1)
      GBPCACHE(YES)         /* Cache changed pages in GBP           */
      RATIO(50)             /* % of castout buffer threshold        */
```

---

## 3. Object Administration

### Database and Tablespace Hierarchy

```
DATABASE
  └── TABLESPACE (holds tables)
       └── TABLE
            └── INDEX → INDEXSPACE
```

### Creating a Database

```sql
CREATE DATABASE MYAPPDB
  STOGROUP SYSDEFLT
  BUFFERPOOL BP1
  INDEXBP BP2
  CCSID EBCDIC;
```

### Tablespace Types

| Type | Keyword | When to Use |
|------|---------|-------------|
| **Partition-by-growth (PBG)** | `MAXPARTITIONS n` | Default for most tables. Auto-grows partitions. |
| **Partition-by-range (PBR)** | `PARTITION BY ... USING` | Large tables with clear range keys (date, region). |
| **Universal (UTS)** | Required for both PBG and PBR (DB2 12+) | All new tablespaces should be UTS. |
| **Segmented** | `SEGSIZE n` | Legacy — migrate to UTS. |
| **Simple** | (default in old releases) | Legacy — do not create new. |

### Creating a PBR UTS Tablespace

```sql
CREATE TABLESPACE ORDERTS
  IN MYAPPDB
  USING STOGROUP SYSDEFLT
  PRIQTY 7200
  SECQTY 7200
  BUFFERPOOL BP1
  LOCKSIZE ROW
  MAXROWS 255
  SEGSIZE 64
  COMPRESS YES
  PARTITION BY RANGE(ORDER_DATE)
  (PARTITION 1 ENDING AT ('2026-03-31') INCLUSIVE,
   PARTITION 2 ENDING AT ('2026-06-30') INCLUSIVE,
   PARTITION 3 ENDING AT ('2026-09-30') INCLUSIVE,
   PARTITION 4 ENDING AT ('2026-12-31') INCLUSIVE);
```

### Creating a PBG UTS Tablespace

```sql
CREATE TABLESPACE CUSTTS
  IN MYAPPDB
  USING STOGROUP SYSDEFLT
  BUFFERPOOL BP1
  LOCKSIZE ROW
  SEGSIZE 32
  MAXPARTITIONS 256
  COMPRESS YES;
```

### Creating Tables

```sql
CREATE TABLE MYSCHEMA.ORDERS
  (ORDER_ID      INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
   CUSTOMER_ID   INTEGER NOT NULL,
   ORDER_DATE    DATE NOT NULL WITH DEFAULT,
   TOTAL_AMOUNT  DECIMAL(15,2) NOT NULL DEFAULT 0,
   STATUS        CHAR(2) NOT NULL DEFAULT 'OP',
   CREATED_TS    TIMESTAMP NOT NULL WITH DEFAULT,
   PRIMARY KEY (ORDER_ID))
  IN MYAPPDB.ORDERTS
  COMPRESS YES
  APPEND NO;
```

### Partitioning Strategies

| Strategy | Best For | Example Key |
|----------|----------|-------------|
| **Date-based** | Time-series data, transaction logs | `ORDER_DATE`, `CREATED_TS` |
| **Region-based** | Geographic data | `REGION_CODE`, `COUNTRY` |
| **Hash-modulo** | Even distribution when no natural range | `MOD(CUSTOMER_ID, 16)` |

### Compression

```sql
-- Enable compression on existing tablespace
ALTER TABLESPACE MYAPPDB.ORDERTS COMPRESS YES;
-- Compression takes effect after next REORG
```

Compression saves DASD and reduces I/O. Typical savings: 50-70% for repetitive business data. CPU trade-off is minimal on modern z15/z16 with hardware compression (zEDC).

---

## 4. Binding — Plans and Packages

### Concepts

| Object | Contains | Scope |
|--------|----------|-------|
| **DBRM** | SQL statements extracted by precompiler | Library member (PDS) |
| **Package** | Bound DBRM — one per program per collection | Stored in DB2 directory (SPT01) |
| **Plan** | Container referencing one or more packages via PKLIST | Executable unit at runtime |

### BIND PACKAGE

```jcl
//BINDPKG  EXEC PGM=IKJEFT01,DYNAMNBR=20
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD *
  DSN SYSTEM(DB2P)
  BIND PACKAGE(COLLID01) -
       MEMBER(MYPRGRM) -
       LIBRARY('MYAPP.PROD.DBRM') -
       ACT(REP) -
       ISOLATION(CS) -
       CURRENTDATA(NO) -
       VALIDATE(BIND) -
       EXPLAIN(YES) -
       RELEASE(COMMIT) -
       QUALIFIER(MYSCHEMA) -
       ENCODING(EBCDIC)
  END
/*
```

### BIND PLAN

```jcl
//BINDPLN  EXEC PGM=IKJEFT01,DYNAMNBR=20
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD *
  DSN SYSTEM(DB2P)
  BIND PLAN(MYPLAN) -
       PKLIST(COLLID01.*) -
       ACT(REP) -
       ISOLATION(CS) -
       VALIDATE(BIND) -
       CURRENTDATA(NO) -
       ACQUIRE(USE) -
       RELEASE(COMMIT)
  END
/*
```

### Key BIND Options

| Option | Values | Recommendation |
|--------|--------|----------------|
| **VALIDATE** | BIND / RUN | BIND for production — catches missing objects at bind time |
| **ISOLATION** | UR / CS / RS / RR | CS (cursor stability) for most OLTP; RR for batch requiring repeatable reads |
| **CURRENTDATA** | YES / NO | NO for better performance (avoids lock escalation) unless app needs guaranteed currency |
| **RELEASE** | COMMIT / DEALLOCATE | COMMIT for OLTP (frees locks); DEALLOCATE for batch (avoids rebind overhead) |
| **ACQUIRE** | USE / ALLOCATE | USE for OLTP; ALLOCATE for batch (locks all at plan allocation) |
| **REOPT** | NONE / ALWAYS / ONCE / AUTO | AUTO (DB2 12+) lets optimizer decide; ALWAYS for variable host-variable skew |
| **EXPLAIN** | YES / NO | YES to populate PLAN_TABLE for access path review |

### REBIND

Rebind to pick up new statistics or changed ZPARMs:

```
DSN SYSTEM(DB2P)
REBIND PACKAGE(COLLID01.MYPRGRM) EXPLAIN(YES)
END
```

For mass rebind of all packages in a collection:

```
DSN SYSTEM(DB2P)
REBIND PACKAGE(COLLID01.(*)) EXPLAIN(YES)
END
```

### Plan vs Package Trade-offs

| Concern | Plan-only (legacy) | Package-based (modern) |
|---------|--------------------|----------------------|
| Granularity | All SQL in one unit | One program per package |
| Rebind impact | Entire plan rebound | Individual package rebound |
| Versioning | Not supported | Multiple versions via BIND ... ACTION(ADD) |
| Recommended | No (legacy only) | Yes — always use packages |

---

## 5. Utilities

This is the most operationally critical section. DB2 utilities run as batch jobs via JCL.

### Common JCL Pattern for DB2 Utilities

```jcl
//UTILSTEP EXEC PGM=DSNUTILB,PARM='DB2P,xxxxxxxx',REGION=0M
//STEPLIB  DD DISP=SHR,DSN=DB2.V13.SDSNLOAD
//SYSPRINT DD SYSOUT=*
//SYSUDUMP DD SYSOUT=*
//UTPRINT  DD SYSOUT=*
//SYSIN    DD *
  <utility control statements>
/*
//SORTOUT  DD UNIT=SYSDA,SPACE=(CYL,(100,50))
//SORTWK01 DD UNIT=SYSDA,SPACE=(CYL,(100,50))
//SORTWK02 DD UNIT=SYSDA,SPACE=(CYL,(100,50))
//SORTWK03 DD UNIT=SYSDA,SPACE=(CYL,(100,50))
//SORTWK04 DD UNIT=SYSDA,SPACE=(CYL,(100,50))
```

The `xxxxxxxx` in PARM is the utility ID (1-16 characters). Each running utility must have a unique ID within the subsystem.

### REORG TABLESPACE

Reorganizes data to reclaim fragmented space and restore clustering order.

```jcl
//REORGTS  EXEC PGM=DSNUTILB,PARM='DB2P,RG01ORDS',REGION=0M
//STEPLIB  DD DISP=SHR,DSN=DB2.V13.SDSNLOAD
//SYSPRINT DD SYSOUT=*
//UTPRINT  DD SYSOUT=*
//SYSREC   DD DSN=MYAPP.REORG.SYSREC,
//            DISP=(NEW,DELETE,CATLG),
//            UNIT=SYSDA,SPACE=(CYL,(500,100))
//SORTOUT  DD UNIT=SYSDA,SPACE=(CYL,(200,50))
//SORTWK01 DD UNIT=SYSDA,SPACE=(CYL,(200,50))
//SORTWK02 DD UNIT=SYSDA,SPACE=(CYL,(200,50))
//SORTWK03 DD UNIT=SYSDA,SPACE=(CYL,(200,50))
//SORTWK04 DD UNIT=SYSDA,SPACE=(CYL,(200,50))
//SYSIN    DD *
  REORG TABLESPACE MYAPPDB.ORDERTS
    SHRLEVEL CHANGE
    STATISTICS TABLE(ALL) INDEX(ALL) REPORT NO
    COPYDDN(SYSCOPY)
    SORTDEVT SYSDA
    SORTNUM 4
    LOG NO
    TIMEOUT TERM
/*
//SYSCOPY  DD DSN=MYAPP.REORG.ICOPY,
//            DISP=(NEW,CATLG,CATLG),
//            UNIT=SYSDA,SPACE=(CYL,(200,50))
```

**SHRLEVEL options:**

| SHRLEVEL | Access During REORG | Use Case |
|----------|-------------------|----------|
| **NONE** | No access (drain lock) | Never in production during business hours |
| **REFERENCE** | Read-only access | Batch windows with no updates |
| **CHANGE** | Full read/write access | Online REORG for 24x7 systems |

**Inline COPY and STATS:** the example above includes `STATISTICS TABLE(ALL) INDEX(ALL)` (inline RUNSTATS) and `COPYDDN(SYSCOPY)` (inline image copy). This avoids separate utility runs post-REORG.

### REORG INDEX

```jcl
//SYSIN    DD *
  REORG INDEX(MYSCHEMA.ORDERS_PK)
    SHRLEVEL CHANGE
    STATISTICS INDEX(ALL)
    SORTDEVT SYSDA
    SORTNUM 4
/*
```

### RUNSTATS

Collects statistics for the optimizer. **Must run after REORG and LOAD.**

```jcl
//RUNSTATS EXEC PGM=DSNUTILB,PARM='DB2P,RS01ORDS',REGION=0M
//STEPLIB  DD DISP=SHR,DSN=DB2.V13.SDSNLOAD
//SYSPRINT DD SYSOUT=*
//UTPRINT  DD SYSOUT=*
//SYSIN    DD *
  RUNSTATS TABLESPACE MYAPPDB.ORDERTS
    TABLE(ALL)
      COLUMN(ALL)
      COLGROUP(ORDER_DATE, STATUS)
      FREQVAL COUNT 20 BOTH
      HISTOGRAM NUMQUANTILES 100
    INDEX(ALL)
      KEYCARD
    SHRLEVEL CHANGE
    REPORT NO
    UPDATE ALL
/*
```

**Key RUNSTATS options:**

| Option | Purpose |
|--------|---------|
| `FREQVAL COUNT n` | Collect top-n most frequent values — critical for skewed columns |
| `HISTOGRAM NUMQUANTILES n` | Distribution histogram for range predicates |
| `KEYCARD` | Full key cardinality for composite indexes |
| `COLGROUP(col1, col2)` | Multi-column cardinality stats for correlated predicates |
| `SHRLEVEL CHANGE` | Collect stats without stopping concurrent access |
| `UPDATE ALL` | Update catalog with all collected stats |

### COPY (Image Copy)

```jcl
//IMGCOPY  EXEC PGM=DSNUTILB,PARM='DB2P,IC01ORDS',REGION=0M
//STEPLIB  DD DISP=SHR,DSN=DB2.V13.SDSNLOAD
//SYSPRINT DD SYSOUT=*
//UTPRINT  DD SYSOUT=*
//SYSCOPY  DD DSN=MYAPP.ORDERTS.FULLCPY.D260331,
//            DISP=(NEW,CATLG,CATLG),
//            UNIT=SYSDA,SPACE=(CYL,(300,50))
//SYSIN    DD *
  COPY TABLESPACE MYAPPDB.ORDERTS
    FULL YES
    SHRLEVEL REFERENCE
    COPYDDN(SYSCOPY)
/*
```

**Copy types:**

| Type | Keyword | When |
|------|---------|------|
| Full image copy | `FULL YES` | After REORG, LOAD REPLACE, weekly baseline |
| Incremental copy | `FULL NO CHANGELIMIT(10)` | Daily — only changed pages since last full copy |
| Concurrent copy | `SHRLEVEL CHANGE` | Minimal disruption, uses log to resolve in-flight changes |

### RECOVER

```jcl
//RECOVER  EXEC PGM=DSNUTILB,PARM='DB2P,RC01ORDS',REGION=0M
//STEPLIB  DD DISP=SHR,DSN=DB2.V13.SDSNLOAD
//SYSPRINT DD SYSOUT=*
//UTPRINT  DD SYSOUT=*
//SYSIN    DD *
  RECOVER TABLESPACE MYAPPDB.ORDERTS
    TOLOGPOINT X'00000ABC12340000'
    TORBA X'00000ABC12340000'
/*
```

Point-in-time recovery:

```
  RECOVER TABLESPACE MYAPPDB.ORDERTS
    TOPOINT IN TIME '2026-03-31-10.30.00'
```

Recovery to current: simply `RECOVER TABLESPACE MYAPPDB.ORDERTS` with no TORBA/TOLOGPOINT — applies image copy + all subsequent log records.

### LOAD

```jcl
//LOADDATA EXEC PGM=DSNUTILB,PARM='DB2P,LD01ORDS',REGION=0M
//STEPLIB  DD DISP=SHR,DSN=DB2.V13.SDSNLOAD
//SYSPRINT DD SYSOUT=*
//UTPRINT  DD SYSOUT=*
//SYSREC   DD DSN=MYAPP.ORDERS.LOADDATA,DISP=SHR
//SYSIN    DD *
  LOAD DATA INDDN(SYSREC)
    INTO TABLE MYSCHEMA.ORDERS
    REPLACE
    LOG NO
    ENFORCE CONSTRAINTS
    STATISTICS TABLE(ALL) INDEX(ALL)
    COPYDDN(SYSCOPY)
    (ORDER_ID     POSITION(1)   INTEGER,
     CUSTOMER_ID  POSITION(5)   INTEGER,
     ORDER_DATE   POSITION(9)   DATE EXTERNAL,
     TOTAL_AMOUNT POSITION(19)  DECIMAL EXTERNAL(15,2),
     STATUS       POSITION(35)  CHAR(2))
/*
//SYSCOPY  DD DSN=MYAPP.ORDERTS.LOADCPY.D260331,
//            DISP=(NEW,CATLG,CATLG),
//            UNIT=SYSDA,SPACE=(CYL,(300,50))
```

| LOAD Option | REPLACE | RESUME(YES) |
|-------------|---------|-------------|
| Existing data | Deleted first | Appended to |
| COPY required after | Yes (mandatory) | Yes (recommended) |
| LOG NO effect | No logging — faster but breaks recovery chain | Same |

### QUIESCE

Establishes a recovery point (quiesce point) without taking a full copy:

```jcl
//SYSIN    DD *
  QUIESCE TABLESPACE MYAPPDB.ORDERTS
/*
```

### CHECK DATA / CHECK INDEX / CHECK LOB

Verifies structural integrity:

```jcl
//SYSIN    DD *
  CHECK DATA TABLESPACE MYAPPDB.ORDERTS
    SCOPE ALL
    SORTDEVT SYSDA
    SORTNUM 4
/*
```

```jcl
//SYSIN    DD *
  CHECK INDEX(ALL) TABLESPACE MYAPPDB.ORDERTS
    SHRLEVEL REFERENCE
    SORTDEVT SYSDA
    SORTNUM 4
/*
```

### MODIFY RECOVERY

Deletes old image copy and log records from SYSIBM.SYSCOPY to free catalog space:

```jcl
//SYSIN    DD *
  MODIFY RECOVERY TABLESPACE MYAPPDB.ORDERTS
    DELETE AGE(90)
/*
```

---

## 6. Performance — EXPLAIN and Access Path Analysis

### EXPLAIN Infrastructure

Create the EXPLAIN tables under the binder's schema:

```sql
CREATE TABLE MYSCHEMA.PLAN_TABLE LIKE DSN8C13.PLAN_TABLE IN MYAPPDB.EXPLTS;
CREATE TABLE MYSCHEMA.DSN_STATEMNT_TABLE LIKE DSN8C13.DSN_STATEMNT_TABLE IN MYAPPDB.EXPLTS;
CREATE TABLE MYSCHEMA.DSN_FUNCTION_TABLE LIKE DSN8C13.DSN_FUNCTION_TABLE IN MYAPPDB.EXPLTS;
CREATE TABLE MYSCHEMA.DSN_FILTER_TABLE LIKE DSN8C13.DSN_FILTER_TABLE IN MYAPPDB.EXPLTS;
CREATE TABLE MYSCHEMA.DSN_PREDICAT_TABLE LIKE DSN8C13.DSN_PREDICAT_TABLE IN MYAPPDB.EXPLTS;
```

### Running EXPLAIN

Inline with BIND:

```
BIND PACKAGE(COLLID01) MEMBER(MYPRGRM) LIBRARY('MYAPP.PROD.DBRM') EXPLAIN(YES)
```

Ad-hoc:

```sql
EXPLAIN ALL SET QUERYNO = 1001 FOR
  SELECT O.ORDER_ID, O.ORDER_DATE, C.CUSTOMER_NAME
  FROM MYSCHEMA.ORDERS O
    INNER JOIN MYSCHEMA.CUSTOMERS C
    ON O.CUSTOMER_ID = C.CUSTOMER_ID
  WHERE O.ORDER_DATE BETWEEN '2026-01-01' AND '2026-03-31'
    AND O.STATUS = 'CL';
```

### Reading PLAN_TABLE

```sql
SELECT QUERYNO, QBLOCKNO, PLANNO, METHOD, CREATOR, TNAME,
       ACCESSTYPE, MATCHCOLS, ACCESSNAME, INDEXONLY,
       PREFETCH, SORTC_UNIQ, SORTC_JOIN, SORTC_ORDERBY,
       SORTC_GROUPBY, TSLOCKMODE, TIMESTAMP
FROM MYSCHEMA.PLAN_TABLE
WHERE QUERYNO = 1001
ORDER BY QUERYNO, QBLOCKNO, PLANNO;
```

### Access Types

| ACCESSTYPE | Meaning | Performance |
|------------|---------|-------------|
| **I** | Index access | Good — using an index |
| **I1** | One-fetch index | Best — unique key fetch |
| **R** | Tablespace scan | Worst for OLTP (OK for batch/small tables) |
| **M** | Multiple index access (RID list intersection) | Acceptable |
| **MX** | Index scan via multiple index ORing | Acceptable |
| **N** | Index scan (IN-list) | Good |

### Predicate Analysis

| Category | Stage | Performance |
|----------|-------|-------------|
| **Indexable + Stage 1** | Evaluated during index access | Best — reduces data read |
| **Non-indexable + Stage 1** | Evaluated by Data Manager after page read | Acceptable |
| **Stage 2** | Evaluated by Relational Data System after Data Manager | Worst — all rows read from storage |

Common Stage 2 traps:

| Expression | Stage | Fix |
|------------|-------|-----|
| `SUBSTR(COL, 1, 3) = 'ABC'` | Stage 2 | Use `COL LIKE 'ABC%'` |
| `COL1 + COL2 = 100` | Stage 2 | Rewrite or use generated column |
| `YEAR(DATE_COL) = 2026` | Stage 2 | Use `DATE_COL BETWEEN '2026-01-01' AND '2026-12-31'` |
| `VALUE(COL, 0) = 5` | Stage 2 | Use `(COL = 5 OR COL IS NULL)` |
| `COL <> 'X'` | Stage 2 (not indexable) | Restructure query if possible |

### DSN_STATEMNT_TABLE — Statement-Level Cost

```sql
SELECT QUERYNO, PROCMS, PROCSU, COST_CATEGORY, REASON_CODE
FROM MYSCHEMA.DSN_STATEMNT_TABLE
WHERE QUERYNO = 1001;
```

`PROCMS` = estimated milliseconds. `COST_CATEGORY` = 'A' (optimal), 'B' (suboptimal — missing index/stats), 'C' (expensive — tablespace scan).

### RID Pool and Sort Optimization

The RID pool stores Record IDs during list prefetch and multiple index access. If the RID pool overflows, DB2 falls back to a tablespace scan.

```
-DB2P DISPLAY BUFFERPOOL(BP1) DETAIL(*)
```

Check `RID POOL FAIL` count. If non-zero, increase MAXRBLK in ZPARM.

Sort work files: allocate sufficient SORTWK datasets. DB2 uses in-memory sort when possible; overflow goes to SORTWK. Monitor `SORT OVERFLOW` in DB2 accounting trace (IFCID 3).

### IFCID Traces

IFCID (Instrumentation Facility Component Identifier) traces collect detailed performance data:

| IFCID | Data | Common Use |
|-------|------|-----------|
| 3 | Accounting (per-thread summary) | Workload analysis |
| 239 | SQL text of dynamic SQL | Finding expensive queries |
| 316 | RealTime statistics (tablespace) | Automated REORG/RUNSTATS triggers |
| 317 | RealTime statistics (index) | Automated REORG/RUNSTATS triggers |
| 318 | RealTime statistics (table) | Row count changes |
| 400-402 | Lock contention detail | Deadlock and timeout diagnosis |

Starting a trace:

```
-DB2P START TRACE(PERFM) DEST(SMF) CLASS(1,2,3) IFCID(3,239)
-DB2P STOP TRACE(PERFM) TNO(01)
```

### RMF / SMF Data

SMF Type 101 (DB2 accounting) and Type 102 (DB2 statistics) records feed into tools like IBM Db2 Administration Tool, BMC MainView, or OMEGAMON. Use these for long-term trend analysis.

---

## 7. Data Sharing

### Overview

DB2 data sharing allows multiple DB2 subsystems (members) on different LPARs to share the same data concurrently. Uses a Parallel Sysplex with coupling facility structures.

### Architecture Components

| Component | Coupling Facility Structure | Purpose |
|-----------|---------------------------|---------|
| **Lock structure** | IRLM lock table | Global lock management across members |
| **SCA** (Shared Communications Area) | SCA structure | DB2 inter-member messaging |
| **Group buffer pools** | GBP0-GBPn | Cross-member page caching and coherency |

### Member-Specific vs Group-Level Commands

```
// Member-specific (only affects the member you issue it on):
-DB2P DISPLAY DATABASE(MYAPPDB) SPACENAM(ORDERTS)

// Group-level (affects all members — use GROUP keyword):
-DB2G DISPLAY DATABASE(MYAPPDB) SPACENAM(ORDERTS) SCOPE(GROUP)
-DB2G DISPLAY GROUPBUFFERPOOL(GBP0) DETAIL(*)
-DB2G START DATABASE(MYAPPDB) SPACENAM(ORDERTS) ACCESS(RW) SCOPE(GROUP)
```

### Coupling Facility Sizing

Key considerations:

- **Lock structure:** size based on max concurrent locks across all members. Under-sizing causes lock structure full (LSF) events and false contention.
- **SCA:** relatively small; size per IBM recommendations.
- **GBP:** size based on inter-member read/write ratio. Higher cross-invalidation = larger GBP needed.

### Data Sharing Performance Concerns

| Issue | Symptom | Fix |
|-------|---------|-----|
| GBP XI (cross-invalidation) | High XI ratio in `-DISPLAY GROUPBUFFERPOOL` | Reduce cross-member writes to same pages; partition workload by member |
| False contention | Lock waits with no apparent logical conflict | Increase lock structure size; use hash algorithm 2 |
| Castout delays | Pages not written from GBP to DASD timely | Increase castout owners; tune CLASST threshold |

---

## 8. Security

### RACF Integration

DB2 for z/OS uses RACF (or compatible ESM) for external security. Two levels:

1. **Connection security** — controls who can connect to DB2 (RACF class DSNR)
2. **Object security** — controls who can access DB2 objects (DB2 GRANT/REVOKE or RACF class DSNADM)

### RACF Resource Classes

| Class | Resource Format | Controls |
|-------|-----------------|----------|
| **DSNR** | `DB2P.DISTSERV`, `DB2P.BATCH` | Connection type allowed |
| **DSNADM** | `DB2P.SYSADM`, `DB2P.SYSCTRL` | Administrative authorities |
| **DSNR** subsystem access | `DB2P.RRSAF`, `DB2P.CICS.*` | Subsystem-level access |

### Authorization IDs

| Type | Source | Example |
|------|--------|---------|
| **Primary AuthID** | From RACF sign-on (TSO user, batch JOB card) | `USRPRD01` |
| **Secondary AuthIDs** | RACF group memberships | `GRPPROD`, `GRPDBA` |
| **CURRENT SQLID** | SET CURRENT SQLID | Controls which AuthID is used for object creation |

### GRANT / REVOKE

```sql
-- Grant SELECT on a table
GRANT SELECT ON TABLE MYSCHEMA.ORDERS TO USRAPP01;

-- Grant with GRANT option (can re-grant)
GRANT SELECT, INSERT, UPDATE ON TABLE MYSCHEMA.ORDERS
  TO USRDBA01 WITH GRANT OPTION;

-- Grant EXECUTE on a package
GRANT EXECUTE ON PACKAGE COLLID01.MYPRGRM TO USRAPP01;

-- Grant to a RACF group (secondary AuthID)
GRANT SELECT ON TABLE MYSCHEMA.ORDERS TO GRPPROD;

-- Revoke
REVOKE INSERT ON TABLE MYSCHEMA.ORDERS FROM USRAPP01;
```

### Row and Column Access Control (RCAC)

DB2 12+ supports fine-grained access:

```sql
-- Column mask: hide salary from non-HR users
CREATE MASK MYSCHEMA.SALARY_MASK ON MYSCHEMA.EMPLOYEES
  FOR COLUMN SALARY RETURN
    CASE WHEN VERIFY_GROUP_FOR_USER(SESSION_USER, 'GRPHR') = 1
         THEN SALARY
         ELSE 0.00
    END
  ENABLE;

-- Row permission: users see only their department
CREATE PERMISSION MYSCHEMA.DEPT_PERM ON MYSCHEMA.EMPLOYEES
  FOR ROWS WHERE DEPT_CODE IN (
    SELECT DEPT_CODE FROM MYSCHEMA.USER_DEPTS
    WHERE USER_ID = SESSION_USER)
  ENFORCED FOR ALL ACCESS
  ENABLE;

-- Activate RCAC on the table
ALTER TABLE MYSCHEMA.EMPLOYEES ACTIVATE ROW ACCESS CONTROL ACTIVATE COLUMN ACCESS CONTROL;
```

### Trusted Contexts

Allow credential propagation from middleware without password re-authentication:

```sql
CREATE TRUSTED CONTEXT WEBCTX
  BASED UPON CONNECTION USING SYSTEM AUTHID WEBSRVID
  ATTRIBUTES (JOBNAME 'WASSVR*')
  WITH USE FOR USRAPP01 WITHOUT AUTHENTICATION,
               USRAPP02 WITHOUT AUTHENTICATION
  ENABLE;
```

### Audit Traces

```
-DB2P START TRACE(AUDIT) DEST(SMF) CLASS(1,2,3,4,5,6,7,8)
```

Audit IFCID classes: 1 = access attempts, 2 = GRANT/REVOKE, 3 = CREATE/ALTER/DROP, 4 = first read/write, 5 = BIND, 6 = authority checks, 7 = changes to audit policy, 8 = utility execution.

---

## 9. Monitoring and Diagnostics

### -DISPLAY Commands

These are the DBA's primary real-time diagnostic tools:

```
// Database/tablespace status
-DB2P DISPLAY DATABASE(MYAPPDB) SPACENAM(ORDERTS) LOCKS CLAIMERS USE

// Active threads
-DB2P DISPLAY THREAD(*) TYPE(*)

// Specific plan's threads
-DB2P DISPLAY THREAD(*) TYPE(*) PLAN(MYPLAN)

// Buffer pool summary
-DB2P DISPLAY BUFFERPOOL(BP1) DETAIL(*)

// Log status
-DB2P DISPLAY LOG

// Utility status
-DB2P DISPLAY UTILITY(*)

// Archive log status
-DB2P DISPLAY ARCHIVE
```

### Restrictive Status Codes

When `-DISPLAY DATABASE` shows abnormal status:

| Status | Meaning | Resolution |
|--------|---------|------------|
| **RECP** | Recovery pending | Run RECOVER utility |
| **CHKP** | CHECK pending | Run CHECK DATA |
| **COPY** | Copy pending | Run COPY (image copy) |
| **RBDP** | REBUILD pending | Run REBUILD INDEX |
| **LPL** | Logical page list (damaged pages) | Run RECOVER to clear |
| **GRECP** | Group recovery pending (data sharing) | Run RECOVER on any member |
| **STOP** | Stopped | START DATABASE to resume access |
| **UT** | Utility running | Wait or TERM UTILITY |

Resolving pending states:

```
// Recovery pending
-DB2P START DATABASE(MYAPPDB) SPACENAM(ORDERTS) ACCESS(RO)
// Then run RECOVER utility, then:
-DB2P START DATABASE(MYAPPDB) SPACENAM(ORDERTS) ACCESS(RW)

// Terminate a hung utility
-DB2P TERM UTILITY(RG01ORDS)
```

### OMEGAMON for DB2

IBM OMEGAMON (or BMC MainView for DB2) provides real-time monitoring dashboards with drill-down into:
- Thread activity and SQL elapsed time
- Lock contention and deadlocks
- Buffer pool hit ratios
- Dynamic SQL cache efficiency
- Coupling facility metrics (data sharing)

### DSNACCOR / DSNACCOX — Access Path Advisory

These stored procedures identify packages with inefficient access paths that would benefit from REBIND:

```sql
CALL SYSPROC.DSNACCOX(
  'MYSCHEMA',     -- qualifier
  '',             -- owner
  'COLLID01',     -- collection
  '',             -- package name (blank = all)
  '',             -- planname
  1,              -- query type (1 = all)
  'Y',            -- check rebind recommended
  NULL            -- output table
);
```

Output in `DSNACCOX_OUTPUT` table identifies packages where:
- Statistics have changed significantly since last BIND
- Access paths have degraded
- New indexes are available but not used

### DB2 Accounting and Statistics Reports

```
// Start accounting trace
-DB2P START TRACE(ACCTG) DEST(SMF) CLASS(1,2,3)

// Start statistics trace
-DB2P START TRACE(STAT) DEST(SMF) CLASS(1,3,4,5,6)
```

Key SMF record types:
- **SMF 101** — DB2 accounting (per-thread resource usage)
- **SMF 102** — DB2 statistics (subsystem-wide counters)
- **SMF 100** — DB2 trace data (IFCIDs)

---

## 10. Catalog and Directory

### Catalog (SYSIBM Tables)

The DB2 catalog is a set of tables in the `SYSIBM` schema describing all DB2 objects. Key tables:

| Table | Contents | Common DBA Query |
|-------|----------|-----------------|
| `SYSIBM.SYSTABLES` | All tables and views | Find tables by schema/name |
| `SYSIBM.SYSCOLUMNS` | Column definitions | Check column types, nullability |
| `SYSIBM.SYSINDEXES` | Index definitions | Find indexes on a table |
| `SYSIBM.SYSTABLESPACE` | Tablespace definitions | Check buffer pool assignments |
| `SYSIBM.SYSPLAN` | Bound plans | Audit plan binds |
| `SYSIBM.SYSPACKAGE` | Bound packages | Check package versions |
| `SYSIBM.SYSCOPY` | Image copy history | Recovery chain validation |
| `SYSIBM.SYSRELS` | Referential integrity | Find foreign key relationships |
| `SYSIBM.SYSPROCEDURES` | Stored procedures | Catalog stored procs |
| `SYSIBM.SYSTABSTATS` | Table-level statistics | Optimizer stats per partition |
| `SYSIBM.SYSINDEXSTATS` | Index-level statistics | Optimizer stats per index partition |

### Common Catalog Queries

```sql
-- List all tables in a schema
SELECT NAME, TYPE, DBNAME, TSNAME, CARDF, NPAGES
FROM SYSIBM.SYSTABLES
WHERE CREATOR = 'MYSCHEMA'
ORDER BY NAME;

-- Find all indexes on a table
SELECT I.NAME, I.UNIQUERULE, I.CLUSTERING, I.NLEAF, I.NLEVELS,
       I.FIRSTKEYCARDF, I.FULLKEYCARDF
FROM SYSIBM.SYSINDEXES I
WHERE I.TBCREATOR = 'MYSCHEMA' AND I.TBNAME = 'ORDERS'
ORDER BY I.CLUSTERING DESC, I.NAME;

-- Check image copy status for a tablespace
SELECT DSNAME, ICTYPE, SHRLEVEL, TIMESTAMP, DSNUM
FROM SYSIBM.SYSCOPY
WHERE DBNAME = 'MYAPPDB' AND TSNAME = 'ORDERTS'
  AND ICTYPE IN ('F', 'I')
ORDER BY TIMESTAMP DESC
FETCH FIRST 10 ROWS ONLY;

-- Find packages that reference a table
SELECT DNAME AS PACKAGE_NAME, DCOLLID AS COLLECTION, BQUALIFIER,
       DCONTOKEN, BINDTIME
FROM SYSIBM.SYSPACKDEP
WHERE BNAME = 'ORDERS' AND BQUALIFIER = 'MYSCHEMA'
ORDER BY BINDTIME DESC;

-- Check RealTime statistics for REORG candidates
SELECT DBNAME, NAME AS TSNAME, REORGINSERTS, REORGDELETES,
       REORGUPDATES, REORGDISORGLOB, REORGCLUSTERSENS, STATSLASTTIME
FROM SYSIBM.SYSTABLESPACESTATS
WHERE DBNAME = 'MYAPPDB'
ORDER BY REORGDISORGLOB DESC;

-- Find columns with missing stats (COLCARDF = -1)
SELECT TBCREATOR, TBNAME, NAME, COLTYPE, COLCARDF
FROM SYSIBM.SYSCOLUMNS
WHERE TBCREATOR = 'MYSCHEMA' AND COLCARDF = -1
ORDER BY TBNAME, COLNO;

-- List plans and their package lists
SELECT P.NAME AS PLANNAME, PL.COLLECTIONID, PL.NAME AS PACKAGENAME
FROM SYSIBM.SYSPLAN P
  INNER JOIN SYSIBM.SYSPKLIST PL ON P.NAME = PL.PLANNAME
WHERE P.NAME = 'MYPLAN'
ORDER BY PL.COLLECTIONID, PL.NAME;
```

### Directory (Internal Structures)

The DB2 directory is separate from the catalog — it contains internal structures DB2 needs at runtime. **Never modify directory tables directly.**

| Directory Table | Contains |
|-----------------|---------|
| **SPT01** | Skeleton package tables (bound package code) |
| **DBD01** | Database descriptors (internal object definitions) |
| **SCT02** | Skeleton cursor tables (plan skeletons) |
| **SYSLGRNX** | Log range index (maps objects to log RBAs for recovery) |
| **SYSUTILX** | Utility restart information |

### Catalog Health

```sql
-- Check catalog tablespace sizes
SELECT DBNAME, NAME, NACTIVEF, SPACE
FROM SYSIBM.SYSTABLESPACE
WHERE DBNAME = 'DSNDB06'
ORDER BY SPACE DESC;
```

DSNDB06 is the catalog database. Monitor its tablespace sizes and REORG regularly, especially SYSDBASE (DBD01 data), SYSPLAN, and SYSPACKAGE after heavy DDL or BIND activity.

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Skipping RUNSTATS after REORG | Optimizer uses stale statistics; query plans degrade; CPU cost increases across the subsystem | Always run RUNSTATS immediately after REORG; schedule them together as a single unit of work |
| BIND with VALIDATE(BIND) for dynamic SQL programs | Prevents execution of any SQL referencing objects not yet created at bind time; breaks phased deployments | Use VALIDATE(RUN) for programs with dynamic SQL; VALIDATE(BIND) only for static-only programs with stable schemas |
| Running COPY without CHANGELIMIT checks | Full image copies on unchanged tablespaces waste tape/DASD and extend batch windows | Use CHANGELIMIT on COPY utility; take incremental copies when change percentage is below threshold |
| Not monitoring DSNZPARM settings after migration | Default zparm values may not match workload after version upgrades; performance degrades silently | Review and tune critical zparms (EDMPOOL, MAXDBAT, CTHREAD, IDTHTOIN) after every DB2 version migration |
| Granting SYSADM instead of granular privileges | Violates least privilege; audit findings; one compromised ID can access every table in the subsystem | Use DBADM, PACKADM, and table-level grants; reserve SYSADM for DBA automation IDs only |

---

## Related Skills

| Topic | Skill |
|-------|-------|
| Python connectivity to DB2 z/OS | `python-enterprise-connectors` |
| RHEL database administration (PostgreSQL, MySQL, Redis) | `rhel-databases` |
| Ubuntu database administration | `ubuntu-databases` |
| Docker containers for DB2 LUW development | `docker-admin` |
| Performance profiling and load testing | `performance` |
