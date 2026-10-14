ALTER PROCEDURE CALC_SALARYS (EMPID INTEGER,
Y1 SMALLINT,
M1 SMALLINT,
Y2 SMALLINT,
M2 SMALLINT,
COLST CHAR(3) CHARACTER SET UTF8)
RETURNS (COLID INTEGER,
COLCODE CHAR(4) CHARACTER SET UTF8,
COLNAME CHAR(15) CHARACTER SET UTF8,
COLORDER INTEGER,
COLSTATUS CHAR(3) CHARACTER SET UTF8,
SUMTOTAL NUMERIC(15, 2))
AS 
declare variable WDAY1 smallint;
declare variable WDAY2 smallint;
declare variable WTIME1 smallint;
declare variable WTIME2 smallint;
declare variable MAINSAL numeric(15,2);
declare variable EMPSAL numeric(15,2);
begin
  select sum(m.wday1),sum(m.wtime1),sum(m.wday2),sum(m.wtime2),sum(m.main_salary) from monthsalary m
  where (MYear*12+MMonth>=12*:Y1 + :M1) and
        (MYear*12+MMonth<=12*:Y2 + :M2) and (m.emp_ident=:empid)
  into :wday1,:wtime1,:wday2,:wtime2,:mainsal;
  if (COLST='ADV') then begin
    COLID = 0;
    COLORDER = -3;
    select description from jwhats j where (j.jwhat_id=7)
    into :colname;
    SUMTOTAL = wday1;
    suspend;
    COLID = 0;
    select description from jwhats j where (j.jwhat_id=8)
    into :colname;
    SUMTOTAL = wtime1;
    suspend;
  end
  else if (COLST is null) then  begin
    COLID = 0;
    COLORDER = -2;
    select description from jwhats j where (j.jwhat_id=7)
    into :colname;
    SUMTOTAL = wday2;
    suspend;
    COLID = 0;
    select description from jwhats j where (j.jwhat_id=8)
    into :colname;
    SUMTOTAL = wtime2;
    suspend;
    COLID = 0;
    COLORDER = -1;
    select description from jwhats j where (j.jwhat_id=9)
    into :colname;
    SUMTOTAL = mainsal;
    suspend;
  end
  for select c.col_id,c.colcode,c.colname,c.colorder,c.colstatus,s.sumtotal from colnames c
  left join calc_newempsal(:EMPID,:y1,:m1,:y2,:m2,C.colcode) s on (0=0)
  where (c.colvisible='yes') and (c.colnames_version_id = -1) and (((:COLST is not null) and (c.colstatus=:COLST)) or (:COLST is null))
  order by c.colorder
  into :COLID,:colcode,:colname,:colorder,:colstatus,:SUMTOTAL
  do suspend;
end ^
