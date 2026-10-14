ALTER PROCEDURE UPDATE_REGISTER AS 
declare variable EMPID integer;
declare variable REG char(10);
begin
  for select c.employee_ident, c.register from customer c
      where c.employee='yes'
      into :empid,reg
  do begin
    update employee e set e.registerno=:reg where e.employee_id=:empid;
  end
end ^
