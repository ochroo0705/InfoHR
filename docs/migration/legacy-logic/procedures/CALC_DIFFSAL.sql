ALTER PROCEDURE CALC_DIFFSAL (DATE1 TIMESTAMP,
DATE2 TIMESTAMP)
RETURNS (NUM INTEGER,
MYEAR SMALLINT,
MMONTH INTEGER,
COLCODE CHAR(4) CHARACTER SET UTF8,
CTYPE CHAR(7) CHARACTER SET UTF8,
ORIG_DBACC CHAR(12) CHARACTER SET UTF8,
ORIG_CRACC CHAR(12) CHARACTER SET UTF8,
ORIG_AMOUNT NUMERIC(15, 10),
ORIG_DBCUST INTEGER,
ORIG_CRCUST INTEGER,
ORIG_EXPTYPE INTEGER,
ORIG_FDBEXP INTEGER,
JDB_ACC CHAR(12) CHARACTER SET UTF8,
JCR_ACC CHAR(12) CHARACTER SET UTF8,
JAMOUNT NUMERIC(15, 10),
ERROR_CODE SMALLINT,
ERROR_TEXT VARCHAR(50) CHARACTER SET UTF8)
AS 
declare variable COLID integer;
declare variable DBACC char(12);
declare variable CRACC char(12);
declare variable DBCUST integer;
declare variable CRCUST integer;
declare variable FDBEXP integer;
declare variable EXPTYPE integer;
declare variable STATUS char(3);
declare variable EMPID integer;
declare variable ADV_DATE date;
declare variable SAL_DATE date;
declare variable SUM1 numeric(15,10);
declare variable DEPID smallint;
declare variable ORDERID integer;
declare variable BRANCHID integer;
declare variable TEMPID integer;
declare variable DBACC_BR char(12);
declare variable CRACC_BR char(12);
declare variable DBCUST_BR integer;
declare variable CRCUST_BR integer;
declare variable FDBEXP_BR integer;
declare variable EXPTYPE_BR integer;
declare variable ACCTYPE smallint;
declare variable JDATE date;
begin
  IF (:DATE1 IS NULL) THEN
    SELECT DAT FROM CONVTODATE(100,1,1,3) INTO :DATE1;
  IF (:DATE2 IS NULL) THEN
    SELECT DAT FROM CONVTODATE(5941,1,1,3) INTO :DATE2;
  num=0;
  for select c.colcode, c.col_id, C.DBACC_NUM,C.CRACC_NUM,C.DBCUST_IDENT,C.CRCUST_IDENT,
  C.COLTYPE,C.FDBEXP_IDENT,C.EXPTYPE_IDENT,C.COLSTATUS from colnames c where c.colnames_version_id = -1
  order by c.colcode
  INTO :COLCODE,:COLID,:DBACC,:CRACC,:DBCUST,:CRCUST,:CTYPE,:FDBEXP,:EXPTYPE,:STATUS
  do begin
    for select m.dep_ident,m.emp_ident,m.adv_date,m.sal_date,m.myear,m.mmonth from monthsalary m
    where ((m.adv_date>=:date1) and (m.adv_date<:date2)) or ((m.sal_date>=:date1) and (m.sal_date<:date2))
    group by m.dep_ident,m.emp_ident,m.adv_date,m.sal_date,m.myear,m.mmonth
    order by m.dep_ident,m.emp_ident,m.adv_date,m.sal_date,m.myear,m.mmonth
    into :depid,:empid,:adv_date,:sal_date,:myear,:mmonth
    do begin
      BranchID=0;
      SELECT E.Branch_Ident FROM customer c,EMPloyee E
          WHERE (c.cust_ID=:EMPID) and (e.employee_id=c.employee_ident)
          INTO :BranchID;
      if (BranchID is null) then
        BranchID=0;
      if (BranchID>0) then begin
        tempid=0;
        SELECT Branch_Ident,DBACC_NUM,CRACC_NUM,DBCUST_IDENT,CRCUST_IDENT,FDBEXP_IDENT,EXPTYPE_IDENT
          from branch_colnames
          where (branch_Ident=:BranchID) and (COL_IDENT=:COLID)
          into :tempid,:DBACC_BR,:CRACC_BR,:DBCUST_BR,:CRCUST_BR,:FDBEXP_BR,:EXPTYPE_BR;
        if (tempid is null) then
          tempid=0;
        if (tempid>0) then begin
          DBACC=DBACC_BR;
          CRACC=CRACC_BR;
          DBCUST=DBCUST_BR;
          CRCUST=CRCUST_BR;
          FDBEXP=FDBEXP_BR;
          EXPTYPE=EXPTYPE_BR;
        end
      end

      IF ((DBACC IS NOT NULL) OR (CRACC IS NOT NULL)) THEN BEGIN
        IF (:EXPTYPE IS NULL) THEN
          SELECT D.EXPTYPE_IDENT FROM DEPS D
            WHERE (D.DEP_ID=:DEPID)
          INTO :EXPTYPE;
        IF (STATUS<>'SOC') THEN BEGIN
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
            SELECT SOCINS_ACC,CUST_IDENT FROM DEPS
              WHERE (DEP_ID=:DEPID)
            INTO :DBACC,:DBCUST;
          ELSE IF (CRACC IS NULL) THEN
            SELECT SOCINS_ACC,CUST_IDENT FROM DEPS
              WHERE (DEP_ID=:DEPID)
            INTO :CRACC,:CRCUST;
        END
        ORDERID=DEPID*1000000+MYEAR*100+MMONTH;
    
        IF ((DBACC IS NULL) OR (CRACC IS NULL)) THEN
          EXCEPTION ACCOUNT_NOTDEFINED_ONDEPS;
        IF ((FDBEXP IS NULL) OR (NOT (FDBEXP>0))) THEN
          SELECT O.FDBEXP_IDENT FROM customer c,EMPloyee E
            LEFT JOIN OCCUPATION O ON (O.OCCUPATION_ID=E.OCCUPATION_IDENT)
          WHERE (c.cust_ID=:EMPID) and (e.employee_id=c.employee_ident)
          INTO :FDBEXP;
    
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
        IF (CTYPE='advance') THEN
          JDATE=ADV_DATE;
        ELSE
          JDATE=SAL_DATE;

        select sum1 from CALC_SALNEW(:COLCODE,:empid,:adv_date,:sal_date)
        into :sum1;
        if (sum1 is null) then sum1=0;

        orig_dbacc=dbacc;
        orig_cracc=cracc;
        orig_dbcust=dbcust;
        orig_crcust=crcust;
        orig_exptype=exptype;
        orig_fdbexp=fdbexp;
        orig_amount=sum1;
        select ERROR_CODE,ERROR_TEXT,JAMOUNT from CALC_DIFFERROR2(:orderid,:orig_dbacc,:orig_cracc,:orig_amount,:orig_dbcust,:orig_crcust,:orig_exptype,:orig_fdbexp,:jdate)
        into :error_code,:error_text,:jamount;

        if (orig_dbcust is null) then orig_dbcust=-1;
        if (orig_crcust is null) then orig_crcust=-1;
        if (orig_exptype is null) then orig_exptype=-1;
        if (orig_fdbexp is null) then orig_fdbexp=-1;
        insert into TEMP_ORDERACC2(ORDER_IDENT,DBACC,CRACC,DBCUST,CRCUST,EXPTYPE,FDBEXP,COLCODE)
        values (:ORDERID,:orig_dbacc,:orig_cracc,:orig_dbcust,:orig_crcust,:orig_exptype,:orig_fdbexp,:COLCODE);
        num=num+1;
        suspend;
      end
    end
  end
end ^
