ALTER PROCEDURE UPD_SAL_INSTYPE AS 
declare variable EMP_IDENT integer;
declare variable DEP_IDENT smallint;
declare variable MYEAR smallint;
declare variable MMONTH smallint;
declare variable INSID integer;
begin
  for select m.emp_ident,m.dep_ident,m.myear,m.mmonth,e.insur_ident from monthsalary m
  left join customer c on (c.cust_id=m.emp_ident)
  left join employee e on (e.employee_id=c.employee_ident)
  where (m.insur_ident is null)
  into :emp_ident,:dep_ident,:myear,:mmonth,:insid
  do begin
    update monthsalary set insur_ident=:insid
    where (emp_ident=:emp_ident) and (dep_ident=:dep_ident) and (myear=:myear) and (mmonth=:mmonth);
  end
end ^
