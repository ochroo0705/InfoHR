ALTER PROCEDURE CALC_CONTREP2_1 (DATE1 TIMESTAMP,
DATE2 TIMESTAMP,
PROJECTID INTEGER,
REALTORID INTEGER,
DATEZ1 TIMESTAMP,
DATEZ2 TIMESTAMP)
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
CONT_TOTAL NUMERIC(15, 2),
WORK_SUM NUMERIC(15, 2),
ADV_TOTAL NUMERIC(15, 2),
ADV_PERC NUMERIC(15, 2),
PAY_SUM NUMERIC(15, 2),
PAY_PERC NUMERIC(15, 2))
AS 
declare variable TOTAL numeric(15,2);
declare variable TOTAL2 numeric(15,2);
declare variable DISC numeric(15,2);
declare variable DISC2 numeric(15,2);
declare variable WPERC numeric(15,2);
begin
  for select distinct c.contract_ident from contracts cc
    left join contract_detail c on (cc.contract_id=c.contract_ident)
    left join project_detail d on (d.projdetail_id=c.projdetail_ident)
  where (cc.contract_date>=:Date1) and (cc.contract_date<:Date2)
        and (((:projectid is not null) and (d.project_ident=:projectid)) or (:projectid is null))
        and (((:realtorid is not null) and (cc.realtor_ident=:realtorid)) or (:realtorid is null))
  into :contract_id
  do begin
    select c.CONTRACT_NO,c.CONSUMER_IDENT,c.REALTOR_IDENT,c.CONTRACT_DATE,
      con.name,con.phone,con.register,e.name,e.surname
    from contracts c
    left join consumer con on (con.consumer_id=c.consumer_ident)
    left join employee e on ((e.employee_id=c.realtor_ident) and (e.realtor=1))
    where (c.contract_id=:contract_id)
    into :CONTRACT_NO,:CONSUMER_IDENT,:REALTOR_IDENT,:CONTRACT_DATE,
         :consumer_name,:consumer_phone,:consumer_register,:name,:surname;
    /*select sum(d.total),sum(d.discount_percent),sum(g.price),sum(c.garage_discount) from contract_detail c
    left join project_detail d on (d.projdetail_id=c.projdetail_ident)
    left join garage g on (g.garage_id=c.garage_ident)
    where (c.contract_ident=:contract_id)
    into :total,:disc,:total2,:disc2;*/
    if (total is null) then total=0;
    if (total2 is null) then total2=0;
    if (disc is null) then disc=0;
    if (disc2 is null) then disc2=0;
    cont_total=(:total+:total*:disc/100)+(:total2+:total2*:disc2/100);
    select avg(p.work_percent) from contract_detail c
    left join project_detail d on (d.projdetail_id=c.projdetail_ident)
    left join projects p on (p.project_id=d.project_ident)
    where (c.contract_ident=:contract_id)
    into :wperc;
    if (wperc is null) then wperc=0;
    work_sum=:cont_total*:wperc/100;
    select sum(tamount) from contract_transition
    where (contract_ident=:contract_id) and (trans_type=4)
    into :adv_total;
    if (adv_total is null) then adv_total=0;
    if (cont_total=0) then
      adv_perc=0;
    else
      adv_perc=:adv_total*100/:cont_total;
    select sum(tamount) from contract_transition
    where (contract_ident=:contract_id) and (trans_type=5) and (trans_date>=:datez1) and (trans_date<:datez2)
    into :pay_sum;
    if (pay_sum is null) then pay_sum=0;
    if (cont_total=0) then
      pay_perc=0;
    else
      pay_perc=:pay_sum*100/:cont_total;
    suspend;
  end
end ^
