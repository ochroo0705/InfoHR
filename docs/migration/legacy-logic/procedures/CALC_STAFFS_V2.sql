ALTER PROCEDURE CALC_STAFFS_V2 (DATE1 TIMESTAMP,
DATE2 TIMESTAMP,
DATEX1 TIMESTAMP,
DATEX2 TIMESTAMP,
BRANCHID INTEGER)
RETURNS (ID INTEGER,
DESCRIPTION VARCHAR(50) CHARACTER SET UTF8,
EMP_QTY INTEGER,
SUM1 NUMERIC(15, 2),
SUM2 NUMERIC(15, 2))
AS 
declare variable CUST integer;
declare variable TEMPSUM numeric(15,2);
declare variable BB integer;
declare variable COLCODE char(3);
declare variable BRANCHSQL varchar(100);
begin
  IF (:DATE1 IS NULL) THEN
    SELECT DAT FROM CONVTODATE(100,1,1,3) INTO :DATE1;
  IF (:DATE2 IS NULL) THEN
    SELECT DAT FROM CONVTODATE(5941,1,1,3) INTO :DATE2;

  ID=1;
  Description='Үйлдвэрлэл, үйлчилгээний';
  sum1=0;
  sum2=0;
  emp_qty=0;

  select colcode from colnames
  where (colstatus='SAL') and (coltype='salary') and (colnames_version_id = -1)
  into :colcode;

  if (:branchid is not null) then
    branchsql = ' and (branch_ident = '||:branchid||')';
  else
    branchsql = '';


  for select c.cust_id from customer c
  left join employee e on (e.employee_id=c.employee_ident)
  left join occupation o on (o.occupation_id=e.occupation_ident)
  where (o.occup=1)
  into :cust
  do begin
    bb = 0;
    execute statement 'select sum('||colcode||') from monthsalary
    where (emp_ident='||:cust||') and (sal_date>='''||cast(:datex1 as varchar(25))||''') and (sal_date<'''||cast(:datex2 as varchar(25))||''')'||branchsql
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    sum1 = sum1 + tempsum;

    if (tempsum>0) then
      bb = 1;

    tempsum = null;
    execute statement 'select sum('||colcode||') from monthsalary
    where (emp_ident='||:cust||') and (sal_date>='''||cast(:date1 as varchar(25))||''') and (sal_date<'''||cast(:date2 as varchar(25))||''')'||branchsql
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    sum2 = sum2 + tempsum;

    if (tempsum>0) then
      bb = 1;
    emp_qty=emp_qty+bb;
  end
  if (sum1 is null) then sum1=0;
  if (sum2 is null) then sum2=0;
  suspend;

  ID=2;
  Description='Борлуулалт маркетингийн';
  sum1=0;
  sum2=0;
  emp_qty=0;
  for select c.cust_id from customer c
  left join employee e on (e.employee_id=c.employee_ident)
  left join occupation o on (o.occupation_id=e.occupation_ident)
  where (o.occup=2)
  into :cust
  do begin
    tempsum = null; bb = 0;

    execute statement 'select sum('||colcode||') from monthsalary
    where (emp_ident='||:cust||') and (sal_date>='''||cast(:datex1 as varchar(25))||''') and (sal_date<'''||cast(:datex2 as varchar(25))||''')'||branchsql
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    sum1 = sum1 + tempsum;
    if (tempsum>0) then
      bb = 1;


    tempsum = null;
    execute statement 'select sum('||colcode||') from monthsalary
    where (emp_ident='||:cust||') and (sal_date>='''||cast(:date1 as varchar(25))||''') and (sal_date<'''||cast(:date2 as varchar(25))||''')'||branchsql
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    sum2 = sum2 + tempsum;
    if (tempsum>0) then
      bb = 1;

    emp_qty=emp_qty+bb;

  end
  if (sum1 is null) then sum1=0;
  if (sum2 is null) then sum2=0;
  suspend;

  ID=3;
  Description='Ерөнхий ба удирдлагын';
  sum1=0;
  sum2=0;
  emp_qty=0;
  for select c.cust_id from customer c
  left join employee e on (e.employee_id=c.employee_ident)
  left join occupation o on (o.occupation_id=e.occupation_ident)
  where (o.occup=3)
  into :cust
  do begin
    tempsum = null; bb = 0;

    execute statement 'select sum('||colcode||') from monthsalary
    where (emp_ident='||:cust||') and (sal_date>='''||cast(:datex1 as varchar(25))||''') and (sal_date<'''||cast(:datex2 as varchar(25))||''')'||branchsql
    into :tempsum;

    if (tempsum is null) then tempsum = 0;
    sum1 = sum1 + tempsum;
    if (tempsum>0) then
      bb = 1;

    tempsum = null;

    execute statement 'select sum('||colcode||') from monthsalary
    where (emp_ident='||:cust||') and (sal_date>='''||cast(:date1 as varchar(25))||''') and (sal_date<'''||cast(:date2 as varchar(25))||''')'||branchsql
    into :tempsum;

    if (tempsum is null) then tempsum = 0;
    sum2 = sum2 + tempsum;
    if (tempsum>0) then
      bb = 1;


    emp_qty=emp_qty+bb;
  end
  if (sum1 is null) then sum1=0;
  if (sum2 is null) then sum2=0;
  suspend;
end ^
