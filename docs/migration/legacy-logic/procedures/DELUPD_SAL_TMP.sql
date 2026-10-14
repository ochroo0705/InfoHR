ALTER PROCEDURE DELUPD_SAL_TMP (YY SMALLINT,
MM SMALLINT,
DEPID INTEGER,
COLCODE CHAR(4) CHARACTER SET UTF8)
AS 
begin
  if (COLCODE='B61') then
    update monthsalary set
      B61=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B62') then
    update monthsalary set
      B62=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B63') then
    update monthsalary set
      B63=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B64') then
    update monthsalary set
      B64=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B65') then
    update monthsalary set
      B65=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B66') then
    update monthsalary set
      B66=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B67') then
    update monthsalary set
      B67=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B68') then
    update monthsalary set
      B68=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B69') then
    update monthsalary set
      B69=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B70') then
    update monthsalary set
      B70=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B71') then
    update monthsalary set
      B71=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B72') then
    update monthsalary set
      B72=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B73') then
    update monthsalary set
      B73=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B74') then
    update monthsalary set
      B74=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B75') then
    update monthsalary set
      B75=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B76') then
    update monthsalary set
      B76=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B77') then
    update monthsalary set
      B77=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B78') then
    update monthsalary set
      B78=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B79') then
    update monthsalary set
      B79=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B80') then
    update monthsalary set
      B80=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B81') then
    update monthsalary set
      B81=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B82') then
    update monthsalary set
      B82=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B83') then
    update monthsalary set
      B83=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B84') then
    update monthsalary set
      B84=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B85') then
    update monthsalary set
      B85=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B86') then
    update monthsalary set
      B86=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B87') then
    update monthsalary set
      B87=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B88') then
    update monthsalary set
      B88=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B89') then
    update monthsalary set
      B89=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B90') then
    update monthsalary set
      B90=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B91') then
    update monthsalary set
      B91=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B92') then
    update monthsalary set
      B92=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B93') then
    update monthsalary set
      B93=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B94') then
    update monthsalary set
      B94=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B95') then
    update monthsalary set
      B95=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B96') then
    update monthsalary set
      B96=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B97') then
    update monthsalary set
      B97=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B98') then
    update monthsalary set
      B98=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B99') then
    update monthsalary set
      B99=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B100') then
    update monthsalary set
      B100=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
end ^
