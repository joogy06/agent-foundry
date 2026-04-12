---
name: cobol-developer
description: Use when reading, writing, debugging, or modernizing COBOL programs — divisions and sections, data types (PIC clauses, COMP/COMP-3/DISPLAY), file handling (QSAM/VSAM/KSDS/RRDS), PERFORM and paragraph structure, COPY/REPLACE, embedded SQL (EXEC SQL), CICS programming (EXEC CICS), batch JCL integration, debugging (CEDF/Xpediter), and COBOL modernization patterns. Part of the ibm-mainframe skill family.
---

# COBOL Developer Reference

Companion to `ibm-mainframe` (JCL/VSAM/utilities) and `db2-mainframe` (DB2 z/OS DBA). For Python mainframe connectivity see `python-enterprise-connectors`.

<HARD-RULE>
Always check SQLCODE after every EXEC SQL statement — unchecked SQLCODEs cause silent data corruption. At minimum check for SQLCODE = 0, +100 (not found), and negative values (errors).
</HARD-RULE>

<HARD-RULE>
Never use GO TO in new COBOL code — use structured PERFORM THRU patterns for maintainability. GO TO creates spaghetti control flow that is nearly impossible to debug or modify.
</HARD-RULE>

<HARD-RULE>
Always define numeric fields with explicit COMP-3 or COMP for calculations — DISPLAY numeric fields cause implicit conversions on every arithmetic operation, degrading performance significantly in batch loops.
</HARD-RULE>

<HARD-RULE>
Always initialize WORKING-STORAGE variables with VALUE clauses or INITIALIZE verb — uninitialized fields contain unpredictable data from previous program executions in CICS or residual memory in batch.
</HARD-RULE>

---

## 1. Program Structure

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDPROC.
       AUTHOR. MAINTENANCE TEAM.
       DATE-WRITTEN. 2026-03-31.
      *================================================================*
      * ORDER PROCESSING - BATCH PROGRAM                               *
      *================================================================*

       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           DECIMAL-POINT IS COMMA.

       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-FILE
               ASSIGN TO ORDIN
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-ORDER-FS.

           SELECT REPORT-FILE
               ASSIGN TO RPTOUT
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-REPORT-FS.

           SELECT CUSTOMER-FILE
               ASSIGN TO CUSTDB
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS CUST-KEY
               FILE STATUS IS WS-CUST-FS.

       DATA DIVISION.
       FILE SECTION.
       FD  ORDER-FILE
           RECORDING MODE IS F
           RECORD CONTAINS 200 CHARACTERS.
       01  ORDER-RECORD.
           05  ORD-ID              PIC 9(10).
           05  ORD-CUST-ID         PIC 9(8).
           05  ORD-DATE            PIC X(10).
           05  ORD-AMOUNT          PIC S9(11)V99 COMP-3.
           05  ORD-STATUS          PIC X(1).
               88  ORD-PENDING     VALUE 'P'.
               88  ORD-SHIPPED     VALUE 'S'.
               88  ORD-CANCELLED   VALUE 'C'.
           05  FILLER              PIC X(163).

       FD  REPORT-FILE
           RECORDING MODE IS F
           RECORD CONTAINS 132 CHARACTERS.
       01  REPORT-RECORD           PIC X(132).

       WORKING-STORAGE SECTION.
       01  WS-FILE-STATUS.
           05  WS-ORDER-FS        PIC XX VALUE SPACES.
           05  WS-REPORT-FS       PIC XX VALUE SPACES.
           05  WS-CUST-FS         PIC XX VALUE SPACES.

       01  WS-FLAGS.
           05  WS-EOF-FLAG        PIC X(1) VALUE 'N'.
               88  END-OF-FILE    VALUE 'Y'.
               88  NOT-END-OF-FILE VALUE 'N'.

       01  WS-COUNTERS.
           05  WS-READ-COUNT      PIC 9(9) COMP VALUE 0.
           05  WS-PROC-COUNT      PIC 9(9) COMP VALUE 0.
           05  WS-ERROR-COUNT     PIC 9(9) COMP VALUE 0.

       01  WS-TOTALS.
           05  WS-TOTAL-AMOUNT    PIC S9(15)V99 COMP-3
                                  VALUE ZERO.

       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-PROCESS UNTIL END-OF-FILE
           PERFORM 9000-TERMINATE
           GOBACK
           .

       1000-INITIALIZE.
           OPEN INPUT ORDER-FILE
           OPEN OUTPUT REPORT-FILE
           PERFORM 1100-READ-ORDER
           .

       1100-READ-ORDER.
           READ ORDER-FILE
               AT END SET END-OF-FILE TO TRUE
               NOT AT END ADD 1 TO WS-READ-COUNT
           END-READ
           .

       2000-PROCESS.
           EVALUATE TRUE
               WHEN ORD-PENDING
                   PERFORM 2100-PROCESS-PENDING
               WHEN ORD-SHIPPED
                   PERFORM 2200-PROCESS-SHIPPED
               WHEN OTHER
                   ADD 1 TO WS-ERROR-COUNT
           END-EVALUATE
           PERFORM 1100-READ-ORDER
           .

       9000-TERMINATE.
           CLOSE ORDER-FILE REPORT-FILE
           DISPLAY 'RECORDS READ:      ' WS-READ-COUNT
           DISPLAY 'RECORDS PROCESSED: ' WS-PROC-COUNT
           DISPLAY 'ERRORS:            ' WS-ERROR-COUNT
           .
```

---

## 2. Data Division Deep Dive

### PIC Clauses

| PIC | Meaning | Example Value |
|-----|---------|---------------|
| `PIC X(20)` | Alphanumeric, 20 chars | `"JOHN DOE            "` |
| `PIC 9(5)` | Numeric display, 5 digits | `00123` |
| `PIC S9(7)V99` | Signed, 7 integer + 2 decimal | `+1234567.89` |
| `PIC S9(7)V99 COMP-3` | Packed decimal (BCD) | 4 bytes |
| `PIC S9(9) COMP` | Binary (fullword) | 4 bytes |
| `PIC S9(18) COMP` | Binary (doubleword) | 8 bytes |
| `PIC S9(7)V99 COMP-1` | Single-precision float | 4 bytes |
| `PIC S9(18)V99 COMP-2` | Double-precision float | 8 bytes |
| `PIC Z(5)9` | Edited numeric (leading zeros suppressed) | `   123` |
| `PIC $ZZ,ZZ9.99` | Edited with currency/commas | `  $1,234.56` |

### Storage Formats

| Usage | Storage | When to Use |
|-------|---------|-------------|
| DISPLAY | 1 byte/digit | External files, reports |
| COMP-3 (packed) | (n+1)/2 bytes | **All calculations and DB2 columns** |
| COMP (binary) | 2/4/8 bytes | Subscripts, counters, indexes |
| COMP-1 (float) | 4 bytes | Scientific calculations (rare) |
| COMP-2 (double) | 8 bytes | Scientific calculations (rare) |

### REDEFINES

```cobol
       01  WS-DATE-FIELD.
           05  WS-DATE-CCYYMMDD   PIC 9(8).
           05  WS-DATE-PARTS REDEFINES WS-DATE-CCYYMMDD.
               10  WS-DATE-CC     PIC 99.
               10  WS-DATE-YY     PIC 99.
               10  WS-DATE-MM     PIC 99.
               10  WS-DATE-DD     PIC 99.
```

### OCCURS (Arrays)

```cobol
       01  WS-MONTHLY-TOTALS.
           05  WS-MONTH-ENTRY OCCURS 12 TIMES
               INDEXED BY WS-MONTH-IDX.
               10  WS-MONTH-NAME  PIC X(10).
               10  WS-MONTH-AMT   PIC S9(11)V99 COMP-3.

      * Variable-length array
       01  WS-ORDER-LINES.
           05  WS-LINE-COUNT      PIC 99 COMP.
           05  WS-LINE-ITEM OCCURS 1 TO 50 TIMES
               DEPENDING ON WS-LINE-COUNT.
               10  WS-ITEM-SKU    PIC X(10).
               10  WS-ITEM-QTY    PIC 9(5) COMP-3.
               10  WS-ITEM-PRICE  PIC S9(7)V99 COMP-3.
```

### 88-Level Condition Names

```cobol
       01  WS-TRANSACTION-TYPE    PIC X(2).
           88  TXN-SALE           VALUE 'SA'.
           88  TXN-RETURN         VALUE 'RT'.
           88  TXN-EXCHANGE       VALUE 'EX'.
           88  TXN-VALID          VALUE 'SA' 'RT' 'EX'.

      * Usage:
           IF TXN-VALID
               PERFORM 2000-PROCESS-TXN
           END-IF

           SET TXN-SALE TO TRUE    *> Sets WS-TRANSACTION-TYPE to 'SA'
```

---

## 3. File Handling

### File Status Codes

| Code | Meaning |
|------|---------|
| 00 | Success |
| 10 | End of file (AT END) |
| 22 | Duplicate key on WRITE |
| 23 | Record not found (READ/START/DELETE) |
| 35 | File not found (OPEN) |
| 39 | File attribute conflict |
| 41 | File already open |
| 42 | File already closed |
| 46 | Sequential READ with no valid next |
| 47 | READ on file not opened INPUT/I-O |
| 48 | WRITE on file not opened OUTPUT/I-O/EXTEND |

### VSAM KSDS (Indexed)

```cobol
       FILE-CONTROL.
           SELECT CUSTOMER-FILE
               ASSIGN TO CUSTFILE
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS CUST-ID
               ALTERNATE RECORD KEY IS CUST-NAME
                   WITH DUPLICATES
               FILE STATUS IS WS-CUST-FS.

      * Random read
           MOVE '00012345' TO CUST-ID
           READ CUSTOMER-FILE
               INVALID KEY
                   DISPLAY 'CUSTOMER NOT FOUND: ' CUST-ID
               NOT INVALID KEY
                   PERFORM 3000-PROCESS-CUSTOMER
           END-READ

      * Sequential browse (START + READ NEXT)
           MOVE '00010000' TO CUST-ID
           START CUSTOMER-FILE KEY >= CUST-ID
               INVALID KEY DISPLAY 'START FAILED'
           END-START
           PERFORM UNTIL WS-CUST-FS NOT = '00'
               READ CUSTOMER-FILE NEXT
                   AT END SET END-OF-FILE TO TRUE
               END-READ
               IF NOT END-OF-FILE
                   PERFORM 3000-PROCESS-CUSTOMER
               END-IF
           END-PERFORM

      * Update
           READ CUSTOMER-FILE
               INVALID KEY DISPLAY 'NOT FOUND'
           END-READ
           MOVE 'ACTIVE' TO CUST-STATUS
           REWRITE CUSTOMER-RECORD
               INVALID KEY DISPLAY 'REWRITE FAILED'
           END-REWRITE
```

### SORT/MERGE

```cobol
       SD  SORT-FILE.
       01  SORT-RECORD.
           05  SORT-KEY           PIC 9(10).
           05  SORT-DATA          PIC X(190).

       PROCEDURE DIVISION.
      * Simple sort
           SORT SORT-FILE
               ON ASCENDING KEY SORT-KEY
               USING INPUT-FILE
               GIVING OUTPUT-FILE

      * Sort with INPUT/OUTPUT PROCEDURE
           SORT SORT-FILE
               ON ASCENDING KEY SORT-KEY
               INPUT PROCEDURE IS 5000-SELECT-RECORDS
               OUTPUT PROCEDURE IS 6000-FORMAT-OUTPUT

       5000-SELECT-RECORDS.
           OPEN INPUT RAW-FILE
           PERFORM UNTIL END-OF-RAW
               READ RAW-FILE AT END SET END-OF-RAW TO TRUE
               NOT AT END
                   IF RAW-STATUS = 'A'
                       MOVE RAW-RECORD TO SORT-RECORD
                       RELEASE SORT-RECORD
                   END-IF
               END-READ
           END-PERFORM
           CLOSE RAW-FILE
           .

       6000-FORMAT-OUTPUT.
           OPEN OUTPUT FINAL-FILE
           PERFORM UNTIL END-OF-SORT
               RETURN SORT-FILE
                   AT END SET END-OF-SORT TO TRUE
                   NOT AT END
                       PERFORM 6100-WRITE-FORMATTED
               END-RETURN
           END-PERFORM
           CLOSE FINAL-FILE
           .
```

---

## 4. Procedure Division Patterns

### STRING / UNSTRING

```cobol
      * STRING — concatenate
           STRING WS-LAST-NAME DELIMITED BY SPACES
                  ', '           DELIMITED BY SIZE
                  WS-FIRST-NAME DELIMITED BY SPACES
             INTO WS-FULL-NAME
             WITH POINTER WS-STR-PTR
             ON OVERFLOW DISPLAY 'NAME TOO LONG'
           END-STRING

      * UNSTRING — split
           UNSTRING WS-CSV-LINE DELIMITED BY ','
             INTO WS-FIELD1
                  WS-FIELD2
                  WS-FIELD3
             WITH POINTER WS-UNS-PTR
             TALLYING IN WS-FIELD-COUNT
             ON OVERFLOW DISPLAY 'TOO MANY FIELDS'
           END-UNSTRING
```

### INSPECT

```cobol
      * Count occurrences
           INSPECT WS-INPUT-STRING
               TALLYING WS-COUNT FOR ALL 'A'

      * Replace characters
           INSPECT WS-INPUT-STRING
               REPLACING ALL LOW-VALUES BY SPACES

      * Convert (translate)
           INSPECT WS-INPUT-STRING
               CONVERTING 'abcdefghijklmnopqrstuvwxyz'
               TO         'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
```

### Reference Modification

```cobol
      * Extract substring: identifier(start:length)
           MOVE WS-FULL-DATE(1:4) TO WS-YEAR    *> First 4 chars
           MOVE WS-FULL-DATE(5:2) TO WS-MONTH   *> Chars 5-6
           MOVE WS-FULL-DATE(7:2) TO WS-DAY     *> Chars 7-8
```

### CALL (Subprogram)

```cobol
      * Static call (link-edited together)
           CALL 'DATECONV' USING WS-INPUT-DATE
                                 WS-OUTPUT-DATE
                                 WS-RETURN-CODE

      * Dynamic call (loaded at runtime — can CANCEL to free)
           MOVE 'DATECONV' TO WS-PGM-NAME
           CALL WS-PGM-NAME USING WS-INPUT-DATE
                                   WS-OUTPUT-DATE
                                   WS-RETURN-CODE
           ON EXCEPTION
               DISPLAY 'PROGRAM NOT FOUND: ' WS-PGM-NAME
               MOVE 16 TO RETURN-CODE
           END-CALL

      * CANCEL (free dynamic program from memory)
           CANCEL WS-PGM-NAME
```

---

## 5. Embedded SQL (DB2)

### Basic Patterns

```cobol
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL INCLUDE DCLORDER END-EXEC.

       01  WS-SQLCODE             PIC S9(9) COMP.
       01  HV-CUST-ID            PIC S9(8) COMP.
       01  HV-ORDER-DATE         PIC X(10).
       01  HV-AMOUNT             PIC S9(11)V99 COMP-3.
       01  HV-AMOUNT-IND         PIC S9(4) COMP.

       PROCEDURE DIVISION.

      * Singleton SELECT
           EXEC SQL
               SELECT CUST_NAME, CUST_BALANCE
               INTO :HV-CUST-NAME, :HV-CUST-BALANCE
               FROM CUSTOMER
               WHERE CUST_ID = :HV-CUST-ID
           END-EXEC
           EVALUATE SQLCODE
               WHEN 0     CONTINUE
               WHEN +100  DISPLAY 'CUSTOMER NOT FOUND'
               WHEN OTHER PERFORM 9100-SQL-ERROR
           END-EVALUATE

      * INSERT
           EXEC SQL
               INSERT INTO ORDERS
               (ORDER_ID, CUST_ID, ORDER_DATE, AMOUNT)
               VALUES
               (:HV-ORDER-ID, :HV-CUST-ID,
                :HV-ORDER-DATE, :HV-AMOUNT)
           END-EXEC

      * NULL indicator handling
           EXEC SQL
               SELECT AMOUNT
               INTO :HV-AMOUNT :HV-AMOUNT-IND
               FROM ORDERS
               WHERE ORDER_ID = :HV-ORDER-ID
           END-EXEC
           IF HV-AMOUNT-IND < 0
               DISPLAY 'AMOUNT IS NULL'
           END-IF
```

### Cursor Processing

```cobol
      * Declare cursor
           EXEC SQL
               DECLARE CSR-ORDERS CURSOR FOR
               SELECT ORDER_ID, ORDER_DATE, AMOUNT
               FROM ORDERS
               WHERE CUST_ID = :HV-CUST-ID
               AND ORDER_DATE >= :HV-START-DATE
               ORDER BY ORDER_DATE DESC
           END-EXEC

      * Open cursor
           EXEC SQL OPEN CSR-ORDERS END-EXEC
           IF SQLCODE NOT = 0
               PERFORM 9100-SQL-ERROR
           END-IF

      * Fetch loop
           PERFORM UNTIL SQLCODE NOT = 0
               EXEC SQL
                   FETCH CSR-ORDERS
                   INTO :HV-ORDER-ID,
                        :HV-ORDER-DATE,
                        :HV-AMOUNT
               END-EXEC
               IF SQLCODE = 0
                   PERFORM 3100-PROCESS-ORDER
               END-IF
           END-PERFORM

           IF SQLCODE NOT = +100
               PERFORM 9100-SQL-ERROR
           END-IF

      * Close cursor
           EXEC SQL CLOSE CSR-ORDERS END-EXEC

      * Error handler
       9100-SQL-ERROR.
           DISPLAY 'SQL ERROR: SQLCODE=' SQLCODE
           DISPLAY 'SQLERRMC=' SQLERRMC
           MOVE 16 TO RETURN-CODE
           EXEC SQL ROLLBACK END-EXEC
           GOBACK
           .
```

### Common SQLCODEs

| SQLCODE | Meaning | Action |
|---------|---------|--------|
| 0 | Success | Continue |
| +100 | Not found / end of cursor | Handle as business logic |
| -803 | Duplicate key on INSERT | Check for existing record |
| -805 | Package/plan not found | Rebind needed |
| -811 | Multiple rows from SELECT INTO | Add predicate or use cursor |
| -818 | Timestamp mismatch | Rebind with current DBRM |
| -904 | Unavailable resource | Retry or fail gracefully |
| -911 | Deadlock/timeout rollback | Retry transaction |
| -913 | Deadlock victim | Retry transaction |

---

## 6. CICS Programming

### Pseudo-Conversational Pattern

```cobol
      * Main entry — pseudo-conversational
       0000-MAIN.
           EVALUATE EIBCALEN
               WHEN 0
                   PERFORM 1000-FIRST-TIME
               WHEN OTHER
                   PERFORM 2000-PROCESS-INPUT
           END-EVALUATE
           .

       1000-FIRST-TIME.
           INITIALIZE WS-COMMAREA
           PERFORM 3000-SEND-MAP
           EXEC CICS RETURN
               TRANSID('ORDQ')
               COMMAREA(WS-COMMAREA)
               LENGTH(LENGTH OF WS-COMMAREA)
           END-EXEC
           .

       2000-PROCESS-INPUT.
           MOVE DFHCOMMAREA TO WS-COMMAREA
           EXEC CICS RECEIVE MAP('ORDMAP')
               MAPSET('ORDMAPS')
               INTO(ORDMAPI)
           END-EXEC

           EVALUATE EIBAID
               WHEN DFHENTER
                   PERFORM 2100-PROCESS-ORDER
               WHEN DFHPF3
                   EXEC CICS RETURN END-EXEC
               WHEN DFHPF12
                   EXEC CICS RETURN END-EXEC
               WHEN OTHER
                   MOVE 'INVALID KEY' TO MSGO
                   PERFORM 3000-SEND-MAP
           END-EVALUATE
           .

       3000-SEND-MAP.
           EXEC CICS SEND MAP('ORDMAP')
               MAPSET('ORDMAPS')
               FROM(ORDMAPO)
               ERASE
               CURSOR
           END-EXEC
           EXEC CICS RETURN
               TRANSID('ORDQ')
               COMMAREA(WS-COMMAREA)
               LENGTH(LENGTH OF WS-COMMAREA)
           END-EXEC
           .
```

### CICS Commands Reference

| Command | Purpose |
|---------|---------|
| `SEND MAP` / `RECEIVE MAP` | BMS screen I/O |
| `LINK PROGRAM` | Call subprogram (returns) |
| `XCTL PROGRAM` | Transfer control (no return) |
| `RETURN TRANSID` | Pseudo-conversational return |
| `READ / WRITE / REWRITE / DELETE` | VSAM file operations |
| `READQ TS / WRITEQ TS / DELETEQ TS` | Temporary Storage queue |
| `READQ TD / WRITEQ TD` | Transient Data queue |
| `START TRANSID` | Schedule async transaction |
| `RETRIEVE` | Get START data |
| `GETMAIN / FREEMAIN` | Memory allocation |
| `ASKTIME / FORMATTIME` | Date/time operations |

### Error Handling

```cobol
      * RESP-based (recommended — replaces HANDLE CONDITION)
           EXEC CICS READ
               DATASET('CUSTFILE')
               INTO(CUST-RECORD)
               RIDFLD(CUST-KEY)
               RESP(WS-RESP)
               RESP2(WS-RESP2)
           END-EXEC

           EVALUATE WS-RESP
               WHEN DFHRESP(NORMAL)
                   PERFORM 3100-DISPLAY-CUSTOMER
               WHEN DFHRESP(NOTFND)
                   MOVE 'CUSTOMER NOT FOUND' TO MSGO
               WHEN DFHRESP(DISABLED)
                   MOVE 'FILE DISABLED' TO MSGO
               WHEN OTHER
                   PERFORM 9200-CICS-ERROR
           END-EVALUATE
```

---

## 7. Batch Processing

### JCL Integration

```jcl
//ORDPROC  JOB (ACCT),'ORDER PROCESSING',
//         CLASS=A,MSGCLASS=X,MSGLEVEL=(1,1)
//STEP010  EXEC PGM=ORDPROC
//STEPLIB  DD DSN=PROD.LOAD.LIBRARY,DISP=SHR
//ORDIN    DD DSN=PROD.ORDERS.DAILY,DISP=SHR
//CUSTDB   DD DSN=PROD.CUSTOMER.VSAM,DISP=SHR
//RPTOUT   DD DSN=PROD.REPORTS.DAILY(+1),
//         DISP=(NEW,CATLG),
//         SPACE=(TRK,(50,10),RLSE),
//         DCB=(RECFM=FB,LRECL=132,BLKSIZE=0)
//SYSOUT   DD SYSOUT=*
```

### PARM Passing

```cobol
       LINKAGE SECTION.
       01  LS-PARM.
           05  LS-PARM-LENGTH    PIC S9(4) COMP.
           05  LS-PARM-DATA      PIC X(100).

       PROCEDURE DIVISION USING LS-PARM.
           IF LS-PARM-LENGTH > 0
               EVALUATE LS-PARM-DATA(1:1)
                   WHEN 'D' SET DAILY-RUN TO TRUE
                   WHEN 'M' SET MONTHLY-RUN TO TRUE
               END-EVALUATE
           END-IF
```

### Return Codes

```cobol
      * Set return code for JCL COND checking
           MOVE 0 TO RETURN-CODE     *> Success
           MOVE 4 TO RETURN-CODE     *> Warning
           MOVE 8 TO RETURN-CODE     *> Error
           MOVE 16 TO RETURN-CODE    *> Severe error

      * In JCL:
      * //STEP020 EXEC PGM=NEXTSTEP,COND=(8,LT,STEP010)
      *   (skip if STEP010 RC < 8, i.e., run only if RC >= 8)
```

---

## 8. Copybook Patterns

```cobol
      * In WORKING-STORAGE:
           COPY ORDCOPY.                      *> Include copybook as-is

           COPY CUSTCOPY REPLACING
               ==:TAG:== BY ==WS-==.          *> Replace tag prefix

      * Copybook CUSTCOPY.cpy:
      * 01  :TAG:-CUSTOMER-RECORD.
      *     05  :TAG:-CUST-ID    PIC 9(8).
      *     05  :TAG:-CUST-NAME  PIC X(40).
      * Becomes:
      * 01  WS-CUSTOMER-RECORD.
      *     05  WS-CUST-ID       PIC 9(8).
      *     05  WS-CUST-NAME     PIC X(40).

      * DCLGEN (DB2 table declarations)
           EXEC SQL INCLUDE DCLORDER END-EXEC
      * Generates host variable declarations matching DB2 columns
```

---

## 9. Debugging

### Common ABEND Codes

| Code | Meaning | Common Cause |
|------|---------|--------------|
| **S0C7** | Data exception | Non-numeric data in numeric field, uninitialized COMP-3 |
| **S0C4** | Protection exception | Bad pointer, subscript out of range, bad LINKAGE |
| **S0C1** | Operation exception | Branching to non-executable area, bad CALL |
| **S222** | Operator cancelled job | Job exceeded time limit |
| **S322** | CPU time exceeded | Infinite loop, bad PERFORM UNTIL |
| **S0B37** | Dataset out of space | Increase SPACE in JCL |
| **S913** | RACF authorization failure | Missing permissions |

### Debugging Techniques

```cobol
      * DISPLAY debugging (simplest — goes to SYSOUT)
           DISPLAY 'DEBUG: CUST-ID=' WS-CUST-ID
                   ' AMOUNT=' WS-AMOUNT
                   ' AT PARAGRAPH 2100'

      * Compile with SSRANGE to catch subscript errors
      * CBL SSRANGE
      * Or: PARM='SSRANGE' on IGYWCL compile step

      * Compile with TEST for symbolic debugging
      * PARM='TEST(ALL,SYM,SEPARATE)'
```

### CEDF (CICS Execution Diagnostic Facility)

```
CEDF ON     — Enable CEDF for your terminal
              Steps through each EXEC CICS command
              Shows EIBRESP, EIBRESP2, before/after data
CEDF OFF    — Disable
```

---

## 10. Modernization

### GnuCOBOL (Local Development)

```bash
# Install on RHEL/Ubuntu
sudo dnf install gnucobol     # RHEL
sudo apt install gnucobol     # Ubuntu

# Compile and run
cobc -x -o ordproc ordproc.cbl
./ordproc

# Compile with DB2 (via ODBC)
cobc -x ordproc.cbl -ldb2
```

### JSON Support (Enterprise COBOL 6.x+)

```cobol
      * JSON GENERATE
           JSON GENERATE WS-JSON-OUTPUT
               FROM WS-ORDER-RECORD
               COUNT IN WS-JSON-LENGTH
               ON EXCEPTION
                   DISPLAY 'JSON GENERATE FAILED'
               NOT ON EXCEPTION
                   DISPLAY WS-JSON-OUTPUT(1:WS-JSON-LENGTH)
           END-JSON

      * JSON PARSE
           JSON PARSE WS-JSON-INPUT
               INTO WS-ORDER-RECORD
               WITH DETAIL
               ON EXCEPTION
                   DISPLAY 'JSON PARSE FAILED'
           END-JSON
```

### COBOL-to-Service Patterns

| Pattern | Approach | Effort |
|---------|----------|--------|
| CICS Web Service | Expose CICS program as WSDL/REST via CICS TS | Low |
| MQ Bridge | COBOL reads/writes MQ queues, external consumer | Medium |
| Zowe API | Access z/OS resources via REST (Zowe CLI/SDK) | Medium |
| Strangler Fig | Gradually replace COBOL with microservices | High |
| Side-by-Side | Run new service alongside COBOL, sync data | High |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using COMP-3 (packed decimal) for fields that need display output | COMP-3 is not human-readable and causes garbled output in reports and logs | Use DISPLAY for fields that appear in reports; reserve COMP-3 for calculations and storage optimization |
| Hardcoding file record lengths instead of using COPY members | Changes to record layouts require hunting through every program; missed updates cause S0C7 abends | Define record layouts in COPY members; use REPLACE for program-specific field names |
| GO TO spaghetti instead of PERFORM-based structured programming | Unreadable control flow, impossible to debug, and maintenance nightmares | Use PERFORM THRU with well-named paragraphs; eliminate GO TO except for error exit patterns |
| Ignoring SQLCODE after every EXEC SQL statement | Silent failures — a failed SELECT returns stale data, a failed INSERT loses records without alerting anyone | Check SQLCODE after every SQL call; handle -803 (duplicate), -811 (multiple rows), +100 (not found) explicitly |
| Big-bang COBOL-to-microservice rewrites | Multi-year rewrites fail 60%+ of the time; business logic is often undocumented in the COBOL itself | Use Strangler Fig pattern: wrap existing programs with APIs, migrate incrementally, validate at each step |

---

## Related Skills

| Skill | When to Use |
|-------|-------------|
| `ibm-mainframe` | z/OS JCL, VSAM, IDCAMS, DFSORT, ISPF, REXX |
| `db2-mainframe` | DB2 for z/OS (BIND, REORG, RUNSTATS, utilities) |
| `python-enterprise-connectors` | Python → z/OS via Zowe SDK, DB2 Connect |
| `datastage-developer` | DataStage ETL reading from mainframe sources |
| `cognos-admin` | Cognos reporting against DB2 z/OS data |
