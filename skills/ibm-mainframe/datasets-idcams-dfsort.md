# Datasets, IDCAMS, and DFSORT

Reference file for the `ibm-mainframe` skill. Covers dataset types (sequential, PDS, PDSE, VSAM), IDCAMS utility, and DFSORT/ICETOOL.

## 4. IDCAMS (Access Method Services)

### DEFINE CLUSTER — KSDS

```jcl
//DEFKSDS  EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
  DEFINE CLUSTER (                           -
           NAME(PROD.CUSTOMER.MASTER)        -
           INDEXED                           -
           RECORDSIZE(200 250)               -
           KEYS(10 0)                        -
           SHAREOPTIONS(2 3)                 -
           SPEED                             -
           FREESPACE(20 10)                  -
           CONTROLINTERVALSIZE(4096)         -
         )                                   -
         DATA (                              -
           NAME(PROD.CUSTOMER.MASTER.DATA)   -
           CYLINDERS(50 10)                  -
         )                                   -
         INDEX (                             -
           NAME(PROD.CUSTOMER.MASTER.INDEX)  -
           CYLINDERS(5 2)                    -
         )
  IF LASTCC > 0 THEN                        -
    SET MAXCC = 16
/*
```

- `INDEXED` — KSDS (default if KEYS specified).
- `RECORDSIZE(avg max)` — Average and maximum record size.
- `KEYS(length offset)` — Primary key: 10 bytes starting at position 0.
- `SHAREOPTIONS(crossregion crosssystem)` — Controls concurrent access.
  - Cross-region: 1=exclusive writes, 2=multiple readers/one writer, 3=multiple readers/writers (application handles integrity), 4=same as 3 with buffers refreshed.
- `SPEED` — Skip preformat (faster initial load). Use `RECOVERY` if loading may fail mid-way.
- `FREESPACE(ci% ca%)` — Reserve space for inserts (CI=control interval, CA=control area).

### DEFINE CLUSTER — ESDS

```jcl
  DEFINE CLUSTER (                           -
           NAME(PROD.AUDIT.LOG)              -
           NONINDEXED                        -
           RECORDSIZE(100 500)               -
           SHAREOPTIONS(2 3)                 -
         )                                   -
         DATA (                              -
           NAME(PROD.AUDIT.LOG.DATA)         -
           CYLINDERS(100 20)                 -
         )
```

### DEFINE CLUSTER — RRDS

```jcl
  DEFINE CLUSTER (                           -
           NAME(PROD.LOOKUP.TABLE)           -
           NUMBERED                          -
           RECORDSIZE(80 80)                 -
           SHAREOPTIONS(2 3)                 -
         )                                   -
         DATA (                              -
           NAME(PROD.LOOKUP.TABLE.DATA)      -
           CYLINDERS(10 5)                   -
         )
```

### REPRO — Copy / Load Data

```jcl
//* --- Load a VSAM KSDS from a flat file ---
//LOADVSAM EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//INFILE   DD DSN=PROD.CUSTOMER.FLATFILE,DISP=SHR
//OUTFILE  DD DSN=PROD.CUSTOMER.MASTER,DISP=SHR
//SYSIN    DD *
  REPRO INFILE(INFILE) OUTFILE(OUTFILE)             -
        COUNT(999999)                                -
        REPLACE
/*

//* --- Backup VSAM to sequential ---
//BACKUP   EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//INFILE   DD DSN=PROD.CUSTOMER.MASTER,DISP=SHR
//OUTFILE  DD DSN=PROD.CUSTOMER.BACKUP,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(50,10),RLSE),
//            DCB=(RECFM=VB,LRECL=254,BLKSIZE=27998)
//SYSIN    DD *
  REPRO INFILE(INFILE) OUTFILE(OUTFILE)
/*
```

### DELETE

```jcl
  DELETE PROD.CUSTOMER.MASTER CLUSTER PURGE
  IF LASTCC = 8 THEN                        -
    SET MAXCC = 0
  /* RC=8 means not found — acceptable for cleanup jobs */
```

- `CLUSTER` — Deletes data, index, and cluster entry.
- `PURGE` — Override retention period.

### ALTER

```jcl
  ALTER PROD.CUSTOMER.MASTER                 -
        FREESPACE(30 15)                     -
        SHAREOPTIONS(3 3)                    -
        BUFFERSPACE(1048576)
```

### LISTCAT

```jcl
  LISTCAT ENTRIES(PROD.CUSTOMER.MASTER)      -
          ALL

  /* List all datasets matching a pattern */
  LISTCAT LEVEL(PROD.CUSTOMER) ALL

  /* List only VSAM clusters in a catalog */
  LISTCAT CATALOG(UCAT.PROD)                -
          CLUSTER
```

### PRINT

```jcl
  /* Print first 100 records of a VSAM dataset */
  PRINT INFILE(INFILE) COUNT(100)            -
        CHARACTER

  /* Print records by key range */
  PRINT INFILE(INFILE)                       -
        FROMKEY(0000001000)                  -
        TOKEY(0000001999)                    -
        CHARACTER
```

### VERIFY

Resets the end-of-file marker after an abnormal close (e.g., abend during update):

```jcl
  VERIFY DATASET(PROD.CUSTOMER.MASTER)
```

Run VERIFY before accessing a VSAM dataset that may have been improperly closed.

### DEFINE ALTERNATEINDEX and PATH

```jcl
  /* Define an alternate index on customer name (positions 11-40) */
  DEFINE ALTERNATEINDEX (                    -
           NAME(PROD.CUSTOMER.AIX.NAME)      -
           RELATE(PROD.CUSTOMER.MASTER)      -
           KEYS(30 10)                       -
           NONUNIQUEKEY                      -
           UPGRADE                           -
           RECORDSIZE(50 200)                -
         )                                   -
         DATA (                              -
           NAME(PROD.CUSTOMER.AIX.NAME.DATA) -
           CYLINDERS(10 5)                   -
         )                                   -
         INDEX (                             -
           NAME(PROD.CUSTOMER.AIX.NAME.INDEX) -
           CYLINDERS(2 1)                    -
         )

  /* Build the alternate index */
  BLDINDEX INDATASET(PROD.CUSTOMER.MASTER)   -
           OUTDATASET(PROD.CUSTOMER.AIX.NAME)

  /* Define a path to access base cluster through the AIX */
  DEFINE PATH (                              -
           NAME(PROD.CUSTOMER.PATH.BYNAME)   -
           PATHENTRY(PROD.CUSTOMER.AIX.NAME) -
           UPDATE                            -
         )
```

### DEFINE GDG

```jcl
  DEFINE GDG (                               -
           NAME(PROD.DAILY.BACKUP)           -
           LIMIT(30)                         -
           NOEMPTY                           -
           SCRATCH                           -
         )
```

- `LIMIT(30)` — Keep up to 30 generations.
- `NOEMPTY` — When limit exceeded, only the oldest generation is rolled off. (`EMPTY` would uncatalog all.)
- `SCRATCH` — Delete the physical dataset when uncataloged. (`NOSCRATCH` keeps data on volume.)

---

## 5. DFSORT / ICETOOL

### Basic SORT

```jcl
//SORTJOB  EXEC PGM=SORT
//SORTIN   DD DSN=PROD.TRANS.DAILY,DISP=SHR
//SORTOUT  DD DSN=PROD.TRANS.SORTED,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(20,5),RLSE)
//SYSOUT   DD SYSOUT=*
//SYSIN    DD *
  SORT FIELDS=(1,10,CH,A,15,8,PD,D)
/*
```

Sort by character field (positions 1-10 ascending), then packed decimal field (positions 15-22 descending).

### Field Types

| Code | Type |
|---|---|
| CH | Character (EBCDIC) |
| ZD | Zoned decimal |
| PD | Packed decimal |
| BI | Binary |
| FI | Fixed-point integer |
| FL | Floating-point |
| AC | ASCII character |

### INCLUDE / OMIT (Filtering)

```jcl
  SORT FIELDS=(1,10,CH,A)
  INCLUDE COND=(25,2,CH,EQ,C'NY',|,
                25,2,CH,EQ,C'CA')

  /* Equivalent OMIT (exclude everything NOT NY or CA) */
  OMIT COND=(25,2,CH,NE,C'NY',&,
             25,2,CH,NE,C'CA')
```

Operators: `EQ`, `NE`, `GT`, `GE`, `LT`, `LE`, `&` (AND), `|` (OR).

### INREC / OUTREC (Record Reformatting)

```jcl
  SORT FIELDS=COPY
  INREC FIELDS=(1,10,15,8,30,20,C' INSERTED TEXT ')

  /* OUTREC with built-in functions */
  OUTREC FIELDS=(1,10,
                 15,8,ZD,EDIT=(TTTTTTTT.TT),
                 C',',
                 30,20,
                 80:X)
```

- `FIELDS=COPY` — Pass records through without sorting (just reformat or filter).
- `EDIT=(pattern)` — Format numeric output (T=digit, .=decimal point).
- `C'text'` — Insert literal text.
- `80:X` — Pad to position 80 with spaces.

### OUTFIL (Multiple Output Files)

```jcl
//SORTJOB  EXEC PGM=SORT
//SORTIN   DD DSN=PROD.TRANS.ALL,DISP=SHR
//OUT1     DD DSN=PROD.TRANS.EAST,DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(10,5),RLSE)
//OUT2     DD DSN=PROD.TRANS.WEST,DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(10,5),RLSE)
//SYSOUT   DD SYSOUT=*
//SYSIN    DD *
  SORT FIELDS=(1,10,CH,A)
  OUTFIL FNAMES=OUT1,INCLUDE=(25,4,CH,EQ,C'EAST')
  OUTFIL FNAMES=OUT2,INCLUDE=(25,4,CH,EQ,C'WEST')
/*
```

### SUM (Summarize Duplicate Keys)

```jcl
  SORT FIELDS=(1,10,CH,A)
  SUM FIELDS=(20,8,PD,30,8,PD)

  /* SUM FIELDS=NONE to deduplicate (remove duplicates, keep first) */
  SORT FIELDS=(1,10,CH,A)
  SUM FIELDS=NONE
```

### ICETOOL — Multi-Operation Utility

```jcl
//ICERUN   EXEC PGM=ICETOOL
//TOOLMSG  DD SYSOUT=*
//DFSMSG   DD SYSOUT=*
//INPUT    DD DSN=PROD.TRANS.DAILY,DISP=SHR
//RPT1     DD SYSOUT=*
//UNIQUE   DD DSN=PROD.TRANS.UNIQUE,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(10,5),RLSE)
//TOOLIN   DD *
  SORT FROM(INPUT) TO(UNIQUE) USING(SRT1)
  DISPLAY FROM(INPUT) LIST(RPT1) -
    HEADER('Transaction Report') -
    ON(1,10,CH) HEADER('Account') -
    ON(15,8,PD) HEADER('Amount') -
    ON(25,8,CH) HEADER('Date') -
    TOTAL('Grand Total') -
    COUNT('Record Count') -
    BLANK
/*
//SRT1CNTL DD *
  SORT FIELDS=(1,10,CH,A)
  SUM FIELDS=NONE
/*
```

ICETOOL operations: `SORT`, `COPY`, `DISPLAY`, `COUNT`, `SELECT`, `UNIQUE`, `RANGE`, `STATS`, `OCCUR`, `SPLICE`.

### SYMNAMES (Symbolic Field Names)

```jcl
//SYMNAMES DD *
  ACCOUNT,1,10,CH
  AMOUNT,15,8,PD
  REGION,25,4,CH
  TRANS_DATE,30,8,CH
/*
//SYSIN    DD *
  SORT FIELDS=(ACCOUNT,A,TRANS_DATE,A)
  INCLUDE COND=(REGION,EQ,C'EAST')
  OUTREC FIELDS=(ACCOUNT,C',',TRANS_DATE,C',',
                 AMOUNT,EDIT=(TTTTTTTT.TT))
/*
```

---

## 6. ISPF

### Panel Navigation

| Option | Panel | Purpose |
|---|---|---|
| 1 | View | Browse datasets (read-only) |
| 2 | Edit | Edit datasets and members |
| 3 | Utilities | Dataset utilities sub-menu |
| 3.1 | Library | PDS member list, operations |
| 3.2 | Dataset | Allocate, rename, delete datasets |
| 3.4 | Dslist | Dataset list (wildcard search) — most used panel |
| 4 | Foreground | Run programs interactively (COBOL compile, etc.) |
| 5 | Batch | Submit batch jobs |
| 6 | Command | TSO command entry |
| SD | SDSF | System Display and Search Facility (job output, spool) |

### ISPF 3.4 — Dataset List

Enter dataset name pattern with wildcards:
- `PROD.PAYROLL.**` — All datasets starting with PROD.PAYROLL
- `PROD.*.SRCLIB` — Any second qualifier

Line commands on dataset list:
- `E` — Edit
- `B` — Browse
- `I` — Info (shows DCB, SPACE, volume)
- `D` — Delete
- `R` — Rename
- `S` — Edit/select member list (for PDS/PDSE)
- `M` — Member list (browse)
- `Z` — Compress (PDS only)

### Edit Commands (Command Line)

| Command | Action |
|---|---|
| `F string` | Find string |
| `C old new ALL` | Change all occurrences |
| `L n` | Go to line n |
| `SORT 1 10` | Sort by columns 1-10 |
| `SAVE` | Save without exiting |
| `CANCEL` | Exit without saving |
| `SUBMIT` or `SUB` | Submit JCL as a job |
| `CUT` / `PASTE` | Clipboard operations |
| `RESET` | Clear line command errors |
| `HILITE JCL` | Syntax highlighting for JCL |
| `HILITE COBOL` | Syntax highlighting for COBOL |
| `TABS ON` | Enable logical tabs |
| `PROFILE` | Show current edit profile |
| `HEX ON` | Show hex display |
| `COLS` | Show column ruler |

### Line Commands

| Command | Action |
|---|---|
| `I` / `In` | Insert 1 or n blank lines after |
| `D` / `Dn` | Delete 1 or n lines |
| `R` / `Rn` | Repeat 1 or n times |
| `C` / `Cn` | Copy line(s) — use with `A` (after) or `B` (before) |
| `M` / `Mn` | Move line(s) — use with `A` or `B` |
| `A` | After — target for copy/move |
| `B` | Before — target for copy/move |
| `CC`/`CC` | Block copy (mark start and end) |
| `MM`/`MM` | Block move |
| `DD`/`DD` | Block delete |
| `X` / `Xn` | Exclude (hide) lines |
| `S` / `Sn` | Show excluded lines |
| `TE` | Text entry (free-form input mode) |
| `)n` | Shift right n columns |
| `(n` | Shift left n columns |

### Edit Macros

Edit macros are REXX or CLIST programs that automate edit operations:

```rexx
/* REXX edit macro — add standard header to member */
'ISREDIT MACRO'
'ISREDIT LINE_BEFORE 1 = " //*====================================="'
'ISREDIT LINE_BEFORE 1 = " //* Program: "'
'ISREDIT LINE_BEFORE 1 = " //* Author:  "'
'ISREDIT LINE_BEFORE 1 = " //* Date:    "'
'ISREDIT LINE_BEFORE 1 = " //*====================================="'
EXIT 0
```

---

