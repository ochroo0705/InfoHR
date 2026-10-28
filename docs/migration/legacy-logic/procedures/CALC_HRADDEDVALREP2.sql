ALTER PROCEDURE CALC_HRADDEDVALREP2 (EMPID INTEGER,
YY SMALLINT,
QQ SMALLINT)
RETURNS (PERC1 NUMERIC(15, 10),
PERC2 NUMERIC(15, 10),
PERC3 NUMERIC(15, 10),
AVG_PERC NUMERIC(15, 10),
KPI_PERC NUMERIC(15, 10))
AS 
declare variable BUDG1 numeric(15,10);
declare variable BUDG2 numeric(15,10);
declare variable BUDG3 numeric(15,10);
declare variable EXEC1 numeric(15,10);
declare variable EXEC2 numeric(15,10);
declare variable EXEC3 numeric(15,10);
declare variable TPERC numeric(15,10);
declare variable PERCM numeric(15,10);
begin
  perc1=0; perc2=0; perc3=0;
  if (qq=1) then begin
    for select b.budget1,b.budget2,b.budget3,b.exec1,b.exec2,b.exec3,s.percentm from hr_addedvalbudg b
    left join hr_addedvalstat s on (s.stat_id=b.stat_ident)
    where (b.emp_ident=:empid) and (b.byear=:YY)
    order by b.stat_ident
    into :budg1,:budg2,:budg3,:exec1,:exec2,:exec3,:percm
    do begin
      if (budg1<>0) then
        TPERC=exec1/budg1;
      else begin
        if (exec1=0) then
          TPERC=100;
        else
          TPERC=0;
      end
      PERC1=PERC1+TPERC*percm/100;

      if (budg2<>0) then
        TPERC=exec2/budg2;
      else begin
        if (exec2=0) then
          TPERC=100;
        else
          TPERC=0;
      end
      PERC2=PERC2+TPERC*percm/100;

      if (budg3<>0) then
        TPERC=exec3/budg3;
      else begin
        if (exec3=0) then
          TPERC=100;
        else
          TPERC=0;
      end
      PERC3=PERC3+TPERC*percm/100;
    end
  end
  if (qq=2) then begin
    for select b.budget4,b.budget5,b.budget6,b.exec4,b.exec5,b.exec6,s.percentm from hr_addedvalbudg b
    left join hr_addedvalstat s on (s.stat_id=b.stat_ident)
    where (b.emp_ident=:empid) and (b.byear=:YY)
    order by b.stat_ident
    into :budg1,:budg2,:budg3,:exec1,:exec2,:exec3,:percm
    do begin
      if (budg1<>0) then
        TPERC=exec1/budg1;
      else begin
        if (exec1=0) then
          TPERC=100;
        else
          TPERC=0;
      end
      PERC1=PERC1+TPERC*percm/100;

      if (budg2<>0) then
        TPERC=exec2/budg2;
      else begin
        if (exec2=0) then
          TPERC=100;
        else
          TPERC=0;
      end
      PERC2=PERC2+TPERC*percm/100;

      if (budg3<>0) then
        TPERC=exec3/budg3;
      else begin
        if (exec3=0) then
          TPERC=100;
        else
          TPERC=0;
      end
      PERC3=PERC3+TPERC*percm/100;
    end
  end
  if (qq=3) then begin
    for select b.budget7,b.budget8,b.budget9,b.exec7,b.exec8,b.exec9,s.percentm from hr_addedvalbudg b
    left join hr_addedvalstat s on (s.stat_id=b.stat_ident)
    where (b.emp_ident=:empid) and (b.byear=:YY)
    order by b.stat_ident
    into :budg1,:budg2,:budg3,:exec1,:exec2,:exec3,:percm
    do begin
      if (budg1<>0) then
        TPERC=exec1/budg1;
      else begin
        if (exec1=0) then
          TPERC=100;
        else
          TPERC=0;
      end
      PERC1=PERC1+TPERC*percm/100;

      if (budg2<>0) then
        TPERC=exec2/budg2;
      else begin
        if (exec2=0) then
          TPERC=100;
        else
          TPERC=0;
      end
      PERC2=PERC2+TPERC*percm/100;

      if (budg3<>0) then
        TPERC=exec3/budg3;
      else begin
        if (exec3=0) then
          TPERC=100;
        else
          TPERC=0;
      end
      PERC3=PERC3+TPERC*percm/100;
    end
  end
  if (qq=1) then begin
    for select b.budget10,b.budget11,b.budget12,b.exec10,b.exec11,b.exec12,s.percentm from hr_addedvalbudg b
    left join hr_addedvalstat s on (s.stat_id=b.stat_ident)
    where (b.emp_ident=:empid) and (b.byear=:YY)
    order by b.stat_ident
    into :budg1,:budg2,:budg3,:exec1,:exec2,:exec3,:percm
    do begin
      if (budg1<>0) then
        TPERC=exec1/budg1;
      else begin
        if (exec1=0) then
          TPERC=100;
        else
          TPERC=0;
      end
      PERC1=PERC1+TPERC*percm/100;

      if (budg2<>0) then
        TPERC=exec2/budg2;
      else begin
        if (exec2=0) then
          TPERC=100;
        else
          TPERC=0;
      end
      PERC2=PERC2+TPERC*percm/100;

      if (budg3<>0) then
        TPERC=exec3/budg3;
      else begin
        if (exec3=0) then
          TPERC=100;
        else
          TPERC=0;
      end
      PERC3=PERC3+TPERC*percm/100;
    end
  end
  avg_perc=(perc1+perc2+perc3)/3;
  if (avg_perc<80) then kpi_perc=-2;
  else if ((avg_perc>=80) and (avg_perc<85)) then kpi_perc=-1.5;
  else if ((avg_perc>=85) and (avg_perc<90)) then kpi_perc=-1;
  else if ((avg_perc>=90) and (avg_perc<95)) then kpi_perc=-0.5;
  else if ((avg_perc>=95) and (avg_perc<=100)) then kpi_perc=0;
  else if ((avg_perc>100) and (avg_perc<=105)) then kpi_perc=0.5;
  else if ((avg_perc>105) and (avg_perc<=110)) then kpi_perc=1;
  else if ((avg_perc>110) and (avg_perc<=115)) then kpi_perc=1.5;
  else if (avg_perc>115) then kpi_perc=2;
  suspend;
end ^
