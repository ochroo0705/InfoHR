ALTER PROCEDURE DELETE_SAL (YY SMALLINT,
MM SMALLINT,
DEPID INTEGER,
ADV CHAR(7) CHARACTER SET UTF8)
AS 
declare variable COLCODE char(4);
begin
  for select colcode from colnames
  where (Trim(coltype)=Trim(:adv)) and (colnames_version_id = -1)
  order by colorder
  into :colcode
  do begin
    execute procedure delupd_sal(:yy,:mm,:depid,:colcode);
  end
  if (Trim(adv)='salary') then begin
    update monthsalary set
      main_salary=0,
      wskill_salary=0,
      works_salary=0,
      sal_date=null
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  end
  /*else begin
    update monthsalary set
      main_salary=0,
      wskill_salary=0,
      works_salary=0,
      sal_date=null
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  end*/
end ^
