ALTER PROCEDURE SP_GEN_COLNAMES_VERSION_ID RETURNS (ID INTEGER)
AS 
begin
  id = gen_id(gen_colnames_version_id, 1);
  suspend;
end ^
