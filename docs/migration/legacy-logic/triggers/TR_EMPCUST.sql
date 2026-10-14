CREATE TRIGGER TR_EMPCUST FOR EMPLOYEE 
ACTIVE AFTER INSERT POSITION 0 
AS
DECLARE VARIABLE address varchar(90);
begin
  if (new.hr ='yes' ) then begin
    if (new.status='active') then begin
      select  c.description||', '||d.description||', '||a.address from address a
      left join citytown c on(a.city_id=c.city_id)
      left join district d on(a.district=d.district_id)
      where a.employee_ident=new.employee_id
      into :address;
      insert into customer(employee_ident,description,code,passport,register,employee,address)
      values(new.employee_id,trim(new.name)||'.'||substring(new.surname from 1 for 1),new.ecode,new.passport,new.registerno,'yes',:address);
    end
  end
end ^
