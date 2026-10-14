ALTER PROCEDURE CHANGED_SALJOURNAL (CCODE CHAR(4) CHARACTER SET UTF8,
MYEAR SMALLINT,
MMONTH SMALLINT,
DEPID INTEGER,
EMPID INTEGER,
AMOUNT NUMERIC(15, 2),
TYP CHAR(3) CHARACTER SET UTF8,
ADV_DATE TIMESTAMP,
SAL_DATE TIMESTAMP)
AS 
declare variable CRACC char(12);
declare variable CRCUST integer;
declare variable CTYPE char(7);
declare variable DBACC char(12);
declare variable DBCUST integer;
declare variable ORDERID integer;
declare variable FDBEXP integer;
declare variable EXPTYPE integer;
declare variable CC integer;
declare variable EID integer;
declare variable WHAT varchar(80);
declare variable DEPNAME char(25);
declare variable ACCTYPE char(2);
declare variable EXPTYPENAME varchar(30);
declare variable JDATE date;
declare variable STATUS char(3);
declare variable BRANCHID integer;
declare variable TEMPID integer;
declare variable CRACC_BR char(12);
declare variable CRCUST_BR integer;
declare variable DBACC_BR char(12);
declare variable DBCUST_BR integer;
declare variable FDBEXP_BR integer;
declare variable EXPTYPE_BR integer;
declare variable COLID integer;
declare variable TEMPMONTH char(2);
declare variable TEMPDEPID char(5);
declare variable JNUMBER varchar(12);
BEGIN


  /* CHECK ACCOUNT AND CUSTOMER FROM COLNAMES*/
  SELECT c.col_id, C.DBACC_NUM,C.CRACC_NUM,C.DBCUST_IDENT,C.CRCUST_IDENT,C.COLTYPE,C.FDBEXP_IDENT,C.EXPTYPE_IDENT,E.DESCRIPTION,C.COLSTATUS
    FROM COLNAMES C
  LEFT JOIN EXPENSETYPE E ON (E.EXPTYPE_ID=C.EXPTYPE_IDENT)
    WHERE (C.COLCODE=:CCODE) and (c.colnames_version_id = -1) /*undsen tohirgoo deer tohiruulj bgaa*/
  INTO :COLID,:DBACC,:CRACC,:DBCUST,:CRCUST,:CTYPE,:FDBEXP,:EXPTYPE,:EXPTYPENAME,:STATUS;
  SELECT NAME FROM DEPS
    WHERE (DEP_ID=:DEPID)
  INTO :DEPNAME;

  BranchID=0;
  SELECT E.Branch_Ident FROM customer c,EMPloyee E
      WHERE (c.cust_ID=:EMPID) and (e.employee_id=c.employee_ident)
      INTO :BranchID;
  if (BranchID is null) then
    BranchID=0;
  if (BranchID>0) then begin
    Tempid=0;
    SELECT Branch_Ident,DBACC_NUM,CRACC_NUM,DBCUST_IDENT,CRCUST_IDENT,FDBEXP_IDENT,EXPTYPE_IDENT
      from branch_colnames
      where (branch_Ident=:BranchID) and (COL_IDENT=:COLID)
      into :tempid,:DBACC_BR,:CRACC_BR,:DBCUST_BR,:CRCUST_BR,:FDBEXP_BR,:EXPTYPE_BR;
    if (tempid is null) then
      Tempid=0;
    if (tempid>0) then begin
      DBACC=DBACC_BR;
      CRACC=CRACC_BR;
      DBCUST=DBCUST_BR;
      CRCUST=CRCUST_BR;
      FDBEXP=FDBEXP_BR;
      EXPTYPE=EXPTYPE_BR;
    end
  end

  IF (:EXPTYPE IS NULL) THEN
    SELECT D.EXPTYPE_IDENT,E.DESCRIPTION FROM DEPS D
    LEFT JOIN EXPENSETYPE E ON (E.EXPTYPE_ID=D.EXPTYPE_IDENT)
      WHERE (DEP_ID=:DEPID)
    INTO :EXPTYPE,:EXPTYPENAME;
  IF  ((DBACC IS NOT NULL) OR (CRACC IS NOT NULL)) THEN BEGIN
    IF (EXPTYPENAME IS NULL) THEN EXPTYPENAME='';

    IF (STATUS<>'SOC') THEN BEGIN
      IF (STATUS<>'LST') THEN BEGIN
        IF (DBACC IS NULL) THEN
          SELECT ACC_NUM,CUST_IDENT FROM DEPS
            WHERE (DEP_ID=:DEPID)
          INTO :DBACC,:DBCUST;
        ELSE IF (CRACC IS NULL) THEN
          SELECT ACC_NUM,CUST_IDENT FROM DEPS
            WHERE (DEP_ID=:DEPID)
          INTO :CRACC,:CRCUST;
      END
      ELSE BEGIN
        IF (DBACC IS NULL) THEN
          SELECT LIST_ACC,CUST_IDENT FROM DEPS
            WHERE (DEP_ID=:DEPID)
          INTO :DBACC,:DBCUST;
        ELSE IF (CRACC IS NULL) THEN
          SELECT LIST_ACC,CUST_IDENT FROM DEPS
            WHERE (DEP_ID=:DEPID)
          INTO :CRACC,:CRCUST;
      END
    END
    ELSE BEGIN
      IF (DBACC IS NULL) THEN
        SELECT SOCINS_ACC,CUST_IDENT FROM DEPS
          WHERE (DEP_ID=:DEPID)
        INTO :DBACC,:DBCUST;
      ELSE IF (CRACC IS NULL) THEN
        SELECT SOCINS_ACC,CUST_IDENT FROM DEPS
          WHERE (DEP_ID=:DEPID)
        INTO :CRACC,:CRCUST;
    END

    IF ((DBACC IS NULL) OR (CRACC IS NULL)) THEN
      EXCEPTION ACCOUNT_NOTDEFINED_ONDEPS;
    IF ((FDBEXP IS NULL) OR (NOT (FDBEXP>0))) THEN
      SELECT c.cust_ID,O.FDBEXP_IDENT FROM customer c,EMPloyee E
        LEFT JOIN OCCUPATION O ON (O.OCCUPATION_ID=E.OCCUPATION_IDENT)
      WHERE (c.cust_ID=:EMPID) and (e.employee_id=c.employee_ident)
      INTO :EID,:FDBEXP;
    /*ORDERID IS NOT DUPLICATE */
/*    ORDERID=MYEAR+MMONTH+DEPID;*/
    ORDERID=DEPID*1000000+MYEAR*100+MMONTH;

    SELECT ACCOUNT_TYPE FROM ACCOUNT
      WHERE (ACCNO=:DBACC)
    INTO :ACCTYPE;
    IF ((DBCUST IS NULL) AND ((ACCTYPE='12') OR (ACCTYPE='31'))) THEN
      DBCUST=EMPID;
    SELECT ACCOUNT_TYPE FROM ACCOUNT
      WHERE (ACCNO=:CRACC)
    INTO :ACCTYPE;
    IF ((CRCUST IS NULL) AND ((ACCTYPE='12') OR (ACCTYPE='31'))) THEN
      CRCUST=EMPID;
    IF (CTYPE='advance') THEN BEGIN
      JDATE=ADV_DATE;
      IF (EXPTYPENAME<>'') THEN
        WHAT=:EXPTYPENAME||' - '||:DEPNAME;
      ELSE begin
        select description from jwhats where (JWHAT_ID=3) and (sysflag=1)
        into :what;
        WHAT=WHAT||' - '||:DEPNAME;
      end
    END
    ELSE BEGIN
      JDATE=SAL_DATE;
      if (JDATE is null) then
        JDATE=ADV_DATE;

      IF (EXPTYPENAME<>'') THEN
        WHAT=:EXPTYPENAME||' - '||:DEPNAME;
      ELSE begin
        select description from jwhats where (JWHAT_ID=4) and (sysflag=1)
        into :what;
        WHAT=WHAT||' - '||:DEPNAME;
      end
    END
    SELECT journal_id FROM JOURNAL
     WHERE (JDATE=:JDATE) AND
           (JORDER_IDENT=:ORDERID) AND (JOURNALCODE='SAL') AND
           (DBACC_NUM=:DBACC) AND (CRACC_NUM=:CRACC) AND
           (((:DBCUST IS NOT NULL) AND (DBCUST_IDENT=:DBCUST)) OR (:DBCUST IS NULL)) AND
           (((:CRCUST IS NOT NULL) AND (CRCUST_IDENT=:CRCUST)) OR (:CRCUST IS NULL)) AND
           (((:EXPTYPE IS NOT NULL) AND (EXPTYPE_IDENT=:EXPTYPE)) OR (:EXPTYPE IS NULL)) AND
           (((:FDBEXP IS NOT NULL) AND (FDBEXP_IDENT=:FDBEXP)) OR (:FDBEXP IS NULL))
    rows 1
    INTO :CC;
    if (cc is  null) then
      cc=0;
    IF (CC>0) THEN BEGIN
      IF (TYP='OLD') THEN
        UPDATE JOURNAL
          SET JAMOUNT=JAMOUNT - :AMOUNT
        WHERE (JDATE=:JDATE) AND
              (JORDER_IDENT=:ORDERID) AND (JOURNALCODE='SAL') AND 
              (DBACC_NUM=:DBACC) AND (CRACC_NUM=:CRACC) AND
              (((:DBCUST IS NOT NULL) AND (DBCUST_IDENT=:DBCUST)) OR (:DBCUST IS NULL)) AND
              (((:CRCUST IS NOT NULL) AND (CRCUST_IDENT=:CRCUST)) OR (:CRCUST IS NULL)) AND
              (((:EXPTYPE IS NOT NULL) AND (EXPTYPE_IDENT=:EXPTYPE)) OR (:EXPTYPE IS NULL)) AND
              (((:FDBEXP IS NOT NULL) AND (FDBEXP_IDENT=:FDBEXP)) OR (:FDBEXP IS NULL));
      ELSE IF (TYP='NEW') THEN
        UPDATE JOURNAL
          SET JAMOUNT=JAMOUNT + :AMOUNT
        WHERE (JDATE=:JDATE) AND
              (JORDER_IDENT=:ORDERID) AND (JOURNALCODE='SAL') AND
              (DBACC_NUM=:DBACC) AND (CRACC_NUM=:CRACC) AND
              (((:DBCUST IS NOT NULL) AND (DBCUST_IDENT=:DBCUST)) OR (:DBCUST IS NULL)) AND
              (((:CRCUST IS NOT NULL) AND (CRCUST_IDENT=:CRCUST)) OR (:CRCUST IS NULL)) AND
              (((:EXPTYPE IS NOT NULL) AND (EXPTYPE_IDENT=:EXPTYPE)) OR (:EXPTYPE IS NULL)) AND
              (((:FDBEXP IS NOT NULL) AND (FDBEXP_IDENT=:FDBEXP)) OR (:FDBEXP IS NULL));
    END
    ELSE IF (TYP='NEW') THEN BEGIN
      execute procedure get_docnumber(23)
      returning_values :jnumber;
      INSERT INTO JOURNAL(JORDER_IDENT,JNUMBER,JDATE,DBACC_NUM,CRACC_NUM,DBCUST_IDENT,CRCUST_IDENT,
          JWHAT,JAMOUNT,JAMOUNTV,JRATE,JVCODE,JTYPE,JOURNALCODE,FDBEXP_IDENT,
          EXPTYPE_IDENT)
      VALUES(:ORDERID,:jnumber,:JDATE,:DBACC,:CRACC,:DBCUST,:CRCUST,
          :WHAT,:AMOUNT,0,0,NULL,1,'SAL',:FDBEXP,
          :EXPTYPE);
    END
  END
END ^
