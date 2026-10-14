ALTER PROCEDURE CALC_TAXTABLEEMP (YY SMALLINT,
MM1 SMALLINT,
MM2 SMALLINT,
DEPID INTEGER,
EMPID INTEGER)
RETURNS (MMONTH SMALLINT,
FNAME CHAR(28) CHARACTER SET UTF8,
NAME1 CHAR(25) CHARACTER SET UTF8,
SURNAME1 CHAR(25) CHARACTER SET UTF8,
REGISTER1 VARCHAR(20) CHARACTER SET UTF8,
EMDNO CHAR(14) CHARACTER SET UTF8,
NDNO CHAR(14) CHARACTER SET UTF8,
ECODE CHAR(20) CHARACTER SET UTF8,
MAINSALARY NUMERIC(15, 2),
PENS1 NUMERIC(15, 2),
PENS2 NUMERIC(15, 2),
STEP1 NUMERIC(15, 2),
STEP2 NUMERIC(15, 2),
INEMP1 NUMERIC(15, 2),
INEMP2 NUMERIC(15, 2),
HEALTH1 NUMERIC(15, 2),
HEALTH2 NUMERIC(15, 2),
OTHER NUMERIC(15, 2),
SUMTAX1 NUMERIC(15, 2),
SUMTAX2 NUMERIC(15, 2),
SUMTOTAL NUMERIC(15, 2))
AS 
begin
  for select M.MMonth,E.Name,E.SurName,C.Register,E.EMDNo,E.NDNo,E.ecode,S.sum1,
  S1.sum1,S2.sum1,S3.sum1,S4.sum1,S5.sum1,S6.sum1,S7.sum1,S8.sum1,S9.sum1,
  (S1.sum1+S3.sum1+S5.sum1+S7.sum1) as sumtax1,(S2.sum1+S4.sum1+S6.sum1+S8.sum1+S9.sum1) as sumtax2,
  (S1.sum1+S3.sum1+S5.sum1+S7.sum1+S2.sum1+S4.sum1+S6.sum1+S8.sum1+S9.sum1) as sumtotal
  /*from MonthSalary M,Customer C*/
  from MonthSalary M
  left join Customer C on (C.cust_id=M.emp_ident)
  left join Employee E on (E.Employee_Id=C.Employee_Ident)
  left join calc_tax('SAL',C.cust_id,:YY,M.MMonth) S on (0=0)
  left join calc_tax('IEP',C.cust_id,:YY,M.MMonth) S1 on (0=0)
  left join calc_tax('IOP',C.cust_id,:YY,M.MMonth) S2 on (0=0)
  left join calc_tax('IES',C.cust_id,:YY,M.MMonth) S3 on (0=0)
  left join calc_tax('IOS',C.cust_id,:YY,M.MMonth) S4 on (0=0)
  left join calc_tax('IEU',C.cust_id,:YY,M.MMonth) S5 on (0=0)
  left join calc_tax('IOU',C.cust_id,:YY,M.MMonth) S6 on (0=0)
  left join calc_tax('IEH',C.cust_id,:YY,M.MMonth) S7 on (0=0)
  left join calc_tax('IOH',C.cust_id,:YY,M.MMonth) S8 on (0=0)
  left join calc_tax('IOE',C.cust_id,:YY,M.MMonth) S9 on (0=0)
  /*where  (C.Cust_Id=M.Emp_Ident) and (M.MYear=:YY) and (M.MMonth=:MM) and*/
  where (M.MYear=:YY) and (M.MMonth>=:MM1) and (M.MMonth<=:MM2) and
  ((:empid is null) or ((:empid is not null) and (E.employee_id=:empid))) and
  ((:depid is null) or ((:depid is not null) and (M.dep_ident=:DEPID))) and
  ((S.sum1>=0.01) or (S.sum1<=-0.01))
  group by M.MMonth,E.Name,E.SurName,C.Register,E.EMDNo,E.NDNo,E.ecode,S.sum1,
  S1.sum1,S2.sum1,S3.sum1,S4.sum1,S5.sum1,S6.sum1,S7.sum1,S8.sum1,S9.sum1/*,
  S1.sum1+S3.sum1+S5.sum1+S7.sum1,S2.sum1+S4.sum1+S6.sum1+S8.sum1+S9.sum1,
  S1.sum1+S3.sum1+S5.sum1+S7.sum1+S2.sum1+S4.sum1+S6.sum1+S8.sum1+S9.sum1*/
  into :mmonth,:NAME1,:SURNAME1,:REGISTER1,:EMDNO,:NDNO,:ECODE,:MAINSALARY,:PENS1,:PENS2,:STEP1,
       :STEP2,:INEMP1,:INEMP2,:HEALTH1,:HEALTH2,:OTHER,:SUMTAX1,:SUMTAX2,:SUMTOTAL
  do begin
    FNAME=trim(:NAME1)||'. '||substring(trim(:SURNAME1) from 1 for 1);
    suspend;
  end

end ^
