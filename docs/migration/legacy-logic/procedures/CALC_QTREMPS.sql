ALTER PROCEDURE CALC_QTREMPS (YY SMALLINT,
MM SMALLINT,
EMPID INTEGER)
RETURNS (CNT_SAL INTEGER)
AS 
begin
  select count(*) from customer c
  join monthsalary m on (c.cust_id=m.emp_ident)
  where (c.employee_ident=:empid) and (m.myear=:yy) and (m.mmonth<=:mm)
  into :cnt_sal;
  if (cnt_sal is null) then
    cnt_sal=0;
  suspend;
end ^
