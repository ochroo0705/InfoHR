ALTER PROCEDURE SP_GEN_EMPLOYEE_HISTORY_ID RETURNS (ID INTEGER)
AS 
begin
  id = gen_id(gen_employee_history_id, 1);
  suspend;
end ^
