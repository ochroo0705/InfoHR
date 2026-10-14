ALTER PROCEDURE CALC_BRANCHDEPTSAL (BRANCHID INTEGER,
DEPID INTEGER,
YEAR1 SMALLINT,
MONTH1 SMALLINT,
YEAR2 SMALLINT,
MONTH2 SMALLINT)
RETURNS (MAIN_SALARY NUMERIC(15, 2),
WSKILL_SALARY NUMERIC(15, 2),
WORKS_SALARY NUMERIC(15, 2),
B01 NUMERIC(15, 2),
B02 NUMERIC(15, 2),
B03 NUMERIC(15, 2),
B04 NUMERIC(15, 2),
B05 NUMERIC(15, 2),
B06 NUMERIC(15, 2),
B07 NUMERIC(15, 2),
B08 NUMERIC(15, 2),
B09 NUMERIC(15, 2),
B10 NUMERIC(15, 2),
B11 NUMERIC(15, 2),
B12 NUMERIC(15, 2),
B13 NUMERIC(15, 2),
B14 NUMERIC(15, 2),
B15 NUMERIC(15, 2),
B16 NUMERIC(15, 2),
B17 NUMERIC(15, 2),
B18 NUMERIC(15, 2),
B19 NUMERIC(15, 2),
B20 NUMERIC(15, 2),
B21 NUMERIC(15, 2),
B22 NUMERIC(15, 2),
B23 NUMERIC(15, 2),
B24 NUMERIC(15, 2),
B25 NUMERIC(15, 2),
B26 NUMERIC(15, 2),
B27 NUMERIC(15, 2),
B28 NUMERIC(15, 2),
B29 NUMERIC(15, 2),
B30 NUMERIC(15, 2),
B31 NUMERIC(15, 2),
B32 NUMERIC(15, 2),
B33 NUMERIC(15, 2),
B34 NUMERIC(15, 2),
B35 NUMERIC(15, 2),
B36 NUMERIC(15, 2),
B37 NUMERIC(15, 2),
B38 NUMERIC(15, 2),
B39 NUMERIC(15, 2),
B40 NUMERIC(15, 2),
B41 NUMERIC(15, 2),
B42 NUMERIC(15, 2),
B43 NUMERIC(15, 2),
B44 NUMERIC(15, 2),
B45 NUMERIC(15, 2),
B46 NUMERIC(15, 2),
B47 NUMERIC(15, 2),
B48 NUMERIC(15, 2),
B49 NUMERIC(15, 2),
B50 NUMERIC(15, 2),
B51 NUMERIC(15, 2),
B52 NUMERIC(15, 2),
B53 NUMERIC(15, 2),
B54 NUMERIC(15, 2),
B55 NUMERIC(15, 2),
B56 NUMERIC(15, 2),
B57 NUMERIC(15, 2),
B58 NUMERIC(15, 2),
B59 NUMERIC(15, 2),
B60 NUMERIC(15, 2),
B61 NUMERIC(15, 2),
B62 NUMERIC(15, 2),
B63 NUMERIC(15, 2),
B64 NUMERIC(15, 2),
B65 NUMERIC(15, 2),
B66 NUMERIC(15, 2),
B67 NUMERIC(15, 2),
B68 NUMERIC(15, 2),
B69 NUMERIC(15, 2),
B70 NUMERIC(15, 2),
B71 NUMERIC(15, 2),
B72 NUMERIC(15, 2),
B73 NUMERIC(15, 2),
B74 NUMERIC(15, 2),
B75 NUMERIC(15, 2),
B76 NUMERIC(15, 2),
B77 NUMERIC(15, 2),
B78 NUMERIC(15, 2),
B79 NUMERIC(15, 2),
B80 NUMERIC(15, 2),
B81 NUMERIC(15, 2),
B82 NUMERIC(15, 2),
B83 NUMERIC(15, 2),
B84 NUMERIC(15, 2),
B85 NUMERIC(15, 2),
B86 NUMERIC(15, 2),
B87 NUMERIC(15, 2),
B88 NUMERIC(15, 2),
B89 NUMERIC(15, 2),
B90 NUMERIC(15, 2),
B91 NUMERIC(15, 2),
B92 NUMERIC(15, 2),
B93 NUMERIC(15, 2),
B94 NUMERIC(15, 2),
B95 NUMERIC(15, 2),
B96 NUMERIC(15, 2),
B97 NUMERIC(15, 2),
B98 NUMERIC(15, 2),
B99 NUMERIC(15, 2),
B100 NUMERIC(15, 2))
AS 
declare variable TMP01 numeric(15,2);
declare variable TMP02 numeric(15,2);
declare variable TMP03 numeric(15,2);
declare variable TMP04 numeric(15,2);
declare variable TMP05 numeric(15,2);
declare variable TMP06 numeric(15,2);
declare variable TMP07 numeric(15,2);
declare variable TMP08 numeric(15,2);
declare variable TMP09 numeric(15,2);
declare variable TMP10 numeric(15,2);
declare variable TMP11 numeric(15,2);
declare variable TMP12 numeric(15,2);
declare variable TMP13 numeric(15,2);
declare variable TMP14 numeric(15,2);
declare variable TMP15 numeric(15,2);
declare variable TMP16 numeric(15,2);
declare variable TMP17 numeric(15,2);
declare variable TMP18 numeric(15,2);
declare variable TMP19 numeric(15,2);
declare variable TMP20 numeric(15,2);
declare variable TMP21 numeric(15,2);
declare variable TMP22 numeric(15,2);
declare variable TMP23 numeric(15,2);
declare variable TMP24 numeric(15,2);
declare variable TMP25 numeric(15,2);
declare variable TMP26 numeric(15,2);
declare variable TMP27 numeric(15,2);
declare variable TMP28 numeric(15,2);
declare variable TMP29 numeric(15,2);
declare variable TMP30 numeric(15,2);
declare variable TMP31 numeric(15,2);
declare variable TMP32 numeric(15,2);
declare variable TMP33 numeric(15,2);
declare variable TMP34 numeric(15,2);
declare variable TMP35 numeric(15,2);
declare variable TMP36 numeric(15,2);
declare variable TMP37 numeric(15,2);
declare variable TMP38 numeric(15,2);
declare variable TMP39 numeric(15,2);
declare variable TMP40 numeric(15,2);
declare variable TMP41 numeric(15,2);
declare variable TMP42 numeric(15,2);
declare variable TMP43 numeric(15,2);
declare variable TMP44 numeric(15,2);
declare variable TMP45 numeric(15,2);
declare variable TMP46 numeric(15,2);
declare variable TMP47 numeric(15,2);
declare variable TMP48 numeric(15,2);
declare variable TMP49 numeric(15,2);
declare variable TMP50 numeric(15,2);
declare variable TMP51 numeric(15,2);
declare variable TMP52 numeric(15,2);
declare variable TMP53 numeric(15,2);
declare variable TMP54 numeric(15,2);
declare variable TMP55 numeric(15,2);
declare variable TMP56 numeric(15,2);
declare variable TMP57 numeric(15,2);
declare variable TMP58 numeric(15,2);
declare variable TMP59 numeric(15,2);
declare variable TMP60 numeric(15,2);
declare variable TMP61 numeric(15,2);
declare variable TMP62 numeric(15,2);
declare variable TMP63 numeric(15,2);
declare variable TMP64 numeric(15,2);
declare variable TMP65 numeric(15,2);
declare variable TMP66 numeric(15,2);
declare variable TMP67 numeric(15,2);
declare variable TMP68 numeric(15,2);
declare variable TMP69 numeric(15,2);
declare variable TMP70 numeric(15,2);
declare variable TMP71 numeric(15,2);
declare variable TMP72 numeric(15,2);
declare variable TMP73 numeric(15,2);
declare variable TMP74 numeric(15,2);
declare variable TMP75 numeric(15,2);
declare variable TMP76 numeric(15,2);
declare variable TMP77 numeric(15,2);
declare variable TMP78 numeric(15,2);
declare variable TMP79 numeric(15,2);
declare variable TMP80 numeric(15,2);
declare variable TMP81 numeric(15,2);
declare variable TMP82 numeric(15,2);
declare variable TMP83 numeric(15,2);
declare variable TMP84 numeric(15,2);
declare variable TMP85 numeric(15,2);
declare variable TMP86 numeric(15,2);
declare variable TMP87 numeric(15,2);
declare variable TMP88 numeric(15,2);
declare variable TMP89 numeric(15,2);
declare variable TMP90 numeric(15,2);
declare variable TMP91 numeric(15,2);
declare variable TMP92 numeric(15,2);
declare variable TMP93 numeric(15,2);
declare variable TMP94 numeric(15,2);
declare variable TMP95 numeric(15,2);
declare variable TMP96 numeric(15,2);
declare variable TMP97 numeric(15,2);
declare variable TMP98 numeric(15,2);
declare variable TMP99 numeric(15,2);
declare variable TMP100 numeric(15,2);
declare variable TMPMAINSALARY numeric(15,2);
declare variable TMPWSKILLSALARY numeric(15,2);
declare variable TMPWORKSALARY numeric(15,2);
BEGIN
   B01=0;B02=0;B03=0;B04=0;B05=0;B06=0;B07=0;B08=0;B09=0;B10=0;B11=0;B12=0;
   B13=0;B14=0;B15=0;B16=0;B17=0;B18=0;B19=0;B20=0;B21=0;B22=0;B23=0;B24=0;
   B25=0;B26=0;B27=0;B28=0;B29=0;B30=0;B31=0;B32=0;B33=0;B34=0;B35=0;B36=0;
   B37=0;B38=0;B39=0;B40=0;B41=0;B42=0;B43=0;B44=0;B45=0;B46=0;B47=0;B48=0;
   B49=0;B50=0;B51=0;B52=0;B53=0;B54=0;B55=0;B56=0;B57=0;B58=0;B59=0;B60=0;
   B61=0;B62=0;B63=0;B64=0;B65=0;B66=0;B67=0;B68=0;B69=0;B70=0;
   B71=0;B72=0;B73=0;B74=0;B75=0;B76=0;B77=0;B78=0;B79=0;B80=0;
   B81=0;B82=0;B83=0;B84=0;B85=0;B86=0;B87=0;B88=0;B89=0;B90=0;
   B91=0;B92=0;B93=0;B94=0;B95=0;B96=0;B97=0;B98=0;B99=0;B100=0;
   MAIN_SALARY=0;WSKILL_SALARY=0;WORKS_SALARY=0;
  FOR SELECT B01,B02,B03,B04,B05,B06,B07,B08,B09,B10,B11,B12,
             B13,B14,B15,B16,B17,B18,B19,B20,B21,B22,B23,B24,
             B25,B26,B27,B28,B29,B30,B31,B32,B33,B34,B35,B36,
             B37,B38,B39,B40,B41,B42,B43,B44,B45,B46,B47,B48,
             B49,B50,B51,B52,B53,B54,B55,B56,B57,B58,B59,B60,
             B61,B62,B63,B64,B65,B66,B67,B68,B69,B70,
             B71,B72,B73,B74,B75,B76,B77,B78,B79,B80,
             B81,B82,B83,B84,B85,B86,B87,B88,B89,B90,
             B91,B92,B93,B94,B95,B96,B97,B98,B99,B100,
             MAIN_SALARY,WSKILL_SALARY,WORKS_SALARY
  FROM MONTHSALARY
  WHERE (((DEP_IDENT=:DEPID) AND (:DEPID IS NOT NULL)) OR (:DEPID IS NULL)) AND
        ((:BRANCHID IS NULL) or ((:BRANCHID IS NOT NULL) and (BRANCH_IDENT=:BRANCHID))) AND
        (MYEAR*12+MMONTH>=:YEAR1*12+:MONTH1) AND
        (MYEAR*12+MMONTH<:YEAR2*12+:MONTH2)
  INTO :TMP01,:TMP02,:TMP03,:TMP04,:TMP05,:TMP06,:TMP07,:TMP08,:TMP09,:TMP10,:TMP11,:TMP12,
       :TMP13,:TMP14,:TMP15,:TMP16,:TMP17,:TMP18,:TMP19,:TMP20,:TMP21,:TMP22,:TMP23,:TMP24,
       :TMP25,:TMP26,:TMP27,:TMP28,:TMP29,:TMP30,:TMP31,:TMP32,:TMP33,:TMP34,:TMP35,:TMP36,
       :TMP37,:TMP38,:TMP39,:TMP40,:TMP41,:TMP42,:TMP43,:TMP44,:TMP45,:TMP46,:TMP47,:TMP48,
       :TMP49,:TMP50,:TMP51,:TMP52,:TMP53,:TMP54,:TMP55,:TMP56,:TMP57,:TMP58,:TMP59,:TMP60,
       :TMP61,:TMP62,:TMP63,:TMP64,:TMP65,:TMP66,:TMP67,:TMP68,:TMP69,:TMP70,
       :TMP71,:TMP72,:TMP73,:TMP74,:TMP75,:TMP76,:TMP77,:TMP78,:TMP79,:TMP80,
       :TMP81,:TMP82,:TMP83,:TMP84,:TMP85,:TMP86,:TMP87,:TMP88,:TMP89,:TMP90,
       :TMP91,:TMP92,:TMP93,:TMP94,:TMP95,:TMP96,:TMP97,:TMP98,:TMP99,:TMP100,
       :TMPMAINSALARY,:TMPWSKILLSALARY,:TMPWORKSALARY
  DO BEGIN
    IF(TMPMAINSALARY>0)THEN MAIN_SALARY = MAIN_SALARY + TMPMAINSALARY;
    IF(TMPWSKILLSALARY>0)THEN WSKILL_SALARY = WSKILL_SALARY + TMPWSKILLSALARY;
    IF(TMPWORKSALARY>0)THEN WORKS_SALARY = WORKS_SALARY + TMPWORKSALARY;
    IF(TMP01>0)THEN B01 = B01 + TMP01;
    IF(TMP02>0)THEN B02 = B02 + TMP02;
    IF(TMP03>0)THEN B03 = B03 + TMP03;
    IF(TMP04>0)THEN B04 = B04 + TMP04;
    IF(TMP05>0)THEN B05 = B05 + TMP05;
    IF(TMP06>0)THEN B06 = B06 + TMP06;
    IF(TMP07>0)THEN B07 = B07 + TMP07;
    IF(TMP08>0)THEN B08 = B08 + TMP08;
    IF(TMP09>0)THEN B09 = B09 + TMP09;
    IF(TMP10>0)THEN B10 = B10 + TMP10;
    IF(TMP11>0)THEN B11 = B11 + TMP11;
    IF(TMP12>0)THEN B12 = B12 + TMP12;
    IF(TMP13>0)THEN B13 = B13 + TMP13;
    IF(TMP14>0)THEN B14 = B14 + TMP14;
    IF(TMP15>0)THEN B15 = B15 + TMP15;
    IF(TMP16>0)THEN B16 = B16 + TMP16;
    IF(TMP17>0)THEN B17 = B17 + TMP17;
    IF(TMP18>0)THEN B18 = B18 + TMP18;
    IF(TMP19>0)THEN B19 = B19 + TMP19;
    IF(TMP20>0)THEN B20 = B20 + TMP20;
    IF(TMP21>0)THEN B21 = B21 + TMP21;
    IF(TMP22>0)THEN B22 = B22 + TMP22;
    IF(TMP23>0)THEN B23 = B23 + TMP23;
    IF(TMP24>0)THEN B24 = B24 + TMP24;
    IF(TMP25>0)THEN B25 = B25 + TMP25;
    IF(TMP26>0)THEN B26 = B26 + TMP26;
    IF(TMP27>0)THEN B27 = B27 + TMP27;
    IF(TMP28>0)THEN B28 = B28 + TMP28;
    IF(TMP29>0)THEN B29 = B29 + TMP29;
    IF(TMP30>0)THEN B30 = B30 + TMP30;
    IF(TMP31>0)THEN B31 = B31 + TMP31;
    IF(TMP32>0)THEN B32 = B32 + TMP32;
    IF(TMP33>0)THEN B33 = B33 + TMP33;
    IF(TMP34>0)THEN B34 = B34 + TMP34;
    IF(TMP35>0)THEN B35 = B35 + TMP35;
    IF(TMP36>0)THEN B36 = B36 + TMP36;
    IF(TMP37>0)THEN B37 = B37 + TMP37;
    IF(TMP38>0)THEN B38 = B38 + TMP38;
    IF(TMP39>0)THEN B39 = B39 + TMP39;
    IF(TMP40>0)THEN B40 = B40 + TMP40;
    IF(TMP41>0)THEN B41 = B41 + TMP41;
    IF(TMP42>0)THEN B42 = B42 + TMP42;
    IF(TMP43>0)THEN B43 = B43 + TMP43;
    IF(TMP44>0)THEN B44 = B44 + TMP44;
    IF(TMP45>0)THEN B45 = B45 + TMP45;
    IF(TMP46>0)THEN B46 = B46 + TMP46;
    IF(TMP47>0)THEN B47 = B47 + TMP47;
    IF(TMP48>0)THEN B48 = B48 + TMP48;
    IF(TMP49>0)THEN B49 = B49 + TMP49;
    IF(TMP50>0)THEN B50 = B50 + TMP50;
    IF(TMP51>0)THEN B51 = B51 + TMP51;
    IF(TMP52>0)THEN B52 = B52 + TMP52;
    IF(TMP53>0)THEN B53 = B53 + TMP53;
    IF(TMP54>0)THEN B54 = B54 + TMP54;
    IF(TMP55>0)THEN B55 = B55 + TMP55;
    IF(TMP56>0)THEN B56 = B56 + TMP56;
    IF(TMP57>0)THEN B57 = B57 + TMP57;
    IF(TMP58>0)THEN B58 = B58 + TMP58;
    IF(TMP59>0)THEN B59 = B59 + TMP59;
    IF(TMP60>0)THEN B60 = B60 + TMP60;
    IF(TMP61>0)THEN B61 = B61 + TMP61;
    IF(TMP62>0)THEN B62 = B62 + TMP62;
    IF(TMP63>0)THEN B63 = B63 + TMP63;
    IF(TMP64>0)THEN B64 = B64 + TMP64;
    IF(TMP65>0)THEN B65 = B65 + TMP65;
    IF(TMP66>0)THEN B66 = B66 + TMP66;
    IF(TMP67>0)THEN B67 = B67 + TMP67;
    IF(TMP68>0)THEN B68 = B68 + TMP68;
    IF(TMP69>0)THEN B69 = B69 + TMP69;
    IF(TMP70>0)THEN B70 = B70 + TMP70;
    IF(TMP71>0)THEN B71 = B71 + TMP71;
    IF(TMP72>0)THEN B72 = B72 + TMP72;
    IF(TMP73>0)THEN B73 = B73 + TMP73;
    IF(TMP74>0)THEN B74 = B74 + TMP74;
    IF(TMP75>0)THEN B75 = B75 + TMP75;
    IF(TMP76>0)THEN B76 = B76 + TMP76;
    IF(TMP77>0)THEN B77 = B77 + TMP77;
    IF(TMP78>0)THEN B78 = B78 + TMP78;
    IF(TMP79>0)THEN B79 = B79 + TMP79;
    IF(TMP80>0)THEN B80 = B80 + TMP80;
    IF(TMP81>0)THEN B81 = B81 + TMP81;
    IF(TMP82>0)THEN B82 = B82 + TMP82;
    IF(TMP83>0)THEN B83 = B83 + TMP83;
    IF(TMP84>0)THEN B84 = B84 + TMP84;
    IF(TMP85>0)THEN B85 = B85 + TMP85;
    IF(TMP86>0)THEN B86 = B86 + TMP86;
    IF(TMP87>0)THEN B87 = B87 + TMP87;
    IF(TMP88>0)THEN B88 = B88 + TMP88;
    IF(TMP89>0)THEN B89 = B89 + TMP89;
    IF(TMP90>0)THEN B90 = B90 + TMP90;
    IF(TMP91>0)THEN B91 = B91 + TMP91;
    IF(TMP92>0)THEN B92 = B92 + TMP92;
    IF(TMP93>0)THEN B93 = B93 + TMP93;
    IF(TMP94>0)THEN B94 = B94 + TMP94;
    IF(TMP95>0)THEN B95 = B95 + TMP95;
    IF(TMP96>0)THEN B96 = B96 + TMP96;
    IF(TMP97>0)THEN B97 = B97 + TMP97;
    IF(TMP98>0)THEN B98 = B98 + TMP98;
    IF(TMP99>0)THEN B99 = B99 + TMP99;
    IF(TMP100>0)THEN B100 = B100 + TMP100;
  END
  SUSPEND;
END ^
