ALTER PROCEDURE CALC_EXPVC (YY SMALLINT,
MM SMALLINT,
PROJECTID INTEGER)
RETURNS (EXP_ID INTEGER,
NAME VARCHAR(500) CHARACTER SET UTF8,
PARENT_ID INTEGER,
HAS_CHILDREN SMALLINT,
SORDER INTEGER,
SLEVEL SMALLINT,
STYPE SMALLINT,
SCLASS SMALLINT,
ZORDER INTEGER,
ESUM NUMERIC(15, 2))
AS 
declare variable EXPTYPE_ID integer;
declare variable DATE1 date;
declare variable DATE2 date;
declare variable ZSUM numeric(15,2);
declare variable PSUM numeric(15,2);
declare variable TEMPSUM numeric(15,2);
declare variable DENSITY numeric(15,2);
declare variable SAL_SUM numeric(15,2);
declare variable NDSH_SUM numeric(15,2);
declare variable PROJCNT integer;
declare variable CUSTID integer;
declare variable PAYCOL char(4);
declare variable RWDCOL char(4);
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
  where (colstatus='PAY') and (colnames_version_id = -1)
  into :paycol;
  select colcode from colnames
  where (colstatus='RWD') and (colnames_version_id = -1)
  into :rwdcol;

  select sum(budget_sum) from CALC_PBUDGET(:yy,:projectid,:mm)
  where (ptype=4)
  into :DENSITY;
  if (DENSITY is null) then DENSITY=0;

  ZORDER=0;
  for select EXP_ID,NAME,PARENT_ID,HAS_CHILDREN,SORDER,SLEVEL,STYPE,SCLASS,HUMAN
  from EXP_STATEMENT
  where (stype=3)
  order by sorder
  into :EXP_ID,:NAME,:PARENT_ID,:HAS_CHILDREN,:SORDER,:SLEVEL,:STYPE,:SCLASS,:HUMAN
  do begin
    ZORDER=ZORDER+1;
    select exec_sum from CALC_PEXEC(:yy,:mm,:projectid,:EXP_ID)
    into :ESUM;
    if (:ESUM is null) then esum=0;
    if (ZORDER=1) then begin /*Niit tsalin*/
      SAL_SUM=0;
      NDSH_SUM=0;
      for select c.cust_id from customer c
      left join employee e on (e.employee_id=c.employee_ident)
      left join deps d on (d.dep_id=e.dep_ident)
      left join emp_projects p on (p.cust_ident=c.cust_id)
      where (c.employee='yes') and (d.sclass=1) and (e.realtor=1) and
            (p.pyear=:yy) and (p.pmonth=:mm) and (p.project_ident=:projectid)
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
        sal_sum=:sal_sum+:psum;
        ndsh_sum=:ndsh_sum+:sal_sum*0.11;
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
        sal_sum=:sal_sum+:psum;
        ndsh_sum=:ndsh_sum+:sal_sum*0.11;
        psum=psum+psum*0.11;
        esum=esum+psum;
      end
    end
    else if (ZORDER=2) then /*Tsalin*/
      esum=:sal_sum;
    else if (ZORDER=3) then /*NDSH*/
      esum=:ndsh_sum;
    else begin
      if (human<>1) then
        for select exptype_ident from expstat_relation
        where (exp_ident=:exp_id)
        into :EXPTYPE_ID
        do begin
          select sum(jamount) from journal
          where (jdate>=:date1) and (jdate<:date2) and (exptype_ident=:exptype_id) and (project_ident=:projectid)
          into :tempsum;
          if (tempsum is null) then tempsum=0;
          esum=esum+:tempsum;
        end
      else begin
        for select exptype_ident from expstat_relation
        where (exp_ident=:exp_id)
        into :EXPTYPE_ID
        do begin
          for select c.cust_id from customer c
          left join employee e on (e.employee_id=c.employee_ident)
          left join deps d on (d.dep_id=e.dep_ident)
          where (c.employee='yes') and (d.sclass=1) and (e.realtor<>1)
          into :custid
          do begin
            select sum(jamount) from journal
            where (jdate>=:date1) and (jdate<:date2) and (exptype_ident=:exptype_id) and (dbcust_ident=:custid) and (project_ident is null)
            into :tempsum;
            if (tempsum is null) then tempsum=0;
            esum=esum+:tempsum;
          end
        end
        if (:able_projcnt<>0) then
          esum=:esum/:able_projcnt;
        else
          esum=0;
      end
    end
    suspend;
  end
end ^
