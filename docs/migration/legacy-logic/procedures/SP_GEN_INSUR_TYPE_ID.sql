ALTER PROCEDURE SP_GEN_INSUR_TYPE_ID RETURNS (ID INTEGER)
AS 
begin
  id = gen_id(gen_insur_type_id, 1);
  suspend;
end ^
