ALTER PROCEDURE CALC_TAX (STAT CHAR(3) CHARACTER SET UTF8,
EMPID INTEGER,
YY SMALLINT,
MM SMALLINT)
RETURNS (SUM1 NUMERIC(15, 2))
AS 
declare variable CCODE char(4);
begin
  select colcode from colnames
  where (colstatus=:stat) and (COLNAMES_VERSION_ID = -1)
  into :CCODE;
  if (CCODE='B01') then begin
    select sum(B01) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B02') then begin
    select sum(B02) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B03') then begin
    select sum(B03) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B04') then begin
    select sum(B04) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B05') then begin
    select sum(B05) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B06') then begin
    select sum(B06) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B07') then begin
    select sum(B07) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B08') then begin
    select sum(B08) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B09') then begin
    select sum(B09) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B10') then begin
    select sum(B10) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B11') then begin
    select sum(B11) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B12') then begin
    select sum(B12) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B13') then begin
    select sum(B13) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B14') then begin
    select sum(B14) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B15') then begin
    select sum(B15) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B16') then begin
    select sum(B16) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B17') then begin
    select sum(B17) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B18') then begin
    select sum(B18) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B19') then begin
    select sum(B19) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B20') then begin
    select sum(B20) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B21') then begin
    select sum(B21) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B22') then begin
    select sum(B22) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B23') then begin
    select sum(B23) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B24') then begin
    select sum(B24) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B25') then begin
    select sum(B25) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B26') then begin
    select sum(B26) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B27') then begin
    select sum(B27) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B28') then begin
    select sum(B28) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B29') then begin
    select sum(B29) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B30') then begin
    select sum(B30) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B31') then begin
    select sum(B31) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B32') then begin
    select sum(B32) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B33') then begin
    select sum(B33) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B34') then begin
    select sum(B34) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B35') then begin
    select sum(B35) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B36') then begin
    select sum(B36) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B37') then begin
    select sum(B37) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B38') then begin
    select sum(B38) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B39') then begin
    select sum(B39) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B40') then begin
    select sum(B40) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B41') then begin
    select sum(B41) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B42') then begin
    select sum(B42) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B43') then begin
    select sum(B43) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B44') then begin
    select sum(B44) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B45') then begin
    select sum(B45) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B46') then begin
    select sum(B46) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B47') then begin
    select sum(B47) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B48') then begin
    select sum(B48) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B49') then begin
    select sum(B49) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B50') then begin
    select sum(B50) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B51') then begin
    select sum(B51) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B52') then begin
    select sum(B52) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B53') then begin
    select sum(B53) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B54') then begin
    select sum(B54) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B55') then begin
    select sum(B55) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B56') then begin
    select sum(B56) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B57') then begin
    select sum(B57) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B58') then begin
    select sum(B58) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B59') then begin
    select sum(B59) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B60') then begin
    select sum(B60) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B61') then begin
    select sum(B61) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B62') then begin
    select sum(B62) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B63') then begin
    select sum(B63) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B64') then begin
    select sum(B64) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B65') then begin
    select sum(B65) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B66') then begin
    select sum(B66) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B67') then begin
    select sum(B67) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B68') then begin
    select sum(B68) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B69') then begin
    select sum(B69) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B70') then begin
    select sum(B70) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B71') then begin
    select sum(B71) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B72') then begin
    select sum(B72) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B73') then begin
    select sum(B73) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B74') then begin
    select sum(B74) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B75') then begin
    select sum(B75) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B76') then begin
    select sum(B76) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B77') then begin
    select sum(B77) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B78') then begin
    select sum(B78) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B79') then begin
    select sum(B79) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B80') then begin
    select sum(B80) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B81') then begin
    select sum(B81) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B82') then begin
    select sum(B82) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B83') then begin
    select sum(B83) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B84') then begin
    select sum(B84) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B85') then begin
    select sum(B85) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B86') then begin
    select sum(B86) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B87') then begin
    select sum(B87) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B88') then begin
    select sum(B88) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B89') then begin
    select sum(B89) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B90') then begin
    select sum(B90) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B91') then begin
    select sum(B91) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B92') then begin
    select sum(B92) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B93') then begin
    select sum(B93) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B94') then begin
    select sum(B94) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B95') then begin
    select sum(B95) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B96') then begin
    select sum(B96) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B97') then begin
    select sum(B97) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B98') then begin
    select sum(B98) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B99') then begin
    select sum(B99) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  else if (CCODE='B100') then begin
    select sum(B100) from monthsalary
    where (emp_ident=:EMPID) and (myear=:YY) and (mmonth=:MM)
    into :SUM1;
  end
  if (sum1 is null) then
    sum1=0;
  suspend;
end ^
