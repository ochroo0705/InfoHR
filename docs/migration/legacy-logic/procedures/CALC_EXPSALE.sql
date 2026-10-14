ALTER PROCEDURE CALC_EXPSALE (YY SMALLINT,
MM SMALLINT,
PID INTEGER)
RETURNS (EXP_ID INTEGER,
NAME VARCHAR(500) CHARACTER SET UTF8,
SORDER INTEGER,
SLEVEL SMALLINT,
STYPE SMALLINT,
SCLASS SMALLINT,
ZORDER INTEGER,
ESUM NUMERIC(15, 2))
AS 
declare variable DATE1 date;
declare variable DATE2 date;
declare variable TYPE_IDENT integer;
declare variable TEMPSUM numeric(15,2);
declare variable Z_START smallint;
declare variable TSUM numeric(15,2);
declare variable PSUM numeric(15,2);
declare variable CUSTID integer;
declare variable PROJCNT integer;
declare variable PAYCOL char(4);
declare variable RWDCOL char(4);
declare variable ZSUM numeric(15,2);
declare variable DENSITY numeric(15,2);
declare variable ABLE integer;
declare variable ABLE_PROJCNT integer;
declare variable HUMAN smallint;
begin
  SELECT DAT FROM CONVTODATE(:YY,:MM,1,3) INTO :DATE1;
  if (MM<12) then
    SELECT DAT FROM CONVTODATE(:YY,:MM+1,1,3) INTO :DATE2;
  else
    SELECT DAT FROM CONVTODATE(:YY+1,1,1,3) INTO :DATE2;

  select cnt from CALC_ACTIVEPROJCOUNT(:yy,:mm)
  into :ABLE_PROJCNT;

  select colcode from colnames
  where (colstatus='PAY') and (COLNAMES_VERSION_ID =-1)
  into :paycol;
  select colcode from colnames
  where (colstatus='RWD') and (COLNAMES_VERSION_ID =-1)
  into :rwdcol;

  select project_ident from project_dates
  where (project_ident=:pid) and (s_year<=:YY) and (s_month<=:MM) and (e_year>=:YY) and (e_month>=:MM)
  rows 1
  into :able;

  ZORDER=0;

  for select name,budget_sum from CALC_PBUDGET(:yy,:pid,:mm)
  into :NAME,:ESUM
  do begin
    if (esum is null) then esum=0;
    ZORDER=ZORDER+1;
    if (ZORDER=2) then PSUM=:ESUM;
    if (ZORDER=4) then DENSITY=:ESUM;
    if (able=0) then begin
      esum=0;
      PSUM=0;
      DENSITY=0;
    end
    suspend;
  end

  for select EXP_ID,NAME,SORDER,SLEVEL,STYPE,SCLASS from exp_statement
  where (stype>=11) and (stype<=16)
  order by sorder
  into :EXP_ID,:NAME,:SORDER,:SLEVEL,:STYPE,:SCLASS
  do begin
    ZORDER=ZORDER+1;
    esum=0;
    if (:stype=15) then ESUM=PSUM;
    if (able=0) then
      esum=0;
    suspend;
  end

  ZORDER=ZORDER+1; NAME='ГђвЂњГђЕ’ГђвЂњГўвЂљВ¬ГђвЂњГўв‚¬В°ГђвЂњГўв‚¬в„ў ГђвЂњГђвЂ№ГђвЂњГ‘вЂ™ГђвЂњГўв‚¬В№ГђвЂњГђвЂ№ГђвЂњГ‘вЂњГђвЂњГђвЂ№'; SLEVEL=1; EXP_ID=null; STYPE=null; SCLASS=null;
  TSUM=ESUM;
  suspend;

  Z_START=1;
  for select EXP_ID,NAME,SORDER,SLEVEL,STYPE,SCLASS,HUMAN from exp_statement
  where (stype=1) /*Huvisah*/
  order by sorder
  into :EXP_ID,:NAME,:SORDER,:SLEVEL,:STYPE,:SCLASS,:HUMAN
  do begin
    ZORDER=ZORDER+1;
    if (able>0) then begin
    select exec_sum from CALC_PEXEC(:yy,:mm,:pid,:EXP_ID)
    into :ESUM;
    if (:ESUM is null) then esum=0;
    if (ZORDER=13) then begin /*Tsalin*/
      for select c.cust_id from customer c
      left join employee e on (e.employee_id=c.employee_ident)
      left join deps d on (d.dep_id=e.dep_ident)
      left join emp_projects p on (p.cust_ident=c.cust_id)
      where (c.employee='yes') and (d.sclass=1) and (e.realtor=1) and
            (p.pyear=:yy) and (p.pmonth=:mm) and (p.project_ident=:pid)
      into :custid
      do begin /*Realtoruudiin tsalin*/
        select salsum from calc_colsal(:yy,:mm,:custid,:paycol)
        into :zsum;
        psum=zsum;
        select salsum from calc_colsal(:yy,:mm,:custid,:rwdcol)
        into :zsum;
        psum=psum+zsum;
        select count(*) from emp_projects
        where (cust_ident=:custid) and (pyear=:yy) and (pmonth=:mm)
        into :projcnt;
        psum=:psum/:projcnt;
        psum=psum+psum*0.11;
        esum=esum+psum;
      end
      for select c.cust_id from customer c
      left join employee e on (e.employee_id=c.employee_ident)
      left join deps d on (d.dep_id=e.dep_ident)
      where (c.employee='yes') and (d.sclass=1) and (e.realtor<>1)
      into :custid
      do begin /*Busad tsalin*/
        select salsum from calc_colsal(:yy,:mm,:custid,:paycol)
        into :zsum;
        psum=zsum;
        select salsum from calc_colsal(:yy,:mm,:custid,:rwdcol)
        into :zsum;
        psum=psum+zsum;
        /*psum=:psum*:density/100;*/
        if (:able_projcnt<>0) then
          psum=:psum/:able_projcnt;
        else
          psum=0;
        psum=psum+psum*0.11;
        esum=esum+psum;
      end
    end
    else begin
      if (human<>1) then
        for select exptype_ident from expstat_relation
        where (exp_ident=:exp_id)
        into :type_ident
        do begin
          select sum(jamount) from journal
          where (jdate>=:date1) and (jdate<:date2) and (exptype_ident=:type_ident) and (project_ident=:pid)
          into :tempsum;
          if (tempsum is null) then tempsum=0;
          esum=esum+:tempsum;
        end
      else begin
        for select exptype_ident from expstat_relation
        where (exp_ident=:exp_id)
        into :type_ident
        do begin
          for select c.cust_id from customer c
          left join employee e on (e.employee_id=c.employee_ident)
          left join deps d on (d.dep_id=e.dep_ident)
          where (c.employee='yes') and (d.sclass=1) and (e.realtor<>1)
          into :custid
          do begin
            select sum(jamount) from journal
            where (jdate>=:date1) and (jdate<:date2) and (exptype_ident=:type_ident) and (dbcust_ident=:custid) and (project_ident is null)
            into :tempsum;
            if (tempsum is null) then tempsum=0;
            esum=esum+:tempsum;
          end
        end
      end
    end
    if (Z_START=1) then begin
      TSUM=TSUM-ESUM;
      Z_START=0;
    end
    end
    else begin
      TSUM=0;
      esum=0;
    end
    suspend;
  end

  ESUM=TSUM; ZORDER=ZORDER+1; NAME='ГђвЂњГђвЂљГђвЂњГўв‚¬ВўГђвЂњГўвЂљВ¬ГђвЂњГўв‚¬Е“ГђвЂњГўв‚¬вЂњ ГђвЂњГђвЂљГђвЂњГ‚ЛњГђвЂњГўвЂљВ¬ГђвЂњГ‘вЂњ'; SLEVEL=1; EXP_ID=null; STYPE=null; SCLASS=null;
  suspend;

  Z_START=1;
  for select EXP_ID,NAME,SORDER,SLEVEL,STYPE,SCLASS,HUMAN from exp_statement
  where (stype=2)  /*Togtmol*/
  order by sorder
  into :EXP_ID,:NAME,:SORDER,:SLEVEL,:STYPE,:SCLASS,:HUMAN
  do begin
    ZORDER=ZORDER+1;
    if (able>0) then begin
    esum=0;
    if (ZORDER=23) then begin
      for select c.cust_id from customer c
      left join employee e on (e.employee_id=c.employee_ident)
      left join deps d on (d.dep_id=e.dep_ident)
      where (c.employee='yes') and (d.sclass=2)
      into :custid
      do begin /*Busad tsalin*/
        select salsum from calc_colsal(:yy,:mm,:custid,:paycol)
        into :zsum;
        psum=zsum;
        select salsum from calc_colsal(:yy,:mm,:custid,:rwdcol)
        into :zsum;
        psum=psum+zsum;
        psum=:psum*:density/100;
        psum=psum+psum*0.11;
        esum=esum+psum;
      end
    end
    else begin
        for select exptype_ident from expstat_relation
        where (exp_ident=:exp_id)
        into :type_ident
        do begin
          select sum(jamount) from journal
          where (jdate>=:date1) and (jdate<:date2) and (exptype_ident=:type_ident) and (project_ident is null)
          into :tempsum;
          if (tempsum is null) then tempsum=0;
          tempsum=tempsum*density/100;
          esum=esum+:tempsum;
        end
    end
    if (Z_START=1) then begin
      TSUM=TSUM-ESUM;
      Z_START=0;
    end
    end
    else begin
      TSUM=0;
      esum=0;
    end
    suspend;
  end
  ESUM=TSUM; ZORDER=ZORDER+1; NAME='ГђвЂњГўв‚¬вЂњГђвЂњГ‘Е“ГђвЂњГўв‚¬ЕЎГђвЂњГ‘Е“ГђвЂњГ‘вЂ™ ГђвЂњГђвЂљГђвЂњГ‚ЛњГђвЂњГўвЂљВ¬ГђвЂњГ‘вЂњ'; SLEVEL=1; EXP_ID=null; STYPE=null; SCLASS=null;
  suspend;
  ESUM=ESUM/10; ZORDER=ZORDER+1; NAME='ГђвЂњГўв‚¬в„ўГђвЂњГ‚В ГђвЂњГђвЂ ГђвЂњГ‘ЕѕГђвЂњГ‚В ГђвЂњГ‚В°'; SLEVEL=1; EXP_ID=null; STYPE=null; SCLASS=null;
  suspend;
  ESUM=TSUM-ESUM; ZORDER=ZORDER+1; NAME='ГђвЂњГўв‚¬в„ўГђвЂњГўв‚¬ЕѕГђвЂњГўв‚¬вЂњГђвЂњГђвЂљ'; SLEVEL=1; EXP_ID=null; STYPE=null; SCLASS=null;
  suspend;
end ^
