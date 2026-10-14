CREATE TRIGGER MOVEMENT_AI0 FOR MOVEMENT 
ACTIVE AFTER INSERT POSITION 0 
AS
begin
  if (new.movement in ('dep','occ')) then begin
    if (new.new_emptype<>new.old_emptype) then begin
      if (new.new_emptype=1) then
        update employee set
          status='active',
          contract_emp='no'
        where (employee_id=new.emp_id);
      else if (new.new_emptype=2) then
        update employee set
          status='resource'
        where (employee_id=new.emp_id);
      else if (new.new_emptype=3) then
        update employee set
          status='inactive'
        where (employee_id=new.emp_id);
      else if (new.new_emptype=4) then
        update employee set
          status='new'
        where (employee_id=new.emp_id);
      else if (new.new_emptype=5) then
        update employee set
          contract_emp='yes'
        where (employee_id=new.emp_id);
      else if (new.new_emptype=6) then
        update employee set
          status='elder'
        where (employee_id=new.emp_id);
    end
    update employee set
      branch_ident=new.new_branchid,
      dep_ident=new.new_depid,
      occupation_ident=new.new_occupid
    where (employee_id=new.emp_id);
  end
end ^
