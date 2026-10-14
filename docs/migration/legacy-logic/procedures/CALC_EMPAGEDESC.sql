ALTER PROCEDURE CALC_EMPAGEDESC (EMP_ID INTEGER)
RETURNS (AGE_INTRVL VARCHAR(25) CHARACTER SET UTF8)
AS 
declare variable BDAY date;
declare variable AGE integer;
declare variable MINAGE smallint;
declare variable MAXAGE smallint;
declare variable INTERVAL integer;
declare variable OK_INTERVAL integer;
begin
  age_intrvl='';
  select e.birthday from employee e
  where (e.employee_id=:emp_id)
  into :bday;
  select age from calc_age(:bday,current_timestamp)
  into :age;
  ok_interval=null;
  for select i.interval_id,i.min_age,i.max_age from age_interval i
  into :interval,:minage,:maxage
  do if ((age>=:minage) and (age<=:maxage)) then
       ok_interval=:interval;

  if (ok_interval is not null) then begin
    select i.min_age,i.max_age from age_interval i
    where (i.interval_id=:ok_interval)
    into :minage,:maxage;
    age_intrvl=cast(:minage as varchar(3))||'-'||cast(:maxage as varchar(3));
  end
  suspend;
end ^
