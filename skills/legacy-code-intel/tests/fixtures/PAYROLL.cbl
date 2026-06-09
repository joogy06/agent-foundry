       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL.
      *> Sample legacy payroll batch program for legacy-code-intel gold file.
      *> Exercises: paragraphs, PERFORM call-edges, COPY copybook, EXEC SQL
      *> with a connection credential (redaction target), and one DYNAMIC CALL
      *> (must classify speculative).
       AUTHOR. SKILL-FACTORY.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMPLOYEE-FILE ASSIGN TO EMPFILE
               ORGANIZATION IS INDEXED
               ACCESS MODE IS SEQUENTIAL
               RECORD KEY IS EMP-ID.
       DATA DIVISION.
       FILE SECTION.
       FD  EMPLOYEE-FILE.
       01  EMPLOYEE-RECORD.
           05  EMP-ID            PIC X(09).
           05  EMP-NAME          PIC X(30).
           05  EMP-RATE          PIC 9(05)V99.
       WORKING-STORAGE SECTION.
       COPY EMPWS.
       01  WS-EOF-FLAG           PIC X(01) VALUE 'N'.
       01  WS-GROSS-PAY          PIC 9(07)V99.
       01  WS-PROGRAM-NAME       PIC X(08) VALUE 'TAXCALC'.
       01  WS-DB-PASSWORD        PIC X(20) VALUE 'sup3rs3cr3tpw'.
       PROCEDURE DIVISION.
       0000-MAIN-CONTROL.
           PERFORM 1000-INITIALIZE
           PERFORM 2000-PROCESS-EMPLOYEES
               UNTIL WS-EOF-FLAG = 'Y'
           PERFORM 9000-TERMINATE
           STOP RUN.
       1000-INITIALIZE.
           OPEN INPUT EMPLOYEE-FILE
           EXEC SQL
               CONNECT TO PAYDB USER 'PAYUSR'
               IDENTIFIED BY 'sup3rs3cr3tpw'
           END-EXEC
           PERFORM 1100-LOAD-TAX-TABLE.
       1100-LOAD-TAX-TABLE.
           EXEC SQL
               SELECT RATE INTO :WS-TAX-RATE
               FROM TAX_BRACKETS
               WHERE BRACKET = 'STD'
           END-EXEC.
       2000-PROCESS-EMPLOYEES.
           READ EMPLOYEE-FILE
               AT END MOVE 'Y' TO WS-EOF-FLAG
               NOT AT END PERFORM 2100-COMPUTE-PAY
           END-READ.
       2100-COMPUTE-PAY.
           MULTIPLY EMP-RATE BY 40 GIVING WS-GROSS-PAY
           CALL 'TAXCALC' USING WS-GROSS-PAY
           PERFORM 2200-WRITE-PAYSLIP.
       2200-WRITE-PAYSLIP.
           CALL WS-PROGRAM-NAME USING EMPLOYEE-RECORD.
       9000-TERMINATE.
           CLOSE EMPLOYEE-FILE.
