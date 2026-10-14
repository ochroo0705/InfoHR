ALTER PROCEDURE EMP_MOVEMENT (EMPID INTEGER,
STS VARCHAR(10) CHARACTER SET UTF8)
AS 
begin
  if ((sts='yes') or (sts='no'))  then begin
      update employee set contract_emp=:sts, status='active'
      where employee_id=:empid ;
  end
  else begin
      update employee set status=:sts
      where employee_id=:empid ;
  end
end ^
