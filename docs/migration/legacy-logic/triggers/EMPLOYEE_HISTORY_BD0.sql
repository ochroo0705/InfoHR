CREATE TRIGGER EMPLOYEE_HISTORY_BD0 FOR EMPLOYEE_HISTORY 
ACTIVE BEFORE DELETE POSITION 0 
AS
declare variable mdate date;
declare variable mdate2 date;
declare variable WORKING_YEAR       SMALLINT;
declare variable SALARY             NUMERIC(15,2);
declare variable INWORKDATE         DATE;
declare variable G_DATE             DATE;
declare variable G_ENDDATE          DATE;
declare variable STATUS             CHAR(8);
declare variable OCCUPATION_IDENT   INTEGER;
declare variable EDUCATION_IDENT    INTEGER;
declare variable GRADUATE_IDENT     INTEGER;
declare variable DEP_IDENT          INTEGER;
declare variable WORKCONDTN         SMALLINT;
declare variable CHANGED_DATE       DATE;
declare variable COMMAND_IDENT      INTEGER;
declare variable CONTRACT_EMP       VARCHAR(12);
declare variable BRANCH_IDENT       INTEGER;
declare variable MOVE_TYPE          SMALLINT;
declare variable FIREDREASON_IDENT  INTEGER;
declare variable EMPTYPE            SMALLINT;
begin
  select max(changed_date) from employee_history
  where (employee_ident=old.employee_ident) and (isdefault<>1)
  into :mdate;
  if (:mdate=old.changed_date) then begin
    select max(changed_date) from employee_history
    where (employee_ident=old.employee_ident) and (changed_date<:mdate) and (isdefault<>1)
    into :mdate2;
    if (mdate2 is not null) then begin
      select WORKING_YEAR,SALARY,INWORKDATE,G_DATE,G_ENDDATE,STATUS,OCCUPATION_IDENT,
             EDUCATION_IDENT,GRADUATE_IDENT,DEP_IDENT,WORKCONDTN,CHANGED_DATE,EMPTYPE,
             COMMAND_IDENT,CONTRACT_EMP,BRANCH_IDENT,MOVE_TYPE,FIREDREASON_IDENT from employee_history
      where (employee_ident=old.employee_ident) and (changed_date=:mdate2) and (isdefault<>1)
      order by history_id desc
      rows 1
      into :WORKING_YEAR,:SALARY,:INWORKDATE,:G_DATE,:G_ENDDATE,:STATUS,:OCCUPATION_IDENT,
           :EDUCATION_IDENT,:GRADUATE_IDENT,:DEP_IDENT,:WORKCONDTN,:CHANGED_DATE,:EMPTYPE,
           :COMMAND_IDENT,:CONTRACT_EMP,:BRANCH_IDENT,:MOVE_TYPE,:FIREDREASON_IDENT;

      update employee set
        WORKING_YEAR=:WORKING_YEAR,
        SALARY=:SALARY,
        INWORKDATE=:INWORKDATE,
        G_DATE=:G_DATE,
        G_ENDDATE=:G_ENDDATE,
        STATUS=:STATUS,
        OCCUPATION_IDENT=:OCCUPATION_IDENT,
        EDUCATION_IDENT=:EDUCATION_IDENT,
        GRADUATE_IDENT=:GRADUATE_IDENT,
        DEP_IDENT=:DEP_IDENT,
        WORKCONDTN=:WORKCONDTN,
        CHANGED_DATE=:CHANGED_DATE,
        COMMAND_IDENT=:COMMAND_IDENT,
        CONTRACT_EMP=:CONTRACT_EMP,
        BRANCH_IDENT=:BRANCH_IDENT,
        MOVE_TYPE=:MOVE_TYPE,
        EMPTYPE=:EMPTYPE,
        FIREDREASON_IDENT=:FIREDREASON_IDENT
      where (employee_id=old.employee_ident);
      FIREDREASON_IDENT=0;
    end
  end
end ^
