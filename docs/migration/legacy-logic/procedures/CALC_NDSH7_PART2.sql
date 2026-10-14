ALTER PROCEDURE CALC_NDSH7_PART2 (DATE1 TIMESTAMP,
DATE2 TIMESTAMP,
YY INTEGER,
MM1 INTEGER,
MM2 INTEGER,
EXPR VARCHAR(100) CHARACTER SET UTF8,
COLNUM INTEGER)
RETURNS (AMOUNT NUMERIC(15, 2))
AS 
declare variable STMT varchar(5000);
declare variable TEMPSUM numeric(15,2);
begin
  amount  = 0;
  tempsum = null;
  stmt='select sum('||:expr||') from monthsalary m '||
       'left join insur_type t on (t.insur_id=m.insur_ident) '||
       'where (m.insur_ident>0) and (t.colnum='||:colnum ||') and (m.myear='||cast(:yy as varchar(4))||') '||
       'and (m.mmonth>='||cast(:MM1 as varchar(2))||') and (m.mmonth<='||cast(:MM2 as varchar(2))||') and (m.status is null)';
  execute statement :stmt
  into :tempsum;
  if (tempsum is null) then tempsum=0;

  amount=amount+tempsum;
  tempsum = null;

  select sum(m.main_salary) from monthsalary m
  left join insur_type t on (t.insur_id=m.insur_ident)
  where (m.insur_ident>0) and (t.colnum=:colnum) and (m.myear=:yy) and (m.mmonth>=:MM1) and (m.mmonth<=:MM2) and (m.status=2)
  into :tempsum;
  if (tempsum is null) then tempsum=0;
  amount=amount+tempsum;
  suspend;
end ^
