ALTER PROCEDURE CALC_TIME_ATTENDANCE (EMPID INTEGER,
DATE1 TIMESTAMP,
DATE2 TIMESTAMP)
RETURNS (EMP_ID INTEGER,
INDATE TIMESTAMP,
WORKTIME INTEGER,
WDAY INTEGER,
OUTDATE TIMESTAMP,
DELAYTIME INTEGER,
MORETIME INTEGER,
TEATIME INTEGER)
AS 
declare variable OUTMINUTE integer;
declare variable INMINUTE integer;
declare variable FINISHMINUTE integer;
declare variable BEGINMINUTE integer;
declare variable TEMPDATE date;
begin
  for select checkdate, emp_ident from checkinout
  where ((:empid=0) or  ((:empid<>0) and (emp_ident=:empid)))
     and ((:date1 is null) or ((:date1 is not null) and (checkdate >=:date1)))
     and ((:date2 is null ) or ((:date2 is not null )and (checkdate<=:date2)))
  group by checkdate, emp_ident
  into :tempdate, :emp_id
  do begin  
    delaytime=0;
    moretime=0;
    worktime=0;
    wday=extract(weekday from tempdate);

    select min(checktime), max(checktime) from checkinout
    where (checkdate=:tempdate) and (emp_ident=:emp_id)
    into :indate, :outdate;

    inminute =EXTRACT(Hour FROM indate)*60+EXTRACT(minute FROM indate);
    outminute =EXTRACT(Hour FROM outdate)*60+EXTRACT(minute FROM outdate);

    select EXTRACT(Hour FROM tp.begintime)*60+EXTRACT(minute FROM tp.begintime),
           EXTRACT(Hour FROM tp.finishtime)*60+EXTRACT(minute FROM tp.finishtime),
           tp.teatime
    from employee e
    left join shifts s on (s.id=e.schedule)
    left join timeperiod tp on (tp.id=s.id)
    where e.employee_id=:emp_id and tp.wday=:wday
    into :beginminute, :finishminute, :teatime;

    if ((beginminute =0) and (finishminute =0)) then begin
       moretime = (outminute-inminute)/60;
    end
    else begin
        worktime = (finishminute-beginminute) /60 - teatime;
        if (inminute>beginminute) then
           delaytime = (inminute-beginminute);

        if (outminute>finishminute) then
            moretime=(outminute-finishminute) /60;

        moretime=moretime-delaytime;
        if (moretime<0) then
          moretime=0 ;
    end
    suspend;
  end
end ^
