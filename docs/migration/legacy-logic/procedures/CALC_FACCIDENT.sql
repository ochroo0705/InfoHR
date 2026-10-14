ALTER PROCEDURE CALC_FACCIDENT (REP_YEAR INTEGER,
ANSIREG1 INTEGER,
ANSIREG2 INTEGER)
RETURNS (FACCIDENT_ID INTEGER,
DESCRIPTION VARCHAR(35) CHARACTER SET UTF8,
FACCIDENT_TYPE VARCHAR(8) CHARACTER SET UTF8,
MASTER_ID INTEGER,
QUANTITY NUMERIC(9, 0),
FLEVEL SMALLINT)
AS 
declare variable DATE1 date;
declare variable DATE2 date;
declare variable QTY_TEMP integer;
declare variable TOTAL_TEMP integer;
declare variable CNT integer;
declare variable FDESC1 char(45);
declare variable FDESC2 char(45);
declare variable FDESC3 char(45);
begin
  select dat from CONVTODATE(:rep_year,1,1,3)
  into :date1;

  select dat from CONVTODATE(:rep_year+1,1,1,3)
  into :date2;

  if (ansireg1 is null) then
    ansireg1=0;
  
  if (ansireg2 is null) then
    ansireg2=0;

  cnt=1;
  while (cnt<3) do begin
    if (cnt=1) then begin
      fdesc1='Үйлдвэрлэлийн ослын тоо';
      fdesc2='Үйлдвэрлэлийн ослын улмаас';
      fdesc3='Үйлдвэрлэлийн осолд өртсөн хүний тоо';
      faccident_type = 'accident';
    end
    else if (cnt=2) then begin
      fdesc1='Хурц хордлогын тоо';
      fdesc2='Хурц хордлогын улмаас';
      fdesc3='Хурц хордлогод өртсөн хүний тоо';
      faccident_type = 'toxic';
    end
    qty_temp=0;

    select count(*) from factory_accident f
    where (f.accident_date>=:date1) and (f.accident_date<:date2) and (f.faccident=:faccident_type)
    into :qty_temp;
  
    faccident_id = 1+(cnt-1)*100;
    description = fdesc1;
    master_id = -1;
    flevel=1;
    if (cnt=1) then
      quantity=qty_temp + ansireg1;
    else
      quantity=qty_temp + ansireg2;
    suspend;
  
    faccident_id = 2+(cnt-1)*100;
    description = 'Бүртгэгдсэн ослын тоо';
    master_id = 1+(cnt-1)*100;
    quantity=qty_temp;
    flevel=2;
    suspend;
  
    faccident_id = 3+(cnt-1)*100;
    description = 'Бүртгэгдээгүй ослын тоо';
    master_id = 1+(cnt-1)*100;
    flevel=2;
    if (cnt=1) then
      quantity=ansireg1;
    else
      quantity=ansireg2;
    suspend;
  
    qty_temp=0;
    select count(*) from factory_accident f
    where (f.accident_date>=:date1) and (f.accident_date<:date2) and (f.faccident=:faccident_type) and (f.empid is not null)
    into :qty_temp;
  
    faccident_id = 4+(cnt-1)*100;
    description = fdesc3;
    master_id = -1;
    flevel=1;
    quantity=qty_temp;
    suspend;
  
    qty_temp=0;
    select count(*) from factory_accident f
    left join employee e on (e.employee_id=f.empid)
    where (f.accident_date>=:date1) and (f.accident_date<:date2) and (f.faccident=:faccident_type) and (e.gender='f')
    into :qty_temp;
  
    faccident_id = 5+(cnt-1)*100;
    description = 'Үүнээс: эмэгтэйчүүд';
    master_id = 4+(cnt-1)*100;
    flevel=2;
    quantity=qty_temp;
    suspend;
  
    total_temp=0;
    for select fc.faccident_type_id*10+(:cnt-1)*100, fc.description
    from factory_accident_type fc
    into :faccident_id, :description
    do begin
      select count(*)
        from factory_accident f
        where (f.faccident_type=:faccident_id) and (f.accident_date>=:date1) and
          (f.accident_date<:date2) and (f.faccident=:faccident_type) and (f.empid is not null)
      into : qty_temp;
  
      total_temp=total_temp+qty_temp;
      master_id=6+(cnt-1)*100;
      suspend;
    end
  
    faccident_id = 6+(cnt-1)*100;
    description = fdesc2;
    master_id = -1;
    flevel=1;
    quantity=total_temp;
    suspend;
  
    select count(*)
      from factory_accident f
      where (f.take_payment='yes') and (f.accident_date>=:date1) and
        (f.accident_date<:date2) and (f.faccident=:faccident_type) and (f.empid is not null)
    into : qty_temp;
  
    faccident_id = 60+(cnt-1)*100;
    description = 'нөхөн төлбөр авч байгаа хүний тоо';
    master_id = 6+(cnt-1)*100;
    flevel=2;
    quantity=qty_temp;
    suspend;
    cnt=cnt+1;
  end
end ^
