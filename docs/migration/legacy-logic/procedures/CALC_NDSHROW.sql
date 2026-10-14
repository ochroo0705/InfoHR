ALTER PROCEDURE CALC_NDSHROW (DATE1 TIMESTAMP,
DATE2 TIMESTAMP,
YY SMALLINT,
MM1 SMALLINT,
MM2 SMALLINT,
ROWNUM INTEGER)
RETURNS (NDSH_SUM1 NUMERIC(15, 2),
NDSH_SUM2 NUMERIC(15, 2),
NDSH_SUM3 NUMERIC(15, 2),
NDSH_SUM4 NUMERIC(15, 2),
NDSH_SUM5 NUMERIC(15, 2),
NDSH_SUM6 NUMERIC(15, 2),
EXPR VARCHAR(100) CHARACTER SET UTF8)
AS 
declare variable TEMPSUM numeric(15,2);
declare variable COLCODE char(4);
declare variable I integer;
declare variable REC_ACC char(12); /* HDSH-iin avlagiin dans */
declare variable PAY_ACC char(12); /* HDSH-iin uglugiin dans */
declare variable STMT varchar(5000);
begin
  IF (:DATE1 IS NULL) THEN
    SELECT DAT FROM CONVTODATE(100,1,1,3) INTO :DATE1;
  IF (:DATE2 IS NULL) THEN
    SELECT DAT FROM CONVTODATE(5941,1,1,3) INTO :DATE2;

  /*select cast(expression as char(12)) from ndsh_config
  where (rownum=1)
  into :rec_acc;
  select cast(expression as char(12)) from ndsh_config
  where (rownum=2)
  into :pay_acc;  */
  select ND7_ACC from sub_information
  into :pay_acc;


  ndsh_sum1=0;
  ndsh_sum2=0;
  ndsh_sum3=0;
  ndsh_sum4=0;
  ndsh_sum5=0;
  ndsh_sum6=0;
  if (rownum=1) then begin /* Daatguulagchiin too (Mongol) */
    select cast(count(*) as numeric(15,2)) from monthsalary m
    left join insur_type t on (t.insur_id=m.insur_ident)
    where (m.insur_ident>0) and (not t.insur_code in ('23','24')) and (t.colnum=1) and (m.myear=:yy) and (mmonth>=:mm1) and (mmonth<=:mm2)
    into :NDSH_SUM1;
    if (ndsh_sum1 is null) then ndsh_sum1=0;
    select cast(count(*) as numeric(15,2)) from monthsalary m
    left join insur_type t on (t.insur_id=m.insur_ident)
    where (m.insur_ident>0) and (not t.insur_code in ('23','24')) and (t.colnum=2) and (m.myear=:yy) and (mmonth>=:mm1) and (mmonth<=:mm2)
    into :NDSH_SUM2;
    if (ndsh_sum2 is null) then ndsh_sum2=0;
    select cast(count(*) as numeric(15,2)) from monthsalary m
    left join insur_type t on (t.insur_id=m.insur_ident)
    where (m.insur_ident>0) and (not t.insur_code in ('23','24')) and (t.colnum=3) and (m.myear=:yy) and (mmonth>=:mm1) and (mmonth<=:mm2)
    into :NDSH_SUM3;
    if (ndsh_sum3 is null) then ndsh_sum3=0;
    select cast(count(*) as numeric(15,2)) from monthsalary m
    left join insur_type t on (t.insur_id=m.insur_ident)
    where (m.insur_ident>0) and (not t.insur_code in ('23','24')) and (t.colnum=4) and (m.myear=:yy) and (mmonth>=:mm1) and (mmonth<=:mm2)
    into :NDSH_SUM4;
    if (ndsh_sum4 is null) then ndsh_sum4=0;
    select cast(count(*) as numeric(15,2)) from monthsalary m
    left join insur_type t on (t.insur_id=m.insur_ident)
    where (m.insur_ident>0) and (not t.insur_code in ('23','24')) and (t.colnum=5) and (m.myear=:yy) and (mmonth>=:mm1) and (mmonth<=:mm2)
    into :NDSH_SUM5;
    if (ndsh_sum5 is null) then ndsh_sum5=0;
  end
  else if (rownum=2) then begin /* Daatguulagchiin too (Gadaad) */
    select cast(count(*) as numeric(15,2)) from monthsalary m
    left join insur_type t on (t.insur_id=m.insur_ident)
    where (m.insur_ident>0) and (t.insur_code in ('23','24')) and (t.colnum=1) and (m.myear=:yy) and (mmonth>=:mm1) and (mmonth<=:mm2)
    into :NDSH_SUM1;
    if (ndsh_sum1 is null) then ndsh_sum1=0;
    select cast(count(*) as numeric(15,2)) from monthsalary m
    left join insur_type t on (t.insur_id=m.insur_ident)
    where (m.insur_ident>0) and (t.insur_code in ('23','24')) and (t.colnum=2) and (m.myear=:yy) and (mmonth>=:mm1) and (mmonth<=:mm2)
    into :NDSH_SUM2;
    if (ndsh_sum2 is null) then ndsh_sum2=0;
    select cast(count(*) as numeric(15,2)) from monthsalary m
    left join insur_type t on (t.insur_id=m.insur_ident)
    where (m.insur_ident>0) and (t.insur_code in ('23','24')) and (t.colnum=3) and (m.myear=:yy) and (mmonth>=:mm1) and (mmonth<=:mm2)
    into :NDSH_SUM3;
    if (ndsh_sum3 is null) then ndsh_sum3=0;
    select cast(count(*) as numeric(15,2)) from monthsalary m
    left join insur_type t on (t.insur_id=m.insur_ident)
    where (m.insur_ident>0) and (t.insur_code in ('23','24')) and (t.colnum=4) and (m.myear=:yy) and (mmonth>=:mm1) and (mmonth<=:mm2)
    into :NDSH_SUM4;
    if (ndsh_sum4 is null) then ndsh_sum4=0;
    select cast(count(*) as numeric(15,2)) from monthsalary m
    left join insur_type t on (t.insur_id=m.insur_ident)
    where (m.insur_ident>0) and (t.insur_code in ('23','24')) and (t.colnum=5) and (m.myear=:yy) and (mmonth>=:mm1) and (mmonth<=:mm2)
    into :NDSH_SUM5;
    if (ndsh_sum5 is null) then ndsh_sum5=0;
  end
  else if (rownum = 3) then begin
    I=4;
    ndsh_sum1=0;  ndsh_sum2 = 0; ndsh_sum3 = 0; ndsh_sum4 = 0; ndsh_sum5 = 0;

    colcode=null; expr = '';
    for select colcode from colnames
    where (ndsh_type=:I) and (colnames_version_id = -1)
    into :colcode
    do begin
      if (expr<>'') then
        expr = expr ||'+';
      expr = expr ||'m.'||colcode;
    end

    while (I<8) do begin
      if (expr <>'') then begin
        select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,1)
        into :ndsh_sum1;

        select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,2)
        into :ndsh_sum2;
        if (I = 3) then
        select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,3)
        into :ndsh_sum3;

        select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,4)
        into :ndsh_sum4;

        select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,5)
        into :ndsh_sum5;

      end
      I=I+1;
    end

    colcode = null;
    select colcode from colnames
    where (colstatus = 'SAL' ) and (colnames_version_id = -1)
    into :colcode;

    tempsum = 0;
    select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :colcode,1)
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    ndsh_sum1 = tempsum - ndsh_sum1;

    tempsum = 0;
    select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :colcode,2)
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    ndsh_sum2 = tempsum - ndsh_sum2;

    tempsum = 0;
    select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :colcode,3)
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    ndsh_sum3 = tempsum - ndsh_sum3;

    tempsum = 0;
    select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :colcode,4)
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    ndsh_sum4 = tempsum - ndsh_sum4;

    tempsum = 0;
    select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :colcode,5)
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    ndsh_sum5 = tempsum - ndsh_sum5;
  end
  else if ((rownum>=4) and (rownum<=7)) then begin /* Tsalingiin heseg */
    expr = ''; colcode = null;
    for select colcode from colnames
    where (ndsh_type=:rownum) and (colnames_version_id = -1)
    into :colcode
    do begin
      if (expr<>'') then
        expr = expr ||'+';
      expr = expr ||'m.'||colcode;
    end


    if (expr<>'') then begin
      tempsum=0;

      select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,1)
      into :ndsh_sum1;

      select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,2)
      into :ndsh_sum2;

      /*select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,3)
      into :ndsh_sum3; */

      select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,4)
      into :ndsh_sum4;

      select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,5)
      into :ndsh_sum5;
    end
  end
  else if (rownum=8) then begin /* Dun 8-r mur */
    colcode = null;
    select colcode from colnames
    where (colstatus = 'SAL' ) and (colnames_version_id = -1)
    into :colcode;
    expr = colcode;

    tempsum = 0;
    select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,1)
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    ndsh_sum1 = tempsum - ndsh_sum1;

    tempsum = 0;
    select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,2)
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    ndsh_sum2 = tempsum - ndsh_sum2;

    tempsum = 0;
    select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,3)
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    ndsh_sum3 = tempsum - ndsh_sum3;

    tempsum = 0;
    select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,4)
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    ndsh_sum4 = tempsum - ndsh_sum4;

    tempsum = 0;
    select amount from CALC_NDSH7_PART2(:date1,:date2,:yy,:mm1, :mm2, :expr,5)
    into :tempsum;
    if (tempsum is null) then tempsum = 0;
    ndsh_sum5 = tempsum - ndsh_sum5;

  end
  else if (rownum=9) then begin /* Dun 9-r mur */
    ndsh_sum1=21;
    ndsh_sum2=4;
    ndsh_sum3=7.5;
    ndsh_sum4=7.8;
    ndsh_sum5=0;
  end
  else if (rownum=10) then begin /* Dun 10-r mur */
    for select colcode from colnames
    where (colstatus in ('IOH','IOP','IOS','IOU','IOE','IEH','IEP','IES','IEU')) and (colnames_version_id = -1)
    into :colcode
    do begin
      /*colcodes=:colcodes||'m.'||cast(:colcode as varchar(3))||cast('+' as varchar(1));
      colcodes=:colcodes||cast('0' as varchar(1));*/

      stmt='select sum('||Upper(:colcode)||') from monthsalary m ' ||
      'left join insur_type t on (t.insur_id=m.insur_ident) '||
      'where (m.insur_ident>0) and (t.colnum=1) and (m.myear='||cast(:yy as varchar(4))||') and '||
      '(m.mmonth>='||cast(:MM1 as varchar(2))||') and (m.mmonth<='||cast(:MM2 as varchar(2))||')';
      execute statement :stmt
      into :tempsum;
      if (tempsum is null) then tempsum=0;
      ndsh_sum1=ndsh_sum1+:tempsum;

      stmt='select sum('||Upper(:colcode)||') from monthsalary m left join insur_type t on (t.insur_id=m.insur_ident) '||
      'where (m.insur_ident>0) and (t.colnum=2) and (m.myear='||cast(:yy as varchar(4))||') and (m.mmonth>='||cast(:MM1 as varchar(2))||') and (m.mmonth<='||cast(:MM2 as varchar(2))||')';
      execute statement :stmt
      into :tempsum;
      if (tempsum is null) then tempsum=0;
      if (tempsum is null) then tempsum=0;
      ndsh_sum2=ndsh_sum2+:tempsum;

      stmt='select sum('||Upper(:colcode)||') from monthsalary m left join insur_type t on (t.insur_id=m.insur_ident) '||
      'where (m.insur_ident>0) and (t.colnum=3) and (m.myear='||cast(:yy as varchar(4))||') and (m.mmonth>='||cast(:MM1 as varchar(2))||') and (m.mmonth<='||cast(:MM2 as varchar(2))||')';
      execute statement :stmt
      into :tempsum;
      if (tempsum is null) then tempsum=0;

      ndsh_sum3=ndsh_sum3+:tempsum;
      stmt='select sum('||Upper(:colcode)||') from monthsalary m left join insur_type t on (t.insur_id=m.insur_ident) '||'
      where (m.insur_ident>0) and (t.colnum=4) and (m.myear='||cast(:yy as varchar(4))||') and (m.mmonth>='||cast(:MM1 as varchar(2))||') and (m.mmonth<='||cast(:MM2 as varchar(2))||')';
      execute statement :stmt
      into :tempsum;
      if (tempsum is null) then tempsum=0;
      ndsh_sum4=ndsh_sum4+:tempsum;
      stmt='select sum('||Upper(:colcode)||') from monthsalary m left join insur_type t on (t.insur_id=m.insur_ident) '||
      'where (m.insur_ident>0) and (t.colnum=5) and (m.myear='||cast(:yy as varchar(4))||') and (m.mmonth>='||cast(:MM1 as varchar(2))||') and (m.mmonth<='||cast(:MM2 as varchar(2))||')';
      execute statement :stmt
      into :tempsum;
      if (tempsum is null) then tempsum=0;
      ndsh_sum5=ndsh_sum5+:tempsum;
    end
  end
  else if (rownum=11) then begin /* Dun 11-r mur */
    select sum(jamount) from journal
    where (dbacc_num=:pay_acc) and (craccount_type in ('10','11')) and (jdate>=:date1) and (jdate<:date2)
    into :ndsh_sum6;
    if (ndsh_sum6 is null) then ndsh_sum6=0;
  end
  else if (rownum=12) then begin /* Dun 12-r mur */
    select sum(jamount) from journal
    where (cracc_num=:pay_acc) and (dbaccount_type in ('10','11')) and (jdate>=:date1) and (jdate<:date2)
    into :ndsh_sum6;
    if (ndsh_sum6 is null) then ndsh_sum6=0;
  end
  if (rownum<11) then
    ndsh_sum6=ndsh_sum1+ndsh_sum2+ndsh_sum3+ndsh_sum4+ndsh_sum5;
  suspend;
end ^
