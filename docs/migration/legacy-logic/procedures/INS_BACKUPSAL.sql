ALTER PROCEDURE INS_BACKUPSAL (YY INTEGER,
MM INTEGER,
DEPID INTEGER)
AS 
declare variable CC integer;
declare variable EMP_IDENT integer;
declare variable DEP_IDENT integer;
declare variable MYEAR smallint;
declare variable MMONTH smallint;
declare variable WDAY1 smallint;
declare variable WTIME1 smallint;
declare variable WDAY2 smallint;
declare variable WTIME2 smallint;
declare variable MAIN_SALARY numeric(15,2);
declare variable WSKILL_SALARY numeric(15,2);
declare variable WORKS_SALARY numeric(15,2);
declare variable B01 numeric(15,2);
declare variable B02 numeric(15,2);
declare variable B03 numeric(15,2);
declare variable B04 numeric(15,2);
declare variable B05 numeric(15,2);
declare variable B06 numeric(15,2);
declare variable B07 numeric(15,2);
declare variable B08 numeric(15,2);
declare variable B09 numeric(15,2);
declare variable B10 numeric(15,2);
declare variable B11 numeric(15,2);
declare variable B12 numeric(15,2);
declare variable B13 numeric(15,2);
declare variable B14 numeric(15,2);
declare variable B15 numeric(15,2);
declare variable B16 numeric(15,2);
declare variable B17 numeric(15,2);
declare variable B18 numeric(15,2);
declare variable B19 numeric(15,2);
declare variable B20 numeric(15,2);
declare variable B21 numeric(15,2);
declare variable B22 numeric(15,2);
declare variable B23 numeric(15,2);
declare variable B24 numeric(15,2);
declare variable B25 numeric(15,2);
declare variable B26 numeric(15,2);
declare variable B27 numeric(15,2);
declare variable B28 numeric(15,2);
declare variable B29 numeric(15,2);
declare variable B30 numeric(15,2);
declare variable B31 numeric(15,2);
declare variable B32 numeric(15,2);
declare variable B33 numeric(15,2);
declare variable B34 numeric(15,2);
declare variable B35 numeric(15,2);
declare variable B36 numeric(15,2);
declare variable B37 numeric(15,2);
declare variable B38 numeric(15,2);
declare variable B39 numeric(15,2);
declare variable B40 numeric(15,2);
declare variable B41 numeric(15,2);
declare variable B42 numeric(15,2);
declare variable B43 numeric(15,2);
declare variable B44 numeric(15,2);
declare variable B45 numeric(15,2);
declare variable B46 numeric(15,2);
declare variable B47 numeric(15,2);
declare variable B48 numeric(15,2);
declare variable B49 numeric(15,2);
declare variable B50 numeric(15,2);
declare variable B51 numeric(15,2);
declare variable B52 numeric(15,2);
declare variable B53 numeric(15,2);
declare variable B54 numeric(15,2);
declare variable B55 numeric(15,2);
declare variable B56 numeric(15,2);
declare variable B57 numeric(15,2);
declare variable B58 numeric(15,2);
declare variable B59 numeric(15,2);
declare variable B60 numeric(15,2);
declare variable B61 numeric(15,2);
declare variable B62 numeric(15,2);
declare variable B63 numeric(15,2);
declare variable B64 numeric(15,2);
declare variable B65 numeric(15,2);
declare variable B66 numeric(15,2);
declare variable B67 numeric(15,2);
declare variable B68 numeric(15,2);
declare variable B69 numeric(15,2);
declare variable B70 numeric(15,2);
declare variable B71 numeric(15,2);
declare variable B72 numeric(15,2);
declare variable B73 numeric(15,2);
declare variable B74 numeric(15,2);
declare variable B75 numeric(15,2);
declare variable B76 numeric(15,2);
declare variable B77 numeric(15,2);
declare variable B78 numeric(15,2);
declare variable B79 numeric(15,2);
declare variable B80 numeric(15,2);
declare variable B81 numeric(15,2);
declare variable B82 numeric(15,2);
declare variable B83 numeric(15,2);
declare variable B84 numeric(15,2);
declare variable B85 numeric(15,2);
declare variable B86 numeric(15,2);
declare variable B87 numeric(15,2);
declare variable B88 numeric(15,2);
declare variable B89 numeric(15,2);
declare variable B90 numeric(15,2);
declare variable B91 numeric(15,2);
declare variable B92 numeric(15,2);
declare variable B93 numeric(15,2);
declare variable B94 numeric(15,2);
declare variable B95 numeric(15,2);
declare variable B96 numeric(15,2);
declare variable B97 numeric(15,2);
declare variable B98 numeric(15,2);
declare variable B99 numeric(15,2);
declare variable B100 numeric(15,2);
declare variable ADV_DATE date;
declare variable SAL_DATE date;
begin
  for select EMP_IDENT,DEP_IDENT,MYEAR,MMONTH,WDAY1,WTIME1,WDAY2,WTIME2,
             MAIN_SALARY,WSKILL_SALARY,WORKS_SALARY,B01,B02,B03,B04,B05,B06,B07,
             B08,B09,B10,B11,B12,B13,B14,B15,B16,B17,B18,B19,B20,B21,B22,B23,B24,
             B25,B26,B27,B28,B29,B30,B31,B32,B33,B34,B35,B36,B37,B38,B39,B40,B41,
             B42,B43,B44,B45,B46,B47,B48,B49,
             B50,B51,B52,B53,B54,B55,B56,B57,B58,B59,
             B60,B61,B62,B63,B64,B65,B66,B67,B68,B69,
             B70,B71,B72,B73,B74,B75,B76,B77,B78,B79,
             B80,B81,B82,B83,B84,B85,B86,B87,B88,B89,
             B90,B91,B92,B93,B94,B95,B96,B97,B98,B99,
             B100,ADV_DATE,SAL_DATE from monthsalary
  where (Myear=:YY) and (MMonth=:MM) and (((Dep_Ident=:depid) and (:depid is not null)) or (:depid is null))
  order by emp_ident
  into :EMP_IDENT,:DEP_IDENT,:MYEAR,:MMONTH,:WDAY1,:WTIME1,:WDAY2,:WTIME2,
       :MAIN_SALARY,:WSKILL_SALARY,:WORKS_SALARY,:B01,:B02,:B03,:B04,:B05,:B06,:B07,
       :B08,:B09,:B10,:B11,:B12,:B13,:B14,:B15,:B16,:B17,:B18,:B19,:B20,:B21,:B22,:B23,:B24,
       :B25,:B26,:B27,:B28,:B29,:B30,:B31,:B32,:B33,:B34,:B35,:B36,:B37,:B38,:B39,:B40,:B41,
       :B42,:B43,:B44,:B45,:B46,:B47,:B48,:B49,
       :B50,:B51,:B52,:B53,:B54,:B55,:B56,:B57,:B58,:B59,
       :B60,:B61,:B62,:B63,:B64,:B65,:B66,:B67,:B68,:B69,
       :B70,:B71,:B72,:B73,:B74,:B75,:B76,:B77,:B78,:B79,
       :B80,:B81,:B82,:B83,:B84,:B85,:B86,:B87,:B88,:B89,
       :B90,:B91,:B92,:B93,:B94,:B95,:B96,:B97,:B98,:B99,
       :B100,:ADV_DATE,:SAL_DATE
  do begin
    select emp_ident from monthsalary_new
    where (myear=:yy) and (mmonth=:mm) and (emp_ident=:emp_ident) and (dep_ident=:dep_ident)
    rows 1
    into :CC;
    if (cc is  null) then
      cc=0;
    if (:CC=0) then
      insert into monthsalary_new(EMP_IDENT,DEP_IDENT,MYEAR,MMONTH,WDAY1,WTIME1,WDAY2,WTIME2,
                                  MAIN_SALARY,WSKILL_SALARY,WORKS_SALARY,B01,B02,B03,B04,B05,B06,B07,
                                  B08,B09,B10,B11,B12,B13,B14,B15,B16,B17,B18,B19,B20,B21,B22,B23,B24,
                                  B25,B26,B27,B28,B29,B30,B31,B32,B33,B34,B35,B36,B37,B38,B39,B40,B41,
                                  B42,B43,B44,B45,B46,B47,B48,B49,
                                  B50,B51,B52,B53,B54,B55,B56,B57,B58,B59,
                                  B60,B61,B62,B63,B64,B65,B66,B67,B68,B69,
                                  B70,B71,B72,B73,B74,B75,B76,B77,B78,B79,
                                  B80,B81,B82,B83,B84,B85,B86,B87,B88,B89,
                                  B90,B91,B92,B93,B94,B95,B96,B97,B98,B99,
                                  B100,ADV_DATE,SAL_DATE)
      values (:EMP_IDENT,:DEP_IDENT,:MYEAR,:MMONTH,:WDAY1,:WTIME1,:WDAY2,:WTIME2,
              :MAIN_SALARY,:WSKILL_SALARY,:WORKS_SALARY,:B01,:B02,:B03,:B04,:B05,:B06,:B07,
              :B08,:B09,:B10,:B11,:B12,:B13,:B14,:B15,:B16,:B17,:B18,:B19,:B20,:B21,:B22,:B23,:B24,
              :B25,:B26,:B27,:B28,:B29,:B30,:B31,:B32,:B33,:B34,:B35,:B36,:B37,:B38,:B39,:B40,:B41,
              :B42,:B43,:B44,:B45,:B46,:B47,:B48,:B49,
              :B50,:B51,:B52,:B53,:B54,:B55,:B56,:B57,:B58,:B59,
              :B60,:B61,:B62,:B63,:B64,:B65,:B66,:B67,:B68,:B69,
              :B70,:B71,:B72,:B73,:B74,:B75,:B76,:B77,:B78,:B79,
              :B80,:B81,:B82,:B83,:B84,:B85,:B86,:B87,:B88,:B89,
              :B90,:B91,:B92,:B93,:B94,:B95,:B96,:B97,:B98,:B99,
              :B100,:ADV_DATE,:SAL_DATE);
    else
      update monthsalary_new set
      WDAY1  =:WDAY1,
      WTIME1  =:WTIME1,
      WDAY2  =:WDAY2,
      WTIME2  =:WTIME2,
      MAIN_SALARY  =:MAIN_SALARY,
      WSKILL_SALARY  =:WSKILL_SALARY,
      WORKS_SALARY  =:WORKS_SALARY,
      B01  =:B01,
      B02  =:B02,
      B03  =:B03,
      B04  =:B04,
      B05  =:B05,
      B06  =:B06,
      B07  =:B07,
      B08  =:B08,
      B09  =:B09,
      B10  =:B10,
      B11  =:B11,
      B12  =:B12,
      B13  =:B13,
      B14  =:B14,
      B15  =:B15,
      B16  =:B16,
      B17  =:B17,
      B18  =:B18,
      B19  =:B19,
      B20  =:B20,
      B21  =:B21,
      B22  =:B22,
      B23  =:B23,
      B24  =:B24,
      B25  =:B25,
      B26  =:B26,
      B27  =:B27,
      B28  =:B28,
      B29  =:B29,
      B30  =:B30,
      B31  =:B31,
      B32  =:B32,
      B33  =:B33,
      B34  =:B34,
      B35  =:B35,
      B36  =:B36,
      B37  =:B37,
      B38  =:B38,
      B39  =:B39,
      B40  =:B40,
      B41  =:B41,
      B42  =:B42,
      B43  =:B43,
      B44  =:B44,
      B45  =:B45,
      B46  =:B46,
      B47  =:B47,
      B48  =:B48,
      B49  =:B49,
      B50  =:B50,
      B51  =:B51,
      B52  =:B52,
      B53  =:B53,
      B54  =:B54,
      B55  =:B55,
      B56  =:B56,
      B57  =:B57,
      B58  =:B58,
      B59  =:B59,
      B60  =:B60,
      B61  =:B61,
      B62  =:B62,
      B63  =:B63,
      B64  =:B64,
      B65  =:B65,
      B66  =:B66,
      B67  =:B67,
      B68  =:B68,
      B69  =:B69,
      B70  =:B70,
      B71  =:B71,
      B72  =:B72,
      B73  =:B73,
      B74  =:B74,
      B75  =:B75,
      B76  =:B76,
      B77  =:B77,
      B78  =:B78,
      B79  =:B79,
      B80  =:B80,
      B81  =:B81,
      B82  =:B82,
      B83  =:B83,
      B84  =:B84,
      B85  =:B85,
      B86  =:B86,
      B87  =:B87,
      B88  =:B88,
      B89  =:B89,
      B90  =:B90,
      B91  =:B91,
      B92  =:B92,
      B93  =:B93,
      B94  =:B94,
      B95  =:B95,
      B96  =:B96,
      B97  =:B97,
      B98  =:B98,
      B99  =:B99,
      B100  =:B100,
      ADV_DATE  =:ADV_DATE,
      SAL_DATE  =:SAL_DATE
      where (myear=:yy) and (mmonth=:mm) and (emp_ident=:emp_ident) and (dep_ident=:dep_ident);
  end
end ^
