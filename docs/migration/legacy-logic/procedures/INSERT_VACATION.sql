ALTER PROCEDURE INSERT_VACATION (DEPID INTEGER,
MYEAR SMALLINT)
AS 
declare variable EMPID integer;
declare variable DEP integer;
declare variable CC integer;
begin
  for select employee_id, dep_ident from employee
  where ((dep_ident=:depid) and (:depid is not null)) or (:depid is null)
  order by employee_id
  into :empid,:dep
  do begin
    select count(*) from emp_vacation
    where (emp_ident=:empid) and (myear=:myear)
    into :cc;
    if (cc is null) then
      cc=0;
    if (CC=0) then
      insert into emp_vacation (emp_ident,dep_ident,xmonth,myear,mmonth)
      values (:empid,:dep,0,:myear,1);
  end
end ^
