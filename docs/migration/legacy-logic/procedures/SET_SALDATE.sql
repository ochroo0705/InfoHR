ALTER PROCEDURE SET_SALDATE AS 
DECLARE VARIABLE myear integer;
DECLARE VARIABLE mmonth integer;
DECLARE VARIABLE advdate timestamp;
DECLARE VARIABLE saldate timestamp;
BEGIN
  for select distinct myear,mmonth from monthsalary
  into myear,mmonth
  do begin
    select dat from convtodate(:myear,:mmonth,'10',3)
    into advdate;
    select dat from convtodate(:myear,:mmonth,'25',3)
    into saldate;
    update monthsalary
      set adv_date=:advdate,
          sal_date=:saldate
    where (myear=:myear) and (mmonth=:mmonth);
  end
END ^
