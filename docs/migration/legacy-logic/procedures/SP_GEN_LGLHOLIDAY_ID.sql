ALTER PROCEDURE SP_GEN_LGLHOLIDAY_ID RETURNS (ID INTEGER)
AS 
begin
  id = gen_id(gen_hr_legalholidays_id, 1);
  suspend;
end ^
