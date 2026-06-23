       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOLDPAY.
      *****************************************************************
      * gold/ precision fixture (advisory-until-gold, #158).         *
      * Exercises both precision-win edge classes against a frozen   *
      * expected-edges table:                                        *
      *   (1) DD-join: SELECT ... ASSIGN TO <ddname> stitched to the *
      *       JCL DD/DSN bind key (GOLDPAY.jcl PAYIN/PAYOUT).        *
      *   (2) host-var:column: EXEC SQL host-var -> table.column,    *
      *       resolvable to inferred when --schema is supplied.      *
      * ADVISORY ONLY: never feeds a gate (design 6). See README.md. *
      *****************************************************************
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PAY-IN  ASSIGN TO UT-S-PAYIN.
           SELECT PAY-OUT ASSIGN TO UT-S-PAYOUT.
       DATA DIVISION.
       FILE SECTION.
       FD  PAY-IN.
       01  PAY-IN-REC.
           05  PI-EMPNO        PIC 9(06).
           05  PI-NAME         PIC X(30).
       FD  PAY-OUT.
       01  PAY-OUT-REC.
           05  PO-EMPNO        PIC 9(06).
           05  PO-NET          PIC 9(07)V99 COMP-3.
       WORKING-STORAGE SECTION.
       01  WS-EMPNO            PIC 9(06).
       01  WS-NAME             PIC X(30).
       01  WS-SALARY           PIC 9(07)V99.
       01  WS-NET              PIC 9(07)V99.
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ PAY-IN INTO PAY-IN-REC.
           EXEC SQL
               SELECT NAME, SALARY
               INTO :WS-NAME, :WS-SALARY
               FROM EMPLOYEE
               WHERE EMPNO = :WS-EMPNO
           END-EXEC.
           EXEC SQL
               UPDATE EMPLOYEE
               SET NET_PAY = :WS-NET
               WHERE EMPNO = :WS-EMPNO
           END-EXEC.
           WRITE PAY-OUT-REC.
           STOP RUN.
