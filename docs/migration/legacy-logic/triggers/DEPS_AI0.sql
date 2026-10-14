CREATE TRIGGER DEPS_AI0 FOR DEPS 
ACTIVE AFTER INSERT POSITION 0 
AS
begin
  update employee e
  set e.schedule=new.schedule
  where e.dep_ident=new.dep_id;
end ^
