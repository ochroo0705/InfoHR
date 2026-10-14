ALTER PROCEDURE CALC_FACTORY_ACCIDENT (REP_YEAR INTEGER,
ANSIREG1 INTEGER,
ANSIREG2 INTEGER)
RETURNS (FACCIDENT_QTY INTEGER,
REG_FACCIDENT INTEGER,
ANSIREG_ACCIDENT INTEGER,
ACCIDENT_EMPQTY INTEGER,
ACCIDENT_FEMPQTY INTEGER,
ACCIDENT_DIEDEMP INTEGER,
ACCIDENT_CRIPPLE INTEGER,
ACCIDENT_TEMPCRIPPLE INTEGER,
ACCIDENT_CHANGEOCCUP INTEGER,
ACCIDENT_DIED INTEGER,
TOXIC_QTY INTEGER,
REG_TOXIC INTEGER,
ANSIREG_TOXIC INTEGER,
TOXIC_EMPQTY INTEGER,
TOXIC_FEMPQTY INTEGER,
TOXIC_DIEDEMP INTEGER,
TOXIC_CRIPPLE INTEGER,
TOXIC_TEMPCRIPPLE INTEGER,
TOXIC_CHANGEOCCUP INTEGER,
TOXIC_DIED INTEGER,
TAKEPAYMENT_QTY INTEGER)
AS 
declare variable FIRSTDATE date;
begin
  select dat from CONVTODATE(:rep_year,1,1,3)
  into :firstdate;
  
/*-- Р В РІР‚в„ўР РЋРІР‚вЂќР В РІР‚СљР вЂ™Р’В©Р В РІР‚СљР вЂ™Р’В«Р В РІР‚СљР вЂ™Р’В¤Р В РІР‚СљР РЋРЎвЂєР В РІР‚СљР В РІР‚В¦Р В РІР‚СљР вЂ™Р’В°Р В РІР‚СљР В Р С“Р В РІР‚СљР вЂ™Р’В©Р В РІР‚СљР вЂ™Р’В­ Р В РІР‚СљР вЂ™Р’В®Р В РІР‚СљР вЂ™Р’В±Р В РІР‚СљР вЂ™Р’В®Р В РІР‚СљР вЂ™Р’В« ---    */
  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.faccident='accident')
  into :reg_faccident;

  ansireg_accident = ansireg1;
  faccident_qty = reg_faccident + ansireg_accident;

  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.faccident='accident') and (f.empid is not null)
  into :accident_empqty;

  select count(*) from factory_accident f
  left join employee e on e.employee_id=f.empid
  where (f.accident_date>=:firstdate) and (f.faccident='accident') and (e.gender='f')
  into :accident_fempqty;

  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.faccident='accident') and (f.faccident_type=1) and (f.empid is not null)
  into :accident_diedemp;

  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.faccident='accident') and (f.faccident_type=2) and (f.empid is not null)
  into :accident_cripple;

  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.faccident='accident') and (f.faccident_type=3) and (f.empid is not null)
  into :accident_tempcripple;

  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.faccident='accident') and (f.faccident_type=4) and (f.empid is not null)
  into :accident_changeoccup;

  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.faccident='accident') and (f.faccident_type=1)
  into :accident_died;

/*-- Р В РІР‚СљР вЂ™Р’ВµР В РІР‚СљР РЋРІР‚вЂњР В РІР‚СљР вЂ™Р’В°Р В РІР‚СљР вЂ™Р’В¶ Р В РІР‚СљР вЂ™Р’ВµР В РІР‚СљР вЂ™Р’В®Р В РІР‚СљР вЂ™Р’В°Р В РІР‚СљР вЂ™Р’В¤Р В РІР‚СљР вЂ™Р’В«Р В РІР‚СљР вЂ™Р’В®Р В РІР‚СљР В РІвЂљВ¬Р В РІР‚СљР вЂ™Р’В® ---  */

  select count(*) from factory_accident f
  where f.accident_date>=:firstdate and (f.faccident='toxic')
  into :reg_toxic;

  ansireg_toxic = ansireg2;
  toxic_qty = reg_toxic + ansireg_toxic;

  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.faccident='toxic') and (f.empid is not null)
  into :toxic_empqty;

  select count(*) from factory_accident f
  left join employee e on e.employee_id=f.empid
  where (f.accident_date>=:firstdate) and (f.faccident='toxic') and (e.gender='f')
  into :toxic_fempqty;

  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.faccident='toxic') and (f.faccident_type=1) and (f.empid is not null)
  into :toxic_diedemp;

  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.faccident='toxic') and (f.faccident_type=2) and (f.empid is not null)
  into :toxic_cripple;

  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.faccident='toxic') and (f.faccident_type=3) and (f.empid is not null)
  into :toxic_tempcripple;

  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.faccident='toxic') and (f.faccident_type=4) and (f.empid is not null)
  into :toxic_changeoccup;

  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.faccident='toxic') and (f.faccident_type=1)
  into :toxic_died;

/*-- Р В РІР‚СљР вЂ™Р’В­Р В РІР‚в„ўР РЋРІР‚СњР В РІР‚СљР вЂ™Р’ВµР В РІР‚в„ўР РЋРІР‚СњР В РІР‚СљР вЂ™Р’В­ Р В РІР‚СљР В РІР‚В Р В РІР‚в„ўР РЋРІР‚СњР В РІР‚СљР вЂ™Р’В«Р В РІР‚СљР В Р вЂ№Р В РІР‚в„ўР РЋРІР‚СњР В РІР‚СљР вЂ™Р’В° Р В РІР‚СљР вЂ™Р’В Р В РІР‚СљР РЋРЎвЂєР В РІР‚СљР вЂ™Р’В¤Р В РІР‚СљР вЂ™Р’В Р В РІР‚СљР В РІвЂљВ¬ ---  */

  select count(*) from factory_accident f
  where (f.accident_date>=:firstdate) and (f.take_payment = 'yes')
  into :takepayment_qty;
  
  suspend;
end ^
