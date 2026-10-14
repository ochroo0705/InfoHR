CREATE TRIGGER INSUR_COLEXPR_BI FOR INSUR_COLEXPR 
ACTIVE BEFORE INSERT POSITION 0 
as
begin
  if (new.inscolexpr_id is null) then
    new.inscolexpr_id = gen_id(gen_insur_colexpr_id,1);
end ^
