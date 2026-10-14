ALTER PROCEDURE SP_GEN_INSUR_COLEXPR_ID RETURNS (ID INTEGER)
AS 
begin
  id = gen_id(gen_insur_colexpr_id, 1);
  suspend;
end ^
