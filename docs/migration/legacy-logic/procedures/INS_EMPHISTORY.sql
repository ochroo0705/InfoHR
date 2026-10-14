ALTER PROCEDURE INS_EMPHISTORY (EMPID INTEGER)
AS 
declare variable HISTORYID integer;
begin
  HISTORYID=gen_id(gen_employee_history_id,1);
  insert into employee_history (history_id,employee_ident, name, surname, post, birthday, emdno, ndno, working_year, salary, inworkdate, g_date, g_enddate, homephone, workphone, calctype, status, manager_exp, occupation_ident, gender, education_ident, graduate_ident, ecode, bycard, email, register,   passport, inworknumber, address, ndsh_deps, hoat_deps, fired_number, fired_date, fired_ident, dep_ident, s_ident, bonus, workcondtn, country_ident, country1_ident, Changed_date, COMAND_NO, COMMAND_IDENT, MOVE_TYPE, EMPTYPE, branch_ident, firedreason_ident,CONTRACT_EMP,FOREIGN_EMP,WAGETEST_EMP)
                         select :HISTORYID,   employee_id, name, surname, post, birthday, emdno, ndno, working_year, salary, inworkdate, g_date, g_enddate, homephone, workphone, calctype, status, manager_exp, occupation_ident, gender, education_ident, graduate_ident, ecode, bycard, email, registerno, passport, null,         null,    null,      null,      null,         null,       null,        dep_ident, null,    null,  workcondtn, null,          null,           changed_date, null,      COMMAND_IDENT, MOVE_TYPE, EMPTYPE, branch_ident, firedreason_ident,CONTRACT_EMP,FOREIGN_EMP,WAGETEST_EMP
  from employee where (employee_id=:empid);
end ^
