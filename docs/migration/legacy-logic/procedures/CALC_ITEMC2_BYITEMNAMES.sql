ALTER PROCEDURE CALC_ITEMC2_BYITEMNAMES (DATE1 TIMESTAMP,
DATE2 TIMESTAMP,
ITEMNAMEID INTEGER)
RETURNS (ITEMNAME VARCHAR(100) CHARACTER SET UTF8,
ITEMNAME_ID INTEGER,
C2_EMP1 NUMERIC(15, 10),
C2_EMP2 NUMERIC(15, 10),
C2_EMP3 NUMERIC(15, 10),
C2_EMP4 NUMERIC(15, 10),
C2_EMP5 NUMERIC(15, 10),
C2_EMP6 NUMERIC(15, 10),
C2_EMP7 NUMERIC(15, 10),
C2_EMP8 NUMERIC(15, 10),
C2_EMP9 NUMERIC(15, 10),
C2_EMP10 NUMERIC(15, 10),
C2_EMP11 NUMERIC(15, 10),
C2_EMP12 NUMERIC(15, 10),
C2_EMP13 NUMERIC(15, 10),
C2_EMP14 NUMERIC(15, 10),
C2_EMP15 NUMERIC(15, 10),
C2_EMP16 NUMERIC(15, 10),
C2_EMP17 NUMERIC(15, 10),
C2_EMP18 NUMERIC(15, 10),
C2_EMP19 NUMERIC(15, 10),
C2_EMP20 NUMERIC(15, 10))
AS 
declare variable I integer;
declare variable TEMPCACC char(12);
declare variable ACC1 char(12);
declare variable ACC2 char(12);
declare variable ACC3 char(12);
declare variable ACC4 char(12);
declare variable ACC5 char(12);
declare variable ACC6 char(12);
declare variable ACC7 char(12);
declare variable ACC8 char(12);
declare variable ACC9 char(12);
declare variable ACC10 char(12);
declare variable ACC11 char(12);
declare variable ACC12 char(12);
declare variable ACC13 char(12);
declare variable ACC14 char(12);
declare variable ACC15 char(12);
declare variable ACC16 char(12);
declare variable ACC17 char(12);
declare variable ACC18 char(12);
declare variable ACC19 char(12);
declare variable ACC20 char(12);
begin
  I = 1;
  for select c.opt_cracc from customer c
  left join employee e on (c.employee_ident = e.employee_id)
  where (c.employee = 'yes') and (e.realtor= 1)
  order by e.name
  into :tempcacc
  do begin
    if (i = 1) then
      acc1 = :tempcacc;
    else if (I = 2) then
      acc2 = :tempcacc;
    else if (I = 3) then
      acc3 = :tempcacc;
    else if (I = 4) then
      acc4 = :tempcacc;
    else if (I = 5) then
      acc5 = :tempcacc;
    else if (I = 6) then
      acc6 = :tempcacc;
    else if (I = 7) then
      acc7 = :tempcacc;
    else if (I = 8) then
      acc8 = :tempcacc;
    else if (I = 9) then
      acc9 = :tempcacc;
    else if (I = 10) then
      acc10 = :tempcacc;
    else if (I = 11) then
      acc11 = :tempcacc;
    else if (I = 12) then
      acc12 = :tempcacc;
    else if (I = 13) then
      acc13 = :tempcacc;
    else if (I = 14) then
      acc14 = :tempcacc;
    else if (I = 15) then
      acc15 = :tempcacc;
    else if (I = 16) then
      acc16 = :tempcacc;
    else if (I = 17) then
      acc17 = :tempcacc;
    else if (I = 18) then
      acc18 = :tempcacc;
    else if (I = 19) then
      acc19 = :tempcacc;
    else if (I = 20) then
      acc20 = :tempcacc;
  end

  for select itemname_id,i.description from itemnames i
  where (i.enquire_item = 1) and
        ((:ITEMNAMEID is null) or ((:ITEMNAMEID is not null) and (i.itemname_id = :ITEMNAMEID)))
  order by i.description
  into :itemname_id,:ITEMNAME
  do begin
    C2_EMP1 = 0; C2_EMP2 = 0; C2_EMP3 = 0; C2_EMP4 = 0; C2_EMP5 = 0;
    C2_EMP6 = 0; C2_EMP7 = 0; C2_EMP8 = 0; C2_EMP9 = 0; C2_EMP10 = 0;
    C2_EMP11 = 0; C2_EMP12 = 0; C2_EMP13 = 0; C2_EMP14 = 0; C2_EMP15 = 0;
    C2_EMP16 = 0; C2_EMP17 = 0; C2_EMP18 = 0; C2_EMP19 = 0; C2_EMP20 = 0;
    if (acc1 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc1)
      into :C2_EMP1;
    end

    if (acc2 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc2)
      into :C2_EMP2;
    end

    if (acc3 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc3)
      into :C2_EMP3;
    end
    if (acc4 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc4)
      into :C2_EMP4;
    end
    if (acc5 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc5)
      into :C2_EMP5;
    end
    if (acc6 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc6)
      into :C2_EMP6;
    end
    if (acc7 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc7)
      into :C2_EMP7;
    end
    if (acc8 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc8)
      into :C2_EMP8;
    end
    if (acc9 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc9)
      into :C2_EMP9;
    end
    if (acc10 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc10)
      into :C2_EMP10;
    end
    if (acc11 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc11)
      into :C2_EMP11;
    end
    if (acc12 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc12)
      into :C2_EMP12;
    end
    if (acc13 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc13)
      into :C2_EMP13;
    end
    if (acc14 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc14)
      into :C2_EMP14;
    end
    if (acc15 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc15)
      into :C2_EMP15;
    end
    if (acc16 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc16)
      into :C2_EMP16;
    end
    if (acc17 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc17)
      into :C2_EMP17;
    end
    if (acc18 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc18)
      into :C2_EMP18;
    end
    if (acc19 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc19)
      into :C2_EMP19;
    end
    if (acc20 is null) then begin
      select Sum(c.c2qty) as c2qty from item i
      left join calc_itempricebal(i.item_id,null,:date2,null,null) c on (0=0)
      where (i.itemname_ident=:itemname_id) and (i.asset_acc=:acc20)
      into :C2_EMP20;
    end


  end


  suspend;
end ^
