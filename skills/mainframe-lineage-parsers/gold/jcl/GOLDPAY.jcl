//GOLDPAY  JOB (ACCT),'GOLD FIXTURE',CLASS=A,MSGCLASS=X
//*****************************************************************
//* gold/ precision fixture JCL (advisory-until-gold, #158).      *
//* The PAYIN/PAYOUT DD/DSN bind keys must stitch to the COBOL    *
//* SELECT ... ASSIGN TO UT-S-PAYIN / UT-S-PAYOUT (DD-join, the   *
//* first precision-win edge class). Literal DSNs -> grounded     *
//* dataset->job edges; the stitch bridge is inferred (never      *
//* grounded). ADVISORY ONLY: never feeds a gate. See README.md.  *
//*****************************************************************
//STEP010  EXEC PGM=GOLDPAY
//PAYIN    DD DSN=PROD.PAYROLL.MASTER,DISP=SHR
//PAYOUT   DD DSN=PROD.PAYROLL.REPORT,DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(5,1),RLSE)
//SYSOUT   DD SYSOUT=*
