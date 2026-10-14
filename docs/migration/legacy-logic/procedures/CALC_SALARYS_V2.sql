ALTER PROCEDURE CALC_SALARYS_V2 (EMPID INTEGER,
COLTYP VARCHAR(10) CHARACTER SET UTF8,
COLSTAT VARCHAR(10) CHARACTER SET UTF8,
Y1 SMALLINT,
M1 SMALLINT)
RETURNS (COLID INTEGER,
COLCODE VARCHAR(20) CHARACTER SET UTF8,
COLNAME CHAR(50) CHARACTER SET UTF8,
COLORDER INTEGER,
COLSTATUS CHAR(3) CHARACTER SET UTF8,
ISBOLD SMALLINT,
ISINT VARCHAR(3) CHARACTER SET UTF8,
SUMTOTAL NUMERIC(15, 2))
AS 
declare variable WDAY1 smallint;
declare variable WDAY2 smallint;
declare variable WTIME1 smallint;
declare variable WTIME2 smallint;
declare variable MDAY1 smallint;
declare variable MDAY2 smallint;
declare variable MTIME1 smallint;
declare variable MTIME2 smallint;

declare variable MAINSAL numeric(15,2);
declare variable EMPSAL numeric(15,2);
declare variable coldep_ident integer;
declare variable dep_ident integer;
declare variable cc integer;
begin
  select sum(m.wday1),sum(m.wtime1),sum(m.wday2),sum(m.wtime2),sum(m.main_salary),max(dep_ident) from monthsalary m
  where (MYear = :Y1) and
        (MMONTH = :M1) and (m.emp_ident=:empid)
  into :wday1,:wtime1,:wday2,:wtime2,:mainsal,:dep_ident;


  cc = 0;
  select count(*) from salary_email_columns s
  where s.dep_ident = :dep_ident
  into :cc;

  if (cc = 0) then
    coldep_ident = -1;
  else
    coldep_ident = :dep_ident;


  select m.wdays1,m.wtime1,m.wdays,m.wtime from month_days m where m.myear = :y1 and m.mmonth= :m1 and m.dep_ident = :dep_ident
  into :mday1,:mtime1,mday2,mtime2;
  if ((mday2 is null) and (:mtime2 is null)) then
    select m.wdays1,m.wtime1,m.wdays,m.wtime from month_days m where m.myear = :y1 and m.mmonth= :m1 and m.dep_ident = 0
    into :mday1,:mtime1,mday2,mtime2;


  for select s.col_ident,s.colcode, s.colname_new,s.colorder,c.colstatus,s.isbold,s.isint from salary_email_columns s
  left join colnames c on (s.col_ident =c.col_id) and (c.colnames_version_id = -1)
  where s.dep_ident = :coldep_ident and
  (((:coltyp='advance' and s.coltype='advance')) or
  ((:coltyp='salary') and (s.coltype='salary' or (s.coltype='advance' and c.checked='''yes''')))) and
  (((:colstat is not null) and (c.colstatus=:colstat)) or (:colstat is null and s.issend = 1))

  into :colid, :colcode, :colname,:colorder,:colstatus,:isbold,:isint
  do begin
    if (colcode = 'm_time1') then begin
      sumtotal = :mtime1;
    end
    else if (colcode = 'm_time2') then begin
      sumtotal = mtime2;
    end
    else if (colcode = 'm_day1') then begin
      sumtotal = mday1;
    end
    else if (colcode = 'm_day2') then begin
      sumtotal = mday2;
    end
    else if (colcode = 'wday1') then begin
      sumtotal = wday1;
    end
    else if (colcode = 'wtime1') then begin
      sumtotal = wtime1;
    end

    else if (colcode = 'wday2') then begin
      sumtotal = wday2;
    end
    else if (colcode = 'wtime2') then begin
      sumtotal = wtime2;
    end
    else begin
      select sumtotal from calc_newempsal(:empid,:y1,:m1,:y1,:m1,:colcode)
      into :sumtotal;
    end
    suspend;

  end
end ^
