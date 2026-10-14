ALTER PROCEDURE CALC_EMPNAME (EMP_ID INTEGER)
RETURNS (ENAME VARCHAR(30) CHARACTER SET UTF8)
AS 
begin
  select trim(name)||'. '||substring(trim(surname) from 1 for 2) from employee
  where (employee_id=:EMP_ID)
  into :ENAME;
  suspend;
end ^
