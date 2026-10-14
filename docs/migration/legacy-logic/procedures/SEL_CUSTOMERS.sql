ALTER PROCEDURE SEL_CUSTOMERS RETURNS (CUST_ID INTEGER,
NAME VARCHAR(80) CHARACTER SET UTF8,
SURNAME VARCHAR(30) CHARACTER SET UTF8,
TTD VARCHAR(20) CHARACTER SET UTF8,
INCD_NUM VARCHAR(20) CHARACTER SET UTF8)
AS 
declare variable EMPID integer;
begin
  for select cust_id,description,ttd,incd_num,employee_ident from customer
  order by description
  into :cust_id,:name,:ttd,:incd_num,:empid
  do begin
    if (:empid>0) then
      select name,surname from employee
      where (employee_id=:empid)
      into :name,:surname;
    else
      surname=null;
    suspend;
  end
end ^
