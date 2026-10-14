CREATE TRIGGER COLNAMES_BD0 FOR COLNAMES 
ACTIVE BEFORE DELETE POSITION 0 
AS
begin
  delete from colexpr
  where col_ident = old.col_id;
end ^
