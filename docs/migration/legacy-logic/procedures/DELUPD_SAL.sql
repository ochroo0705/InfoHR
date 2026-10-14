ALTER PROCEDURE DELUPD_SAL (YY SMALLINT,
MM SMALLINT,
DEPID INTEGER,
COLCODE CHAR(4) CHARACTER SET UTF8)
AS 
begin
  if (COLCODE='B01') then
    update monthsalary set
      B01=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B02') then
    update monthsalary set
      B02=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B03') then
    update monthsalary set
      B03=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B04') then
    update monthsalary set
      B04=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B05') then
    update monthsalary set
      B05=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B06') then
    update monthsalary set
      B06=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B07') then
    update monthsalary set
      B07=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B08') then
    update monthsalary set
      B08=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B09') then
    update monthsalary set
      B09=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B10') then
    update monthsalary set
      B10=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B11') then
    update monthsalary set
      B11=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B12') then
    update monthsalary set
      B12=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B13') then
    update monthsalary set
      B13=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B14') then
    update monthsalary set
      B14=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B15') then
    update monthsalary set
      B15=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B16') then
    update monthsalary set
      B16=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B17') then
    update monthsalary set
      B17=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B18') then
    update monthsalary set
      B18=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B19') then
    update monthsalary set
      B19=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B20') then
    update monthsalary set
      B20=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B21') then
    update monthsalary set
      B21=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B22') then
    update monthsalary set
      B22=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B23') then
    update monthsalary set
      B23=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B24') then
    update monthsalary set
      B24=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B25') then
    update monthsalary set
      B25=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B26') then
    update monthsalary set
      B26=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B27') then
    update monthsalary set
      B27=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B28') then
    update monthsalary set
      B28=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B29') then
    update monthsalary set
      B29=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B30') then
    update monthsalary set
      B30=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B31') then
    update monthsalary set
      B31=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B32') then
    update monthsalary set
      B32=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B33') then
    update monthsalary set
      B33=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B34') then
    update monthsalary set
      B34=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B35') then
    update monthsalary set
      B35=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B36') then
    update monthsalary set
      B36=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B37') then
    update monthsalary set
      B37=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B38') then
    update monthsalary set
      B38=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B39') then
    update monthsalary set
      B39=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B40') then
    update monthsalary set
      B40=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B41') then
    update monthsalary set
      B41=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B42') then
    update monthsalary set
      B42=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B43') then
    update monthsalary set
      B43=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B44') then
    update monthsalary set
      B44=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B45') then
    update monthsalary set
      B45=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B46') then
    update monthsalary set
      B46=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B47') then
    update monthsalary set
      B47=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B48') then
    update monthsalary set
      B48=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B49') then
    update monthsalary set
      B49=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B50') then
    update monthsalary set
      B50=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B51') then
    update monthsalary set
      B51=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B52') then
    update monthsalary set
      B52=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B53') then
    update monthsalary set
      B53=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B54') then
    update monthsalary set
      B54=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B55') then
    update monthsalary set
      B55=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B56') then
    update monthsalary set
      B56=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B57') then
    update monthsalary set
      B57=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B58') then
    update monthsalary set
      B58=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B59') then
    update monthsalary set
      B59=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else if (COLCODE='B60') then
    update monthsalary set
      B60=0
    where (MYear=:yy) and (MMonth=:mm) and (Dep_ident=:depid);
  else
    execute procedure DELUPD_SAL_TMP(:yy,:mm,:depid,:colcode);
end ^
