# z/OS Fundamentals and JCL

Reference file for the `ibm-mainframe` skill. Covers z/OS fundamentals, JCL syntax and patterns (JOB, EXEC, DD statements, procedures, conditional execution, GDGs).

## 1. z/OS Fundamentals

### Address Spaces and MVS Concepts

z/OS is a 64-bit operating system running on IBM Z hardware. Key concepts:

- **Address space** — Each running program gets its own virtual address space (up to 16 EB in 64-bit mode). Major address spaces: master scheduler, JES2/JES3, VTAM, TCAS (TSO), CICS, IMS.
- **LPAR (Logical Partition)** — A single physical mainframe (CPC) is divided into multiple LPARs, each running its own z/OS instance. LPARs share CPUs (CPs, zIIPs, zAAPs) via PR/SM (Processor Resource/Systems Manager).
- **Sysplex / Parallel Sysplex** — Multiple z/OS images (LPARs across CPCs) coupled together via Coupling Facility (CF) for shared workloads, data sharing, and high availability.
- **WLM (Workload Manager)** — Manages system resources across address spaces. Work is classified into service classes with performance goals (response time, velocity, discretionary).

### Batch vs Online

| Mode | Subsystem | Description |
|---|---|---|
| Batch | JES2/JES3 | Jobs submitted via JCL, scheduled by job entry subsystem, runs unattended |
| TSO/ISPF | TCAS | Interactive command-line (TSO) with panel-driven interface (ISPF) |
| CICS | CICS TS | Online transaction processing — screens, APIs, real-time |
| IMS | IMS TM/DB | Hierarchical database and transaction manager |
| USS | OMVS | UNIX System Services — POSIX shell, file system, TCP/IP applications |

### Dataset Naming Conventions

- Maximum 44 characters total.
- Composed of qualifiers separated by dots: `HLQ.SECOND.THIRD.FOURTH`
- Each qualifier: 1-8 characters, starts with letter or national character (@, #, $).
- High-level qualifier (HLQ) typically matches the TSO user ID or a project/application code.
- Examples: `PROD.PAYROLL.MASTER`, `DEV.APPX.COBOL.SRCLIB`, `SYS1.PARMLIB`

### Catalog Structure

- **Master catalog (MCAT)** — One per z/OS image. Contains system datasets and aliases pointing to user catalogs.
- **User catalogs (UCAT)** — ICF catalogs that hold entries for application datasets. Assigned via ALIAS entries in the master catalog.
- **Catalog search order:** JOBCAT/STEPCAT DD (deprecated) → master catalog alias → user catalog.
- Use `LISTCAT` (IDCAMS) to query catalog entries.

### DASD Volumes

- **DASD (Direct Access Storage Device)** — Disk storage. Common device types: 3390 (most common, ~56 GB per volume in model 54).
- **Volume serial (VOLSER)** — 1-6 character label identifying each DASD volume (e.g., `VOL001`, `PROD01`).
- **VTOC (Volume Table of Contents)** — On each volume, tracks which datasets reside on it and their extents.
- Tracks and cylinders: 3390 has 15 tracks/cylinder, 56,664 bytes/track.

---

## 2. JCL (Job Control Language)

### JOB Statement

```jcl
//PAYROLL  JOB (ACCT#,DEPT),'JOHN SMITH',
//         CLASS=A,
//         MSGCLASS=X,
//         MSGLEVEL=(1,1),
//         NOTIFY=&SYSUID,
//         REGION=0M,
//         TIME=1440
```

- `CLASS` — Input job class (determines initiator selection).
- `MSGCLASS` — Output class for job log (SYSOUT).
- `MSGLEVEL=(stmt,msg)` — (1,1) shows all JCL statements and all allocation messages.
- `NOTIFY=&SYSUID` — Send completion message to the submitting user.
- `REGION=0M` — Unlimited region (use cautiously; site standards may restrict).
- `TIME=1440` — CPU time limit in minutes (1440 = no limit).

### EXEC Statement

```jcl
//STEP01   EXEC PGM=MYCOBOL,PARM='PARAM1,PARAM2'
//STEP02   EXEC PGM=SORT
//STEP03   EXEC PROC=COBCLG,MEM=MYPROG
```

- `PGM=` — Program to execute from a load library (STEPLIB or link list).
- `PROC=` — Cataloged or in-stream procedure to invoke.
- `PARM=` — Parameters passed to the program (max 100 characters).

### DD Statement

```jcl
//* --- New sequential dataset ---
//OUTPUT   DD DSN=PROD.PAYROLL.REPORT,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(50,10),RLSE),
//            DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920),
//            UNIT=SYSALLDA

//* --- Existing dataset (shared read) ---
//INPUT    DD DSN=PROD.PAYROLL.MASTER,DISP=SHR

//* --- Temporary dataset (auto-deleted at job end) ---
//TEMP     DD DSN=&&TEMPFILE,
//            DISP=(NEW,PASS),
//            SPACE=(TRK,(100,50)),
//            DCB=(RECFM=FB,LRECL=200,BLKSIZE=27800)

//* --- SYSOUT (print to output class) ---
//SYSPRINT DD SYSOUT=*

//* --- In-stream data ---
//SYSIN    DD *
  SORT FIELDS=(1,10,CH,A)
/*

//* --- Concatenated datasets ---
//STEPLIB  DD DSN=PROD.LOAD.LIBRARY,DISP=SHR
//         DD DSN=TEST.LOAD.LIBRARY,DISP=SHR

//* --- Dummy (placeholder, no I/O) ---
//NULLFILE DD DUMMY
```

### DISP Parameter

`DISP=(status,normal-end,abnormal-end)`

| Status | Meaning |
|---|---|
| NEW | Create new dataset |
| OLD | Exclusive access to existing dataset |
| SHR | Shared read access to existing dataset |
| MOD | Append to existing (or NEW if not found) |

| Disposition | Meaning |
|---|---|
| DELETE | Delete dataset |
| KEEP | Keep but do not catalog |
| CATLG | Keep and catalog |
| PASS | Pass to next step (temporary) |
| UNCATLG | Uncatalog but keep on volume |

Common patterns:
- `DISP=(NEW,CATLG,DELETE)` — Create, catalog if OK, delete if abend.
- `DISP=SHR` — Shorthand for `DISP=(SHR,KEEP,KEEP)`.
- `DISP=(MOD,CATLG,CATLG)` — Append to existing; catalog either way.
- `DISP=(NEW,PASS)` — Temporary dataset passed to later step.

### SPACE Parameter

```jcl
SPACE=(unit,(primary,secondary,directory),RLSE,,ROUND)
```

- `unit` — TRK (tracks), CYL (cylinders), or block size (e.g., 27920).
- `primary` — Initial allocation.
- `secondary` — Each additional extent (up to 15 extents per volume, 123 with DFSMS multi-volume).
- `directory` — Number of 256-byte directory blocks (PDS only).
- `RLSE` — Release unused space after close.
- `ROUND` — Round to cylinder boundary (when unit is block size).

### DCB Parameter

```jcl
DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920)
```

| RECFM | Meaning |
|---|---|
| F | Fixed length |
| FB | Fixed blocked |
| V | Variable length |
| VB | Variable blocked |
| FBA/VBA | With ASA carriage control |
| U | Undefined (load modules) |

Let the system determine BLKSIZE by omitting it (DFSMS picks optimal size), or calculate: for FB, `BLKSIZE = LRECL * n` where `n * LRECL <= 27998` (half-track blocking for 3390).

### Symbolic Parameters and PROCs

```jcl
//* --- Cataloged procedure invocation ---
//STEP01   EXEC PROC=SORTPROC,
//         INPUT='PROD.DAILY.TRANS',
//         OUTPUT='PROD.DAILY.SORTED',
//         SORTKEY='1,10,CH,A'

//* --- PROC definition (in PROCLIB or in-stream) ---
//SORTPROC PROC INPUT=,OUTPUT=,SORTKEY=
//SORT     EXEC PGM=SORT
//SORTIN   DD DSN=&INPUT,DISP=SHR
//SORTOUT  DD DSN=&OUTPUT,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(10,5),RLSE),
//            DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920)
//SYSIN    DD *
  SORT FIELDS=(&SORTKEY)
/*
//SYSOUT   DD SYSOUT=*
//         PEND
```

### COND and IF/THEN/ELSE/ENDIF

```jcl
//* --- COND parameter (skip step if condition is TRUE) ---
//* Skip STEP03 if STEP01 RC > 4 OR STEP02 RC > 0
//STEP03   EXEC PGM=REPORT,
//         COND=((4,LT,STEP01),(0,LT,STEP02))

//* --- IF/THEN/ELSE (preferred, clearer logic) ---
//         IF (STEP01.RC = 0) THEN
//STEP02   EXEC PGM=PROCESS
//INPUT    DD DSN=PROD.DATA.FILE,DISP=SHR
//OUTPUT   DD DSN=PROD.RESULT.FILE,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(10,5),RLSE)
//         ELSE
//ERRSTEP  EXEC PGM=NOTIFY,PARM='STEP01 FAILED'
//         ENDIF

//* --- Nested and compound conditions ---
//         IF (STEP01.RC <= 4 & STEP02.RC = 0) THEN
//STEP03   EXEC PGM=FINAL
//         ENDIF
//         IF (STEP01.ABEND | STEP02.ABEND) THEN
//CLEANUP  EXEC PGM=IEFBR14
//DELFILE  DD DSN=PROD.TEMP.FILE,DISP=(OLD,DELETE)
//         ENDIF
```

### GDG References in JCL

```jcl
//* --- Write to next generation ---
//OUTPUT   DD DSN=PROD.DAILY.TRANS(+1),
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(50,10),RLSE),
//            DCB=(RECFM=FB,LRECL=200,BLKSIZE=27800)

//* --- Read current (most recent) generation ---
//INPUT    DD DSN=PROD.DAILY.TRANS(0),DISP=SHR

//* --- Read previous generation ---
//PREV     DD DSN=PROD.DAILY.TRANS(-1),DISP=SHR

//* --- Read all generations (concatenation) ---
//ALLIN    DD DSN=PROD.DAILY.TRANS,DISP=SHR
```

### Common JCL Errors

| Error | Cause | Fix |
|---|---|---|
| JCL ERROR — IEF621I | Invalid syntax (misspelled keyword, bad continuation) | Check column 72 continuation, comma placement |
| S B37 | Dataset out of space (no more extents on volume) | Increase SPACE primary/secondary, add volumes |
| S D37 | Dataset out of space (extent limit reached) | Increase primary allocation, use SMS multi-volume |
| S E37 | No more volumes available for dataset extension | Add VOLUME parameter or increase primary SPACE |
| S 013 | Member not found in PDS, or DCB conflict | Check member name, verify RECFM/LRECL match |
| S 213 | Dataset not found or volume not mounted | Check DSN spelling, verify cataloged, check DISP |
| S 722 | SYSOUT lines exceeded (output limit) | Increase OUTLIM or reduce output volume |
| S 806 | Load module not found | Check STEPLIB, JOBLIB, or linklist |
| S 0C7 | Data exception (decimal arithmetic on bad data) | Check input data for non-numeric characters |
| S 0C4 | Protection exception (bad memory reference) | Check program for subscript errors, buffer overflows |
| S 322 | CPU time limit exceeded | Increase TIME parameter, check for infinite loops |
| NOT CATLG 2 | Dataset already exists in catalog | Delete/uncatalog old dataset, or use different name |

---

## 3. Dataset Types

### Sequential (PS) — Physical Sequential

Single flat file. Records read/written sequentially. Simplest dataset type.

```jcl
//SEQFILE  DD DSN=PROD.PAYROLL.EXTRACT,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(20,5),RLSE),
//            DCB=(RECFM=FB,LRECL=150,BLKSIZE=27900)
```

### PDS — Partitioned Data Set

Library containing members (like a directory of files). Fixed directory at creation. Used for source code, JCL, load modules, PARMLIB.

```jcl
//PDSLIB   DD DSN=DEV.COBOL.SRCLIB,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(50,10,50)),
//            DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920),
//            DSNTYPE=PDS
```

- Directory blocks (3rd SPACE sub-parameter) must be specified at creation.
- Directory cannot grow — once full, you must compress (IEBCOPY COPY with same input/output) or reallocate.
- Member names: 1-8 characters.

### PDSE — Partitioned Data Set Extended

Improved PDS format. Dynamic directory (no compress needed), member-level sharing, program objects support.

```jcl
//PDSELIB  DD DSN=DEV.COBOL.SRCLIB,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(50,10)),
//            DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920),
//            DSNTYPE=LIBRARY
```

- `DSNTYPE=LIBRARY` creates a PDSE.
- No directory blocks needed in SPACE (system manages automatically).
- Cannot be placed on a non-SMS-managed volume.

### VSAM Types

| Type | Description | Key Access |
|---|---|---|
| KSDS | Key-Sequenced Data Set | Primary key + optional alternate indexes |
| ESDS | Entry-Sequenced Data Set | RBA (Relative Byte Address) — insertion order |
| RRDS | Relative Record Data Set | Relative record number (slot-based) |
| LDS | Linear Data Set | Byte-stream (used by DB2, data-in-memory) |

VSAM datasets are defined using IDCAMS (Access Method Services), not JCL DD statements. VSAM components:
- **Cluster** — The logical dataset name.
- **Data component** — Holds the actual records.
- **Index component** — B-tree index for KSDS (not present for ESDS/RRDS/LDS).

### Temporary Datasets

```jcl
//* --- System-generated name (&&) ---
//TEMP1    DD DSN=&&WORK,
//            DISP=(NEW,PASS),
//            SPACE=(CYL,(10,5)),
//            DCB=(RECFM=FB,LRECL=80)

//* --- Automatically deleted at job end ---
//* --- Passed between steps via DISP=(OLD,PASS) or DISP=(OLD,DELETE) ---
//STEP02   EXEC PGM=NEXT
//INPUT    DD DSN=&&WORK,DISP=(OLD,DELETE)
```

### GDG — Generation Data Group

A group of chronologically related datasets. Each generation is a separate sequential dataset.

```jcl
//* Defined via IDCAMS first (see IDCAMS section), then referenced in JCL:
//NEWGEN   DD DSN=PROD.DAILY.BACKUP(+1),
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(100,20),RLSE),
//            DCB=(RECFM=FB,LRECL=200,BLKSIZE=27800)
```

Absolute names look like: `PROD.DAILY.BACKUP.G0001V00`, `PROD.DAILY.BACKUP.G0002V00`.

### ALIAS

An alias is an alternate name pointing to an existing dataset or a user catalog. Defined via IDCAMS:

```
  DEFINE ALIAS (NAME(NEWHLQ) RELATE(UCAT.PROD))
```

This tells the master catalog that all datasets starting with `NEWHLQ` are in user catalog `UCAT.PROD`.

---

