CREATE TRIGGER DEPS_BU0 FOR DEPS 
ACTIVE BEFORE UPDATE POSITION 0 
AS
begin
  update employee e
  set e.schedule=new.schedule
  where e.dep_ident=new.dep_id;
end ^
