* ORD.POST  -- post pending orders, update customer balances
* MultiValue / Pick BASIC sample fixture for legacy-code-intel.
      PROGRAM ORD.POST
      COMMON /ORD.CTX/ RUN.DATE, OPERATOR
      EQUATE AM TO CHAR(254), VM TO CHAR(253)

      OPEN "ORDERS" TO F.ORD ELSE STOP 201, "ORDERS"
      OPEN "CUSTOMERS" TO F.CUST ELSE STOP 201, "CUSTOMERS"

      GOSUB INIT
      SELECT F.ORD TO ORD.LIST
      LOOP
         READNEXT OID FROM ORD.LIST ELSE EXIT
         READU REC FROM F.ORD, OID ELSE CONTINUE
            IF REC<9> = "P" THEN
               GOSUB POST.ONE
            END
         WRITE REC ON F.ORD, OID
      REPEAT

      EXECUTE "LIST ORDERS WITH STATUS = 'S'"
      CALL ORD.AUDIT(RUN.DATE)
      CALL @POST.HOOK(OID)
      STOP

   INIT:
      RUN.DATE = OCONV(DATE(), "D2/")
      RETURN

   POST.ONE:
      CUST.ID = REC<2>
      AMT     = REC<7,1>
      READU CREC FROM F.CUST, CUST.ID THEN
         CREC<5> = CREC<5> + AMT
         WRITE CREC ON F.CUST, CUST.ID
      END ELSE
         RELEASE F.CUST, CUST.ID
      END
      REC<9> = "S"
      RETURN
