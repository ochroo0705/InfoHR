CREATE TRIGGER CONTACTING_AU0 FOR CONTACTING 
ACTIVE AFTER UPDATE POSITION 0 
AS
begin
  if (new.contacttype_ident=2) then
    update employee set homephone=new.contacting
     where employee_id=new.employee_ident ;
end ^
