ALTER PROCEDURE CALC_UE RETURNS (EMPQTY INTEGER,
FIRSTEMPQTY INTEGER,
LASTEMPQTY INTEGER,
FEMALEEMP INTEGER,
YOUNGEMPQTY INTEGER,
ENTEREMPQTY INTEGER,
EXITEMPQTY INTEGER,
VOTEEMPQTY INTEGER,
VOTEFEMALEEMPQTY INTEGER,
DELETEEMPQTY INTEGER)
AS 
declare variable SYSDATE date;
declare variable SYSYEAR integer;
declare variable FIRSTDATE date;
declare variable YOUNGDATE date;
begin
  sysdate = current_timestamp;
  
  sysyear=EXTRACT(year FROM :sysdate);
  
  select dat from CONVTODATE(:sysyear,1,1,3)
  into :firstdate;

  sysyear=sysyear-35;

  select dat from CONVTODATE(:sysyear,1,1,3)
  into :youngdate;
  select count(*)
  from employee
  where status='active'
  into :empqty;

  select count(*)
  from employee
  where (status='active') and (g_enddate>=:firstdate)
  into :firstempqty;

  select count(*)
  from employee
  where (status='active') and (g_enddate>=:sysdate)
  into :lastempqty;

  select count(*)
  from employee
  where (status='active') and (g_enddate>=:sysdate) and (gender='F')
  into :femaleemp;

  select count(*)
  from employee
  where (status='active') and (g_enddate>=:sysdate) and (birthday>=:youngdate)
  into :youngempqty;

  select count(*)
  from employee
  where status='active' and (G_date>=:firstdate) and (G_DATE<=:sysdate)
  into :enterempqty;

  select count(*)
  from employee
  where status='active' and (G_ENDDATE>=:firstdate) and (G_ENDDATE<=:sysdate)
  into :exitempqty;

  if (exitempqty > enterempqty) then
    DELETEEMPQTY=exitempqty-enterempqty;
  else
    DELETEEMPQTY=0;

  select count(*)
  from employee
  where status='active' and (voting_work_ident is not null)
  into :VOTEEMPqTY;

  select count(*)
  from employee
  where status='active' and (voting_work_ident is not null) and (gender = 'F')
  into :votefemaleempqty;
  
  SUSPEND;
end ^
