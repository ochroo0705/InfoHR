CREATE TRIGGER NDSH_CONFIG_BI FOR NDSH_CONFIG 
ACTIVE BEFORE INSERT POSITION 0 
as
begin
  if (new.ndsh_id is null) then
    new.ndsh_id = gen_id(gen_ndsh_config_id,1);
end ^
