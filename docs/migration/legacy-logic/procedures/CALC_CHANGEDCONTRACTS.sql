ALTER PROCEDURE CALC_CHANGEDCONTRACTS (DATE1 TIMESTAMP,
DATE2 TIMESTAMP)
RETURNS (CONTRACT_ID INTEGER,
CONTRACT_NO VARCHAR(20) CHARACTER SET UTF8,
CONTRACT_DATE TIMESTAMP,
CONSUMSER_NAME VARCHAR(100) CHARACTER SET UTF8,
CONSUMSER_PHONE VARCHAR(20) CHARACTER SET UTF8,
CONSUMSER_REGISTER VARCHAR(20) CHARACTER SET UTF8,
NAME CHAR(25) CHARACTER SET UTF8,
SURNAME CHAR(25) CHARACTER SET UTF8,
TRANS_DATE TIMESTAMP,
PROJDETAIL_ID INTEGER,
DIFF_SUM NUMERIC(15, 2),
REASONDESC VARCHAR(500) CHARACTER SET UTF8,
PROJECT_IDENT INTEGER,
DOOR_NUMBER VARCHAR(10) CHARACTER SET UTF8,
SQUARE NUMERIC(15, 2),
SQUARE_PRICE NUMERIC(15, 2),
TOTAL NUMERIC(15, 2),
DISCOUNT_PERCENT NUMERIC(15, 2),
ROOM INTEGER,
GATEWAY VARCHAR(10) CHARACTER SET UTF8,
DESIGN_NAME VARCHAR(20) CHARACTER SET UTF8,
FLOOR_NUM SMALLINT,
GARAGE_DESIGN VARCHAR(20) CHARACTER SET UTF8,
GARAGE_DISCOUNT NUMERIC(15, 2),
GARAGE_NUMBER VARCHAR(10) CHARACTER SET UTF8,
GARAGE_PRICE NUMERIC(15, 2))
AS 
declare variable PROJDET1 integer;
declare variable PROJDET2 integer;
begin
  for select t.CONTRACT_IDENT,t.TRANS_DATE,t.PROJDETAIL_IDENT1,t.PROJDETAIL_IDENT2,t.DIFF_SUM,
    C.CONTRACT_NO,C.CONTRACT_DATE,con.name,con.phone,con.register,e.name,e.surname,r.reason_desc
  from contract_trans t
  left join contracts c on (c.contract_id=t.contract_ident)
  left join consumer con on (con.consumer_id=c.consumer_ident)
  left join employee e on ((e.employee_id=c.realtor_ident) and (e.realtor=1))
  left join reason r on (r.reason_id=t.reason_ident)
  where (t.trans_date>=:Date1) and (t.trans_date<:Date2)
  into :CONTRACT_ID,:TRANS_DATE,:PROJDET1,:PROJDET2,:DIFF_SUM,
       :CONTRACT_NO,:CONTRACT_DATE,:consumser_name,:consumser_phone,
       :consumser_register,:name,:surname,:reasondesc
  do begin
    projdetail_id=:projdet1;
    /*select p.PROJECT_IDENT,p.DOOR_NUMBER,p.SQUARE,p.SQUARE_PRICE,p.TOTAL,p.DISCOUNT_PERCENT,p.ROOM,p.GATEWAY,
      d.dname as design_name,f.floor_num,gd.dname as garage_design,cd.garage_discount,g.garage_number,g.price
    from project_detail p
    left join building_design d on (d.design_id=p.design_ident)
    left join floor f on (f.floor_id=p.floor_ident)
    left join contract_detail cd on (cd.projdetail_ident=p.projdetail_id)
    left join garage g on (g.garage_id=cd.garage_ident)
    left join building_design gd on (gd.design_id=cd.garage_ident)
    where (p.projdetail_id=:projdet1) and (cd.contract_ident=:contract_id)
    into :PROJECT_IDENT,:DOOR_NUMBER,:SQUARE,:SQUARE_PRICE,:TOTAL,:DISCOUNT_PERCENT,:ROOM,:GATEWAY,
         :design_name,:floor_num,:garage_design,:garage_discount,:garage_number,:garage_price;
    suspend;*/

    projdetail_id=:projdet2;
    select p.PROJECT_IDENT,p.DOOR_NUMBER,p.SQUARE,p.SQUARE_PRICE,p.TOTAL,p.DISCOUNT_PERCENT,p.ROOM,p.GATEWAY,
      d.dname as design_name,f.floor_num
    from project_detail p
    left join building_design d on (d.design_id=p.design_ident)
    left join floor f on (f.floor_id=p.floor_ident)
    where (p.projdetail_id=:projdet2)
    into :PROJECT_IDENT,:DOOR_NUMBER,:SQUARE,:SQUARE_PRICE,:TOTAL,:DISCOUNT_PERCENT,:ROOM,:GATEWAY,
         :design_name,:floor_num;
    suspend;
  end
end ^
