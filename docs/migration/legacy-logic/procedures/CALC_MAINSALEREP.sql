ALTER PROCEDURE CALC_MAINSALEREP (DATEQ1 TIMESTAMP,
DATEQ2 TIMESTAMP,
PROJECTID INTEGER,
REALTORID INTEGER)
RETURNS (CONTRACT_ID INTEGER,
CONTRACT_NO VARCHAR(20) CHARACTER SET UTF8,
CONSUMER_IDENT INTEGER,
REALTOR_IDENT INTEGER,
CONTRACT_DATE TIMESTAMP,
CONSUMER_NAME VARCHAR(100) CHARACTER SET UTF8,
CONSUMER_PHONE VARCHAR(20) CHARACTER SET UTF8,
CONSUMER_REGISTER VARCHAR(20) CHARACTER SET UTF8,
NAME CHAR(25) CHARACTER SET UTF8,
SURNAME CHAR(25) CHARACTER SET UTF8,
DATE1 TIMESTAMP,
SUM1 NUMERIC(15, 2),
DATE2 TIMESTAMP,
SUM2 NUMERIC(15, 2),
DATE3 TIMESTAMP,
SUM3 NUMERIC(15, 2),
DATE4 TIMESTAMP,
SUM4 NUMERIC(15, 2),
DATE5 TIMESTAMP,
SUM5 NUMERIC(15, 2),
DATE6 TIMESTAMP,
SUM6 NUMERIC(15, 2),
GARAGE_NUMBER VARCHAR(10) CHARACTER SET UTF8,
GARAGE_PRICE NUMERIC(15, 2),
LOCATION_DESC VARCHAR(500) CHARACTER SET UTF8,
GARAGE_DESIGN VARCHAR(20) CHARACTER SET UTF8,
USE_DATE TIMESTAMP,
FLOOR_NUM SMALLINT,
DESIGN_NAME VARCHAR(20) CHARACTER SET UTF8,
PROJDETAIL_ID INTEGER,
DOOR_NUMBER VARCHAR(10) CHARACTER SET UTF8,
SQUARE NUMERIC(15, 2),
SQUARE_PRICE NUMERIC(15, 2),
TOTAL NUMERIC(15, 2),
DISCOUNT_PERCENT NUMERIC(15, 2),
DESIGN_IDENT INTEGER,
FLOOR_IDENT INTEGER,
GATEWAY VARCHAR(10) CHARACTER SET UTF8,
ROOM_QTY INTEGER)
AS 
declare variable DETID integer;
declare variable GARAGEID integer;
begin
  for select c.CONTRACT_ID,c.CONTRACT_NO,c.CONSUMER_IDENT,c.REALTOR_IDENT,c.CONTRACT_DATE,
    con.name,con.phone,con.register,e.name,e.surname,
    t.date1,t.sum1,t.date2,t.sum2,t.date3,t.sum3,t.date4,t.sum4,t.date5,t.sum5,t.date6,t.sum6
  from contracts c
  left join consumer con on (con.consumer_id=c.consumer_ident)
  left join employee e on ((e.employee_id=c.realtor_ident) and (e.realtor=1))
  left join CALC_CONTTRANS(c.contract_id) t on (0=0)
  where (c.contract_date>=:Dateq1) and (c.contract_date<:Dateq2) and (((:realtorid is not null) and (c.realtor_ident=:realtorid)) or (:realtorid is null))
        and (((:PROJECTID is not null) and (c.project_ident=:PROJECTID)) or (:PROJECTID is null))
  into :CONTRACT_ID,:CONTRACT_NO,:CONSUMER_IDENT,:REALTOR_IDENT,:CONTRACT_DATE,
       :consumer_name,:consumer_phone,:consumer_register,:name,:surname,
       :date1,:sum1,:date2,:sum2,:date3,:sum3,:date4,:sum4,:date5,:sum5,:date6,:sum6
  do begin
    select c.projdetail_ident from contract_detail c
    left join project_detail p on (p.projdetail_id=c.projdetail_ident)
    where (c.contract_ident=:contract_id) and (p.dtype<>4)
    rows 1
    into :detid;
    select p.use_date1,d.gateway,d.room,f.floor_num,des.dname,
      D.PROJDETAIL_ID,D.DOOR_NUMBER,D.SQUARE,D.DESIGN_IDENT,D.FLOOR_IDENT,
      D.SQUARE_PRICE,D.TOTAL,D.DISCOUNT_PERCENT
    from project_detail d
    left join floor f on (f.floor_id=d.floor_ident)
    left join building_design des on (des.design_id=d.design_ident)
    left join projects p on (p.project_id=d.project_ident)
    where (d.projdetail_id=:detid)
    into :use_date,:gateway,:room_qty,:floor_num,:Design_Name,
      :PROJDETAIL_ID,:DOOR_NUMBER,:SQUARE,:DESIGN_IDENT,:FLOOR_IDENT,
      :SQUARE_PRICE,:TOTAL,:DISCOUNT_PERCENT;

    select c.projdetail_ident from contract_detail c
    left join project_detail p on (p.projdetail_id=c.projdetail_ident)
    where (c.contract_ident=:contract_id) and (p.dtype=4)
    rows 1
    into :garageid;

    select D.DOOR_NUMBER,D.TOTAL,D.LOCATION_DESC,des.dname
    from project_detail d
    left join floor f on (f.floor_id=d.floor_ident)
    left join building_design des on (des.design_id=d.design_ident)
    left join projects p on (p.project_id=d.project_ident)
    where (d.projdetail_id=:garageid)
    into :GARAGE_NUMBER,:GARAGE_PRICE,:LOCATION_DESC,:GARAGE_DESIGN;

    suspend;
  end
end ^
