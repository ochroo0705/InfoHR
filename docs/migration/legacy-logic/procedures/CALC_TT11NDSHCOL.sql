ALTER PROCEDURE CALC_TT11NDSHCOL (YY SMALLINT,
MM1 SMALLINT,
MM2 SMALLINT,
COLCODE CHAR(4) CHARACTER SET UTF8)
RETURNS (SALSUM NUMERIC(15, 10))
AS 
begin
  if (colcode='B01') then
    select sum(B01) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B02') then
    select sum(B02) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B03') then
    select sum(B03) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B04') then
    select sum(B04) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B05') then
    select sum(B05) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B06') then
    select sum(B06) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B07') then
    select sum(B07) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B08') then
    select sum(B08) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B09') then
    select sum(B09) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B10') then
    select sum(B10) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B11') then
    select sum(B11) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B12') then
    select sum(B12) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B13') then
    select sum(B13) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B14') then
    select sum(B14) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B15') then
    select sum(B15) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B16') then
    select sum(B16) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B17') then
    select sum(B17) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B18') then
    select sum(B18) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B19') then
    select sum(B19) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B20') then
    select sum(B20) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B21') then
    select sum(B21) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B22') then
    select sum(B22) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B23') then
    select sum(B23) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B24') then
    select sum(B24) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B25') then
    select sum(B25) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B26') then
    select sum(B26) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B27') then
    select sum(B27) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B28') then
    select sum(B28) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B29') then
    select sum(B29) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B30') then
    select sum(B30) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B31') then
    select sum(B31) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B32') then
    select sum(B32) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B33') then
    select sum(B33) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B34') then
    select sum(B34) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B35') then
    select sum(B35) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B36') then
    select sum(B36) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B37') then
    select sum(B37) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B38') then
    select sum(B38) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B39') then
    select sum(B39) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B40') then
    select sum(B40) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B41') then
    select sum(B41) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B42') then
    select sum(B42) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B43') then
    select sum(B43) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B44') then
    select sum(B44) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B45') then
    select sum(B45) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B46') then
    select sum(B46) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B47') then
    select sum(B47) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B48') then
    select sum(B48) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B49') then
    select sum(B49) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B50') then
    select sum(B50) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B51') then
    select sum(B51) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B52') then
    select sum(B52) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B53') then
    select sum(B53) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B54') then
    select sum(B54) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B55') then
    select sum(B55) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B56') then
    select sum(B56) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B57') then
    select sum(B57) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B58') then
    select sum(B58) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B59') then
    select sum(B59) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B60') then
    select sum(B60) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B61') then
    select sum(B61) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B62') then
    select sum(B62) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B63') then
    select sum(B63) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B64') then
    select sum(B64) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B65') then
    select sum(B65) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B66') then
    select sum(B66) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B67') then
    select sum(B67) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B68') then
    select sum(B68) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B69') then
    select sum(B69) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B70') then
    select sum(B70) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B71') then
    select sum(B71) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B72') then
    select sum(B72) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B73') then
    select sum(B73) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B74') then
    select sum(B74) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B75') then
    select sum(B75) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B76') then
    select sum(B76) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B77') then
    select sum(B77) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B78') then
    select sum(B78) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B79') then
    select sum(B79) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B80') then
    select sum(B80) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B81') then
    select sum(B81) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B82') then
    select sum(B82) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B83') then
    select sum(B83) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B84') then
    select sum(B84) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B85') then
    select sum(B85) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B86') then
    select sum(B86) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B87') then
    select sum(B87) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B88') then
    select sum(B88) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B89') then
    select sum(B89) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B90') then
    select sum(B90) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B91') then
    select sum(B91) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B92') then
    select sum(B92) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B93') then
    select sum(B93) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B94') then
    select sum(B94) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B95') then
    select sum(B95) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B96') then
    select sum(B96) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B97') then
    select sum(B97) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B98') then
    select sum(B98) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B99') then
    select sum(B99) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (colcode='B100') then
    select sum(B100) from monthsalary
    where (myear=:yy) and (mmonth>=:MM1) and (mmonth<=:MM2)
    into :salsum;
  if (salsum is null) then salsum=0;
  suspend;
end ^
