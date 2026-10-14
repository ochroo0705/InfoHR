ALTER PROCEDURE CALC_STAFFS (DATE1 TIMESTAMP,
DATE2 TIMESTAMP,
DATEX1 TIMESTAMP,
DATEX2 TIMESTAMP)
RETURNS (ID INTEGER,
DESCRIPTION VARCHAR(50) CHARACTER SET UTF8,
EMP_QTY INTEGER,
SUM1 NUMERIC(15, 2),
SUM2 NUMERIC(15, 2))
AS 
declare variable CUST integer;
declare variable TEMPSUM numeric(15,2);
declare variable BB integer;
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
  for select c.cust_id from customer c
  left join employee e on (e.employee_id=c.employee_ident)
  left join occupation o on (o.occupation_id=e.occupation_ident)
  where (o.occup=1)
  into :cust
  do begin
    bb = 0;
    select sum(sum1) from calc_sal(:cust,:datex1,:datex2)
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    sum1 = sum1 + tempsum;

    if (tempsum>0) then
      bb = 1;

    tempsum = null;
    select sum(sum1) from calc_sal(:cust,:date1,:date2)
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
    select sum(sum1) from calc_sal(:cust,:datex1,:datex2)
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    sum1 = sum1 + tempsum;
    if (tempsum>0) then
      bb = 1;


    tempsum = null;
    select sum(sum1) from calc_sal(:cust,:date1,:date2)
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

    select sum(sum1) from calc_sal(:cust,:datex1,:datex2)
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    sum1 = sum1 + tempsum;
    if (tempsum>0) then
      bb = 1;

    tempsum = null;
    select sum(sum1) from calc_sal(:cust,:date1,:date2)
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
