ALTER PROCEDURE REPAIR_ALLSALJOURNAL RETURNS (MYEAR INTEGER,
MMONTH INTEGER)
AS 
begin
  for select  myear,mmonth from monthsalary
  group by myear,mmonth
  into :myear,:mmonth
  do begin
    execute procedure REPAIR_SALJOURNAL('salary',:myear,:mmonth,null);
    suspend;
  end



end ^
