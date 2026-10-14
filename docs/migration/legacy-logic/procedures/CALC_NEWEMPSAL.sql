ALTER PROCEDURE CALC_NEWEMPSAL (EMPID INTEGER,
Y1 SMALLINT,
M1 SMALLINT,
Y2 SMALLINT,
M2 SMALLINT,
COLCODE CHAR(3) CHARACTER SET UTF8)
RETURNS (SUMTOTAL NUMERIC(15, 2))
AS 
begin
  if (COLCODE='B01') then
    select SUM(B01) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B02') then
    select SUM(B02) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B03') then
    select SUM(B03) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B04') then
    select SUM(B04) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B05') then
    select SUM(B05) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B06') then
    select SUM(B06) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B07') then
    select SUM(B07) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B08') then
    select SUM(B08) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B09') then
    select SUM(B09) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B10') then
    select SUM(B10) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B11') then
    select SUM(B11) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B12') then
    select SUM(B12) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B13') then
    select SUM(B13) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B14') then
    select SUM(B14) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B15') then
    select SUM(B15) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B16') then
    select SUM(B16) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B17') then
    select SUM(B17) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B18') then
    select SUM(B18) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B19') then
    select SUM(B19) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B20') then
    select SUM(B20) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B21') then
    select SUM(B21) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B22') then
    select SUM(B22) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B23') then
    select SUM(B23) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B24') then
    select SUM(B24) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B25') then
    select SUM(B25) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B26') then
    select SUM(B26) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B27') then
    select SUM(B27) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B28') then
    select SUM(B28) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B29') then
    select SUM(B29) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B30') then
    select SUM(B30) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B31') then
    select SUM(B31) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B32') then
    select SUM(B32) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B33') then
    select SUM(B33) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B34') then
    select SUM(B34) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B35') then
    select SUM(B35) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B36') then
    select SUM(B36) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B37') then
    select SUM(B37) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B38') then
    select SUM(B38) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B39') then
    select SUM(B39) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B40') then
    select SUM(B40) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B41') then
    select SUM(B41) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B42') then
    select SUM(B42) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B43') then
    select SUM(B43) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B44') then
    select SUM(B44) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B45') then
    select SUM(B45) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B46') then
    select SUM(B46) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B47') then
    select SUM(B47) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B48') then
    select SUM(B48) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B49') then
    select SUM(B49) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B50') then
    select SUM(B50) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B51') then
    select SUM(B51) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B52') then
    select SUM(B52) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B53') then
    select SUM(B53) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B54') then
    select SUM(B54) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B55') then
    select SUM(B55) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B56') then
    select SUM(B56) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B57') then
    select SUM(B57) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B58') then
    select SUM(B58) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B59') then
    select SUM(B59) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B60') then
    select SUM(B60) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B61') then
    select SUM(B61) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B62') then
    select SUM(B62) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B63') then
    select SUM(B63) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B64') then
    select SUM(B64) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B65') then
    select SUM(B65) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B66') then
    select SUM(B66) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B67') then
    select SUM(B67) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B68') then
    select SUM(B68) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B69') then
    select SUM(B69) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B70') then
    select SUM(B70) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B71') then
    select SUM(B71) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B72') then
    select SUM(B72) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B73') then
    select SUM(B73) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B74') then
    select SUM(B74) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B75') then
    select SUM(B75) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B76') then
    select SUM(B76) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B77') then
    select SUM(B77) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B78') then
    select SUM(B78) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B79') then
    select SUM(B79) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B80') then
    select SUM(B80) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B81') then
    select SUM(B81) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B82') then
    select SUM(B82) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B83') then
    select SUM(B83) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B84') then
    select SUM(B84) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B85') then
    select SUM(B85) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B86') then
    select SUM(B86) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B87') then
    select SUM(B87) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B88') then
    select SUM(B88) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B89') then
    select SUM(B89) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B90') then
    select SUM(B90) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B91') then
    select SUM(B91) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B92') then
    select SUM(B92) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B93') then
    select SUM(B93) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B94') then
    select SUM(B94) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B95') then
    select SUM(B95) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B96') then
    select SUM(B96) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B97') then
    select SUM(B97) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B98') then
    select SUM(B98) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B99') then
    select SUM(B99) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (COLCODE='B100') then
    select SUM(B100) from monthsalary
    where (MYear*12+MMonth>=12*:Y1 + :M1) and
    (MYear*12+MMonth<=12*:Y2 + :M2) and (emp_ident=:empid)
    into :SUMTOTAL;
  if (SumTotal is null) then SumTotal=0;
  suspend;
end ^
