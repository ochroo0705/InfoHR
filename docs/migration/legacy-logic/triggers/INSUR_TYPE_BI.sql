CREATE TRIGGER INSUR_TYPE_BI FOR INSUR_TYPE 
ACTIVE BEFORE INSERT POSITION 0 
as
begin
  if (new.insur_id is null) then
    new.insur_id = gen_id(gen_insur_type_id,1);
end ^
