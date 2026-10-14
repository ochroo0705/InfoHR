ALTER PROCEDURE CALC_INCOME (STATUS VARCHAR(8) CHARACTER SET UTF8)
RETURNS (DEP_ID INTEGER,
DEP VARCHAR(25) CHARACTER SET UTF8,
OCCUP VARCHAR(100) CHARACTER SET UTF8,
FULLNAME VARCHAR(30) CHARACTER SET UTF8,
INC INTEGER,
LEVEL_ID INTEGER,
INC_LEVEL VARCHAR(20) CHARACTER SET UTF8,
DIV_QTY INTEGER,
FAMILY_QTY INTEGER,
EMPID INTEGER,
BRANCHNAME CHAR(25) CHARACTER SET UTF8)
AS 
declare variable SAL integer;
declare variable NAME varchar(25);
declare variable SURNAME varchar(25);
begin
  for select e.employee_id, e.name, e.surname, e.income,e.salary, d.dep_id,d.name, o.description, b.description
      from employee e
      left join deps d on (e.dep_ident=d.dep_id)
      left join occupation o on (e.occupation_ident=o.occupation_id)
      left join branch b on (e.branch_ident=b.branch_id)
      where (:status is null) or ((:status is not null) and (e.status=:status))
      order by d.name, e.name, e.surname
      into :empid,:name,:surname,:inc,:sal, :dep_id,:dep,:occup,:branchname
  do begin
      fullname = substring(:surname from 1 for 1)||'.'||trim(:name);

      select count(*) from family f
      where f.employee_ident=:empid
      into :family_qty;

      if (:family_qty is null)  then
        family_qty=0;
      family_qty=family_qty+1;

      if ((:inc is null) or (:inc=0)) then
        if ((:sal<>0) or (:sal is null))  then begin
            inc=sal;
            div_qty=inc/family_qty;
        end
        else begin
            div_qty=0;
            inc=0;
        end
      else
        div_qty=inc/family_qty;

      select i.income_id, i.income_level from income i
      where i.c1<:div_qty and i.c2>=:div_qty
      into :level_id,:inc_level;
    suspend;
  end
end ^
