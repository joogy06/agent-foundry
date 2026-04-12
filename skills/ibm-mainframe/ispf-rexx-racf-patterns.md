# ISPF, TSO/REXX, Utilities, RACF, SMS, and JCL Patterns

Reference file for the `ibm-mainframe` skill. Covers ISPF navigation, TSO/REXX scripting, system utilities, RACF security, SMS storage management, and practical JCL patterns.

## 7. TSO/REXX

### Common TSO Commands

```
ALLOC DA('PROD.NEW.DATASET') NEW CATALOG                -
      SPACE(10,5) CYLINDERS                              -
      RECFM(F,B) LRECL(80) BLKSIZE(27920)               -
      DSORG(PS)

FREE DA('PROD.NEW.DATASET')

LISTDS 'PROD.CUSTOMER.MASTER' ALL MEMBERS

SUBMIT 'PROD.JCL.LIBRARY(PAYJOB)'

STATUS

LISTCAT ENTRIES('PROD.CUSTOMER.**')

DELETE 'PROD.OLD.DATASET'

RENAME 'PROD.OLD.NAME' 'PROD.NEW.NAME'

EXEC 'MY.REXX.LIBRARY(MYSCRIPT)' 'PARM1 PARM2'
```

### REXX Basics

```rexx
/* REXX - Process a dataset and generate a report */
ARG input_dsn output_dsn
IF input_dsn = '' THEN DO
  SAY 'Usage: PROCESS input_dsn output_dsn'
  EXIT 8
END

/* Allocate files */
"ALLOC FI(INFILE) DA('"input_dsn"') SHR REUSE"
IF RC <> 0 THEN DO
  SAY 'ERROR: Cannot allocate' input_dsn '- RC='RC
  EXIT 12
END

"ALLOC FI(OUTFILE) DA('"output_dsn"') NEW CATALOG" ,
  "SPACE(5,2) CYLINDERS RECFM(F,B) LRECL(133) BLKSIZE(27930) REUSE"

/* Read all records */
"EXECIO * DISKR INFILE (STEM inrec. FINIS"
SAY 'Records read:' inrec.0

/* Process records */
count = 0
DO i = 1 TO inrec.0
  IF SUBSTR(inrec.i, 25, 2) = 'NY' THEN DO
    count = count + 1
    outrec.count = ' ' || LEFT(inrec.i, 80) || RIGHT(count, 10)
  END
END
outrec.0 = count

/* Write output */
"EXECIO" outrec.0 "DISKW OUTFILE (STEM outrec. FINIS"
SAY 'Records written:' outrec.0

/* Free files */
"FREE FI(INFILE OUTFILE)"

EXIT 0
```

### EXECIO — File I/O

```rexx
/* Read all records into a stem variable */
"EXECIO * DISKR ddname (STEM data. FINIS"
/* data.0 = record count, data.1..data.n = records */

/* Read 10 records starting from current position */
"EXECIO 10 DISKR ddname (STEM data."

/* Read one record into a single variable */
"EXECIO 1 DISKR ddname (VAR record"

/* Write all records from stem */
"EXECIO" data.0 "DISKW ddname (STEM data. FINIS"

/* Write one record */
"EXECIO 1 DISKW ddname (VAR record"

/* Queue records to the stack, then write from stack */
DO i = 1 TO 5
  QUEUE 'Line' i 'of output'
END
"EXECIO 5 DISKW ddname (FINIS"
```

### OUTTRAP — Capture TSO Command Output

```rexx
/* Capture output of TSO LISTDS command */
x = OUTTRAP('line.')
"LISTDS 'SYS1.PARMLIB' MEMBERS"
x = OUTTRAP('OFF')

DO i = 1 TO line.0
  SAY line.i
END
```

### ADDRESS — Routing Commands

```rexx
/* Default is ADDRESS TSO */
ADDRESS TSO "ALLOC FI(MYFILE) DA('MY.DATASET') SHR"

/* Route to ISPF services */
ADDRESS ISPEXEC
"CONTROL ERRORS RETURN"
"LMINIT DATAID(DID) DATASET('PROD.JCL.LIB') ENQ(SHR)"
"LMOPEN DATAID("DID") OPTION(INPUT)"
"LMMLIST DATAID("DID") MEMBER(MEM) STATS(YES)"
DO WHILE RC = 0
  SAY 'Member:' MEM
  "LMMLIST DATAID("DID") MEMBER(MEM) STATS(YES)"
END
"LMCLOSE DATAID("DID")"
"LMFREE DATAID("DID")"

/* Route to MVS console commands */
ADDRESS MVS "EXECIO * DISKR INDD (STEM rec. FINIS"
```

---

## 8. System Utilities

### IEBGENER — Copy Sequential Datasets

```jcl
//COPY     EXEC PGM=IEBGENER
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
//SYSUT1   DD DSN=PROD.INPUT.FILE,DISP=SHR
//SYSUT2   DD DSN=PROD.OUTPUT.FILE,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(20,5),RLSE),
//            DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920)
```

Note: `ICEGENER` (DFSORT replacement) is often aliased to IEBGENER and runs faster. If DFSORT is installed, ICEGENER is typically the default.

### IEBCOPY — Copy/Compress PDS

```jcl
//* --- Copy members between PDS libraries ---
//COPYMBRS EXEC PGM=IEBCOPY
//SYSPRINT DD SYSOUT=*
//SYSUT3   DD UNIT=SYSALLDA,SPACE=(TRK,(5,5))
//INLIB    DD DSN=DEV.COBOL.SRCLIB,DISP=SHR
//OUTLIB   DD DSN=PROD.COBOL.SRCLIB,DISP=SHR
//SYSIN    DD *
  COPY O=OUTLIB,I=INLIB
  SELECT MEMBER=(PROG001,PROG002,PROG003)
/*

//* --- Compress PDS in place (reclaim deleted space) ---
//COMPRESS EXEC PGM=IEBCOPY
//SYSPRINT DD SYSOUT=*
//SYSUT3   DD UNIT=SYSALLDA,SPACE=(TRK,(5,5))
//PDSLIB   DD DSN=DEV.COBOL.SRCLIB,DISP=OLD
//SYSIN    DD *
  COPY O=PDSLIB,I=PDSLIB
/*
```

### IEFBR14 — Do-Nothing Program

Used solely to trigger JCL DD statement processing (allocate/delete datasets):

```jcl
//* --- Create an empty dataset ---
//CREATE   EXEC PGM=IEFBR14
//NEWFILE  DD DSN=PROD.NEW.DATASET,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(10,5),RLSE),
//            DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920)

//* --- Delete a dataset ---
//DELSTEP  EXEC PGM=IEFBR14
//DELFILE  DD DSN=PROD.OLD.DATASET,DISP=(OLD,DELETE)
```

### IEHPROGM — Catalog Maintenance

```jcl
//* --- Scratch (delete) a dataset from a volume ---
//SCRATCH  EXEC PGM=IEHPROGM
//SYSPRINT DD SYSOUT=*
//DD1      DD UNIT=SYSALLDA,VOL=SER=VOL001,DISP=OLD
//SYSIN    DD *
  SCRATCH DSNAME=PROD.OLD.DATASET,VOL=SYSALLDA=VOL001
  UNCATLG DSNAME=PROD.OLD.DATASET
/*
```

### ICEGENER — DFSORT Copy Utility

Drop-in replacement for IEBGENER. Identical JCL syntax but uses DFSORT engine for better performance:

```jcl
//COPY     EXEC PGM=ICEGENER
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
//SYSUT1   DD DSN=PROD.INPUT.FILE,DISP=SHR
//SYSUT2   DD DSN=PROD.OUTPUT.FILE,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(20,5),RLSE)
```

---

## 9. RACF Security

### Users and Groups

```
/* Define a new user */
ADDUSER JSMITH NAME('JOHN SMITH')            -
        DFLTGRP(DEVGRP)                      -
        PASSWORD(TEMP1234)                   -
        OWNER(SECADMIN)                      -
        TSO(ACCTNUM(ACCT01)                  -
            PROC(ISPFPROC)                   -
            SIZE(4096)                       -
            MAXSIZE(0))

/* Define a group */
ADDGROUP DEVGRP SUPGROUP(SYS1)              -
         OWNER(SECADMIN)

/* Connect user to additional group */
CONNECT JSMITH GROUP(PRODGRP)               -
        AUTH(USE)                            -
        OWNER(SECADMIN)

/* Alter user properties */
ALTUSER JSMITH RESUME                        /* Resume a revoked user */
ALTUSER JSMITH REVOKE                        /* Revoke user access */
ALTUSER JSMITH PASSWORD(NEWTEMP) NOEXPIRED   /* Reset password */

/* List user information */
LISTUSER JSMITH ALL
LISTGRP DEVGRP ALL
```

### Dataset Profiles

```
/* Discrete profile (exact dataset name) */
ADDSD 'PROD.PAYROLL.MASTER'                 -
      UACC(NONE)                            -
      OWNER(SECADMIN)                       -
      AUDIT(SUCCESS(READ) FAILURES(READ))

/* Generic profile (pattern-based) */
ADDSD 'PROD.PAYROLL.**'                     -
      UACC(NONE)                            -
      OWNER(SECADMIN)

/* Grant access */
PERMIT 'PROD.PAYROLL.**'                    -
       ID(PAYGRP)                           -
       ACCESS(UPDATE)

PERMIT 'PROD.PAYROLL.**'                    -
       ID(AUDITOR)                          -
       ACCESS(READ)

/* List dataset profile */
LISTDSD DA('PROD.PAYROLL.**') ALL GENERIC

/* Remove access */
PERMIT 'PROD.PAYROLL.**'                    -
       ID(JSMITH)                           -
       DELETE
```

RACF access levels: `NONE` < `EXECUTE` < `READ` < `UPDATE` < `CONTROL` < `ALTER`.

### Program Control

```
/* Protect a program — only authorized users can execute */
RDEFINE PROGRAM PAYPROG                     -
        ADDMEM('PROD.LOAD.LIBRARY'//NOPADCHK) -
        UACC(NONE)

PERMIT PAYPROG CLASS(PROGRAM)               -
       ID(PAYGRP)                           -
       ACCESS(READ)

SETROPTS WHEN(PROGRAM)                      -
         REFRESH RACLIST(PROGRAM)
```

### Common RACF Queries

```
/* Search for all profiles a user can access */
SEARCH CLASS(DATASET) USER(JSMITH)

/* Search for all users with access to a dataset */
LISTDSD DA('PROD.PAYROLL.**') ALL GENERIC AUTHUSER

/* Check your own access to a dataset */
LISTDSD DA('PROD.PAYROLL.MASTER') GENERIC
```

---

## 10. SMS (Storage Management Subsystem)

SMS automates dataset placement, performance, and lifecycle management through three classes and ACS (Automatic Class Selection) routines.

### Data Class

Defines default dataset attributes (RECFM, LRECL, SPACE, DSORG). If coded in JCL, JCL values override data class.

```
/* Example data class definition (ISMF panels or SCDS) */
Data Class Name: DCFB80
  Record Format:    FB
  Record Length:    80
  Block Size:       27920
  Space (Primary):  10 CYL
  Space (Secondary): 5 CYL
  Directory Blocks: 50  (for PDS)
  Data Set Type:    LIBRARY  (PDSE)
  Compaction:       YES
```

### Storage Class

Defines performance and availability objectives (response time, availability, accessibility).

```
Storage Class Name: SCFAST
  Performance Objective:
    Direct Millisecond Response:  10
    Sequential Millisecond Response: 20
  Availability:        CONTINUOUS
  Accessibility:       CONTINUOUS (no single point of failure)
  Guaranteed Space:    YES
  Cache:               PREFERRED
```

### Management Class

Defines lifecycle rules — migration, backup frequency, retention, expiration.

```
Management Class Name: MC30DAY
  Expire After Days/Date: 30
  Migration:
    Primary Days Non-Usage:   5
    Level 1 Days Non-Usage:   30
  Backup:
    Backup Frequency:   1  (daily)
    Number of Backup Versions: 5
    Retain Days for Versions: 60
    Retain Days for Deleted: 30
```

### ACS Routines

ACS routines are coded in a REXX-like language and run automatically when datasets are allocated. They assign data class, storage class, management class, and storage group based on dataset name, HLQ, job name, or other criteria.

```
/* Example ACS routine fragment for storage class */
PROC 0
  FILTLIST PROD_HLQ INCLUDE('PROD.**')
  FILTLIST CRIT_DSN INCLUDE('PROD.CUST.**','PROD.PAYROLL.**')

  SELECT
    WHEN (&DSN = &CRIT_DSN) DO
      SET &STORCLAS = 'SCFAST'
    END
    WHEN (&DSN = &PROD_HLQ) DO
      SET &STORCLAS = 'SCSTANDARD'
    END
    OTHERWISE DO
      SET &STORCLAS = 'SCDEFAULT'
    END
  END
END
```

ACS routines are validated and activated through ISMF (Interactive Storage Management Facility) panels or the `STGADMIN` TSO commands.

---

## 11. Practical JCL Patterns

### Multi-Step Job with Conditional Execution

```jcl
//DAILYJOB JOB (ACCT#,DEPT),'DAILY BATCH',
//         CLASS=A,MSGCLASS=X,MSGLEVEL=(1,1),
//         NOTIFY=&SYSUID
//*
//*============================================================
//* STEP 1: SORT DAILY TRANSACTIONS
//*============================================================
//STEP010  EXEC PGM=SORT
//SORTIN   DD DSN=PROD.DAILY.TRANS(0),DISP=SHR
//SORTOUT  DD DSN=&&SORTED,
//            DISP=(NEW,PASS),
//            SPACE=(CYL,(20,5)),
//            DCB=(RECFM=FB,LRECL=200,BLKSIZE=27800)
//SYSOUT   DD SYSOUT=*
//SYSIN    DD *
  SORT FIELDS=(1,10,CH,A,15,8,PD,D)
  INCLUDE COND=(100,1,CH,EQ,C'A')
/*
//*
//*============================================================
//* STEP 2: PROCESS SORTED TRANSACTIONS (only if sort OK)
//*============================================================
//         IF (STEP010.RC = 0) THEN
//STEP020  EXEC PGM=BATCHPGM
//STEPLIB  DD DSN=PROD.LOAD.LIBRARY,DISP=SHR
//INPUT    DD DSN=&&SORTED,DISP=(OLD,DELETE)
//MASTER   DD DSN=PROD.CUSTOMER.MASTER,DISP=SHR
//OUTPUT   DD DSN=PROD.DAILY.RESULTS,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(30,10),RLSE),
//            DCB=(RECFM=FB,LRECL=250,BLKSIZE=27750)
//REPORT   DD SYSOUT=*
//SYSPRINT DD SYSOUT=*
//         ENDIF
//*
//*============================================================
//* STEP 3: GENERATE SUMMARY REPORT (only if step 2 OK)
//*============================================================
//         IF (STEP020.RC <= 4) THEN
//STEP030  EXEC PGM=SORT
//SORTIN   DD DSN=PROD.DAILY.RESULTS,DISP=SHR
//SORTOUT  DD DSN=PROD.DAILY.SUMMARY,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(5,2),RLSE),
//            DCB=(RECFM=FB,LRECL=133,BLKSIZE=27930)
//SYSOUT   DD SYSOUT=*
//SYSIN    DD *
  SORT FIELDS=(1,10,CH,A)
  SUM FIELDS=(50,8,PD,60,8,PD)
  OUTFIL FNAMES=SORTOUT,
    HEADER1=(5:'DAILY TRANSACTION SUMMARY',
             60:DATE=(4MD/),70:TIME),
    OUTREC=(1,10,C'  ',
            50,8,PD,EDIT=(TTTTTTTTTT.TT),C'  ',
            60,8,PD,EDIT=(TTTTTTTTTT.TT)),
    TRAILER1=(5:'*** END OF REPORT ***',
              30:'RECORDS: ',COUNT)
/*
//         ENDIF
//*
//*============================================================
//* STEP 4: CREATE NEW GDG GENERATION (backup)
//*============================================================
//         IF (STEP020.RC <= 4) THEN
//STEP040  EXEC PGM=IEBGENER
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
//SYSUT1   DD DSN=PROD.DAILY.RESULTS,DISP=SHR
//SYSUT2   DD DSN=PROD.DAILY.BACKUP(+1),
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(30,10),RLSE),
//            DCB=(RECFM=FB,LRECL=250,BLKSIZE=27750)
//         ENDIF
//*
//*============================================================
//* CLEANUP: DELETE TEMP FILES ON FAILURE
//*============================================================
//         IF (STEP020.ABEND | STEP030.ABEND) THEN
//CLEANUP  EXEC PGM=IEFBR14
//DELRSLT  DD DSN=PROD.DAILY.RESULTS,
//            DISP=(MOD,DELETE,DELETE)
//         ENDIF
```

### GDG Cycling Pattern (Rotate Daily, Keep 30 Days)

```jcl
//*============================================================
//* Define GDG base (run once)
//*============================================================
//DEFGDG   EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
  DEFINE GDG (NAME(PROD.DAILY.BACKUP)       -
              LIMIT(30) NOEMPTY SCRATCH)
  IF LASTCC > 0 THEN SET MAXCC = 16
/*
//*
//*============================================================
//* Define model DSCB (run once)
//*============================================================
//DEFMODEL EXEC PGM=IEFBR14
//MODEL    DD DSN=PROD.DAILY.BACKUP,
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(TRK,0),
//            DCB=(RECFM=FB,LRECL=200,BLKSIZE=27800)
//*
//*============================================================
//* Daily job — create new generation
//*============================================================
//GENSTEP  EXEC PGM=IEBGENER
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
//SYSUT1   DD DSN=PROD.DAILY.EXTRACT,DISP=SHR
//SYSUT2   DD DSN=PROD.DAILY.BACKUP(+1),
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(50,10),RLSE),
//            DCB=(RECFM=FB,LRECL=200,BLKSIZE=27800)
```

### VSAM Reload Pattern (Delete/Define/Repro)

```jcl
//RELOAD   JOB (ACCT#),'VSAM RELOAD',CLASS=A,
//         MSGCLASS=X,NOTIFY=&SYSUID
//*
//*============================================================
//* STEP 1: BACKUP EXISTING VSAM CLUSTER
//*============================================================
//STEP010  EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//INFILE   DD DSN=PROD.CUSTOMER.MASTER,DISP=SHR
//OUTFILE  DD DSN=PROD.CUSTOMER.BACKUP(+1),
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(50,10),RLSE),
//            DCB=(RECFM=VB,LRECL=254,BLKSIZE=27998)
//SYSIN    DD *
  REPRO INFILE(INFILE) OUTFILE(OUTFILE)
/*
//*
//*============================================================
//* STEP 2: DELETE AND REDEFINE CLUSTER
//*============================================================
//         IF (STEP010.RC <= 4) THEN
//STEP020  EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
  DELETE PROD.CUSTOMER.MASTER CLUSTER PURGE
  IF LASTCC = 8 THEN SET MAXCC = 0
  DEFINE CLUSTER (                           -
           NAME(PROD.CUSTOMER.MASTER)        -
           INDEXED                           -
           RECORDSIZE(200 250)               -
           KEYS(10 0)                        -
           SHAREOPTIONS(2 3)                 -
           SPEED                             -
           FREESPACE(20 10)                  -
         )                                   -
         DATA (                              -
           NAME(PROD.CUSTOMER.MASTER.DATA)   -
           CYLINDERS(50 10)                  -
         )                                   -
         INDEX (                             -
           NAME(PROD.CUSTOMER.MASTER.INDEX)  -
           CYLINDERS(5 2)                    -
         )
/*
//         ENDIF
//*
//*============================================================
//* STEP 3: RELOAD FROM BACKUP
//*============================================================
//         IF (STEP020.RC = 0) THEN
//STEP030  EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//INFILE   DD DSN=PROD.CUSTOMER.BACKUP(0),DISP=SHR
//OUTFILE  DD DSN=PROD.CUSTOMER.MASTER,DISP=SHR
//SYSIN    DD *
  REPRO INFILE(INFILE) OUTFILE(OUTFILE) REPLACE
/*
//         ENDIF
```

### SORT-Based Reporting Pattern

```jcl
//RPTJOB   EXEC PGM=ICETOOL
//TOOLMSG  DD SYSOUT=*
//DFSMSG   DD SYSOUT=*
//TRANSIN  DD DSN=PROD.DAILY.TRANS,DISP=SHR
//DETAIL   DD SYSOUT=*,DCB=(RECFM=FBA,LRECL=133,BLKSIZE=27930)
//SUMMARY  DD SYSOUT=*,DCB=(RECFM=FBA,LRECL=133,BLKSIZE=27930)
//TOOLIN   DD *
  DISPLAY FROM(TRANSIN) LIST(DETAIL)             -
    TITLE('Daily Transaction Detail Report')     -
    DATE(4MD/)                                   -
    TIME                                         -
    PAGE                                         -
    HEADER('Account') ON(1,10,CH)                -
    HEADER('Region')  ON(11,4,CH)                -
    HEADER('Amount')  ON(15,8,PD)                -
    HEADER('Date')    ON(25,8,CH)                -
    BLANK
  SORT FROM(TRANSIN) USING(SUMM)                 -
    TO(SUMMARY)
/*
//SUMMCNTL DD *
  SORT FIELDS=(11,4,CH,A)
  SUM FIELDS=(15,8,PD)
  OUTFIL FNAMES=SUMMARY,
    HEADER1=(1:C'1',5:'DAILY TRANSACTION SUMMARY BY REGION',
             70:DATE=(4MD/),85:TIME,
             100:'PAGE ',PAGE),
    HEADER2=(5:'REGION',15:'TOTAL AMOUNT',
             35:'RECORD COUNT'),
    OUTREC=(5:11,4,
            15:15,8,PD,EDIT=(TTTTTTTTTTT.TT),
            35:COUNT),
    TRAILER1=(5:'*** END OF REPORT ***')
/*
```

### Common Batch Flow — Extract/Transform/Load

```jcl
//ETLJOB   JOB (ACCT#),'ETL DAILY',CLASS=A,
//         MSGCLASS=X,MSGLEVEL=(1,1),NOTIFY=&SYSUID
//*
//* STEP 1: EXTRACT — Pull today's transactions
//EXTRACT  EXEC PGM=BATCHEXT
//STEPLIB  DD DSN=PROD.LOAD.LIBRARY,DISP=SHR
//DBIN     DD DSN=PROD.DB2.EXTRACT.PARM,DISP=SHR
//RAWOUT   DD DSN=&&RAWDATA,
//            DISP=(NEW,PASS),
//            SPACE=(CYL,(100,20)),
//            DCB=(RECFM=VB,LRECL=2000,BLKSIZE=27998)
//SYSPRINT DD SYSOUT=*
//*
//* STEP 2: TRANSFORM — Validate, cleanse, reformat
//         IF (EXTRACT.RC = 0) THEN
//TRANSFRM EXEC PGM=SORT
//SORTIN   DD DSN=&&RAWDATA,DISP=(OLD,DELETE)
//SORTOUT  DD DSN=&&CLEANED,
//            DISP=(NEW,PASS),
//            SPACE=(CYL,(100,20)),
//            DCB=(RECFM=FB,LRECL=200,BLKSIZE=27800)
//SYSOUT   DD SYSOUT=*
//SYSIN    DD *
  SORT FIELDS=(1,10,CH,A)
  INCLUDE COND=(50,1,CH,NE,C'D')
  INREC FIELDS=(1,10,C'|',15,8,ZD,EDIT=(TTTTTTTT),
                C'|',30,30,C'|',80:DATE1(4MD-))
  SUM FIELDS=NONE
/*
//         ENDIF
//*
//* STEP 3: LOAD — Update master VSAM and GDG archive
//         IF (TRANSFRM.RC = 0) THEN
//LOAD     EXEC PGM=BATCHLOD
//STEPLIB  DD DSN=PROD.LOAD.LIBRARY,DISP=SHR
//INPUT    DD DSN=&&CLEANED,DISP=(OLD,DELETE)
//MASTER   DD DSN=PROD.CUSTOMER.MASTER,DISP=SHR
//ARCHIVE  DD DSN=PROD.DAILY.ARCHIVE(+1),
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(50,10),RLSE),
//            DCB=(RECFM=FB,LRECL=200,BLKSIZE=27800)
//SYSPRINT DD SYSOUT=*
//         ENDIF
//*
//* NOTIFY ON FAILURE
//         IF (EXTRACT.ABEND | TRANSFRM.ABEND | LOAD.ABEND) THEN
//NOTIFY   EXEC PGM=BATCHNTF,PARM='ETL FAILED - SEE JOB LOG'
//STEPLIB  DD DSN=PROD.LOAD.LIBRARY,DISP=SHR
//         ENDIF
```

---

## Related Skills

| Topic | Skill |
|---|---|
| Python connectors to z/OS (Zowe SDK, ibm_db, EBCDIC) | `python-enterprise-connectors` |
| DB2 for z/OS administration | `db2-mainframe` |
