ALTER PROCEDURE CALC_FACTORYTOX (DATE1 TIMESTAMP,
DATE2 TIMESTAMP,
BRANCHID INTEGER)
RETURNS (DESCRIPTION VARCHAR(100) CHARACTER SET UTF8,
ROWNUM INTEGER,
SUM1 INTEGER,
ID INTEGER)
AS 
declare variable SDATE date;
declare variable NAME varchar(100);
declare variable I integer;
declare variable TOT integer;
declare variable ORGTYPE varchar(2);
begin
  select orgtype_code from info
  into :orgtype;

  ID=1;
  rownum=1;
  description='Ажилтны дундаж тоо';
  select count(*) from employee
  where (status='active') and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=2;
  description='Үүнээс эмэгтэй';
  select count(*) from employee
  where (status='active') and (gender='F') and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=3;
  description='Хурц хордлого гарсан тоо';
  /*select FACCIDENT,count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  group by FACCIDENT
  into :I,:sum1;*/
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=4;
  description='Үүнээс: Бүлэг хордлого';
  sum1=0;
  select FACCIDENT,count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (group_accident=1) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  group by FACCIDENT
  into :I,:sum1;
  suspend;

  ID=ID+1;
  rownum=5;
  description='Хурц хордлогод өртсөн хүний тоо';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  tot=sum1;
  suspend;

  ID=ID+1;
  rownum=6;
  description='Үүнээс эмэгтэй';
  select count(*) from factory_accident f
  left join employee e on (e.employee_id=f.empid)
  where (F.FACCIDENT='toxic') and (F.ACCIDENT_DATE>=:date1) and (F.ACCIDENT_DATE<:date2) and (e.gender='F') and ((:branchid is null) or ((:branchid is not null) and (e.branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=7;
  description='Нас барсан хүний тоо';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_result=1) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=8;
  description='Хөгжлийн бэрхшээлтэй болсон хүний тоо';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_result=2) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=9;
  description='Хөдөлмөрийн чадвар түр алдсан хүний тоо';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_result=3) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=10;
  description='Мэргэжлийн ажлаас өөр ажилд шилжсэн хүний тоо';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_result=4) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=null;
  description='Хурц хордлогын хэлбэр';
  sum1=null;
  suspend;

  ID=ID+1;
  rownum=11;
  description='Хөнгөн';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_type=3) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=12;
  description='Дунд';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_type=4) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=13;
  description='Хүнд';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_type=2) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=14;
  description='Хүний амь үрэгдсэн';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_type=1) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=null;
  description='Хурц хордлогын шалтгаан';
  sum1=null;
  suspend;

  ID=ID+1;
  rownum=15;
  description='Угаарын хий';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=1) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=16;
  description='Органик уусгагч';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=2) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=17;
  description='Пестицид';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=3) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=18;
  description='Нефтийн бүтээгдэхүүн';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=4) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=19;
  description='Аммиак';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=5) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=20;
  description='Хүчил, шүлт';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=6) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=21;
  description='Хүнд металлын нэгдэл';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=7) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=22;
  description='Цацраг идэвхит бодис';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=8) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=23;
  description='Бусад химийн бодис';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=9) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=24;
  description='Машин тоног төхөөрөмжийн гэмтэл';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=10) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=25;
  description='Тоног төхөөрөмжийн битүүмжлэл алдагдсан';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=11) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=26;
  description='Технологийн процесс зөрчсөн';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=12) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=27;
  description='Аюулгүй ажиллах арга барилд хангалтгүй сурсан';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=13) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=28;
  description='Ажлын хувцас хамгаалах хэрэгсэлгүй ажилласан';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=14) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=29;
  description='Онцгой ур чадвар шаардсан ажилд мэргэжлийн хүн ажиллуулаагүй';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=15) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=30;
  description='Бусад';
  select count(*) from factory_accident
  where (FACCIDENT='toxic') and (ACCIDENT_DATE>=:date1) and (ACCIDENT_DATE<:date2) and (facc_reason=16) and ((:branchid is null) or ((:branchid is not null) and (branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=null;
  description='Нас';
  sum1=null;
  suspend;

  ID=ID+1;
  rownum=31;
  description='18 нас хүртэл';
  select count(*) from factory_accident F
  left join employee e on (e.employee_id=f.empid)
  left join calc_age(e.birthday,f.accident_date) a on (0=0)
  where (F.FACCIDENT='toxic') and (F.ACCIDENT_DATE>=:date1) and (F.ACCIDENT_DATE<:date2) and (a.age<18) and ((:branchid is null) or ((:branchid is not null) and (f.branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=32;
  description='18-35 нас хүртэл';
  select count(*) from factory_accident F
  left join employee e on (e.employee_id=f.empid)
  left join calc_age(e.birthday,f.accident_date) a on (0=0)
  where (F.FACCIDENT='toxic') and (F.ACCIDENT_DATE>=:date1) and (F.ACCIDENT_DATE<:date2) and (a.age>=18) and (a.age<35) and ((:branchid is null) or ((:branchid is not null) and (f.branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=33;
  description='35-аас дээш';
  select count(*) from factory_accident F
  left join employee e on (e.employee_id=f.empid)
  left join calc_age(e.birthday,f.accident_date) a on (0=0)
  where (F.FACCIDENT='toxic') and (F.ACCIDENT_DATE>=:date1) and (F.ACCIDENT_DATE<:date2) and (a.age>=35) and ((:branchid is null) or ((:branchid is not null) and (f.branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=null;
  description='Ажилласан хугацаа';
  sum1=null;
  suspend;

  ID=ID+1;
  rownum=34;
  description='5 жил хүртэл';
  select count(*) from factory_accident F
  left join employee e on (e.employee_id=f.empid)
  left join calc_workedyear(e.inworkdate,f.accident_date,e.working_year) a on (0=0)
  where (F.FACCIDENT='toxic') and (F.ACCIDENT_DATE>=:date1) and (F.ACCIDENT_DATE<:date2) and (a.age<5) and ((:branchid is null) or ((:branchid is not null) and (f.branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=35;
  description='5-15 жил хүртэл';
  select count(*) from factory_accident F
  left join employee e on (e.employee_id=f.empid)
  left join calc_workedyear(e.inworkdate,f.accident_date,e.working_year) a on (0=0)
  where (F.FACCIDENT='toxic') and (F.ACCIDENT_DATE>=:date1) and (F.ACCIDENT_DATE<:date2) and (a.age>=5) and (a.age<15) and ((:branchid is null) or ((:branchid is not null) and (f.branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=36;
  description='15-аас дээш жил';
  select count(*) from factory_accident F
  left join employee e on (e.employee_id=f.empid)
  left join calc_workedyear(e.inworkdate,f.accident_date,e.working_year) a on (0=0)
  where (F.FACCIDENT='toxic') and (F.ACCIDENT_DATE>=:date1) and (F.ACCIDENT_DATE<:date2) and (a.age>=15) and ((:branchid is null) or ((:branchid is not null) and (f.branch_ident=:branchid)))
  into :sum1;
  suspend;

  ID=ID+1;
  rownum=null;
  description='Аж ахуйн нэгж, байгууллагын өмчийн хэлбэр';
  sum1=null;
  suspend;

  ID=ID+1;
  rownum=37;
  description='Төрийн болон төрийн өмч давамгайлсан';
  if (orgtype='01') then
    sum1=tot;
  else
    sum1=null;
  suspend;

  ID=ID+1;
  rownum=38;
  description='Хувийн';
  if (orgtype='02') then
    sum1=tot;
  else
    sum1=null;
  suspend;

  ID=ID+1;
  rownum=39;
  description='Төсвийн';
  if (orgtype='03') then
    sum1=tot;
  else
    sum1=null;
  suspend;

  ID=ID+1;
  rownum=40;
  description='Гадаадын болон хамтарсан хөрөнгө оруулалттай';
  if (orgtype='04') then
    sum1=tot;
  else
    sum1=null;
  suspend;
end ^
