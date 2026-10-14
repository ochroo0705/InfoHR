ALTER PROCEDURE CALC_NDSH8_V2 (CUST_ID INTEGER,
YY SMALLINT,
MM1 SMALLINT)
RETURNS (INSUR_IDENT INTEGER,
SUM1 NUMERIC(15, 2),
SUM2 NUMERIC(15, 2),
SUM3 NUMERIC(15, 2),
SUM4 NUMERIC(15, 2),
ZSUM1 NUMERIC(15, 2),
ZSUM2 NUMERIC(15, 2),
ZSUM3 NUMERIC(15, 2),
ZSUM4 NUMERIC(15, 2),
ZSUM5 NUMERIC(15, 2))
AS 
declare variable COLCODE char(4);
declare variable STMT varchar(5000);
declare variable COLCODES varchar(100);
declare variable TMPSUM numeric(15,2);
begin
  select colcode from colnames
  where (colstatus='SAL')
  into :colcode;
  execute statement 'select sum('||:colcode||') from monthsalary where emp_ident = '||cust_id||' and myear = '||YY||' and mmonth ='||mm1
  into :sum4;
  select insur_ident from monthsalary where (emp_ident=:cust_id) and (myear=:yy) and (mmonth=:MM1)
  rows 1
  into :insur_ident;

  if (SUM4 is null) then SUM4=0;
  select main_salary from monthsalary
  where (emp_ident=:cust_id) and (myear=:yy) and (mmonth=:mm1)  and (status=2)
  into :tmpsum;

  if (tmpsum is null) then tmpsum=0;
  sum4=sum4+:tmpsum;

  SUM1=0;
  colcodes='';
  for select colcode from colnames
  /*where (colstatus in ('IOH','IOP','IOS','IOU','IOE'))  and (colnames_version_id = -1)*/
  where (colstatus in ('SOC'))  and (colnames_version_id = -1)
  into :colcode
  do begin
    execute statement 'select sum('||:colcode||') from monthsalary where emp_ident = '||cust_id||' and myear = '||YY||' and mmonth ='||mm1
    into :tmpsum;
    if (tmpsum is null) then tmpsum=0;
    SUM1=SUM1+:tmpsum;
  end

  SUM2=0;
  colcodes='';
  for select colcode from colnames
  /*where (colstatus in ('IEH','IEP','IES','IEU')) and (colnames_version_id = -1)*/
  where (colstatus in ('SEC')) and (colnames_version_id = -1)
  into :colcode
  do begin
    execute statement 'select sum('||:colcode||') from monthsalary where emp_ident = '||cust_id||' and myear = '||YY||' and mmonth ='||mm1
    into :tmpsum;
    if (tmpsum is null) then tmpsum=0;
    SUM2=SUM2+:tmpsum;
  end

  SUM3=SUM1+SUM2;

  colcode=null;
  select List(colcode,'+') from colnames
  where (ndsh_type=4) and (colnames_version_id = -1)
  into :colcodes;
  if (colcodes is not null) then
  execute statement 'select sum('||:colcodes||') from monthsalary where emp_ident = '||cust_id||' and myear = '||YY||' and mmonth ='||mm1
  into :ZSUM1;
  if (ZSUM1 is null) then ZSUM1=0;

  colcode=null;
  select List(colcode,'+') from colnames
  where (ndsh_type=5) and (colnames_version_id = -1)
  into :colcodes;
  if (colcodes is not null) then
  execute statement 'select sum('||:colcodes||') from monthsalary where emp_ident = '||cust_id||' and myear = '||YY||' and mmonth ='||mm1
  into :ZSUM2;
  if (ZSUM2 is null) then ZSUM2=0;

  ZSUM3=0;
  colcode=null;
  for select colcode from colnames
  where (ndsh_type=6) and (colnames_version_id = -1)
  into :colcode
  do begin
    execute statement 'select sum('||:colcode||') from monthsalary where emp_ident = '||cust_id||' and myear = '||YY||' and mmonth ='||mm1
    into :tmpsum;
    if (tmpsum is null) then tmpsum=0;
    ZSUM3=ZSUM3+:tmpsum;
  end
  if (ZSUM3 is null) then ZSUM3=0;

  colcode=null;
  select List(colcode,'+') from colnames
  where (ndsh_type=7) and (colnames_version_id = -1)
  into :colcodes;
  if (colcodes is not null) then
  execute statement 'select sum('||:colcodes||') from monthsalary where emp_ident = '||cust_id||' and myear = '||YY||' and mmonth ='||mm1
  into :ZSUM4;
  if (ZSUM4 is null) then ZSUM4=0;

  ZSUM5=sum4-(ZSum1+ZSum2+ZSum3+ZSum4);
  suspend;
end ^
