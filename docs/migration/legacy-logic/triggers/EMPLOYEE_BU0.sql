CREATE TRIGGER EMPLOYEE_BU0 FOR EMPLOYEE 
ACTIVE BEFORE UPDATE POSITION 0 
AS
begin
  if (new.emptype<>old.emptype) then begin
    if (new.emptype=1) then begin
      new.status='active';
      new.contract_emp='no';
      new.wagetest_emp=null;
    end
    if (new.emptype=2) then begin
      new.status='resource';
      new.contract_emp='no';
      new.wagetest_emp=null;
    end
    if (new.emptype=3) then begin
      new.status='inactive';
      new.contract_emp='no';
      new.wagetest_emp=null;
    end
    if (new.emptype=4) then begin
      new.status='new';
      new.contract_emp='no';
      new.wagetest_emp=null;
    end
    if (new.emptype=5) then begin
      new.status='active';
      new.contract_emp='yes';
      new.wagetest_emp=null;
    end
    if (new.emptype=6) then begin
      new.status='elder';
      new.contract_emp='no';
      new.wagetest_emp=null;
    end
    if (new.emptype=8) then begin
      new.status='active';
      new.contract_emp='no';
      new.wagetest_emp=1;
    end
    if (new.emptype=9) then begin
      new.status='active';
      new.contract_emp='no';
      new.wagetest_emp=2;
    end
  end
end ^
