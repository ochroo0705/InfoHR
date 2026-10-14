CREATE TRIGGER TR_EMPLOYEEID FOR EMPLOYEE 
ACTIVE BEFORE INSERT POSITION 0 
AS
BEGIN
  IF (NEW.EMPLOYEE_ID IS NULL) THEN
    NEW.EMPLOYEE_ID = GEN_ID(GEN_EMPLOYEEID,1);
  new.loginpass = new.employee_id;
  if (new.birthday is not null) then
  new.birthyear=EXTRACT(year FROM new.birthday);
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
END ^
