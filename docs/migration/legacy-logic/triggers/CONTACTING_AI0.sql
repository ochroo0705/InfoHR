CREATE TRIGGER CONTACTING_AI0 FOR CONTACTING 
ACTIVE AFTER INSERT POSITION 0 
AS
begin
  if (new.contacttype_ident=4) then
    update employee set email=new.contacting
     where employee_id=new.employee_ident;
  if (new.contacttype_ident=2) then
    update employee set homephone=new.contacting
     where employee_id=new.employee_ident ;
end ^
